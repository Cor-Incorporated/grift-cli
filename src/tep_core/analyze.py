"""Assemble a provenance-bearing TEP report."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tep_core.activity import activity_metrics
from tep_core.cochange import test_cochange
from tep_core.context_profile import build_context_profile
from tep_core.core_period import compute_core_activity_period
from tep_core.gitutil import (
    GitError,
    coauthor_shas,
    read_commits,
    remote_url,
    repository_identity,
    rev_parse,
)
from tep_core.identity import (
    RECORDED_EXPLICIT_CONSENT,
    IdentityConfig,
    has_recorded_explicit_consent,
    load_identity,
)
from tep_core.lineage import Lineage
from tep_core.observation import NotObserved, Observed
from tep_core.origin import classify_commits
from tep_core.reference import interpret_metric
from tep_core.revision import commit_history_complete
from tep_core.rework import rework_metrics
from tep_core.scope import DEFAULT_SCOPE, population_shas
from tep_core.survival import survival_metrics
from tep_core.tests_observed import observe_test_frameworks
from tep_core.version import (
    ACTIVITY_DEFINITION_VERSION,
    DEFINITION_VERSION,
    ORIGIN_DEFINITION_VERSION,
    REPORT_SCHEMA_VERSION,
    __version__,
)


def prepare_inputs(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    include_files: bool = False,
    scope: str = DEFAULT_SCOPE,
) -> tuple[list, Any]:
    """Read commits and classify origin once. Shared by report and export
    so both consumers see identical per-commit classification (WP-P1e ruling)."""
    repo = repo.resolve()
    commits = read_commits(repo, include_files=False)
    if include_files:
        _attach_files(repo, commits)
    origin = classify_commits(commits, _classification_identity(identity), lineage)
    need_paths = (
        include_files or scope in {"repo", "actor_cluster"} or origin.counts["tenant_unique"] > 0
    )
    if not include_files and need_paths:
        _attach_files(repo, commits)
    return commits, origin


def _classification_identity(identity: IdentityConfig) -> IdentityConfig:
    """Retain source-declared bots while analyzing one selected tenant actor.

    ``grift actor`` narrows a multi-actor identity to the requested row so other
    human actors cannot enter the tenant population.  Bot declarations are
    classification inputs rather than tenant subjects, however, and dropping
    them would silently turn custom automation into human history.  Reload only
    those closed bot rows from the already selected identity source.
    """

    if (
        identity.source_path is None
        or identity.email_patterns
        or len(identity.actors) != 1
        or not identity.source_path.is_file()
    ):
        return identity
    full_identity = load_identity(identity.source_path)
    selected_ids = {actor.canonical_id for actor in identity.actors}
    declared_bots = tuple(
        actor
        for actor in full_identity.actors
        if actor.attribution_state == "bot" and actor.canonical_id not in selected_ids
    )
    if not declared_bots:
        return identity
    return IdentityConfig(
        schema_version=identity.schema_version,
        email_patterns=(),
        actors=(*identity.actors, *declared_bots),
        source_path=identity.source_path,
        pending_attribution=False,
    )


def _attach_files(repo: Path, commits: list) -> None:
    try:
        named = read_commits(repo, include_files=True)
        files_by_sha = {item.sha: item.files for item in named}
        for commit in commits:
            commit.files = files_by_sha.get(commit.sha, ())
    except GitError:
        pass


def analyze_repository(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    template_provided: bool = False,
    parent_repo_provided: bool = False,
    include_files: bool = False,
    include_local_path: bool = False,
    survival: bool = False,
    scope: str = DEFAULT_SCOPE,
    reference_version: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    commits, origin = prepare_inputs(
        repo, identity, lineage, include_files=include_files, scope=scope
    )
    # A shallow or promisor clone makes every depth-dependent repo metric a
    # statement about the truncation rather than the repository (G3 finding).
    history_complete = commit_history_complete(repo)
    tests = observe_test_frameworks(repo)
    tests_observed = tests.get("kind") == "observed"
    head_sha = rev_parse(repo)
    head_date = commits[0].date if commits else None
    if scope == "actor_cluster":
        actor_shas = population_shas(commits, origin, scope)
        activity_dates = [commit.date for commit in commits if commit.sha in actor_shas]
        activity_day_counts = Counter(activity_dates)
    else:
        activity_dates = origin.tenant_dates
        activity_day_counts = origin.tenant_day_counts
    activity = activity_metrics(activity_dates, activity_day_counts, head_date=head_date)
    cochange = test_cochange(
        commits,
        origin,
        tests_observed=tests_observed,
        pending_attribution=identity.pending_attribution,
        head_date=head_date,
        scope=scope,
    )
    rework = rework_metrics(
        commits,
        origin,
        pending_attribution=identity.pending_attribution,
        scope=scope,
    )
    corr = rework.get("corrective_rework_rate") if rework.get("kind") == "observed" else rework
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "provenance": {
            "tool_name": "grift",
            "method_name": "TEP",
            "tool_version": __version__,
            "definition_version": DEFINITION_VERSION,
            "origin_definition_version": ORIGIN_DEFINITION_VERSION,
            "activity_definition_version": ACTIVITY_DEFINITION_VERSION,
            "analysis_scope": scope,
            "analyzed_commit_sha": head_sha,
            "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "repository": repository_identity(repo, include_local_path=include_local_path),
        "identity": {
            "pending_attribution": identity.pending_attribution,
            "actor_count": identity.actor_count,
        },
        "lineage": lineage.to_dict(),
        "origin": origin.origin_observations(
            template_provided=template_provided,
            parent_repo_provided=parent_repo_provided,
            has_upstream_lineage=lineage.has_upstream_lineage,
        ),
        "attribution": {
            "bot": Observed(origin.bot_commits, "commits").to_dict(),
        },
        "activity": activity,
        "core_activity_period": compute_core_activity_period(activity_dates),
        "test_frameworks": tests,
        "test_cochange": cochange,
        "rework": rework,
        "survival": survival_metrics(repo, enabled=survival),
        "context_profile": build_context_profile(
            repo, commits, origin, history_complete=history_complete
        ),
        "interpretation": {
            "test_cochange": interpret_metric(
                report_scope=scope,
                metric_id="test_cochange",
                observation=cochange,
                reference_version=reference_version,
            ),
            "corrective_rework": interpret_metric(
                report_scope=scope,
                metric_id="corrective_rework",
                observation=corr,
                reference_version=reference_version,
            ),
        },
    }
    if scope == "tenant":
        experience, role_profile, context = _tenant_experience(repo, commits, origin, identity)
        report["experience"] = experience
        report["role_profile"] = role_profile
        report["library_context"] = context
    return report


_COLLECTION_FAILURE_LIMITATION = {
    "history_incomplete": (
        "The fixed history is shallow, promisor-backed, or missing required Git "
        "objects; grift did not fetch them implicitly."
    ),
    "experience_collection_timeout": (
        "Experience collection exceeded its Git subprocess budget on this repository; "
        "no partial observation is emitted. This is a budget limit, not an absence of work."
    ),
}

_INCOMPLETE_MARKERS = ("lazy fetching disabled", "promisor remote")
_TIMEOUT_MARKER = "timed out"


def _collection_failure_reason(message: str) -> str | None:
    """Map a collection failure to a report reason, or None to re-raise.

    Only these two degradations are absorbed. Anything else must surface: a
    silent not_observed would hide a real defect behind a missing observation.
    """
    if any(marker in message for marker in _INCOMPLETE_MARKERS):
        return "history_incomplete"
    if _TIMEOUT_MARKER in message:
        return "experience_collection_timeout"
    return None


def _tenant_experience(
    repo: Path,
    commits: list,
    origin: Any,
    identity: IdentityConfig,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Collect one explicitly declared tenant actor, or state why it is absent.

    Returns the actor's experience, their role profile, and the prevalence of
    the libraries they introduced -- the last describing libraries, not them.
    """

    from tep_core.attribution import (
        build_attribution_index,
        derive_repo_scope_digest,
        read_mailmap_at_revision,
    )
    from tep_core.ai_identity import load_ai_identities_at_revision
    from tep_core.experience import (
        EXPERIENCE_DEFINITION_VERSION,
        TenantConsent,
        build_experience,
    )
    from tep_core.experience_collect import (
        ExperienceCollectionError,
        ExperienceHistoryIncomplete,
        collect_dependency_introductions,
        collect_experience_inputs,
    )
    from tep_core.prevalence import library_context
    from tep_core.role_profile import ROLE_PROFILE_DEFINITION_VERSION, build_role_profile

    actor_id = "unresolved"
    consent = None
    explicit_actor = (
        identity.actors[0]
        if (
            identity.source_path is not None
            and not identity.email_patterns
            and len(identity.actors) == 1
        )
        else None
    )
    if explicit_actor is not None:
        actor_id = explicit_actor.canonical_id
    if explicit_actor is not None and has_recorded_explicit_consent(explicit_actor):
        consent = TenantConsent(
            actor_id,
            f"identity_file_explicit_consent:{RECORDED_EXPLICIT_CONSENT}",
        )
    if consent is None:
        return (
            build_experience((), actor_id=actor_id, consent=None),
            build_role_profile((), actor_id=actor_id, consent=None),
            NotObserved("consenting_actor_required").to_dict(),
        )

    target = rev_parse(repo)
    ai_identities = load_ai_identities_at_revision(repo, target)
    mailmap = read_mailmap_at_revision(repo, target)
    scope_digest, _object_format = derive_repo_scope_digest(commits, remote_url(repo))
    index = build_attribution_index(
        commits,
        origin,
        identity,
        mailmap=mailmap,
        mailmap_present=mailmap.present,
        coauthor_shas=coauthor_shas(repo),
        repo_scope_digest=scope_digest,
        canonical_origin=remote_url(repo),
    )
    sha_to_actor = dict(index.sha_to_actor)
    bot_actor = "__grift_bot__"
    for commit in commits:
        if origin.classes_by_sha.get(commit.sha) == "bot":
            sha_to_actor[commit.sha] = bot_actor
    tagger_map = {
        email.strip().casefold(): actor.canonical_id
        for actor in identity.actors
        for email in actor.emails
    }
    tagger_digest_map = {
        digest.casefold(): actor.canonical_id
        for actor in identity.actors
        for digest in actor.email_sha256
    }
    try:
        collection = collect_experience_inputs(
            repo,
            revision=target,
            sha_to_actor=sha_to_actor,
            bot_actor_ids=(bot_actor,),
            tagger_actor_by_email=tagger_map,
            tagger_actor_by_email_sha256=tagger_digest_map,
            snapshot_actor_ids=(actor_id,),
        )
    except ExperienceCollectionError as exc:
        # Incomplete history carries its own exception type, so it is recognised
        # by type rather than by matching a message; the collection timeout has
        # no dedicated type and is still identified by its marker.
        reason = (
            "history_incomplete"
            if isinstance(exc, ExperienceHistoryIncomplete)
            else _collection_failure_reason(str(exc))
        )
        if reason is None:
            raise
        limitation = _COLLECTION_FAILURE_LIMITATION[reason]
        return (
            {
                "kind": "not_observed",
                "actor_id": actor_id,
                "reason": reason,
                "definition_version": EXPERIENCE_DEFINITION_VERSION,
                "limitations": [limitation],
            },
            {
                "kind": "not_observed",
                "actor_id": actor_id,
                "reason": reason,
                "definition_version": ROLE_PROFILE_DEFINITION_VERSION,
                "limitations": [limitation],
            },
            NotObserved(reason).to_dict(),
        )
    # Which libraries this actor first declared. Scanned from manifests at fixed
    # revisions, so it stays deterministic; a scan failure degrades the axis to
    # not_observed rather than reporting an absence of choices (W2).
    try:
        dependencies = collect_dependency_introductions(repo, revision=target)
    except ExperienceCollectionError as exc:
        if _collection_failure_reason(str(exc)) is None:
            raise
        dependencies = None

    experience = build_experience(
            collection.commits,
            actor_id=actor_id,
            consent=consent,
            ai_coauthor_emails=ai_identities.emails,
            ai_coauthor_email_sha256=ai_identities.email_sha256,
            release_tags=collection.release_tags,
            dependency_introductions=(
                dependencies.introduced if dependencies is not None else None
            ),
            dependency_manifest_commits=(
                dependencies.manifest_commits if dependencies is not None else None
            ),
            dependency_unparseable=(
                dependencies.unparseable if dependencies is not None else None
            ),
    )
    # W4: how common each of those libraries is, as a separate axis. Read back
    # out of the observation that named them, so the two blocks cannot drift
    # into describing different sets. Nothing here is combined with the actor's
    # measurements -- it describes libraries (norms §7).
    introduction = (experience.get("metrics") or {}).get("dependency_introduction") or {}
    names = introduction.get("values") if introduction.get("kind") == "observed" else None
    context = library_context(
        names or (),
        ecosystems_by_name=(dependencies.ecosystems if dependencies is not None else None),
    )
    return (
        experience,
        build_role_profile(
            collection.commits,
            actor_id=actor_id,
            consent=consent,
            release_tags=collection.release_tags,
        ),
        context,
    )
