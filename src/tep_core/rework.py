"""Rework metrics among production commits in the analysis scope (H-4 / WP1b-1).

path_retouch_rate and corrective_rework_rate are observational only.
corrective_rework_rate depends on commit-subject conventions (fix/revert) and
must not be used as an evidence claim (measurement confounding: conventional
commit culture inflates detection). Line-level rework is deferred to v0.6.
"""

from __future__ import annotations

import re
from datetime import date

from tep_core.gitutil import GitCommit
from tep_core.observation import NotObserved
from tep_core.origin import OriginResult
from tep_core.paths import split_paths
from tep_core.scope import DEFAULT_SCOPE, population_shas

REWORK_DEFINITION_VERSION = "rework-v1.1-2026-08-22"
REWORK_WINDOW_DAYS = 21

# Conventional-commit and common prose: fix / hotfix / bug / revert.
_CORRECTIVE_SUBJECT_RE = re.compile(
    r"^(revert\b|fix(\b|\(|:|!)|hotfix\b|bugfix\b|bug(\b|\(|:)|fixes\s+#)",
    re.I,
)


def _parse_day(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def is_corrective_subject(subject: str) -> bool:
    return bool(_CORRECTIVE_SUBJECT_RE.search(subject) or "This reverts commit" in subject)


def rework_metrics(
    commits: list[GitCommit],
    origin: OriginResult,
    *,
    pending_attribution: bool,
    scope: str = DEFAULT_SCOPE,
) -> dict[str, object]:
    shas = population_shas(commits, origin, scope)
    if scope == "tenant" and pending_attribution and not shas:
        return NotObserved("pending_attribution").to_dict()
    if not shas:
        return NotObserved(
            "no_tenant_commits" if scope == "tenant" else "no_human_commits"
        ).to_dict()
    if not any(c.files for c in commits):
        return NotObserved("commit_paths_unavailable").to_dict()

    prod_commits = [c for c in commits if c.sha in shas and split_paths(c.files)[0]]
    if not prod_commits:
        return NotObserved("no_production_commits").to_dict()

    chrono = sorted(prod_commits, key=lambda c: c.date)
    last_touch: dict[str, date] = {}
    retouch = 0
    corrective = 0
    for commit in chrono:
        prod, _, _ = split_paths(commit.files)
        day = _parse_day(commit.date)
        recent_path = False
        for path in prod:
            prev = last_touch.get(path)
            if prev is not None and (day - prev).days <= REWORK_WINDOW_DAYS:
                recent_path = True
            last_touch[path] = day
        if recent_path:
            retouch += 1
            if is_corrective_subject(commit.subject):
                corrective += 1

    reverts = sum(
        1
        for c in commits
        if c.sha in shas
        and is_corrective_subject(c.subject)
        and (c.subject.lower().startswith("revert") or "This reverts commit" in c.subject)
    )
    population = len(prod_commits)
    return {
        "kind": "observed",
        "definition_version": REWORK_DEFINITION_VERSION,
        "analysis_scope": scope,
        "window_days": REWORK_WINDOW_DAYS,
        "evidence_claim": None,
        "corrective_rework_rate": {
            "kind": "observed",
            "value": round(corrective / population, 4),
            "unit": "ratio",
            "corrective_commits": corrective,
            "population": population,
            "narrate_rate": population >= 20,
            "evidence_claim": False,
        },
        "path_retouch_rate": {
            "kind": "observed",
            "value": round(retouch / population, 4),
            "unit": "ratio",
            "retouch_commits": retouch,
            "population": population,
            "evidence_claim": False,
        },
        "revert_rate": {
            "kind": "observed",
            "value": round(reverts / max(len(shas), 1), 4),
            "unit": "ratio",
            "reverts": reverts,
            "population": len(shas),
        },
        "line_rework": NotObserved("deferred_to_v0.6").to_dict(),
    }
