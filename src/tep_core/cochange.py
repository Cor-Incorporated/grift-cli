"""Test co-change rate (definition v1, 2026-08-19 ruling)."""

from __future__ import annotations

from datetime import date, timedelta

from tep_core.activity import WINDOW_13W_DAYS
from tep_core.gitutil import GitCommit
from tep_core.observation import NotObserved
from tep_core.origin import OriginResult
from tep_core.paths import split_paths
from tep_core.scope import DEFAULT_SCOPE, population_shas

COCHANGE_DEFINITION_VERSION = "test-cochange-v1-2026-08-22"
MIN_POPULATION_FOR_RATE = 20


def _parse_day(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def test_cochange(
    commits: list[GitCommit],
    origin: OriginResult,
    *,
    tests_observed: bool,
    pending_attribution: bool,
    head_date: str | None,
    scope: str = DEFAULT_SCOPE,
) -> dict[str, object]:
    """Co-change among production-changing commits in the analysis scope.

    tenant: identity-matched consenting tenant (evidence).
    actor_cluster: one repo-local primary-author cluster, without consent claim.
    repo: all non-bot, non-merge humans (process / reference distribution).
    """
    if not tests_observed:
        return NotObserved("no_test_framework_or_directory").to_dict()

    shas = population_shas(commits, origin, scope)
    if scope == "tenant" and pending_attribution and not shas:
        return NotObserved("pending_attribution").to_dict()
    if not shas:
        reason = {
            "tenant": "no_tenant_commits",
            "actor_cluster": "no_actor_commits",
            "repo": "no_human_commits",
        }[scope]
        return NotObserved(reason).to_dict()
    if not any(c.files for c in commits):
        return NotObserved("commit_paths_unavailable").to_dict()

    pop_all, co_all, test_only, docs_only = _window(commits, shas, start=None)
    payload: dict[str, object] = {
        "kind": "observed",
        "definition_version": COCHANGE_DEFINITION_VERSION,
        "analysis_scope": scope,
        "all_time": _rate_block(pop_all, co_all, test_only, docs_only),
    }
    if head_date:
        cut = _parse_day(head_date) - timedelta(days=WINDOW_13W_DAYS)
        pop_w, co_w, test_w, docs_w = _window(commits, shas, start=cut)
        payload["last_13w"] = _rate_block(pop_w, co_w, test_w, docs_w)
    else:
        payload["last_13w"] = NotObserved("head_date_unavailable").to_dict()
    return payload


def _window(
    commits: list[GitCommit],
    tenant_shas: set[str],
    start: date | None,
) -> tuple[int, int, int, int]:
    pop = co = test_only = docs_only = 0
    for commit in commits:
        if commit.sha not in tenant_shas:
            continue
        if start is not None and _parse_day(commit.date) < start:
            continue
        prod, tests, docs = split_paths(commit.files)
        if prod:
            pop += 1
            if tests:
                co += 1
        elif tests:
            test_only += 1
        elif docs:
            docs_only += 1
    return pop, co, test_only, docs_only


def _rate_block(pop: int, co: int, test_only: int, docs_only: int) -> dict[str, object]:
    if pop == 0:
        return NotObserved("no_production_commits").to_dict()
    rate = round(co / pop, 4)
    return {
        "kind": "observed",
        "value": rate,
        "unit": "ratio",
        "population": pop,
        "cochanged": co,
        "test_only": test_only,
        "docs_or_config_excluded": docs_only,
        "narrate_rate": pop >= MIN_POPULATION_FOR_RATE,
    }
