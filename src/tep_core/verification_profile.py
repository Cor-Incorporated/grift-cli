"""Verification evidence from test paths. Does not label anyone as QA."""

from __future__ import annotations

import re
from typing import Any

from tep_core.gitutil import GitCommit
from tep_core.observation import NotObserved, Observed
from tep_core.path_surface import classify_surface
from tep_core.paths import is_test_path, split_paths
from tep_core.rework import is_corrective_subject
from tep_core.v2_constants import MIN_POPULATION_FOR_RATES, VERIFICATION_TYPES
from tep_core.version import VERIFICATION_DEFINITION_VERSION

_UNIT_RE = re.compile(r"(^|/)(unit|tests?/unit)(/|$)|(^|/)test_[^/]+\.py$|_test\.py$", re.I)
_INT_RE = re.compile(r"(^|/)(integration|integ|int)(/|$)", re.I)
_E2E_RE = re.compile(r"(^|/)(e2e|cypress|playwright|selenium)(/|$)", re.I)
_CONTRACT_RE = re.compile(r"(^|/)(contract|pact)(/|$)", re.I)
_SURFACE_KEYS = ("frontend", "backend", "data", "platform")


def _test_type(path: str) -> str:
    if not is_test_path(path):
        return "unspecified"
    if _CONTRACT_RE.search(path):
        return "contract"
    if _E2E_RE.search(path):
        return "e2e"
    if _INT_RE.search(path):
        return "integration"
    if _UNIT_RE.search(path):
        return "unit"
    return "unspecified"


def verification_profile(
    commits: list[GitCommit],
    *,
    tests_observed: bool,
    empty_reason: str,
) -> dict[str, Any]:
    if not tests_observed:
        payload = NotObserved("no_test_framework_or_directory").to_dict()
        payload["definition_version"] = VERIFICATION_DEFINITION_VERSION
        return payload
    if not commits:
        payload = NotObserved(empty_reason).to_dict()
        payload["definition_version"] = VERIFICATION_DEFINITION_VERSION
        return payload
    if not any(commit.files for commit in commits):
        payload = NotObserved("commit_paths_unavailable").to_dict()
        payload["definition_version"] = VERIFICATION_DEFINITION_VERSION
        return payload

    test_only = 0
    test_touch = 0
    type_counts = {name: 0 for name in VERIFICATION_TYPES}
    fix_total = 0
    fix_with_test = 0
    surface_co = {name: 0 for name in _SURFACE_KEYS}

    for commit in commits:
        prod, tests, _docs = split_paths(commit.files)
        if tests:
            test_touch += 1
            types = {_test_type(path) for path in tests}
            for item in types:
                type_counts[item] += 1
        if tests and not prod:
            test_only += 1
        surfaces = {classify_surface(path) for path in commit.files}
        if tests:
            for name in _SURFACE_KEYS:
                if name in surfaces:
                    surface_co[name] += 1
        subject = commit.subject.lower()
        if is_corrective_subject(commit.subject) or subject.startswith("revert"):
            fix_total += 1
            if tests:
                fix_with_test += 1

    population = len(commits)
    share: dict[str, Any]
    if population < MIN_POPULATION_FOR_RATES:
        share = NotObserved("insufficient_population").to_dict()
        share["population"] = population
        share["test_touch"] = test_touch
    else:
        share = Observed(
            round(test_touch / population, 4), "ratio", sample_size=population
        ).to_dict()
        share["test_touch"] = test_touch

    # `test_type_distribution` counts commits, so a floor declared against a
    # type had nothing to compare with: `alignment._obs_share` looks for a
    # share, found none, and returned `not_observed` for every non-zero type
    # while a zero-count type got the definite `observed_zero`. The verdicts
    # were inverted — the type someone actually worked on read as unmeasured.
    #
    # The denominator is the actor's test-touching commits, not the sum of
    # `type_counts`: the loop above collects a *set* per commit, so one commit
    # touching unit and e2e adds one to each. A commit-count denominator is
    # what makes `commit_share` in `alignment._obs_share` an honest unit.
    type_share: dict[str, Any]
    if test_touch == 0:
        type_share = NotObserved("no_test_touching_commits").to_dict()
    elif test_touch < MIN_POPULATION_FOR_RATES:
        type_share = NotObserved("insufficient_population").to_dict()
        type_share["population"] = test_touch
    else:
        type_share = {
            "kind": "observed",
            "unit": "ratio",
            "sample_size": test_touch,
            "population": test_touch,
            "denominator_definition": "commits that touched at least one test path",
            "values": {
                name: round(type_counts[name] / test_touch, 4) for name in VERIFICATION_TYPES
            },
        }

    pairing: dict[str, Any]
    if fix_total == 0:
        pairing = NotObserved("no_fix_or_revert_commits").to_dict()
    elif fix_total < MIN_POPULATION_FOR_RATES:
        pairing = NotObserved("insufficient_population").to_dict()
        pairing["population"] = fix_total
        pairing["with_test"] = fix_with_test
    else:
        pairing = Observed(
            round(fix_with_test / fix_total, 4), "ratio", sample_size=fix_total
        ).to_dict()
        pairing["with_test"] = fix_with_test

    return {
        "kind": "observed",
        "unit": "profile",
        "definition_version": VERIFICATION_DEFINITION_VERSION,
        "sample_size": population,
        "test_only_commit_count": Observed(test_only, "commits", sample_size=population).to_dict(),
        "test_touch_share": share,
        "test_type_distribution": {
            "kind": "observed",
            "unit": "commits",
            "values": type_counts,
        },
        "test_type_share": type_share,
        "fix_with_test_pairing": pairing,
        "surface_test_cochange": {
            "kind": "observed",
            "unit": "commits",
            "values": surface_co,
        },
    }
