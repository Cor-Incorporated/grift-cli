"""GH Archive event-observation loader. No actor, no payload, no network."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tep_core.digest import sha256_bytes
from tep_core.observation import NotObserved, Observed
from tep_core.secrets_guard import InputValidationError

EVENT_TYPES = (
    "PushEvent",
    "IssuesEvent",
    "IssueCommentEvent",
    "PullRequestEvent",
    "PullRequestReviewEvent",
    "PullRequestReviewCommentEvent",
    "ReleaseEvent",
)
_ALLOWED_KEYS = {
    "event_id",
    "event_type",
    "occurred_at",
    "repository",
    "action",
    "ref",
    "object_number",
    "release_tag",
    "push_id",
}
_FORBIDDEN_KEYS = {"actor", "payload", "actor_id", "actor_login", "sender"}
DEFAULT_WINDOW_START = datetime(2024, 1, 15, tzinfo=timezone.utc)
DEFAULT_WINDOW_END = datetime(2024, 1, 22, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ArchiveEvent:
    event_id: str
    event_type: str
    occurred_at: str
    repository: str
    action: str | None
    timezone_rule: str


@dataclass(frozen=True)
class ArchiveBundle:
    events: tuple[ArchiveEvent, ...]
    digest: str
    window_start: str
    window_end: str
    duplicate_count: int
    duplicate_rate: float
    timezone_rules: tuple[str, ...]
    dropped_duplicate_ids: tuple[str, ...]
    observed_hours: int = 0
    expected_hours: int = 0
    missing_hours: int = 0
    coverage_rate: float = 0.0
    coverage_status: str = "unspecified"
    source_format: str = "event-observation-ndjson"


def _parse_occurred_at(value: str) -> tuple[datetime, str]:
    text = value.strip()
    if text.endswith("Z"):
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        return parsed.astimezone(timezone.utc), "utc_zulu"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise InputValidationError("occurred_at missing timezone; will not assume UTC")
    offset = parsed.utcoffset()
    utc = parsed.astimezone(timezone.utc)
    if offset is None or offset.total_seconds() == 0:
        return utc, "utc_offset"
    return utc, f"normalized_to_utc_from={parsed.tzinfo}"


def _parse_row(row: dict[str, Any], index: int) -> ArchiveEvent:
    path = f"archive[{index}]"
    for key in _FORBIDDEN_KEYS:
        if key in row:
            raise InputValidationError(f"{path}: {key} is not allowed")
    extra = set(row) - _ALLOWED_KEYS
    if extra:
        raise InputValidationError(f"{path}: unknown keys {sorted(extra)}")
    event_id = row.get("event_id")
    event_type = row.get("event_type")
    occurred_at = row.get("occurred_at")
    repository = row.get("repository")
    if not isinstance(event_id, str) or not event_id:
        raise InputValidationError(f"{path}: event_id required")
    if event_type not in EVENT_TYPES:
        raise InputValidationError(f"{path}: unknown_event_type:{event_type}")
    if not isinstance(occurred_at, str):
        raise InputValidationError(f"{path}: occurred_at required")
    if not isinstance(repository, str) or "/" not in repository:
        raise InputValidationError(f"{path}: repository must be owner/name")
    instant, rule = _parse_occurred_at(occurred_at)
    return ArchiveEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        repository=repository,
        action=row.get("action") if isinstance(row.get("action"), str) else None,
        timezone_rule=rule,
    )


def load_archive_events(
    path: Path,
    *,
    window_start: datetime = DEFAULT_WINDOW_START,
    window_end: datetime = DEFAULT_WINDOW_END,
    strict_window: bool = True,
    source_hours: Iterable[str] | None = None,
) -> ArchiveBundle:
    if window_start >= window_end:
        raise InputValidationError("archive: window_start must be earlier than window_end")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    events: list[ArchiveEvent] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    outside = 0
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputValidationError(f"archive[{index}]: malformed JSON") from exc
        if not isinstance(row, dict):
            raise InputValidationError(f"archive[{index}]: must be an object")
        item = _parse_row(row, index)
        instant = datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00"))
        if instant < window_start or instant >= window_end:
            outside += 1
            if strict_window:
                raise InputValidationError(
                    f"archive[{index}]: occurred_at outside event window "
                    f"({window_start.date().isoformat()} / {window_end.date().isoformat()})"
                )
            continue
        if item.event_id in seen:
            duplicates.append(item.event_id)
            continue
        seen.add(item.event_id)
        events.append(item)
    if not events:
        raise InputValidationError("archive: no events in window")
    total_read = len(events) + len(duplicates) + (0 if strict_window else outside)
    rate = (len(duplicates) / total_read) if total_read else 0.0
    rules = tuple(sorted({item.timezone_rule for item in events}))
    duration_hours = (window_end - window_start).total_seconds() / 3600
    if not duration_hours.is_integer():
        raise InputValidationError("archive: event window must contain whole UTC hours")
    expected_hours = int(duration_hours)
    if source_hours is None:
        observed_source_hours = {
            datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00")).strftime("%Y-%m-%d-%H")
            for item in events
        }
    else:
        observed_source_hours = {str(item) for item in source_hours}
    for value in observed_source_hours:
        try:
            instant = datetime.strptime(value, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise InputValidationError(f"archive: invalid source hour {value!r}") from exc
        if instant < window_start or instant >= window_end:
            raise InputValidationError(f"archive: source hour outside event window {value!r}")
    observed_hours = len(observed_source_hours)
    if observed_hours > expected_hours:
        raise InputValidationError("archive: observed source hours exceed expected window hours")
    missing_hours = expected_hours - observed_hours
    return ArchiveBundle(
        events=tuple(events),
        digest=sha256_bytes(raw),
        window_start=window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_end=window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duplicate_count=len(duplicates),
        duplicate_rate=round(rate, 4),
        timezone_rules=rules,
        dropped_duplicate_ids=tuple(duplicates),
        observed_hours=observed_hours,
        expected_hours=expected_hours,
        missing_hours=missing_hours,
        coverage_rate=round(observed_hours / expected_hours, 4),
        coverage_status="complete" if missing_hours == 0 else "partial",
    )


def summarize_archive(bundle: ArchiveBundle) -> dict[str, Any]:
    events = bundle.events
    by_repo: Counter[str] = Counter(item.repository for item in events)
    by_day: Counter[str] = Counter(item.occurred_at[:10] for item in events)
    by_type: Counter[str] = Counter(item.event_type for item in events)
    ordered = sorted(item.occurred_at for item in events)
    type_counts = {name: int(by_type.get(name, 0)) for name in EVENT_TYPES}
    missing_types = [name for name, count in type_counts.items() if count == 0]
    payload = {
        "kind": "observed",
        "unit": "profile",
        "source_format": bundle.source_format,
        "sample_size": len(events),
        "population": len(events),
        "window": {"start": bundle.window_start, "end": bundle.window_end},
        "interval_coverage": {
            "kind": "observed",
            "unit": "hours",
            "status": bundle.coverage_status,
            "observed": bundle.observed_hours,
            "expected": bundle.expected_hours,
            "missing": bundle.missing_hours,
            "value": bundle.coverage_rate,
        },
        "repository_event_counts": {
            "kind": "observed",
            "unit": "events",
            "values": dict(sorted(by_repo.items())),
        },
        "daily_event_counts": {
            "kind": "observed",
            "unit": "events",
            "values": dict(sorted(by_day.items())),
        },
        "event_type_counts": {
            "kind": "observed",
            "unit": "events",
            "values": type_counts,
        },
        "active_utc_days": Observed(len(by_day), "days", sample_size=len(events)).to_dict(),
        "first_observed_event": Observed(ordered[0], "timestamp").to_dict(),
        "last_observed_event": Observed(ordered[-1], "timestamp").to_dict(),
        "unknown_event_type_count": Observed(0, "events").to_dict(),
        "missing_event_types": missing_types,
        "duplicate_count": Observed(bundle.duplicate_count, "events").to_dict(),
        "duplicate_rate": Observed(
            bundle.duplicate_rate, "ratio", sample_size=len(events)
        ).to_dict(),
        "timezone_rules": list(bundle.timezone_rules),
        "limitations": [
            "Public GitHub events for the declared window only.",
            "Actor login, actor id, and raw payload are not present.",
            "Push timestamps are not DORA change lead time.",
            "Review events are not review quality or PM suitability.",
            (
                f"Partial source-hour coverage: {bundle.observed_hours}/{bundle.expected_hours} "
                "hours; absence and cadence metrics are not observed."
                if bundle.coverage_status == "partial"
                else "All declared source hours are present."
            ),
        ],
    }
    if len(by_repo) > 1:
        payload["collection_kind"] = "multi_repository_benchmark"
        payload["repository_profiles"] = {
            repository: _repository_profile(bundle, repository) for repository in sorted(by_repo)
        }
        payload["limitations"].append(
            "Repository event series are computed separately; no cross-repository cadence is emitted."
        )
    return payload


def _repository_profile(bundle: ArchiveBundle, repository: str) -> dict[str, Any]:
    events = [item for item in bundle.events if item.repository == repository]
    by_day: Counter[str] = Counter(item.occurred_at[:10] for item in events)
    by_type: Counter[str] = Counter(item.event_type for item in events)
    return {
        "kind": "observed",
        "unit": "profile",
        "sample_size": len(events),
        "active_utc_days": len(by_day),
        "event_type_counts": dict(sorted(by_type.items())),
        "coverage_status": bundle.coverage_status,
        "cadence": (
            {"kind": "not_observed", "reason": "partial_hour_coverage"}
            if bundle.coverage_status == "partial"
            else {"kind": "observed", "unit": "events", "value": len(events)}
        ),
    }


def archive_for_repository(bundle: ArchiveBundle, repository: str) -> ArchiveBundle:
    events = tuple(item for item in bundle.events if item.repository == repository)
    if not events:
        raise InputValidationError(f"archive: repository not present: {repository}")
    return ArchiveBundle(
        events=events,
        digest=sha256_bytes(
            (bundle.digest + "\0" + repository + "\0" + str(len(events))).encode("utf-8")
        ),
        window_start=bundle.window_start,
        window_end=bundle.window_end,
        duplicate_count=0,
        duplicate_rate=0.0,
        timezone_rules=tuple(sorted({item.timezone_rule for item in events})),
        dropped_duplicate_ids=(),
        observed_hours=bundle.observed_hours,
        expected_hours=bundle.expected_hours,
        missing_hours=bundle.missing_hours,
        coverage_rate=bundle.coverage_rate,
        coverage_status=bundle.coverage_status,
        source_format=bundle.source_format,
    )


def empty_event_observation(reason: str) -> dict[str, Any]:
    payload = NotObserved(reason).to_dict()
    payload["limitations"] = ["Forge/event input was not provided; this is not zero events."]
    return payload
