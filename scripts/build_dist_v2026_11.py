#!/usr/bin/env python3
"""Build reference distribution v2026.11 from corpus run results.

Merges v2026.09 results (n=47) with the v2026.11 admission results (n=70)
into distributions.json (same shape as v2026.09). Metrics: test_cochange
and corrective_rework (narratable only). Context strata: collaboration_class
per-pinned from the admission run's context_profile. Stratum deciles are
issued only for strata with n >= MIN_N (30); otherwise global only + note.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MIN_N = 30


def load_results(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


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


def deciles(values: list[float]) -> list[float]:
    qs = []
    s = sorted(values)
    for q in range(10):
        idx = q * (len(s) - 1) / 9
        lo = int(idx)
        hi = min(lo + 1, len(s) - 1)
        frac = idx - lo
        qs.append(round(s[lo] * (1 - frac) + s[hi] * frac, 4))
    return qs


def main() -> int:
    old_rows = load_results(ROOT / "corpus" / "runs" / "results.jsonl")
    new_raw = load_results(ROOT / "corpus" / "runs-v2026.11" / "results.jsonl")

    # v2026.09 rows already carry test_cochange/rework blocks (slim record).
    rows = []
    for row in old_rows:
        rows.append(
            {
                "id": row["id"],
                "group": row.get("group"),
                "name": row.get("name"),
                "sha": row.get("sha"),
                "source": "v2026.09",
                "context": None,
                "test_cochange": row.get("test_cochange"),
                "rework": row.get("rework"),
            }
        )
    # new rows need a repo-scope re-read for the metric blocks: re-run analyze for
    # narratable-flagged pins only? Simpler: the admission run recorded only flags.
    # Re-analyze each new repo to capture blocks (cached clones make this cheap).
    from tep_core.analyze import analyze_repository
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    for row in new_raw:
        dest = ROOT / ".corpus-cache" / row["id"].split("-", 1)[1]
        try:
            report = analyze_repository(dest, empty_identity(), Lineage(), scope="repo")
            ctx = report.get("context_profile") or {}
            rows.append(
                {
                    "id": row["id"],
                    "group": row.get("group"),
                    "name": row["id"].split("-", 1)[1],
                    "sha": row.get("sha"),
                    "source": "v2026.11",
                    "context": {
                        "collaboration_class": (ctx.get("collaboration_class") or {}).get("value"),
                        "lifecycle_stage": (ctx.get("lifecycle_stage") or {}).get("value"),
                    },
                    "test_cochange": report.get("test_cochange"),
                    "rework": report.get("rework"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            print(f"skip {row['id']}: {exc}")

    metrics: dict[str, dict] = {}
    for metric_id in ("test_cochange", "corrective_rework"):
        values = []
        for row in rows:
            rate = rate_of(row, metric_id)
            if rate is not None:
                values.append(rate)
        n = len(values)
        entry: dict = {"n": n, "deciles": deciles(values) if n else []}
        metrics[metric_id] = entry
        print(metric_id, "global n =", n)

    # context strata (v2026.11 rows only have context; stratum issue requires
    # the class recorded on the pin — global distribution uses all rows)
    strata_notes = []
    for metric_id in ("test_cochange",):
        for dim in ("collaboration_class", "lifecycle_stage"):
            by_stratum: dict[str, list[float]] = {}
            for row in rows:
                if not row.get("context"):
                    continue
                rate = rate_of(row, metric_id)
                if rate is None:
                    continue
                key = (row["context"] or {}).get(dim)
                if key:
                    by_stratum.setdefault(key, []).append(rate)
            for key, vals in sorted(by_stratum.items()):
                if len(vals) >= MIN_N:
                    metrics[metric_id].setdefault("strata", {})[key] = {
                        "n": len(vals),
                        "deciles": deciles(vals),
                    }
                    print(f"{metric_id} stratum {key}: n={len(vals)} issued")
                else:
                    strata_notes.append(
                        f"{metric_id} stratum {key}: n={len(vals)} < MIN_N 30 — global only (context_stratum_too_small)"
                    )

    dist = {
        "version": "v2026.11",
        "analysis_scope": "repo",
        "definition_version": None,  # filled by caller (tep_core.version)
        "metrics": metrics,
        "notes": strata_notes,
        "sources": {
            "v2026.09": len([r for r in rows if r["source"] == "v2026.09"]),
            "v2026.11": len([r for r in rows if r["source"] == "v2026.11"]),
        },
    }
    from tep_core.version import DEFINITION_VERSION

    dist["definition_version"] = DEFINITION_VERSION
    out = ROOT / "corpus" / "v2026.11" / "distributions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "src" / "tep_core" / "data" / "v2026.11").mkdir(parents=True, exist_ok=True)
    (ROOT / "src" / "tep_core" / "data" / "v2026.11" / "distributions.json").write_text(
        json.dumps(dist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("wrote", out)
    for note in strata_notes:
        print("NOTE:", note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
