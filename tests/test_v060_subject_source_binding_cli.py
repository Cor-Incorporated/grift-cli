"""CLI falsification for target-bound forge/tracker inputs on v0.6 subjects."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from git_fixture import commit, git, init_repo
import tep_core.analyze_v2 as analyze_v2_module
from tep_cli.__main__ import main
from tep_core.forge import load_forge_export
from tep_core.identity import email_identity_sha256
from tep_core.tracker import load_tracker_export


def _sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="alice@example.test",
        date="2026-08-01",
        message="feat: source-bound fixture",
        filename="src/app.py",
    )
    git(repo, "remote", "add", "origin", "https://github.com/acme/source-bound.git")
    identity = repo / ".tep" / "identity.toml"
    identity.parent.mkdir(parents=True)
    email_digest = email_identity_sha256("alice@example.test")
    identity.write_text(
        'schema_version = "identity-v2"\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        f'email_sha256 = ["{email_digest}"]\n'
        'attribution_state = "verified"\n',
        encoding="utf-8",
    )
    project = tmp_path / "project.toml"
    project.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "checkout-api"\n',
        encoding="utf-8",
    )
    return repo, identity, project


def _binding(repo: Path, **overrides: object) -> dict[str, Any]:
    value: dict[str, Any] = {
        "provider": "github",
        "host": "github.com",
        "project_id": "R_source_bound_1",
        "project_path": "acme/source-bound",
        "target_oid": {"algorithm": "sha1", "value": _sha(repo)},
        "window": {
            "start": "2026-08-01T00:00:00Z",
            "end": "2026-09-01T00:00:00Z",
        },
        "coverage": {
            "status": "complete",
            "observed": 31,
            "expected": 31,
            "missing": 0,
            "unit": "days",
        },
    }
    value.update(overrides)
    return value


def _write_export(
    path: Path,
    repo: Path,
    *,
    kind: str = "forge",
    binding: dict[str, Any] | None = None,
) -> Path:
    schema = "tep-forge-export-v2" if kind == "forge" else "tep-tracker-export-v2"
    source_binding = binding or _binding(repo)
    if kind == "forge":
        events = [
            {
                "event_id": "forge-1",
                "kind": "pull_request_review",
                "timestamp": "2026-08-10T00:00:00Z",
                "actor_canonical_id": "alice",
                "project_id": source_binding["project_id"],
                "project_path": source_binding["project_path"],
                "pr_number": 7,
                "commit_sha": _sha(repo),
            },
            {
                "event_id": "forge-2",
                "kind": "pull_request_opened",
                "timestamp": "2026-08-12T00:00:00Z",
                "actor_canonical_id": "bob",
                "project_id": source_binding["project_id"],
                "project_path": source_binding["project_path"],
                "pr_number": 8,
                "commit_sha": _sha(repo),
            },
        ]
    else:
        events = [
            {
                "event_id": "issue-opened-1",
                "kind": "issue_opened",
                "timestamp": "2026-08-10T00:00:00Z",
                "actor_canonical_id": "alice",
                "project_id": source_binding["project_id"],
                "project_path": source_binding["project_path"],
                "record_type": "issue",
                "record_id": "issue-7",
                "state": "open",
                "previous_state": None,
                "previous_event_id": None,
                "linked_event_id": None,
                "duration_seconds": None,
                "issue_number": 7,
                "commit_sha": _sha(repo),
            },
            {
                "event_id": "issue-closed-1",
                "kind": "issue_closed",
                "timestamp": "2026-08-11T00:00:00Z",
                "actor_canonical_id": "alice",
                "project_id": source_binding["project_id"],
                "project_path": source_binding["project_path"],
                "record_type": "issue",
                "record_id": "issue-7",
                "state": "closed",
                "previous_state": "open",
                "previous_event_id": "issue-opened-1",
                "linked_event_id": None,
                "duration_seconds": 86400,
                "issue_number": 7,
                "commit_sha": _sha(repo),
            },
            {
                "event_id": "issue-opened-2",
                "kind": "issue_opened",
                "timestamp": "2026-08-12T00:00:00Z",
                "actor_canonical_id": "bob",
                "project_id": source_binding["project_id"],
                "project_path": source_binding["project_path"],
                "record_type": "issue",
                "record_id": "issue-8",
                "state": "open",
                "previous_state": None,
                "previous_event_id": None,
                "linked_event_id": None,
                "duration_seconds": None,
                "issue_number": 8,
                "commit_sha": _sha(repo),
            },
            {
                "event_id": "issue-closed-2",
                "kind": "issue_closed",
                "timestamp": "2026-08-13T00:00:00Z",
                "actor_canonical_id": "bob",
                "project_id": source_binding["project_id"],
                "project_path": source_binding["project_path"],
                "record_type": "issue",
                "record_id": "issue-8",
                "state": "closed",
                "previous_state": "open",
                "previous_event_id": "issue-opened-2",
                "linked_event_id": None,
                "duration_seconds": 86400,
                "issue_number": 8,
                "commit_sha": _sha(repo),
            },
        ]
    path.write_text(
        json.dumps(
            {
                "schema_version": schema,
                "binding": source_binding,
                "events": events,
            }
        ),
        encoding="utf-8",
    )
    return path


def _legacy_export(path: Path, *, kind: str = "forge") -> Path:
    schema = "tep-forge-export-v1" if kind == "forge" else "tep-tracker-export-v1"
    path.write_text(
        json.dumps({"schema_version": schema, "provider": "github", "events": []}),
        encoding="utf-8",
    )
    return path


def _subject_commands(
    repo: Path,
    identity: Path,
    project: Path,
    *,
    option: str,
    export: Path,
) -> list[list[str]]:
    return [
        ["repo", str(repo), option, str(export), "--format", "json"],
        [
            "actor",
            "alice",
            str(repo),
            "--identity",
            str(identity),
            option,
            str(export),
            "--format",
            "json",
        ],
        ["project", str(repo), option, str(export), "--format", "json"],
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(identity),
            "--actor",
            "alice",
            "--project",
            str(project),
            option,
            str(export),
            "--format",
            "json",
        ],
    ]


@pytest.mark.parametrize(
    ("kind", "option"),
    (("forge", "--forge-export"), ("tracker", "--tracker-export")),
)
def test_all_v060_subjects_reject_unbound_v1_but_legacy_loader_keeps_read_compatibility(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    option: str,
) -> None:
    repo, identity, project = _fixture(tmp_path)
    export = _legacy_export(tmp_path / f"legacy-{kind}.json", kind=kind)

    # The format remains readable for legacy commands/library consumers.
    if kind == "forge":
        assert load_forge_export(export).schema_version == "tep-forge-export-v1"
    else:
        assert load_tracker_export(export).schema_version == "tep-tracker-export-v1"

    for command in _subject_commands(repo, identity, project, option=option, export=export):
        assert main(command) == 2
        assert "unbound" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("kind", "option"),
    (("forge", "--forge-export"), ("tracker", "--tracker-export")),
)
def test_target_bound_v2_is_accepted_and_recorded_by_every_v060_subject(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    option: str,
) -> None:
    repo, identity, project = _fixture(tmp_path)
    export = _write_export(tmp_path / f"bound-{kind}.json", repo, kind=kind)

    for command in _subject_commands(repo, identity, project, option=option, export=export):
        assert main(command) == 0, capsys.readouterr().err
        output = json.loads(capsys.readouterr().out)
        provenance = output.get("provenance") or {}
        if output.get("schema_version") == "alignment-v1":
            # Compatibility align copies the actor report's source digest.
            digest = provenance["input_digests"][kind]
        elif output.get("schema_version") == "project-v1":
            digest = provenance["input_digests"][kind]
            binding = output["observed"]["input_coverage"][kind]["binding"]
            assert binding["project_id"] == "R_source_bound_1"
            if kind == "forge":
                assert output["observed"]["event_observation"]["sample_size"] == 2
            else:
                assert output["observed"]["tracker_lifecycle"]["sample_size"] == 4
        else:
            digest = provenance["input_digests"][kind]
            binding = output["input_coverage"][kind]["binding"]
            assert binding["project_id"] == "R_source_bound_1"
            assert binding["target_oid"]["value"] == _sha(repo)
            if kind == "forge":
                observation = output["event_observation"]
                assert observation["kind"] == "observed"
                expected = 1 if output["subject"]["kind"] == "actor" else 2
                assert observation["sample_size"] == expected
                assert observation["event_type_counts"]["values"]["pull_request_review"] == 1
                assert observation["active_utc_days"]["value"] == expected
                assert observation["binding"]["coverage"]["missing"] == 0
            else:
                lifecycle = output["tracker_lifecycle"]
                assert lifecycle["kind"] == "observed"
                expected = 2 if output["subject"]["kind"] == "actor" else 4
                assert lifecycle["sample_size"] == expected
                assert lifecycle["event_kind_counts"]["issue_closed"] == (
                    1 if output["subject"]["kind"] == "actor" else 2
                )
                project_metrics = lifecycle["projects"]["R_source_bound_1"]
                assert project_metrics["issue_created_to_closed_median_hours"]["value"] == 24.0
                assert output["input_coverage"]["event_window"]["source_format"] == (
                    "tep-tracker-export-v2"
                )
        assert isinstance(digest, str) and len(digest) == 64


@pytest.mark.parametrize(
    ("mutation", "needle"),
    (
        ({"provider": "gitlab"}, "provider"),
        ({"host": "gitlab.com"}, "host"),
        ({"project_path": "other/repository"}, "project_path"),
        ({"target_oid": {"algorithm": "sha1", "value": "a" * 40}}, "target_oid"),
    ),
)
def test_repo_rejects_self_consistent_export_bound_to_another_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: dict[str, Any],
    needle: str,
) -> None:
    repo, _identity, _project = _fixture(tmp_path)
    binding = _binding(repo)
    binding.update(copy.deepcopy(mutation))
    export = _write_export(tmp_path / "wrong-source.json", repo, binding=binding)

    assert main(["repo", str(repo), "--forge-export", str(export), "--format", "json"]) == 2
    assert needle in capsys.readouterr().err


def test_repo_rejects_explicit_window_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _identity, _project = _fixture(tmp_path)
    export = _write_export(tmp_path / "wrong-window.json", repo)
    assert (
        main(
            [
                "repo",
                str(repo),
                "--forge-export",
                str(export),
                "--event-window",
                "2026-08-02",
                "2026-09-01",
                "--format",
                "json",
            ]
        )
        == 2
    )
    assert "window" in capsys.readouterr().err


def test_forge_and_tracker_must_bind_the_same_stable_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _identity, _project = _fixture(tmp_path)
    forge = _write_export(tmp_path / "forge.json", repo)
    other = _binding(repo, project_id="R_other_project")
    tracker = _write_export(tmp_path / "tracker.json", repo, kind="tracker", binding=other)

    assert (
        main(
            [
                "repo",
                str(repo),
                "--forge-export",
                str(forge),
                "--tracker-export",
                str(tracker),
                "--format",
                "json",
            ]
        )
        == 2
    )
    assert "project_id" in capsys.readouterr().err


def test_saved_report_alignment_refuses_new_unbound_side_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, identity, _project = _fixture(tmp_path)
    actor_report = tmp_path / "actor-report.json"
    project_report = tmp_path / "project-report.json"
    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--identity",
                str(identity),
                "--format",
                "json",
                "--out",
                str(actor_report),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "project",
                str(repo),
                "--format",
                "json",
                "--out",
                str(project_report),
            ]
        )
        == 0
    )
    capsys.readouterr()
    legacy = _legacy_export(tmp_path / "legacy.json")

    assert (
        main(
            [
                "align",
                "--actor-report",
                str(actor_report),
                "--project-report",
                str(project_report),
                "--forge-export",
                str(legacy),
            ]
        )
        == 2
    )
    assert "saved-report align refuses" in capsys.readouterr().err


def test_project_detects_head_change_during_unmaterialized_analysis(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _identity, _project = _fixture(tmp_path)
    original = analyze_v2_module.describe_revision(repo)
    calls = 0

    def drifting_revision(path: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original
        return replace(
            original,
            oid={"algorithm": original.oid["algorithm"], "value": "f" * 40},
        )

    monkeypatch.setattr(analyze_v2_module, "describe_revision", drifting_revision)
    assert main(["project", str(repo), "--format", "json"]) == 2
    assert "HEAD changed during subject analysis" in capsys.readouterr().err
