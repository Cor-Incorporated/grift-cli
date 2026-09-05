"""W5 — team coverage gaps that cannot be turned back into per-person values.

Two readers were held in mind while writing these, and each has a test that
fails when their side of the bargain is broken.

The client asks: is anything my project needs missing here, how deeply is what
*is* covered held, and how much of this did you actually manage to look at.

The engineer asks: does any number here rank me against the person next to me,
and does "not covered" get printed when the truth is "not measured".

The second reader is the one the tool can hurt, so most of the file is theirs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tep_core.complementarity import (
    BELOW_DECLARED,
    COVERED,
    MIN_TEAM_SIZE,
    NOT_OBSERVED,
    build_complementarity,
)

SCHEMA = Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json"

DECLARED = {
    "surfaces": {
        "kind": "declared",
        "value": ["test", "observability"],
        "min_share": {"test": 0.20, "observability": 0.20},
    },
    "verification": {"kind": "declared", "value": ["e2e"], "min_share": {"e2e": 0.10}},
}


def _actor(test: float, observability: float) -> dict:
    return {
        "surface_profile": {
            "kind": "observed",
            "surface_commit_counts": {
                "values": {"test": int(test * 100), "observability": int(observability * 100)}
            },
            "surface_commit_share": {"values": {"test": test, "observability": observability}},
        },
        "verification_profile": {
            "kind": "not_observed",
            "reason": "no_test_framework_or_directory",
        },
    }


def _blind_actor() -> dict:
    return {
        "surface_profile": {"kind": "not_observed", "reason": "commit_paths_unavailable"},
        "verification_profile": {"kind": "not_observed", "reason": "no_test_framework"},
    }


def _team(*actors: dict) -> dict:
    return build_complementarity(
        actor_reports=list(actors), declared=DECLARED, project_digest="d" * 64
    )


def _requirement(report: dict, axis: str) -> dict:
    for item in report["requirements"]:
        if item["requirement"] == axis:
            return item
    raise AssertionError(
        f"{axis} not emitted: {[r['requirement'] for r in report['requirements']]}"
    )


STANDARD = (
    _actor(0.50, 0.04),
    _actor(0.35, 0.00),
    _actor(0.11, 0.06),
    _actor(0.40, 0.02),
    _actor(0.05, 0.00),
)


# --------------------------------------------------------------------------
# The engineer's side: nothing here ranks anyone
# --------------------------------------------------------------------------

PERSON_SHAPED = {
    "actors",
    "actor_ids",
    "per_actor",
    "members",
    "by_actor",
    "contributors",
    "ranking",
    "rank",
    "score",
    "best",
    "top",
    "leader",
    "strongest",
    "max_share",
    "shares",
}


def _walk(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def test_no_person_shaped_key_appears_anywhere() -> None:
    report = _team(*STANDARD)
    offenders = [f"{path}.{key}" for path, key, _ in _walk(report) if key in PERSON_SHAPED]
    assert not offenders, offenders


# norms `align --team` 例外条件 2 の強制側。key 名だけを見る
# `test_no_person_shaped_key_appears_anywhere` は、順序の語彙が値の側
# —— `state` や `reason`、`limitations` の文—— に現れたときに何も言えない。
# 「1 位」を key で名乗らなくても、文で名乗れば同じことが起きる。
_ORDER_WORDS = {
    "rank",
    "ranks",
    "ranked",
    "ranking",
    "rankings",
    "top",
    "best",
    "strongest",
    "weakest",
    "leader",
    "leaders",
    "first",
    "last",
    "above",
    "below",
}

# 順序を否定する文だけは、その語を含んでよい。「順位を付けない」と
# 書くには "rank" が要る。許すのは否定の言い回しそのものであって、
# 語ではない: 新しい文が裸の "rank" を持ち込めば下の assert は落ちる。
# `below_declared` は state 名で、`[a-z_]+` の 1 トークンとして数える
# ため、そもそも "below" には一致しない。
_DISCLAIMER_PHRASES = {
    "rank": ("cannot rank",),
    "below": ("below its floor",),
}


def _strings(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def test_no_ordering_vocabulary_appears_in_any_value() -> None:
    offenders = []
    for report in (_team(*STANDARD), _team(*STANDARD, _blind_actor())):
        for path, text in _strings(report):
            lowered = text.lower()
            for token in set(re.findall(r"[a-z_]+", lowered)) & _ORDER_WORDS:
                allowed = _DISCLAIMER_PHRASES.get(token, ())
                if any(phrase in lowered for phrase in allowed):
                    continue
                offenders.append(f"{path}: {token!r} in {text!r}")
    assert not offenders, offenders


def test_no_individual_measurement_escapes() -> None:
    """Even one actor's share, emitted anonymously, is a per-person value.

    The team is built so that exactly one actor holds 0.06 observability. If any
    float in the output equals a single actor's input, a number about a person
    left the module.
    """
    report = _team(*STANDARD)
    # Declared floors (0.20, 0.10) legitimately appear in the output; every
    # value below is one an actor produced, and none collides with a floor.
    individual_values = {0.50, 0.35, 0.11, 0.40, 0.05, 0.04, 0.06, 0.02}
    emitted = {
        value
        for _, _, value in _walk(report)
        if isinstance(value, float) and not isinstance(value, bool)
    }
    leaked = emitted & individual_values
    assert not leaked, (
        f"these values came from individual actors and appear in the team report: {sorted(leaked)}"
    )


def test_counts_are_integers_not_identities() -> None:
    covered = _requirement(_team(*STANDARD), "surfaces.test")
    assert isinstance(covered["meeting_declared"], int)
    assert isinstance(covered["with_any_observation"], int)
    assert covered["meeting_declared"] <= covered["team_size"]


def test_a_team_below_the_minimum_is_refused() -> None:
    """With two actors, "covered by 1 of 2" names a person by elimination."""
    report = _team(*STANDARD[: MIN_TEAM_SIZE - 1])
    assert report["kind"] == "not_observed"
    assert report["reason"] == "insufficient_team_size"
    assert "requirements" not in report


def test_the_report_says_it_is_not_about_individuals() -> None:
    text = " ".join(_team(*STANDARD)["limitations"]).lower()
    assert "never which" in text or "not input to a decision about any individual" in text, text


# --------------------------------------------------------------------------
# Three states, because two would libel someone
# --------------------------------------------------------------------------


def test_an_unmeasurable_requirement_is_not_a_gap() -> None:
    """`verification` is not_observed for every actor: no test framework found.

    Reporting that as "not covered" would say the team cannot write end-to-end
    tests, when what happened is that grift did not look at any.
    """
    item = _requirement(_team(*STANDARD), "verification.e2e")
    assert item["state"] == NOT_OBSERVED
    assert "meeting_declared" not in item, (
        "an unmeasured requirement reported a coverage count, which reads as zero"
    )
    assert item["actors_observed"] == 0


def test_measured_and_short_is_distinct_from_unmeasured() -> None:
    item = _requirement(_team(*STANDARD), "surfaces.observability")
    assert item["state"] == BELOW_DECLARED
    assert item["meeting_declared"] == 0
    assert item["actors_observed"] == 5


def test_a_met_requirement_reports_its_depth() -> None:
    item = _requirement(_team(*STANDARD), "surfaces.test")
    assert item["state"] == COVERED
    assert item["meeting_declared"] == 3, "0.50, 0.35 and 0.40 clear the 0.20 floor"


def test_ramp_up_is_distinguishable_from_from_scratch() -> None:
    """The client's duration question turns on exactly this difference."""
    touched = _requirement(_team(*STANDARD), "surfaces.observability")
    assert touched["meeting_declared"] == 0
    assert touched["with_any_observation"] == 3, (
        "three actors have non-zero observability work; without this count the "
        "client cannot tell ramp-up from starting cold"
    )

    cold = _team(*(_actor(0.50, 0.0) for _ in range(5)))
    cold_item = _requirement(cold, "surfaces.observability")
    assert cold_item["with_any_observation"] == 0
    assert cold_item["state"] == BELOW_DECLARED


