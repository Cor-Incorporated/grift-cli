"""Local forge/tracker export loading and refusal of secrets."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.forge import load_forge_export
from tep_core.secrets_guard import InputValidationError
from tep_core.tracker import load_tracker_export

from git_fixture import commit, init_repo


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="app.py")
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    return repo


def test_forge_parse_and_sort(tmp_path: Path) -> None:
    path = tmp_path / "forge.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "tep-forge-export-v1",
                "provider": "github",
                "events": [
                    {
                        "event_id": "b",
                        "kind": "pull_request_review",
                        "timestamp": "2026-08-29T01:00:00Z",
                        "actor_canonical_id": "candidate_001",
                        "pr_number": 2,
                        "commit_sha": "a" * 40,
                    },
                    {
                        "event_id": "a",
                        "kind": "pull_request_review",
                        "timestamp": "2026-08-29T01:00:00Z",
                        "actor_canonical_id": "candidate_001",
                        "pr_number": 1,
                        "commit_sha": "b" * 40,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_forge_export(path)
    assert [item.event_id for item in loaded.events] == ["a", "b"]


def test_malformed_forge_exit_2(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    bad = tmp_path / "forge.json"
    bad.write_text("{}", encoding="utf-8")
    code = main(["repo", str(repo), "--forge-export", str(bad), "--format", "json"])
    assert code == 2
    assert "forge" in capsys.readouterr().err.lower()


def test_bad_sha_refused(tmp_path: Path) -> None:
    path = tmp_path / "forge.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "tep-forge-export-v1",
                "provider": "github",
                "events": [
                    {
                        "event_id": "a",
                        "kind": "pull_request_review",
                        "timestamp": "2026-08-29T00:00:00Z",
                        "actor_canonical_id": "candidate_001",
                        "commit_sha": "not-a-sha",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        load_forge_export(path)
    except InputValidationError:
        return
    raise AssertionError("invalid sha must be refused")


def test_missing_export_is_not_observed_not_zero(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    review = payload["coordination_profile"]["review"]
    assert review["kind"] == "not_observed"
    assert review["reason"] == "forge_export_not_provided"
    tracker = payload["coordination_profile"]["tracker"]
    assert tracker["kind"] == "not_observed"
    assert tracker["reason"] == "tracker_export_not_provided"


def test_email_in_tracker_refused(tmp_path: Path) -> None:
    path = tmp_path / "tracker.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "tep-tracker-export-v1",
                "provider": "github",
                "events": [
                    {
                        "event_id": "a",
                        "kind": "issue_linked",
                        "timestamp": "2026-08-29T00:00:00Z",
                        "actor_canonical_id": "candidate_001",
                        "note": "write to person@example.com",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        load_tracker_export(path)
    except InputValidationError as exc:
        assert "@" not in str(exc)
        return
    raise AssertionError("raw email must be refused")
