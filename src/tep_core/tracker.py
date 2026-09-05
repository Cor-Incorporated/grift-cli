"""Local tracker export loader. v1 is legacy; v2 is target-bound."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from tep_core.dates import parse_iso_utc
from tep_core.identity import CANONICAL_ID_RE
from tep_core.observation import NotObserved, Observed
from tep_core.secrets_guard import InputValidationError, assert_no_secrets
from tep_core.source_binding import (
    SourceBinding,
    assert_event_project,
    event_in_window,
    parse_source_binding,
    source_binding_payload,
)
from tep_core.version import TRACKER_EXPORT_SCHEMA_VERSION

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRACKER_EXPORT_V2 = "tep-tracker-export-v2"
_EVENT_KINDS = frozenset(
    {
        "issue_linked",
        "issue_opened",
        "issue_closed",
        "issue_triaged",
        "milestone_set",
        "milestone_closed",
    }
)
_RECORD_TYPES = frozenset({"issue", "milestone"})
_ISSUE_STATES = frozenset({"open", "triaged", "closed"})
_MILESTONE_STATES = frozenset({"active", "closed"})


@dataclass(frozen=True)
class TrackerEvent:
    event_id: str
    kind: str
    timestamp: str
    actor_canonical_id: str
    issue_number: int | None
    commit_sha: str | None
    record_type: str | None = None
    record_id: str | None = None
    state: str | None = None
    previous_state: str | None = None
    previous_event_id: str | None = None
    linked_event_id: str | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class TrackerExport:
    schema_version: str
    provider: str
    events: tuple[TrackerEvent, ...]
    digest: str
    binding: SourceBinding | None = None


def _require_str(node: dict[str, Any], key: str, path: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value:
        raise InputValidationError(f"{path}: {key} must be a non-empty string")
    return value


def load_tracker_export(path: Path) -> TrackerExport:
    raw = path.read_text(encoding="utf-8")
    assert_no_secrets(raw, source="tracker-export")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputValidationError("tracker-export: malformed JSON") from exc
    if not isinstance(data, dict):
        raise InputValidationError("tracker-export: root must be an object")
    schema = data.get("schema_version")
    if schema not in {TRACKER_EXPORT_SCHEMA_VERSION, TRACKER_EXPORT_V2}:
        raise InputValidationError(
            "tracker-export: schema_version must be tep-tracker-export-v1 or tep-tracker-export-v2"
        )
    binding: SourceBinding | None = None
    if schema == TRACKER_EXPORT_V2:
        extra = set(data) - {"schema_version", "binding", "events"}
        if extra:
            raise InputValidationError(f"tracker-export: unknown keys {sorted(extra)}")
        binding = parse_source_binding(data.get("binding"), source="tracker-export")
        provider = binding.provider
    else:
        provider = _require_str(data, "provider", "tracker-export")
    events_raw = data.get("events")
    if not isinstance(events_raw, list):
        raise InputValidationError("tracker-export: events must be an array")
    events = tuple(
        _parse_event(item, index, binding=binding) for index, item in enumerate(events_raw)
    )
    ids = [item.event_id for item in events]
    if len(ids) != len(set(ids)):
        raise InputValidationError("tracker-export: duplicate event_id")
    if schema == TRACKER_EXPORT_V2:
        from tep_core.schema import validate_schema

        schema_errors = validate_schema("tracker-export-v2", data)
        if schema_errors:
            raise InputValidationError(
                "tracker-export: schema violation: " + "; ".join(schema_errors)
            )
    if schema == TRACKER_EXPORT_V2:
        _validate_v2_sequence(events)
        ordered = events
    else:
        ordered = tuple(
            sorted(events, key=lambda item: (parse_iso_utc(item.timestamp), item.event_id))
        )
    from tep_core.digest import sha256_text

    return TrackerExport(
        schema_version=schema,
        provider=provider,
        events=ordered,
        digest=sha256_text(raw),
        binding=binding,
    )


def _parse_event(item: Any, index: int, *, binding: SourceBinding | None) -> TrackerEvent:
    path = f"tracker-export.events[{index}]"
    if not isinstance(item, dict):
        raise InputValidationError(f"{path}: must be an object")
    if binding is not None:
        allowed = {
            "event_id",
            "kind",
            "timestamp",
            "actor_canonical_id",
            "issue_number",
            "commit_sha",
            "project_id",
            "project_path",
            "record_type",
            "record_id",
            "state",
            "previous_state",
            "previous_event_id",
            "linked_event_id",
            "duration_seconds",
        }
        extra = set(item) - allowed
        if extra:
            raise InputValidationError(f"{path}: unknown keys {sorted(extra)}")
        assert_event_project(item, binding, path=path)
    event_id = _require_str(item, "event_id", path)
    if binding is not None and event_id != event_id.strip():
        raise InputValidationError(f"{path}: event_id must not contain surrounding whitespace")
    kind = _require_str(item, "kind", path)
    if kind not in _EVENT_KINDS:
        raise InputValidationError(f"{path}: unknown kind")
    timestamp = _require_str(item, "timestamp", path)
    try:
        instant = parse_iso_utc(timestamp)
    except ValueError as exc:
        raise InputValidationError(f"{path}: timestamp must be ISO-8601") from exc
    if binding is not None:
        event_in_window(timestamp, binding, path=f"{path}.timestamp")
        timestamp = instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    actor = _require_str(item, "actor_canonical_id", path)
    if not CANONICAL_ID_RE.fullmatch(actor):
        raise InputValidationError(f"{path}: actor_canonical_id is invalid")
    issue_number = item.get("issue_number")
    if issue_number is not None and not (
        isinstance(issue_number, int) and not isinstance(issue_number, bool) and issue_number > 0
    ):
        raise InputValidationError(f"{path}: issue_number must be a positive integer or omitted")
    commit_sha = item.get("commit_sha")
    if commit_sha is not None:
        pattern = (
            _SHA_RE if binding is None or binding.target_oid.algorithm == "sha1" else _SHA256_RE
        )
        if not (isinstance(commit_sha, str) and pattern.fullmatch(commit_sha)):
            size = 40 if pattern is _SHA_RE else 64
            raise InputValidationError(f"{path}: commit_sha must be {size}-char lowercase hex")
    record_type: str | None = None
    record_id: str | None = None
    state: str | None = None
    previous_state: str | None = None
    previous_event_id: str | None = None
    linked_event_id: str | None = None
    duration_seconds: float | None = None
    if binding is not None:
        record_type = _require_str(item, "record_type", path)
        record_id = _require_str(item, "record_id", path)
        if record_id != record_id.strip():
            raise InputValidationError(f"{path}: record_id must not contain surrounding whitespace")
        state = _require_str(item, "state", path)
        if record_type not in _RECORD_TYPES:
            raise InputValidationError(f"{path}: record_type is invalid")
        allowed_states = _ISSUE_STATES if record_type == "issue" else _MILESTONE_STATES
        if state not in allowed_states:
            raise InputValidationError(f"{path}: state is invalid for {record_type}")
        previous_state = _optional_str(item, "previous_state", path)
        previous_event_id = _optional_str(item, "previous_event_id", path)
        linked_event_id = _optional_str(item, "linked_event_id", path)
        raw_duration = item.get("duration_seconds")
        if raw_duration is not None:
            if (
                isinstance(raw_duration, bool)
                or not isinstance(raw_duration, (int, float))
                or not math.isfinite(float(raw_duration))
            ):
                raise InputValidationError(f"{path}: duration_seconds must be finite")
            if raw_duration < 0:
                raise InputValidationError(f"{path}: duration_seconds must be non-negative")
            duration_seconds = float(raw_duration)
    return TrackerEvent(
        event_id=event_id,
        kind=kind,
        timestamp=timestamp,
        actor_canonical_id=actor,
        issue_number=issue_number,
        commit_sha=commit_sha,
        record_type=record_type,
        record_id=record_id,
        state=state,
        previous_state=previous_state,
        previous_event_id=previous_event_id,
        linked_event_id=linked_event_id,
        duration_seconds=duration_seconds,
    )


def _optional_str(item: dict[str, Any], key: str, path: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise InputValidationError(f"{path}: {key} must be a non-empty string or null")
    if value != value.strip():
        raise InputValidationError(f"{path}: {key} must not contain surrounding whitespace")
    return value


def _validate_v2_sequence(events: tuple[TrackerEvent, ...]) -> None:
    instants = [parse_iso_utc(event.timestamp) for event in events]
    if any(right < left for left, right in zip(instants, instants[1:])):
        raise InputValidationError("tracker-export: event timestamps are out of order")
    by_id = {event.event_id: event for event in events}
    position = {event.event_id: index for index, event in enumerate(events)}
    latest_state_event: dict[tuple[str, str], TrackerEvent] = {}
    successor_by_id: dict[str, str] = {}

    for index, event in enumerate(events):
        path = f"tracker-export.events[{index}]"
        assert event.record_type is not None
        assert event.record_id is not None
        assert event.state is not None
        key = (event.record_type, event.record_id)
        previous = latest_state_event.get(key)

        if event.kind != "issue_linked" and event.linked_event_id is not None:
            raise InputValidationError(f"{path}: linked_event_id is only allowed for issue_linked")

        if event.kind == "issue_opened":
            _require_initial_event(event, previous, path=path, record_type="issue", state="open")
            latest_state_event[key] = event
        elif event.kind == "milestone_set":
            _require_initial_event(
                event, previous, path=path, record_type="milestone", state="active"
            )
            latest_state_event[key] = event
        elif event.kind == "issue_triaged":
            _require_transition(
                event,
                previous,
                path=path,
                record_type="issue",
                state="triaged",
                allowed_previous=frozenset({"open"}),
                by_id=by_id,
                position=position,
                successor_by_id=successor_by_id,
            )
            latest_state_event[key] = event
        elif event.kind == "issue_closed":
            _require_transition(
                event,
                previous,
                path=path,
                record_type="issue",
                state="closed",
                allowed_previous=frozenset({"open", "triaged"}),
                by_id=by_id,
                position=position,
                successor_by_id=successor_by_id,
            )
            latest_state_event[key] = event
        elif event.kind == "milestone_closed":
            _require_transition(
                event,
                previous,
                path=path,
                record_type="milestone",
                state="closed",
                allowed_previous=frozenset({"active"}),
                by_id=by_id,
                position=position,
                successor_by_id=successor_by_id,
            )
            latest_state_event[key] = event
        else:
            _require_link_event(
                event,
                previous,
                path=path,
                by_id=by_id,
                position=position,
            )


def _require_initial_event(
    event: TrackerEvent,
    previous: TrackerEvent | None,
    *,
    path: str,
    record_type: str,
    state: str,
) -> None:
    if event.record_type != record_type or event.state != state:
        raise InputValidationError(f"{path}: kind/state/record_type mismatch")
    if previous is not None:
        raise InputValidationError(f"{path}: duplicate initial state for record_id")
    if any(
        value is not None
        for value in (event.previous_state, event.previous_event_id, event.duration_seconds)
    ):
        raise InputValidationError(f"{path}: initial state cannot declare a predecessor")


def _require_transition(
    event: TrackerEvent,
    previous: TrackerEvent | None,
    *,
    path: str,
    record_type: str,
    state: str,
    allowed_previous: frozenset[str],
    by_id: dict[str, TrackerEvent],
    position: dict[str, int],
    successor_by_id: dict[str, str],
) -> None:
    if event.record_type != record_type or event.state != state:
        raise InputValidationError(f"{path}: kind/state/record_type mismatch")
    if previous is None:
        raise InputValidationError(f"{path}: state transition is missing an initial event")
    if event.previous_state not in allowed_previous:
        raise InputValidationError(f"{path}: previous_state is inconsistent with transition")
    if event.previous_state != previous.state or event.previous_event_id != previous.event_id:
        raise InputValidationError(f"{path}: transition does not reference the latest record state")
    if event.duration_seconds is None:
        raise InputValidationError(f"{path}: transition requires duration_seconds")
    _validate_predecessor(event, path=path, by_id=by_id, position=position)
    prior_successor = successor_by_id.get(previous.event_id)
    if prior_successor is not None:
        raise InputValidationError(
            f"{path}: previous_event_id already has successor {prior_successor}"
        )
    successor_by_id[previous.event_id] = event.event_id


def _require_link_event(
    event: TrackerEvent,
    previous: TrackerEvent | None,
    *,
    path: str,
    by_id: dict[str, TrackerEvent],
    position: dict[str, int],
) -> None:
    if event.kind != "issue_linked" or event.record_type != "issue":
        raise InputValidationError(f"{path}: kind/state/record_type mismatch")
    if previous is None:
        raise InputValidationError(f"{path}: issue_linked is missing an issue state")
    if (
        event.previous_event_id != previous.event_id
        or event.previous_state != previous.state
        or event.state != previous.state
    ):
        raise InputValidationError(f"{path}: issue_linked state is inconsistent")
    if event.state not in {"open", "triaged"}:
        raise InputValidationError(f"{path}: a closed issue cannot be linked")
    if event.duration_seconds is None:
        raise InputValidationError(f"{path}: issue_linked requires duration_seconds")
    _validate_predecessor(event, path=path, by_id=by_id, position=position)
    if event.linked_event_id is None:
        raise InputValidationError(f"{path}: issue_linked requires linked_event_id")
    target = _validate_link_target(event, path=path, by_id=by_id, position=position)
    if target.record_type != "milestone" or target.state != "active":
        raise InputValidationError(f"{path}: issue_linked target must be an active milestone event")


def _validate_predecessor(
    event: TrackerEvent,
    *,
    path: str,
    by_id: dict[str, TrackerEvent],
    position: dict[str, int],
) -> None:
    previous_id = event.previous_event_id
    if previous_id is None or previous_id not in by_id:
        raise InputValidationError(f"{path}: broken previous_event_id")
    previous = by_id[previous_id]
    if position[previous.event_id] >= position[event.event_id]:
        raise InputValidationError(f"{path}: previous_event_id must reference an earlier event")
    if (previous.record_type, previous.record_id) != (event.record_type, event.record_id):
        raise InputValidationError(f"{path}: previous_event_id crosses tracker records")
    elapsed = (parse_iso_utc(event.timestamp) - parse_iso_utc(previous.timestamp)).total_seconds()
    if elapsed < 0:
        raise InputValidationError(f"{path}: negative transition duration")
    if not math.isclose(float(event.duration_seconds), elapsed, rel_tol=0.0, abs_tol=1e-6):
        raise InputValidationError(f"{path}: duration_seconds does not match timestamp difference")


def _validate_link_target(
    event: TrackerEvent,
    *,
    path: str,
    by_id: dict[str, TrackerEvent],
    position: dict[str, int],
) -> TrackerEvent:
    linked_id = event.linked_event_id
    if linked_id is None or linked_id not in by_id:
        raise InputValidationError(f"{path}: broken linked_event_id")
    target = by_id[linked_id]
    if target.event_id == event.event_id or position[target.event_id] >= position[event.event_id]:
        raise InputValidationError(f"{path}: linked_event_id must reference an earlier event")
    return target


def summarize_tracker_export(
    export: TrackerExport, *, canonical_id: str | None = None
) -> dict[str, Any]:
    """Summarize validated v2 tracker events without provider-specific inference."""

    if export.schema_version != TRACKER_EXPORT_V2 or export.binding is None:
        raise InputValidationError("tracker-export: target-bound v2 export is required")
    binding = export.binding
    events = (
        export.events
        if canonical_id is None
        else tuple(event for event in export.events if event.actor_canonical_id == canonical_id)
    )
    by_kind = {name: 0 for name in sorted(_EVENT_KINDS)}
    for event in events:
        by_kind[event.kind] += 1
    states = Counter(f"{event.record_type}.{event.state}" for event in events)
    active_days = len({event.timestamp[:10] for event in events})
    issue_ids = {
        event.record_id for event in events if event.record_type == "issue" and event.record_id
    }
    linked_issue_ids = {
        event.record_id for event in events if event.kind == "issue_linked" and event.record_id
    }
    started = {
        (event.record_type, event.record_id): parse_iso_utc(event.timestamp)
        for event in export.events
        if event.kind in {"issue_opened", "milestone_set"}
    }
    triage_hours = _elapsed_from_start(events, started, "issue_triaged")
    close_hours = _elapsed_from_start(events, started, "issue_closed")
    coverage = binding.coverage
    first = (
        Observed(events[0].timestamp, "timestamp").to_dict()
        if events
        else NotObserved("no_matching_events").to_dict()
    )
    last = (
        Observed(events[-1].timestamp, "timestamp").to_dict()
        if events
        else NotObserved("no_matching_events").to_dict()
    )
    linked_share: dict[str, Any]
    if coverage.status == "partial":
        linked_share = {
            "kind": "not_proven",
            "reason": "partial_source_coverage",
            "n": len(linked_issue_ids),
            "denominator": len(issue_ids),
        }
    else:
        linked_share = Observed(
            round(len(linked_issue_ids) / len(issue_ids), 4) if issue_ids else 0.0,
            "ratio",
            sample_size=len(issue_ids),
        ).to_dict()
        linked_share.update({"n": len(linked_issue_ids), "denominator": len(issue_ids)})
    project_metrics = {
        "active_days": Observed(active_days, "days", sample_size=len(events)).to_dict(),
        "issue_created_to_in_progress_median_hours": _maybe_hours(triage_hours),
        "issue_created_to_closed_median_hours": _maybe_hours(close_hours),
        "pr_created_to_first_review_median_hours": NotObserved(
            "event_kind_not_collected"
        ).to_dict(),
        "pr_created_to_merged_median_hours": NotObserved("event_kind_not_collected").to_dict(),
        "release_count": NotObserved("event_kind_not_collected").to_dict(),
        "release_interval_days": NotObserved("event_kind_not_collected").to_dict(),
        "linked_issue_share": linked_share,
        "linked_pr_share": NotObserved("event_kind_not_collected").to_dict(),
        "issue_to_close_median_hours": round(float(median(close_hours)), 4)
        if close_hours
        else None,
        "pr_to_merge_median_hours": None,
    }
    selection_note = (
        "All provider-neutral events in the bound tracker export are included."
        if canonical_id is None
        else "Only exact actor_canonical_id matches are included; provider handles and names are not inferred."
    )
    missing_note = (
        "Declared source coverage is partial; counts are lower bounds and absence/share values are not proven."
        if coverage.status == "partial"
        else "The submitter declared complete coverage for the bound source window."
    )
    actor_duration_note = (
        [
            "Actor lifecycle durations select the Actor's transition event but may span events emitted by other Actors."
        ]
        if canonical_id is not None
        else []
    )
    return {
        "kind": "observed",
        "unit": "profile",
        "source_format": TRACKER_EXPORT_V2,
        "digest": export.digest,
        "binding": source_binding_payload(binding),
        "sample_size": len(events),
        "coverage_status": coverage.status,
        "window": {"start": binding.window.start, "end": binding.window.end},
        "event_kind_counts": by_kind,
        "record_state_counts": dict(sorted(states.items())),
        "active_utc_days": Observed(active_days, "days", sample_size=len(events)).to_dict(),
        "first_observed_event": first,
        "last_observed_event": last,
        "projects": {binding.project_id: project_metrics},
        "limitations": [
            selection_note,
            missing_note,
            *actor_duration_note,
            "Durations are event timestamp differences, not work time, ability, or delivery speed.",
        ],
    }


def _elapsed_from_start(
    events: tuple[TrackerEvent, ...],
    started: dict[tuple[str | None, str | None], datetime],
    kind: str,
) -> list[float]:
    values: list[float] = []
    for event in events:
        if event.kind != kind:
            continue
        start = started.get((event.record_type, event.record_id))
        if start is not None:
            values.append((parse_iso_utc(event.timestamp) - start).total_seconds() / 3600)
    return values


def _maybe_hours(values: list[float]) -> dict[str, Any]:
    if not values:
        return NotObserved("timestamp_absent").to_dict()
    return Observed(round(float(median(values)), 4), "hours", sample_size=len(values)).to_dict()
