"""The norms and the code that enforces them, tied together mechanically.

Two clauses changed in v0.7 and both are the kind that rot quietly: a promise
written in a document, enforced somewhere else, with nothing joining the two. A
comment saying "keep in sync" is not a control. These tests are.

Each assertion names *both* values when it fails, because "they disagree" is not
enough to fix anything.

Covered here:

* the purpose set in `docs/norms.md`, `docs/en/norms.md` and `PURPOSES`
* the minimum team size promised by the norms and enforced in code
* the per-person prohibitions promised for `align --team` and enforced by the
  schema's `additionalProperties: false`
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NORMS_JA = ROOT / "docs" / "norms.md"
NORMS_EN = ROOT / "docs" / "en" / "norms.md"
SCHEMA = ROOT / "src/tep_core/schemas/v060-contracts.schema.json"

# `| `id` | `purpose` |` rows of the purpose table, in either document.
# The table sits inside a numbered list item, so the row may be indented.
_PURPOSE_ROW = re.compile(
    r"^\s*\|\s*`([a-z][a-z0-9-]*)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE
)


def _declared_purposes(path: Path) -> dict[str, str]:
    return dict(_PURPOSE_ROW.findall(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------
# Purpose binding
# --------------------------------------------------------------------------


def test_the_purpose_set_matches_the_japanese_norms() -> None:
    from tep_core.contribution_v2 import PURPOSES

    declared = _declared_purposes(NORMS_JA)
    assert declared, "no purpose table found in docs/norms.md"
    assert declared == PURPOSES, (
        f"docs/norms.md declares {declared} but the implementation enforces "
        f"{dict(PURPOSES)}. A submission bound to a purpose the norms do not "
        "list, or a listed purpose nothing accepts, is unenforceable either way."
    )


def test_the_two_norms_documents_declare_the_same_purposes() -> None:
    japanese = _declared_purposes(NORMS_JA)
    english = _declared_purposes(NORMS_EN)
    assert japanese == english, (
        f"docs/norms.md declares {japanese} and docs/en/norms.md declares "
        f"{english}. Readers of the two languages would be promised different things."
    )


def test_the_default_purpose_is_the_v06_one() -> None:
    """Saying nothing must keep meaning what it meant before the amendment."""
    from tep_core.contribution_v2 import PURPOSE, PURPOSES, resolve_purpose

    assert PURPOSE == PURPOSES["reference-distributions"]
    assert resolve_purpose(None) == PURPOSE


def test_an_undeclared_purpose_is_refused_by_name() -> None:
    import pytest

    from tep_core.contribution_v2 import PURPOSES, resolve_purpose

    with pytest.raises(ValueError) as excinfo:
        resolve_purpose("sales-enablement")
    message = str(excinfo.value)
    assert "sales-enablement" in message
    for name in PURPOSES:
        assert name in message, f"the refusal does not say {name} was available"


def test_a_payload_may_only_carry_a_declared_purpose() -> None:
    """The validator is the enforcement point a recipient actually runs."""
    from tep_core.contribution_v2 import PURPOSES, validate_v2_payload

    for value in PURPOSES.values():
        problems = validate_v2_payload({"purpose": value}, for_public_intake=False)
        assert "unexpected purpose" not in problems, value
    problems = validate_v2_payload(
        {"purpose": "anything at all"}, for_public_intake=False
    )
    assert "unexpected purpose" in problems


def test_the_norms_state_who_chooses() -> None:
    """The amendment moved a choice; the text must say so, in both languages."""
    japanese = NORMS_JA.read_text(encoding="utf-8")
    english = NORMS_EN.read_text(encoding="utf-8")
    assert "提出者が提出時に選択し payload に記録された目的にのみ" in japanese
    assert "the purpose the submitter chose at submission time" in english
    # The ban that did not change must survive the amendment.
    assert "SaaS" in japanese and "SaaS" in english


# --------------------------------------------------------------------------
# The multi-actor exception
# --------------------------------------------------------------------------


def test_the_minimum_team_size_matches_the_norms() -> None:
    from tep_core.complementarity import MIN_TEAM_SIZE

    japanese = NORMS_JA.read_text(encoding="utf-8")
    english = NORMS_EN.read_text(encoding="utf-8")
    assert f"{MIN_TEAM_SIZE} 名未満" in japanese, (
        f"the code refuses below {MIN_TEAM_SIZE} actors but docs/norms.md does "
        "not state that number"
    )
    assert "below three actors" in english, (
        f"docs/en/norms.md must state the same minimum the code enforces ({MIN_TEAM_SIZE})"
    )


def test_the_schema_minimum_matches_the_code_minimum() -> None:
    from tep_core.complementarity import MIN_TEAM_SIZE

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    observed = schema["$defs"]["report_complementarity"]["oneOf"][0]
    schema_minimum = observed["properties"]["team_size"]["minimum"]
    assert schema_minimum == MIN_TEAM_SIZE, (
        f"the schema admits teams of {schema_minimum} while the code refuses "
        f"below {MIN_TEAM_SIZE}; one of them is not the rule"
    )


def test_the_exception_names_its_enforcement_points() -> None:
    """A clause that does not say where it is enforced cannot be audited."""
    japanese = NORMS_JA.read_text(encoding="utf-8")
    english = NORMS_EN.read_text(encoding="utf-8")
    for text in (japanese, english):
        assert "complementarity.py" in text
        assert "report_complementarity" in text
        assert "additionalProperties" in text


def test_the_schema_enforces_the_promised_prohibitions() -> None:
    """The norms promise counts only, no ordering, no identity. The type says so."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    observed = schema["$defs"]["report_complementarity"]["oneOf"][0]
    requirement = observed["properties"]["requirements"]["items"]["oneOf"][0]
    assert observed["additionalProperties"] is False
    assert requirement["additionalProperties"] is False
    for field, spec in requirement["properties"].items():
        if field in {"meeting_declared", "with_any_observation", "actors_observed", "team_size"}:
            assert spec["type"] == "integer", (
                f"{field} is promised as a count but the schema admits {spec}"
            )


def test_the_cli_offers_exactly_the_declared_purposes() -> None:
    """A choice the CLI offers but the validator rejects is a dead end.

    It would surface at the last step of a consent flow, after the person has
    read the disclosure and agreed.
    """
    import argparse

    from tep_cli.options import build_parser
    from tep_core.contribution_v2 import PURPOSES

    parser = build_parser()
    actions = [
        action
        for action in parser._subparsers._group_actions  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction)
    ]
    contribute = actions[0].choices["contribute"]
    purpose = next(
        action for action in contribute._actions if action.dest == "purpose"  # noqa: SLF001
    )
    assert tuple(purpose.choices) == tuple(PURPOSES), (
        f"the CLI offers {tuple(purpose.choices)} but the declared set is "
        f"{tuple(PURPOSES)}"
    )
    assert purpose.default is None, "the default must be resolved by the norms-linked code"


def test_the_exception_is_scoped_to_one_command() -> None:
    japanese = NORMS_JA.read_text(encoding="utf-8")
    english = NORMS_EN.read_text(encoding="utf-8")
    assert "grift align --team" in japanese
    assert "grift align --team" in english
    for text in (japanese, english):
        assert text.count("grift align --team") >= 1
