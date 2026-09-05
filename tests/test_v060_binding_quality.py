"""Target-binding and benchmark data-quality falsification tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tep_core.archive_events import load_archive_events, summarize_archive
from tep_core.benchmark import load_manifest, validate_manifest
from tep_core.event_rhythm import event_rhythm
from tep_core.forge import load_forge_export
from tep_core.local_inputs import load_forge_input, load_tracker_input
from tep_core.role_validation import load_role_sample, validate_role_sample
from tep_core.secrets_guard import InputValidationError
from tep_core.source_binding import parse_source_binding
from tep_core.tracker import load_tracker_export
from tep_core.tracker_lifecycle import load_tracker_lifecycle

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "v060"


def _binding(**overrides: object) -> dict:
    binding: dict = {
        "provider": "gitlab",
        "host": "gitlab.example",
        "project_id": "gid://gitlab/Project/7",
        "project_path": "group/project",
        "target_oid": {"algorithm": "sha1", "value": "a" * 40},
        "window": {"start": "2026-08-01T00:00:00Z", "end": "2026-09-01T00:00:00Z"},
        "coverage": {
            "status": "complete",
            "observed": 31,
            "expected": 31,
            "missing": 0,
            "unit": "days",
        },
    }
    binding.update(overrides)
    return binding


def _event(**overrides: object) -> dict:
    event = {
        "event_id": "evt-1",
        "kind": "pull_request_review",
        "timestamp": "2026-08-15T12:00:00Z",
        "actor_canonical_id": "candidate_001",
        "pr_number": 7,
        "commit_sha": "b" * 40,
        "project_id": "gid://gitlab/Project/7",
        "project_path": "group/project",
    }
    event.update(overrides)
    return event


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_forge_v2_requires_complete_target_binding(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "forge.json",
        {
            "schema_version": "tep-forge-export-v2",
            "binding": _binding(),
            "events": [_event()],
        },
    )
    export = load_forge_export(path)
    assert export.binding is not None
    assert export.binding.project_path == "group/project"
    assert export.binding.coverage.status == "complete"
    assert load_forge_input(path, require_bound=True).source_format == "tep-forge-export-v2"


@pytest.mark.parametrize(
    "mutation,needle",
    [
        ({"project_path": "other/project"}, "mixed source"),
        ({"timestamp": "2026-09-01T00:00:00Z"}, "outside binding window"),
        ({"commit_sha": "b" * 64}, "40-char"),
    ],
)
def test_forge_v2_rejects_mixed_or_out_of_scope_events(
    tmp_path: Path, mutation: dict, needle: str
) -> None:
    path = _write(
        tmp_path / "forge.json",
        {
            "schema_version": "tep-forge-export-v2",
            "binding": _binding(),
            "events": [_event(**mutation)],
        },
    )
    with pytest.raises(InputValidationError, match=needle):
        load_forge_export(path)


def test_binding_coverage_arithmetic_and_unbound_v1_fail_closed(tmp_path: Path) -> None:
    partial = _binding(
        coverage={
            "status": "partial",
            "observed": 7,
            "expected": 168,
            "missing": 160,
            "unit": "hours",
        }
    )
    with pytest.raises(InputValidationError, match=r"observed \+ missing"):
        parse_source_binding(partial, source="test")

    v1 = _write(
        tmp_path / "legacy.json",
        {"schema_version": "tep-forge-export-v1", "provider": "github", "events": []},
    )
    with pytest.raises(InputValidationError, match="unbound"):
        load_forge_input(v1, require_bound=True)


def test_expected_binding_mismatch_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "forge.json",
        {
            "schema_version": "tep-forge-export-v2",
            "binding": _binding(),
            "events": [_event()],
        },
    )
    expected = parse_source_binding(
        _binding(project_id="gid://gitlab/Project/99"), source="expected"
    )
    with pytest.raises(InputValidationError, match="project_id"):
        load_forge_input(path, expected_binding=expected)


def test_tracker_v2_binding_and_duplicate_ids(tmp_path: Path) -> None:
    event = _event(
        kind="issue_opened",
        issue_number=9,
        record_type="issue",
        record_id="issue-9",
        state="open",
        previous_state=None,
        previous_event_id=None,
        linked_event_id=None,
        duration_seconds=None,
    )
    event.pop("pr_number")
    path = _write(
        tmp_path / "tracker.json",
        {
            "schema_version": "tep-tracker-export-v2",
            "binding": _binding(),
            "events": [event],
        },
    )
    export = load_tracker_export(path)
    assert export.binding and export.binding.host == "gitlab.example"
    assert load_tracker_input(path, require_bound=True).source_format == "tep-tracker-export-v2"

    duplicate = json.loads(path.read_text(encoding="utf-8"))
    duplicate["events"].append(dict(event))
    _write(path, duplicate)
    with pytest.raises(InputValidationError, match="duplicate event_id"):
        load_tracker_export(path)


def _tracker_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    columns = [
        "fixture_kind",
        "record_type",
        "record_id",
        "project_id",
        "created_at",
        "in_progress_at",
        "first_review_at",
        "merged_at",
        "closed_at",
        "release_at",
        "status",
        "linked_record_id",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _issue(**overrides: str) -> dict[str, str]:
    row = {
        "fixture_kind": "synthetic_contract",
        "record_type": "issue",
        "record_id": "ISSUE-1",
        "project_id": "project-1",
        "created_at": "2026-08-02T00:00:00Z",
        "in_progress_at": "2026-08-03T00:00:00Z",
        "first_review_at": "",
        "merged_at": "",
        "closed_at": "2026-08-04T00:00:00Z",
        "release_at": "",
        "status": "closed",
        "linked_record_id": "",
        "notes": "fixture",
    }
    row.update(overrides)
    return row


def test_tracker_lifecycle_rejects_negative_duration_and_broken_link(tmp_path: Path) -> None:
    negative = _tracker_csv(
        tmp_path / "negative.csv",
        [_issue(closed_at="2026-08-01T00:00:00Z")],
    )
    with pytest.raises(InputValidationError, match="negative duration"):
        load_tracker_lifecycle(negative)

    broken = _tracker_csv(
        tmp_path / "broken.csv",
        [_issue(linked_record_id="PR-missing")],
    )
    with pytest.raises(InputValidationError, match="broken linked_record_id"):
        load_tracker_lifecycle(broken)


def test_tracker_lifecycle_rejects_missing_columns_and_state_mismatch(tmp_path: Path) -> None:
    missing = tmp_path / "missing-column.csv"
    row = _issue()
    columns = [key for key in row if key != "notes"]
    with missing.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({key: row[key] for key in columns})
    with pytest.raises(InputValidationError, match="columns mismatch"):
        load_tracker_lifecycle(missing)

    inconsistent = _tracker_csv(
        tmp_path / "inconsistent.csv",
        [_issue(status="open", closed_at="2026-08-04T00:00:00Z")],
    )
    with pytest.raises(InputValidationError, match="open issue contains"):
        load_tracker_lifecycle(inconsistent)


def test_role_sample_rejects_duplicate_missing_and_nonfinite_features(tmp_path: Path) -> None:
    source = list(csv.DictReader((PACK / "data" / "role_ground_truth_sample.csv").open()))
    duplicate = tmp_path / "duplicate.csv"
    _write_role(duplicate, [source[0], dict(source[0]), *source[1:]])
    with pytest.raises(InputValidationError, match="duplicate"):
        load_role_sample(duplicate)

    nonfinite = tmp_path / "nonfinite.csv"
    rows = [dict(row) for row in source]
    rows[0]["bio_backend"] = "NaN"
    _write_role(nonfinite, rows)
    with pytest.raises(InputValidationError, match="finite"):
        load_role_sample(nonfinite)

    missing_class = tmp_path / "missing-class.csv"
    rows = [dict(row) for row in source if row["role_label"] != "Mobile"]
    _write_role(missing_class, rows)
    with pytest.raises(InputValidationError, match="missing classes"):
        load_role_sample(missing_class)

    valid = validate_role_sample(PACK / "data" / "role_ground_truth_sample.csv")
    assert valid["effective_sample_size"] == valid["sample_size"] == 40


def _write_role(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_gharchive_coverage_is_7_of_168_and_cadence_withheld() -> None:
    bundle = load_archive_events(PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson")
    assert (bundle.observed_hours, bundle.expected_hours, bundle.missing_hours) == (7, 168, 161)
    assert bundle.coverage_rate == 0.0417
    observation = summarize_archive(bundle)
    assert observation["interval_coverage"]["status"] == "partial"
    assert observation["collection_kind"] == "multi_repository_benchmark"
    rhythm = event_rhythm(bundle)
    assert rhythm["kind"] == "not_proven"
    assert rhythm["reason"] == "mixed_repository_collection"
    assert rhythm["active_day_share"]["kind"] == "not_observed"
    assert all(
        profile["release_interval_days"]["kind"] == "not_observed"
        for profile in rhythm["repositories"].values()
    )


def test_manifest_is_closed_over_all_local_artifacts(tmp_path: Path) -> None:
    result = validate_manifest(PACK / "sources.json")
    assert result["ok"] is True
    copied = tmp_path / "pack"
    import shutil

    shutil.copytree(PACK, copied)
    (copied / "data" / "unregistered.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="unregistered local artifacts"):
        validate_manifest(copied / "sources.json")

    symlinked = tmp_path / "symlink-pack"
    shutil.copytree(PACK, symlinked)
    target = tmp_path / "outside.csv"
    target.write_text("outside\n", encoding="utf-8")
    registered = symlinked / "data" / "role_label_counts.csv"
    registered.unlink()
    registered.symlink_to(target)
    with pytest.raises(InputValidationError, match="symlink fixture"):
        validate_manifest(symlinked / "sources.json")


def test_bundled_manifest_is_available_outside_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GRIFT_BENCHMARK_PACK", raising=False)
    monkeypatch.chdir(tmp_path)
    manifest = load_manifest()
    assert manifest["pack_id"] == "grift-v060-reference-pack"
    assert validate_manifest()["ok"] is True
