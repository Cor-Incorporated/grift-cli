"""Core activity period and activity-day metrics."""

from __future__ import annotations

from collections import Counter

from tep_core.activity import activity_metrics
from tep_core.core_period import CORE_ACTIVITY_MIN_SHARE, compute_core_activity_period


def test_core_period_single_burst() -> None:
    dates: list[str] = []
    for month in (9, 10, 11, 12):
        for day in range(1, 22):
            dates.append(f"2025-{month:02d}-{day:02d}")
    for day in range(1, 14):
        dates.append(f"2026-03-{day:02d}")
    period = compute_core_activity_period(dates)
    assert period["kind"] == "observed"
    assert period["start"] == "2025-09"
    assert period["end"] == "2025-12"
    assert period["share"] >= CORE_ACTIVITY_MIN_SHARE
    assert period["share"] <= 0.88
    assert "definition_version" in period
    assert period["unit"] == "month-range"


def test_core_period_empty_is_not_observed() -> None:
    period = compute_core_activity_period([])
    assert period["kind"] == "not_observed"
    assert period["reason"] == "no_tenant_commits"


def test_activity_zero_days_not_a_rate() -> None:
    metrics = activity_metrics([], Counter(), head_date="2026-08-21")
    assert metrics["tenant_commits"] == {
        "kind": "observed",
        "value": 0,
        "unit": "commits",
    }
    assert metrics["active_days"]["value"] == 0
    assert metrics["commits_per_active_day"]["kind"] == "not_observed"
