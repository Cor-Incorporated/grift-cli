"""Scope tenant vs repo must not be mixed."""

from __future__ import annotations

from pathlib import Path

import pytest

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity, load_identity
from tep_core.lineage import Lineage
from tep_core.scope import ScopeMismatchError, require_same_scope

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


def test_repo_scope_includes_unresolved_humans(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    commit(repo, email="alice@acme.test", date="2026-01-02", message="feat", filename="app.py")
    commit(
        repo,
        email="outsider@example.com",
        date="2026-01-03",
        message="feat+test",
        filename="app.py",
    )
    commit(
        repo,
        email="outsider@example.com",
        date="2026-01-03",
        message="feat+test",
        filename="tests/test_app.py",
        content="def test_ok():\n    pass\n",
    )
    ident = load_identity(_ident(tmp_path))
    tenant = analyze_repository(repo, ident, Lineage(), scope="tenant")
    repo_scope = analyze_repository(repo, ident, Lineage(), scope="repo")
    assert tenant["provenance"]["analysis_scope"] == "tenant"
    assert repo_scope["provenance"]["analysis_scope"] == "repo"
    t_pop = tenant["test_cochange"]["all_time"]["population"]
    r_pop = repo_scope["test_cochange"]["all_time"]["population"]
    assert r_pop > t_pop


def test_repo_scope_works_without_identity(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    commit(repo, email="a@example.com", date="2026-01-02", message="feat", filename="app.py")
    commit(
        repo,
        email="a@example.com",
        date="2026-01-03",
        message="together",
        filename="tests/test_app.py",
        content="def test_ok():\n    pass\n",
    )
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    assert report["test_cochange"]["kind"] == "observed"
    assert report["test_cochange"]["analysis_scope"] == "repo"


def test_tenant_interpretation_skips_reference(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="feat", filename="app.py")
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="tenant")
    assert report["interpretation"]["test_cochange"]["reason"] == "scope_is_tenant"


def test_scope_mismatch_linter() -> None:
    require_same_scope("repo", "repo")
    with pytest.raises(ScopeMismatchError):
        require_same_scope("tenant", "repo")
