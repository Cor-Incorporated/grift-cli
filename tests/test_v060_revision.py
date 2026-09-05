from __future__ import annotations

import json
import subprocess
from pathlib import Path

from git_fixture import commit, init_repo
from tep_cli.__main__ import main
from tep_core.gitutil import coauthor_shas, read_numstat
from tep_core.revision import fixed_revision_worktree


def test_fixed_revision_uses_tree_not_dirty_working_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="first@example.com",
        date="2025-01-01",
        message="feat: first",
        filename="value.txt",
    )
    first = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo / ".mailmap").write_text("Canonical <canonical@example.com> <first@example.com>\n")
    subprocess.run(["git", "-C", str(repo), "add", ".mailmap"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "feat: mailmap",
        ],
        check=True,
        capture_output=True,
    )
    (repo / "value.txt").write_text("dirty and not committed\n", encoding="utf-8")
    (repo / ".mailmap").write_text("Wrong <wrong@example.com> <first@example.com>\n")

    with fixed_revision_worktree(repo, first) as fixed:
        assert fixed.worktree != repo
        assert fixed.oid == {"algorithm": "sha1", "value": first}
        assert (fixed.worktree / "value.txt").read_text(
            encoding="utf-8"
        ) != "dirty and not committed\n"
        assert not (fixed.worktree / ".mailmap").exists()

    assert (repo / "value.txt").read_text(encoding="utf-8") == "dirty and not committed\n"
    assert (repo / ".mailmap").read_text(encoding="utf-8").startswith("Wrong")


def test_sha256_repository_reports_generic_oid(tmp_path: Path) -> None:
    repo = tmp_path / "sha256"
    result = subprocess.run(
        ["git", "init", "--object-format=sha256", str(repo)], capture_output=True, text=True
    )
    if result.returncode:
        return
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "commit",
            "-m",
            "seed",
            "-m",
            "Co-authored-by: Helper <helper@example.test>",
        ],
        check=True,
        capture_output=True,
    )
    oid = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with fixed_revision_worktree(repo) as fixed:
        assert fixed.oid["algorithm"] == "sha256"
        assert len(fixed.oid["value"]) == 64
    assert coauthor_shas(repo) == {oid}
    assert read_numstat(repo) == {oid: (("a.txt", 1, 0),)}


def test_explicit_head_revision_excludes_dirty_and_untracked_observation_inputs(
    tmp_path: Path,
    capsys: object,
) -> None:
    repo = init_repo(tmp_path / "repo")
    committed_files = {
        "src/app.py": "print('committed')\n",
        "tests/test_committed.py": "def test_committed():\n    assert True\n",
        "pyproject.toml": '[project]\nname = "fixture"\ndependencies = ["pytest"]\n',
        "LICENSE": "committed license\n",
        ".mailmap": "Alice <alice@example.test> Alias <alias@example.test>\n",
        ".tep/ai-identities.toml": (
            'schema_version = "ai-identity-v1"\nemails = ["tool@example.test"]\n'
        ),
    }
    for relative, body in committed_files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "feat: fixed tree inputs"],
        check=True,
    )
    target = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Every observation-relevant filesystem input is now contaminated without
    # changing the fixed commit.
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\ndependencies = ["vitest"]\n', encoding="utf-8"
    )
    (repo / "LICENSE").write_text("dirty license\n", encoding="utf-8")
    (repo / ".mailmap").write_text(
        "Wrong <wrong@example.test> Alias <alias@example.test>\n", encoding="utf-8"
    )
    (repo / ".tep" / "ai-identities.toml").write_text(
        'schema_version = "ai-identity-v1"\nemails = ["wrong@example.test"]\n',
        encoding="utf-8",
    )
    injected = repo / "spec" / "test_injected.py"
    injected.parent.mkdir()
    injected.write_text("raise RuntimeError('must not be observed')\n", encoding="utf-8")

    with fixed_revision_worktree(repo, target) as fixed:
        assert fixed.worktree != repo
        assert (fixed.worktree / "pyproject.toml").read_text(encoding="utf-8") == (
            committed_files["pyproject.toml"]
        )
        assert (fixed.worktree / "LICENSE").read_text(encoding="utf-8") == (
            committed_files["LICENSE"]
        )
        assert (fixed.worktree / ".mailmap").read_text(encoding="utf-8") == (
            committed_files[".mailmap"]
        )
        assert (fixed.worktree / ".tep" / "ai-identities.toml").read_text(
            encoding="utf-8"
        ) == committed_files[".tep/ai-identities.toml"]
        assert not (fixed.worktree / "spec").exists()

    output = tmp_path / "report.json"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--rev",
                target,
                "--format",
                "json",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["test_frameworks"] == {
        "kind": "observed",
        "value": True,
        "names": ["pytest"],
        "directories": ["tests"],
        "unit": "boolean",
    }
    license_row = report["input_coverage"]["public_forge"]["repository_license"]
    assert license_row["files"][0]["path"] == "LICENSE"
    assert license_row["files"][0]["bytes"] == len(committed_files["LICENSE"].encode())
    assert report["population"]["actor_count"] == 1
    assert (repo / "LICENSE").read_text(encoding="utf-8") == "dirty license\n"
    assert injected.is_file()
