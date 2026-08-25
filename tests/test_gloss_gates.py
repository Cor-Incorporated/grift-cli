"""v0.5.9 review gates (提唱者 2026-08-25):
(1) gloss unit alignment — every glossed line's unit must appear in the gloss
(2) gloss vocabulary gate — no normative words (良い/悪い/優れ/劣る/健全/理想/...)
(3) report.json immutability — glosses live in markdown only
"""

from __future__ import annotations

import json
from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.report import (
    _ORIGIN_GLOSS,
    render_markdown,
)

from git_fixture import commit, init_repo

ROOT = Path(__file__).resolve().parents[1]


def _repo_report(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "d"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
    for index in range(24):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
        if index % 2 == 0:
            commit(
                repo,
                email="a@example.com",
                date="2026-01-05",
                message=f"test: {index}",
                filename="tests/t.py",
            )
    return analyze_repository(repo, empty_identity(), Lineage(), scope="repo")


# --- (1) unit alignment ----------------------------------------------------

UNIT_TOKENS = (
    "commits",
    "days",
    "ratio",
    "actors",
    "class",
    "boolean",
    "tags",
    "dirs",
    "manifests",
    "markers",
    "date",
    "month-range",
    "releases",
)
# lines whose VALUE unit must be echoed by the gloss: map line-prefix → required token(s)
_UNIT_EXPECTATIONS = [
    # origin classes are all "commits"
    ("tenant_unique:", "コミット"),
    ("unresolved:", "コミット"),
    ("bot:", "コミット"),
    ("generated_or_vendor:", "コミット"),
    ("ambiguous_origin:", "コミット"),
    ("tenant_derivative:", "コミット"),
    ("external_upstream_contribution:", "コミット"),
    ("template_inherited:", "コミット"),
    # activity
    ("tenant commits:", "コミット"),
    ("active days:", "日数"),
    ("commits per active day:", "密度"),
    ("active days (13 weeks):", "日数"),
]


def test_1_origin_glosses_carry_commit_unit() -> None:
    for name, gloss in _ORIGIN_GLOSS.items():
        if name in ("tenant_merge_or_sync", "upstream_sync"):
            continue  # flow-path glosses; line unit still commits but gloss is route
        assert "コミット" in gloss, f"{name}: gloss lacks コミット unit: {gloss}"
        assert "commits" in gloss or "PR" in gloss or "upstream" in gloss, (
            f"{name}: gloss lacks en unit"
        )


def test_1_every_glossed_line_echoes_its_unit(tmp_path: Path) -> None:
    report = _repo_report(tmp_path)
    markdown = render_markdown(report)
    for line in markdown.splitlines():
        if "—" not in line or not line.startswith("- "):
            continue
        gloss = line.split("—", 1)[1]
        for prefix, token in _UNIT_EXPECTATIONS:
            if prefix in line.split("—")[0]:
                assert token in gloss, f"unit mismatch: {line.strip()[:80]}"


# --- (2) gloss vocabulary gate -----------------------------------------------

NORMATIVE = [
    "良い",
    "悪い",
    "優れ",
    "劣る",
    "健全",
    "理想",
    "優秀",
    "優劣",
    "質が高",
    "質が低",
    "excellent",
    "superior",
    "inferior",
    "healthy",
    "ideal",
    "good,",
    "bad,",
]


def test_2_glosses_carry_no_normative_words(tmp_path: Path) -> None:
    report = _repo_report(tmp_path)
    markdown = render_markdown(report)
    for line in markdown.splitlines():
        if "—" not in line:
            continue
        gloss = line.split("—", 1)[1]
        for word in NORMATIVE:
            assert word not in gloss, f"normative word {word!r} in gloss: {gloss.strip()[:60]}"


def test_2_gloss_dictionary_clean() -> None:
    for name, gloss in _ORIGIN_GLOSS.items():
        for word in NORMATIVE:
            assert word not in gloss, f"{name}: {word!r} in {gloss!r}"


# --- (3) report.json immutability --------------------------------------------


def test_3_report_json_has_no_gloss(tmp_path: Path) -> None:
    report = _repo_report(tmp_path)
    text = json.dumps(report, ensure_ascii=False)
    for marker in ("—", "何を測るか", "このrepoのかたち", "gloss"):
        assert marker not in text, f"report.json carries markdown gloss marker {marker!r}"
    # schema untouched
    assert report["schema_version"] == "report-v1"


def test_3_verify_unaffected_by_glosses(tmp_path: Path) -> None:
    """Glosses are markdown-only decoration: verify recomputes the report dict
    and must return VERIFIED even after rendering the markdown."""
    import copy
    import json as _json

    from tep_core.verify import VERIFIED, verify_report

    report = _repo_report(tmp_path)
    before = copy.deepcopy(report)
    render_markdown(report)
    assert report == before, "render_markdown must not mutate the report dict"
    path = tmp_path / "report.json"
    path.write_text(_json.dumps(report), encoding="utf-8")
    outcome = verify_report(path, tmp_path / "repo")
    assert outcome.status == VERIFIED


def test_4_shared_block_stays_gloss_free(tmp_path: Path) -> None:
    """(4) spec: Shared block carries no glosses (paste-friendly compactness)."""
    from tep_core.report import shared_block as _sb

    report = _repo_report(tmp_path)
    for line in _sb(report):
        assert "—" not in line, f"shared block line carries a gloss: {line}"


def test_g1_no_standalone_paren_note_lines(tmp_path: Path) -> None:
    """G-1: section-header parenthetical notes are forbidden — glosses live
    on value lines only (Test frameworks used to double-print the note)."""
    report = _repo_report(tmp_path)
    markdown = render_markdown(report)
    for line in markdown.splitlines():
        stripped = line.strip()
        assert not (stripped.startswith("（") and stripped.endswith("）")), (
            f"standalone paren note line present: {stripped[:50]}"
        )


def test_g1_no_immediate_duplicate_gloss_lines(tmp_path: Path) -> None:
    """G-1: a repo with detected frameworks must not print the same gloss
    twice in a row (header note + value line duplication pattern)."""
    report = _repo_report(tmp_path)
    markdown = render_markdown(report)
    lines = markdown.splitlines()
    for i in range(len(lines) - 1):
        if "—" in lines[i] and "—" in lines[i + 1]:
            g1 = lines[i].split("—", 1)[1].strip()
            g2 = lines[i + 1].split("—", 1)[1].strip()
            if g1 and g1 == g2:
                raise AssertionError(f"consecutive duplicate glosses: {g1[:50]}")
