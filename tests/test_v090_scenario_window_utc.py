"""v0.9.0: the scenario runner expects the observation window in UTC days.

0.9.0 (#90) takes the observation date without --as-of from HEAD's UTC day.
The runner still built its expected legacy window from the author's local day
(`%as`), so R01's fixed target (a650ffa, authored 00:51 JST = 15:51 UTC the day
before) failed `window-start` / `window-end` by one day when the private
registry was regenerated for the release.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tep_core.analyze_v2 import _git_window, resolve_observation
from tep_core.gitutil import read_commits

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v060_scenario_matrix.py"
_SPEC = importlib.util.spec_from_file_location("v060_scenario_matrix_window", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
matrix = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = matrix
_SPEC.loader.exec_module(matrix)


def _one_commit(path: Path, authored: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "A",
        "GIT_AUTHOR_EMAIL": "a@example.com",
        "GIT_AUTHOR_DATE": authored,
        "GIT_COMMITTER_NAME": "A",
        "GIT_COMMITTER_EMAIL": "a@example.com",
        "GIT_COMMITTER_DATE": authored,
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "a.txt"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "a"], check=True, env=env)
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return head.stdout.strip()


@pytest.mark.parametrize(
    ("authored", "utc_day"),
    [
        ("2026-08-30T00:51:57+09:00", "2026-08-29"),  # R01: east of UTC, early morning
        ("2026-08-29T20:00:00-07:00", "2026-08-30"),  # west of UTC, evening
        ("2026-08-29T12:00:00+00:00", "2026-08-29"),  # same day everywhere
    ],
)
def test_expected_window_is_the_window_grift_writes(
    tmp_path: Path, authored: str, utc_day: str
) -> None:
    repo = tmp_path / "repo"
    oid = _one_commit(repo, authored)
    observation_date, _basis = resolve_observation(read_commits(repo), None)
    written = _git_window(observation_date)
    expected = matrix._expected_window(repo, oid)
    facts = {
        "authored": authored,
        "runner_expects": expected,
        "grift_writes": {key: written[key] for key in ("start", "end", "days")},
    }
    assert expected["end"] == utc_day, facts
    assert expected == facts["grift_writes"], facts
