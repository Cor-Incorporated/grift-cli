"""F-P10-1: the parity recipe in docs/export-schema.md must be executable verbatim.

This test extracts the backticked Python expressions from the recipe section
and runs them against real export rows. If the doc drifts from the
implementation (or the recipe is removed), this test fails. The proposer's own
first recompute forgot the cochange-null filter and got 444/1537 instead of
73/274 — an undocumented recipe is a misimplementation waiting to happen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.export import build_export, write_export
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "export-schema.md"

_SECTION_RE = re.compile(r"### パリティ検算レシピ.*?(?=\n## )", re.DOTALL)
_EXPR_RE = re.compile(r"`([^`\n]+`)")


def _recipe_exprs() -> dict[str, str]:
    text = DOC.read_text(encoding="utf-8")
    match = _SECTION_RE.search(text)
    assert match, "recipe section '### パリティ検算レシピ' is missing from export-schema.md"
    section = match.group(0)
    named: dict[str, str] = {}
    for line in section.splitlines():
        label_match = re.match(r"- ([^:：]+)[：:]\s*`([^`]+)`", line.strip())
        if label_match and label_match.group(2).startswith(("sum(", "r[")):
            named[label_match.group(1)] = label_match.group(2)
    required = {
        "各クラス c の行数",
        "母集団フィルタ（tenant）",
        "cochanged フィルタ（tenant）",
        "母集団フィルタ（repo）",
        "cochanged フィルタ（repo）",
    }
    missing = required - set(named)
    assert not missing, f"recipe lost labeled expressions: {sorted(missing)}"
    return named


def _fixture(tmp_path: Path) -> tuple[dict, list[dict]]:
    repo = init_repo(tmp_path / "repo")
    repo.joinpath("pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    tests_dir.joinpath("test_smoke.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    for index in range(25):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-02",
            message=f"feat: {index}",
            filename="app.py",
        )
        if index % 2 == 0:
            commit(
                repo,
                email="a@example.com",
                date="2026-01-02",
                message=f"test: {index}",
                filename="tests/test_app.py",
            )
    out = tmp_path / "export"
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    export = build_export(repo, empty_identity(), Lineage(), scope="repo")
    write_export(export, out)
    rows = [
        json.loads(line)
        for line in (out / "commits.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    return report, rows


def test_recipe_verbatim_on_repo_scope(tmp_path: Path) -> None:
    report, rows = _fixture(tmp_path)
    exprs = _recipe_exprs()
    population = [
        r
        for r in rows
        if eval(exprs["母集団フィルタ（repo）"], {}, {"r": r})  # noqa: S307
    ]
    cochanged = [
        r
        for r in rows
        if eval(exprs["cochanged フィルタ（repo）"], {}, {"r": r})  # noqa: S307
    ]
    all_time = report["test_cochange"]["all_time"]
    assert len(population) == all_time["population"]
    assert len(cochanged) == all_time["cochanged"]


def test_recipe_origin_count_expression(tmp_path: Path) -> None:
    _report, rows = _fixture(tmp_path)
    exprs = _recipe_exprs()
    count_expr = next(v for k, v in exprs.items() if v.startswith("sum("))
    classes = {r["origin"] for r in rows}
    for klass in classes:
        counted = eval(count_expr, {"rows": rows, "c": klass})  # noqa: S307
        assert counted == sum(1 for r in rows if r["origin"] == klass)


def test_recipe_requires_both_scope_filters() -> None:
    exprs = _recipe_exprs()
    tenant_filters = [exprs["母集団フィルタ（tenant）"], exprs["cochanged フィルタ（tenant）"]]
    repo_filters = [exprs["母集団フィルタ（repo）"], exprs["cochanged フィルタ（repo）"]]
    assert all('"tenant_unique"' in v for v in tenant_filters)
    assert all('"bot"' in v and '"is_merge"' in v for v in repo_filters)
    assert "is not None" in exprs["母集団フィルタ（tenant）"], (
        "the cochange-null filter is the documented safeguard against the "
        "444/1537 misimplementation; removing it must fail this test"
    )
    assert "is not None" in exprs["母集団フィルタ（repo）"]
    assert exprs["cochanged フィルタ（tenant）"].endswith("is True")
    assert exprs["cochanged フィルタ（repo）"].endswith("is True")
