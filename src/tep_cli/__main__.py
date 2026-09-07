"""grift CLI (method = TEP). Verb semantics: analyze=display (stdout), report=record (.grift/)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tep_cli.benchmark_cmd import run_benchmark
from tep_cli.options import build_parser
from tep_cli.subject import run_actor, run_align, run_project, run_repo
from tep_core.analyze import analyze_repository
from tep_core.export import build_export, write_export
from tep_core.identity import IdentityValidationError, discover_legacy_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown
from tep_core.verify import CANNOT_VERIFY, MISMATCH, VERIFIED, verify_report
from tep_core.version import __version__


def _run_analyze(args: argparse.Namespace) -> int:
    if getattr(args, "actor", None):
        args.actor_id = args.actor
        if args.format == "both":
            args.format = "md"
        return run_actor(args, deprecated_from_analyze=True)
    repo: Path = args.repo if args.repo is not None else Path(".")
    scope = (
        str(args.scope) if args.scope is not None else ("repo" if args.repo is None else "tenant")
    )
    if not (repo / ".git").exists() and not repo.joinpath("HEAD").exists():
        sys.stderr.write(f"not a git repository: {repo}\n")
        return 2
    try:
        identity = discover_legacy_identity(repo, args.identity)
    except IdentityValidationError as exc:
        sys.stderr.write(f"identity validation error: {exc}\n")
        return 2
    lineage = Lineage(is_fork=bool(args.fork), parent=args.parent or None)
    report = analyze_repository(
        repo,
        identity,
        lineage,
        template_provided=args.template is not None,
        parent_repo_provided=args.parent_repo is not None,
        include_files=bool(args.vendor_scan),
        include_local_path=bool(args.include_local_path),
        survival=bool(args.survival),
        scope=scope,
        reference_version=str(args.reference_version) if args.reference_version else None,
    )
    markdown = render_markdown(report)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(markdown, encoding="utf-8")
        (args.out / "report.json").write_text(encoded, encoding="utf-8")
    if args.format in {"md", "both"}:
        sys.stdout.write(markdown)
        if args.format == "both":
            sys.stdout.write("\n")
    if args.format in {"json", "both"}:
        sys.stdout.write(encoded)
    if args.export is not None:
        export = build_export(
            repo,
            identity,
            lineage,
            template_provided=args.template is not None,
            parent_repo_provided=args.parent_repo is not None,
            include_files=bool(args.vendor_scan),
            scope=scope,
        )
        write_export(export, args.export)
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    repo = args.repo if args.repo is not None else Path(".")
    if (
        args.public_evidence is not None
        and args.bundle is None
        and args.report is None
        and args.report_positional is None
    ):
        return _run_public_evidence_verify(args.public_evidence, repo)
    if args.report is not None and args.report_positional is not None:
        sys.stderr.write("verify: pass the report either positionally or with --report, not both\n")
        return 2
    report = args.report or args.report_positional or GRIFT_DIR / "report.json"
    if report.is_dir() and args.bundle is None:
        return _run_actor_artifact_verify(
            report,
            repo,
            args.identity,
            getattr(args, "public_evidence", None),
        )
    if args.bundle is not None:
        return _run_attestation_verify(args, report, repo)
    if not report.is_file():
        sys.stderr.write(
            f"verify: {report} not found — run `grift report` first "
            "(bare verify checks .grift/report.json against the current repo)\n"
        )
        return 2
    result = verify_report(
        report,
        repo,
        args.identity,
        project_path=getattr(args, "project", None),
        forge_export=getattr(args, "forge_export", None),
        tracker_export=getattr(args, "tracker_export", None),
        actor_id=getattr(args, "actor_id", None),
        actor_report_path=getattr(args, "actor_report", None),
        project_report_path=getattr(args, "project_report", None),
        reference_manifest=getattr(args, "reference_manifest", None),
        public_evidence_path=getattr(args, "public_evidence", None),
    )
    if result.status == VERIFIED:
        sys.stdout.write(f"{VERIFIED}: all fields match recomputation under recorded provenance\n")
        return 0
    if result.status == MISMATCH:
        sys.stdout.write(f"{MISMATCH}: {len(result.differences)} field(s) differ\n")
        for line in result.differences:
            sys.stdout.write(f"  - {line}\n")
        return 1
    sys.stdout.write(f"{CANNOT_VERIFY}:\n")
    for note in result.notes:
        sys.stdout.write(f"  - {note}\n")
    return 2


def _run_actor_artifact_verify(
    directory: Path,
    repo: Path,
    identity_path: Path | None,
    public_evidence_path: Path | None,
) -> int:
    """Verify a closed actor collection and its fixed-OID Git partition offline."""

    from tep_core.actor_artifacts import (
        ActorArtifactError,
        verify_actor_artifact_directory,
    )
    from tep_core.analyze import _tenant_experience, prepare_inputs
    from tep_core.attribution import (
        build_attribution_index,
        derive_repo_scope_digest,
        read_mailmap_at_revision,
    )
    from tep_core.analyze_v2 import _consent_not_observed
    from tep_core.experience import EXPERIENCE_DEFINITION_VERSION
    from tep_core.role_profile import ROLE_PROFILE_DEFINITION_VERSION
    from tep_core.gitutil import coauthor_shas, remote_url, rev_parse
    from tep_core.identity import actor_ids, load_subject_identity, select_actor
    from tep_core.public_evidence import load_public_evidence, verify_public_evidence
    from tep_core.revision import RevisionError, fixed_revision_worktree

    try:
        verified = verify_actor_artifact_directory(directory)
        manifest = json.loads((directory / "collection-manifest.json").read_text(encoding="utf-8"))
        actor_index = json.loads((directory / "actor-index.json").read_text(encoding="utf-8"))
        repo_report = json.loads((directory / "repo-report.json").read_text(encoding="utf-8"))
        target = manifest["target"]["oid"]
        with fixed_revision_worktree(repo, str(target["value"])) as fixed:
            if fixed.oid != target:
                sys.stdout.write("MISMATCH: actor artifact target OID differs from repository\n")
                return 1
            identity = load_subject_identity(
                fixed.worktree,
                identity_path,
                revision=str(target["value"]),
            )
            commits, origin = prepare_inputs(
                fixed.worktree,
                identity,
                Lineage(),
                include_files=True,
            )
            canonical_origin = remote_url(fixed.worktree)
            scope_digest, _object_format = derive_repo_scope_digest(commits, canonical_origin)
            mailmap = read_mailmap_at_revision(fixed.worktree, rev_parse(fixed.worktree))
            recomputed = build_attribution_index(
                commits,
                origin,
                identity,
                mailmap=mailmap,
                mailmap_present=mailmap.present,
                coauthor_shas=coauthor_shas(fixed.worktree),
                repo_scope_digest=scope_digest,
                canonical_origin=canonical_origin,
            )
            expected_actors = [
                {
                    "actor_id": actor.actor_id,
                    "commit_count": len(actor.commit_shas),
                    "nonmerge_commit_count": actor.nonmerge_count,
                    "merge_commit_count": actor.merge_count,
                }
                for actor in sorted(
                    recomputed.actors,
                    key=lambda item: (-len(item.commit_shas), item.actor_id),
                )
            ]
            differences: list[str] = []
            if recomputed.partition_digest != manifest["partition_digest"]["value"]:
                differences.append("partition digest")
            if expected_actors != actor_index["actors"]:
                differences.append("actor membership/counts")
            attributed = sum(len(actor.commit_shas) for actor in recomputed.actors)
            human_total = attributed + len(recomputed.unresolved_shas)
            if human_total != repo_report["population"]["human_commit_count"]:
                differences.append("human commit population")
            if recomputed.merge_count != repo_report["population"]["merge_commit_count"]:
                differences.append("merge population")
            completeness = {
                "shallow": fixed.shallow,
                "promisor": fixed.promisor,
                "complete": fixed.completeness_proven,
            }
            if completeness != repo_report["provenance"]["revision_completeness"]:
                differences.append("revision completeness")
            actor_by_id = {actor.actor_id: actor for actor in recomputed.actors}
            cards: list[dict] = []
            for card_path in sorted((directory / "actors").glob("*.json")):
                card = json.loads(card_path.read_text(encoding="utf-8"))
                cards.append(card)
                actor = actor_by_id.get(str(card.get("actor_id")))
                if actor is None:
                    differences.append(f"card actor membership:{card_path.name}")
                    continue
                if actor_index["selection"]["mode"] == "explicit":
                    if identity.actors and actor.actor_id in actor_ids(identity):
                        selected_identity = select_actor(identity, actor.actor_id)
                        # The third element is the library-prevalence axis, which
                        # the actor card does not carry; cards recompute only
                        # what they record.
                        expected_experience, expected_role, _ = _tenant_experience(
                            fixed.worktree,
                            commits,
                            origin,
                            selected_identity,
                        )
                    else:
                        # Definition versions come from the modules that own
                        # them: a literal here recomputes an expectation the
                        # card can no longer match once a version moves (W1).
                        expected_experience = _consent_not_observed(
                            actor.actor_id, EXPERIENCE_DEFINITION_VERSION
                        )
                        expected_role = _consent_not_observed(
                            actor.actor_id, ROLE_PROFILE_DEFINITION_VERSION
                        )
                    for detail in (expected_experience, expected_role):
                        if (
                            detail.get("kind") == "not_observed"
                            and detail.get("reason") == "consenting_actor_required"
                        ):
                            detail["actor_id"] = actor.actor_id
                    if card.get("experience") != expected_experience:
                        differences.append(f"experience recomputation:{actor.actor_id}")
                    if card.get("role_profile") != expected_role:
                        differences.append(f"role profile recomputation:{actor.actor_id}")
                actor_oids = {oid.lower() for oid in actor.commit_shas}
                for account in card.get("accounts") or []:
                    for evidence in account.get("evidence") or []:
                        oid = str((evidence.get("commit_oid") or {}).get("value") or "")
                        if oid.lower() not in actor_oids:
                            differences.append(f"account evidence actor binding:{card_path.name}")
            recorded_public_digest = repo_report["provenance"].get("public_evidence_digest")
            has_public_accounts = any(card.get("accounts") for card in cards)
            public_required = recorded_public_digest is not None or has_public_accounts
            cannot_notes: list[str] = []
            if public_evidence_path is None:
                if public_required:
                    cannot_notes.append(
                        "recorded provider accounts require the bound --public-evidence bundle"
                    )
            else:
                public_result = verify_public_evidence(
                    public_evidence_path,
                    expected_oids=[commit.sha for commit in commits],
                )
                public_status = public_result.get("status")
                if public_status == CANNOT_VERIFY:
                    cannot_notes.append(
                        "public evidence cannot be replayed: "
                        + str(public_result.get("reason") or "unknown reason")
                    )
                elif public_status != VERIFIED:
                    differences.append(
                        "public evidence integrity: "
                        + str(public_result.get("reason") or public_status)
                    )
                else:
                    public_manifest = load_public_evidence(
                        public_evidence_path,
                        expected_oids=[commit.sha for commit in commits],
                    )
                    observed_digest = public_result.get("bundle_payload_sha256")
                    expected_digest = (
                        recorded_public_digest.get("value")
                        if isinstance(recorded_public_digest, dict)
                        else recorded_public_digest
                    )
                    if not expected_digest:
                        differences.append("report is missing the public evidence digest")
                    elif expected_digest != observed_digest:
                        differences.append("public evidence digest")
                    if public_manifest.get("target_oid") != target:
                        differences.append("public evidence target OID")
                    reconciliation = public_result.get("reconciliation") or {}
                    if (
                        public_result.get("coverage") != "complete"
                        or reconciliation.get("status") != "complete"
                    ):
                        cannot_notes.append("public evidence coverage is partial")
                    expected_links: set[tuple[str, str, str, str, str, str, str]] = set()
                    account_actors: dict[tuple[str, str, str], set[str]] = {}
                    actor_accounts: dict[str, set[tuple[str, str, str]]] = {
                        actor_id: set() for actor_id in actor_by_id
                    }
                    for oid, raw_account in (public_manifest.get("sha_to_account") or {}).items():
                        rows = raw_account if isinstance(raw_account, list) else [raw_account]
                        actor_id = recomputed.sha_to_actor.get(str(oid))
                        if actor_id is None:
                            continue
                        for row in rows:
                            if not isinstance(row, dict):
                                differences.append("public evidence account row shape")
                                continue
                            key = (
                                str(row.get("provider") or ""),
                                str(row.get("host") or ""),
                                str(row.get("account_id") or ""),
                            )
                            actor_accounts[actor_id].add(key)
                            account_actors.setdefault(key, set()).add(actor_id)
                            expected_links.add(
                                (
                                    actor_id,
                                    str(oid),
                                    *key,
                                    str(row.get("handle") or ""),
                                    str(row.get("profile_url") or ""),
                                )
                            )
                    selected_ids = {str(card.get("actor_id")) for card in cards}
                    expected_links = {link for link in expected_links if link[0] in selected_ids}
                    actual_links: set[tuple[str, str, str, str, str, str, str]] = set()
                    for card in cards:
                        actor_id = str(card.get("actor_id"))
                        for account in card.get("accounts") or []:
                            for item in account.get("evidence") or []:
                                if item.get("kind") != "commit_account_link":
                                    cannot_notes.append(
                                        "declared account evidence lacks a stable-id trust statement"
                                    )
                                    continue
                                actual_links.add(
                                    (
                                        actor_id,
                                        str((item.get("commit_oid") or {}).get("value") or ""),
                                        str(account.get("provider") or ""),
                                        str(account.get("host") or ""),
                                        str(account.get("account_id") or ""),
                                        str(account.get("handle") or ""),
                                        str(account.get("profile_url") or ""),
                                    )
                                )
                        keys = actor_accounts.get(actor_id, set())
                        if public_manifest.get("account_linkage") == "unsupported":
                            expected_status = "unsupported"
                        elif any(len(account_actors.get(key, set())) > 1 for key in keys):
                            expected_status = "conflict"
                        elif len(keys) > 1:
                            expected_status = "ambiguous"
                        elif len(keys) == 1:
                            expected_status = "matched"
                        elif public_result.get("coverage") == "complete":
                            expected_status = "unmatched"
                        else:
                            expected_status = "unavailable"
                        if card.get("account_status") != expected_status:
                            differences.append(f"provider account status:{actor_id}")
                    if actual_links != expected_links:
                        differences.append("provider account metadata/OID binding")
            if differences:
                sys.stdout.write(f"{MISMATCH}: " + ", ".join(dict.fromkeys(differences)) + "\n")
                return 1
            if cannot_notes:
                sys.stdout.write(
                    f"{CANNOT_VERIFY}: " + ", ".join(dict.fromkeys(cannot_notes)) + "\n"
                )
                return 2
        sys.stdout.write(
            f"{VERIFIED}: actor collection {verified.member_count} member(s), "
            f"full={verified.full_actor_count}, selected={verified.selected_actor_count}\n"
        )
        return 0
    except RevisionError as exc:
        sys.stdout.write(f"{CANNOT_VERIFY}: target repository cannot supply fixed OID: {exc}\n")
        return 2
    except (ActorArtifactError, IdentityValidationError, OSError, ValueError) as exc:
        sys.stdout.write(f"{MISMATCH}: actor collection verification failed: {exc}\n")
        return 1


def _run_public_evidence_verify(bundle: Path, repo: Path) -> int:
    from tep_core.forge_public import GitObjectId
    from tep_core.public_evidence import (
        load_public_evidence,
        read_fixed_history_oids,
        reconcile_commit_coverage,
        verify_public_evidence,
    )

    result = verify_public_evidence(bundle)
    if result.get("status") != VERIFIED:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return 1 if result.get("status") == MISMATCH else 2
    try:
        manifest = load_public_evidence(bundle)
        if not (repo / ".git").exists() and not repo.joinpath("HEAD").exists():
            result = {
                **result,
                "status": CANNOT_VERIFY,
                "reason": "target repository not provided",
            }
            sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            return 2
        target = GitObjectId(**manifest["target_oid"])
        coverage = reconcile_commit_coverage(manifest, read_fixed_history_oids(repo, target))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        result = {**result, "status": CANNOT_VERIFY, "reason": str(exc)}
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return 2
    result["git_oid_coverage"] = coverage
    if coverage["status"] == "mismatch":
        result["status"] = MISMATCH
        code = 1
    elif coverage["status"] == "partial" or result.get("coverage") != "complete":
        result["status"] = CANNOT_VERIFY
        result["reason"] = "public evidence is a safe partial bundle"
        code = 2
    else:
        code = 0
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return code


def _run_attestation_verify(args: argparse.Namespace, report: Path, repo: Path) -> int:
    from tep_core.attest import (
        CANNOT_VERIFY as ATTEST_CANNOT_VERIFY,
        MISMATCH as ATTEST_MISMATCH,
        CosignTrustPolicy,
        SSHTrustPolicy,
        VerificationPart,
        verify_attestation_bundle,
    )

    trust = None
    ssh_selected = args.allowed_signers is not None or args.principal is not None
    cert_selected = (
        args.certificate_identity is not None or args.certificate_oidc_issuer is not None
    )
    key_selected = args.cosign_public_key is not None
    if sum(bool(value) for value in (ssh_selected, cert_selected, key_selected)) > 1:
        sys.stderr.write("verify: specify exactly one SSH or cosign trust policy\n")
        return 2
    if ssh_selected:
        if args.allowed_signers is None or args.principal is None:
            sys.stderr.write("verify: SSH trust requires --allowed-signers and --principal\n")
            return 2
        trust = SSHTrustPolicy(args.allowed_signers, args.principal)
    elif cert_selected:
        if args.certificate_identity is None or args.certificate_oidc_issuer is None:
            sys.stderr.write(
                "verify: keyless cosign trust requires certificate identity and OIDC issuer\n"
            )
            return 2
        trust = CosignTrustPolicy(
            certificate_identity=args.certificate_identity,
            certificate_oidc_issuer=args.certificate_oidc_issuer,
        )
    elif key_selected:
        trust = CosignTrustPolicy(public_key=args.cosign_public_key)

    def recompute(bound_report: Path, bound_repo: Path) -> VerificationPart:
        verified = verify_report(
            bound_report,
            bound_repo,
            args.identity,
            project_path=getattr(args, "project", None),
            forge_export=getattr(args, "forge_export", None),
            tracker_export=getattr(args, "tracker_export", None),
            actor_id=getattr(args, "actor_id", None),
            actor_report_path=getattr(args, "actor_report", None),
            project_report_path=getattr(args, "project_report", None),
            reference_manifest=getattr(args, "reference_manifest", None),
            public_evidence_path=getattr(args, "public_evidence", None),
        )
        details = verified.differences or verified.notes
        detail = "; ".join(details) if details else "repository recomputation matched"
        return VerificationPart(verified.status, detail)

    result = verify_attestation_bundle(
        args.bundle,
        report,
        trust_policy=trust,
        repo=repo,
        recompute=recompute,
    )
    payload = result.to_dict()
    payload["notice"] = (
        "署名は実行主体と記録条件を検証するもので、数値の正しさ、品質、優秀さを証明しません。"
    )
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    if result.overall == VERIFIED:
        return 0
    if result.overall == ATTEST_MISMATCH:
        return 1
    if result.overall == ATTEST_CANNOT_VERIFY:
        return 2
    return 1


GRIFT_DIR = Path(".grift")
_DEFAULT_REPORT_SEARCH = (
    GRIFT_DIR / "report.json",
    Path("out") / "report.json",  # legacy pre-0.5.5 locations, read-only compat
    Path(".grift-out") / "report.json",
    Path("report.json"),
)


def _resolve_report_path(explicit: Path | None) -> tuple[Path | None, str]:
    """Return (path, guidance). Search .grift, then legacy ./out, .grift-out, ./."""
    if explicit is not None:
        return explicit, ""
    for candidate in _DEFAULT_REPORT_SEARCH:
        if candidate.is_file():
            return candidate, ""
    return None, ""


def _run_report(args: argparse.Namespace) -> int:
    if args.report_json is None:
        # UX (代表 2026-08-23): bare `grift report` ALWAYS re-analyzes the
        # current HEAD and rewrites .grift/report.{json,md}. It never falls
        # back to a stale report.json — "report で測ったつもりが古い
        # SHA のまま" は自己証明の罠になるため、既存ファイルは無条件に
        # 上書きする。再分析なしの再レンダリングは引数指定時のみ。
        return _analyze_to_grift_dir(scope=str(args.scope))
    try:
        payload = json.loads(args.report_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"report unreadable ({args.report_json}): {exc}\n")
        return 2
    try:
        markdown = render_markdown(payload)
    except KeyError as exc:
        sys.stderr.write(f"report is missing a required field: {exc}\n")
        return 2
    if args.out is not None:
        target = args.out / "report.md" if args.out.is_dir() else args.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0


def _analyze_to_grift_dir(*, scope: str = "repo") -> int:
    """Run the analysis in the current directory and write ./out/report.{json,md}.

    UX (v0.5.5): bare verbs write into .grift/ (auto-created, gitignored
    by convention). Reuses the analyze pipeline on '.'.
    """
    repo = Path(".")
    if not (repo / ".git").exists():
        sys.stderr.write("grift: not a git repository (run inside the repo you want to analyze)\n")
        return 2
    identity = discover_legacy_identity(repo, None)
    report = analyze_repository(repo, identity, Lineage(), scope=scope)
    markdown = render_markdown(report)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    out_dir = GRIFT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(encoded, encoding="utf-8")
    (out_dir / "report.md").write_text(markdown, encoding="utf-8")
    sys.stdout.write(markdown)
    sys.stderr.write(f"\nwrote {out_dir / 'report.json'} and {out_dir / 'report.md'}\n")
    return 0


def _run_update(args: argparse.Namespace) -> int:
    """Explicit self-upgrade (#51). No telemetry: reads PyPI metadata (public
    JSON) only with --check; upgrade runs pipx/pip locally."""
    import shutil
    import subprocess
    import urllib.request

    latest = None
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/grift-cli/json", timeout=10) as response:
            latest = json.loads(response.read()).get("info", {}).get("version")
    except Exception as exc:  # noqa: BLE001 — offline is fine
        sys.stderr.write(f"version check skipped (offline or PyPI unreachable): {exc}\n")
    sys.stdout.write(f"installed: {__version__}\n")
    if latest:
        sys.stdout.write(f"latest:    {latest}\n")
        if latest == __version__:
            sys.stdout.write("up to date\n")
            return 0
    elif not args.check:
        sys.stderr.write("continuing with upgrade attempt anyway\n")
    if args.check:
        return 0
    pipx = shutil.which("pipx")
    if pipx:
        sys.stdout.write("running: pipx upgrade grift-cli\n")
        result = subprocess.run([pipx, "upgrade", "grift-cli"])
        return result.returncode
    pip = shutil.which("pip") or shutil.which("pip3")
    if pip:
        sys.stdout.write("running: pip install --upgrade grift-cli\n")
        result = subprocess.run([pip, "install", "--upgrade", "grift-cli"])
        return result.returncode
    sys.stderr.write("neither pipx nor pip found — upgrade manually (pipx upgrade grift-cli)\n")
    return 2


def _run_contribute(args: argparse.Namespace) -> int:
    import hashlib

    from tep_core.contribute import (
        CONFIRMATION_TEXT,
        prepare_contribution,
        render_confirmation,
        write_contribution_text_atomic,
        write_controlled_contribution_atomic,
    )

    report_path, _guidance = _resolve_report_path(args.report_json)
    if report_path is None:
        sys.stderr.write(
            "contribute: no report.json found (searched .grift/report.json, then legacy ./out, .grift-out, ./). "
            "Run `grift report` first — it will analyze the repo and write .grift/report.json.\n"
        )
        return 2
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"report unreadable ({report_path}): {exc}\n")
        return 2
    selected_door = "public-pr" if getattr(args, "open", False) else str(args.door)
    try:
        bundle = prepare_contribution(
            report,
            mode=args.mode,
            privacy=None if args.mode is not None else args.privacy,
            door=selected_door,
            key_file=args.key_file,
            key_fd=args.key_fd,
            controlled_sidecar=args.controlled_sidecar,
            study_manifest=args.study_manifest,
            repo_subject_id=args.repo_subject_id,
            purpose=getattr(args, "purpose", None),
        )
    except ValueError as exc:
        sys.stderr.write(f"contribute: {exc}\n")
        return 2
    payload = bundle.payload
    payload_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    controlled = payload.get("privacy_profile") in {"masked", "raw"}
    disclosure = CONFIRMATION_TEXT
    if controlled:
        disclosure = CONFIRMATION_TEXT.replace(
            "1. 上記の payload 全文が提出内容のすべてです / The payload above is the entirety of the submission\n",
            "1. controlledではterminalにdigest要約だけを表示し、private出力ファイルが提出内容のすべてです / Controlled mode prints only a digest summary to the terminal; the private output file is the complete payload\n",
            1,
        )
        payload_digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
        text = (
            "=== controlled contribution payload summary ===\n"
            f"schema={payload.get('contribution_schema')}; "
            f"profile={payload.get('privacy_profile')}; door={payload.get('door')}; "
            f"sha256={payload_digest}\n"
            "Full controlled payload is not printed. Inspect the private output file directly.\n\n"
            + disclosure
        )
    else:
        text = render_confirmation(payload)
    if not args.yes:
        # F-C1: consent gate is enforced on EVERY path. Non-TTY without --yes
        # is refused (exit 2) with the disclosure on stderr — never a silent write.
        if not sys.stdin.isatty():
            sys.stderr.write(
                "contribute: interactive confirmation required.\n\n"
                + disclosure
                + (
                    "\n非対話環境では --yes を明示してください。controlled payloadは --yes でもdigest要約だけを表示します。\n"
                    if controlled
                    else "\n非対話環境では --yes を明示してください。--yes でも開示文と payload 全文を表示してから書き出します。\n"
                )
            )
            return 2
        sys.stdout.write(text)
        answer = input(
            "提出payloadを確認しましたか？ 公開されることに同意して書き出しますか? [yes/No] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            sys.stderr.write("aborted: nothing was written or sent\n")
            return 1
    else:
        # F-C1: --yes still prints disclosure + payload summary BEFORE writing
        # (consent leaves a trace even in non-interactive use).
        sys.stderr.write(disclosure)
        sections = payload.get("metrics")
        section_names = (
            sorted(sections)
            if isinstance(sections, dict)
            else sorted(
                key
                for key in payload
                if key not in {"contribution_schema", "purpose", "provenance"}
            )
        )
        sys.stderr.write(
            f"payload summary: schema={payload['contribution_schema']} "
            f"purpose={payload['purpose']} "
            f"definition={(payload.get('provenance') or {}).get('definition_version')} "
            f"metric_sections={section_names}\n"
            + (
                "controlled payload digest summary follows on stdout; full text is withheld.\n"
                if controlled
                else "payload full text follows on stdout.\n"
            )
        )
        sys.stdout.write(text)
    from datetime import datetime, timezone

    target = args.out
    if target is None:
        # UX (#49): consented submissions always land somewhere — default to .grift/
        target = GRIFT_DIR / "contribution.json"
    try:
        if bundle.controlled_sidecar is not None:
            # Controlled payloads contain high-precision/private material.  The
            # payload and governance sidecar cross the consent boundary as one
            # recoverable pair and are both private on disk.
            assert args.controlled_sidecar is not None  # checked by prepare_contribution
            write_controlled_contribution_atomic(
                payload_path=target,
                payload=payload,
                sidecar_path=args.controlled_sidecar,
                sidecar=bundle.controlled_sidecar,
            )
        else:
            # Preserve the v1 and aggregate/named-public local/public-pr file
            # contract.  Those payloads contain no controlled sidecar.
            write_contribution_text_atomic(target, payload_text)
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"contribute: could not write payload: {exc}\n")
        return 2
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    submission_id = now.strftime("%m%d-%H%M") + "-" + digest[:8]
    sys.stderr.write(f"\npayload written to {target} (nothing was sent)\n")
    if selected_door == "public-pr":
        sys.stderr.write(
            "\n=== 公開提出手順（Git履歴から完全撤回できません） ===\n"
            f"1. https://github.com/Cor-Incorporated/tep-contributions に PR を出す\n"
            f"   - ファイル名: payloads/{now.year}/{submission_id}.json（上記 payload をそのまま）\n"
            f"   - 同じ場所に {submission_id}.meta.json も追加（--open は自動でコミット済み）:\n"
            f'     {{"id":"{submission_id}","sha256":"{digest}","received_at":"{now.strftime("%Y-%m-%dT%H:%M:%SZ")}","door":"pr"}}\n'
            "   - manifest.jsonl は main で自動生成されるため編集不要\n"
            "2. 代理PR経路は提出者の身元を公開しないだけで、payload自体は最終的に公開されます\n"
            "   詳細: tep-contributions の README/CONTRIBUTING\n"
        )
    elif selected_door == "controlled":
        sys.stderr.write(
            "\ncontrolled payload was written locally. Automatic upload is intentionally unavailable; "
            "transfer it only to the authorized controlled destination named in the sidecar.\n"
        )
    else:
        sys.stderr.write("\nlocal payload only: no submission destination was selected.\n")
    if getattr(args, "open", False):
        from tep_core.contribute import validate_contribution_payload

        violations = validate_contribution_payload(payload)
        if violations:
            sys.stderr.write(
                "contribute --open: payload failed the local pre-push check; not pushing:\n"
            )
            for violation in violations:
                sys.stderr.write(f"  - {violation}\n")
            return 1
        _open_submission_flow(payload_text, submission_id, digest, now)
    return 0


def _open_submission_flow(payload_text: str, submission_id: str, digest: str, now) -> None:
    """`grift contribute --open` (#49 follow-up): open the submission flow.

    Preferred path (gh + git available): create a fork branch locally with the
    payload committed (payload + manifest line), push it to the user's fork,
    and open the compare URL — the browser shows a ready PR with files already
    attached; the user only presses "Create pull request".
    Fallback: open the intake repo's new-PR page in the browser.

    This explicit ``--open`` path performs clone/fork/push operations with the
    user's own gh/git credentials; the user still presses the final PR button.
    """
    import shlex
    import shutil
    import subprocess
    import tempfile
    import urllib.parse
    import urllib.request

    INTAKE = "https://github.com/Cor-Incorporated/tep-contributions"
    received_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    branch = f"contrib/{submission_id}"
    title = f"contribution: {submission_id}"
    body = (
        f"Opt-in TEP contribution (door: pr).\n\n"
        f"- payload: `payloads/{now.year}/{submission_id}.json`\n"
        f"- sha256: `{digest}`\n"
    )
    gh = shutil.which("gh")
    git = shutil.which("git")
    if not (gh and git):
        # F-1: fallback lands on the intake repository (a real page) — the old
        # compare/main...new URL was invalid. Manual attach per CONTRIBUTING.
        url = f"{INTAKE}#how-to-submit"
        _open_browser(url)
        sys.stderr.write(
            "opened the intake repository in your browser — attach "
            f"{GRIFT_DIR / 'contribution.json'} as payloads/{now.year}/{submission_id}.json "
            "(gh CLI not found for the automated branch flow)\n"
        )
        return

    def run(
        cmd: list[str], cwd: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"{' '.join(shlex.quote(c) for c in cmd)}\n{result.stderr.strip()}")
        return result

    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = str(Path(tmp) / "tep-contributions")
            run([git, "clone", "--quiet", "--depth", "1", f"{INTAKE}.git", repo_dir])
            year_dir = Path(repo_dir) / "payloads" / str(now.year)
            year_dir.mkdir(parents=True, exist_ok=True)
            (year_dir / f"{submission_id}.json").write_text(payload_text, encoding="utf-8")
            # C: PRs add payload + sidecar meta only; manifest.jsonl is
            # regenerated on main (single writer) — no append conflicts
            meta = year_dir / f"{submission_id}.meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "id": submission_id,
                        "sha256": digest,
                        "received_at": received_at,
                        "door": "pr",
                    },
                    ensure_ascii=False,
                    indent=1,
                )
                + "\n",
                encoding="utf-8",
            )
            run([git, "-C", repo_dir, "config", "user.name", "grift-contribute"])
            run(
                [git, "-C", repo_dir, "config", "user.email", "contribute@users.noreply.github.com"]
            )
            run([git, "-C", repo_dir, "checkout", "--quiet", "-b", branch])
            run([git, "-C", repo_dir, "add", "-A"])
            run([git, "-C", repo_dir, "commit", "--quiet", "-m", title])
            # fork (idempotent) using the user's credentials; the intake README
            # already discloses that --open may auto-create the fork (B-3)
            run([gh, "repo", "fork", INTAKE, "--clone=false"], check=False)
            user = run([gh, "api", "user", "--jq", ".login"]).stdout.strip()
            fork_url = f"https://github.com/{user}/tep-contributions.git"
            if fork_url.rstrip(".git") == INTAKE:
                raise RuntimeError("push target resolved to the intake origin; refusing")
            # B-3: push ONLY the single contribution branch to the user's fork;
            # never push to origin (the clone's origin stays untouched).
            run([git, "-C", repo_dir, "remote", "add", "fork", fork_url])
            run([git, "-C", repo_dir, "push", "--quiet", "fork", branch])
            compare = (
                f"{INTAKE}/compare/{urllib.parse.quote(branch)}"
                f"?expand=1&title={urllib.parse.quote(title)}"
                f"&body={urllib.parse.quote(body)}"
            )
            _open_browser(compare)
            sys.stderr.write(
                f"branch `{branch}` pushed to your fork ({user}/tep-contributions).\n"
                "browser opened at the PR creation page — payload and manifest line are "
                "already committed; press 'Create pull request' to submit.\n"
            )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        sys.stderr.write(f"automated flow failed ({exc}); falling back to the browser\n")
        _open_browser(f"{INTAKE}#how-to-submit")


def _open_browser(url: str) -> None:
    import platform
    import subprocess

    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", url], check=False)
    elif system == "Windows":
        subprocess.run(["cmd", "/c", "start", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


def _run_attest(args: argparse.Namespace) -> int:
    from tep_core.attest import (
        AttestationError,
        CosignSigningConfig,
        SSHSigningConfig,
        create_attestation_bundle,
    )

    preflight = verify_report(
        args.report,
        args.repo,
        args.identity,
        project_path=args.project,
        forge_export=args.forge_export,
        tracker_export=args.tracker_export,
        actor_id=args.actor_id,
        actor_report_path=args.actor_report,
        project_report_path=args.project_report,
        reference_manifest=args.reference_manifest,
        public_evidence_path=args.public_evidence,
    )
    if preflight.status != VERIFIED:
        sys.stderr.write(
            "attest: refusing to sign a report that does not independently recompute "
            f"({preflight.status})\n"
        )
        for detail in preflight.differences or preflight.notes:
            sys.stderr.write(f"  - {detail}\n")
        return 1 if preflight.status == MISMATCH else 2
    if args.sign == "ssh":
        if args.ssh_key is None or args.principal is None:
            sys.stderr.write("attest: --sign ssh requires --ssh-key and --principal\n")
            return 2
        if any(
            value is not None
            for value in (
                args.cosign_key,
                args.cosign_public_key,
                args.certificate_identity,
                args.certificate_oidc_issuer,
            )
        ):
            sys.stderr.write("attest: SSH signing rejects cosign options\n")
            return 2
        signing = SSHSigningConfig(args.ssh_key, args.principal)
    else:
        if args.ssh_key is not None or args.principal is not None:
            sys.stderr.write("attest: cosign signing rejects SSH options\n")
            return 2
        keyful = args.cosign_key is not None or args.cosign_public_key is not None
        keyless = args.certificate_identity is not None or args.certificate_oidc_issuer is not None
        if keyful and keyless:
            sys.stderr.write("attest: choose cosign keyful or keyless signing, not both\n")
            return 2
        if keyful:
            if args.cosign_key is None or args.cosign_public_key is None:
                sys.stderr.write(
                    "attest: keyful cosign requires --cosign-key and --cosign-public-key\n"
                )
                return 2
            signing = CosignSigningConfig(
                key=args.cosign_key,
                public_key=args.cosign_public_key,
            )
        else:
            if args.certificate_identity is None or args.certificate_oidc_issuer is None:
                sys.stderr.write(
                    "attest: keyless cosign requires --certificate-identity and "
                    "--certificate-oidc-issuer\n"
                )
                return 2
            signing = CosignSigningConfig(
                certificate_identity=args.certificate_identity,
                certificate_oidc_issuer=args.certificate_oidc_issuer,
            )
    try:
        bundle = create_attestation_bundle(
            args.report,
            args.out,
            signing=signing,
            repo_hint=args.repo_hint,
        )
    except AttestationError as exc:
        sys.stderr.write(f"attest: {exc}\n")
        return 2
    payload = {
        "schema_version": bundle.manifest["schema_version"],
        "bundle": str(bundle.directory),
        "statement_digest": bundle.manifest["statement"]["digest"],
        "signature": bundle.manifest["signature"],
        "notice": (
            "署名は実行主体と記録条件を証明するもので、数値の正しさ、品質、優秀さを証明しません。"
        ),
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


def _run_portfolio(args: argparse.Namespace) -> int:
    from tep_core.attest import CosignTrustPolicy, SSHTrustPolicy
    from tep_core.portfolio import (
        PortfolioValidationError,
        build_portfolio,
        publish_portfolio_artifacts,
        render_portfolio_markdown,
    )

    trust = None
    ssh_selected = args.allowed_signers is not None or args.principal is not None
    cert_selected = (
        args.certificate_identity is not None or args.certificate_oidc_issuer is not None
    )
    key_selected = args.cosign_public_key is not None
    if sum(bool(value) for value in (ssh_selected, cert_selected, key_selected)) > 1:
        sys.stderr.write("portfolio: specify exactly one SSH or cosign trust policy\n")
        return 2
    if ssh_selected:
        if args.allowed_signers is None or args.principal is None:
            sys.stderr.write("portfolio: SSH trust requires --allowed-signers and --principal\n")
            return 2
        trust = SSHTrustPolicy(args.allowed_signers, args.principal)
    elif cert_selected:
        if args.certificate_identity is None or args.certificate_oidc_issuer is None:
            sys.stderr.write(
                "portfolio: keyless cosign trust requires certificate identity and OIDC issuer\n"
            )
            return 2
        trust = CosignTrustPolicy(
            certificate_identity=args.certificate_identity,
            certificate_oidc_issuer=args.certificate_oidc_issuer,
        )
    elif key_selected:
        trust = CosignTrustPolicy(public_key=args.cosign_public_key)

    try:
        payload = build_portfolio(args.manifest, trust_policy=trust)
        markdown = render_portfolio_markdown(payload)
        encoded = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        publish_portfolio_artifacts(
            args.out,
            json_text=encoded if args.format in {"json", "both"} else None,
            markdown_text=markdown if args.format in {"md", "both"} else None,
        )
    except PortfolioValidationError as exc:
        sys.stderr.write(f"portfolio: {exc}\n")
        return 2
    if args.format in {"json", "both"}:
        sys.stdout.write(encoded)
    if args.format in {"md", "both"}:
        if args.format == "both":
            sys.stdout.write("\n")
        sys.stdout.write(markdown)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "repo":
        return run_repo(args)
    if args.command == "actor":
        return run_actor(args)
    if args.command == "project":
        return run_project(args)
    if args.command == "align":
        return run_align(args)
    if args.command == "analyze":
        return _run_analyze(args)
    if args.command == "verify":
        return _run_verify(args)
    if args.command == "report":
        return _run_report(args)
    if args.command == "contribute":
        return _run_contribute(args)
    if args.command == "attest":
        return _run_attest(args)
    if args.command == "portfolio":
        return _run_portfolio(args)
    if args.command == "update":
        return _run_update(args)
    if args.command == "benchmark":
        return run_benchmark(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
