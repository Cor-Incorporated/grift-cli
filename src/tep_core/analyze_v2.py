"""Assemble report-v2 evidence. report-v1 meaning is left unchanged."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from tep_core.activity import activity_metrics
from tep_core.actor_basis import actor_analysis_scope, actor_basis_notices
from tep_core.actor_directory import actor_directory_payload
from tep_core.analyze import analyze_repository, prepare_inputs
from tep_core.archive_events import empty_event_observation, summarize_archive
from tep_core.attribution import (
    MailmapSnapshot,
    build_attribution_index,
    derive_repo_scope_digest,
    read_mailmap_at_revision,
)
from tep_core.coordination import coordination_profile
from tep_core.event_rhythm import empty_event_rhythm, event_rhythm
from tep_core.gitutil import (
    GitCommit,
    GitError,
    apply_numstat,
    coauthor_shas,
    read_numstat,
    remote_url,
    repository_identity,
    rev_parse,
)
from tep_core.forge_public import GitObjectId
from tep_core.forge import summarize_forge_export, summarize_forge_rhythm
from tep_core.identity import IdentityConfig, identity_digest
from tep_core.lineage import Lineage
from tep_core.local_inputs import ForgeInput, TrackerInput, load_forge_input, load_tracker_input
from tep_core.context_profile import HISTORY_INCOMPLETE_REASON
from tep_core.observation import NotObserved, Observed
from tep_core.origin import OriginResult
from tep_core.outcome import load_outcome_input, outcome_payload
from tep_core.public_evidence import collect_revision_license_evidence
from tep_core.dates import parse_day
from tep_core.rhythm import change_rhythm, commit_timestamp
from tep_core.role_lens import role_lens_payload, validate_role_lens
from tep_core.revision import describe_revision
from tep_core.scope import population_shas
from tep_core.secrets_guard import InputValidationError
from tep_core.source_binding import (
    SourceBinding,
    assert_binding_matches,
    assert_subject_binding,
    source_binding_payload,
)
from tep_core.surface_profile import surface_profile
from tep_core.tagset import reachable_tagset_digest
from tep_core.tests_observed import observe_test_frameworks
from tep_core.tracker_lifecycle import summarize_lifecycle
from tep_core.tracker import summarize_tracker_export
from tep_core.v2_constants import (
    ACTIVITY_DENOMINATOR_NOTE,
    EVIDENCE_DISCLAIMER,
    FORGE_NOT_OBSERVED_NOTE,
    RHYTHM_LIMITATION,
    TRACKER_NOT_OBSERVED_NOTE,
)
from tep_core.role_profile import ROLE_PROFILE_DEFINITION_VERSION
from tep_core.verification_profile import verification_profile
from tep_core.version import (
    ACTIVITY_DEFINITION_VERSION,
    DEFINITION_VERSION,
    ORIGIN_DEFINITION_VERSION,
    REPORT_V2_SCHEMA_VERSION,
    __version__,
)


def resolve_observation(commits: list[GitCommit], as_of: str | None) -> tuple[str, str]:
    if as_of:
        return as_of, "explicit_as_of"
    if commits:
        return commits[0].date, "legacy_head_date"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return now, "legacy_head_date"


def scoped_commits(commits: list[GitCommit], origin: OriginResult, scope: str) -> list[GitCommit]:
    shas = population_shas(commits, origin, scope)
    return [commit for commit in commits if commit.sha in shas]


_TENANT_WITH_MERGES = frozenset({"tenant_unique", "tenant_merge_or_sync", "upstream_sync"})


def scoped_commits_with_merges(
    commits: list[GitCommit], origin: OriginResult, scope: str
) -> list[GitCommit]:
    if scope == "repo":
        return [commit for commit in commits if origin.classes_by_sha.get(commit.sha) != "bot"]
    if scope == "actor_cluster":
        return [commit for commit in commits if commit.sha in origin.actor_cluster_shas]
    return [
        commit for commit in commits if origin.classes_by_sha.get(commit.sha) in _TENANT_WITH_MERGES
    ]


def _coverage(forge: ForgeInput | None, tracker: TrackerInput | None) -> dict[str, Any]:
    if forge is None:
        forge_block: dict[str, Any] = {
            "kind": "not_observed",
            "reason": "forge_export_not_provided",
            "provided": False,
        }
    else:
        forge_block = {
            "kind": "observed",
            "value": True,
            "unit": "boolean",
            "provided": True,
            "digest": forge.digest,
            "source_format": forge.source_format,
        }
        if forge.export is not None and forge.export.binding is not None:
            forge_block["binding"] = source_binding_payload(forge.export.binding)
    if tracker is None:
        tracker_block: dict[str, Any] = {
            "kind": "not_observed",
            "reason": "tracker_export_not_provided",
            "provided": False,
        }
    else:
        tracker_block = {
            "kind": "observed",
            "value": True,
            "unit": "boolean",
            "provided": True,
            "digest": tracker.digest,
            "source_format": tracker.source_format,
            "fixture_kind": tracker.fixture_kind,
        }
        if tracker.export is not None and tracker.export.binding is not None:
            tracker_block["binding"] = source_binding_payload(tracker.export.binding)
    return {
        "git": {"kind": "observed", "value": True, "unit": "boolean", "provided": True},
        "forge": forge_block,
        "tracker": tracker_block,
    }


def _limitations(
    *,
    subject_kind: str,
    forge: ForgeInput | None,
    tracker: TrackerInput | None,
    inferred: bool = False,
    attribution_state: str | None = None,
) -> list[str]:
    notes = [EVIDENCE_DISCLAIMER, RHYTHM_LIMITATION]
    if subject_kind == "actor":
        notes.extend(
            actor_basis_notices(
                "inferred_actor" if inferred else "explicit_actor",
                attribution_state,
            )
        )
    if forge is None:
        notes.append(FORGE_NOT_OBSERVED_NOTE)
    if tracker is None:
        notes.append(TRACKER_NOT_OBSERVED_NOTE)
    if tracker is not None and tracker.fixture_kind == "synthetic_contract":
        notes.append("tracker fixture_kind=synthetic_contract. Not an external measurement.")
    if forge is not None and forge.archive is not None:
        notes.append("GH Archive events have no actor identity and are not DORA lead time.")
    return notes


def _digest_payload(domain: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + encoded).hexdigest()


def _strict_window(git_window: dict[str, Any], window_basis: str) -> dict[str, str]:
    return {
        "start": str(git_window["start"]),
        "end": str(git_window["end"]),
        "unit": "date-range",
        "basis": window_basis,
    }


def _consent_not_observed(actor_id: str, definition_version: str) -> dict[str, Any]:
    return {
        "kind": "not_observed",
        "actor_id": actor_id,
        "reason": "consenting_actor_required",
        "definition_version": definition_version,
        "limitations": [
            "This observation requires an explicit actor-matched tenant consent record."
        ],
    }


def _event_blocks(
    subject_kind: str, forge: ForgeInput | None, *, canonical_id: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if forge is None:
        reason = "forge_export_not_provided"
        return empty_event_observation(reason), empty_event_rhythm(reason)
    if forge.export is not None:
        actor_filter = None if subject_kind == "repo" else canonical_id
        return (
            summarize_forge_export(forge.export, canonical_id=actor_filter),
            summarize_forge_rhythm(forge.export, canonical_id=actor_filter),
        )
    if forge.archive is None:
        reason = "forge_export_not_provided"
        return empty_event_observation(reason), empty_event_rhythm(reason)
    if subject_kind == "actor":
        reason = "archive_events_have_no_actor_identity"
        return empty_event_observation(reason), empty_event_rhythm(reason)
    return summarize_archive(forge.archive), event_rhythm(forge.archive)


def _lifecycle_block(
    subject_kind: str, tracker: TrackerInput | None, *, canonical_id: str | None
) -> dict[str, Any]:
    if tracker is None:
        return {
            "kind": "not_observed",
            "reason": "tracker_export_not_provided",
            "limitations": ["Tracker lifecycle was not provided; this is not zero issues."],
        }
    if tracker.export is not None:
        actor_filter = None if subject_kind == "repo" else canonical_id
        return summarize_tracker_export(tracker.export, canonical_id=actor_filter)
    if tracker.lifecycle is None:
        return {
            "kind": "not_observed",
            "reason": "tracker_export_not_provided",
            "limitations": ["Tracker lifecycle was not provided; this is not zero issues."],
        }
    if subject_kind == "actor":
        return {
            "kind": "not_proven",
            "reason": "synthetic_contract_not_actor_evidence",
            "fixture_kind": tracker.fixture_kind,
        }
    return summarize_lifecycle(tracker.lifecycle)


def analyze_subject(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    repository_source: Path | None = None,
    subject_kind: str,
    canonical_id: str | None = None,
    as_of: str | None = None,
    role_lens: str | None = None,
    forge_export: Path | None = None,
    tracker_export: Path | None = None,
    outcome_declaration: Path | None = None,
    reference_version: str | None = None,
    reference_id: str | None = None,
    reference_manifest: Path | None = None,
    event_window: tuple[str, str] | None = None,
    public_handles: dict[str, str] | None = None,
    sha_to_login: dict[str, str] | None = None,
    sha_to_accounts: dict[str, Any] | None = None,
    fetched_login_count: int | None = None,
    canonical_origin: str | None = None,
    repo_scope_digest: str | None = None,
    mailmap: MailmapSnapshot | None = None,
    public_evidence_digest: str | None = None,
    public_evidence_coverage: dict[str, Any] | None = None,
    template_provided: bool = False,
    parent_repo_provided: bool = False,
    include_files: bool = False,
    include_local_path: bool = False,
    survival: bool = False,
    target_oid: dict[str, str] | None = None,
    revision_completeness: dict[str, bool] | None = None,
) -> dict[str, Any]:
    if subject_kind not in {"repo", "actor"}:
        raise ValueError("subject_kind must be repo or actor")
    if subject_kind == "actor" and reference_version:
        raise InputValidationError(
            "actor view refuses --reference-version; tenant values are not placed on repo distributions"
        )
    if reference_id and "role" in reference_id and subject_kind == "actor":
        from tep_core.role_validation import refuse_actor_join

        refuse_actor_join()
    lens = validate_role_lens(role_lens)
    selected_attribution_state = None
    if subject_kind == "actor" and identity.source_path is not None:
        selected_actor = next(
            (row for row in identity.actors if row.canonical_id == canonical_id), None
        )
        if selected_actor is not None:
            selected_attribution_state = selected_actor.attribution_state
    selection = (
        "repo_all_human"
        if subject_kind == "repo"
        else "explicit_actor"
        if identity.source_path is not None
        else "inferred_actor"
    )
    scope = (
        "repo"
        if subject_kind == "repo"
        else actor_analysis_scope(selection, selected_attribution_state)
    )
    empty_reason = "no_human_commits" if subject_kind == "repo" else "no_actor_commits"
    if target_oid is None or revision_completeness is None:
        described = describe_revision(repo)
        target_oid = dict(described.oid)
        revision_completeness = {
            "shallow": described.shallow,
            "promisor": described.promisor,
            "complete": described.completeness_proven,
        }
    tagset_digest = reachable_tagset_digest(repo, target_oid)

    # v0.6 subject commands consume only target-bound v2 exports.  Legacy v1,
    # GH Archive NDJSON, and tracker CSV remain readable by their legacy and
    # benchmark loaders, but may not be attached to a repo/actor/project/align
    # report where they could be mistaken for evidence from this repository.
    forge = load_forge_input(
        forge_export,
        event_window=event_window,
        require_bound=forge_export is not None,
    )
    tracker = load_tracker_input(
        tracker_export,
        event_window=event_window,
        require_bound=tracker_export is not None,
    )
    # Read from disk and digested like any other local input; nothing about it
    # is fetched, and nothing about it is verified.
    outcome = load_outcome_input(outcome_declaration)
    repository_origin = canonical_origin or remote_url(repo)
    forge_binding: SourceBinding | None = None
    tracker_binding: SourceBinding | None = None
    if forge is not None:
        forge_binding = assert_subject_binding(
            forge.export.binding if forge.export is not None else None,
            repository_origin=repository_origin,
            target_oid=target_oid,
            event_window=event_window,
            source="forge-export",
        )
    if tracker is not None:
        tracker_binding = assert_subject_binding(
            tracker.export.binding if tracker.export is not None else None,
            repository_origin=repository_origin,
            target_oid=target_oid,
            event_window=event_window,
            source="tracker-export",
        )
    if forge_binding is not None and tracker_binding is not None:
        assert_binding_matches(tracker_binding, forge_binding)
    v1 = analyze_repository(
        repo,
        identity,
        lineage,
        template_provided=template_provided,
        parent_repo_provided=parent_repo_provided,
        include_files=include_files,
        include_local_path=include_local_path,
        survival=survival,
        scope=scope,
        reference_version=reference_version if subject_kind == "repo" else None,
    )
    analyzed_oid = str((v1.get("provenance") or {}).get("analyzed_commit_sha") or "")
    if analyzed_oid != target_oid["value"]:
        raise InputValidationError(
            "repository HEAD changed before subject analysis; refusing a mixed-revision report"
        )
    commits, origin = prepare_inputs(repo, identity, lineage, include_files=True, scope=scope)
    if repo_scope_digest is None:
        repo_scope_digest, _object_format = derive_repo_scope_digest(
            commits, canonical_origin=canonical_origin
        )
    if mailmap is None:
        mailmap = read_mailmap_at_revision(repo, rev_parse(repo))
    observation_date, window_basis = resolve_observation(commits, as_of)
    cutoff = parse_day(observation_date)
    dated = [commit for commit in commits if commit_timestamp(commit).date() <= cutoff]
    selected = scoped_commits(dated, origin, scope)
    selected_with_merges = scoped_commits_with_merges(dated, origin, scope)
    try:
        numstat = read_numstat(repo)
        apply_numstat(selected, numstat)
        apply_numstat(selected_with_merges, numstat)
    except GitError:
        pass
    tests = observe_test_frameworks(repo)
    tests_observed = tests.get("kind") == "observed"
    surfaces = surface_profile(selected, empty_reason=empty_reason)
    rhythm = change_rhythm(selected, observation_date=observation_date, empty_reason=empty_reason)
    verification = verification_profile(
        selected, tests_observed=tests_observed, empty_reason=empty_reason
    )
    coordination = coordination_profile(
        selected_with_merges,
        canonical_id=canonical_id,
        forge=None if forge is None else forge.export,
        tracker=None if tracker is None else tracker.export,
        empty_reason=empty_reason,
    )
    license_evidence = collect_revision_license_evidence(
        repo,
        GitObjectId(
            str(target_oid.get("algorithm") or ""),
            str(target_oid.get("value") or ""),
        ),
    )
    coverage = _coverage(forge, tracker)
    public_forge_coverage = dict(
        public_evidence_coverage
        or {
            "kind": "not_observed",
            "reason": "public_evidence_not_provided",
        }
    )
    public_forge_coverage["repository_license"] = license_evidence
    public_forge_coverage["provider_api_terms"] = {
        "kind": "not_observed",
        "reason": "provider_api_terms_not_recorded",
    }
    coverage["public_forge"] = public_forge_coverage
    event_observation, archive_rhythm = _event_blocks(
        subject_kind, forge, canonical_id=canonical_id
    )
    lifecycle = _lifecycle_block(subject_kind, tracker, canonical_id=canonical_id)
    git_window = _git_window(observation_date)
    event_win = _declared_event_window(forge, tracker, event_window)
    coverage["git_window"] = git_window
    coverage["event_window"] = event_win or {
        "kind": "not_observed",
        "reason": "bound_export_not_provided",
    }
    if event_win is None:
        coverage["window_alignment"] = {
            "kind": "not_observed",
            "reason": "event_window_not_provided",
        }
    elif not _windows_equivalent(git_window, event_win):
        coverage["window_alignment"] = {
            "kind": "not_proven",
            "reason": "windows_not_equivalent",
            "git_window": git_window,
            "event_window": event_win,
        }
    else:
        coverage["window_alignment"] = {
            "kind": "observed",
            "value": True,
            "unit": "boolean",
        }
    tracker_win = _tracker_window(tracker)
    coverage["tracker_window"] = tracker_win or {
        "kind": "not_observed",
        "reason": "tracker_export_not_provided",
    }
    if event_win and tracker_win and tracker_win.get("kind") == "observed":
        coverage["forge_tracker_window_alignment"] = (
            {
                "kind": "observed",
                "value": True,
                "unit": "boolean",
            }
            if _windows_equivalent(event_win, tracker_win)
            else {
                "kind": "not_proven",
                "reason": "windows_not_equivalent",
                "forge_window": event_win,
                "tracker_window": tracker_win,
            }
        )
    manifest_digest = _manifest_digest(reference_manifest, reference_id)

    payload: dict[str, Any] = {
        "schema_version": REPORT_V2_SCHEMA_VERSION,
        "report_kind": "evidence",
        "subject": {
            "kind": subject_kind,
            "selection": selection,
        },
        "provenance": {
            "tool_name": "grift",
            "method_name": "TEP",
            "tool_version": __version__,
            "definition_version": DEFINITION_VERSION,
            "origin_definition_version": ORIGIN_DEFINITION_VERSION,
            "activity_definition_version": ACTIVITY_DEFINITION_VERSION,
            "analysis_scope": scope,
            "analyzed_commit_sha": rev_parse(repo),
            "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "observation_date": observation_date,
            "window_basis": window_basis,
            # An inferred actor uses an ephemeral selector reconstructed from
            # the Git partition; it is not an identity input and must not be
            # presented as one.
            "identity_digest": (
                identity_digest(identity)
                if subject_kind != "actor" or identity.source_path is not None
                else None
            ),
            "vendor_scan": bool(include_files),
            "survival": bool(survival),
            "include_local_path": bool(include_local_path),
            "as_of": as_of,
            "role_lens": lens,
            "lineage": {"is_fork": lineage.is_fork, "parent": lineage.parent},
            "event_window": event_win,
            "git_window": git_window,
            "source_format": None if forge is None else forge.source_format,
            "reference_id": reference_id,
            "reference_manifest": _portable_manifest(reference_manifest),
            "reference_manifest_digest": manifest_digest,
            "input_digests": {
                "forge": None if forge is None else forge.digest,
                "tracker": None if tracker is None else tracker.digest,
                "forge_binding": None if forge_binding is None else forge_binding.digest,
                "tracker_binding": None if tracker_binding is None else tracker_binding.digest,
                "benchmark_manifest": manifest_digest,
                "public_evidence": public_evidence_digest,
                "license_evidence": license_evidence["digest"]["value"],
                "tagset": tagset_digest,
            },
            "public_evidence_digest": public_evidence_digest,
            "tagset_digest": tagset_digest,
            "target_oid": target_oid,
            "revision_completeness": revision_completeness,
        },
        "repository": repository_identity(
            repository_source or repo, include_local_path=include_local_path
        ),
        "identity": (
            {"pending_attribution": True, "actor_count": 0}
            if subject_kind == "actor" and identity.source_path is None
            else v1["identity"]
        ),
        "lineage": v1["lineage"],
        "origin": v1["origin"],
        "attribution": v1["attribution"],
        "activity": v1["activity"],
        "actor_directory": {"observed_count": 0, "actors": []},
        "experience": v1.get("experience")
        or _consent_not_observed(canonical_id or "repo", "experience-v1"),
        "role_profile": v1.get("role_profile")
        or _consent_not_observed(canonical_id or "repo", ROLE_PROFILE_DEFINITION_VERSION),
        # Describes the libraries the actor introduced, not the actor. Carried
        # beside their observations, never folded into them (W4, norms §7).
        "library_context": v1.get("library_context")
        or NotObserved("consenting_actor_required").to_dict(),
        # What happened after the work, for the part git cannot see. Always
        # kind="declared" or not_observed -- never an observation (W6).
        "outcome": outcome_payload(outcome),
        "core_activity_period": v1["core_activity_period"],
        "test_frameworks": v1["test_frameworks"],
        "test_cochange": v1["test_cochange"],
        "rework": v1["rework"],
        "survival": v1["survival"],
        "context_profile": v1["context_profile"],
        "surface_profile": surfaces,
        "change_rhythm": rhythm,
        "verification_profile": verification,
        "coordination_profile": coordination,
        "event_observation": event_observation,
        "event_rhythm": archive_rhythm,
        "tracker_lifecycle": lifecycle,
        "role_lens": role_lens_payload(lens),
        "input_coverage": coverage,
        "limitations": _limitations(
            subject_kind=subject_kind,
            forge=forge,
            tracker=tracker,
            inferred=subject_kind == "actor" and identity.source_path is None,
            attribution_state=selected_attribution_state,
        ),
        "notices": _limitations(
            subject_kind=subject_kind,
            forge=forge,
            tracker=tracker,
            inferred=subject_kind == "actor" and identity.source_path is None,
            attribution_state=selected_attribution_state,
        ),
    }
    if not revision_completeness["complete"]:
        payload["limitations"].append(
            "The source is shallow or promisor-backed; full reachable-history "
            "completeness is not proven."
        )
    if revision_completeness["shallow"]:
        # Says what the truncation actually did to the numbers, so a reader is
        # not left to infer it from the flag above.
        payload["limitations"].append(
            "The commit graph is truncated, so repository-wide counts, spans and "
            "actor totals are reported as not_observed rather than measured from "
            "the fetched slice."
        )
    index = build_attribution_index(
        selected_with_merges,
        origin,
        identity,
        public_handles=public_handles,
        sha_to_login=sha_to_login,
        sha_to_accounts=sha_to_accounts,
        fetched_login_count=fetched_login_count,
        mailmap=mailmap,
        mailmap_present=mailmap.present,
        coauthor_shas=coauthor_shas(repo),
        repo_scope_digest=repo_scope_digest,
        canonical_origin=canonical_origin,
    )
    directory = actor_directory_payload(index, human_commit_count=len(selected))
    for actor_row in directory.get("actors") or []:
        if isinstance(actor_row, dict):
            actor_row.pop("internal_actor_id", None)
    payload["actor_directory"] = directory
    attr = {
        **(v1.get("attribution") or {}),
        **(directory.get("attribution") or {}),
    }
    origin_unresolved = 0
    if hasattr(origin, "counts"):
        origin_unresolved = int((origin.counts or {}).get("unresolved") or 0)
    attr["origin_unresolved_commit_count"] = origin_unresolved
    payload["attribution"] = attr
    directory["attribution"] = attr

    normalized_window = _strict_window(git_window, window_basis)
    nonmerge_count = sum(not commit.is_merge for commit in selected_with_merges)
    merge_count = sum(commit.is_merge for commit in selected_with_merges)
    human_commit_count = nonmerge_count + merge_count
    population_body: dict[str, Any] = {
        "actor_count": int(directory["observed_count"]),
        "human_commit_count": human_commit_count,
        "nonmerge_commit_count": nonmerge_count,
        "merge_commit_count": merge_count,
        "basis": "git_primary_author_cluster",
        "partition_digest": {
            "algorithm": "sha256",
            "value": index.partition_digest,
        },
    }
    population_body["population_digest"] = {
        "algorithm": "sha256",
        "value": _digest_payload("tep-population-v1", population_body),
    }
    payload["target"] = {"oid": dict(target_oid)}
    payload["population"] = population_body
    payload["window"] = normalized_window
    payload["metrics"] = {
        "human_nonmerge_commit_share": {
            "kind": "observed",
            "value": round(nonmerge_count / human_commit_count, 4) if human_commit_count else 0.0,
            "numerator": nonmerge_count,
            "denominator": human_commit_count,
            "unit": "commit_share",
            "window": normalized_window,
            "definition_version": DEFINITION_VERSION,
            "limitations": [
                "This is a population accounting ratio, not a quality or productivity score."
            ],
        }
    }
    if subject_kind == "repo":
        # Experience and role are tenant-consent observations, never public
        # repository enrichment.
        payload["experience"] = _consent_not_observed("repo", "experience-v1")
        payload["role_profile"] = _consent_not_observed("repo", ROLE_PROFILE_DEFINITION_VERSION)
        payload["library_context"] = NotObserved("consenting_actor_required").to_dict()
        payload["activity"] = _repo_activity(
            v1.get("activity") or {},
            selected,
            identity,
            history_complete=not revision_completeness["shallow"],
        )
        context = dict(v1.get("context_profile") or {})
        # The directory is built from the same truncated history, so this
        # override must respect the degradation v1 already applied — otherwise
        # it silently restores the count context_profile just suppressed.
        if not revision_completeness["shallow"]:
            context["resolved_human_actors"] = Observed(
                directory["observed_count"], "actors"
            ).to_dict()
        payload["context_profile"] = context
    if subject_kind == "actor":
        payload["subject"]["canonical_id"] = canonical_id
        payload["subject"]["actor_id"] = canonical_id
        payload["subject"]["selection"] = selection
        if selected_attribution_state is not None:
            payload["subject"]["attribution_state"] = selected_attribution_state
        # A no-consent observation is still bound to the selected repo-local
        # actor.  ``unresolved`` described the absence of a consenting tenant
        # identity in the v1 collector, not an unknown CLI selection.
        for key in ("experience", "role_profile"):
            detail = payload.get(key)
            if (
                isinstance(detail, dict)
                and detail.get("kind") == "not_observed"
                and detail.get("reason") == "consenting_actor_required"
                and canonical_id
            ):
                detail["actor_id"] = canonical_id
        if scope == "actor_cluster":
            payload["activity"] = _actor_cluster_activity(v1.get("activity") or {})
            cluster_note = (
                "actor_cluster is a repo-local Git primary-author cluster; it does not "
                "assert consent, personhood, or cross-repository identity. Legacy "
                "origin keys named tenant_* are classification vocabulary only."
            )
            payload["limitations"].append(cluster_note)
        else:
            payload["activity"] = _tenant_actor_activity(v1.get("activity") or {})
        payload["notices"] = [
            *actor_basis_notices(
                payload["subject"]["selection"],
                selected_attribution_state,
            ),
            EVIDENCE_DISCLAIMER,
            *([cluster_note] if scope == "actor_cluster" else []),
        ]
    else:
        payload["notices"] = [EVIDENCE_DISCLAIMER]
        if reference_id or reference_version:
            payload["interpretation"] = v1["interpretation"]
    if reference_id:
        payload["reference"] = _reference_block(
            reference_id,
            payload.get("event_rhythm") or payload.get("change_rhythm") or {},
            reference_manifest,
        )
    final_revision = describe_revision(repo)
    if final_revision.oid != target_oid:
        raise InputValidationError(
            "repository HEAD changed during subject analysis; refusing a mixed-revision report"
        )
    if reachable_tagset_digest(repo, target_oid) != tagset_digest:
        raise InputValidationError(
            "reachable tag set changed during subject analysis; refusing mixed provenance"
        )
    return payload


def _git_window(observation_date: str) -> dict[str, Any]:
    from datetime import timedelta

    end = parse_day(observation_date)
    start = end - timedelta(days=180)
    return {"start": start.isoformat(), "end": observation_date, "days": 180, "unit": "days"}


def _tracker_window(tracker: Any) -> dict[str, Any] | None:
    if tracker is None:
        return None
    if tracker.export is not None and tracker.export.binding is not None:
        binding = tracker.export.binding
        return {
            "kind": "observed",
            "unit": "utc_date_range",
            "value": f"{binding.window.start[:10]}/{binding.window.end[:10]}",
            "start": binding.window.start[:10],
            "end": binding.window.end[:10],
            "source_format": tracker.source_format,
            "binding_digest": binding.digest,
            "coverage_status": binding.coverage.status,
        }
    if tracker.lifecycle is None:
        return None
    stamps = [row.created_at or row.release_at or row.closed_at for row in tracker.lifecycle.rows]
    present = [item for item in stamps if item is not None]
    if not present:
        return {"kind": "not_observed", "reason": "tracker_timestamps_missing"}
    start = min(present).date().isoformat()
    end = max(present).date().isoformat()
    return {
        "kind": "observed",
        "unit": "utc_date_range",
        "value": f"{start}/{end}",
        "start": start,
        "end": end,
        "source_format": tracker.source_format,
    }


def _declared_event_window(
    forge: Any, tracker: Any, requested: tuple[str, str] | None
) -> dict[str, Any] | None:
    archive_win = None
    if forge is not None and forge.export is not None and forge.export.binding is not None:
        binding = forge.export.binding
        archive_win = {
            "start": binding.window.start[:10],
            "end": binding.window.end[:10],
            "source_format": forge.source_format,
        }
    elif forge is not None and forge.archive is not None:
        archive_win = {
            "start": forge.archive.window_start[:10],
            "end": forge.archive.window_end[:10],
            "source_format": forge.source_format,
        }
    elif tracker is not None and tracker.export is not None and tracker.export.binding is not None:
        binding = tracker.export.binding
        archive_win = {
            "start": binding.window.start[:10],
            "end": binding.window.end[:10],
            "source_format": tracker.source_format,
        }
    if requested is None:
        return archive_win
    if archive_win is not None and (
        archive_win["start"] != requested[0] or archive_win["end"] != requested[1]
    ):
        raise InputValidationError(
            "event window does not match forge/tracker window "
            f"(requested {requested[0]}/{requested[1]}, "
            f"observed {archive_win['start']}/{archive_win['end']})"
        )
    return {
        "start": requested[0],
        "end": requested[1],
        "source_format": (archive_win or {}).get("source_format") or "cli_event_window",
    }


def _repo_activity(
    legacy: dict[str, Any],
    selected: list[GitCommit],
    identity: IdentityConfig,
    *,
    history_complete: bool = True,
) -> dict[str, Any]:
    """Repo-wide activity counts.

    On a truncated clone these count the slice that was fetched, not the
    repository: `--depth 50` on urllib3 yields 38 commits over 24 active days
    against a true 3,533 over 1,488. Absolute counts and rates therefore
    degrade to not_observed, while HEAD-anchored facts survive (G3 finding).
    """
    dates = [item.date for item in selected]
    computed = activity_metrics(dates, Counter(dates), head_date=dates[0] if dates else None)
    tenant = None if identity.pending_attribution else legacy.get("tenant_commits")
    nonmerge = computed.get("tenant_commits")

    def depth_dependent(observation: Any) -> Any:
        if history_complete:
            return observation
        return NotObserved(HISTORY_INCOMPLETE_REASON).to_dict()

    return {
        "scope": "repo",
        "population": "human_nonmerge",
        "repo_commits": depth_dependent(nonmerge),
        "repo_human_nonmerge_commits": depth_dependent(nonmerge),
        "repo_active_days": depth_dependent(computed.get("active_days")),
        "tenant_commits": depth_dependent(tenant) if tenant is not None else tenant,
        "active_days": depth_dependent(computed.get("active_days")),
        "commits_per_active_day": depth_dependent(computed.get("commits_per_active_day")),
        "commits_per_active_day_median": depth_dependent(
            computed.get("commits_per_active_day_median")
        ),
        "active_days_13w": depth_dependent(computed.get("active_days_13w")),
        "denominator_note": ACTIVITY_DENOMINATOR_NOTE,
    }


def _actor_cluster_activity(legacy: dict[str, Any]) -> dict[str, Any]:
    """Rename the selected-cluster denominator without leaking tenant semantics."""

    return {
        "scope": "actor_cluster",
        "population": "repo_local_git_primary_author_cluster",
        "actor_cluster_commits": legacy.get("tenant_commits"),
        "tenant_commits": None,
        "active_days": legacy.get("active_days"),
        "commits_per_active_day": legacy.get("commits_per_active_day"),
        "commits_per_active_day_median": legacy.get("commits_per_active_day_median"),
        "active_days_13w": legacy.get("active_days_13w"),
        "denominator_note": (
            "actor_cluster_commits counts selected primary-author non-merge commits; "
            "it is not a consenting tenant population"
        ),
    }


def _tenant_actor_activity(legacy: dict[str, Any]) -> dict[str, Any]:
    """Make the explicit-identity population machine-readable."""

    return {
        **legacy,
        "scope": "tenant",
        "population": "explicit_identity_nonmerge",
        "denominator_note": (
            "tenant_commits counts explicit identity-matched non-merge commits; "
            "the scope label is not proof of consent or personhood"
        ),
    }


def _windows_equivalent(git_window: dict[str, Any], event_window: dict[str, Any]) -> bool:
    return git_window.get("start") == event_window.get("start") and git_window.get(
        "end"
    ) == event_window.get("end")


def _portable_manifest(reference_manifest: Path | None) -> str | None:
    from tep_core.benchmark import portable_manifest_ref

    return portable_manifest_ref(reference_manifest)


def _manifest_digest(reference_manifest: Path | None, reference_id: str | None) -> str | None:
    if reference_manifest is None and not reference_id:
        return None
    from tep_core.benchmark import load_manifest
    from tep_core.digest import file_digest

    manifest = load_manifest(reference_manifest)
    return file_digest(Path(str(manifest["_manifest_path"])))


def _reference_block(
    source_id: str, observed_profile: dict[str, Any], manifest_path: Path | None
) -> dict[str, Any]:
    from tep_core.benchmark import attach_reference, find_entry, load_manifest

    manifest = load_manifest(manifest_path)
    entry = find_entry(manifest, source_id)
    share = (observed_profile or {}).get("active_day_share")
    comparison = attach_reference(
        source_id=source_id,
        observed=share,
        metric_id="rhythm.active_day_share",
        limitations=[
            "Reference metadata is not a pass/fail threshold.",
            "Git or forge event time is not production delivery time.",
        ],
        missing=["production_deployments"],
        interpretation="observed rhythm only",
        manifest_path=manifest_path,
    )
    return {
        "catalog": entry,
        "comparisons": [comparison],
        "limitations": list(entry.get("do_not_use_for") or [])
        + list(entry.get("quality_notes") or []),
    }
