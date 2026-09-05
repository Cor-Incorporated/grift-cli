"""Provider-neutral bound export observations and tracker falsification."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tep_core.forge import (
    load_forge_export,
    summarize_forge_export,
    summarize_forge_rhythm,
)
from tep_core.schema import load_schema, validate_schema
from tep_core.secrets_guard import InputValidationError
from tep_core.tracker import load_tracker_export, summarize_tracker_export


def _binding(*, status: str = "complete") -> dict[str, object]:
    missing = 0 if status == "complete" else 24
    return {
        "provider": "gitlab",
        "host": "gitlab.example.test",
        "project_id": "project-42",
        "project_path": "group/repository",
        "target_oid": {"algorithm": "sha1", "value": "a" * 40},
        "window": {
            "start": "2026-08-01T00:00:00Z",
            "end": "2026-09-01T00:00:00Z",
        },
        "coverage": {
            "status": status,
            "observed": 744 - missing,
            "expected": 744,
            "missing": missing,
            "unit": "hours",
        },
    }


def _forge_payload(*, status: str = "complete") -> dict[str, object]:
    binding = _binding(status=status)
    common = {
        "project_id": binding["project_id"],
        "project_path": binding["project_path"],
        "commit_sha": "b" * 40,
    }
    return {
        "schema_version": "tep-forge-export-v2",
        "binding": binding,
        "events": [
            {
                **common,
                "event_id": "f-1",
                "kind": "pull_request_opened",
                "timestamp": "2026-08-02T00:00:00Z",
                "actor_canonical_id": "alice",
                "pr_number": 10,
            },
            {
                **common,
                "event_id": "f-2",
                "kind": "pull_request_review",
                "timestamp": "2026-08-03T00:00:00Z",
                "actor_canonical_id": "bob",
                "pr_number": 10,
            },
            {
                **common,
                "event_id": "f-3",
                "kind": "review_comment",
                "timestamp": "2026-08-03T01:00:00Z",
                "actor_canonical_id": "alice",
                "pr_number": 10,
            },
        ],
    }


def _tracker_payload(*, status: str = "complete") -> dict[str, object]:
    binding = _binding(status=status)
    common = {
        "project_id": binding["project_id"],
        "project_path": binding["project_path"],
        "commit_sha": "b" * 40,
    }
    return {
        "schema_version": "tep-tracker-export-v2",
        "binding": binding,
        "events": [
            {
                **common,
                "event_id": "m-1",
                "kind": "milestone_set",
                "timestamp": "2026-08-02T00:00:00Z",
                "actor_canonical_id": "alice",
                "record_type": "milestone",
                "record_id": "milestone-1",
                "state": "active",
                "previous_state": None,
                "previous_event_id": None,
                "linked_event_id": None,
                "duration_seconds": None,
            },
            {
                **common,
                "event_id": "i-1",
                "kind": "issue_opened",
                "timestamp": "2026-08-02T01:00:00Z",
                "actor_canonical_id": "alice",
                "record_type": "issue",
                "record_id": "issue-7",
                "state": "open",
                "previous_state": None,
                "previous_event_id": None,
                "linked_event_id": None,
                "duration_seconds": None,
                "issue_number": 7,
            },
            {
                **common,
                "event_id": "i-link",
                "kind": "issue_linked",
                "timestamp": "2026-08-02T02:00:00Z",
                "actor_canonical_id": "alice",
                "record_type": "issue",
                "record_id": "issue-7",
                "state": "open",
                "previous_state": "open",
                "previous_event_id": "i-1",
                "linked_event_id": "m-1",
                "duration_seconds": 3600,
                "issue_number": 7,
            },
            {
                **common,
                "event_id": "i-2",
                "kind": "issue_triaged",
                "timestamp": "2026-08-02T03:00:00Z",
                "actor_canonical_id": "bob",
                "record_type": "issue",
                "record_id": "issue-7",
                "state": "triaged",
                "previous_state": "open",
                "previous_event_id": "i-1",
                "linked_event_id": None,
                "duration_seconds": 7200,
                "issue_number": 7,
            },
            {
                **common,
                "event_id": "i-3",
                "kind": "issue_closed",
                "timestamp": "2026-08-02T04:00:00Z",
                "actor_canonical_id": "alice",
                "record_type": "issue",
                "record_id": "issue-7",
                "state": "closed",
                "previous_state": "triaged",
                "previous_event_id": "i-2",
                "linked_event_id": None,
                "duration_seconds": 3600,
                "issue_number": 7,
            },
        ],
    }


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_forge_bound_summary_is_provider_neutral_and_actor_exact(tmp_path: Path) -> None:
    export = load_forge_export(_write(tmp_path / "forge.json", _forge_payload()))
    repo = summarize_forge_export(export)
    actor = summarize_forge_export(export, canonical_id="alice")

    assert repo["sample_size"] == 3
    assert repo["event_type_counts"]["values"]["pull_request_review"] == 1
    assert repo["active_utc_days"]["value"] == 2
    assert repo["binding"]["provider"] == "gitlab"
    assert repo["binding"]["coverage"]["missing"] == 0
    assert actor["sample_size"] == 2
    assert actor["event_type_counts"]["values"]["pull_request_review"] == 0
    assert "exact actor_canonical_id" in " ".join(actor["limitations"])


def test_partial_forge_keeps_counts_but_withholds_cadence(tmp_path: Path) -> None:
    export = load_forge_export(
        _write(tmp_path / "forge-partial.json", _forge_payload(status="partial"))
    )
    observation = summarize_forge_export(export)
    rhythm = summarize_forge_rhythm(export)

    assert observation["sample_size"] == 3
    assert observation["interval_coverage"]["missing"] == 24
    assert rhythm["kind"] == "not_proven"
    assert rhythm["reason"] == "partial_source_coverage"
    assert rhythm["active_day_share"]["kind"] == "not_proven"


def test_tracker_bound_summary_uses_validated_state_chain_and_actor_exact(
    tmp_path: Path,
) -> None:
    export = load_tracker_export(_write(tmp_path / "tracker.json", _tracker_payload()))
    repo = summarize_tracker_export(export)
    actor = summarize_tracker_export(export, canonical_id="alice")

    assert repo["sample_size"] == 5
    assert repo["event_kind_counts"]["issue_triaged"] == 1
    assert repo["record_state_counts"] == {
        "issue.closed": 1,
        "issue.open": 2,
        "issue.triaged": 1,
        "milestone.active": 1,
    }
    metrics = repo["projects"]["project-42"]
    assert metrics["issue_created_to_in_progress_median_hours"]["value"] == 2.0
    assert metrics["issue_created_to_closed_median_hours"]["value"] == 3.0
    assert metrics["linked_issue_share"]["value"] == 1.0
    assert actor["sample_size"] == 4
    assert actor["event_kind_counts"]["issue_triaged"] == 0
    assert "exact actor_canonical_id" in " ".join(actor["limitations"])


def _mutated_tracker(name: str) -> dict[str, object]:
    payload = copy.deepcopy(_tracker_payload())
    events = payload["events"]
    assert isinstance(events, list)
    if name == "duplicate":
        events[-1]["event_id"] = "i-2"
    elif name == "missing":
        del events[-1]["state"]
    elif name == "nonfinite":
        events[-1]["duration_seconds"] = float("nan")
    elif name == "broken_link":
        events[2]["linked_event_id"] = "missing"
    elif name == "negative_duration":
        events[-1]["duration_seconds"] = -1
    elif name == "duration_mismatch":
        events[-1]["duration_seconds"] = 3599
    elif name == "out_of_order":
        events[-1]["timestamp"] = "2026-08-01T00:00:00Z"
    elif name == "state_mismatch":
        events[-1]["previous_state"] = "open"
    elif name == "cross_record":
        events[-1]["record_id"] = "issue-other"
    else:  # pragma: no cover - test helper guard
        raise AssertionError(name)
    return payload


@pytest.mark.parametrize(
    ("mutation", "needle"),
    (
        ("duplicate", "duplicate event_id"),
        ("missing", "state must be a non-empty string"),
        ("nonfinite", "finite"),
        ("broken_link", "broken (linked_event_id|link)"),
        ("negative_duration", "non-negative"),
        ("duration_mismatch", "timestamp difference"),
        ("out_of_order", "(out of order|in order)"),
        ("state_mismatch", "latest (record )?state"),
        ("cross_record", "missing an initial event"),
    ),
)
def test_tracker_v2_rejects_known_bad_state_inputs(
    tmp_path: Path, mutation: str, needle: str
) -> None:
    path = _write(tmp_path / f"tracker-{mutation}.json", _mutated_tracker(mutation))
    with pytest.raises(InputValidationError, match=needle):
        load_tracker_export(path)


def test_tracker_schema_and_stdlib_invariants_cross_check(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    payload = _tracker_payload()
    assert validate_schema("tracker-export-v2", payload) == []
    errors = list(
        jsonschema.Draft202012Validator(
            load_schema("tracker-export-v2"), format_checker=jsonschema.FormatChecker()
        ).iter_errors(payload)
    )
    assert errors == []

    broken = copy.deepcopy(payload)
    events = broken["events"]
    assert isinstance(events, list)
    events[-1]["previous_event_id"] = "missing"
    assert any(
        "previous_event_id" in error for error in validate_schema("tracker-export-v2", broken)
    )


def test_bound_report_fragments_require_binding_and_digest(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    forge = load_forge_export(_write(tmp_path / "forge-report.json", _forge_payload()))
    tracker = load_tracker_export(_write(tmp_path / "tracker-report.json", _tracker_payload()))
    cases = (
        ("report_event_observation", summarize_forge_export(forge)),
        ("report_tracker_lifecycle", summarize_tracker_export(tracker)),
    )
    for definition, payload in cases:
        schema = load_schema("report-v2")
        schema["$ref"] = f"#/$defs/{definition}"
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        assert list(validator.iter_errors(payload)) == []
        for required in ("binding", "digest"):
            mutated = copy.deepcopy(payload)
            del mutated[required]
            assert list(validator.iter_errors(mutated)), (definition, required)
