"""v0.9.0 (a): the 0.8.0 discrepancies recorded in the trait-profile design §1.4.

`docs/design/trait-profile-20261026.md` §1.4 lists what a non-engineer misreads in
0.8.0 output and why. Each test here fails on 0.8.0 and names the row it closes.

Boundaries (PR body): single person ↔ team repository (a relationship must not
divide one person's commit count by a whole team's), declaration ↔ artifact
(a window label must say what was counted), and real git ↔ alignment JSON (every
case runs the CLI on real repositories, no hand-built axes).
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from git_fixture import commit, git, init_repo

from tep_cli.__main__ import main
from tep_core.tendency import surface_tendency

AS_OF = "2026-08-31"
SPAN_START = date(2026, 6, 1)
PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "payments-api"
title = "決済 API の保守"

[requirements.change_rhythm]
median_gap_days_max = 7

[requirements.surfaces]
required = ["backend", "test"]

[requirements.verification]
required = ["unit"]

[requirements.inputs]
required = ["git"]

[requirements.role_lens]
name = "backend"
"""
IDENTITY = """schema_version = "identity-v2"

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "claimed"
consent = "recorded-explicit-consent"
authority = "subject-authorization"
"""


def _day(offset: int) -> str:
    return (SPAN_START + timedelta(days=offset)).isoformat()


def _work(repo: Path, email: str, name: str, index: int, day: str) -> None:
    """Seven of every twelve commits touch backend code, five touch unit tests.

    The backend commits keep editing one file, so file-change shares and
    commit shares differ and a test can tell which one was read.
    """

    if index % 12 < 7:
        filename, message = "src/api/svc.py", f"feat: svc {index}"
    else:
        filename, message = f"tests/test_svc_{index}.py", f"test: svc {index}"
    commit(repo, email=email, date=day, message=message, filename=filename, name=name)


OLD_DAY = "2026-01-15"  # before the 180-day window that starts 2026-03-04


def _person_repo(tmp: Path) -> Path:
    repo = init_repo(tmp / "person")
    commit(
        repo,
        email="alice@example.com",
        date=OLD_DAY,
        message="docs: notes",
        filename="docs/notes.md",
        name="Alice",
    )
    for index in range(24):
        _work(repo, "alice@example.com", "Alice", index, _day(index * 2))
    return repo


def _team_repo(tmp: Path) -> Path:
    """Three people, the same mix of work as the person, three times the volume."""

    repo = init_repo(tmp / "team")
    people = [("p@example.com", "P"), ("q@example.com", "Q"), ("r@example.com", "R")]
    for index in range(72):
        email, name = people[index % 3]
        _work(repo, email, name, index, _day(index))
    return repo


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """One person repository, one team repository, every artifact the tests read."""

    tmp = tmp_path_factory.mktemp("v090a")
    person, team = _person_repo(tmp), _team_repo(tmp)
    identity, requirements = tmp / "identity.toml", tmp / "requirements.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    requirements.write_text(PROJECT_TOML, encoding="utf-8")
    actor_json, project_dir = tmp / "actor.json", tmp / "project-out"
    _cli(
        [
            "actor",
            "alice",
            str(person),
            "--identity",
            str(identity),
            "--as-of",
            AS_OF,
            "--format",
            "json",
            "--out",
            str(actor_json),
        ]
    )
    project = ["project", str(team), "--requirements", str(requirements), "--as-of", AS_OF]
    _cli([*project, "--format", "both", "--out", str(project_dir)])
    align = [
        "align",
        "--actor-report",
        str(actor_json),
        "--project-report",
        str(project_dir / "project.json"),
    ]
    return {
        "alignment": _cli([*align, "--format", "json"]),
        "alignment_md": _cli([*align, "--format", "md"]),
        "project_md": (project_dir / "project.md").read_text(encoding="utf-8"),
    }


def _axis(payload: dict, name: str) -> dict:
    return next(axis for axis in payload["axes"] if axis["axis"] == name)


def test_relationship_compares_shares_not_one_person_against_a_team(outputs) -> None:
    """§1.4 row 1: same mix of work at three times the volume is the same direction."""

    payload = json.loads(outputs["alignment"])
    backend = _axis(payload, "surfaces.backend")
    assert backend["actor_observed"]["value"] * 3 == backend["project_observed"]["value"]
    relation = backend["relationship"]
    assert relation["kind"] == "similar_direction", relation
    assert relation["compared"] == "commit_share", relation
    # The verdict carries the two shares it compared, so a reader can check it.
    assert relation["actor_share"] == {
        "kind": "observed",
        "value": round(14 / 25, 4),
        "unit": "commit_share",
        "sample_size": 25,
    }, relation
    assert relation["project_share"]["value"] == round(42 / 72, 4), relation
    assert relation["project_share"]["sample_size"] == 72, relation
    # The Markdown no longer prints relationship (v0.9.0 (c)); the JSON keeps the shares.
    assert "relationship surfaces.backend" not in outputs["alignment_md"]
    unit = _axis(payload, "verification.unit")["relationship"]
    # Ten unit-test commits sit below the rate gate, so the person's test-type
    # share is not observed and the axis is not compared (0.8.0 divided 10 by 30).
    assert unit["kind"] == "not_comparable", unit
    assert unit["reason"] == "observed_unavailable", unit
    assert unit["compared"] == "commit_share", unit
    assert unit["actor_share"] == {"kind": "not_observed", "reason": "insufficient_population"}


