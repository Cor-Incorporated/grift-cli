"""W2 — attribute a dependency *introduction* to the person who made it.

Knowing a repository declares a library says nothing about who chose it. The
manifest is a property of the repository; the decision is a property of a
commit, and therefore of an author. `introduced` is the set of names present in
a commit's manifest and absent from its first parent's.

Lock files are excluded upstream (`dependency_manifest`), so a transitive bump
never registers as a choice.

An unreadable manifest is skipped and counted, never treated as "declared
nothing": under norms §1 a failure to read must not become an observation of
absence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


from tep_core.experience_collect import collect_dependency_introductions


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "dep"
    repo.mkdir()
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "A",
        "GIT_AUTHOR_EMAIL": "a@example.test",
        "GIT_COMMITTER_NAME": "A",
        "GIT_COMMITTER_EMAIL": "a@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)

    def commit(manifest: str, message: str) -> str:
        (repo / "package.json").write_text(manifest, encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", message)
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "-q")
    first = commit('{"dependencies": {"express": "^4"}}', "feat: seed")
    second = commit('{"dependencies": {"express": "^4", "h2": "^1"}}', "feat: add h2")
    third = commit('{"dependencies": {"express": "^5", "h2": "^1"}}', "chore: bump express")
    fourth = commit('{"dependencies": {"h2": "^1"}}', "chore: drop express")
    return repo, {"first": first, "second": second, "third": third, "fourth": fourth}


def test_root_commit_introduces_everything_it_declares(tmp_path: Path) -> None:
    repo, oids = _repo(tmp_path)
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert result.introduced[oids["first"]] == frozenset({"express"})


def test_only_the_new_name_counts_as_an_introduction(tmp_path: Path) -> None:
    repo, oids = _repo(tmp_path)
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert result.introduced[oids["second"]] == frozenset({"h2"})


def test_a_version_bump_is_not_an_introduction(tmp_path: Path) -> None:
    """`express ^4 -> ^5` is maintenance, not a choice of library."""
    repo, oids = _repo(tmp_path)
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert oids["third"] not in result.introduced


def test_a_removal_is_recorded_separately(tmp_path: Path) -> None:
    repo, oids = _repo(tmp_path)
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert result.removed[oids["fourth"]] == frozenset({"express"})
    assert oids["fourth"] not in result.introduced


def test_commits_without_a_manifest_are_absent(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=a@example.test",
            "-c",
            "user.name=A",
            "commit",
            "-qm",
            "docs: readme",
        ],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert head not in result.introduced
    assert head not in result.removed


def test_unreadable_manifest_is_counted_not_silently_empty(tmp_path: Path) -> None:
    """A parse failure must not read as 'this commit declared nothing'."""
    repo, _ = _repo(tmp_path)
    (repo / "package.json").write_text("{not json", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=a@example.test",
            "-c",
            "user.name=A",
            "commit",
            "-qm",
            "chore: break the manifest",
        ],
        check=True,
        capture_output=True,
    )
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert result.unparseable >= 1, (
        "an unreadable manifest was skipped without being counted; the caller "
        "cannot tell coverage from absence"
    )


def test_manifest_count_is_reported_for_coverage(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    result = collect_dependency_introductions(repo, revision="HEAD")
    assert result.manifest_commits == 4
