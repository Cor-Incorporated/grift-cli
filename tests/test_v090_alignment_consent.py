"""v0.9.0: interview questions in the alignment need the consent record (T7).

The actor report shows person-facing sentences only for a claimed identity with
`consent=recorded-explicit-consent`. The alignment asked its interview questions
for any claimed or verified identity, because alignment-v1 carried no consent
record. The user's decision (2026-10-26): when the consent record cannot be
confirmed, the alignment asks nothing. `grift align` now copies the record into
`subject.actor_consent` with the same function the actor report uses, and
`grift verify` rebuilds it from the actor report instead of trusting the saved one.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core import trait_tables as tables
from tep_core.schema_v2 import validate_alignment

AS_OF = "2026-08-31"
PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "payments-api"

[requirements.surfaces]
required = ["backend", "test", "data"]
"""
BASES = {
    "claimed": ("claimed", True),
    "claimed-noconsent": ("claimed", False),
    "verified": ("verified", True),
}


def _identity(state: str, consent: bool) -> str:
    lines = [
        'schema_version = "identity-v2"',
        "",
        "[[actors]]",
        'canonical_id = "alice"',
        'emails = ["alice@example.com"]',
        f'attribution_state = "{state}"',
    ]
    if consent:
        lines += ['consent = "recorded-explicit-consent"', 'authority = "subject-authorization"']
    return "\n".join(lines) + "\n"


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue()


def _cli(argv: list[str]) -> str:
    code, out = _run(argv)
    assert code == 0, (argv[0], out)
    return out


def _repo(path: Path, email: str, count: int) -> Path:
    repo = init_repo(path)
    start = date(2026, 6, 1)
    for index in range(count):
        day = (start + timedelta(days=index * 2)).isoformat()
        filename = "src/api/svc.py" if index % 3 else f"tests/test_svc_{index}.py"
        commit(repo, email=email, date=day, message=f"feat: {index}", filename=filename, name="A")
    return repo


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Path | str]]:
    tmp = tmp_path_factory.mktemp("v090consent")
    person = _repo(tmp / "person", "alice@example.com", 30)
    team = _repo(tmp / "team", "p@example.com", 30)
    requirements = tmp / "requirements.toml"
    requirements.write_text(PROJECT_TOML, encoding="utf-8")
    project_dir = tmp / "project-out"
    project = ["project", str(team), "--requirements", str(requirements), "--as-of", AS_OF]
    _cli([*project, "--format", "json", "--out", str(project_dir)])
    project_json = project_dir / "project.json"
    out: dict[str, dict[str, Path | str]] = {}
    for name, (state, consent) in BASES.items():
        identity = tmp / f"identity-{name}.toml"
        identity.write_text(_identity(state, consent), encoding="utf-8")
        actor_json = tmp / f"actor-{name}.json"
        actor = ["actor", "alice", str(person), "--identity", str(identity), "--as-of", AS_OF]
        _cli([*actor, "--format", "json", "--out", str(actor_json)])
        align = ["align", "--actor-report", str(actor_json), "--project-report", str(project_json)]
        alignment_json = tmp / f"alignment-{name}.json"
        _cli([*align, "--format", "json", "--out", str(alignment_json)])
        out[name] = {
            "actor": actor_json,
            "project": project_json,
            "alignment": alignment_json,
            "markdown": _cli([*align, "--format", "md"]),
        }
    return out


def _questions(markdown: str) -> str:
    return markdown.split(tables.HEADINGS["align_questions"], 1)[1].split("\n## ", 1)[0]


@pytest.mark.parametrize(
    ("name", "consent", "reason"),
    [
        ("claimed", "recorded-explicit-consent", None),
        ("claimed-noconsent", None, "no_consent"),
        ("verified", "recorded-explicit-consent", "admin_verified"),
    ],
)
def test_questions_need_a_claimed_identity_and_a_consent_record(
    runs, name: str, consent: str | None, reason: str | None
) -> None:
    payload = json.loads(Path(runs[name]["alignment"]).read_text(encoding="utf-8"))
    questions = _questions(str(runs[name]["markdown"]))
    facts = {
        "actor_consent": payload["subject"].get("actor_consent"),
        "asked": any(line.startswith("1. ") for line in questions.splitlines()),
        "not_shown": None
        if reason is None
        else tables.ALIGNMENT_TEXTS["questions_not_shown"].format(reason=tables.NOT_SHOWN[reason])
        in questions,
    }
    assert facts == {
        "actor_consent": consent,
        "asked": reason is None,
        "not_shown": None if reason is None else True,
    }, (name, facts, questions)


def _verify(runs, name: str, alignment: Path) -> tuple[int, str]:
    return _run(
        [
            "verify",
            str(alignment),
            "--actor-report",
            str(runs[name]["actor"]),
            "--project-report",
            str(runs[name]["project"]),
        ]
    )


def test_verify_rebuilds_the_consent_record_from_the_actor_report(runs, tmp_path: Path) -> None:
    saved = Path(runs["claimed"]["alignment"])
    code, out = _verify(runs, "claimed", saved)
    assert code == 0 and out.startswith("VERIFIED"), out
    for name, change in (("claimed", "drop"), ("claimed-noconsent", "add")):
        payload = json.loads(Path(runs[name]["alignment"]).read_text(encoding="utf-8"))
        if change == "drop":
            payload["subject"].pop("actor_consent")
        else:
            payload["subject"]["actor_consent"] = "recorded-explicit-consent"
        assert validate_alignment(payload) == [], (name, change)
        tampered = tmp_path / f"{name}-{change}.json"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        code, out = _verify(runs, name, tampered)
        assert code == 1 and out.startswith("MISMATCH") and "actor_consent" in out, (name, out)


def test_schema_holds_only_the_recorded_consent_and_never_for_a_public_cluster(runs) -> None:
    payload = json.loads(Path(runs["claimed"]["alignment"]).read_text(encoding="utf-8"))
    wrong = {**payload, "subject": {**payload["subject"], "actor_consent": "yes"}}
    public = {
        **payload,
        "subject": {
            key: value
            for key, value in payload["subject"].items()
            if key != "actor_attribution_state"
        }
        | {"actor_selection": "inferred_actor"},
    }
    errors = {
        "wrong": [e for e in validate_alignment(wrong) if "actor_consent" in e],
        "public": [e for e in validate_alignment(public) if "actor_consent" in e],
    }
    assert errors["wrong"] and errors["public"], errors
