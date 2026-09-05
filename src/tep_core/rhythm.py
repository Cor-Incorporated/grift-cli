"""Change-submission intervals from Git author timestamps. Not labor time."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from tep_core.dates import parse_day, parse_iso_utc
from tep_core.gitutil import GitCommit
from tep_core.observation import NotObserved, Observed
from tep_core.v2_constants import (
    MIN_POPULATION_FOR_RATES,
    RHYTHM_LIMITATION,
    RHYTHM_TIMESTAMP_LIMITATIONS,
    RHYTHM_WINDOW_DAYS,
    RHYTHM_WINDOW_NOTE,
)
from tep_core.version import RHYTHM_DEFINITION_VERSION

TIMESTAMP_BASIS = "git_author_timestamp"


def commit_timestamp(commit: GitCommit) -> datetime:
    if commit.author_iso:
        return parse_iso_utc(commit.author_iso)
    return datetime(*parse_day(commit.date).timetuple()[:3], 12, 0, 0, tzinfo=timezone.utc)


def ordered_commits(commits: list[GitCommit]) -> list[GitCommit]:
    return sorted(commits, key=lambda item: (commit_timestamp(item), item.sha))


def _gaps(ordered: list[GitCommit]) -> list[float]:
    gaps: list[float] = []
    for left, right in zip(ordered, ordered[1:]):
        delta = commit_timestamp(right) - commit_timestamp(left)
        gaps.append(delta.total_seconds() / 86400)
    return gaps


def _quantile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ranked = sorted(values)
    if len(ranked) == 1:
        return round(ranked[0], 4)
    index = (len(ranked) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ranked) - 1)
    weight = index - lower
    return round(ranked[lower] * (1 - weight) + ranked[upper] * weight, 4)


def _window_bounds(observation_date: str) -> tuple:
    end = parse_day(observation_date)
    start = end - timedelta(days=RHYTHM_WINDOW_DAYS)
    return start, end


def in_rhythm_window(commit: GitCommit, observation_date: str) -> bool:
    start, end = _window_bounds(observation_date)
    day = commit_timestamp(commit).date()
    return start <= day <= end


def _limitations() -> list[str]:
    return [RHYTHM_LIMITATION, RHYTHM_WINDOW_NOTE, RHYTHM_TIMESTAMP_LIMITATIONS]


def change_rhythm(
    commits: list[GitCommit],
    *,
    observation_date: str,
    empty_reason: str,
) -> dict[str, Any]:
    """Gaps use the 180-day author-timestamp window only. Not labor time."""
    notes = _limitations()
    if not commits:
        payload = NotObserved(empty_reason).to_dict()
        payload["definition_version"] = RHYTHM_DEFINITION_VERSION
        payload["timestamp_basis"] = TIMESTAMP_BASIS
        payload["window_days"] = RHYTHM_WINDOW_DAYS
        payload["observation_date"] = observation_date
        payload["limitations"] = notes
        return payload
    ordered = ordered_commits(commits)
    windowed = [item for item in ordered if in_rhythm_window(item, observation_date)]
    outside = len(ordered) - len(windowed)
    gaps = _gaps(windowed)
    sample = len(windowed)
    active = len({commit_timestamp(item).date() for item in windowed})
    payload: dict[str, Any] = {
        "kind": "observed",
        "unit": "profile",
        "definition_version": RHYTHM_DEFINITION_VERSION,
        "sample_size": sample,
        "timestamp_basis": TIMESTAMP_BASIS,
        "observation_date": observation_date,
        "window_days": RHYTHM_WINDOW_DAYS,
        "window_population": sample,
        "history_outside_window_commit_count": Observed(outside, "commits").to_dict(),
        "active_days_180d": Observed(active, "days", sample_size=sample).to_dict(),
        "interval_sample_size": Observed(len(gaps), "gaps").to_dict(),
        "limitations": notes,
    }
    if sample < MIN_POPULATION_FOR_RATES or not gaps:
        if sample == 0:
            reason = "no_commits_in_window"
        elif sample < MIN_POPULATION_FOR_RATES:
            reason = "insufficient_population"
        else:
            reason = "no_gaps"
        suppressed = NotObserved(reason).to_dict()
        payload["median_gap_days"] = dict(suppressed)
        payload["p90_gap_days"] = dict(suppressed)
        payload["burst_share_le_2d"] = dict(suppressed)
        payload["long_gap_share_ge_30d"] = dict(suppressed)
        return payload
    burst = sum(1 for gap in gaps if gap <= 2) / len(gaps)
    long_gap = sum(1 for gap in gaps if gap >= 30) / len(gaps)
    payload["median_gap_days"] = Observed(
        round(statistics.median(gaps), 4), "days", sample_size=len(gaps)
    ).to_dict()
    payload["p90_gap_days"] = Observed(
        _quantile(gaps, 0.9), "days", sample_size=len(gaps)
    ).to_dict()
    payload["burst_share_le_2d"] = Observed(
        round(burst, 4), "ratio", sample_size=len(gaps)
    ).to_dict()
    payload["long_gap_share_ge_30d"] = Observed(
        round(long_gap, 4), "ratio", sample_size=len(gaps)
    ).to_dict()
    return payload
