"""W3 (案C) — compare surfaces and verification by composition, not presence.

`_presence_compare` returned `overlap` for any non-zero count, so a surface
holding half of someone's work and one holding 0.6% of it produced the same
verdict. A deliberately mismatched project brief still came back as eight
"overlap" cells out of ten.

The project may now declare a minimum share per surface or verification type.
Those axes then use the same `_numeric_compare` that `change_rhythm` has always
used, and the verdict vocabulary is unchanged: no score, no rank, no total.
Declaring a floor is not weighting — it states what the work needs, and the
observation is still reported as measured (norms §7).

A brief that declares no floor keeps the presence behaviour, so existing
project files mean exactly what they meant before.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tep_core.alignment import build_alignment
from tep_core.gitutil import read_commits
from tep_core.verification_profile import verification_profile

from git_fixture import commit, git, init_repo

# The verification half of this fixture used to hand-write `test_type_share`,
# which production never emitted. The tests therefore passed while the shipped
# tool inverted the verdicts: a type with 62 commits read `not_observed`
# (no share to compare) and a type with 0 read `below_declared` (a definite
# zero). Nothing hand-written stands in for that block any more — the
# verification tests below take it from `verification_profile()` over a real
# commit series.
ACTOR = {
    "schema_version": "report-v2",
    "surface_profile": {
        "kind": "observed",
        "surface_commit_counts": {"values": {"test": 1197, "observability": 14}},
        "surface_commit_share": {"values": {"test": 0.5, "observability": 0.006}},
    },
    "change_rhythm": {"kind": "not_observed", "reason": "not_provided"},
}


def _profile(repo: Path) -> dict:
    return verification_profile(
        read_commits(repo, include_files=True),
        tests_observed=True,
        empty_reason="no_commits_in_window",
    )


@pytest.fixture(scope="module")
def unit_only_verification(tmp_path_factory) -> dict:
    """Production output for an actor whose tests are all unit tests.

    Shaped like the report that exposed the defect: many unit-test commits,
    zero e2e. `MIN_POPULATION_FOR_RATES` is 20, so 24 test-touching commits
    put the share over the threshold and make it a real observation.
    """
    repo = init_repo(tmp_path_factory.mktemp("unit-only") / "repo")
    for index in range(24):
        commit(
            repo,
            email="a@example.com",
            date=f"2025-01-{1 + index % 28:02d}",
            message=f"test: cover module {index}",
            filename=f"tests/unit/test_module_{index}.py",
            name="Alice",
        )
    for index in range(6):
        commit(
            repo,
            email="a@example.com",
            date=f"2025-02-{1 + index:02d}",
            message=f"feat: service {index}",
            filename=f"api/service_{index}.py",
            name="Alice",
        )
    return _profile(repo)


@pytest.fixture(scope="module")
def both_types_verification(tmp_path_factory) -> dict:
    """Production output where every test commit touches unit *and* e2e."""
    repo = init_repo(tmp_path_factory.mktemp("both-types") / "repo")
    for index in range(21):
        for name in (f"tests/unit/test_m{index}.py", f"tests/e2e/spec_m{index}.py"):
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# {index}\n", encoding="utf-8")
        git(repo, "add", "-A")
        env = {
            **dict(os.environ),
            "GIT_AUTHOR_NAME": "Alice",
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_AUTHOR_DATE": f"2025-03-{1 + index:02d}T12:00:00",
            "GIT_COMMITTER_NAME": "Alice",
            "GIT_COMMITTER_EMAIL": "a@example.com",
            "GIT_COMMITTER_DATE": f"2025-03-{1 + index:02d}T12:00:00",
        }
        git(repo, "commit", "-m", f"test: cover {index} end to end", env=env)
    return _profile(repo)


FORBIDDEN = {"score", "rank", "fit", "fit_score", "overall", "pass", "fail", "recommendation"}


def _align(surfaces=None, verification=None, actor=None):
    declared = {
        "surfaces": surfaces or {"kind": "not_declared"},
        "verification": verification or {"kind": "not_declared"},
        "change_rhythm": {},
        "inputs": {"kind": "not_declared"},
        "role_lens": {"kind": "not_declared"},
    }
    return build_alignment(
        actor_report=actor or ACTOR,
        declared=declared,
        actor_digest=None,
        project_digest="d" * 64,
    )


def _axis(axes, name):
    for axis in axes:
        if axis["axis"] == name:
            return axis
    raise AssertionError(f"axis {name} not emitted: {[a['axis'] for a in axes]}")


def _surface(names, floors=None):
    node = {"kind": "declared", "value": list(names)}
    if floors:
        node["min_share"] = floors
    return node


# --------------------------------------------------------------------------
# A declared floor separates concentration from mere presence
# --------------------------------------------------------------------------


def test_a_share_below_the_declared_floor_is_outside_the_range() -> None:
    axes = _align(surfaces=_surface(["observability"], {"observability": 0.20}))
    axis = _axis(axes, "surfaces.observability")
    assert axis["comparison"] == "outside_declared_range", (
        f"0.6% of the actor's work met a 20% floor: {axis}"
    )


def test_a_share_above_the_declared_floor_overlaps() -> None:
    axes = _align(surfaces=_surface(["test"], {"test": 0.20}))
    assert _axis(axes, "surfaces.test")["comparison"] == "overlap"


def test_the_two_surfaces_no_longer_collapse_together() -> None:
    """The defect this fixes: 50.0% and 0.6% produced the same verdict."""
    axes = _align(
        surfaces=_surface(["test", "observability"], {"test": 0.20, "observability": 0.20})
    )
    verdicts = {
        _axis(axes, "surfaces.test")["comparison"],
        _axis(axes, "surfaces.observability")["comparison"],
    }
    assert len(verdicts) == 2, f"both surfaces still return the same verdict: {verdicts}"


def _verification(names, floors=None):
    node = {"kind": "declared", "value": list(names)}
    if floors:
        node["min_share"] = floors
    return node


def test_verification_types_take_a_floor_too(unit_only_verification) -> None:
    """The inversion this fixes, on production output rather than a fixture.

    24 unit-test commits and 0 e2e. Before `verification_profile()` emitted
    `test_type_share`, `_obs_share` found nothing to read and the type the
    actor actually worked on came back `not_observed`, while the type they had
    never touched came back with a definite verdict. The worked-on type must
    hold the observation.
    """
    actor = {**ACTOR, "verification_profile": unit_only_verification}
    counts = unit_only_verification["test_type_distribution"]["values"]
    assert (counts["unit"], counts["e2e"]) == (24, 0), counts

    axes = _align(
        verification=_verification(["unit", "e2e"], {"unit": 0.10, "e2e": 0.10}), actor=actor
    )
    unit_axis = _axis(axes, "verification.unit")
    assert unit_axis["comparison"] == "overlap", (
        f"the type holding every test commit did not hold the observation: {unit_axis}"
    )
    assert unit_axis["observed"]["kind"] == "observed"
    assert _axis(axes, "verification.e2e")["comparison"] == "observed_zero"


def test_a_worked_type_never_reports_as_unmeasured(unit_only_verification) -> None:
    """The falsification: a non-zero count must never read `not_observed`.

    Deleting the `test_type_share` block from `verification_profile()` puts
    the shipped inversion back, and this assertion is what catches it.
    """
    actor = {**ACTOR, "verification_profile": unit_only_verification}
    axes = _align(verification=_verification(["unit"], {"unit": 0.10}), actor=actor)
    axis = _axis(axes, "verification.unit")
    assert axis["comparison"] != "not_observed", (
        "a type with 24 commits was reported as unmeasured; production emitted "
        f"no share beside its distribution: {axis}"
    )
    assert axis["observed"]["unit"] == "commit_share"


def test_type_shares_do_not_sum_to_one(both_types_verification) -> None:
    """Each type is divided by commits, so the shares are not a partition.

    A commit touching `tests/unit/` and `tests/e2e/` counts once for each
    type but once in the denominator, so the shares can total more than 1.0.
    That is not a defect: the question each share answers is "of the commits
    where this actor touched tests, in what fraction did they touch this
    kind", and a reader must not add them up.
    """
    share = both_types_verification["test_type_share"]
    assert share["kind"] == "observed", share
    assert share["denominator_definition"] == "commits that touched at least one test path"
    assert share["population"] == 21, share
    assert share["values"]["unit"] == pytest.approx(1.0)
    assert share["values"]["e2e"] == pytest.approx(1.0)
    assert sum(share["values"].values()) > 1.0, share


# --------------------------------------------------------------------------
# The observation stays visible, and old briefs keep their meaning
# --------------------------------------------------------------------------


def test_the_measured_share_is_reported_beside_the_verdict() -> None:
    """A reader must see 0.006 against 0.20, not just the word."""
    axes = _align(surfaces=_surface(["observability"], {"observability": 0.20}))
    axis = _axis(axes, "surfaces.observability")
    assert axis["observed"]["value"] == pytest.approx(0.006)
    assert axis["observed"]["unit"] == "commit_share"
    assert axis["declared"]["value"] == pytest.approx(0.20)


def test_without_a_floor_presence_behaviour_is_unchanged() -> None:
    """Existing project files must mean what they meant before."""
    axes = _align(surfaces=_surface(["observability"]))
    axis = _axis(axes, "surfaces.observability")
    assert axis["comparison"] == "overlap"
    assert axis["observed"]["unit"] == "commits"


def test_a_floor_on_an_unobserved_surface_is_not_observed() -> None:
    actor = {
        **ACTOR,
        "surface_profile": {"kind": "not_observed", "reason": "commit_paths_unavailable"},
    }
    axes = _align(surfaces=_surface(["test"], {"test": 0.20}), actor=actor)
    assert _axis(axes, "surfaces.test")["comparison"] == "not_observed"


def test_zero_share_against_a_floor_is_still_observed_zero() -> None:
    """`observed_zero` carries its own limitation and must not become a range miss."""
    axes = _align(surfaces=_surface(["data"], {"data": 0.20}))
    assert _axis(axes, "surfaces.data")["comparison"] == "observed_zero"


def test_no_score_or_total_is_introduced() -> None:
    axes = _align(
        surfaces=_surface(["test", "observability"], {"test": 0.20, "observability": 0.20})
    )
    for axis in axes:
        assert FORBIDDEN.isdisjoint(axis), sorted(FORBIDDEN & set(axis))
