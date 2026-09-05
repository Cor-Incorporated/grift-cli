"""Regression coverage for report-v2 inferred-actor verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tep_cli.__main__ import main

from git_fixture import commit, git, init_repo


def _identityless_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "git@github.com:Example/demo.git")
    commit(
        repo,
        email="alice@example.com",
        date="2026-08-01",
        message="feat: alice",
        filename="alice.py",
        name="Alice",
    )
    commit(
        repo,
        email="bob@example.com",
        date="2026-08-02",
        message="feat: bob",
        filename="bob.py",
        name="Bob",
    )
    return repo


def _inferred_actor_report(repo: Path, path: Path, capsys: object) -> dict:
    assert main(["actor", "alice", str(repo), "--format", "json", "--out", str(path)]) == 0
    capsys.readouterr()
    return json.loads(path.read_text(encoding="utf-8"))


def test_verify_reconstructs_inferred_actor_from_fixed_git_partition(
    tmp_path: Path, capsys: object
) -> None:
    repo = _identityless_repo(tmp_path)
    report_path = tmp_path / "actor.json"
    report = _inferred_actor_report(repo, report_path, capsys)
    assert report["subject"]["selection"] == "inferred_actor"
    commit(
        repo,
        email="later@example.com",
        date="2026-08-03",
        message="feat: after recorded target",
        filename="later.py",
        name="Later",
    )

    assert main(["verify", str(report_path), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_verify_rejects_unknown_inferred_actor_id_as_mismatch(
    tmp_path: Path, capsys: object
) -> None:
    repo = _identityless_repo(tmp_path)
    report_path = tmp_path / "actor.json"
    report = _inferred_actor_report(repo, report_path, capsys)
    report["subject"]["canonical_id"] = "missing_actor"
    report["subject"]["actor_id"] = "missing_actor"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert main(["verify", str(report_path), "--repo", str(repo)]) == 1
    output = capsys.readouterr().out
    assert "MISMATCH" in output
    assert "not present in the fixed Git actor partition" in output


def test_verify_inferred_actor_fails_closed_for_other_repository(
    tmp_path: Path, capsys: object
) -> None:
    repo = _identityless_repo(tmp_path)
    report_path = tmp_path / "actor.json"
    _inferred_actor_report(repo, report_path, capsys)
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "--quiet", str(repo), str(other)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert main(["verify", str(report_path), "--repo", str(other)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_verify_inferred_actor_rejects_target_oid_tampering(tmp_path: Path, capsys: object) -> None:
    repo = _identityless_repo(tmp_path)
    report_path = tmp_path / "actor.json"
    report = _inferred_actor_report(repo, report_path, capsys)
    report["provenance"]["target_oid"]["value"] = "f" * 40
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert main(["verify", str(report_path), "--repo", str(repo)]) == 1
    output = capsys.readouterr().out
    assert "MISMATCH" in output
    assert "report-v2 schema invalid" in output
    assert "$.target.oid" in output


def test_verify_explicit_actor_identity_remains_compatible(tmp_path: Path, capsys: object) -> None:
    repo = _identityless_repo(tmp_path)
    identity = tmp_path / "identity.toml"
    identity.write_text(
        """schema_version = "identity-v1"

[[actors]]
canonical_id = "candidate_001"
emails = ["alice@example.com"]
attribution_state = "verified"
""",
        encoding="utf-8",
    )
    report_path = tmp_path / "explicit-actor.json"
    assert (
        main(
            [
                "actor",
                "candidate_001",
                str(repo),
                "--identity",
                str(identity),
                "--format",
                "json",
                "--out",
                str(report_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "verify",
                str(report_path),
                "--repo",
                str(repo),
                "--identity",
                str(identity),
            ]
        )
        == 0
    )
    assert "VERIFIED" in capsys.readouterr().out
