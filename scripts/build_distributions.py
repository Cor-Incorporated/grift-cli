#!/usr/bin/env python3
"""Build immutable reference distribution v2026.09 from corpus run JSONL.

not_observed rows are excluded from that metric's n (denominator = measured).
Does not emit a per-repo league table.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "corpus" / "runs" / "results.jsonl"
PINS = ROOT / "corpus" / "pins-v2026.09.toml"
OUT_PKG = ROOT / "src" / "tep_core" / "data" / "v2026.09" / "distributions.json"
OUT_CORPUS = ROOT / "corpus" / "v2026.09" / "distributions.json"


def _rate(block: dict, nested: str | None = None) -> float | None:
    if not isinstance(block, dict):
        return None
    node = block
    if nested:
        node = block.get(nested) or {}
    if node.get("kind") != "observed":
        return None
    if node.get("value") is None:
        return None
    return float(node["value"])


def quartiles(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min": round(ordered[0], 4),
        "q1": round(statistics.quantiles(ordered, n=4)[0], 4) if len(ordered) >= 4 else None,
        "median": round(statistics.median(ordered), 4),
        "q3": round(statistics.quantiles(ordered, n=4)[2], 4) if len(ordered) >= 4 else None,
        "max": round(ordered[-1], 4),
        "values": [round(v, 4) for v in ordered],
    }


def main() -> int:
    rows = []
    if RESULTS.is_file():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    pin_hash = hashlib.sha256(PINS.read_bytes()).hexdigest()[:16]
    cochange = []
    corrective = []
    survival = []
    for row in rows:
        if row.get("status") != "ok":
            continue
        c = _rate(row.get("test_cochange") or {}, "all_time")
        if c is not None:
            cochange.append(c)
        rw = row.get("rework") or {}
        r = _rate(rw.get("corrective_rework_rate") if rw.get("kind") == "observed" else {})
        if r is not None:
            corrective.append(r)
        s = _rate(row.get("survival") or {})
        if s is not None and "survival_index" in (row.get("survival") or {}):
            survival.append(float(row["survival"]["survival_index"]))
    payload = {
        "version": "v2026.09",
        "analysis_scope": "repo",
        "definition_version": "tep-v0.5.0-2026-08-22",
        "tool_version": "0.5.0",
        "pin_list_hash": pin_hash,
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok_repos": len(rows),
        "metrics": {
            "test_cochange": quartiles(cochange) if cochange else {"n": 0, "values": []},
            "corrective_rework": quartiles(corrective) if corrective else {"n": 0, "values": []},
            "survival_index": quartiles(survival) if survival else {"n": 0, "values": []},
        },
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    OUT_PKG.parent.mkdir(parents=True, exist_ok=True)
    OUT_CORPUS.parent.mkdir(parents=True, exist_ok=True)
    OUT_PKG.write_text(text, encoding="utf-8")
    OUT_CORPUS.write_text(text, encoding="utf-8")
    print(json.dumps({k: v.get("n") for k, v in payload["metrics"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
