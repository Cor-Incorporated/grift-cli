"""Markdown reports must carry units and must not use grade vocabulary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown

from git_fixture import commit, init_repo

ROOT = Path(__file__).resolve().parents[1]


def _vocab():
    spec = importlib.util.spec_from_file_location(
        "check_forbidden_vocab",
        ROOT / "scripts" / "check_forbidden_vocab.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_markdown_has_units_and_no_forbidden_words(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one")
    report = analyze_repository(repo, empty_identity(), Lineage(), include_files=False)
    markdown = render_markdown(report)
    assert "commits" in markdown
    assert "definition version" in markdown
    assert report["provenance"]["analyzed_commit_sha"] in markdown
    found = _vocab().violations(markdown)
    assert found == [], found


def test_first_party_markdown_omits_upstream_sync_label(tmp_path: Path) -> None:
    """H-1: first-party reports must not narrate upstream_sync."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one")
    report = analyze_repository(repo, empty_identity(), Lineage(), include_files=False)
    markdown = render_markdown(report)
    assert "upstream_sync" not in markdown
    assert "inherited_upstream" not in markdown
    assert "unresolved" in markdown


def test_default_report_omits_local_path(tmp_path: Path) -> None:
    """H-3: absolute path is opt-in."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one")
    report = analyze_repository(repo, empty_identity(), Lineage(), include_files=False)
    assert "path" not in report["repository"]
    assert report["repository"]["name"] == "repo"
    with_path = analyze_repository(
        repo, empty_identity(), Lineage(), include_files=False, include_local_path=True
    )
    assert with_path["repository"]["path"] == str(repo.resolve())
