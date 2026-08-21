"""Rework falsification: H-4 corrective vs path retouch."""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import load_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown

from git_fixture import commit, init_repo


def _ident(tmp_path: Path) -> Path:
    path = tmp_path / "id.toml"
    path.write_text(
        """
schema_version = "identity-v1"
[[actors]]
canonical_id = "alice"
emails = ["alice@acme.test"]
attribution_state = "verified"
""",
        encoding="utf-8",
    )
    return path


def test_burst_polish_is_path_retouch_not_corrective(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo, email="alice@acme.test", date="2026-01-02", message="feat: start", filename="app.py"
    )
    commit(
        repo, email="alice@acme.test", date="2026-01-10", message="feat: polish", filename="app.py"
    )
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    touch = report["rework"]["path_retouch_rate"]
    corr = report["rework"]["corrective_rework_rate"]
    assert touch["retouch_commits"] == 1
    assert touch["value"] == 0.5
    assert touch["evidence_claim"] is False
    assert corr["corrective_commits"] == 0
    assert corr["value"] == 0.0
    assert corr["evidence_claim"] is False
    assert report["rework"]["evidence_claim"] is None


def test_fix_on_recent_path_is_corrective(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo, email="alice@acme.test", date="2026-01-02", message="feat: start", filename="app.py"
    )
    commit(
        repo, email="alice@acme.test", date="2026-01-10", message="fix: crash", filename="app.py"
    )
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    corr = report["rework"]["corrective_rework_rate"]
    assert corr["corrective_commits"] == 1
    assert corr["population"] == 2
    assert corr["value"] == 0.5
    markdown = render_markdown(report)
    assert "not an evidence claim" in markdown
    assert "subject-convention dependent" in markdown
    assert "not a bug count" in markdown


def test_fix_outside_window_is_not_corrective_rework(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo, email="alice@acme.test", date="2026-01-02", message="feat: start", filename="app.py"
    )
    commit(
        repo, email="alice@acme.test", date="2026-03-01", message="fix: crash", filename="app.py"
    )
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    assert report["rework"]["path_retouch_rate"]["retouch_commits"] == 0
    assert report["rework"]["corrective_rework_rate"]["corrective_commits"] == 0


def test_line_rework_deferred(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="alice@acme.test", date="2026-01-02", message="feat", filename="app.py")
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    assert report["rework"]["line_rework"]["kind"] == "not_observed"
    assert report["rework"]["line_rework"]["reason"] == "deferred_to_v0.6"
