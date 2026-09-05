"""Alignment axis comparisons. No overall verdict."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.v2_constants import FORBIDDEN_VERDICT_KEYS

from git_fixture import commit, init_repo


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    repo = init_repo(tmp_path / "repo")
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "tests").mkdir()
    for index in range(22):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"feat: {index}",
            filename="src/api/app.py",
        )
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    project = tmp_path / "project.toml"
    project.write_text(
        """schema_version = "tep-project-v1"
project_id = "checkout-api"
title = "Checkout API"

[requirements.change_rhythm]
active_days_180d_min = 100
median_gap_days_max = 14
p90_gap_days_max = 60

[requirements.surfaces]
required = ["backend", "frontend"]

[requirements.verification]
required = ["e2e"]

[requirements.inputs]
required = ["git", "tracker"]
""",
        encoding="utf-8",
    )
    return repo, project


def test_alignment_comparison_kinds(tmp_path: Path, capsys: object) -> None:
    repo, project = _setup(tmp_path)
    code = main(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "candidate_001",
            "--project",
            str(project),
            "--as-of",
            "2026-08-29",
            "--format",
            "json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    kinds = {axis["comparison"] for axis in payload["axes"]}
    assert "overlap" in kinds
    assert "observed_zero" in kinds or "not_observed" in kinds
    assert "not_observed" in kinds  # tracker required but missing
    assert "outside_declared_range" in kinds
    by_axis = {axis["axis"]: axis["comparison"] for axis in payload["axes"]}
    assert by_axis["surfaces.backend"] == "overlap"
    assert by_axis["surfaces.frontend"] == "observed_zero"
    assert by_axis["inputs.tracker"] == "not_observed"
    dumped = json.dumps(payload)
    for key in FORBIDDEN_VERDICT_KEYS:
        assert f'"{key}"' not in dumped
    assert "recommendation" not in dumped
    assert payload["subject"]["actor_canonical_id"] == "candidate_001"


def test_not_declared_when_requirements_empty(tmp_path: Path, capsys: object) -> None:
    repo, _project = _setup(tmp_path)
    empty = tmp_path / "empty.toml"
    empty.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "checkout-api"\n', encoding="utf-8"
    )
    assert (
        main(
            [
                "align",
                "--repo",
                str(repo),
                "--identity",
                str(repo / ".tep" / "identity.toml"),
                "--actor",
                "candidate_001",
                "--project",
                str(empty),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    kinds = {axis["comparison"] for axis in payload["axes"]}
    assert "not_declared" in kinds
    assert payload["axes"], "other axes must remain even when some are not_declared"


def test_actor_report_excludes_other_actor(tmp_path: Path, capsys: object) -> None:
    repo, _project = _setup(tmp_path)
    commit(
        repo,
        email="other@example.com",
        date="2026-08-02",
        message="feat: other",
        filename="src/api/other.py",
    )
    ident = repo / ".tep" / "identity.toml"
    ident.write_text(
        'schema_version = "identity-v1"\n\n'
        '[[actors]]\ncanonical_id = "candidate_001"\nemails = ["a@example.com"]\n'
        'attribution_state = "verified"\n\n'
        '[[actors]]\ncanonical_id = "other_actor"\nemails = ["other@example.com"]\n'
        'attribution_state = "claimed"\n',
        encoding="utf-8",
    )
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
    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["actor_count"] == 1
    assert payload["subject"]["canonical_id"] == "candidate_001"
    assert "other_actor" not in json.dumps(payload)
