"""Local forge export loader. v1 is legacy; v2 is target-bound."""

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
from tep_core.version import FORGE_EXPORT_SCHEMA_VERSION

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORGE_EXPORT_V2 = "tep-forge-export-v2"
_EVENT_KINDS = frozenset(
    {
        "pull_request_review",
        "pull_request_opened",
        "pull_request_merged",
        "review_comment",
        "pull_request_lifecycle",
    }
)


@dataclass(frozen=True)
class ForgeEvent:
    event_id: str
    kind: str
    timestamp: str
    actor_canonical_id: str
    pr_number: int | None
    commit_sha: str | None


@dataclass(frozen=True)
class ForgeExport:
    schema_version: str
    provider: str
    events: tuple[ForgeEvent, ...]
    digest: str
    binding: SourceBinding | None = None


def _require_str(node: dict[str, Any], key: str, path: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value:
        raise InputValidationError(f"{path}: {key} must be a non-empty string")
    return value


def load_forge_export(path: Path) -> ForgeExport:
    raw = path.read_text(encoding="utf-8")
    assert_no_secrets(raw, source="forge-export")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputValidationError("forge-export: malformed JSON") from exc
    if not isinstance(data, dict):
        raise InputValidationError("forge-export: root must be an object")
    schema = data.get("schema_version")
    if schema not in {FORGE_EXPORT_SCHEMA_VERSION, FORGE_EXPORT_V2}:
        raise InputValidationError(
            "forge-export: schema_version must be tep-forge-export-v1 or tep-forge-export-v2"
        )
    binding: SourceBinding | None = None
    if schema == FORGE_EXPORT_V2:
        extra = set(data) - {"schema_version", "binding", "events"}
        if extra:
            raise InputValidationError(f"forge-export: unknown keys {sorted(extra)}")
        binding = parse_source_binding(data.get("binding"), source="forge-export")
        provider = binding.provider
    else:
        provider = _require_str(data, "provider", "forge-export")
    events_raw = data.get("events")
    if not isinstance(events_raw, list):
        raise InputValidationError("forge-export: events must be an array")
    events = tuple(
        _parse_event(item, index, binding=binding) for index, item in enumerate(events_raw)
    )
    ids = [item.event_id for item in events]
    if len(ids) != len(set(ids)):
        raise InputValidationError("forge-export: duplicate event_id")
    if schema == FORGE_EXPORT_V2:
        from tep_core.schema import validate_schema

        schema_errors = validate_schema("forge-export-v2", data)
        if schema_errors:
            raise InputValidationError(
                "forge-export: schema violation: " + "; ".join(schema_errors)
            )
    ordered = tuple(sorted(events, key=lambda item: (parse_iso_utc(item.timestamp), item.event_id)))
    from tep_core.digest import sha256_text

    return ForgeExport(
        schema_version=schema,
        provider=provider,
        events=ordered,
        digest=sha256_text(raw),
        binding=binding,
    )


def _parse_event(item: Any, index: int, *, binding: SourceBinding | None) -> ForgeEvent:
    path = f"forge-export.events[{index}]"
    if not isinstance(item, dict):
        raise InputValidationError(f"{path}: must be an object")
    if binding is not None:
        allowed = {
            "event_id",
            "kind",
            "timestamp",
            "actor_canonical_id",
            "pr_number",
            "commit_sha",
            "project_id",
            "project_path",
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
    pr_number = item.get("pr_number")
    if pr_number is not None and not (
        isinstance(pr_number, int) and not isinstance(pr_number, bool) and pr_number > 0
    ):
        raise InputValidationError(f"{path}: pr_number must be a positive integer or omitted")
    commit_sha = item.get("commit_sha")
    if commit_sha is not None:
        pattern = (
            _SHA_RE if binding is None or binding.target_oid.algorithm == "sha1" else _SHA256_RE
        )
        if not (isinstance(commit_sha, str) and pattern.fullmatch(commit_sha)):
            size = 40 if pattern is _SHA_RE else 64
            raise InputValidationError(f"{path}: commit_sha must be {size}-char lowercase hex")
    return ForgeEvent(
        event_id=event_id,
        kind=kind,
        timestamp=timestamp,
        actor_canonical_id=actor,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )


def summarize_forge_export(
    export: ForgeExport, *, canonical_id: str | None = None
) -> dict[str, Any]:
    """Summarize a target-bound provider-neutral forge export.

    Actor selection is an exact ``actor_canonical_id`` equality check.  The
    provider account and display handle are deliberately not join keys.
    Counts describe only rows present in the supplied export; the independently
    declared source coverage remains visible beside them.
    """

    binding = _bound_binding(export)
    events = _selected_events(export, canonical_id)
    by_day: Counter[str] = Counter(item.timestamp[:10] for item in events)
    by_kind: Counter[str] = Counter(item.kind for item in events)
    kind_counts = {name: int(by_kind.get(name, 0)) for name in sorted(_EVENT_KINDS)}
    ordered = [item.timestamp for item in events]
    first = (
        Observed(ordered[0], "timestamp").to_dict()
        if ordered
        else NotObserved("no_matching_events").to_dict()
    )
    last = (
        Observed(ordered[-1], "timestamp").to_dict()
        if ordered
        else NotObserved("no_matching_events").to_dict()
    )
    coverage = _coverage_payload(binding)
    selection_note = (
        "All provider-neutral events in the bound repository export are included."
        if canonical_id is None
        else "Only exact actor_canonical_id matches are included; names, emails, and provider handles are not inferred."
    )
    missing_note = (
        "Declared source coverage is partial; observed counts are lower bounds and absence is not proven."
        if binding.coverage.status == "partial"
        else "The submitter declared complete coverage for the bound source window."
    )
    return {
        "kind": "observed",
        "unit": "profile",
        "source_format": FORGE_EXPORT_V2,
        "digest": export.digest,
        "binding": source_binding_payload(binding),
        "sample_size": len(events),
        "population": len(events),
        "window": {"start": binding.window.start, "end": binding.window.end},
        "interval_coverage": coverage,
        "repository_event_counts": {
            "kind": "observed",
            "unit": "events",
            "values": {binding.project_path: len(events)},
        },
        "daily_event_counts": {
            "kind": "observed",
            "unit": "events",
            "values": dict(sorted(by_day.items())),
        },
        "event_type_counts": {
            "kind": "observed",
            "unit": "events",
            "values": kind_counts,
        },
        "active_utc_days": Observed(len(by_day), "days", sample_size=len(events)).to_dict(),
        "first_observed_event": first,
        "last_observed_event": last,
        "unknown_event_type_count": Observed(0, "events").to_dict(),
        "missing_event_types": [name for name, count in kind_counts.items() if count == 0],
        "duplicate_count": Observed(0, "events").to_dict(),
        "duplicate_rate": Observed(0.0, "ratio", sample_size=len(events)).to_dict(),
        "timezone_rules": ["normalized_to_utc"],
        "limitations": [
            selection_note,
            missing_note,
            "Event counts are not review quality, ability, productivity, or delivery speed.",
        ],
    }


def summarize_forge_rhythm(
    export: ForgeExport, *, canonical_id: str | None = None
) -> dict[str, Any]:
    """Compute within-export timing while withholding cadence for partial input."""

    binding = _bound_binding(export)
    events = _selected_events(export, canonical_id)
    coverage = _coverage_payload(binding)
    start = parse_iso_utc(binding.window.start)
    end = parse_iso_utc(binding.window.end)
    window_days = max(1, math.ceil((end - start).total_seconds() / 86400))
    base: dict[str, Any] = {
        "kind": "observed",
        "unit": "profile",
        "window_days": window_days,
        "sample_size": len(events),
        "population": window_days,
        "digest": export.digest,
        "timezone_rules": ["normalized_to_utc"],
        "interval_coverage": coverage,
        "limitations": [
            "Event gaps are not work duration, productivity, quality, or delivery speed.",
            "Actor filtering uses exact actor_canonical_id equality only.",
        ],
    }
    active_days = len({item.timestamp[:10] for item in events})
    if binding.coverage.status == "partial":
        base["kind"] = "not_proven"
        base["reason"] = "partial_source_coverage"
        base["active_day_share"] = {
            "kind": "not_proven",
            "reason": "partial_source_coverage",
            "n": active_days,
            "denominator": window_days,
        }
        base["limitations"].append(
            "Cadence and absence are withheld because declared source coverage is partial."
        )
        return base

    base["active_day_share"] = Observed(
        round(active_days / window_days, 4), "ratio", sample_size=window_days
    ).to_dict()
    base["active_day_share"].update({"n": active_days, "denominator": window_days})
    instants = [parse_iso_utc(item.timestamp) for item in events]
    _fill_bound_gaps(base, instants)
    _fill_bound_same_day(base, instants)
    base["release_interval_days"] = NotObserved("event_kind_not_collected").to_dict()
    base["shape_label"] = _bound_shape(instants, window_days=window_days)
    return base


def _bound_binding(export: ForgeExport) -> SourceBinding:
    if export.schema_version != FORGE_EXPORT_V2 or export.binding is None:
        raise InputValidationError("forge-export: target-bound v2 export is required")
    return export.binding


def _selected_events(export: ForgeExport, canonical_id: str | None) -> tuple[ForgeEvent, ...]:
    if canonical_id is None:
        return export.events
    return tuple(event for event in export.events if event.actor_canonical_id == canonical_id)


def _coverage_payload(binding: SourceBinding) -> dict[str, Any]:
    coverage = binding.coverage
    return {
        "kind": "observed",
        "unit": coverage.unit,
        "status": coverage.status,
        "observed": coverage.observed,
        "expected": coverage.expected,
        "missing": coverage.missing,
        "value": round(coverage.observed / coverage.expected, 12),
    }


def _fill_bound_gaps(payload: dict[str, Any], instants: list[datetime]) -> None:
    gaps = [(right - left).total_seconds() / 3600 for left, right in zip(instants, instants[1:])]
    if not gaps:
        payload["inter_event_gap_median_hours"] = NotObserved("fewer_than_two_events").to_dict()
        payload["inter_event_gap_iqr_hours"] = NotObserved("fewer_than_two_events").to_dict()
        return
    payload["inter_event_gap_median_hours"] = Observed(
        round(float(median(gaps)), 4), "hours", sample_size=len(gaps)
    ).to_dict()
    if len(gaps) < 4:
        payload["inter_event_gap_iqr_hours"] = {
            "kind": "not_observed",
            "reason": "insufficient_population",
            "population": len(gaps),
        }
        return
    ranked = sorted(gaps)
    lower = _quantile(ranked, 0.25)
    upper = _quantile(ranked, 0.75)
    payload["inter_event_gap_iqr_hours"] = Observed(
        round(upper - lower, 4), "hours", sample_size=len(gaps)
    ).to_dict()


def _quantile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _fill_bound_same_day(payload: dict[str, Any], instants: list[datetime]) -> None:
    if not instants:
        payload["same_day_event_share"] = NotObserved("no_events").to_dict()
        payload["burst_day_share"] = NotObserved("no_events").to_dict()
        return
    by_day = Counter(item.date().isoformat() for item in instants)
    multi = sum(1 for item in instants if by_day[item.date().isoformat()] > 1)
    payload["same_day_event_share"] = Observed(
        round(multi / len(instants), 4), "ratio", sample_size=len(instants)
    ).to_dict()
    counts = list(by_day.values())
    median_day = float(median(counts))
    burst_days = sum(1 for count in counts if count >= max(2, 2 * median_day))
    payload["burst_day_share"] = Observed(
        round(burst_days / len(counts), 4), "ratio", sample_size=len(counts)
    ).to_dict()


def _bound_shape(instants: list[datetime], *, window_days: int) -> dict[str, Any]:
    from tep_core.tendency import shape_or_unproven

    if not instants:
        return NotObserved("no_events").to_dict()
    by_day = Counter(item.date().isoformat() for item in instants)
    counts = list(by_day.values())
    median_day = float(median(counts))
    burst_days = sum(1 for count in counts if count >= max(2, 2 * median_day))
    label = "burst" if burst_days and burst_days / len(counts) >= 0.5 else "constant"
    return shape_or_unproven(len(by_day), len(instants), window_days, label)
