"""Determinism and offline rails for subject commands."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.forge import load_forge_export
from tep_core.gitutil import GitCommit
from tep_core.rhythm import ordered_commits

from git_fixture import commit, init_repo


def test_commit_order_does_not_change_rhythm_sort() -> None:
    a = GitCommit("b" * 40, "a@x", ("p",), "2026-01-02", "a", author_iso="2026-01-02T12:00:00Z")
    b = GitCommit("a" * 40, "a@x", ("p",), "2026-01-01", "b", author_iso="2026-01-01T12:00:00Z")
    assert [item.sha for item in ordered_commits([a, b])] == [
        item.sha for item in ordered_commits([b, a])
    ]


def test_forge_event_sort_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "forge.json"
    events = [
        {
            "event_id": "2",
            "kind": "pull_request_review",
            "timestamp": "2026-08-29T00:00:01Z",
            "actor_canonical_id": "candidate_001",
            "commit_sha": "a" * 40,
        },
        {
            "event_id": "1",
            "kind": "pull_request_review",
            "timestamp": "2026-08-29T00:00:00Z",
            "actor_canonical_id": "candidate_001",
            "commit_sha": "b" * 40,
        },
    ]
    path.write_text(
        json.dumps(
            {"schema_version": "tep-forge-export-v1", "provider": "github", "events": events}
        ),
        encoding="utf-8",
    )
    loaded = load_forge_export(path)
    assert [item.event_id for item in loaded.events] == ["1", "2"]


def test_subject_commands_do_not_touch_socket(tmp_path: Path, monkeypatch, capsys: object) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("socket.create_connection", boom)
    monkeypatch.setattr("urllib.request.urlopen", boom)
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="app.py")
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    project = tmp_path / "p.toml"
    project.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "checkout-api"\n', encoding="utf-8"
    )
    assert main(["repo", str(repo), "--format", "json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "actor",
                "candidate_001",
                str(repo),
                "--identity",
                str(ident),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["project", "--requirements", str(project), "--format", "json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "align",
                "--repo",
                str(repo),
                "--identity",
                str(ident),
                "--actor",
                "candidate_001",
                "--project",
                str(project),
                "--format",
                "json",
            ]
        )
        == 0
    )
