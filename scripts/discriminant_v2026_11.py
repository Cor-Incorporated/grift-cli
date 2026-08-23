#!/usr/bin/env python3
"""Discriminant re-run for v2026.11: A vs C / A vs D on registered criteria 5f2665e.

Verbatim output (separated and fail both recorded). C narratable shortfall
(14 < 30 target) is recorded verbatim in the report header.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

METRICS = ("test_cochange", "corrective_rework")


def load_rows() -> list[dict]:
    rows = []
    for source, path in (
        ("v2026.09", ROOT / "corpus/runs/results.jsonl"),
        ("v2026.11", ROOT / "corpus/runs-v2026.11/results-with-metrics.jsonl"),
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["_source"] = source
                rows.append(row)
    return rows


def rate_of(row: dict, metric: str) -> float | None:
    if metric == "test_cochange":
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


def compare(
    name: str, a: list[float], other: list[float], *, expect_a_higher: bool, tier2_required: bool
) -> dict:
    n_a, n_other = len(a), len(other)
    result = {
        "comparison": name,
        "n_A": n_a,
        "n_other": n_other,
    }
    if n_other < 2:
        result["verdict"] = "inconclusive_small_n"
        result["verbatim"] = f"{name}: inconclusive_small_n (n {n_a}/{n_other})"
        return result
    med_a = round(statistics.median(a), 4)
    med_o = round(statistics.median(other), 4)
    gap = round(med_a - med_o, 4)
    delta = cliffs_delta(a, other)
    result.update(
        {
            "median_A": med_a,
            "median_other": med_o,
            "gap": gap,
            "cliffs_delta": round(delta, 4) if delta is not None else None,
        }
    )
    if not tier2_required:
        result["verdict"] = "no_required_direction"
        result["verbatim"] = (
            f"{name}: no_required_direction (median_A {med_a}, median_other {med_o}, "
            f"gap {gap}, Cliff δ {result['cliffs_delta']}, n {n_a}/{n_other})"
        )
        return result
    ok_direction = (gap >= 0.10) if expect_a_higher else True
    ok_range = not (min(a) >= min(other) and max(a) <= max(other))
    ok_effect = delta is not None and abs(delta) >= 0.33
    verdict = "separated" if (ok_direction and ok_range and ok_effect) else "fail_tier2"
    result["verdict"] = verdict
    result["verbatim"] = (
        f"{name}: {verdict} (median_A {med_a}, median_other {med_o}, gap {gap}, "
        f"Cliff δ {result['cliffs_delta']}, n {n_a}/{n_other})"
    )
    return result


def main() -> int:
    rows = load_rows()
    by_group: dict[str, list[float]] = {m: {"A": [], "C": [], "D": []} for m in METRICS}
    for row in rows:
        group = row.get("group")
        if group not in ("A", "C", "D"):
            continue
        for metric in METRICS:
            rate = rate_of(row, metric)
            if rate is not None:
                by_group[metric][group].append(rate)
    out = {
        "corpus": "v2026.11 (v2026.09 rows merged)",
        "criteria": "5f2665e (frozen)",
        "shortfall_verbatim": (
            "C narratable = 14 against target 30 (research tests-hints overestimated; "
            "flags machine-verified at admission). D narratable = 14 / total 29 (target 20 met on total)."
        ),
        "results": [],
    }
    for metric in METRICS:
        g = by_group[metric]
        # A vs C: direction required (co-change) per registered criteria
        out["results"].append(
            compare(
                f"{metric} A vs C",
                g["A"],
                g["C"],
                expect_a_higher=(metric == "test_cochange"),
                tier2_required=(metric == "test_cochange"),
            )
        )
        # A vs D: corrective has no required direction (D expected not_observed historically,
        # but v2026.11 template D repos DO have tests — first time n stands)
        out["results"].append(
            compare(
                f"{metric} A vs D",
                g["A"],
                g["D"],
                expect_a_higher=(metric == "test_cochange"),
                tier2_required=(metric == "test_cochange"),
            )
        )
    for r in out["results"]:
        print(r["verbatim"])
    print("SHORTFALL:", out["shortfall_verbatim"])
    dest = ROOT / "corpus" / "runs-v2026.11" / "discriminant-v2026.11.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
