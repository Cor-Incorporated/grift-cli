"""W6 — a declared outcome must never be able to pass as a measurement.

The channel exists because delivery is the half of "the right person for this
work" that git cannot record. It is also the half anyone can simply assert, and
a résumé already does that for free. What makes carrying it defensible is that
the type refuses to let it look like anything else.

So most of this file is about what the channel cannot do:

* no branch of `report_outcome` admits `kind: "observed"`
* `verify` does not recompute it, and must not claim to
* an attestation with nobody behind it is refused, not downgraded
* absence means nothing was declared, never that work did not ship (norms §1)
* the presence or absence of a declaration is not itself evidence (norms §3)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_core.outcome import (
    ATTESTATION_KINDS,
    NOT_PROVIDED_REASON,
    OUTCOME_KINDS,
    OUTCOME_SCHEMA_VERSION,
    load_outcome_input,
    outcome_payload,
)
from tep_core.secrets_guard import InputValidationError

SCHEMA = Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json"


def _write(tmp_path: Path, **body) -> Path:
    body.setdefault("schema_version", OUTCOME_SCHEMA_VERSION)
    path = tmp_path / "outcome.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def _attested(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        declarations=[
            {
                "outcome": "delivered",
                "attestation": "counterparty_attested",
                "attested_by": "Acme K.K.",
                "scope": "payments platform",
                "occurred_on": "2026-03-31",
            }
        ],
    )


def _self_declared(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        declarations=[
            {"outcome": "delivered", "attestation": "self_declared", "scope": "admin console"}
        ],
    )


# --------------------------------------------------------------------------
# A declaration is not an observation
# --------------------------------------------------------------------------


def test_every_declaration_is_typed_as_declared(tmp_path: Path) -> None:
    payload = outcome_payload(load_outcome_input(_attested(tmp_path)))
    assert payload["kind"] == "declared"
    for declaration in payload["declarations"]:
        assert declaration["kind"] == "declared"


def test_the_schema_has_no_observed_branch() -> None:
    """The type is what stops a claim being presented as a measurement."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    branches = schema["$defs"]["report_outcome"]["oneOf"]
    kinds = {branch["properties"]["kind"]["const"] for branch in branches}
    assert kinds == {"declared", "not_observed"}, (
        f"report_outcome admits {sorted(kinds)}; an 'observed' branch would let "
        "an unverifiable claim be typed as evidence"
    )
    declaration = branches[0]["properties"]["declarations"]["items"]
    assert declaration["properties"]["kind"]["const"] == "declared"


def test_the_block_says_what_not_being_recomputed_costs(tmp_path: Path) -> None:
    """ "Not recomputed" alone reads as a protection. It is the opposite.

    `verify` excludes this block, so nothing here is checked against anything
    -- including a declaration edited after the report was written. A reader
    who mistakes an unguarded field for a guarded one is worse off than one
    told plainly, so the block must say so in words.
    """
    payload = outcome_payload(load_outcome_input(_attested(tmp_path)))
    text = " ".join(payload["limitations"]).lower()
    assert "not observations" in text, text
    assert "verify" in text, text
    assert "not detected by verify" in text, (
        f"the block claims it is not recomputed without saying that a modified "
        f"declaration therefore goes undetected: {text}"
    )


def test_the_recompute_path_never_builds_a_declaration() -> None:
    """If `verify` ever recomputed this, it would be asserting someone's word.

    The grep is aimed at the two modules that actually recompute -- `verify`
    and the `analyze_subject` it calls -- rather than at the CLI entry point,
    which only parses arguments and dispatches. Reading the wrong file made
    this pass for a reason unrelated to the property.
    """
    import inspect

    from tep_core import analyze_v2, verify

    source = Path(verify.__file__).read_text(encoding="utf-8")
    for builder in ("outcome_payload", "load_outcome_input"):
        assert builder not in source, (
            f"the verify path reaches {builder}; a declaration must not take part in recomputation"
        )
    assert verify.NOT_RECOMPUTED_PATHS == {"outcome"}, (
        f"verify excludes {sorted(verify.NOT_RECOMPUTED_PATHS)} from its diff; "
        "everything beyond the declared outcome is an observation that stopped "
        "being checked"
    )
    parameter = inspect.signature(analyze_v2.analyze_subject).parameters["outcome_declaration"]
    assert parameter.default is None, (
        "analyze_subject would read a declaration file the verifier never chose"
    )


