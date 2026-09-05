"""Coordination observations split by input. Git-only is not review."""

from __future__ import annotations

import re
from typing import Any

from tep_core.forge import ForgeExport
from tep_core.gitutil import GitCommit
from tep_core.observation import NotObserved, Observed
from tep_core.tracker import TrackerExport
from tep_core.v2_constants import (
    FORGE_NOT_OBSERVED_NOTE,
    MIN_POPULATION_FOR_RATES,
    TRACKER_NOT_OBSERVED_NOTE,
)
from tep_core.version import COORDINATION_DEFINITION_VERSION

_ISSUE_RE = re.compile(r"(#\d+|fixes\s+#|close[sd]?\s+#)", re.I)
_REVIEW_KINDS = frozenset({"pull_request_review", "review_comment"})
_LIFECYCLE_KINDS = frozenset(
    {"pull_request_opened", "pull_request_merged", "pull_request_lifecycle"}
)


def _ratio(count: int, population: int) -> dict[str, Any]:
    if population < MIN_POPULATION_FOR_RATES:
        payload = NotObserved("insufficient_population").to_dict()
        payload["population"] = population
        payload["count"] = count
        return payload
    payload = Observed(round(count / population, 4), "ratio", sample_size=population).to_dict()
    payload["count"] = count
    return payload


def coordination_profile(
    commits: list[GitCommit],
    *,
    canonical_id: str | None,
    forge: ForgeExport | None,
    tracker: TrackerExport | None,
    empty_reason: str,
) -> dict[str, Any]:
    if not commits:
        payload = NotObserved(empty_reason).to_dict()
        payload["definition_version"] = COORDINATION_DEFINITION_VERSION
        return payload
    humans = [commit for commit in commits if not commit.is_merge]
    merges = [commit for commit in commits if commit.is_merge]
    linked = [commit for commit in humans if _ISSUE_RE.search(commit.subject)]
    git_block = {
        "kind": "observed",
        "unit": "profile",
        "merge_commit_count": Observed(len(merges), "commits").to_dict(),
        "merge_commit_share": _ratio(len(merges), len(commits)),
        "issue_link_count": Observed(len(linked), "commits").to_dict(),
        "issue_link_share": _ratio(len(linked), len(humans) if humans else 0),
        "limitations": [
            "Git-only merge_commit_share is not pull-request review.",
            "Commit-subject issue links are heuristics, not tracker events.",
        ],
    }
    review = _forge_block(forge, canonical_id)
    tracker_block = _tracker_block(tracker, canonical_id)
    return {
        "kind": "observed",
        "unit": "profile",
        "definition_version": COORDINATION_DEFINITION_VERSION,
        "sample_size": len(commits),
        "git": git_block,
        "review": review,
        "tracker": tracker_block,
    }


def _forge_block(forge: ForgeExport | None, canonical_id: str | None) -> dict[str, Any]:
    if forge is None:
        payload = NotObserved("forge_export_not_provided").to_dict()
        payload["limitations"] = [FORGE_NOT_OBSERVED_NOTE]
        return payload
    events = forge.events
    if canonical_id:
        events = tuple(item for item in events if item.actor_canonical_id == canonical_id)
    reviews = [item for item in events if item.kind in _REVIEW_KINDS]
    prs = {item.pr_number for item in reviews if item.pr_number is not None}
    lifecycle = [item for item in events if item.kind in _LIFECYCLE_KINDS]
    limitations = ["Counts are from the supplied local export. Review quality is not measured."]
    if forge.binding is not None and forge.binding.coverage.status == "partial":
        limitations.append("Declared source coverage is partial; event counts are lower bounds.")
    return {
        "kind": "observed",
        "unit": "profile",
        "review_event_count": Observed(len(reviews), "events").to_dict(),
        "reviewed_pr_count": Observed(len(prs), "pull-requests").to_dict(),
        "lifecycle_event_count": Observed(len(lifecycle), "events").to_dict(),
        "limitations": limitations,
    }


def _tracker_block(tracker: TrackerExport | None, canonical_id: str | None) -> dict[str, Any]:
    if tracker is None:
        payload = NotObserved("tracker_export_not_provided").to_dict()
        payload["limitations"] = [TRACKER_NOT_OBSERVED_NOTE]
        return payload
    events = tracker.events
    if canonical_id:
        events = tuple(item for item in events if item.actor_canonical_id == canonical_id)
    kinds = {item.kind: 0 for item in events}
    for item in events:
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    issues = {item.issue_number for item in events if item.issue_number is not None}
    limitations = ["Private meetings and requirement quality are not observed."]
    if tracker.binding is not None and tracker.binding.coverage.status == "partial":
        limitations.append("Declared source coverage is partial; event counts are lower bounds.")
    return {
        "kind": "observed",
        "unit": "profile",
        "event_count": Observed(len(events), "events").to_dict()
        if events
        else Observed(0, "events").to_dict(),
        "distinct_issue_count": Observed(len(issues), "issues").to_dict(),
        "kind_counts": kinds,
        "limitations": limitations,
    }
