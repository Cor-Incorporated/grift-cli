"""v0.9.0: the Markdown names the four viewpoints the way griftai.org does.

The site calls them 変えた部分の区分 / 変更のペース / テストの付け方 / 関わり方
(plain words, griftai `src/config/tep.ts`) with the site terms 作業領域 / 変更リズム /
検証の形 next to them; for role_profile the site term is the plain words, so that
heading is 関わり方 alone (and a heading never carries a number, T5). 0.9.0 first shipped other names
(「どこを触るか」, 「作業領域プロファイル」, 「変更提出の間隔」 ...), so a reader saw a
third vocabulary. The names are declared once, in docs/metrics-guide.md, and the
headings are tied to that table here. JSON keys and the JSON limitation texts
keep the site terms and do not change.

The site term 「定着率」 read survival backwards (it is how recently the lines at
HEAD were written, not how many lines stayed), so the glossary now says
「コードの新しさ」 / Code recency.
"""

from __future__ import annotations

import contextlib
import io
from datetime import date, timedelta
from pathlib import Path

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core.trait_tables import HEADINGS

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-31"
IDENTITY = """schema_version = "identity-v2"

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "claimed"
consent = "recorded-explicit-consent"
authority = "subject-authorization"
"""
PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "payments-api"

[requirements.surfaces]
required = ["backend", "test"]
"""
NAMES_HEADING = "## Markdown の観点の呼び名"
HEADING_KEY_BY_JSON_KEY = {
    "surface_profile": "places",
    "change_rhythm": "rhythm",
    "verification_profile": "verify",
    "role_profile": "make",
}
OLD_NAMES = (
    "どこを触るか",
    "どんな間隔で変更を出すか",
    "どう確かめるか",
    "作るか、手を入れるか",
    "作業領域プロファイル",
    "変更提出の間隔",
    "変更提出間隔",
    "検証の観測",
    "作業領域観測",
    "触る場所",
    "確かめ方",
)


def _heading_text(plain: str, site: str) -> str:
    return plain if site == plain else f"{plain}（{site}）"


def _names_table() -> dict[str, tuple[str, str]]:
    """JSON key -> (plain name, site term), from the one table in metrics-guide.md."""

    text = (ROOT / "docs" / "metrics-guide.md").read_text(encoding="utf-8")
    assert text.count(NAMES_HEADING) == 1, "the names table heading must appear exactly once"
    section = text.split(NAMES_HEADING, 1)[1].split("\n## ", 1)[0]
    rows: dict[str, tuple[str, str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 3 or cells[2].startswith("JSON"):
            continue
        if set("".join(cells)) <= {"-"}:
            continue
        rows[cells[2].strip("`")] = (cells[0], cells[1])
    return rows


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


def _repo(path: Path, email: str, count: int) -> Path:
    repo = init_repo(path)
    start = date(2026, 6, 1)
    for index in range(count):
        day = (start + timedelta(days=index * 2)).isoformat()
        filename = "src/api/svc.py" if index % 3 else f"tests/test_svc_{index}.py"
        commit(repo, email=email, date=day, message=f"feat: {index}", filename=filename, name="A")
    return repo


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    tmp = tmp_path_factory.mktemp("v090names")
    person = _repo(tmp / "person", "alice@example.com", 30)
    team = _repo(tmp / "team", "p@example.com", 30)
    identity = tmp / "identity.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    requirements = tmp / "requirements.toml"
    requirements.write_text(PROJECT_TOML, encoding="utf-8")
    actor = ["actor", "alice", str(person), "--identity", str(identity), "--as-of", AS_OF]
    actor_json = tmp / "actor.json"
    _cli([*actor, "--format", "json", "--out", str(actor_json)])
    project_dir = tmp / "project-out"
    project = ["project", str(team), "--requirements", str(requirements), "--as-of", AS_OF]
    _cli([*project, "--format", "both", "--out", str(project_dir)])
    align = [
        "align",
        "--actor-report",
        str(actor_json),
        "--project-report",
        str(project_dir / "project.json"),
        "--format",
        "md",
    ]
    return {
        "actor": _cli([*actor, "--format", "md"]),
        "repo": _cli(["repo", str(person), "--as-of", AS_OF, "--format", "md"]),
        "project": (project_dir / "project.md").read_text(encoding="utf-8"),
        "alignment": _cli(align),
    }


def test_metrics_guide_declares_the_names_the_headings_use() -> None:
    table = _names_table()
    assert set(table) == set(HEADING_KEY_BY_JSON_KEY), sorted(table)
    for json_key, (plain, site) in table.items():
        heading = HEADINGS[HEADING_KEY_BY_JSON_KEY[json_key]]
        assert heading == f"### {_heading_text(plain, site)}", (json_key, heading, plain, site)


def test_actor_markdown_uses_the_site_names_in_both_sections(outputs) -> None:
    text = outputs["actor"]
    for json_key, (plain, site) in _names_table().items():
        assert f"### {_heading_text(plain, site)}\n" in text, (json_key, plain, site)
    for detail in (
        "### 変えた部分の区分（作業領域、surface）",
        "### 変更のペース（変更リズム、change rhythm）",
        "### テストの付け方（検証の形、test path heuristic。QA 適性ではない）",
    ):
        assert detail in text, detail


@pytest.mark.parametrize("name", ["actor", "repo", "project", "alignment"])
def test_no_markdown_keeps_the_old_viewpoint_names(outputs, name: str) -> None:
    text = outputs[name]
    left = [old for old in OLD_NAMES if old in text]
    assert not left, (name, left)


def test_english_guide_and_readmes_carry_the_same_names() -> None:
    table = _names_table()
    english = (ROOT / "docs" / "en" / "metrics-guide.md").read_text(encoding="utf-8")
    for plain, site in table.values():
        assert f"| {_heading_text(plain, site)} |" in english, (plain, site)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for json_key in ("surface_profile", "change_rhythm", "verification_profile"):
        plain, site = table[json_key]
        assert f"- {_heading_text(plain, site)}: " in readme, (json_key, plain, site)


def test_survival_is_called_code_recency_not_teichakuritsu() -> None:
    guide = (ROOT / "docs" / "metrics-guide.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "docs" / "en" / "metrics-guide.md").read_text(encoding="utf-8")
    facts = {
        "guide_row": "| コードの新しさ | survival |" in guide,
        "guide_old": "定着率" in guide,
        "readme_new": "コードの新しさ" in readme,
        "readme_old": "定着率" in readme,
        "english": "Code recency" in english,
    }
    assert facts == {
        "guide_row": True,
        "guide_old": False,
        "readme_new": True,
        "readme_old": False,
        "english": True,
    }, facts
