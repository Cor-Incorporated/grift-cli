"""v0.9.1: which commits enter the window when HEAD is made on an east-of-UTC morning.

0.9.0 (#90) takes the observation date without --as-of from HEAD's UTC day, and
cuts the range and the 180-day rhythm window on each commit's UTC day.
`tests/test_v090_observation_date.py` pins a west-of-UTC evening HEAD and
`tests/test_v090_scenario_window_utc.py` pins the observation date and window
edges. This pins the commits on the other side (M2): on a +09:00 morning the
local day is one day ahead of the UTC day, so HEAD's own local day is after the
observation date and still in the window, and a commit made on the local first
day of the window is the day before it in UTC and outside it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from datetime import date, timedelta
from pathlib import Path

from git_fixture import git, init_repo

from tep_cli.__main__ import main

# HEAD is 2026-08-29 08:00 at +09:00, which is 2026-08-28 23:00 UTC.
OBSERVATION = date(2026, 8, 28)
START = OBSERVATION - timedelta(days=180)
MIDDLE = 20


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


def _commit(repo: Path, when: str, index: int) -> None:
    path = repo / "src" / "api" / "svc.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.read_text(encoding="utf-8") + f"# {index}\n" if path.exists() else "# 0\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_COMMITTER_DATE": when,
    }
    git(repo, "add", "src/api/svc.py", env=env)
    git(repo, "commit", "-q", "-m", f"feat: svc {index}", env=env)


def _east_morning(day: date, hour: int) -> str:
    return f"{day.isoformat()}T{hour:02d}:00:00+09:00"


def test_an_east_morning_head_keeps_its_local_day_and_drops_the_local_first_day(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "east")
    one_day = timedelta(days=1)
    _commit(repo, _east_morning(START, 8), 0)  # START - 1 in UTC: before the window
    _commit(repo, _east_morning(START + one_day, 8), 1)  # START in UTC: the first day in it
    for index in range(MIDDLE):
        middle = START + timedelta(days=30 + index)
        _commit(repo, f"{middle.isoformat()}T12:00:00+00:00", 2 + index)
    _commit(repo, _east_morning(OBSERVATION + one_day, 7), 2 + MIDDLE)
    _commit(repo, _east_morning(OBSERVATION + one_day, 8), 3 + MIDDLE)  # HEAD
    report = json.loads(_cli(["repo", str(repo), "--format", "json"]))
    provenance, rhythm = report["provenance"], report["change_rhythm"]
    facts = {
        "observation_date": provenance["observation_date"],
        "git_window": [provenance["git_window"]["start"], provenance["git_window"]["end"]],
        "counted": report["surface_profile"]["sample_size"],
        "in_window": rhythm["window_population"],
        "before_window": rhythm["history_outside_window_commit_count"]["value"],
        "window_days": rhythm["active_days_180d"]["value"],
    }
    assert provenance["window_basis"] == "legacy_head_date"
    assert facts == {
        "observation_date": OBSERVATION.isoformat(),
        "git_window": [START.isoformat(), OBSERVATION.isoformat()],
        "counted": MIDDLE + 4,  # every commit, HEAD's local day after the date included
        "in_window": MIDDLE + 3,  # all but the one made on the window's local first day
        "before_window": 1,
        "window_days": MIDDLE + 2,  # START, the middle days and the observation date, in UTC
    }, facts
