#!/usr/bin/env python3
"""WP4: A vs C / A vs D against criteria registered in 5f2665e.

Repo-scope rates only. Do not mix tenant numbers. No league table in stdout
beyond group-level n / median / verdict.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "corpus" / "runs" / "results.jsonl"
OUT_JSON = ROOT / "corpus" / "runs" / "discriminant-latest.json"


def _rate(row: dict, key: str) -> float | None:
    if key == "test_cochange":
        block = row.get("test_cochange") or {}
        inner = block.get("all_time") or {}
        if inner.get("kind") == "observed" and inner.get("narrate_rate"):
            return float(inner["value"])
        return None
    rework = row.get("rework") or {}
    inner = rework.get("corrective_rework_rate") or {}
    if rework.get("kind") == "observed" and inner.get("kind") == "observed":
        if inner.get("narrate_rate"):
            return float(inner["value"])
    return None


def cliffs_delta(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(right) < 2:
        return None
    gt = lt = 0
    for a in left:
        for b in right:
            if a > b:
                gt += 1
            elif a < b:
                lt += 1
    n = len(left) * len(right)
    return (gt - lt) / n if n else None


def compare(name: str, a: list[float], other: list[float], *, expect_a_higher: bool) -> dict:
    if len(a) < 2 or len(other) < 2:
        return {
            "metric": name,
            "verdict": "inconclusive_small_n",
            "n_A": len(a),
            "n_other": len(other),
        }
    med_a = statistics.median(a)
    med_o = statistics.median(other)
    gap = med_a - med_o
    ra = (min(a), max(a))
    ro = (min(other), max(other))
    contained = (ra[0] >= ro[0] and ra[1] <= ro[1]) or (ro[0] >= ra[0] and ro[1] <= ra[1])
    delta = cliffs_delta(a, other)
    direction_ok = gap >= 0.10 if expect_a_higher else gap <= -0.10
    reverse = (gap <= -0.10) if expect_a_higher else (gap >= 0.10)
    if reverse:
        verdict = "kill_reverse_direction"
    elif direction_ok and not contained and delta is not None and abs(delta) >= 0.33:
        verdict = "separated"
    else:
        verdict = "fail_tier2"
    return {
        "metric": name,
        "verdict": verdict,
        "median_A": round(med_a, 4),
        "median_other": round(med_o, 4),
        "gap": round(gap, 4),
        "range_A": ra,
        "range_other": ro,
        "contained": contained,
        "cliffs_delta": None if delta is None else round(delta, 4),
        "n_A": len(a),
        "n_other": len(other),
    }


def main() -> int:
    rows = []
    if RESULTS.is_file():
        rows = [
            json.loads(line)
            for line in RESULTS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    by_group: dict[str, list] = defaultdict(list)
    for row in rows:
        by_group[row.get("group", "?")].append(row)

    def values(group: str, key: str) -> list[float]:
        out = []
        for row in by_group.get(group, []):
            v = _rate(row, key)
            if v is not None:
                out.append(v)
        return out

    checks = [
        compare(
            "test_cochange A vs D",
            values("A", "test_cochange"),
            values("D", "test_cochange"),
            expect_a_higher=True,
        ),
        compare(
            "test_cochange A vs C",
            values("A", "test_cochange"),
            values("C", "test_cochange"),
            expect_a_higher=True,
        ),
        compare(
            "corrective_rework A vs C",
            values("A", "corrective"),
            values("C", "corrective"),
            expect_a_higher=False,
        ),
    ]
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(checks, indent=2) + "\n")
    sys.stderr.write(
        "Wrote latest verdicts to corpus/runs/discriminant-latest.json. "
        "Do not overwrite historical sections in DISCRIMINANT-v2026.09.md.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
