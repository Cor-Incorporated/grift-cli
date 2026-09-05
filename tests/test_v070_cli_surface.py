"""The v0.7.0 flags, exercised through the process entry point.

Three flags shipped in v0.7.0 -- `--purpose`, `--outcome-declaration` and
`align --team` -- and every test that covered them stopped at the boundary the
user never touches: the parser was introspected, or the builder function was
called with a hand-written dict. Both can agree while the command still refuses
to run, because argparse wiring, subcommand dispatch and the exit code live
between them.

So each test here calls `tep_cli.__main__.main` with the argument list a person
would type, reads what the process wrote, and asserts on the exit code. Nothing
in this module constructs a report by hand: the actor cards `align --team`
reads are produced by running `grift actor`, which is what makes the test able
to fail when the report shape and the reader drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.contribution_v2 import PURPOSES

from git_fixture import commit, init_repo

OUTCOME_LINKAGE = "outcome-linkage"


def _day(index: int) -> str:
    """A calendar date for the nth commit, without overflowing a month."""
    return f"2026-{(index // 27) + 1:02d}-{(index % 27) + 1:02d}"


def _repo(tmp_path: Path, *, name: str = "repo", commits: int = 6) -> Path:
    repo = init_repo(tmp_path / name)
    for index in range(commits):
        commit(
            repo,
            email="alice@example.com",
            date=_day(index),
            message=f"feat: change {index}",
            filename="src/app.py",
            name="Alice",
        )
    return repo


def _outcome_declaration(tmp_path: Path) -> Path:
    path = tmp_path / "outcome.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "tep-outcome-declaration-v1",
                "declarations": [
                    {
                        "outcome": "delivered",
                        "attestation": "counterparty_attested",
                        "attested_by": "Acme K.K.",
                        "scope": "payments platform",
                        "occurred_on": "2026-03-31",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _repo_report(tmp_path: Path, repo: Path, *, extra: list[str] | None = None) -> Path:
    out = tmp_path / "report.json"
    assert main(["repo", str(repo), "--format", "json", "--out", str(out), *(extra or [])]) == 0
    return out


# --------------------------------------------------------------------------
# --purpose: the value reaches the payload, and the refused door refuses
# --------------------------------------------------------------------------


def test_purpose_reaches_the_payload_through_the_local_door(tmp_path: Path) -> None:
    report = _repo_report(tmp_path, _repo(tmp_path))
    payload = tmp_path / "payload.json"
    code = main(
        [
            "contribute",
            str(report),
            "--out",
            str(payload),
            "--purpose",
            OUTCOME_LINKAGE,
            "--door",
            "local",
            "--yes",
        ]
    )
    assert code == 0
    assert json.loads(payload.read_text(encoding="utf-8"))["purpose"] == PURPOSES[OUTCOME_LINKAGE]


def test_the_public_door_refuses_the_purpose_it_cannot_deliver(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal must name the door, or the submitter cannot act on it.

    `PURPOSE_DOORS` is checked at build time, but a check the CLI never reaches
    -- because the flag is misspelled in the parser, or the exception is
    swallowed into a zero exit -- would let the payload be written and bounce
    at the public intake instead.
    """
    report = _repo_report(tmp_path, _repo(tmp_path))
    code = main(
        [
            "contribute",
            str(report),
            "--out",
            str(tmp_path / "payload.json"),
            "--purpose",
            OUTCOME_LINKAGE,
            "--door",
            "public-pr",
            "--yes",
        ]
    )
    assert code != 0
    assert "cannot use door 'public-pr'" in capsys.readouterr().err
    assert not (tmp_path / "payload.json").exists(), "a refused submission still wrote a payload"


# --------------------------------------------------------------------------
# --outcome-declaration: carried where a report can hold it, absent elsewhere
# --------------------------------------------------------------------------


def test_a_declared_outcome_reaches_the_repo_report(tmp_path: Path) -> None:
    out = _repo_report(
        tmp_path,
        _repo(tmp_path),
        extra=["--outcome-declaration", str(_outcome_declaration(tmp_path))],
    )
    outcome = json.loads(out.read_text(encoding="utf-8"))["outcome"]
    assert outcome["kind"] == "declared"
    assert outcome["declarations"][0]["attested_by"] == "Acme K.K."


@pytest.mark.parametrize("command", ["project", "align"])
def test_the_flag_is_absent_where_no_report_can_carry_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """`project` and `align` emit no `report_outcome`, so accepting the file
    silently discarded it -- and a report with no outcome reads as "nothing was
    declared" (norms §1)."""
    with pytest.raises(SystemExit) as exit_info:
        main([command, "--outcome-declaration", str(_outcome_declaration(tmp_path))])
    assert exit_info.value.code == 2
    assert "unrecognized arguments: --outcome-declaration" in capsys.readouterr().err


# --------------------------------------------------------------------------
# align --team: over real actor cards, not hand-written dicts
# --------------------------------------------------------------------------

TEAM = ("alice", "bob", "carol")


def _team_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "team-repo")
    index = 0
    for actor in TEAM:
        for round_index in range(6):
            for kind, path in (
                ("feat", f"src/{actor}_{round_index}.py"),
                ("test", f"tests/test_{actor}_{round_index}.py"),
            ):
                commit(
                    repo,
                    email=f"{actor}@example.com",
                    date=_day(index),
                    message=f"{kind}: {actor} {round_index}",
                    filename=path,
                    name=actor.capitalize(),
                )
                index += 1
    return repo


def _team_identity(tmp_path: Path) -> Path:
    path = tmp_path / "identity.toml"
    blocks = "".join(
        "\n[[actors]]\n"
        f'canonical_id = "{actor}"\n'
        f'emails = ["{actor}@example.com"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n'
        for actor in TEAM
    )
    path.write_text('schema_version = "identity-v2"\n' + blocks, encoding="utf-8")
    return path


def _project_report(tmp_path: Path, repo: Path) -> Path:
    requirements = tmp_path / "project.toml"
    requirements.write_text(
        'schema_version = "tep-project-v1"\n'
        'project_id = "demo"\n'
        'title = "Demo"\n'
        "\n[requirements.surfaces]\n"
        'required = ["test", "backend", "observability"]\n'
        "\n[requirements.verification]\n"
        'required = ["unit"]\n',
        encoding="utf-8",
    )
    out = tmp_path / "project.json"
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
    )
    return out


def test_team_reads_the_cards_grift_actor_actually_wrote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every input here is produced by the CLI, so a change to the report shape
    that the team reader does not follow fails this test instead of passing
    against a dict written to match the reader."""
    repo = _team_repo(tmp_path)
    identity = _team_identity(tmp_path)
    cards = tmp_path / "cards" / "actors"
    cards.mkdir(parents=True)
    for actor in TEAM:
        assert (
            main(
                [
                    "actor",
                    actor,
                    str(repo),
                    "--identity",
                    str(identity),
                    "--format",
                    "json",
                    "--out",
                    str(cards / f"{actor}.json"),
                ]
            )
            == 0
        ), f"grift actor did not produce a card for {actor}"
    for card in sorted(cards.glob("*.json")):
        assert json.loads(card.read_text(encoding="utf-8"))["schema_version"] == "report-v2"

    project = _project_report(tmp_path, repo)
    capsys.readouterr()
    code = main(
        [
            "align",
            "--team",
            "--actor-dir",
            str(cards.parent),
            "--project-report",
            str(project),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "observed", payload
    assert payload["team_size"] == len(TEAM), payload
