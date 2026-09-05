"""Deep closure checks for the report-v2 Draft 2020-12 contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tep_cli.__main__ import main
from tep_core.schema import load_schema, validate_schema

from git_fixture import commit, init_repo


ROOT = Path(__file__).resolve().parents[1]


def _repo(root: Path) -> Path:
    repo = init_repo(root / "repo")
    for index in range(3):
        commit(
            repo,
            email="alice@example.test",
            name="Alice",
            date=f"2026-08-0{index + 1}",
            message=f"feat: change {index}",
            filename=f"src/module_{index}.py",
        )
    commit(
        repo,
        email="alice@example.test",
        name="Alice",
        date="2026-08-04",
        message="docs: add license",
        filename="LICENSE",
    )
    commit(
        repo,
        email="alice@example.test",
        name="Alice",
        date="2026-08-05",
        message="test: add unit coverage",
        filename="tests/test_module.py",
    )
    identity = repo / ".tep" / "identity.toml"
    identity.parent.mkdir(parents=True)
    identity.write_text(
        'schema_version = "identity-v1"\n\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["alice@example.test"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    return repo


def _emit(capsys: Any, repo: Path, *extra: str) -> dict[str, Any]:
    assert main(["repo", str(repo), "--format", "json", *extra]) == 0, capsys.readouterr().err
    return json.loads(capsys.readouterr().out)


def _draft_errors(payload: dict[str, Any]) -> list[Any]:
    jsonschema = pytest.importorskip("jsonschema")
    return list(
        jsonschema.Draft202012Validator(
            load_schema("report-v2"),
            format_checker=jsonschema.FormatChecker(),
        ).iter_errors(payload)
    )


def _node(payload: dict[str, Any], path: tuple[Any, ...]) -> dict[str, Any]:
    value: Any = payload
    for part in path:
        value = value[part]
    assert isinstance(value, dict), path
    return value


_MAJOR_CHILD_PATHS = (
    ("subject",),
    ("target",),
    ("target", "oid"),
    ("provenance",),
    ("provenance", "lineage"),
    ("provenance", "git_window"),
    ("provenance", "revision_completeness"),
    ("repository",),
    ("identity",),
    ("lineage",),
    ("origin",),
    ("origin", "bot"),
    ("attribution",),
    ("attribution", "unresolved_definitions"),
    ("attribution", "actor_partition"),
    ("attribution", "public_join"),
    ("activity",),
    ("actor_directory",),
    ("actor_directory", "actors", 0),
    ("core_activity_period",),
    ("test_frameworks",),
    ("test_cochange",),
    ("test_cochange", "all_time"),
    ("rework",),
    ("rework", "corrective_rework_rate"),
    ("survival",),
    ("context_profile",),
    ("context_profile", "scale"),
    ("context_profile", "actor_turnover", "value", "2026"),
    ("surface_profile",),
    ("surface_profile", "surface_commit_counts"),
    ("surface_profile", "surface_commit_counts", "values"),
    ("change_rhythm",),
    ("change_rhythm", "active_days_180d"),
    ("verification_profile",),
    ("verification_profile", "test_touch_share"),
    ("coordination_profile",),
    ("coordination_profile", "git"),
    ("coordination_profile", "review"),
    ("event_observation",),
    ("event_rhythm",),
    ("tracker_lifecycle",),
    ("input_coverage",),
    ("input_coverage", "git"),
    ("input_coverage", "public_forge"),
    ("input_coverage", "public_forge", "repository_license"),
    ("input_coverage", "public_forge", "repository_license", "files", 0),
    ("input_coverage", "window_alignment"),
    ("experience",),
    ("role_profile",),
    ("window",),
    ("metrics", "human_nonmerge_commit_share"),
)


@pytest.mark.parametrize("path", _MAJOR_CHILD_PATHS, ids=lambda value: ".".join(map(str, value)))
def test_each_major_report_child_rejects_unknown_key_in_both_validators(
    tmp_path: Path,
    capsys: Any,
    path: tuple[Any, ...],
) -> None:
    payload = _emit(capsys, _repo(tmp_path))
    assert validate_schema("report-v2", payload) == []
    assert _draft_errors(payload) == []

    mutated = copy.deepcopy(payload)
    _node(mutated, path)["unexpected_v060_key"] = True
    assert validate_schema("report-v2", mutated), path
    assert _draft_errors(mutated), path


def test_role_lens_interpretation_and_reference_are_closed_producer_shapes(
    tmp_path: Path,
    capsys: Any,
) -> None:
    repo = _repo(tmp_path)
    lens = _emit(capsys, repo, "--role-lens", "backend")
    assert validate_schema("report-v2", lens) == []
    assert _draft_errors(lens) == []
    lens["role_lens"]["unexpected_v060_key"] = True
    assert validate_schema("report-v2", lens)
    assert _draft_errors(lens)

    interpreted = _emit(capsys, repo, "--reference-version", "v2026.11")
    assert validate_schema("report-v2", interpreted) == []
    assert _draft_errors(interpreted) == []
    interpreted["interpretation"]["unexpected_v060_key"] = True
    assert validate_schema("report-v2", interpreted)
    assert _draft_errors(interpreted)

    referenced = _emit(
        capsys,
        repo,
        "--reference",
        "gharchive-2024-01-15-to-21-selected-repos",
        "--reference-manifest",
        str(ROOT / "benchmarks" / "v060" / "sources.json"),
    )
    assert validate_schema("report-v2", referenced) == []
    assert _draft_errors(referenced) == []
    referenced["reference"]["catalog"]["unexpected_v060_key"] = True
    assert validate_schema("report-v2", referenced)
    assert _draft_errors(referenced)


def test_intentional_extension_maps_still_validate_keys_and_values(
    tmp_path: Path,
    capsys: Any,
) -> None:
    payload = _emit(capsys, _repo(tmp_path))

    digests = copy.deepcopy(payload)
    digests["provenance"]["input_digests"]["extension.invalid key"] = None
    assert validate_schema("report-v2", digests)
    assert _draft_errors(digests)

    language = copy.deepcopy(payload)
    language["context_profile"]["language_composition"]["value"]["rust"] = "not-a-number"
    assert validate_schema("report-v2", language)
    assert _draft_errors(language)
