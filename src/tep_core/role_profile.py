"""Four-dimensional, non-ranking role observations for a consented actor.

The profile is descriptive.  Categories may overlap because a commit can, for
example, touch both tests and core, or be both corrective and dependency work.
No category is collapsed to a job title, score, fit or ordering.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, Sequence

from tep_core.experience import (
    DEFAULT_MIN_POPULATION,
    ExperienceCommit,
    ExperienceInputError,
    ReleaseTag,
    TenantConsent,
    as_utc,
    classify_domain,
    is_dependency_path,
    is_test_path,
    observation_window,
    ordered_commits,
)
from tep_core.rework import is_corrective_subject

ROLE_PROFILE_DEFINITION_VERSION = "role-profile-v1.1-2026-09-02"

DOMAIN_CATEGORIES = ("core", "test", "docs", "infra", "deps", "unclassified")
WORK_TYPE_CATEGORIES = ("create", "modify", "rename", "test", "dependency", "corrective")
TIME_PHASE_CATEGORIES = ("early", "middle", "recent")
PROCESS_POSITION_CATEGORIES = ("creator", "maintainer", "integrator", "release")

__all__ = [
    "DOMAIN_CATEGORIES",
    "PROCESS_POSITION_CATEGORIES",
    "ROLE_PROFILE_DEFINITION_VERSION",
    "TIME_PHASE_CATEGORIES",
    "WORK_TYPE_CATEGORIES",
    "build_role_profile",
    "classify_domain",
]


def _role_metric(
    numerator: int,
    denominator: int,
    *,
    window: dict[str, str | None],
    min_population: int,
    limitation: str,
    unit: str,
) -> dict[str, object]:
    common: dict[str, object] = {
        "denominator": denominator,
        "unit": unit,
        "window": dict(window),
        "definition_version": ROLE_PROFILE_DEFINITION_VERSION,
        "limitations": [limitation],
    }
    if denominator < min_population:
        return {"kind": "not_observed", "reason": "insufficient_population", **common}
    return {
        "kind": "observed",
        "value": round(numerator / denominator, 4),
        "numerator": numerator,
        **common,
    }


def _dimension(
    categories: Sequence[str],
    counts: Counter[str],
    denominator: int,
    *,
    window: dict[str, str | None],
    min_population: int,
    limitation: str,
    unit: str = "commit_share",
) -> dict[str, dict[str, object]]:
    return {
        category: _role_metric(
            counts[category],
            denominator,
            window=window,
            min_population=min_population,
            limitation=limitation,
            unit=unit,
        )
        for category in categories
    }


def _time_phase(timestamp: datetime, start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None or end <= start:
        return "recent"
    elapsed = (timestamp - start).total_seconds()
    span = (end - start).total_seconds()
    if elapsed < span / 3:
        return "early"
    if elapsed < span * 2 / 3:
        return "middle"
    return "recent"


def build_role_profile(
    commits: Iterable[ExperienceCommit],
    *,
    actor_id: str,
    consent: TenantConsent | None,
    release_tags: Iterable[ReleaseTag] = (),
    observation_end: datetime | str | None = None,
    min_population: int = DEFAULT_MIN_POPULATION,
) -> dict[str, object]:
    """Build domain/work/time/process observations without classifying a role."""

    if min_population < 1:
        raise ExperienceInputError("min_population must be positive")
    if consent is None or consent.actor_id != actor_id:
        return {
            "kind": "not_observed",
            "actor_id": actor_id,
            "reason": "consenting_actor_required",
            "definition_version": ROLE_PROFILE_DEFINITION_VERSION,
            "limitations": [
                "Role observations require an explicit, actor-matched tenant consent record.",
                "Public identity and provider account data are not consent.",
            ],
        }

    rows = ordered_commits(commits)
    start, end, window = observation_window(rows, observation_end)

    target = [commit for commit in rows if commit.actor_id == actor_id and not commit.is_bot]
    nonmerge = [commit for commit in target if not commit.is_merge]

    # early/middle/recent divide the actor's own tenure, not the repository's
    # lifetime: a late joiner otherwise lands entirely in `recent` and a departed
    # contributor entirely in `early`, describing the repository's age rather than
    # what the person did over their span (W1). This re-bases a denominator; no
    # coefficient is introduced, so norms §7 is untouched.
    phase_start, phase_end, phase_window = observation_window(nonmerge)
    domain = Counter[str]()
    work_type = Counter[str]()
    time_phase = Counter[str]()
    calendar_year = Counter[str]()
    process = Counter[str]()

    for commit in nonmerge:
        domains = {classify_domain(change.path) for change in commit.changes} or {"unclassified"}
        domain.update(domains)

        work: set[str] = set()
        statuses = {change.status for change in commit.changes}
        if statuses & {"A", "C"}:
            work.add("create")
        if statuses & {"M", "D"}:
            work.add("modify")
        if "R" in statuses:
            work.add("rename")
        if any(is_test_path(change.path) for change in commit.changes):
            work.add("test")
        if any(is_dependency_path(change.path) for change in commit.changes):
            work.add("dependency")
        if is_corrective_subject(commit.subject):
            work.add("corrective")
        work_type.update(work)

        timestamp = as_utc(commit.authored_at)
        time_phase[_time_phase(timestamp, phase_start, phase_end)] += 1
        calendar_year[str(timestamp.year)] += 1

    for commit in target:
        if not commit.is_merge:
            statuses = {change.status for change in commit.changes}
            if statuses & {"A", "C"}:
                process["creator"] += 1
            if statuses & {"M", "D", "R"}:
                process["maintainer"] += 1
        if commit.is_merge:
            process["integrator"] += 1

    release_targets = {
        (tag.name, tag.target_oid)
        for tag in release_tags
        if tag.annotated and tag.tagger_actor_id == actor_id
    }
    process["release"] = len(release_targets)

    dimensions: dict[str, object] = {
        "domain": _dimension(
            DOMAIN_CATEGORIES,
            domain,
            len(nonmerge),
            window=window,
            min_population=min_population,
            limitation="A commit may appear in multiple domains; categories are not a ranking.",
        ),
        "work_type": _dimension(
            WORK_TYPE_CATEGORIES,
            work_type,
            len(nonmerge),
            window=window,
            min_population=min_population,
            limitation="Work types overlap and depend on paths, diff status, and subject conventions.",
        ),
        "time": {
            "phase": _dimension(
                TIME_PHASE_CATEGORIES,
                time_phase,
                len(nonmerge),
                window=phase_window,
                min_population=min_population,
                limitation=(
                    "Early/middle/recent are equal thirds of this actor's own observed span, "
                    "not of the repository window. The span is the window recorded here."
                ),
            ),
            "calendar_year": _dimension(
                tuple(sorted(calendar_year)),
                calendar_year,
                len(nonmerge),
                window=window,
                min_population=min_population,
                limitation=(
                    "Calendar-year shares describe observed commits, not continuous employment."
                ),
            ),
        },
        "process_position": _dimension(
            PROCESS_POSITION_CATEGORIES,
            process,
            sum(process.values()),
            window=window,
            min_population=min_population,
            limitation=(
                "The denominator is observed process signals; release counts only supplied "
                "annotated tags with a matching tagger actor."
            ),
            unit="process_signal_share",
        ),
    }

    return {
        "kind": "observed",
        "actor_id": actor_id,
        "consent_basis": consent.basis,
        "definition_version": ROLE_PROFILE_DEFINITION_VERSION,
        "window": window,
        "basis": "actor_commits",
        "overlap_allowed": True,
        "dimensions": dimensions,
        "limitations": [
            "This profile does not infer a job title, ability, quality, fit, score, or rank.",
            "All categories describe only supplied fixed-OID Git events.",
        ],
    }