def test_an_actor_who_cannot_be_measured_does_not_count_as_uncovered() -> None:
    with_blind = _team(*STANDARD, _blind_actor())
    item = _requirement(with_blind, "surfaces.test")
    assert item["team_size"] == 6
    assert item["actors_observed"] == 5, (
        "the actor with no commit paths was counted as observed, so their "
        "absence of evidence became evidence of absence"
    )


# --------------------------------------------------------------------------
# The client's side: observability comes first
# --------------------------------------------------------------------------


def test_observability_is_reported_before_the_requirements() -> None:
    report = _team(*STANDARD)
    keys = list(report)
    assert keys.index("observability") < keys.index("requirements")


def test_observability_counts_match_the_requirement_states() -> None:
    report = _team(*STANDARD)
    block = report["observability"]
    unobservable = sum(1 for r in report["requirements"] if r["state"] == NOT_OBSERVED)
    assert block["declared_requirements"] == len(report["requirements"])
    assert block["not_observable"] == unobservable
    assert block["observable"] == block["declared_requirements"] - unobservable
    assert block["share"] == pytest.approx(
        block["observable"] / block["declared_requirements"], abs=1e-4
    )


def test_the_observability_rate_leads_the_limitations() -> None:
    report = _team(*STANDARD)
    first = report["limitations"][0]
    assert "could be observed" in first, first
    assert str(report["observability"]["observable"]) in first


