"""Git log must not crash on non-UTF-8 commit bytes (WP1b-2 / A-curl)."""

from __future__ import annotations

import os
from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.gitutil import read_commits
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage

from git_fixture import git, init_repo


def test_latin1_commit_subject_does_not_raise(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("x\n", encoding="utf-8")
    git(repo, "add", "file.txt")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Author",
        "GIT_AUTHOR_EMAIL": "a@example.com",
        "GIT_AUTHOR_DATE": "2026-01-02T12:00:00",
        "GIT_COMMITTER_NAME": "Author",
        "GIT_COMMITTER_EMAIL": "a@example.com",
        "GIT_COMMITTER_DATE": "2026-01-02T12:00:00",
        "LC_ALL": "C",
    }
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), "commit", "-F", "-"],
        input=b"caf\xe9\n",
        check=True,
        capture_output=True,
        env=env,
    )
    commits = read_commits(repo)
    assert len(commits) == 1
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    assert report["provenance"]["analyzed_commit_sha"]
    assert "\ufffd" in commits[0].subject or "caf" in commits[0].subject.lower()