def test_rhythm_relationship_is_not_comparable_between_a_person_and_a_repository(
    outputs,
) -> None:
    """§1.4 row 1: a repository's gaps mix every member's commits; one person's do not."""

    payload = json.loads(outputs["alignment"])
    for name in (
        "change_rhythm.active_days_180d",
        "change_rhythm.median_gap_days",
        "change_rhythm.p90_gap_days",
    ):
        axis = _axis(payload, name)
        relation = axis["relationship"]
        assert relation["kind"] == "not_comparable", (name, relation)
        assert relation["reason"] == "scope_not_equivalent", (name, relation)
        assert axis["coverage"] == {"status": "partial", "missing": ["comparable_scope"]}, name


def test_surface_axis_window_says_the_whole_history_was_counted(outputs) -> None:
    """§1.4 row 2: surface counts cover the history up to the observation date."""

    payload = json.loads(outputs["alignment"])
    for name in ("surfaces.backend", "verification.unit"):
        axis = _axis(payload, name)
        for key in ("actor_window", "project_window"):
            assert axis[key]["basis"] == "history_to_observation_date", (name, axis[key])
            assert axis[key]["end"] == AS_OF, name
        assert axis["actor_basis"]["window"] == axis["actor_window"], name
    rhythm = _axis(payload, "change_rhythm.median_gap_days")
    assert rhythm["actor_window"]["start"] == "2026-03-04"
    assert rhythm["actor_window"]["end"] == AS_OF
    # The label matches what was counted: the commit before 2026-03-04 is in the
    # surface counts and outside the 180-day rhythm window.
    actor = payload["actor_observed"]
    assert actor["surface_profile"]["surface_commit_counts"]["values"]["docs"] == 1
    assert actor["change_rhythm"]["window_population"] == 24
    # The tendency basis keeps the machine string in JSON; Markdown says it in words.
    backend = _axis(payload, "surfaces.backend")
    assert backend["actor_tendency"]["basis"]["window"] == f"history/{AS_OF}"
    assert "history/" not in outputs["alignment_md"]
    assert f"actor_window={AS_OF} までの履歴" in outputs["alignment_md"]
    assert f"window={AS_OF} までの履歴 source=" in outputs["alignment_md"]


def test_verification_axis_is_not_labelled_as_a_surface(outputs) -> None:
    """§1.4 row 7: 0.8.0 printed `宣言=unit surface` for a test type."""

    payload = json.loads(outputs["alignment"])
    assert _axis(payload, "verification.unit")["declared"]["unit"] == "verification-type"
    assert _axis(payload, "surfaces.backend")["declared"]["unit"] == "surface"


def test_rhythm_tendency_does_not_claim_a_regular_cadence(outputs) -> None:
    """§1.4 row 3: 0.8.0 called every observed median `regular_submission_direction`."""

    payload = json.loads(outputs["alignment"])
    tendency = _axis(payload, "change_rhythm.median_gap_days")["actor_tendency"]
    assert tendency["kind"] == "directional", tendency
    assert tendency["value"] == "rhythm_observed", tendency
    assert "定期的な変更提出" not in outputs["alignment_md"]
    assert "定期的な変更提出" not in outputs["project_md"]


def test_surface_tendency_counts_commits_like_the_surface_list(outputs) -> None:
    """§1.4 row 4: the tendency used file changes while the list counted commits."""

    payload = json.loads(outputs["alignment"])
    tendency = _axis(payload, "surfaces.backend")["actor_tendency"]
    share = payload["actor_observed"]["surface_profile"]["surface_commit_share"]
    assert tendency["basis"]["metric"] == "surface_profile.surface_commit_share.backend"
    assert tendency["basis"]["observed"] == share["values"]["backend"]
    assert tendency["basis"]["n"] == share["sample_size"]


def test_surface_tendency_is_not_proven_when_the_share_is_not_observed() -> None:
    """§1.4 row 9: an unobserved share was read as 0.0 and `test` won the tie.

    The block carries a sample size and its own reason, so only the share's
    `kind` can stop the ranking here.
    """

    unobserved = {"kind": "not_observed", "reason": "share_not_computed", "sample_size": 25}
    counts = {"kind": "observed", "sample_size": 25, "values": {"test": 3, "backend": 3}}
    profile = {
        "kind": "observed",
        "surface_commit_counts": counts,
        "surface_commit_share": unobserved,
        "surface_file_counts": counts,
        "surface_file_share": unobserved,
    }
    node = surface_tendency(profile, window="2026-03-04/2026-08-31", source=["git:path"])
    assert node["kind"] == "not_proven", node
    assert node["reason"] == "share_not_computed", node


