"""Test co-change falsification tests."""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import load_identity
from tep_core.lineage import Lineage

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


def test_cochange_same_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    commit(
        repo,
        email="alice@acme.test",
        date="2026-01-02",
        message="feat+test",
        filename="src/app.py",
        content="x=1\n",
    )
    commit(
        repo,
        email="alice@acme.test",
        date="2026-01-03",
        message="more+test",
        filename="src/app.py",
        content="x=2\n",
    )
    # same commit: also add test file by writing both in one commit via second file after first
    # The fixture writes one file per commit. Make an explicit dual-file commit:
    (repo / "src" / "app.py").write_text("x=3\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    from git_fixture import git
    import os

    git(repo, "add", "src/app.py", "tests/test_app.py")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Author",
        "GIT_AUTHOR_EMAIL": "alice@acme.test",
        "GIT_AUTHOR_DATE": "2026-01-04T12:00:00",
        "GIT_COMMITTER_NAME": "Author",
        "GIT_COMMITTER_EMAIL": "alice@acme.test",
        "GIT_COMMITTER_DATE": "2026-01-04T12:00:00",
    }
    git(repo, "commit", "-m", "together", env=env)
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    all_time = report["test_cochange"]["all_time"]
    assert all_time["kind"] == "observed"
    assert all_time["population"] >= 1
    assert all_time["cochanged"] >= 1
    assert all_time["value"] > 0
    assert all_time["narrate_rate"] is False  # n < 20


def test_cochange_not_observed_without_tests(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="alice@acme.test", date="2026-01-02", message="prod", filename="app.py")
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    assert report["test_cochange"]["kind"] == "not_observed"
    assert report["test_cochange"]["reason"] == "no_test_framework_or_directory"


def test_cochange_observed_zero_when_tests_exist_but_uncoupled(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    commit(repo, email="alice@acme.test", date="2026-01-02", message="prod", filename="app.py")
    commit(
        repo,
        email="alice@acme.test",
        date="2026-01-03",
        message="only-test",
        filename="tests/test_app.py",
        content="def test_ok():\n    pass\n",
    )
    report = analyze_repository(repo, load_identity(_ident(tmp_path)), Lineage())
    all_time = report["test_cochange"]["all_time"]
    assert all_time["kind"] == "observed"
    assert all_time["value"] == 0.0
    assert all_time["population"] == 1
    assert all_time["test_only"] == 1
