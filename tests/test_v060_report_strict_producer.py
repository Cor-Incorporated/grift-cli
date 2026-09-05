"""Strict report-v2 envelope integration for the real repo/actor CLI producers."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import tep_cli.subject as subject_module
from tep_cli.__main__ import main
from tep_core.schema import load_schema, validate_schema
from tep_core.schema_v2 import validate_report_v2

from git_fixture import commit, init_repo


def _repository(root: Path) -> Path:
    repo = init_repo(root / "repo")
    for index in range(3):
        commit(
            repo,
            email="alice@example.test",
            name="Alice",
            date="2026-08-01",
            message=f"feat: alice {index}",
            filename="src/app.py",
        )
    for index in range(2):
        commit(
            repo,
            email="bob@example.test",
            name="Bob",
            date="2026-08-02",
            message=f"fix: bob {index}",
            filename="src/other.py",
        )
    identity = repo / ".tep" / "identity.toml"
    identity.parent.mkdir(parents=True)
    identity.write_text(
        'schema_version = "identity-v1"\n\n'
        '[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["alice@example.test"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    return repo


def _emit(capsys: Any, argv: list[str]) -> dict[str, Any]:
    assert main(argv) == 0, capsys.readouterr().err
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _population_digest(population: dict[str, Any]) -> str:
    body = {
        key: population[key]
        for key in (
            "actor_count",
            "human_commit_count",
            "nonmerge_commit_count",
            "merge_commit_count",
            "basis",
            "partition_digest",
        )
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(b"tep-population-v1\0" + encoded).hexdigest()


def _draft_errors(payload: dict[str, Any]) -> list[Any]:
    jsonschema = pytest.importorskip("jsonschema")
    return list(
        jsonschema.Draft202012Validator(
            load_schema("report-v2"),
            format_checker=jsonschema.FormatChecker(),
        ).iter_errors(payload)
    )


def test_repo_cli_emits_closed_strict_envelope_and_keeps_rich_sections(
    tmp_path: Path, capsys: Any
) -> None:
    repo = _repository(tmp_path)
    payload = _emit(
        capsys,
        ["repo", str(repo), "--format", "json", "--as-of", "2026-08-29"],
    )

    assert validate_report_v2(payload) == []
    assert validate_schema("report-v2", payload) == []
    assert _draft_errors(payload) == []
    assert payload["target"]["oid"] == payload["provenance"]["target_oid"]
    assert payload["target"]["oid"]["value"] == payload["provenance"]["analyzed_commit_sha"]
    population = payload["population"]
    assert population["human_commit_count"] == (
        population["nonmerge_commit_count"] + population["merge_commit_count"]
    )
    assert (
        population["partition_digest"]["value"]
        == payload["attribution"]["actor_partition"]["partition_digest"]
    )
    assert population["population_digest"]["value"] == _population_digest(population)
    assert payload["metrics"]["human_nonmerge_commit_share"]["window"] == payload["window"]
    assert all("internal_actor_id" not in actor for actor in payload["actor_directory"]["actors"])
    for rich_key in (
        "repository",
        "identity",
        "origin",
        "activity",
        "surface_profile",
        "change_rhythm",
        "verification_profile",
        "coordination_profile",
        "input_coverage",
    ):
        assert rich_key in payload


def test_actor_subject_binding_and_strict_blocks_are_deterministic(
    tmp_path: Path, capsys: Any
) -> None:
    repo = _repository(tmp_path)
    argv = [
        "actor",
        "candidate_001",
        str(repo),
        "--identity",
        str(repo / ".tep" / "identity.toml"),
        "--format",
        "json",
        "--as-of",
        "2026-08-29",
    ]
    first = _emit(capsys, argv)
    second = _emit(capsys, argv)

    assert first["subject"] == {
        "kind": "actor",
        "selection": "explicit_actor",
        "canonical_id": "candidate_001",
        "actor_id": "candidate_001",
        "attribution_state": "verified",
    }
    assert validate_schema("report-v2", first) == []
    assert _draft_errors(first) == []
    for key in ("target", "population", "window", "metrics", "attribution"):
        assert first[key] == second[key]


def test_population_target_partition_and_unknown_key_mutations_fail_closed(
    tmp_path: Path, capsys: Any
) -> None:
    payload = _emit(
        capsys,
        ["repo", str(_repository(tmp_path)), "--format", "json"],
    )

    population = copy.deepcopy(payload)
    population["population"]["human_commit_count"] += 1
    assert any("human_commit_count" in error for error in validate_schema("report-v2", population))

    partition = copy.deepcopy(payload)
    partition["population"]["partition_digest"]["value"] = "f" * 64
    assert any("partition_digest" in error for error in validate_schema("report-v2", partition))

    target = copy.deepcopy(payload)
    target["target"]["oid"]["value"] = "f" * 40
    assert any("provenance.target_oid" in error for error in validate_schema("report-v2", target))

    root_unknown = copy.deepcopy(payload)
    root_unknown["unexpected_root"] = True
    assert any("unexpected_root" in error for error in validate_report_v2(root_unknown))

    provenance_unknown = copy.deepcopy(payload)
    provenance_unknown["provenance"]["unexpected_provenance"] = True
    assert any("unexpected_provenance" in error for error in validate_report_v2(provenance_unknown))

    leaked_internal = copy.deepcopy(payload)
    leaked_internal["actor_directory"]["actors"][0]["internal_actor_id"] = "secret"
    assert any(
        "internal_actor_id" in error for error in validate_schema("report-v2", leaked_internal)
    )


def test_cli_validation_path_rejects_unknown_root_from_producer(
    tmp_path: Path, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    payload = _emit(capsys, ["repo", str(repo), "--format", "json"])
    payload["unexpected_root"] = True
    monkeypatch.setattr(subject_module, "analyze_subject", lambda *_args, **_kwargs: payload)

    assert main(["repo", str(repo), "--format", "json"]) == 2
    assert "unexpected_root" in capsys.readouterr().err


def test_history_incomplete_is_the_only_additional_consent_gate_reason(
    tmp_path: Path, capsys: Any
) -> None:
    payload = _emit(
        capsys,
        ["repo", str(_repository(tmp_path)), "--format", "json"],
    )
    for key, definition in (
        ("experience", "experience-v1"),
        ("role_profile", "role-profile-v1"),
    ):
        payload[key] = {
            "kind": "not_observed",
            "actor_id": "repo",
            "reason": "history_incomplete",
            "definition_version": definition,
            "limitations": ["Missing Git objects prevent complete history observation."],
        }
    assert validate_schema("report-v2", payload) == []

    payload["experience"]["reason"] = "unknown_history_reason"
    assert validate_schema("report-v2", payload)
