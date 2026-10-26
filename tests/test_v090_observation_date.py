"""v0.9.0: without --as-of, the observation date and the counted range use one clock.

`resolve_observation` took the HEAD commit's date in its author's time zone
(`%ad --date=short`), while the range is cut by each commit's UTC date. A HEAD
commit made in the evening west of UTC falls on the next UTC day, so it dropped
out of its own report: one change fewer than the person made, and a range that
ends before the last change.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path

from git_fixture import git, init_repo

from tep_cli.__main__ import main


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


def test_a_head_committed_west_of_utc_stays_inside_its_own_report(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "west")
    for index in range(24):
        _commit(repo, f"2026-08-{index + 1:02d}T12:00:00+00:00", index)
    _commit(repo, "2026-08-28T20:00:00-08:00", 24)  # HEAD: 2026-08-29 04:00 UTC
    report = json.loads(_cli(["repo", str(repo), "--format", "json"]))
    provenance = report["provenance"]
    assert provenance["window_basis"] == "legacy_head_date"
    facts = {
        "observation_date": provenance["observation_date"],
        "counted": report["surface_profile"]["sample_size"],
        "made": 25,
    }
    assert facts["counted"] == facts["made"], facts
    assert facts["observation_date"] == "2026-08-29", facts
