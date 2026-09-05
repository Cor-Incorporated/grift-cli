"""W1 — early/middle/recent must divide the actor's own span, not the repository's.

``time_phase`` split the *fixed repository window* into equal thirds. A person
who joined a long-lived project last year therefore landed entirely in
``recent``, and one who left early landed entirely in ``early``: the axis
described when the repository existed, not what the person did over their own
tenure. For staffing that is the wrong denominator — "what has this person been
doing lately" is a question about their career, not about the repository's age.

This is a denominator change, not a weighting. No coefficient is introduced, so
`docs/norms.md` §7 (no weighting or conversion) is untouched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tep_core.experience import ExperienceCommit, FileChange, TenantConsent
from tep_core.role_profile import ROLE_PROFILE_DEFINITION_VERSION, build_role_profile

CONSENT = TenantConsent("subject", "unit_test")
EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _commit(oid: str, day: int, actor: str) -> ExperienceCommit:
    return ExperienceCommit(
        oid=oid,
        actor_id=actor,
        authored_at=EPOCH + timedelta(days=day),
        message="feat: work",
        changes=(FileChange("M", f"src/module_{day}.py"),),
        parents=("0" * 40,),
    )


def _late_joiner_history() -> list[ExperienceCommit]:
    """Repository spans 2020-2026; the subject only worked in the last stretch.

    Thirty subject commits clear DEFAULT_MIN_POPULATION (20).
    """
    others = [_commit(f"{i:040x}", i * 60, "veteran") for i in range(30)]
    subject = [_commit(f"{i + 900:040x}", 1700 + i * 6, "subject") for i in range(30)]
    return others + subject


def _profile(commits):
    return build_role_profile(commits, actor_id="subject", consent=CONSENT)


# --------------------------------------------------------------------------
# The axis must describe the actor's tenure
# --------------------------------------------------------------------------


def test_a_late_joiner_is_not_entirely_recent() -> None:
    phases = _profile(_late_joiner_history())["dimensions"]["time"]["phase"]
    shares = {name: node.get("value") for name, node in phases.items()}
    assert shares["recent"] != 1.0, (
        "the subject's whole tenure collapsed into 'recent'; the axis is still "
        f"dividing the repository window: {shares}"
    )
    assert shares["early"] and shares["early"] > 0, (
        f"a thirty-commit tenure has an early third: {shares}"
    )


def test_phases_divide_the_actor_span_evenly() -> None:
    """Thirty commits at a constant cadence split ten / ten / ten."""
    commits = [_commit(f"{i:040x}", 1000 + i * 10, "subject") for i in range(30)]
    phases = _profile(commits)["dimensions"]["time"]["phase"]
    counts = {name: node.get("numerator") for name, node in phases.items()}
    assert counts == {"early": 10, "middle": 10, "recent": 10}, counts


def test_time_phase_window_is_the_actor_window() -> None:
    """The emitted window must name the span the thirds were taken from."""
    commits = _late_joiner_history()
    dims = _profile(commits)["dimensions"]
    subject_times = sorted(c.authored_at for c in commits if c.actor_id == "subject")
    phase_window = next(iter(dims["time"]["phase"].values()))["window"]
    assert phase_window["start"].startswith(subject_times[0].strftime("%Y-%m-%d")), (
        f"time_phase window starts at {phase_window['start']}, "
        f"but the subject's first commit is {subject_times[0]}"
    )
    assert phase_window["end"].startswith(subject_times[-1].strftime("%Y-%m-%d"))


def test_other_dimensions_keep_the_repository_window() -> None:
    """Only time_phase changes basis; domain and work_type are unaffected."""
    commits = _late_joiner_history()
    dims = _profile(commits)["dimensions"]
    repo_start = min(c.authored_at for c in commits)
    domain_window = next(iter(dims["domain"].values()))["window"]
    assert domain_window["start"].startswith(repo_start.strftime("%Y-%m-%d")), (
        f"domain window moved to {domain_window['start']}; it must stay on the repository window"
    )


def test_limitation_names_the_actor_basis() -> None:
    phases = _profile(_late_joiner_history())["dimensions"]["time"]["phase"]
    limitations = next(iter(phases.values()))["limitations"]
    text = " ".join(limitations)
    assert "thirds of the fixed repository window" not in text, (
        f"limitation still claims the repository window as the basis: {text}"
    )
    assert "actor's own observed span" in text, (
        f"limitation must name the actor span as the basis: {text}"
    )


# --------------------------------------------------------------------------
# Definition change must be visible, and stated in one place
# --------------------------------------------------------------------------


def test_definition_version_moved() -> None:
    assert ROLE_PROFILE_DEFINITION_VERSION != "role-profile-v1", (
        "time_phase changed meaning; the definition version must move with it"
    )


def test_not_observed_path_uses_the_same_constant() -> None:
    """analyze_v2 hardcoded the old literal; observed and not_observed drifted."""
    from pathlib import Path

    source = Path("src/tep_core/analyze_v2.py").read_text(encoding="utf-8")
    assert '"role-profile-v1"' not in source, (
        "analyze_v2 still hardcodes the role profile definition version; "
        "import ROLE_PROFILE_DEFINITION_VERSION instead"
    )


@pytest.mark.parametrize("actor", ["subject", "veteran"])
def test_single_commit_actor_degrades_rather_than_crashes(actor: str) -> None:
    """One commit is below the population floor: not_observed, never a divide-by-span."""
    commits = [_commit("a" * 40, 10, actor)]
    phases = build_role_profile(
        commits, actor_id=actor, consent=TenantConsent(actor, "unit_test")
    )["dimensions"]["time"]["phase"]
    for name, node in phases.items():
        assert node["kind"] == "not_observed", f"{name}: {node}"
        assert node["reason"] == "insufficient_population"