def test_two_reports_are_declared_not_comparable() -> None:
    text = " ".join(_team(*STANDARD)["limitations"]).lower()
    assert "not comparable" in text, text


# --------------------------------------------------------------------------
# Degenerate inputs
# --------------------------------------------------------------------------


def test_a_project_declaring_nothing_named_is_not_observed() -> None:
    report = build_complementarity(
        actor_reports=list(STANDARD), declared={}, project_digest="d" * 64
    )
    assert report["kind"] == "not_observed"
    assert report["reason"] == "no_named_requirements_declared"


def test_output_is_independent_of_actor_order() -> None:
    forward = _team(*STANDARD)
    backward = _team(*reversed(STANDARD))
    assert forward == backward


# --------------------------------------------------------------------------
# Declaration <-> enforcement
# --------------------------------------------------------------------------


def test_the_schema_forbids_a_per_actor_structure() -> None:
    """The type is what keeps this true once nobody is reading the diff."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    block = schema["$defs"]["report_complementarity"]["oneOf"][0]
    assert block["additionalProperties"] is False
    assert PERSON_SHAPED.isdisjoint(block["properties"]), sorted(
        PERSON_SHAPED & set(block["properties"])
    )
    requirement = block["properties"]["requirements"]["items"]["oneOf"][0]
    assert requirement["additionalProperties"] is False
    assert PERSON_SHAPED.isdisjoint(requirement["properties"]), sorted(
        PERSON_SHAPED & set(requirement["properties"])
    )


def test_the_schema_accepts_every_shape_the_builder_emits() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    definition = {**schema["$defs"]["report_complementarity"], "$defs": schema["$defs"]}
    for shape in (
        _team(*STANDARD),
        _team(*STANDARD, _blind_actor()),
        _team(*STANDARD[: MIN_TEAM_SIZE - 1]),
        build_complementarity(actor_reports=list(STANDARD), declared={}, project_digest="d" * 64),
    ):
        jsonschema.validate(shape, definition)


# --------------------------------------------------------------------------
# 監査 #1 — CLI 経路。手組みの dict ではなく実 report を通す。
#
# 上のテストは build_complementarity に直接 dict を渡すので、CLI が
# 何を読み込んでいるかを一切確かめない。出荷 card は surface_profile
# を持たないため、CLI 経由では全要求が not_observed に落ちていたが、
# このファイルのどのテストもそれを検出できなかった。
# --------------------------------------------------------------------------

_TEAM = ("alice", "bob", "carol")
_EMAIL = {"alice": "a@example.com", "bob": "b@example.com", "carol": "c@example.com"}

_IDENTITY = 'schema_version = "identity-v2"\n\n' + "".join(
    f"[[actors]]\ncanonical_id = \"{actor}\"\n"
    f"emails = [\"{_EMAIL[actor]}\"]\n"
    'attribution_state = "verified"\n'
    'consent = "recorded-explicit-consent"\n'
    'authority = "subject-authorization"\n\n'
    for actor in _TEAM
)

_REQUIREMENTS = (
    'schema_version = "tep-project-v1"\n'
    'project_id = "acme-portal"\n\n'
    "[requirements.surfaces]\n"
    'required = ["backend"]\n\n'
    "[requirements.surfaces.min_share]\n"
    "backend = 0.20\n\n"
    "[requirements.verification]\n"
    'required = ["unit"]\n'
)


def _team_repo(tmp_path: Path) -> Path:
    """Three actors, each over `MIN_POPULATION_FOR_RATES`, so shares are real."""
    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    day = 0
    for actor in _TEAM:
        for index in range(21):
            day += 1
            is_test = index % 4 == 3
            path = (
                f"tests/unit/test_{actor}_{index}.py"
                if is_test
                else f"api/{actor}/service_{index}.py"
            )
            commit(
                repo,
                email=_EMAIL[actor],
                date=f"2025-{1 + day // 28:02d}-{1 + day % 28:02d}",
                message=("test: cover %s %d" if is_test else "feat: %s %d") % (actor, index),
                filename=path,
                name=actor.capitalize(),
            )
    return repo


def _project_report(tmp_path: Path, repo: Path, capsys) -> Path:
    from tep_cli.__main__ import main

    requirements = tmp_path / "requirements.toml"
    requirements.write_text(_REQUIREMENTS, encoding="utf-8")
    out = tmp_path / "project-out"
    assert (
        main(
            [
                "project",
                str(repo),
                "--requirements",
                str(requirements),
                "--format",
                "json",
                "--out",
                str(out),
            ]
        )
        == 0
    ), capsys.readouterr().err
    capsys.readouterr()
    return out / "project.json"


def _report_v2_dir(tmp_path: Path, repo: Path, capsys) -> Path:
    """Exactly the command the refusal message tells the operator to run."""
    from tep_cli.__main__ import main

    identity = tmp_path / "identity.toml"
    identity.write_text(_IDENTITY, encoding="utf-8")
    directory = tmp_path / "reports"
    directory.mkdir()
    for actor in _TEAM:
        assert (
            main(["actor", actor, str(repo), "--identity", str(identity), "--format", "json"]) == 0
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_version"] == "report-v2"
        (directory / f"{actor}.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def test_the_cli_team_path_observes_real_actor_reports(tmp_path: Path, capsys) -> None:
    """The defect: through the CLI every requirement came back not_observed."""
    from tep_cli.__main__ import main

    repo = _team_repo(tmp_path)
    project = _project_report(tmp_path, repo, capsys)
    directory = _report_v2_dir(tmp_path, repo, capsys)

    assert (
        main(
            [
                "align",
                "--actor-dir",
                str(directory),
                "--project-report",
                str(project),
                "--team",
            ]
        )
        == 0
    ), capsys.readouterr().err
    report = json.loads(capsys.readouterr().out)

    assert report["kind"] == "observed", report
    surfaces = _requirement(report, "surfaces.backend")
    assert surfaces["state"] != NOT_OBSERVED, (
        f"the CLI team path reported the surface as unobservable: {surfaces}"
    )
    assert surfaces["actors_observed"] == 3, surfaces
    assert surfaces["meeting_declared"] == 3, surfaces


def test_the_cli_team_path_refuses_the_shipped_actor_card(tmp_path: Path, capsys) -> None:
    """`actor-card-v1` carries no surface observations, so it must be refused.

    Accepting it produced a full-looking report in which every requirement was
    `not_observed` — a silence that read as a measurement of the team.
    """
    from tep_cli.__main__ import main

    repo = _team_repo(tmp_path)
    project = _project_report(tmp_path, repo, capsys)
    collection = tmp_path / "collection"
    assert (
        main(["repo", str(repo), "--actors", "--format", "json", "--out", str(collection)]) == 0
    ), capsys.readouterr().err
    capsys.readouterr()
    cards = sorted((collection / "actors").glob("*.json"))
    assert cards, "fixture did not produce actor cards"
    assert json.loads(cards[0].read_text(encoding="utf-8"))["schema_version"] == "actor-card-v1"

    code = main(
        [
            "align",
            "--actor-dir",
            str(collection),
            "--project-report",
            str(project),
            "--team",
        ]
    )
    error = capsys.readouterr().err
    assert code != 0, "the shipped card was accepted"
    assert "align --team requires report-v2 actor reports" in error, error
    assert "actor-card-v1 carries no surface observations" in error, error
    assert "grift actor <ID> --identity <toml> --format json" in error, error
