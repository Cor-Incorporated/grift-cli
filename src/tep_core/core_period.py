"""Core activity period: minimal contiguous month range covering >=80%."""

from __future__ import annotations

from collections import Counter
from datetime import date

from tep_core.observation import NotObserved
from tep_core.version import CORE_ACTIVITY_DEFINITION_VERSION

CORE_ACTIVITY_MIN_SHARE = 0.80


def _parse_day(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _add_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def compute_core_activity_period(commit_dates: list[str]) -> dict[str, object]:
    """Return Observed month-range or NotObserved.

    Sliding window over calendar months (empty months kept) from the first
    tenant commit month to the last. The shortest window whose share is
    >= 80% wins; ties take the earliest start.
    """
    if not commit_dates:
        return NotObserved("no_tenant_commits").to_dict()

    months: Counter[str] = Counter()
    for raw in commit_dates:
        months[_month_key(_parse_day(raw))] += 1

    keys = sorted(months)
    start_y, start_m = (int(p) for p in keys[0].split("-"))
    end_y, end_m = (int(p) for p in keys[-1].split("-"))
    sequence: list[tuple[str, int]] = []
    year, month = start_y, start_m
    while (year, month) <= (end_y, end_m):
        key = f"{year:04d}-{month:02d}"
        sequence.append((key, months.get(key, 0)))
        year, month = _add_month(year, month, 1)

    total = sum(count for _, count in sequence)
    if total == 0:
        return NotObserved("no_tenant_commits").to_dict()

    best: tuple[int, int, int, float] | None = None
    for start in range(len(sequence)):
        acc = 0
        for end in range(start, len(sequence)):
            acc += sequence[end][1]
            share = acc / total
            if share >= CORE_ACTIVITY_MIN_SHARE:
                span = end - start
                if best is None or span < best[0] or (span == best[0] and start < best[1]):
                    best = (span, start, end, share)
                break
    if best is None:
        return NotObserved("no_tenant_commits").to_dict()

    _, start_idx, end_idx, share = best
    return {
        "kind": "observed",
        "start": sequence[start_idx][0],
        "end": sequence[end_idx][0],
        "share": round(share, 4),
        "unit": "month-range",
        "definition_version": CORE_ACTIVITY_DEFINITION_VERSION,
    }
