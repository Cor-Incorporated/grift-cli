"""H-5: population < 20 must hide ratio AND reference position.

Violation strings are frozen from the openai/swarm dogfood report
(2026-08-22, --scope repo). Swarm is NOT a corpus pin (corpus protocol:
do not add a failing repo to pins just to make a test).
2/9 = 0.2222 produced decile 4 (co-change) and decile 9 (corrective).
"""

from __future__ import annotations

import os
from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.reference import interpret_metric
from tep_core.report import render_markdown

from git_fixture import git, init_repo

# Live markdown lines observed on openai/swarm (production population 9).
# After H-5 these strings must not be emitted.
SWARM_VIOLATING_LINES = (
    "all-time 0.2222 ratio (population 9 commits; rate narrative omitted: population below 20)",
    "co-change 0.2222 (repo scope) — reference corpus v2026.09 (n=33) decile 4",
    "0.2222 ratio (population 9 commits; rate narrative omitted: population below 20)",
    "corrective rework 0.2222 (repo scope) — reference corpus v2026.09 (n=42) decile 9",
)


def _swarm_shaped_report() -> dict:
    """Same numbers as the swarm dogfood row: 2 of 9 → 0.2222, decile 4 / 9."""
    cochange = {
        "kind": "observed",
        "all_time": {
            "kind": "observed",
            "value": 0.2222,
            "unit": "ratio",
            "population": 9,
            "cochanged": 2,
            "narrate_rate": False,
        },
    }
    corr = {
        "kind": "observed",
        "value": 0.2222,
        "unit": "ratio",
        "corrective_commits": 2,
        "population": 9,
        "narrate_rate": False,
        "evidence_claim": False,
    }
    rework = {
        "kind": "observed",
        "definition_version": "rework-v1.1-2026-08-22",
        "window_days": 21,
        "evidence_claim": None,
        "corrective_rework_rate": corr,
        "path_retouch_rate": {
            "kind": "observed",
            "value": 0.3333,
            "unit": "ratio",
            "retouch_commits": 3,
            "population": 9,
            "evidence_claim": False,
        },
    }
    return {
        "provenance": {
            "tool_name": "grift",
            "method_name": "TEP",
            "tool_version": "0.5.0",
            "definition_version": "tep-v0.5.0-2026-08-22",
            "analyzed_commit_sha": "deadbeef",
            "analyzed_at": "2026-08-22T00:00:00Z",
        },
        "repository": {"name": "swarm", "remote": "https://github.com/openai/swarm.git"},
        "lineage": {"is_fork": False, "parent": None, "has_upstream_lineage": False},
        "identity": {"pending_attribution": True, "actor_count": 0},
        "origin": {"unresolved": {"kind": "observed", "value": 29, "unit": "commits"}},
        "activity": {
            "tenant_commits": {"kind": "observed", "value": 0, "unit": "commits"},
            "active_days": {"kind": "observed", "value": 0, "unit": "days"},
            "commits_per_active_day": {"kind": "not_observed", "reason": "no_tenant_commits"},
            "commits_per_active_day_median": {
                "kind": "not_observed",
                "reason": "no_tenant_commits",
            },
            "active_days_13w": {"kind": "not_observed", "reason": "no_tenant_commits"},
        },
        "core_activity_period": {"kind": "not_observed", "reason": "no_tenant_commits"},
        "test_frameworks": {
            "kind": "observed",
            "value": True,
            "names": ["pytest"],
            "unit": "boolean",
        },
        "test_cochange": cochange,
        "rework": rework,
        "survival": {"kind": "not_observed", "reason": "survival_scan_disabled"},
        "interpretation": {
            "test_cochange": interpret_metric(
                report_scope="repo", metric_id="test_cochange", observation=cochange
            ),
            "corrective_rework": interpret_metric(
                report_scope="repo", metric_id="corrective_rework", observation=corr
            ),
        },
    }


def test_swarm_violation_strings_are_the_locked_bug_signature() -> None:
    blob = "\n".join(SWARM_VIOLATING_LINES)
    assert "0.2222 ratio" in blob
    assert "decile 4" in blob
    assert "decile 9" in blob
    assert "rate narrative omitted: population below 20" in blob


def test_h5_hides_ratio_and_decile_for_swarm_shaped_report() -> None:
    markdown = render_markdown(_swarm_shaped_report())
    for line in SWARM_VIOLATING_LINES:
        assert line not in markdown, line
    assert "0.2222" not in markdown
    assert "decile" not in markdown
    assert "insufficient_population" in markdown
    assert "9コミット中2件" in markdown
    interp = _swarm_shaped_report()["interpretation"]
    assert interp["test_cochange"] == {
        "kind": "not_observed",
        "reason": "insufficient_population",
    }
    assert interp["corrective_rework"] == {
        "kind": "not_observed",
        "reason": "insufficient_population",
    }


def test_h5_live_repo_scope_small_population(tmp_path: Path) -> None:
    """Nine production commits, two with tests — swarm's 2/9 shape, not a corpus pin."""
    repo = init_repo(tmp_path / "swarm-shape")
    (repo / "tests").mkdir()
    (repo / "src").mkdir()
    for i in range(9):
        (repo / "src" / "app.py").write_text(f"x={i}\n", encoding="utf-8")
        files = ["src/app.py"]
        if i < 2:
            (repo / "tests" / "test_app.py").write_text(
                f"def test_{i}():\n    assert True\n", encoding="utf-8"
            )
            files.append("tests/test_app.py")
        git(repo, "add", *files)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Author",
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_AUTHOR_DATE": f"2026-01-{i + 2:02d}T12:00:00",
            "GIT_COMMITTER_NAME": "Author",
            "GIT_COMMITTER_EMAIL": "a@example.com",
            "GIT_COMMITTER_DATE": f"2026-01-{i + 2:02d}T12:00:00",
        }
        git(repo, "commit", "-m", f"feat: step {i}", env=env)
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    all_time = report["test_cochange"]["all_time"]
    assert all_time["population"] == 9
    assert all_time["cochanged"] == 2
    assert all_time["value"] == 0.2222
    assert all_time["narrate_rate"] is False
    markdown = render_markdown(report)
    for line in SWARM_VIOLATING_LINES:
        assert line not in markdown, line
    assert "0.2222" not in markdown
    assert "decile" not in markdown
    assert "insufficient_population" in markdown
    assert "9コミット中2件" in markdown
    assert report["interpretation"]["test_cochange"]["reason"] == "insufficient_population"
    assert report["interpretation"]["corrective_rework"]["reason"] == "insufficient_population"
    assert report["provenance"]["tool_name"] == "grift"
    assert report["provenance"]["method_name"] == "TEP"