def _code_and_test_repo(tmp: Path) -> Path:
    """Every commit changes a backend file and its unit test together."""

    repo = init_repo(tmp / "paired")
    for index in range(24):
        code = repo / "src" / "api" / f"svc_{index}.py"
        code.parent.mkdir(parents=True, exist_ok=True)
        code.write_text(f"VALUE = {index}\n", encoding="utf-8")
        git(repo, "add", str(code.relative_to(repo)))
        commit(
            repo,
            email="alice@example.com",
            date=_day(index * 2),
            message=f"feat: svc {index} with test",
            filename=f"tests/test_svc_{index}.py",
            name="Alice",
        )
    return repo


def test_surface_tendency_names_no_surface_when_two_shares_tie(tmp_path: Path) -> None:
    """Commit shares count a code-and-test commit for both surfaces, so ties are real.

    The stable sort used to hand a tie to the first name in SURFACES (`test`).
    """

    repo = _code_and_test_repo(tmp_path)
    identity = tmp_path / "identity.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    base = ["actor", "alice", str(repo), "--identity", str(identity), "--as-of", AS_OF]
    report = json.loads(_cli([*base, "--format", "json"]))
    shares = report["surface_profile"]["surface_commit_share"]["values"]
    assert shares["backend"] == shares["test"] == 1.0, shares
    node = surface_tendency(report["surface_profile"], window="history", source=["git:path"])
    assert node["kind"] == "not_proven", node
    assert node["reason"] == "tied_top_share", node
    assert node["tied"] == ["test", "backend"], node
    assert "系surfaceが相対的に多い傾向" not in _cli([*base, "--format", "md"])


def test_project_and_alignment_markdown_show_the_title_without_unit_names(outputs) -> None:
    """§1.4 row 6: the TOML title was dropped and unit names were glued to values."""

    for name in ("project_md", "alignment_md"):
        text = outputs[name]
        assert "決済 API の保守" in text, name
        for token in (
            "surface-names",
            "verification-types",
            "input-kinds",
            "unit surface",
            "backend lens",
            "git input",
        ):
            assert token not in text, (name, token)
    assert "payments-api id" not in outputs["project_md"]
    # Only the kind-only unit names go: a declared amount keeps its unit.
    assert "宣言=7 days" in outputs["alignment_md"]


def test_history_window_without_an_observation_date_is_not_printed_as_none() -> None:
    """A report saved without `observation_date` has no end date to name."""

    from tep_core.report_v2 import _window_text
    from tep_core.v2_constants import HISTORY_WINDOW_BASIS, HISTORY_WINDOW_PREFIX

    assert _window_text({"basis": HISTORY_WINDOW_BASIS, "end": None}) == "—"
    assert _window_text(HISTORY_WINDOW_PREFIX) == "—"
    assert _window_text(f"{HISTORY_WINDOW_PREFIX}{AS_OF}") == f"{AS_OF} までの履歴"


def test_markdown_says_plainly_when_the_project_has_no_title() -> None:
    """§1.4 row 6: a missing title is not a requirement, so no requirement boilerplate."""

    from tep_core.report_v2 import render_alignment_markdown, render_project_markdown

    untitled = {"kind": "not_declared", "reason": "requirement_not_provided"}
    project = render_project_markdown({"declared": {"title": untitled}})
    alignment = render_alignment_markdown({"declared": {"title": untitled}})
    for text in (project, alignment):
        title_line = next(line for line in text.splitlines() if "- 題名:" in line)
        assert "不足ではない" not in title_line, title_line
        assert "案件側が書いていません" in title_line, title_line


ROOT = Path(__file__).resolve().parents[1]
SURVIVAL_GUIDES = {
    "docs/metrics-guide.md": (
        "## survival",
        ("180日後も残っている行の割合", "6ヶ月経ってもほぼ残っている", "ほぼ全行が残存"),
    ),
    "docs/en/metrics-guide.md": (
        "## Survival",
        ("still present after 180 days", "lines mostly still present"),
    ),
}


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def test_metrics_guide_describes_survival_the_way_survival_py_computes_it() -> None:
    """§1.4 row 10: the guide read survival as a share of lines kept for 180 days.

    `survival.py` averages exp(-age/τ) over the lines blamed at HEAD in up to
    DEFAULT_MAX_FILES sampled files, so a value near 1 means most current lines
    are recent. The guide and the constants are tied here, both ways.
    """

    from tep_core.survival import DEFAULT_MAX_FILES, TAU_DAYS

    for path, (heading, wrong) in SURVIVAL_GUIDES.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for phrase in wrong:
            assert phrase not in text, (path, phrase)
        section = _section(text, heading)
        assert f"τ={TAU_DAYS}" in section, (path, TAU_DAYS)
        assert str(DEFAULT_MAX_FILES) in section, (path, DEFAULT_MAX_FILES)
        assert "exp(-" in section, path
