"""The enforcement point that lives in another repository.

`test_v070_norms_link` ties four places together -- both norms documents,
`PURPOSES`, and the CLI's choices -- and every one of them is inside this
repository. The fifth is not: the public intake validates `purpose` against its
own schema in `Cor-Incorporated/tep-contributions`, and nothing joined the two.

That is how v0.7.0 shipped a purpose the intake rejects. The set was widened
here, the `const` over there stayed pinned to the single v0.6.0 value, and a
submitter would have found out after building, disclosing, and confirming a
payload that then bounced.

This file is what makes that visible from this side. It cannot fix the other
repository, and it does not pretend to: when the sibling checkout is absent the
tests skip, and `PURPOSE_DOORS` carries the constraint that is actually
enforced at build time. What these tests catch is the two drifting apart while
both are present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_core.contribution_v2 import (
    PURPOSE_DOORS,
    PURPOSES,
    _validate_purpose_door,
)

def _find_intake() -> Path | None:
    """Locate a sibling `tep-contributions` checkout.

    Walks up rather than counting `parents[n]`: this repository is often worked
    on from a git worktree, where the sibling sits one level further out, and a
    hard-coded depth silently skips instead of comparing -- which is the exact
    failure this file exists to prevent.
    """
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "tep-contributions"
        if (candidate / "schemas").is_dir():
            return candidate
    return None


INTAKE = _find_intake()
PUBLIC_SCHEMA = (
    INTAKE / "schemas" / "tep-contribution-v2-public.schema.json" if INTAKE else None
)


def _intake_accepted_purposes() -> set[str]:
    """The purpose values the public intake schema admits, as it stands."""
    schema = json.loads(PUBLIC_SCHEMA.read_text(encoding="utf-8"))
    rule = schema["properties"]["purpose"]
    if "const" in rule:
        return {rule["const"]}
    if "enum" in rule:
        return set(rule["enum"])
    raise AssertionError(f"intake purpose rule is neither const nor enum: {rule}")


needs_intake = pytest.mark.skipif(
    PUBLIC_SCHEMA is None or not PUBLIC_SCHEMA.is_file(),
    reason="sibling tep-contributions checkout not found in any ancestor directory",
)


# --------------------------------------------------------------------------
# Enforced here, whether or not the sibling repository is around
# --------------------------------------------------------------------------


def test_every_purpose_declares_which_doors_it_can_reach() -> None:
    assert set(PURPOSE_DOORS) == set(PURPOSES), (
        f"PURPOSE_DOORS covers {sorted(PURPOSE_DOORS)} but the declared purposes "
        f"are {sorted(PURPOSES)}; an uncovered purpose would raise KeyError at "
        "build time instead of refusing with a reason"
    )


def test_local_is_always_reachable() -> None:
    """A purpose nothing can deliver is a purpose that should not be offered."""
    for name, doors in PURPOSE_DOORS.items():
        assert "local" in doors, name


def test_an_undeliverable_combination_is_refused_before_the_payload_is_built() -> None:
    with pytest.raises(ValueError) as excinfo:
        _validate_purpose_door("outcome-linkage", "public-pr")
    message = str(excinfo.value)
    assert "outcome-linkage" in message
    assert "public-pr" in message
    assert "local" in message, "the refusal must name a door that does work"


def test_the_deliverable_combinations_pass() -> None:
    for name, doors in PURPOSE_DOORS.items():
        for door in doors:
            _validate_purpose_door(name, door)


def test_saying_nothing_still_reaches_the_public_intake() -> None:
    """The v0.6.0 default must not become undeliverable by accident."""
    _validate_purpose_door(None, "public-pr")


# --------------------------------------------------------------------------
# Compared against the other repository, when it is here
# --------------------------------------------------------------------------


@needs_intake
def test_public_pr_purposes_match_what_the_intake_accepts() -> None:
    accepted = _intake_accepted_purposes()
    ours = {PURPOSES[name] for name, doors in PURPOSE_DOORS.items() if "public-pr" in doors}
    assert ours == accepted, (
        f"this repository would send {sorted(ours)} through public-pr, and the "
        f"intake schema at {PUBLIC_SCHEMA} accepts {sorted(accepted)}. A payload "
        "in the difference is built, disclosed, confirmed, and then bounced."
    )


@needs_intake
def test_a_purpose_the_intake_rejects_is_not_offered_for_public_pr() -> None:
    accepted = _intake_accepted_purposes()
    offered_but_rejected = sorted(
        name
        for name, doors in PURPOSE_DOORS.items()
        if "public-pr" in doors and PURPOSES[name] not in accepted
    )
    assert not offered_but_rejected, offered_but_rejected


@needs_intake
def test_the_intake_is_not_ahead_of_us_either() -> None:
    """Drift in the other direction is a smaller problem but still drift."""
    accepted = _intake_accepted_purposes()
    unknown_here = sorted(accepted - set(PURPOSES.values()))
    assert not unknown_here, (
        f"the intake accepts {unknown_here}, which this repository does not "
        "declare; either it is a purpose we should offer or a value nothing produces"
    )