def _repo_with_history(tmp_path: Path) -> Path:
    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    for index in range(4):
        commit(
            repo,
            email="alice@example.com",
            date=f"2026-01-{index + 1:02d}",
            message=f"feat: change {index}",
            filename="src/app.py",
            name="Alice",
        )
    return repo


def test_a_declared_outcome_does_not_make_a_report_unverifiable(tmp_path: Path) -> None:
    """The declaration rides along; it is not part of what verify re-derives.

    Both halves matter. A report carrying a declaration must verify, and it
    must still verify once the declaration file is gone -- because the file was
    never an input to the recomputation, and requiring it back would make an
    unverifiable claim a precondition for verifying the observations.
    """
    from tep_cli.__main__ import main

    repo = _repo_with_history(tmp_path)
    declaration = _attested(tmp_path)
    report = tmp_path / "report.json"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--format",
                "json",
                "--out",
                str(report),
                "--outcome-declaration",
                str(declaration),
            ]
        )
        == 0
    )
    assert json.loads(report.read_text(encoding="utf-8"))["outcome"]["kind"] == "declared"

    assert main(["verify", str(report), "--repo", str(repo)]) == 0
    declaration.unlink()
    assert main(["verify", str(report), "--repo", str(repo)]) == 0, (
        "verify demanded the declaration file back; it is not a recompute input"
    )


