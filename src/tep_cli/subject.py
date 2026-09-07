"""Subject-first commands: repo / actor / project / align."""

from __future__ import annotations

import json
import os
import re
import sys
from argparse import Namespace
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tep_cli.output import emit
from tep_core.actor_artifacts import (
    ActorArtifactError,
    build_actor_artifacts,
    write_actor_artifacts,
)
from tep_core.actor_directory import actor_report_from_card
from tep_core.analyze import prepare_inputs
from tep_core.analyze_v2 import analyze_subject
from tep_core.alignment import alignment_payload
from tep_core.attribution import build_attribution_index, find_actor, synthetic_identity
from tep_core.digest import file_digest
from tep_core.gitutil import coauthor_shas, raw_remote_url, remote_url, rev_parse
from tep_core.forge_public import ForgeLocator, GitObjectId, parse_forge_locator
from tep_core.public_fetch import collect_public_handles, load_public_handles
from tep_core.public_evidence import (
    not_requested_manifest,
    read_fixed_history_oids,
    reconcile_commit_coverage,
    manifest_fetched_login_count,
    verify_public_evidence,
)
from tep_core.identity import (
    ActorSelectionError,
    IdentityValidationError,
    actor_ids,
    load_identity,
    load_subject_identity,
    select_actor,
)
from tep_core.lineage import Lineage
from tep_core.project import (
    build_project_report,
    declared_view,
    empty_declared,
    init_project_template,
    load_project_toml,
)
from tep_core.report import render_markdown
from tep_core.revision import RevisionError, fixed_revision_worktree
from tep_core.schema_v2 import validate_alignment, validate_project, validate_report_v2
from tep_core.secrets_guard import InputValidationError, artifact_leaks
from tep_core.actor_basis import (
    actor_analysis_scope,
    actor_basis_notice,
    classify_actor_basis,
)
from tep_core.v2_constants import (
    ALIGNMENT_NOTICE,
    EVIDENCE_DISCLAIMER,
    FORGE_NOT_OBSERVED_NOTE,
    PROJECT_OBSERVED_MISSING_NOTE,
    TRACKER_NOT_OBSERVED_NOTE,
)
from tep_core.version import DEFINITION_VERSION, __version__


def _is_git(repo: Path) -> bool:
    return (repo / ".git").exists() or repo.joinpath("HEAD").exists()


def _lineage(args: Namespace) -> Lineage:
    return Lineage(
        is_fork=bool(getattr(args, "fork", False)), parent=getattr(args, "parent", "") or None
    )


def _fail(message: str, code: int = 2) -> int:
    sys.stderr.write(message if message.endswith("\n") else message + "\n")
    return code


