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
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core import trait_tables
from tep_core.trait_tables import DECLARED_ITEM_NAMES, DECLARED_TEXTS, HEADINGS

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
# The detailed-numbers headings add what the numbers are to the name (report_v2_observed.py).
DETAIL_SUFFIXES = {
    "surface_profile": "surface",
    "change_rhythm": "change rhythm",
    "verification_profile": "test path heuristic。QA 適性ではない",
}
DECLARED_KEY_BY_JSON_KEY = {"surface_profile": "surfaces", "verification_profile": "verification"}
# Tables whose names are compared whole (the tests above and below); every other
# trait_tables template that names a viewpoint in its text is listed in NAME_MENTIONS.
WHOLE_NAME_TABLES = ("HEADINGS", "DECLARED_TEXTS", "DECLARED_ITEM_NAMES")
NAME_MENTIONS = {
    ("SENTENCES", "place_tests_only"): "verification_profile",
    ("SENTENCES", "work_not_observed"): "role_profile",
    ("SENTENCES", "work_scope_differs"): "role_profile",
    ("SENTENCES", "work_scope_later"): "role_profile",
    ("SECTION_TEXTS", "record_scope_paths"): "surface_profile",
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


def _detail_headings(table: dict[str, tuple[str, str]]) -> list[str]:
    return [
        f"### {table[json_key][0]}（{table[json_key][1]}、{suffix}）"
        for json_key, suffix in DETAIL_SUFFIXES.items()
    ]


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
    table = _names_table()
    for json_key, (plain, site) in table.items():
        assert f"### {_heading_text(plain, site)}\n" in text, (json_key, plain, site)
    for detail in _detail_headings(table):
        assert f"{detail}\n" in text, detail


def _section_lines(text: str, heading: str) -> list[str]:
    """The lines under one `## ` heading of a Markdown, up to the next `## ` or `# `."""
    assert f"\n{heading}\n" in text, heading
    body = text.split(f"\n{heading}\n", 1)[1]
    return re.split(r"\n#{1,2} ", body, maxsplit=1)[0].splitlines()


def _names_in_code(outputs: dict[str, str]) -> dict[str, object]:
    """Every place outside HEADINGS that prints a viewpoint name, as the code has it."""
    found: dict[str, object] = {}
    for report in ("actor", "repo", "project"):
        lines = _section_lines(outputs[report], "## 傾向")
        found[f"{report} ## 傾向"] = [
            line[2:].split(": ", 1)[0] for line in lines if line.startswith("- ")
        ]
        details = [
            line
            for line in _section_lines(outputs[report], "## 観測された数値")
            if line.startswith("### ")
        ]
        found[f"{report} ## 観測された数値"] = details[: len(DETAIL_SUFFIXES)]
    for json_key, key in DECLARED_KEY_BY_JSON_KEY.items():
        found[f"DECLARED_TEXTS[{key}]"] = DECLARED_TEXTS[key]
        found[f"DECLARED_ITEM_NAMES[{key}]"] = DECLARED_ITEM_NAMES[key]
    return found


def _names_from_table() -> dict[str, object]:
    """The same places, as the names table in docs/metrics-guide.md says they read."""
    table = _names_table()
    name = {json_key: _heading_text(plain, site) for json_key, (plain, site) in table.items()}
    expected: dict[str, object] = {}
    for report in ("actor", "repo", "project"):
        expected[f"{report} ## 傾向"] = [name["surface_profile"], name["change_rhythm"]]
        expected[f"{report} ## 観測された数値"] = _detail_headings(table)
    for json_key, key in DECLARED_KEY_BY_JSON_KEY.items():
        expected[f"DECLARED_TEXTS[{key}]"] = f"- {name[json_key]}: {{items}}"
        expected[f"DECLARED_ITEM_NAMES[{key}]"] = name[json_key]
    return expected


def test_tendency_detail_and_declared_names_follow_the_names_table(outputs) -> None:
    """0.9.1 M7: the names table binds more than HEADINGS.

    The tendency names (report_v2.py), the detailed-numbers headings
    (report_v2_observed.py) and DECLARED_TEXTS / DECLARED_ITEM_NAMES print the
    whole viewpoint names. Changing a name in the table and HEADINGS alone fails
    here with the table's value and the code's value side by side. Sentences that
    name a viewpoint inside their text are tied by the NAME_MENTIONS test below.
    """
    expected, found = _names_from_table(), _names_in_code(outputs)
    assert set(expected) == set(found), sorted(set(expected) ^ set(found))
    diffs = [
        (where, expected[where], found[where])
        for where in expected
        if expected[where] != found[where]
    ]
    assert not diffs, ("(where, names table, code)", diffs)


def _templates() -> dict[tuple[str, str], str]:
    """Every trait_tables text outside WHOLE_NAME_TABLES, keyed (constant, row)."""
    found: dict[tuple[str, str], str] = {}
    for constant in dir(trait_tables):
        value = getattr(trait_tables, constant)
        if not constant.isupper() or constant in WHOLE_NAME_TABLES:
            continue
        if isinstance(value, dict):
            found.update({(constant, str(k)): v for k, v in value.items() if isinstance(v, str)})
        elif isinstance(value, str):
            found[(constant, "")] = value
    return found


def test_sentences_that_name_a_viewpoint_follow_the_names_table() -> None:
    """0.9.1 M7 (review): sentences such as 「テストは「テストの付け方」で数えています」.

    Forward: each NAME_MENTIONS template carries the table's plain name for its
    viewpoint. Reverse: the templates that carry any plain name are exactly the
    NAME_MENTIONS keys, so a template that keeps an old name, or a new one that
    names a viewpoint, fails here with both values.
    """
    plain = {json_key: names[0] for json_key, names in _names_table().items()}
    templates = _templates()
    missing = [
        (where, plain[json_key], templates.get(where))
        for where, json_key in NAME_MENTIONS.items()
        if plain[json_key] not in (templates.get(where) or "")
    ]
    assert not missing, ("(template, names table, template text)", missing)
    naming = {where for where, text in templates.items() if any(n in text for n in plain.values())}
    assert naming == set(NAME_MENTIONS), (
        "(templates that name a viewpoint, NAME_MENTIONS)",
        sorted(naming),
        sorted(NAME_MENTIONS),
    )


@pytest.mark.parametrize("name", ["actor", "repo", "project"])
def test_a_tendency_row_names_its_viewpoint_once(outputs, name: str) -> None:
    """0.9.1 L16: 「- 変更のペース（変更リズム）: 変更のペース（変更リズム）が観測される」 read twice."""
    table = _names_table()
    plain = [table[key][0] for key in ("surface_profile", "change_rhythm")]
    rows = [
        line
        for heading in ("## 傾向", "## 傾向の確からしさ")
        for line in _section_lines(outputs[name], heading)
        if line.startswith("- ")
    ]
    repeated = [row for row in rows if any(row.count(word) > 1 for word in plain)]
    assert rows, name
    assert not repeated, (name, repeated)


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
