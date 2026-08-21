"""Activity-day metrics (TEP metric-design ruling 1, 2026-08-16)."""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, timedelta

from tep_core.observation import NotObserved, Observed

WINDOW_13W_DAYS = 13 * 7


def _parse_day(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def activity_metrics(
    tenant_dates: list[str],
    day_counts: Counter[str],
    *,
    head_date: str | None,
) -> dict[str, dict[str, object]]:
    tenant_commits = len(tenant_dates)
    payload: dict[str, dict[str, object]] = {
        "tenant_commits": Observed(tenant_commits, "commits").to_dict(),
    }
    unique_days = sorted(set(tenant_dates))
    active_days = len(unique_days)
    payload["active_days"] = Observed(active_days, "days").to_dict()

    if active_days == 0:
        payload["commits_per_active_day"] = NotObserved("no_tenant_active_days").to_dict()
        payload["commits_per_active_day_median"] = NotObserved("no_tenant_active_days").to_dict()
        payload["active_days_13w"] = Observed(0, "days").to_dict()
        return payload

    per_day = tenant_commits / active_days
    payload["commits_per_active_day"] = Observed(round(per_day, 4), "commits/active-day").to_dict()
    daily_values = [day_counts[d] for d in unique_days]
    payload["commits_per_active_day_median"] = Observed(
        statistics.median(daily_values),
        "commits/active-day",
        sample_size=len(daily_values),
    ).to_dict()

    if head_date:
        head = _parse_day(head_date)
        cut = head - timedelta(days=WINDOW_13W_DAYS)
        in_window = [d for d in unique_days if _parse_day(d) >= cut]
        payload["active_days_13w"] = Observed(len(in_window), "days").to_dict()
    else:
        payload["active_days_13w"] = NotObserved("head_date_unavailable").to_dict()
    return payload
