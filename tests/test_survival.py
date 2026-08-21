"""Survival scan: repo-level, no author emails."""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo


def test_survival_disabled_by_default(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one", filename="app.py")
    report = analyze_repository(repo, empty_identity(), Lineage())
    assert report["survival"]["kind"] == "not_observed"
    assert report["survival"]["reason"] == "survival_scan_disabled"


def test_survival_enabled_has_index_and_no_emails(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="a@example.com",
        date="2026-01-02",
        message="one",
        filename="app.py",
        content="print(1)\nprint(2)\n",
    )
    report = analyze_repository(repo, empty_identity(), Lineage(), survival=True)
    assert report["survival"]["kind"] == "observed"
    assert 0 <= report["survival"]["survival_index"] <= 1
    assert report["survival"]["tau_days"] == 180
    blob = str(report["survival"])
    assert "@example.com" not in blob