def _validate_as_of(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise InputValidationError("--as-of must be YYYY-MM-DD")
    return value


def _event_window(args: Namespace) -> tuple[str, str] | None:
    raw = getattr(args, "event_window", None)
    if not raw:
        return None
    start, end = raw
    _validate_as_of(start)
    _validate_as_of(end)
    if start >= end:
        raise InputValidationError("--event-window START must be earlier than END")
    return start, end


def _load_json_report(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"report unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputValidationError(f"report must be an object: {path}")
    return payload


class PublicEvidenceError(ValueError):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PublicEvidenceState:
    manifest: dict
    locator: ForgeLocator | None
    reconciliation: dict
    requested: bool
    exit_code: int = 0

    @property
    def account_mapping(self) -> dict | None:
        if (
            not self.requested
            or self.exit_code == 1
            or self.manifest.get("account_linkage") == "unsupported"
        ):
            return None
        value = self.manifest.get("sha_to_account")
        return value if isinstance(value, dict) else None

    @property
    def digest(self) -> str | None:
        if not self.requested:
            return None
        value = self.manifest.get("bundle_payload_sha256")
        return value if isinstance(value, str) else None

    def coverage_observation(self) -> dict:
        status = str((self.manifest.get("coverage") or {}).get("status") or "not_requested")
        if not self.requested:
            return {"kind": "not_observed", "reason": "public_evidence_not_provided"}
        common = {
            "status": status,
            "unit": "coverage_status",
            "expected_count": self.reconciliation.get("expected_count"),
            "observed_count": self.reconciliation.get("observed_count"),
            "missing_count": len(self.reconciliation.get("missing") or []),
            "extra_count": len(self.reconciliation.get("extra") or []),
            "duplicate_count": len(self.reconciliation.get("duplicates") or []),
            "account_linkage": self.manifest.get("account_linkage"),
        }
        if status == "complete" and self.reconciliation.get("status") == "complete":
            return {"kind": "observed", "value": status, **common}
        return {
            "kind": "not_proven",
            "reason": "public_evidence_incomplete_or_mismatched",
            **common,
        }


def _locator_from_manifest(manifest: dict) -> ForgeLocator:
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise PublicEvidenceError("public evidence source is missing", 1)
    try:
        return ForgeLocator(
            provider=str(source["provider"]),
            host=str(source["host"]),
            project_path=str(source["project_path"]),
            api_base=str(source["api_base"]),
            sanitized_remote=str(source["sanitized_remote"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicEvidenceError(f"public evidence source is invalid: {exc}", 1) from exc


def _auth_token(args: Namespace) -> str | None:
    name = getattr(args, "auth_token_env", None)
    if name is None:
        return None
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)) is None:
        raise PublicEvidenceError("--auth-token-env must be an environment variable name", 2)
    value = os.environ.get(str(name))
    if not value:
        raise PublicEvidenceError(f"--auth-token-env {name!r} is unset or empty", 2)
    return value


def _public_evidence(repo: Path, args: Namespace) -> PublicEvidenceState:
    fixed = getattr(args, "_fixed_revision", None)
    if fixed is None:
        raise PublicEvidenceError("fixed revision context is missing", 2)
    target = GitObjectId(**fixed.oid)
    raw_remote = raw_remote_url(repo)
    fetch = bool(getattr(args, "fetch_public", False))
    replay_dir = getattr(args, "public_evidence", None)
    resume_dir = getattr(args, "resume_public_evidence", None)
    requested = fetch or replay_dir is not None or resume_dir is not None
    evidence_out = getattr(args, "public_evidence_out", None)
    max_pages_arg = getattr(args, "max_public_pages", None)
    token_name = getattr(args, "auth_token_env", None)
    if not requested:
        if evidence_out is not None or max_pages_arg is not None or token_name is not None:
            raise PublicEvidenceError(
                "public evidence options require --fetch-public or --resume-public-evidence", 2
            )
        if raw_remote is None:
            return PublicEvidenceState(
                manifest={"coverage": {"status": "not_requested"}},
                locator=None,
                reconciliation={"status": "not_requested"},
                requested=False,
            )
        try:
            locator = parse_forge_locator(
                raw_remote,
                provider=getattr(args, "forge_provider", "auto"),
                api_base=getattr(args, "forge_api_base", None),
            )
        except ValueError:
            return PublicEvidenceState(
                manifest={"coverage": {"status": "not_requested"}},
                locator=None,
                reconciliation={"status": "not_requested"},
                requested=False,
            )
        return PublicEvidenceState(
            manifest=not_requested_manifest(locator, target),
            locator=locator,
            reconciliation={"status": "not_requested"},
            requested=False,
        )

    if replay_dir is not None:
        if evidence_out is not None or token_name is not None or max_pages_arg is not None:
            raise PublicEvidenceError(
                "--public-evidence is offline and rejects fetch/token/pagination output options", 2
            )
        verification = verify_public_evidence(replay_dir)
        status = verification.get("status")
        if status != "VERIFIED":
            code = 1 if status == "MISMATCH" else 2
            raise PublicEvidenceError(
                "public evidence replay failed: "
                + str(verification.get("reason") or status or "unknown"),
                code,
            )
        manifest = load_public_handles(replay_dir)
        locator = _locator_from_manifest(manifest)
    else:
        if raw_remote is None:
            raise PublicEvidenceError("public fetch requires an origin remote", 2)
        try:
            locator = parse_forge_locator(
                raw_remote,
                provider=getattr(args, "forge_provider", "auto"),
                api_base=getattr(args, "forge_api_base", None),
            )
        except ValueError as exc:
            raise PublicEvidenceError(f"cannot resolve Forge provider: {exc}", 2) from exc
        if fetch:
            if evidence_out is None:
                raise PublicEvidenceError(
                    "--fetch-public requires --public-evidence-out so the response is replayable", 2
                )
            bundle = evidence_out
            resume = False
        else:
            if evidence_out is not None:
                raise PublicEvidenceError(
                    "--resume-public-evidence uses its directory in place; omit --public-evidence-out",
                    2,
                )
            bundle = resume_dir
            resume = True
        try:
            manifest = collect_public_handles(
                raw_remote,
                fetch=True,
                head_sha=target.value,
                max_pages=max_pages_arg or 100,
                provider=locator.provider,
                api_base=locator.api_base,
                auth_token=_auth_token(args),
                evidence_out=bundle,
                resume=resume,
            )
        except FileExistsError as exc:
            raise PublicEvidenceError(str(exc), 2) from exc
        except (OSError, ValueError) as exc:
            raise PublicEvidenceError(f"public evidence collection failed: {exc}", 1) from exc

    if manifest.get("target_oid") != target.to_dict():
        raise PublicEvidenceError("public evidence target_oid does not match --rev", 1)
    if raw_remote is not None:
        try:
            current = parse_forge_locator(
                raw_remote,
                provider=locator.provider,
                api_base=locator.api_base,
            )
        except ValueError as exc:
            raise PublicEvidenceError(f"cannot bind public evidence to current remote: {exc}", 2)
        if current.sanitized_remote != locator.sanitized_remote:
            raise PublicEvidenceError("public evidence source does not match the current origin", 1)
    history = read_fixed_history_oids(repo, target)
    reconciliation = reconcile_commit_coverage(manifest, history)
    state_status = reconciliation.get("status")
    if state_status == "mismatch":
        exit_code = 1
    elif state_status == "partial" or (manifest.get("coverage") or {}).get("status") != "complete":
        exit_code = 3
    else:
        exit_code = 0
    return PublicEvidenceState(manifest, locator, reconciliation, True, exit_code)


def _sha_to_login(handles: dict) -> dict | None:
    if handles.get("source_type") != "forge_api":
        return None
    mapping = handles.get("sha_to_login")
    return mapping if isinstance(mapping, dict) else None


def _manifest_login_count(handles: dict) -> int | None:
    """Contributors endpoint login-list size. Distinct from any SHA join."""
    if handles.get("source_type") != "forge_api":
        return None
    count = handles.get("fetched_login_count")
    return count if isinstance(count, int) else None


def _attribution_index(repo: Path, identity, args: Namespace, evidence: PublicEvidenceState):
    from tep_core.attribution import derive_repo_scope_digest, read_mailmap_at_revision

    commits, origin = prepare_inputs(repo, identity, _lineage(args), include_files=True)
    canonical_origin = (
        evidence.locator.sanitized_remote if evidence.locator is not None else remote_url(repo)
    )
    scope_digest, _object_format = derive_repo_scope_digest(commits, canonical_origin)
    mailmap = read_mailmap_at_revision(repo, rev_parse(repo))
    return (
        commits,
        origin,
        build_attribution_index(
            commits,
            origin,
            identity,
            sha_to_accounts=evidence.account_mapping,
            fetched_login_count=_manifest_account_count(evidence.manifest),
            mailmap=mailmap,
            mailmap_present=mailmap.present,
            coauthor_shas=coauthor_shas(repo),
            repo_scope_digest=scope_digest,
            canonical_origin=canonical_origin,
        ),
    )


def _manifest_account_count(manifest: dict) -> int | None:
    return manifest_fetched_login_count(manifest)


def _artifact_account_evidence(manifest: dict, index: object) -> dict[str, list[str]]:
    """Invert recorded commit/account links without inventing provider evidence."""

    result: dict[str, list[str]] = {}
    mapping = manifest.get("sha_to_account")
    if isinstance(mapping, dict):
        for oid, raw in mapping.items():
            rows = raw if isinstance(raw, list) else [raw]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                provider = str(row.get("provider") or "")
                host = str(row.get("host") or "")
                account_id = str(row.get("account_id") or "")
                if provider and host and account_id:
                    result.setdefault("|".join((provider, host, account_id)), []).append(str(oid))
    for actor in getattr(index, "actors", ()):
        for account in actor.public_accounts:
            if "identity_declared" not in str(account.evidence or ""):
                continue
            key = "|".join((account.provider, account.host, account.account_id))
            result.setdefault(key, []).extend(actor.commit_shas)
    return {key: sorted(set(values)) for key, values in sorted(result.items())}


def _artifact_account_statuses(evidence: PublicEvidenceState, index: object) -> dict[str, str]:
    actors = getattr(index, "actors", ())
    if not evidence.requested:
        return {}
    if evidence.locator is not None and evidence.locator.provider == "gitlab":
        return {actor.actor_id: "unsupported" for actor in actors}
    coverage = (evidence.manifest.get("coverage") or {}).get("status")
    if coverage != "complete":
        return {actor.actor_id: "unavailable" for actor in actors if not actor.public_accounts}
    return {}


def _collection_destination(out: Path | None) -> Path | None:
    if out is None:
        return None
    if out.exists():
        raise ActorArtifactError(
            "actor collection --out must name a new directory; refusing to replace existing data"
        )
    if out.suffix:
        raise ActorArtifactError("actor collection --out must name a directory, not a file")
    return out


def _actor_out_requests_collection(out: Path | None) -> bool:
    """Keep explicit report file output while making directory output strict.

    A named JSON/Markdown file remains the compatibility path for the detailed
    tenant report.  A directory is a v0.6 actor collection and therefore must
    be new, closed, and independently verifiable.
    """

    if out is None:
        return False
    if out.exists():
        if out.is_file() and out.suffix.lower() not in {".json", ".md"}:
            raise ActorArtifactError(
                "explicit actor report files must end in .json or .md; "
                "use a suffix-free new directory for a strict collection"
            )
        return out.is_dir()
    suffix = out.suffix.lower()
    if suffix == ".toml":
        raise ActorArtifactError(
            "explicit actor report files must end in .json or .md; .toml output is not supported"
        )
    return suffix not in {".json", ".md"}


def _refuse_leaks(text: str, *, allow_path: bool) -> str | None:
    leaks = artifact_leaks(text)
    if allow_path:
        leaks = [item for item in leaks if item != "absolute path"]
    if leaks:
        return "refusing to emit leaked fields: " + ", ".join(leaks)
    return None


def run_repo(args: Namespace) -> int:
    source = args.repo if args.repo is not None else Path(".")
    if not _is_git(source):
        return _fail(f"not a git repository: {source}")
    try:
        with fixed_revision_worktree(source, getattr(args, "rev", None)) as fixed:
            routed = copy(args)
            routed.repo = fixed.worktree
            routed._source_repo = source.resolve()
            routed._fixed_revision = fixed
            return _run_repo_fixed(routed)
    except RevisionError as exc:
        return _fail(f"cannot resolve fixed revision: {exc}")


def _run_repo_fixed(args: Namespace) -> int:
    repo = args.repo if args.repo is not None else Path(".")
    if not _is_git(repo):
        return _fail(f"not a git repository: {repo}")
    try:
        as_of = _validate_as_of(getattr(args, "as_of", None))
        identity = load_subject_identity(
            repo,
            getattr(args, "identity", None),
            revision=args._fixed_revision.oid["value"],
        )
        evidence = _public_evidence(repo, args)
        canonical_origin = (
            evidence.locator.sanitized_remote if evidence.locator is not None else remote_url(repo)
        )
        report = analyze_subject(
            repo,
            identity,
            _lineage(args),
            repository_source=getattr(args, "_source_repo", repo),
            subject_kind="repo",
            as_of=as_of,
            role_lens=getattr(args, "role_lens", None),
            forge_export=getattr(args, "forge_export", None),
            tracker_export=getattr(args, "tracker_export", None),
            outcome_declaration=getattr(args, "outcome_declaration", None),
            reference_version=getattr(args, "reference_version", None),
            template_provided=getattr(args, "template", None) is not None,
            parent_repo_provided=getattr(args, "parent_repo", None) is not None,
            include_files=bool(getattr(args, "vendor_scan", False)),
            include_local_path=bool(getattr(args, "include_local_path", False)),
            survival=bool(getattr(args, "survival", False)),
            reference_id=getattr(args, "reference", None),
            reference_manifest=getattr(args, "reference_manifest", None),
            event_window=_event_window(args),
            sha_to_accounts=evidence.account_mapping,
            fetched_login_count=_manifest_account_count(evidence.manifest),
            canonical_origin=canonical_origin,
            public_evidence_digest=evidence.digest,
            public_evidence_coverage=evidence.coverage_observation(),
            target_oid=args._fixed_revision.oid,
            revision_completeness={
                "shallow": args._fixed_revision.shallow,
                "promisor": args._fixed_revision.promisor,
                "complete": args._fixed_revision.completeness_proven,
            },
        )
        errors = validate_report_v2(report)
        if errors:
            return _fail("report-v2 validation failed:\n" + "\n".join(errors))
        markdown = render_markdown(report)
        leaked = _refuse_leaks(
            markdown + json.dumps(report),
            allow_path=bool(getattr(args, "include_local_path", False)),
        )
        if leaked:
            return _fail(leaked)
        if getattr(args, "actors", False):
            _commits, _origin, index = _attribution_index(repo, identity, args, evidence)
            artifacts = build_actor_artifacts(
                index,
                report,
                selection_mode="all",
                account_evidence=_artifact_account_evidence(evidence.manifest, index),
                account_status_overrides=_artifact_account_statuses(evidence, index),
            )
            destination = _collection_destination(args.out)
            if destination is not None:
                write_actor_artifacts(destination, artifacts)
            emit(
                markdown=artifacts.repo_markdown,
                payload=artifacts.repo_report,
                fmt=args.format,
                out=None,
                artifact="repo",
            )
        else:
            emit(
                markdown=markdown,
                payload=report,
                fmt=args.format,
                out=args.out,
                artifact="repo",
            )
        return evidence.exit_code
    except PublicEvidenceError as exc:
        return _fail(str(exc), exc.code)
    except (ActorArtifactError, InputValidationError, IdentityValidationError, ValueError) as exc:
        return _fail(str(exc))


def _run_actor_collection(
    args: Namespace,
    repo: Path,
    *,
    identity_override=None,
    evidence_override: PublicEvidenceState | None = None,
    selection_mode: str | None = None,
    actor_ids_override: list[str] | None = None,
    actor_details: dict[str, dict] | None = None,
) -> int:
    try:
        as_of = _validate_as_of(getattr(args, "as_of", None))
        identity = (
            identity_override
            if identity_override is not None
            else load_subject_identity(
                repo,
                getattr(args, "identity", None),
                revision=args._fixed_revision.oid["value"],
            )
        )
        evidence = (
            evidence_override if evidence_override is not None else _public_evidence(repo, args)
        )
        canonical_origin = (
            evidence.locator.sanitized_remote if evidence.locator is not None else remote_url(repo)
        )
        report = analyze_subject(
            repo,
            identity,
            _lineage(args),
            repository_source=getattr(args, "_source_repo", repo),
            subject_kind="repo",
            as_of=as_of,
            include_files=bool(getattr(args, "vendor_scan", False)),
            include_local_path=bool(getattr(args, "include_local_path", False)),
            sha_to_accounts=evidence.account_mapping,
            fetched_login_count=_manifest_account_count(evidence.manifest),
            canonical_origin=canonical_origin,
            public_evidence_digest=evidence.digest,
            public_evidence_coverage=evidence.coverage_observation(),
            target_oid=args._fixed_revision.oid,
            revision_completeness={
                "shallow": args._fixed_revision.shallow,
                "promisor": args._fixed_revision.promisor,
                "complete": args._fixed_revision.completeness_proven,
            },
        )
        errors = validate_report_v2(report)
        if errors:
            return _fail("report-v2 validation failed:\n" + "\n".join(errors))
        _commits, _origin, index = _attribution_index(repo, identity, args, evidence)
        top = getattr(args, "top", None)
        if isinstance(top, int):
            if top < 1:
                return _fail("--top must be >= 1")
        mode = selection_mode or ("top" if isinstance(top, int) else "all")
        artifacts = build_actor_artifacts(
            index,
            report,
            selection_mode=mode,
            top=top if mode == "top" else None,
            actor_ids=actor_ids_override,
            account_evidence=_artifact_account_evidence(evidence.manifest, index),
            account_status_overrides=_artifact_account_statuses(evidence, index),
            actor_details=actor_details,
        )
        destination = _collection_destination(args.out)
        if destination is not None:
            write_actor_artifacts(destination, artifacts)
        emit(
            markdown=artifacts.index_markdown,
            payload=artifacts.actor_index,
            fmt=getattr(args, "format", "json"),
            out=None,
            artifact="actor",
        )
        return evidence.exit_code
    except PublicEvidenceError as exc:
        return _fail(str(exc), exc.code)
    except (ActorArtifactError, InputValidationError, IdentityValidationError, ValueError) as exc:
        return _fail(str(exc))


def _remap_actor_repo(args: Namespace) -> tuple[Path, str | None]:
    actor_id = getattr(args, "actor_id", None)
    repo = args.repo if args.repo is not None else Path(".")
    collecting = bool(getattr(args, "all_actors", False) or getattr(args, "top", None))
    if collecting and actor_id and _is_git(Path(actor_id)):
        return Path(actor_id), None
    return repo, actor_id


def run_actor(args: Namespace, *, deprecated_from_analyze: bool = False) -> int:
    source, actor_id = _remap_actor_repo(args)
    if not _is_git(source):
        return _fail(f"not a git repository: {source}")
    try:
        with fixed_revision_worktree(source, getattr(args, "rev", None)) as fixed:
            routed = copy(args)
            routed.repo = fixed.worktree
            routed.actor_id = actor_id
            routed._source_repo = source.resolve()
            routed._fixed_revision = fixed
            return _run_actor_fixed(routed, deprecated_from_analyze=deprecated_from_analyze)
    except RevisionError as exc:
        return _fail(f"cannot resolve fixed revision: {exc}")


def _run_actor_fixed(args: Namespace, *, deprecated_from_analyze: bool = False) -> int:
    repo = args.repo if args.repo is not None else Path(".")
    actor_id = getattr(args, "actor_id", None)
    if not _is_git(repo):
        return _fail(f"not a git repository: {repo}")
    if getattr(args, "export", None) is not None:
        return _fail(
            "grift actor does not accept --export (per-actor quality export remains forbidden)"
        )
    if getattr(args, "reference_version", None):
        return _fail(
            "actor view refuses --reference-version; tenant values are not placed on repo distributions"
        )
    if getattr(args, "all_actors", False) or getattr(args, "top", None):
        if actor_id:
            return _fail("actor id, --all, and --top are mutually exclusive")
        return _run_actor_collection(args, repo)
    if not actor_id:
        return _fail("actor id required unless --all or --top is set")
    try:
        collection_output = _actor_out_requests_collection(getattr(args, "out", None))
        as_of = _validate_as_of(getattr(args, "as_of", None))
        identity = load_subject_identity(
            repo,
            getattr(args, "identity", None),
            revision=args._fixed_revision.oid["value"],
        )
        evidence = _public_evidence(repo, args)
        canonical_origin = (
            evidence.locator.sanitized_remote if evidence.locator is not None else remote_url(repo)
        )
        if identity.actors and actor_id in actor_ids(identity):
            if identity.email_patterns:
                return _fail(
                    "email_patterns cannot be safely assigned to one actor; "
                    "use --all or explicit emails on the selected id"
                )
            selected = select_actor(identity, str(actor_id))
        else:
            _commits, _origin, index = _attribution_index(repo, identity, args, evidence)
            inferred = find_actor(index, str(actor_id))
            if inferred is None:
                available = ", ".join(actor.actor_id for actor in index.actors) or "(none)"
                return _fail(f"unknown actor id {actor_id!r}; available: {available}")
            selected = synthetic_identity(inferred)
        if deprecated_from_analyze:
            sys.stderr.write(
                "warning: `grift analyze --actor` is a compatibility alias for "
                "`grift actor`; output is report-v2 and does not write .grift/report.json\n"
            )
        report = analyze_subject(
            repo,
            selected,
            _lineage(args),
            repository_source=getattr(args, "_source_repo", repo),
            subject_kind="actor",
            canonical_id=str(actor_id),
            as_of=as_of,
            role_lens=getattr(args, "role_lens", None),
            forge_export=getattr(args, "forge_export", None),
            tracker_export=getattr(args, "tracker_export", None),
            outcome_declaration=getattr(args, "outcome_declaration", None),
            template_provided=getattr(args, "template", None) is not None,
            parent_repo_provided=getattr(args, "parent_repo", None) is not None,
            include_files=bool(getattr(args, "vendor_scan", False)),
            include_local_path=bool(getattr(args, "include_local_path", False)),
            survival=bool(getattr(args, "survival", False)),
            reference_id=getattr(args, "reference", None),
            reference_manifest=getattr(args, "reference_manifest", None),
            event_window=_event_window(args),
            sha_to_accounts=evidence.account_mapping,
            fetched_login_count=_manifest_account_count(evidence.manifest),
            canonical_origin=canonical_origin,
            public_evidence_digest=evidence.digest,
            public_evidence_coverage=evidence.coverage_observation(),
            target_oid=args._fixed_revision.oid,
            revision_completeness={
                "shallow": args._fixed_revision.shallow,
                "promisor": args._fixed_revision.promisor,
                "complete": args._fixed_revision.completeness_proven,
            },
        )
        errors = validate_report_v2(report)
        if errors:
            return _fail("report-v2 validation failed:\n" + "\n".join(errors))
        sys.stderr.write(_actor_basis_notice(report.get("subject") or {}) + "\n")
        markdown = render_markdown(report)
        leaked = _refuse_leaks(
            markdown + json.dumps(report),
            allow_path=bool(getattr(args, "include_local_path", False)),
        )
        if leaked:
            return _fail(leaked)
        if collection_output:
            return _run_actor_collection(
                args,
                repo,
                identity_override=identity,
                evidence_override=evidence,
                selection_mode="explicit",
                actor_ids_override=[str(actor_id)],
                actor_details={str(actor_id): report},
            )
        emit(
            markdown=markdown,
            payload=report,
            fmt=getattr(args, "format", "md"),
            out=getattr(args, "out", None),
            artifact="actor",
        )
        return evidence.exit_code
    except PublicEvidenceError as exc:
        return _fail(str(exc), exc.code)
    except ActorSelectionError as exc:
        ids = ""
        try:
            identity = load_subject_identity(
                repo,
                getattr(args, "identity", None),
                revision=args._fixed_revision.oid["value"],
            )
            listed = ", ".join(actor_ids(identity))
            if listed:
                ids = f" available canonical_id values: {listed}"
        except Exception:
            ids = ""
        return _fail(f"{exc}.{ids}")
    except (InputValidationError, IdentityValidationError, ValueError) as exc:
        return _fail(str(exc))


def run_project(args: Namespace) -> int:
    if args.init:
        if args.repo is not None or args.requirements is not None:
            return _fail("project --init cannot be combined with REPO or --requirements")
        if args.out is None:
            return _fail("project --init requires --out")
        try:
            init_project_template(args.out)
        except InputValidationError as exc:
            return _fail(str(exc))
        sys.stderr.write(f"wrote empty project template to {args.out}\n")
        return 0
    if args.repo is None and args.requirements is None:
        args.repo = Path(".")
    # --requirements FILE alone is a declared view; do not imply cwd as REPO.
    try:
        as_of = _validate_as_of(getattr(args, "as_of", None))
        declared = empty_declared()
        loaded = None
        project_digest = None
        if args.requirements is not None:
            loaded = load_project_toml(args.requirements)
            declared = declared_view(loaded)
            project_digest = file_digest(args.requirements)
        observed = None
        repo_sha = None
        evidence_prov: dict = {}
        evidence: dict = {}
        if args.repo is not None:
            if not _is_git(args.repo):
                return _fail(f"not a git repository: {args.repo}")
            from tep_core.identity import empty_identity

            evidence = analyze_subject(
                args.repo,
                empty_identity(),
                Lineage(),
                subject_kind="repo",
                as_of=as_of,
                forge_export=getattr(args, "forge_export", None),
                tracker_export=getattr(args, "tracker_export", None),
                outcome_declaration=getattr(args, "outcome_declaration", None),
                reference_id=getattr(args, "reference", None),
                reference_manifest=getattr(args, "reference_manifest", None),
                event_window=_event_window(args),
            )
            evidence_prov = evidence["provenance"]
            repo_sha = evidence_prov["analyzed_commit_sha"]
            observed = {
                "kind": "observed",
                "unit": "profile",
                "definition_version": evidence_prov["definition_version"],
                "surface_profile": evidence["surface_profile"],
                "change_rhythm": evidence["change_rhythm"],
                "verification_profile": evidence["verification_profile"],
                "coordination_profile": evidence["coordination_profile"],
                "event_observation": evidence.get("event_observation"),
                "event_rhythm": evidence.get("event_rhythm"),
                "tracker_lifecycle": evidence.get("tracker_lifecycle"),
                "input_coverage": evidence["input_coverage"],
            }
        project_id = ""
        if declared.get("project_id", {}).get("kind") == "declared":
            project_id = str(declared["project_id"]["value"])
        digests = evidence_prov.get("input_digests") or {}
        payload = build_project_report(
            declared=declared,
            observed=observed,
            provenance={
                "tool_name": "grift",
                "tool_version": __version__,
                "definition_version": DEFINITION_VERSION,
                "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "analyzed_commit_sha": repo_sha,
                "observation_date": evidence_prov.get("observation_date") or as_of,
                "window_basis": evidence_prov.get("window_basis")
                or ("explicit_as_of" if as_of else "legacy_head_date"),
                "git_window": evidence_prov.get("git_window"),
                "event_window": evidence_prov.get("event_window"),
                "input_digests": {
                    "project": project_digest,
                    "forge": digests.get("forge"),
                    "tracker": digests.get("tracker"),
                },
            },
            subject={"kind": "project", "project_id": project_id or None},
            limitations=[
                EVIDENCE_DISCLAIMER,
                "declared requirements are owner input, not observations.",
            ],
        )
        if evidence.get("reference"):
            payload["reference"] = evidence["reference"]
        errors = validate_project(payload)
        if errors:
            return _fail("project-v1 validation failed:\n" + "\n".join(errors))
        emit(
            markdown=render_markdown(payload),
            payload=payload,
            fmt=args.format,
            out=args.out,
            artifact="project",
        )
        return 0
    except (InputValidationError, IdentityValidationError, ValueError) as exc:
        return _fail(str(exc))


def _alignment_limitations(actor_report: dict) -> list[str]:
    notes = [ALIGNMENT_NOTICE, EVIDENCE_DISCLAIMER]
    notes.append(_actor_basis_notice(actor_report.get("subject") or {}))
    coverage = actor_report.get("input_coverage") or {}
    forge = coverage.get("forge") or {}
    tracker = coverage.get("tracker") or {}
    if forge.get("kind") == "not_observed":
        notes.append(FORGE_NOT_OBSERVED_NOTE)
    if tracker.get("kind") == "not_observed":
        notes.append(TRACKER_NOT_OBSERVED_NOTE)
    return notes


def _actor_basis_notice(subject: dict) -> str:
    basis = classify_actor_basis(
        subject.get("selection"),
        subject.get("attribution_state"),
    )
    return actor_basis_notice(basis)


def _alignment_subject(
    actor_subject: dict,
    *,
    project_id: object,
    mode: str | None = None,
) -> dict[str, object]:
    """Keep optional actor basis fields absent instead of serializing null."""

    subject: dict[str, object] = {
        "kind": "alignment",
        "actor_canonical_id": actor_subject.get("canonical_id"),
        "project_id": project_id,
    }
    if actor_subject.get("selection") is not None:
        subject["actor_selection"] = actor_subject["selection"]
    if actor_subject.get("attribution_state") is not None:
        subject["actor_attribution_state"] = actor_subject["attribution_state"]
    if mode is not None:
        subject["mode"] = mode
    return subject


def _align_from_reports(
    args: Namespace,
    *,
    require_actor_schema: bool = True,
    actor_payload: dict | None = None,
    actor_digest: str | None = None,
) -> int:
    try:
        actor_report = (
            actor_payload if actor_payload is not None else _load_json_report(args.actor_report)
        )
        project_report = _load_json_report(args.project_report)
        if require_actor_schema:
            actor_errors = validate_report_v2(actor_report)
            if actor_errors:
                return _fail("report-v2 validation failed:\n" + "\n".join(actor_errors))
        project_errors = validate_project(project_report)
        if project_errors:
            return _fail("project-v1 validation failed:\n" + "\n".join(project_errors))
        if (
            actor_report.get("schema_version") != "report-v2"
            or actor_report.get("subject", {}).get("kind") != "actor"
        ):
            return _fail("--actor-report must be a report-v2 actor document")
        if project_report.get("schema_version") != "project-v1":
            return _fail("--project-report must be a project-v1 document")
        actor_subject = actor_report.get("subject") or {}
        actor_scope = actor_analysis_scope(
            actor_subject.get("selection"),
            actor_subject.get("attribution_state"),
        )
        declared = project_report.get("declared") or {}
        actor_digest = actor_digest if actor_digest is not None else file_digest(args.actor_report)
        project_digest = file_digest(args.project_report)
        actor_sha = (actor_report.get("provenance") or {}).get("analyzed_commit_sha")
        project_sha = (project_report.get("provenance") or {}).get("analyzed_commit_sha")
        actor_prov = dict(actor_report.get("provenance") or {})
        if not require_actor_schema:
            actor_prov["analysis_scope"] = actor_scope
            if actor_subject.get("selection") == "inferred_actor":
                actor_prov["identity_digest"] = None
            actor_report = {**actor_report, "provenance": actor_prov}
        project_prov = project_report.get("provenance") or {}
        payload = alignment_payload(
            actor_report=actor_report,
            declared=declared,
            provenance={
                "tool_name": "grift",
                "tool_version": __version__,
                "definition_version": DEFINITION_VERSION,
                "analysis_scope": actor_scope,
                "analyzed_commit_sha": actor_sha,
                "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "observation_date": actor_prov.get("observation_date"),
                "window_basis": actor_prov.get("window_basis"),
                "identity_digest": actor_prov.get("identity_digest"),
                "actor_commit_sha": actor_sha,
                "project_commit_sha": project_sha,
                "role_lens": actor_prov.get("role_lens")
                or (actor_report.get("role_lens") or {}).get("name"),
                "vendor_scan": actor_prov.get("vendor_scan"),
                "survival": actor_prov.get("survival"),
                "git_window": actor_prov.get("git_window"),
                "event_window": actor_prov.get("event_window"),
                "reference_manifest": (
                    args.reference_manifest.name
                    if getattr(args, "reference_manifest", None)
                    else actor_prov.get("reference_manifest")
                ),
                "reference_manifest_digest": (
                    file_digest(args.reference_manifest)
                    if getattr(args, "reference_manifest", None)
                    else actor_prov.get("reference_manifest_digest")
                ),
                "input_digests": {
                    "actor_report": actor_digest,
                    "project_report": project_digest,
                    "project": (project_prov.get("input_digests") or {}).get("project"),
                    "forge": (actor_prov.get("input_digests") or {}).get("forge"),
                    "tracker": (actor_prov.get("input_digests") or {}).get("tracker"),
                },
            },
            subject=_alignment_subject(
                actor_report.get("subject") or {},
                project_id=(project_report.get("subject") or {}).get("project_id"),
                mode="saved_reports",
            ),
            limitations=_alignment_limitations(actor_report)
            + [
                "actor report and project report may come from different repositories.",
                "No portfolio score is computed across repositories.",
            ],
            project_report=project_report,
            actor_report_digest=actor_digest,
            project_report_digest=project_digest,
        )
        errors = validate_alignment(payload)
        if errors:
            return _fail("alignment-v1 validation failed:\n" + "\n".join(errors))
        sys.stderr.write(_actor_basis_notice(actor_report.get("subject") or {}) + "\n")
        emit(
            markdown=render_markdown(payload),
            payload=payload,
            fmt=args.format,
            out=args.out,
            artifact="alignment",
        )
        return 0
    except (InputValidationError, ValueError) as exc:
        return _fail(str(exc))


def _align_team_from_actor_dir(args: Namespace) -> int:
    """W5: what the whole team does not cover, against one project brief.

    The single-actor path below refuses a multi-actor directory outright, which
    was the right default while every output was a per-person one. This mode is
    the exception the norms now allow: it reads all of them and emits counts.
    """
    from tep_core.complementarity import build_complementarity

    directory = args.actor_dir
    cards_dir = directory / "actors" if (directory / "actors").is_dir() else directory
    cards = sorted(path for path in cards_dir.glob("*.json") if path.name != "actors.json")
    if not cards:
        return _fail("actor-dir has no actor JSON")

    reports: list[dict] = []
    for path in cards:
        card = _load_json_report(path)
        schema = card.get("schema_version")
        if schema == "report-v2":
            reports.append(card)
        elif schema == "actor-card-v1":
            # The shipped card carries no `surface_profile`, so every named
            # requirement came back `not_observed` and the whole report said
            # nothing. Reading it was worse than refusing it: the output looked
            # like a measurement of the team.
            return _fail(
                "align --team requires report-v2 actor reports; actor-card-v1 carries no "
                "surface observations. Produce one per member with: "
                "grift actor <ID> --identity <toml> --format json"
            )
        else:
            return _fail(
                f"actor-dir card {path.name} has unsupported schema_version={schema!r}; "
                "align --team accepts report-v2 only"
            )

    project_report = _load_json_report(args.project_report)
    declared = project_report.get("declared") or {}
    digest = str(
        (project_report.get("provenance") or {}).get("project_digest")
        or project_report.get("project_digest")
        or ""
    )
    payload = build_complementarity(
        actor_reports=reports,
        declared=declared,
        project_digest=digest,
    )
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


def _align_from_actor_dir(args: Namespace) -> int:
    directory = args.actor_dir
    cards_dir = directory / "actors" if (directory / "actors").is_dir() else directory
    cards = sorted(path for path in cards_dir.glob("*.json") if path.name != "actors.json")
    if not cards:
        return _fail("actor-dir has no actor JSON")
    actor_id = getattr(args, "actor_id", None)
    if len(cards) > 1 and not actor_id:
        ids = []
        for path in cards:
            try:
                ids.append(str(_load_json_report(path).get("actor_id") or path.stem))
            except InputValidationError:
                ids.append(path.stem)
        return _fail(
            "align --actor-dir with multiple actors requires --actor ACTOR_ID; "
            "available: " + ", ".join(ids)
        )
    chosen = cards[0]
    if actor_id:
        match = None
        for path in cards:
            payload = _load_json_report(path)
            if payload.get("actor_id") == actor_id or path.stem == str(actor_id).replace(":", "_"):
                match = path
                break
        if match is None:
            return _fail(f"actor id {actor_id!r} not found in actor-dir")
        chosen = match
    card = _load_json_report(chosen)
    schema = card.get("schema_version")
    if schema not in {"actor-card-v1", "report-v2"}:
        return _fail(
            f"actor-dir card {chosen.name} has unsupported schema_version={schema!r}; "
            "align accepts actor-card-v1 or report-v2 only (no format guessing)"
        )
    if schema == "report-v2":
        args.actor_report = chosen
        return _align_from_reports(args)
    actor_report = actor_report_from_card(card)
    repo_json = directory / "repo-report.json"
    if not repo_json.is_file():
        # actor-dir may point at the cards subdirectory (DIR/actors) or at the
        # collection root (DIR); the repo report lives at the collection root.
        repo_json = cards_dir.parent / "repo-report.json"
    if not repo_json.is_file():
        # Read-only compatibility with pre-v0.6 actor directories.
        repo_json = directory / "report.json"
    if not repo_json.is_file():
        repo_json = cards_dir.parent / "report.json"
    if repo_json.is_file():
        repo_report = _load_json_report(repo_json)
        actor_report["provenance"] = {
            **(repo_report.get("provenance") or {}),
            **(actor_report.get("provenance") or {}),
        }
    # Digest is taken from the CARD file itself so `grift verify` recomputes
    # the same alignment from the same collection layout (actors/<id>.json).
    args.actor_report = chosen
    return _align_from_reports(
        args,
        require_actor_schema=False,
        actor_payload=actor_report,
        actor_digest=file_digest(chosen),
    )


def run_align(args: Namespace) -> int:
    if getattr(args, "reference_version", None):
        return _fail(
            "align refuses --reference-version; tenant values are not placed on repo distributions"
        )
    saved_mode = bool(
        getattr(args, "actor_dir", None)
        or getattr(args, "actor_report", None)
        or getattr(args, "project_report", None)
    )
    if saved_mode and (
        getattr(args, "forge_export", None) is not None
        or getattr(args, "tracker_export", None) is not None
    ):
        return _fail(
            "saved-report align refuses --forge-export/--tracker-export; "
            "the saved reports must already carry their source bindings"
        )
    if getattr(args, "actor_dir", None) and getattr(args, "project_report", None):
        if getattr(args, "team", False):
            return _align_team_from_actor_dir(args)
        return _align_from_actor_dir(args)
    if getattr(args, "actor_report", None) and getattr(args, "project_report", None):
        return _align_from_reports(args)
    if not args.repo or not args.identity or not args.actor_id or not args.project:
        return _fail(
            "align requires --repo --identity --actor --project, "
            "or --actor-report and --project-report, or --actor-dir and --project-report"
        )
    repo = args.repo
    if not _is_git(repo):
        return _fail(f"not a git repository: {repo}")
    try:
        as_of = _validate_as_of(getattr(args, "as_of", None))
        identity = load_identity(args.identity)
        selected = select_actor(identity, str(args.actor_id))
        loaded = load_project_toml(args.project)
        declared = declared_view(loaded)
        actor_report = analyze_subject(
            repo,
            selected,
            _lineage(args),
            subject_kind="actor",
            canonical_id=str(args.actor_id),
            as_of=as_of,
            role_lens=getattr(args, "role_lens", None),
            forge_export=getattr(args, "forge_export", None),
            tracker_export=getattr(args, "tracker_export", None),
            outcome_declaration=getattr(args, "outcome_declaration", None),
            template_provided=getattr(args, "template", None) is not None,
            parent_repo_provided=getattr(args, "parent_repo", None) is not None,
            include_files=bool(getattr(args, "vendor_scan", False)),
            include_local_path=False,
            survival=bool(getattr(args, "survival", False)),
            reference_id=getattr(args, "reference", None),
            reference_manifest=getattr(args, "reference_manifest", None),
            event_window=_event_window(args),
        )
        payload = alignment_payload(
            actor_report=actor_report,
            declared=declared,
            provenance={
                "tool_name": "grift",
                "tool_version": __version__,
                "definition_version": DEFINITION_VERSION,
                "analysis_scope": actor_analysis_scope(
                    (actor_report.get("subject") or {}).get("selection"),
                    (actor_report.get("subject") or {}).get("attribution_state"),
                ),
                "analyzed_commit_sha": actor_report["provenance"]["analyzed_commit_sha"],
                "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "observation_date": actor_report["provenance"]["observation_date"],
                "window_basis": actor_report["provenance"]["window_basis"],
                "identity_digest": actor_report["provenance"].get("identity_digest"),
                "actor_commit_sha": actor_report["provenance"]["analyzed_commit_sha"],
                "project_commit_sha": None,
                "role_lens": (actor_report.get("role_lens") or {}).get("name"),
                "input_digests": {
                    **(actor_report["provenance"].get("input_digests") or {}),
                    "project": file_digest(args.project),
                    "actor_report": None,
                },
            },
            subject=_alignment_subject(
                actor_report.get("subject") or {},
                project_id=loaded.get("project_id") or None,
            ),
            limitations=_alignment_limitations(actor_report) + [PROJECT_OBSERVED_MISSING_NOTE],
        )
        if actor_report.get("reference"):
            payload["reference"] = actor_report["reference"]
        errors = validate_alignment(payload)
        if errors:
            return _fail("alignment-v1 validation failed:\n" + "\n".join(errors))
        sys.stderr.write(_actor_basis_notice(actor_report.get("subject") or {}) + "\n")
        emit(
            markdown=render_markdown(payload),
            payload=payload,
            fmt=args.format,
            out=args.out,
            artifact="alignment",
        )
        return 0
    except ActorSelectionError as exc:
        return _fail(str(exc))
    except (InputValidationError, IdentityValidationError, ValueError) as exc:
        return _fail(str(exc))
