from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from git_fixture import init_repo
from tep_cli.__main__ import main
from tep_core.analyze_v2 import analyze_subject
from tep_core.identity import load_subject_identity
from tep_core.lineage import Lineage
from tep_core.revision import fixed_revision_worktree


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _fixed_report(repo: Path, target: str) -> dict:
    with fixed_revision_worktree(repo, target) as fixed:
        identity = load_subject_identity(fixed.worktree, None, revision=target)
        return analyze_subject(
            fixed.worktree,
            identity,
            Lineage(),
            repository_source=repo,
            subject_kind="repo",
        )


def test_verify_v2_recomputes_recorded_head_from_fixed_tree_and_preserves_source_dirt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = init_repo(tmp_path / "source-repo")
    committed = {
        "src/app.py": "print('fixed')\n",
        "tests/test_app.py": "def test_app():\n    assert True\n",
        "pyproject.toml": '[project]\nname = "fixture"\ndependencies = ["pytest"]\n',
        "LICENSE": "fixed license\n",
        ".tep/identity.toml": (
            'schema_version = "identity-v2"\n'
            "[[actors]]\n"
            'canonical_id = "alice"\n'
            'emails = ["alice@example.test"]\n'
            'attribution_state = "verified"\n'
        ),
        ".tep/ai-identities.toml": (
            'schema_version = "ai-identity-v1"\nemails = ["tool@example.test"]\n'
        ),
    }
    for relative, body in committed.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: fixed verification fixture")
    target = _git(repo, "rev-parse", "HEAD").strip()

    report = _fixed_report(repo, target)
    assert report["provenance"]["analyzed_commit_sha"] == target
    assert report["test_frameworks"]["names"] == ["pytest"]
    assert report["input_coverage"]["public_forge"]["repository_license"]["files"][0][
        "bytes"
    ] == len(committed["LICENSE"].encode())
    report_path = tmp_path / "fixed-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    dirty = {
        "pyproject.toml": '[project]\nname = "fixture"\ndependencies = ["vitest"]\n',
        "LICENSE": "dirty license\n",
        ".tep/identity.toml": (
            'schema_version = "identity-v2"\n'
            "[[actors]]\n"
            'canonical_id = "mallory"\n'
            'emails = ["mallory@example.test"]\n'
            'attribution_state = "verified"\n'
        ),
        ".tep/ai-identities.toml": (
            'schema_version = "ai-identity-v1"\nemails = ["wrong@example.test"]\n'
        ),
    }
    for relative, body in dirty.items():
        (repo / relative).write_text(body, encoding="utf-8")
    injected = repo / "spec" / "test_untracked.py"
    injected.parent.mkdir()
    injected.write_text("raise RuntimeError('must not be observed')\n", encoding="utf-8")

    status_before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    worktrees_before = _git(repo, "worktree", "list", "--porcelain")
    bytes_before = {
        relative: (repo / relative).read_bytes() for relative in [*dirty, "spec/test_untracked.py"]
    }

    assert main(["verify", str(report_path), "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.startswith("VERIFIED:")
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert _git(repo, "worktree", "list", "--porcelain") == worktrees_before
    assert {
        relative: (repo / relative).read_bytes() for relative in [*dirty, "spec/test_untracked.py"]
    } == bytes_before

    tampered = copy.deepcopy(report)
    tampered["test_frameworks"]["value"] = False
    tampered_path = tmp_path / "tampered-report.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")

    assert main(["verify", str(tampered_path), "--repo", str(repo)]) == 1
    output = capsys.readouterr().out
    assert output.startswith("MISMATCH:")
    assert "test_frameworks" in output
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert _git(repo, "worktree", "list", "--porcelain") == worktrees_before
    assert {
        relative: (repo / relative).read_bytes() for relative in [*dirty, "spec/test_untracked.py"]
    } == bytes_before
