"""Event-sequence rhythm. Observational labels only — not speed or quality."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from statistics import median
from typing import Any

from tep_core.archive_events import ArchiveEvent, ArchiveBundle, archive_for_repository
from tep_core.digest import sha256_text
from tep_core.observation import NotObserved, Observed

_BURST_LABEL = "burst"
_CONSTANT_LABEL = "constant"


def _hours(left: datetime, right: datetime) -> float:
    return (right - left).total_seconds() / 3600.0


def _quantile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return round(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight, 4)


def event_rhythm(
    bundle: ArchiveBundle,
    *,
    window_days: int | None = None,
) -> dict[str, Any]:
    events = bundle.events
    repositories = sorted({item.repository for item in events})
    if len(repositories) > 1:
        return {
            "kind": "not_proven",
            "reason": "mixed_repository_collection",
            "unit": "profile",
            "sample_size": len(events),
            "interval_coverage": _coverage_node(bundle),
            "active_day_share": {
                "kind": "not_observed",
                "reason": "mixed_repository_collection",
                "denominator": max(1, bundle.expected_hours // 24),
            },
            "repositories": {
                repository: event_rhythm(archive_for_repository(bundle, repository))
                for repository in repositories
            },
            "limitations": [
                "Cadence is computed per repository; no cross-repository interval is emitted."
            ],
        }
    instants = [datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00")) for item in events]
    ordered = sorted(instants)
    start = datetime.fromisoformat(bundle.window_start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(bundle.window_end.replace("Z", "+00:00"))
    span_days = max(1, int(round((end - start).total_seconds() / 86400)))
    days = window_days if window_days is not None else span_days
    by_day = Counter(item.date() for item in ordered)
    active = len(by_day)
    digest = sha256_text(f"{days}|{bundle.digest}|{len(events)}")
    payload: dict[str, Any] = {
        "kind": "observed",
        "unit": "profile",
        "window_days": days,
        "sample_size": len(events),
        "population": days,
        "digest": digest,
        "timezone_rules": list(bundle.timezone_rules),
        "interval_coverage": _coverage_node(bundle),
        "limitations": [
            "Event gaps are not work duration, productivity, or delivery speed.",
            "Push time is not DORA change lead time.",
            "constant/burst are observational concentration labels, not quality.",
        ],
    }
    if bundle.coverage_status == "partial":
        reason = "partial_hour_coverage"
        active = len({item.date() for item in ordered})
        payload["active_day_share"] = {
            "kind": "not_observed",
            "reason": reason,
            "n": active,
            "denominator": days,
        }
        for key in (
            "inter_event_gap_median_hours",
            "inter_event_gap_iqr_hours",
            "same_day_event_share",
            "burst_day_share",
            "release_interval_days",
            "shape_label",
        ):
            payload[key] = {"kind": "not_observed", "reason": reason}
        payload["limitations"].append(
            f"Only {bundle.observed_hours}/{bundle.expected_hours} source hours are present; "
            "absence and cadence values are withheld."
        )
        return payload
    payload["active_day_share"] = Observed(
        round(active / days, 4), "ratio", sample_size=days
    ).to_dict()
    payload["active_day_share"]["denominator"] = days
    payload["active_day_share"]["n"] = active
    _fill_gaps(payload, ordered)
    _fill_same_day(payload, events, by_day)
    _fill_releases(payload, events)
    payload["shape_label"] = _shape_label(by_day, event_count=len(events), window_days=days)
    return payload


def _coverage_node(bundle: ArchiveBundle) -> dict[str, Any]:
    if bundle.coverage_status == "unspecified":
        return {"kind": "not_observed", "reason": "source_hour_coverage_unspecified"}
    return {
        "kind": "observed",
        "unit": "hours",
        "status": bundle.coverage_status,
        "observed": bundle.observed_hours,
        "expected": bundle.expected_hours,
        "missing": bundle.missing_hours,
        "value": bundle.coverage_rate,
    }


def _fill_gaps(payload: dict[str, Any], ordered: list[datetime]) -> None:
    gaps = [_hours(ordered[index], ordered[index + 1]) for index in range(len(ordered) - 1)]
    if len(gaps) < 1:
        payload["inter_event_gap_median_hours"] = NotObserved("fewer_than_two_events").to_dict()
        payload["inter_event_gap_iqr_hours"] = NotObserved("fewer_than_two_events").to_dict()
        return
    payload["inter_event_gap_median_hours"] = Observed(
        round(float(median(gaps)), 4),
        "hours",
        sample_size=len(gaps),
    ).to_dict()
    if len(gaps) < 4:
        payload["inter_event_gap_iqr_hours"] = NotObserved("insufficient_population").to_dict()
        payload["inter_event_gap_iqr_hours"]["population"] = len(gaps)
        return
    ranked = sorted(gaps)
    payload["inter_event_gap_iqr_hours"] = Observed(
        round(_quantile(ranked, 0.75) - _quantile(ranked, 0.25), 4),
        "hours",
        sample_size=len(gaps),
    ).to_dict()


def _fill_same_day(
    payload: dict[str, Any], events: tuple[ArchiveEvent, ...], by_day: Counter
) -> None:
    if not events:
        payload["same_day_event_share"] = NotObserved("fewer_than_one_event").to_dict()
        payload["burst_day_share"] = NotObserved("fewer_than_one_event").to_dict()
        return
    multi = sum(
        1
        for item in events
        if by_day[datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00")).date()] > 1
    )
    payload["same_day_event_share"] = Observed(
        round(multi / len(events), 4), "ratio", sample_size=len(events)
    ).to_dict()
    counts = list(by_day.values())
    median_day = sorted(counts)[len(counts) // 2]
    burst_days = sum(1 for count in counts if count >= 2 and count >= max(2, 2 * median_day))
    payload["burst_day_share"] = Observed(
        round(burst_days / len(counts), 4), "ratio", sample_size=len(counts)
    ).to_dict()


def _fill_releases(payload: dict[str, Any], events: tuple[ArchiveEvent, ...]) -> None:
    releases = sorted(
        datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00"))
        for item in events
        if item.event_type == "ReleaseEvent"
    )
    if len(releases) < 2:
        node = {"kind": "not_proven", "reason": "fewer_than_two_releases", "n": len(releases)}
        payload["release_interval_days"] = node
        return
    gaps = [
        (releases[index + 1] - releases[index]).total_seconds() / 86400
        for index in range(len(releases) - 1)
    ]
    payload["release_interval_days"] = Observed(
        round(sorted(gaps)[len(gaps) // 2], 4), "days", sample_size=len(gaps)
    ).to_dict()


def _shape_label(by_day: Counter, *, event_count: int, window_days: int) -> dict[str, Any]:
    from tep_core.tendency import shape_or_unproven

    if not by_day:
        return {"kind": "not_observed", "reason": "no_events"}
    counts = list(by_day.values())
    median_day = sorted(counts)[len(counts) // 2]
    burst_days = sum(1 for count in counts if count >= max(2, 2 * median_day))
    label = _BURST_LABEL if burst_days and burst_days / len(counts) >= 0.5 else _CONSTANT_LABEL
    return shape_or_unproven(len(by_day), event_count, window_days, label)


def empty_event_rhythm(reason: str) -> dict[str, Any]:
    payload = NotObserved(reason).to_dict()
    payload["limitations"] = ["Event rhythm is not observed; this is not a zero-speed project."]
    return payload