def test_the_exclusion_did_not_stop_verify_checking_the_observations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The counterweight to the test above.

    Excluding a block from the diff is how a verifier stops verifying. This one
    edits a field that *is* an observation, in a report that also carries a
    declaration, and requires the mismatch to be found. If the exclusion ever
    widens past `outcome`, this is what fails.
    """
    from tep_cli.__main__ import main

    repo = _repo_with_history(tmp_path)
    report = tmp_path / "report.json"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--format",
                "json",
                "--out",
                str(report),
                "--outcome-declaration",
                str(_attested(tmp_path)),
            ]
        )
        == 0
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["context_profile"]["repo_age_days"]["kind"] == "observed"
    payload["context_profile"]["repo_age_days"]["value"] += 4000
    report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    capsys.readouterr()
    assert main(["verify", str(report), "--repo", str(repo)]) != 0, (
        "a falsified repo_age_days verified; the diff exclusion has grown past the declared outcome"
    )
    assert "context_profile.repo_age_days.value" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Who stands behind the claim
# --------------------------------------------------------------------------


def test_a_self_declared_outcome_says_so_first(tmp_path: Path) -> None:
    payload = outcome_payload(load_outcome_input(_self_declared(tmp_path)))
    first = payload["declarations"][0]["limitations"][0].lower()
    assert first.startswith("self-declared"), first
    assert "no external corroboration" in first, first


def test_an_attested_outcome_names_the_attesting_party(tmp_path: Path) -> None:
    payload = outcome_payload(load_outcome_input(_attested(tmp_path)))
    assert payload["declarations"][0]["attested_by"] == "Acme K.K."


def test_an_attestation_with_nobody_behind_it_is_refused(tmp_path: Path) -> None:
    """Refused, not silently downgraded to self_declared.

    Downgrading would accept a file whose author meant something else, and the
    difference is exactly what a reader relies on.
    """
    path = _write(
        tmp_path,
        declarations=[
            {"outcome": "delivered", "attestation": "counterparty_attested", "scope": "x"}
        ],
    )
    with pytest.raises(InputValidationError, match="attested_by is required"):
        load_outcome_input(path)


def test_a_self_declaration_may_not_borrow_an_attester(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        declarations=[
            {
                "outcome": "delivered",
                "attestation": "self_declared",
                "attested_by": "Acme K.K.",
                "scope": "x",
            }
        ],
    )
    with pytest.raises(InputValidationError, match="must be absent"):
        load_outcome_input(path)


def test_the_schema_enforces_the_attester_rule() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    declaration = {
        **schema["$defs"]["report_outcome"]["oneOf"][0]["properties"]["declarations"]["items"],
        "$defs": schema["$defs"],
    }
    borrowed = {
        "kind": "declared",
        "outcome": "delivered",
        "attestation": "self_declared",
        "attested_by": "Acme K.K.",
        "scope": "x",
        "definition_version": "outcome-v1",
        "limitations": ["x"],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(borrowed, declaration)

    unbacked = {
        "kind": "declared",
        "outcome": "delivered",
        "attestation": "counterparty_attested",
        "scope": "x",
        "definition_version": "outcome-v1",
        "limitations": ["x"],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(unbacked, declaration)


# --------------------------------------------------------------------------
# Absence, and the closed vocabularies
# --------------------------------------------------------------------------


def test_absence_is_not_failure() -> None:
    payload = outcome_payload(None)
    assert payload["kind"] == "not_observed"
    assert payload["reason"] == NOT_PROVIDED_REASON
    text = " ".join(payload["limitations"]).lower()
    assert "absence is not evidence that work did not ship" in text, text


def test_no_summary_or_tally_is_emitted(tmp_path: Path) -> None:
    """A count of delivered against not_delivered is a score made of claims."""
    path = _write(
        tmp_path,
        declarations=[
            {"outcome": "delivered", "attestation": "self_declared", "scope": "a"},
            {"outcome": "not_delivered", "attestation": "self_declared", "scope": "b"},
        ],
    )
    payload = outcome_payload(load_outcome_input(path))
    forbidden = {"summary", "delivered_count", "success_rate", "score", "ratio", "total"}
    assert forbidden.isdisjoint(payload), sorted(forbidden & set(payload))


@pytest.mark.parametrize("field,value", [("outcome", "great_success"), ("attestation", "trust_me")])
def test_an_undeclared_vocabulary_value_is_refused(tmp_path: Path, field: str, value: str) -> None:
    body = {"outcome": "delivered", "attestation": "self_declared", "scope": "x"}
    body[field] = value
    with pytest.raises(InputValidationError, match="must be one of"):
        load_outcome_input(_write(tmp_path, declarations=[body]))


def test_the_vocabularies_match_the_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    declaration = schema["$defs"]["report_outcome"]["oneOf"][0]["properties"]["declarations"][
        "items"
    ]
    assert set(declaration["properties"]["outcome"]["enum"]) == OUTCOME_KINDS
    assert set(declaration["properties"]["attestation"]["enum"]) == ATTESTATION_KINDS


def test_a_malformed_file_is_refused_not_ignored(tmp_path: Path) -> None:
    """Silently ignoring it would report not_observed for a file that exists."""
    path = tmp_path / "outcome.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(InputValidationError, match="not valid JSON"):
        load_outcome_input(path)

    path.write_text(json.dumps({"schema_version": "something-else"}), encoding="utf-8")
    with pytest.raises(InputValidationError, match="schema_version"):
        load_outcome_input(path)


def test_the_digest_binds_the_file(tmp_path: Path) -> None:
    first = load_outcome_input(_attested(tmp_path))
    again = load_outcome_input(_attested(tmp_path))
    assert first is not None and again is not None
    assert first.digest == again.digest
    changed = _write(
        tmp_path,
        declarations=[
            {
                "outcome": "delivered",
                "attestation": "counterparty_attested",
                "attested_by": "Different K.K.",
                "scope": "payments platform",
                "occurred_on": "2026-03-31",
            }
        ],
    )
    other = load_outcome_input(changed)
    assert other is not None and other.digest != first.digest
