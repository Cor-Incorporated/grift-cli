"""`grift verify <report.json>` — recompute under the recorded provenance and
diff every field (P1g). Exit codes: 0 VERIFIED / 1 MISMATCH / 2 CANNOT_VERIFY.

Falsifiable tamper detection: one modified field must surface as a MISMATCH
line, never as a crash. Definition-version drift is reported honestly as
CANNOT_VERIFY (historical reproduction is a future feature).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tep_core.analyze import analyze_repository
from tep_core.gitutil import GitError, repository_identity, rev_parse
from tep_core.identity import (
    IdentityConfig,
    load_identity,
    load_subject_identity,
)
from tep_core.lineage import Lineage

VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
CANNOT_VERIFY = "CANNOT_VERIFY"

# Fields that legitimately differ between runs and are excluded from diff.
VOLATILE_PATHS = {"provenance.analyzed_at"}

# Blocks that were never derived from the repository, and so have nothing to be
# recomputed from. `verify` re-derives observations and compares them; a
# declared outcome is someone's word carried beside them (W6, norms §3). The
# verifier is handed no declaration file, so recomputation returns
# not_observed and comparing this block reported a MISMATCH on every report
# that carried one -- while the report's own limitations said it was not
# recomputed. Requiring the file back would have made an unverifiable claim a
# precondition for verifying the observations.
#
# This is exactly one block, and it must stay that way: anything added here is
# an observation that stopped being checked. What follows from the exclusion is
# stated where it is read -- a modified declaration is not detected by verify
# (see DECLARATION_LIMITATION in tep_core.outcome).
NOT_RECOMPUTED_PATHS = {"outcome"}


def _excluded_from_diff(key: str) -> bool:
    """One predicate for both diff loops, so the two cannot drift apart."""
    for prefix in VOLATILE_PATHS | NOT_RECOMPUTED_PATHS:
        if key == prefix or key.startswith(prefix + "."):
            return True
    return key == "analyzed_at" or key.endswith(".analyzed_at")


@dataclass
class VerifyResult:
    status: str
    differences: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(value, path))
    else:
        flat[prefix] = node
    return flat


def verify_report(
    report_path: Path,
    repo: Path | None,
    identity_path: Path | None = None,
    *,
    project_path: Path | None = None,
    forge_export: Path | None = None,
    tracker_export: Path | None = None,
    actor_id: str | None = None,
    actor_report_path: Path | None = None,
    project_report_path: Path | None = None,
    reference_manifest: Path | None = None,
    public_evidence_path: Path | None = None,
) -> VerifyResult:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifyResult(CANNOT_VERIFY, notes=[f"report unreadable: {exc}"])
    if not isinstance(report, dict):
        return VerifyResult(CANNOT_VERIFY, notes=["report root must be an object"])

    schema = report.get("schema_version")
    if schema == "report-v2":
        from tep_core.schema_v2 import validate_report_v2

        if not isinstance(report.get("provenance"), dict):
            return VerifyResult(
                CANNOT_VERIFY,
                notes=["report-v2 provenance must be an object"],
            )
        schema_errors = validate_report_v2(report)
        if schema_errors:
            return VerifyResult(
                MISMATCH,
                differences=["report-v2 schema invalid: " + schema_errors[0]],
            )
        return _verify_v2(
            report,
            repo,
            identity_path,
            forge_export=forge_export,
            tracker_export=tracker_export,
            reference_manifest=reference_manifest,
            public_evidence_path=public_evidence_path,
        )
    if schema == "alignment-v1":
        return _verify_alignment(
            report,
            repo,
            identity_path,
            project_path=project_path,
            forge_export=forge_export,
            tracker_export=tracker_export,
            actor_id=actor_id,
            actor_report_path=actor_report_path,
            project_report_path=project_report_path,
            reference_manifest=reference_manifest,
        )
    if schema == "project-v1":
        return _verify_project(
            report,
            repo,
            project_path=project_path,
            forge_export=forge_export,
            tracker_export=tracker_export,
        )

    provenance = report.get("provenance") or {}
    sha = provenance.get("analyzed_commit_sha")
    definition_version = provenance.get("definition_version")
    scope = provenance.get("analysis_scope") or "tenant"

    if not sha or not isinstance(sha, str) or len(sha) not in {40, 64}:
        return VerifyResult(CANNOT_VERIFY, notes=["provenance.analyzed_commit_sha missing/invalid"])
    target_oid = provenance.get("target_oid")
    if isinstance(target_oid, dict) and target_oid.get("value") != sha:
        return VerifyResult(
            MISMATCH,
            differences=["provenance.target_oid.value != provenance.analyzed_commit_sha"],
        )
    if not definition_version:
        return VerifyResult(CANNOT_VERIFY, notes=["provenance.definition_version missing"])

    from tep_core.version import DEFINITION_VERSION

    if definition_version != DEFINITION_VERSION:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=[
                f"definition version {definition_version!r} is not the current "
                f"{DEFINITION_VERSION!r} — historical versions cannot be "
                "reproduced yet (compatibility table: docs/report-schema.md)"
            ],
        )

    if repo is None:
        return VerifyResult(CANNOT_VERIFY, notes=["target repository not provided"])
    if not (repo / ".git").exists():
        return VerifyResult(CANNOT_VERIFY, notes=[f"not a git repository: {repo}"])

    analyze_repo, blocked, worktree = _repo_for_sha(
        repo,
        sha,
        reuse_matching_checkout=True,
    )
    if blocked is not None:
        return blocked
    lineage = Lineage(
        is_fork=bool(report.get("lineage", {}).get("is_fork")),
        parent=report.get("lineage", {}).get("parent"),
    )
    identity: IdentityConfig
    try:
        if identity_path is not None:
            identity = load_identity(identity_path)
        else:
            identity = load_subject_identity(analyze_repo, None, revision=sha)
    except Exception as exc:  # noqa: BLE001
        _cleanup_worktree(repo, worktree)
        return VerifyResult(CANNOT_VERIFY, notes=[f"identity load failed: {exc}"])

    try:
        recomputed = analyze_repository(analyze_repo, identity, lineage, scope=scope)
    except Exception as exc:  # noqa: BLE001
        _cleanup_worktree(repo, worktree)
        return VerifyResult(CANNOT_VERIFY, notes=[f"recomputation failed: {exc}"])
    # A detached verification worktree has a generated directory name.  The
    # legacy report-v1 repository block describes the source checkout, so
    # reconstruct that block from the supplied repository without reading any
    # analysis input from its working tree.
    recomputed["repository"] = repository_identity(
        repo.resolve(),
        include_local_path="path" in (report.get("repository") or {}),
    )
    _cleanup_worktree(repo, worktree)

    left = _flatten(report)
    right = _flatten(recomputed)
    differences: list[str] = []
    for key in sorted(set(left) | set(right)):
        if _excluded_from_diff(key):
            continue
        if left.get(key) != right.get(key):
            differences.append(f"{key}: report={left.get(key)!r} recomputed={right.get(key)!r}")
    if differences:
        return VerifyResult(MISMATCH, differences=differences)
    return VerifyResult(VERIFIED)


def _diff_payloads(left_obj: dict, right_obj: dict) -> list[str]:
    left = _flatten(left_obj)
    right = _flatten(right_obj)
    differences: list[str] = []
    for key in sorted(set(left) | set(right)):
        if _excluded_from_diff(key):
            continue
        if left.get(key) != right.get(key):
            differences.append(f"{key}: report={left.get(key)!r} recomputed={right.get(key)!r}")
    return differences


def _repo_for_sha(
    repo: Path,
    sha: str,
    *,
    reuse_matching_checkout: bool = False,
) -> tuple[Path, VerifyResult | None, Path | None]:
    """Return a detached fixed-tree checkout for a recorded SHA.

    New fixed-OID schemas must not reuse the caller's checkout even when its
    HEAD is the recorded commit: dirty tracked files and untracked observation
    inputs are outside that commit and therefore outside the recorded
    provenance.  Legacy report-v1 is the compatibility exception.  It has
    historically observed the current checkout (including test-framework
    files), so an immediately generated report remains reproducible while HEAD
    still equals the recorded SHA.
    """

    repo = repo.resolve()
    if reuse_matching_checkout:
        try:
            if rev_parse(repo) == sha:
                return repo, None, None
        except GitError:
            pass

    from tep_core.revision import RevisionError, materialize_fixed_revision

    try:
        fixed = materialize_fixed_revision(repo, sha)
    except (RevisionError, OSError) as exc:
        return (
            repo,
            VerifyResult(
                CANNOT_VERIFY,
                notes=[f"recorded SHA {sha[:8]} not reachable or cannot be materialized: {exc}"],
            ),
            None,
        )
    return fixed.worktree, None, fixed.worktree


def _resolve_manifest(provenance: dict, reference_manifest: Path | None) -> Path | None:
    if reference_manifest is not None:
        return reference_manifest
    recorded = provenance.get("reference_manifest")
    if not recorded:
        return None
    name = Path(str(recorded)).name
    digest = provenance.get("reference_manifest_digest")
    candidates = [
        Path(name),
        Path.cwd() / name,
        Path.cwd() / "benchmarks" / "v060" / name,
    ]
    from tep_core.digest import file_digest

    for candidate in candidates:
        if not candidate.is_file():
            continue
        if digest and file_digest(candidate) != digest:
            continue
        return candidate
    return None


def _check_manifest(provenance: dict, reference_manifest: Path | None) -> VerifyResult | None:
    recorded = provenance.get("reference_manifest_digest")
    if not recorded:
        return None
    path = _resolve_manifest(provenance, reference_manifest)
    if path is None:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=["CANNOT_VERIFY: benchmark manifest is unavailable or different"],
        )
    from tep_core.digest import file_digest

    if file_digest(path) != recorded:
        return VerifyResult(MISMATCH, differences=["provenance.reference_manifest_digest"])
    return None


def _verify_saved_alignment(
    report: dict,
    *,
    actor_report_path: Path | None,
    project_report_path: Path | None,
    reference_manifest: Path | None,
) -> VerifyResult:
    from tep_core.alignment import alignment_payload
    from tep_core.digest import file_digest

    if actor_report_path is None or project_report_path is None:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=["saved-report alignment requires --actor-report and --project-report"],
        )
    try:
        actor_report = json.loads(actor_report_path.read_text(encoding="utf-8"))
        project_report = json.loads(project_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifyResult(CANNOT_VERIFY, notes=[f"saved report unreadable: {exc}"])
    actor_card: dict | None = None
    if actor_report.get("schema_version") == "actor-card-v1":
        # Formal collection path: actors/<safe-id>.json cards are first-class
        # alignment inputs. Convert deterministically (no format guessing) and
        # mirror the align --actor-dir provenance merge so recomputation and
        # the recorded card digest both match the collection layout.
        from tep_core.actor_directory import actor_report_from_card

        actor_card = actor_report
        converted = actor_report_from_card(actor_report)
        repo_json = actor_report_path.parent.parent / "repo-report.json"
        if not repo_json.is_file():
            repo_json = actor_report_path.parent / "repo-report.json"
        if not repo_json.is_file():
            # Read-only compatibility with pre-v0.6 actor directories.
            repo_json = actor_report_path.parent.parent / "report.json"
        if not repo_json.is_file():
            repo_json = actor_report_path.parent / "report.json"
        if repo_json.is_file():
            try:
                repo_report = json.loads(repo_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                repo_report = {}
            converted["provenance"] = {
                **(repo_report.get("provenance") or {}),
                **(converted.get("provenance") or {}),
            }
        # The collection-level report contributes fixed-revision provenance,
        # but it must not change the actor input's semantic scope.  Mirror the
        # normalization performed by align --actor-dir before recomputation so
        # the same card remains an actor-cluster observation during replay.
        from tep_core.actor_basis import actor_analysis_scope

        actor_subject = converted.get("subject") or {}
        actor_provenance = dict(converted.get("provenance") or {})
        actor_provenance["analysis_scope"] = actor_analysis_scope(
            actor_subject.get("selection"),
            actor_subject.get("attribution_state"),
        )
        if actor_subject.get("selection") == "inferred_actor":
            actor_provenance["identity_digest"] = None
        converted["provenance"] = actor_provenance
        actor_report = converted
    notes = _saved_schema_notes(
        report,
        actor_report,
        project_report,
        actor_card=actor_card,
    )
    if notes:
        return VerifyResult(CANNOT_VERIFY, notes=notes)
    actor_digest = file_digest(actor_report_path)
    project_digest = file_digest(project_report_path)
    diffs = _saved_alignment_field_diffs(
        report, actor_report, project_report, actor_digest, project_digest
    )
    blocked = _check_manifest(report.get("provenance") or {}, reference_manifest)
    if blocked is not None:
        return blocked
    recomputed = alignment_payload(
        actor_report=actor_report,
        declared=project_report.get("declared") or {},
        provenance=report.get("provenance") or {},
        subject=report.get("subject") or {},
        limitations=list(report.get("limitations") or []),
        project_report=project_report,
        actor_report_digest=actor_digest,
        project_report_digest=project_digest,
    )
    diffs.extend(_diff_payloads(report, recomputed))
    if diffs:
        return VerifyResult(MISMATCH, differences=diffs)
    return VerifyResult(VERIFIED)


def _saved_schema_notes(
    report: dict,
    actor_report: dict,
    project_report: dict,
    *,
    actor_card: dict | None = None,
) -> list[str]:
    from tep_core.schema import validate_schema
    from tep_core.schema_v2 import validate_alignment, validate_project, validate_report_v2

    notes: list[str] = []
    # A strict actor-card is the signed/hashed alignment input.  Its temporary
    # report-v2 adapter deliberately has no legacy surface/rhythm observations,
    # so validate the closed card schema rather than treating that adapter as a
    # persisted full report.  Persisted report-v2 inputs keep their legacy
    # validation path for compatibility.
    actor_errors = (
        validate_schema("actor-card-v1", actor_card)
        if actor_card is not None
        else validate_report_v2(actor_report)
    )
    project_errors = validate_project(project_report)
    align_errors = validate_alignment(report)
    if actor_errors:
        notes.append("actor report schema: " + actor_errors[0])
    if project_errors:
        notes.append("project report schema: " + project_errors[0])
    if align_errors:
        notes.append("alignment schema: " + align_errors[0])
    return notes


def _saved_alignment_field_diffs(
    report: dict,
    actor_report: dict,
    project_report: dict,
    actor_digest: str,
    project_digest: str,
) -> list[str]:
    diffs: list[str] = []
    actor_prov = actor_report.get("provenance") or {}
    project_prov = project_report.get("provenance") or {}
    prov = report.get("provenance") or {}
    if report.get("actor_report_digest") != actor_digest:
        diffs.append("actor_report_digest")
    if report.get("project_report_digest") != project_digest:
        diffs.append("project_report_digest")
    pairs = (
        (
            "provenance.actor_commit_sha",
            prov.get("actor_commit_sha"),
            actor_prov.get("analyzed_commit_sha"),
        ),
        (
            "provenance.project_commit_sha",
            prov.get("project_commit_sha"),
            project_prov.get("analyzed_commit_sha"),
        ),
        (
            "provenance.identity_digest",
            prov.get("identity_digest"),
            actor_prov.get("identity_digest"),
        ),
        (
            "provenance.definition_version",
            prov.get("definition_version"),
            actor_prov.get("definition_version"),
        ),
        ("provenance.role_lens", prov.get("role_lens"), actor_prov.get("role_lens")),
        ("provenance.vendor_scan", prov.get("vendor_scan"), actor_prov.get("vendor_scan")),
        ("provenance.survival", prov.get("survival"), actor_prov.get("survival")),
        (
            "forge input digest",
            (prov.get("input_digests") or {}).get("forge"),
            (actor_prov.get("input_digests") or {}).get("forge"),
        ),
        (
            "tracker input digest",
            (prov.get("input_digests") or {}).get("tracker"),
            (actor_prov.get("input_digests") or {}).get("tracker"),
        ),
        ("git_window", prov.get("git_window"), actor_prov.get("git_window")),
        ("event_window", prov.get("event_window"), actor_prov.get("event_window")),
    )
    for name, left, right in pairs:
        if left != right:
            diffs.append(name)
    return diffs


def _cleanup_worktree(repo: Path, worktree: Path | None) -> None:
    if worktree is None:
        return
    from tep_core.revision import remove_fixed_revision_worktree

    remove_fixed_revision_worktree(repo, worktree)


def _verify_v2(
    report: dict,
    repo: Path | None,
    identity_path: Path | None,
    *,
    forge_export: Path | None,
    tracker_export: Path | None,
    reference_manifest: Path | None = None,
    public_evidence_path: Path | None = None,
) -> VerifyResult:
    from tep_core.analyze_v2 import analyze_subject
    from tep_core.identity import select_actor
    from tep_core.version import DEFINITION_VERSION

    provenance = report.get("provenance") or {}
    blocked_manifest = _check_manifest(provenance, reference_manifest)
    if blocked_manifest is not None:
        return blocked_manifest
    reference_manifest = _resolve_manifest(provenance, reference_manifest)
    sha = provenance.get("analyzed_commit_sha")
    if not sha or not isinstance(sha, str) or len(sha) not in {40, 64}:
        return VerifyResult(CANNOT_VERIFY, notes=["provenance.analyzed_commit_sha missing/invalid"])
    target_oid = provenance.get("target_oid")
    if isinstance(target_oid, dict) and target_oid.get("value") != sha:
        return VerifyResult(
            MISMATCH,
            differences=["provenance.target_oid.value != provenance.analyzed_commit_sha"],
        )
    if provenance.get("definition_version") != DEFINITION_VERSION:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=[
                f"definition version {provenance.get('definition_version')!r} is not the current "
                f"{DEFINITION_VERSION!r}"
            ],
        )
    if repo is None or not (repo / ".git").exists():
        return VerifyResult(CANNOT_VERIFY, notes=["target repository not provided"])
    analyze_repo, blocked, worktree = _repo_for_sha(repo, sha)
    if blocked is not None:
        return blocked
    lineage = Lineage(
        is_fork=bool((provenance.get("lineage") or report.get("lineage") or {}).get("is_fork")),
        parent=(provenance.get("lineage") or report.get("lineage") or {}).get("parent"),
    )
    public_manifest: dict[str, Any] | None = None
    public_reconciliation: dict[str, Any] | None = None
    public_digest = provenance.get("public_evidence_digest")
    if public_digest is not None:
        if public_evidence_path is None:
            _cleanup_worktree(repo, worktree)
            return VerifyResult(
                CANNOT_VERIFY,
                notes=["recorded public evidence bundle was not supplied"],
            )
        from tep_core.forge_public import GitObjectId
        from tep_core.public_evidence import (
            load_public_evidence,
            read_fixed_history_oids,
            reconcile_commit_coverage,
            verify_public_evidence,
        )

        checked = verify_public_evidence(public_evidence_path)
        if checked.get("status") != VERIFIED:
            _cleanup_worktree(repo, worktree)
            return VerifyResult(
                MISMATCH if checked.get("status") == MISMATCH else CANNOT_VERIFY,
                differences=(
                    [f"public evidence: {checked.get('reason') or 'mismatch'}"]
                    if checked.get("status") == MISMATCH
                    else []
                ),
                notes=(
                    [f"public evidence: {checked.get('reason') or 'cannot verify'}"]
                    if checked.get("status") != MISMATCH
                    else []
                ),
            )
        try:
            public_manifest = load_public_evidence(public_evidence_path)
            if public_manifest.get("bundle_payload_sha256") != public_digest:
                raise ValueError("public evidence digest differs from report provenance")
            target = GitObjectId(**public_manifest["target_oid"])
            if target.value != sha:
                raise ValueError("public evidence target differs from report target")
            public_reconciliation = reconcile_commit_coverage(
                public_manifest, read_fixed_history_oids(analyze_repo, target)
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            _cleanup_worktree(repo, worktree)
            return VerifyResult(MISMATCH, differences=[str(exc)])
        if public_reconciliation.get("status") == "mismatch":
            _cleanup_worktree(repo, worktree)
            return VerifyResult(
                MISMATCH,
                differences=["public evidence Git OID population mismatch"],
            )
    try:
        identity = (
            load_identity(identity_path)
            if identity_path is not None
            else load_subject_identity(analyze_repo, None, revision=sha)
        )
        subject = report.get("subject") or {}
        if subject.get("kind") == "actor":
            if subject.get("selection") == "inferred_actor":
                identity, actor_mismatch = _reconstruct_inferred_actor_identity(
                    analyze_repo,
                    identity,
                    lineage,
                    actor_id=str(subject.get("canonical_id") or ""),
                    canonical_origin=_canonical_origin(report, public_manifest),
                    sha_to_accounts=_public_accounts_for_attribution(public_manifest),
                    fetched_account_count=_public_account_count_for_recompute(
                        report, public_manifest
                    ),
                )
                if actor_mismatch is not None:
                    _cleanup_worktree(repo, worktree)
                    return actor_mismatch
            else:
                identity = select_actor(identity, str(subject.get("canonical_id")))
        as_of = provenance.get("as_of")
        if as_of is None and provenance.get("window_basis") == "explicit_as_of":
            as_of = provenance.get("observation_date")
        lens = provenance.get("role_lens") or (report.get("role_lens") or {}).get("name")
        event_window = None
        recorded_window = provenance.get("event_window") or {}
        if isinstance(recorded_window, dict) and recorded_window.get("start"):
            event_window = (str(recorded_window["start"]), str(recorded_window["end"]))
        recomputed = analyze_subject(
            analyze_repo,
            identity,
            lineage,
            repository_source=repo,
            subject_kind=str(subject.get("kind")),
            canonical_id=subject.get("canonical_id"),
            as_of=as_of,
            role_lens=lens,
            forge_export=forge_export,
            tracker_export=tracker_export,
            reference_id=provenance.get("reference_id"),
            include_files=bool(provenance.get("vendor_scan")),
            include_local_path=bool(provenance.get("include_local_path")),
            survival=bool(provenance.get("survival")),
            event_window=event_window,
            reference_manifest=reference_manifest,
            sha_to_accounts=_public_accounts_for_attribution(public_manifest),
            fetched_login_count=_public_account_count_for_recompute(report, public_manifest),
            canonical_origin=_canonical_origin(report, public_manifest),
            public_evidence_digest=(
                None if public_manifest is None else public_manifest.get("bundle_payload_sha256")
            ),
            public_evidence_coverage=_public_coverage_observation(
                public_manifest, public_reconciliation
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _cleanup_worktree(repo, worktree)
        return VerifyResult(CANNOT_VERIFY, notes=[f"recomputation failed: {exc}"])
    _cleanup_worktree(repo, worktree)
    differences = _diff_payloads(report, recomputed)
    if differences:
        return VerifyResult(MISMATCH, differences=differences)
    if public_reconciliation is not None and public_reconciliation.get("status") == "partial":
        return VerifyResult(
            CANNOT_VERIFY,
            notes=["public evidence is replayable but its Git OID coverage is partial"],
        )
    return VerifyResult(VERIFIED)


def _reconstruct_inferred_actor_identity(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    actor_id: str,
    canonical_origin: str | None,
    sha_to_accounts: dict[str, Any] | None,
    fetched_account_count: int | None,
) -> tuple[IdentityConfig, VerifyResult | None]:
    """Recreate an inferred actor from the fixed repo-local Git partition.

    The actor command first partitions the full fixed-OID repository history,
    then analyzes one selected cluster through a synthetic one-actor identity.
    Verification must repeat that first step; selecting the actor from an
    empty identity file cannot reproduce an identityless actor report.

    This deliberately delegates all clustering to ``build_attribution_index``:
    fixed-tree mailmap and explicit identity aliases may join records, while
    provider handles/names never create, merge, or split actors.
    """

    from tep_core.analyze import prepare_inputs
    from tep_core.attribution import (
        build_attribution_index,
        derive_repo_scope_digest,
        find_actor,
        read_mailmap_at_revision,
        synthetic_identity,
    )
    from tep_core.gitutil import coauthor_shas, rev_parse

    commits, origin = prepare_inputs(
        repo,
        identity,
        lineage,
        include_files=True,
        scope="repo",
    )
    target = rev_parse(repo)
    mailmap = read_mailmap_at_revision(repo, target)
    repo_scope_digest, _object_format = derive_repo_scope_digest(
        commits,
        canonical_origin,
    )
    index = build_attribution_index(
        commits,
        origin,
        identity,
        sha_to_accounts=sha_to_accounts,
        fetched_login_count=fetched_account_count,
        mailmap=mailmap,
        mailmap_present=mailmap.present,
        coauthor_shas=coauthor_shas(repo),
        repo_scope_digest=repo_scope_digest,
        canonical_origin=canonical_origin,
    )
    actor = find_actor(index, actor_id)
    if actor is None:
        return identity, VerifyResult(
            MISMATCH,
            differences=[
                f"subject.canonical_id: reported inferred actor {actor_id!r} "
                "is not present in the fixed Git actor partition"
            ],
        )
    return synthetic_identity(actor), None


def _canonical_origin(report: dict[str, Any], public_manifest: dict[str, Any] | None) -> str | None:
    if public_manifest is not None:
        source = public_manifest.get("source")
        if isinstance(source, dict) and isinstance(source.get("sanitized_remote"), str):
            return source["sanitized_remote"]
    repository = report.get("repository")
    if isinstance(repository, dict) and isinstance(repository.get("remote"), str):
        return repository["remote"]
    return None


def _public_accounts_for_attribution(
    manifest: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if manifest is None or manifest.get("account_linkage") == "unsupported":
        return None
    mapping = manifest.get("sha_to_account")
    return mapping if isinstance(mapping, dict) else None


def _public_account_count(manifest: dict[str, Any] | None) -> int | None:
    from tep_core.public_evidence import manifest_fetched_login_count

    return manifest_fetched_login_count(manifest)


def _public_account_count_for_recompute(
    _report: dict[str, Any], manifest: dict[str, Any] | None
) -> int | None:
    """Recompute only account counts backed by a replayed CAS manifest."""

    if manifest is not None:
        return _public_account_count(manifest)
    # A recognized remote without an explicit public-evidence bundle still has
    # no observed account population.  Treating that as zero would turn
    # not-requested enrichment into a measured absence.
    return None


def _public_coverage_observation(
    manifest: dict[str, Any] | None,
    reconciliation: dict[str, Any] | None,
) -> dict[str, Any]:
    if manifest is None or reconciliation is None:
        return {"kind": "not_observed", "reason": "public_evidence_not_provided"}
    status = str((manifest.get("coverage") or {}).get("status") or "not_requested")
    common = {
        "status": status,
        "unit": "coverage_status",
        "expected_count": reconciliation.get("expected_count"),
        "observed_count": reconciliation.get("observed_count"),
        "missing_count": len(reconciliation.get("missing") or []),
        "extra_count": len(reconciliation.get("extra") or []),
        "duplicate_count": len(reconciliation.get("duplicates") or []),
        "account_linkage": manifest.get("account_linkage"),
    }
    if status == "complete" and reconciliation.get("status") == "complete":
        return {"kind": "observed", "value": status, **common}
    return {
        "kind": "not_proven",
        "reason": "public_evidence_incomplete_or_mismatched",
        **common,
    }


def _verify_alignment(
    report: dict,
    repo: Path | None,
    identity_path: Path | None,
    *,
    project_path: Path | None,
    forge_export: Path | None,
    tracker_export: Path | None,
    actor_id: str | None,
    actor_report_path: Path | None = None,
    project_report_path: Path | None = None,
    reference_manifest: Path | None = None,
) -> VerifyResult:
    from tep_core.alignment import alignment_payload
    from tep_core.analyze_v2 import analyze_subject
    from tep_core.digest import file_digest
    from tep_core.identity import identity_digest, select_actor
    from tep_core.project import declared_view, load_project_toml
    from tep_core.version import DEFINITION_VERSION

    provenance = report.get("provenance") or {}
    if provenance.get("definition_version") != DEFINITION_VERSION:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=["definition version is not current"],
        )
    subject = report.get("subject") or {}
    if subject.get("mode") == "saved_reports":
        return _verify_saved_alignment(
            report,
            actor_report_path=actor_report_path,
            project_report_path=project_report_path,
            reference_manifest=reference_manifest,
        )
    if repo is None or project_path is None:
        return VerifyResult(
            CANNOT_VERIFY, notes=["repo and --project are required for alignment-v1"]
        )
    sha = provenance.get("analyzed_commit_sha") or provenance.get("actor_commit_sha")
    if not isinstance(sha, str) or len(sha) not in {40, 64}:
        return VerifyResult(CANNOT_VERIFY, notes=["alignment target OID missing/invalid"])
    analyze_repo, blocked, worktree = _repo_for_sha(repo, sha)
    if blocked is not None:
        return blocked
    canonical = actor_id or subject.get("actor_canonical_id")
    if not canonical:
        _cleanup_worktree(repo, worktree)
        return VerifyResult(CANNOT_VERIFY, notes=["actor id missing"])
    try:
        identity = (
            load_identity(identity_path)
            if identity_path is not None
            else load_subject_identity(
                analyze_repo,
                None,
                revision=rev_parse(analyze_repo),
            )
        )
        selected = select_actor(identity, str(canonical))
        loaded = load_project_toml(project_path)
        declared = declared_view(loaded)
        as_of = provenance.get("as_of")
        if as_of is None and provenance.get("window_basis") == "explicit_as_of":
            as_of = provenance.get("observation_date")
        actor_report = analyze_subject(
            analyze_repo,
            selected,
            Lineage(),
            repository_source=repo,
            subject_kind="actor",
            canonical_id=str(canonical),
            as_of=as_of,
            role_lens=provenance.get("role_lens"),
            forge_export=forge_export,
            tracker_export=tracker_export,
            include_files=bool(provenance.get("vendor_scan")),
            survival=bool(provenance.get("survival")),
            reference_id=provenance.get("reference_id"),
        )
        recomputed = alignment_payload(
            actor_report=actor_report,
            declared=declared,
            provenance={
                **provenance,
                "analyzed_commit_sha": actor_report["provenance"]["analyzed_commit_sha"],
                "observation_date": actor_report["provenance"]["observation_date"],
                "window_basis": actor_report["provenance"]["window_basis"],
                "identity_digest": identity_digest(selected),
                "input_digests": {
                    **(actor_report["provenance"].get("input_digests") or {}),
                    "project": file_digest(project_path),
                },
            },
            subject=subject,
            limitations=list(report.get("limitations") or []),
        )
    except Exception as exc:  # noqa: BLE001
        _cleanup_worktree(repo, worktree)
        return VerifyResult(CANNOT_VERIFY, notes=[f"recomputation failed: {exc}"])
    _cleanup_worktree(repo, worktree)
    differences = _diff_payloads(report, recomputed)
    if differences:
        return VerifyResult(MISMATCH, differences=differences)
    return VerifyResult(VERIFIED)


def _verify_project(
    report: dict,
    repo: Path | None,
    *,
    project_path: Path | None,
    forge_export: Path | None,
    tracker_export: Path | None,
) -> VerifyResult:
    from tep_core.analyze_v2 import analyze_subject
    from tep_core.digest import file_digest
    from tep_core.identity import empty_identity
    from tep_core.project import build_project_report, declared_view, load_project_toml
    from tep_core.schema_v2 import validate_project
    from tep_core.version import DEFINITION_VERSION, __version__

    errors = validate_project(report)
    if errors:
        return VerifyResult(CANNOT_VERIFY, notes=["project-v1 schema invalid: " + errors[0]])
    observed = report.get("observed") or {}
    provenance = report.get("provenance") or {}
    if observed.get("kind") != "observed":
        if project_path is None:
            return VerifyResult(
                CANNOT_VERIFY,
                notes=["declared-only project-v1 needs --project to check the TOML digest"],
            )
        recorded = (provenance.get("input_digests") or {}).get("project")
        digest = file_digest(project_path)
        if recorded and recorded != digest:
            return VerifyResult(MISMATCH, differences=["provenance.input_digests.project"])
        return VerifyResult(VERIFIED)
    sha = provenance.get("analyzed_commit_sha")
    if not sha or repo is None:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=["observed project-v1 requires analyzed_commit_sha and --repo"],
        )
    analyze_repo, blocked, worktree = _repo_for_sha(repo, sha)
    if blocked is not None:
        return blocked
    try:
        as_of = provenance.get("as_of")
        if as_of is None and provenance.get("window_basis") == "explicit_as_of":
            as_of = provenance.get("observation_date")
        evidence = analyze_subject(
            analyze_repo,
            empty_identity(),
            Lineage(),
            repository_source=repo,
            subject_kind="repo",
            as_of=as_of,
            forge_export=forge_export,
            tracker_export=tracker_export,
            include_files=bool(provenance.get("vendor_scan")),
            survival=bool(provenance.get("survival")),
            reference_id=provenance.get("reference_id"),
        )
        declared = report.get("declared") or {}
        if project_path is not None:
            declared = declared_view(load_project_toml(project_path))
        recomputed = build_project_report(
            declared=declared,
            observed={
                "kind": "observed",
                "unit": "profile",
                "definition_version": evidence["provenance"]["definition_version"],
                "surface_profile": evidence["surface_profile"],
                "change_rhythm": evidence["change_rhythm"],
                "verification_profile": evidence["verification_profile"],
                "coordination_profile": evidence["coordination_profile"],
                "event_observation": evidence.get("event_observation"),
                "event_rhythm": evidence.get("event_rhythm"),
                "tracker_lifecycle": evidence.get("tracker_lifecycle"),
                "input_coverage": evidence["input_coverage"],
            },
            provenance={
                **provenance,
                "analyzed_commit_sha": evidence["provenance"]["analyzed_commit_sha"],
                "observation_date": evidence["provenance"]["observation_date"],
                "window_basis": evidence["provenance"]["window_basis"],
                "definition_version": DEFINITION_VERSION,
                "tool_version": __version__,
            },
            subject=report.get("subject") or {},
            limitations=list(report.get("limitations") or []),
        )
    except Exception as exc:  # noqa: BLE001
        _cleanup_worktree(repo, worktree)
        return VerifyResult(CANNOT_VERIFY, notes=[f"recomputation failed: {exc}"])
    _cleanup_worktree(repo, worktree)
    differences = _diff_payloads(report.get("observed") or {}, recomputed.get("observed") or {})
    if differences:
        return VerifyResult(MISMATCH, differences=differences)
    return VerifyResult(VERIFIED)
