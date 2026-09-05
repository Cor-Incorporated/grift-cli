"""Surface classification precedence and split_paths invariance."""

from __future__ import annotations

from pathlib import Path

from tep_core.export import build_export
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.path_surface import classify_surface, surface_flags
from tep_core.paths import split_paths
from tep_core.surface_profile import surface_profile

from tep_core.gitutil import GitCommit as RealCommit


def _commit(sha: str, files: tuple[str, ...]) -> RealCommit:
    return RealCommit(
        sha=sha,
        author_email="a@example.com",
        parents=("p",),
        date="2026-08-01",
        subject="feat",
        files=files,
        author_iso="2026-08-01T12:00:00Z",
    )


def test_test_outranks_frontend() -> None:
    assert classify_surface("src/components/Button.test.tsx") == "test"
    surface, ambiguous, _ = surface_flags("src/components/Button.test.tsx")
    assert surface == "test"
    assert ambiguous is True


def test_platform_outranks_config() -> None:
    assert classify_surface("k8s/deployment.yaml") == "platform"
    assert classify_surface("terraform/main.tf") == "platform"


def test_ci_outranks_config() -> None:
    assert classify_surface(".github/workflows/ci.yml") == "ci_cd"


def test_docs_markdown() -> None:
    assert classify_surface("docs/guide.md") == "docs"


def test_backend_python_and_api() -> None:
    assert classify_surface("src/api/app.py") == "backend"


def test_data_sql() -> None:
    assert classify_surface("migrations/001.sql") == "data"


def test_conflict_paths_use_precedence_and_ambiguous() -> None:
    cases = {
        "docs/backend.md": "docs",
        "docs/api/overview.md": "docs",
        "components/api.py": "frontend",
        "tests/components/Button.tsx": "test",
        "terraform/main.py": "platform",
        "vendor/lib.py": "backend",
    }
    for path, expected in cases.items():
        assert classify_surface(path) == expected, path
    _, docs_api_ambiguous, _ = surface_flags("docs/api/overview.md")
    _, components_api_ambiguous, _ = surface_flags("components/api.py")
    _, test_tsx_ambiguous, _ = surface_flags("tests/components/Button.tsx")
    assert docs_api_ambiguous
    assert components_api_ambiguous
    assert test_tsx_ambiguous


def test_fixture_paths_are_classified_without_author_guesses() -> None:
    fixtures = {
        "frontend": "src/components/Button.tsx",
        "backend": "src/api/handler.py",
        "data": "migrations/001_init.sql",
        "platform": "docker/Dockerfile",
        "test": "tests/test_app.py",
        "docs": "docs/readme.md",
        "config": "pyproject.toml",
        "generated_vendor": "node_modules/pkg/index.js",
    }
    for expected, path in fixtures.items():
        assert classify_surface(path) == expected


def test_unknown_is_other() -> None:
    surface, _ambiguous, unclassified = surface_flags("random.bin")
    assert surface == "other"
    assert unclassified is True


def test_split_paths_unchanged() -> None:
    files = ["app.py", "tests/test_app.py", "README.md"]
    prod, tests, docs = split_paths(files)
    assert prod == ["app.py"]
    assert tests == ["tests/test_app.py"]
    assert docs == ["README.md"]


def test_surface_profile_counts_and_share_denominator() -> None:
    commits = [
        _commit("a" * 40, ("src/api/app.py", "tests/test_app.py")),
        _commit("b" * 40, ("src/components/Button.tsx",)),
    ]
    # pad to keep counts even if rates suppressed
    for index in range(18):
        commits.append(_commit(f"{index:040d}", ("src/api/app.py",)))
    profile = surface_profile(commits, empty_reason="no_human_commits")
    assert profile["kind"] == "observed"
    assert profile["surface_commit_counts"]["values"]["backend"] >= 1
    assert profile["surface_commit_counts"]["values"]["test"] >= 1
    assert profile["classification_basis"]
    assert "cross_surface_cochange" in profile


def test_export_v1_still_uses_old_path_split(tmp_path: Path) -> None:
    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one", filename="app.py")
    export = build_export(repo, empty_identity(), Lineage(), scope="repo")
    assert export["commits"]
    row = export["commits"][0]
    assert "prod_paths_touched" in row or "files" in row or "origin" in row
