#!/usr/bin/env python3
"""A/D discriminatory-power pilot. Criteria live in docs/corpus-protocol.md.

Run only after those criteria are committed. This script must not invent
new pass bars from the numbers it just computed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".golden-cache"
sys.path.insert(0, str(ROOT / "src"))

from tep_core.analyze import analyze_repository  # noqa: E402
from tep_core.identity import empty_identity, load_identity  # noqa: E402
from tep_core.lineage import Lineage  # noqa: E402

# Pins for this pilot (must match corpus-protocol.md).
A_IDENTITY = {
    "click": {
        "identity": ROOT / "golden/identity/G1-click.toml",
        "fork": False,
        "parent": None,
    }
}
A_MARKER = {
    "express": {"fork": False, "parent": None},
    "typer": {"fork": False, "parent": None},
}
D_PINS = {
    "gitignore": {"fork": False, "parent": None},
    "Spoon-Knife": {"fork": True, "parent": "octocat/Hello-World"},
}


def _obs_reason(block: dict) -> str | None:
    if block.get("kind") == "not_observed":
        return str(block.get("reason"))
    return None


def _rate(block: dict) -> dict[str, object]:
    if block.get("kind") != "observed":
        return {
            "status": "not_observed",
            "reason": block.get("reason"),
        }
    inner = block.get("all_time") or block
    if inner.get("kind") == "not_observed":
        return {"status": "not_observed", "reason": inner.get("reason")}
    return {
        "status": "observed",
        "value": inner.get("value"),
        "narrate_rate": inner.get("narrate_rate"),
        "population": inner.get("population"),
    }


def analyze_named(name: str, *, identity_path: Path | None, fork: bool, parent: str | None) -> dict:
    repo = CACHE / name
    identity = load_identity(identity_path) if identity_path else empty_identity()
    report = analyze_repository(repo, identity, Lineage(is_fork=fork, parent=parent))
    rework = report.get("rework") or {}
    if rework.get("kind") == "not_observed":
        corrective = {"status": "not_observed", "reason": rework.get("reason")}
    else:
        corrective = _rate(rework.get("corrective_rework_rate") or {})
    return {
        "repo": name,
        "pending_attribution": report["identity"]["pending_attribution"],
        "test_frameworks": {
            "kind": report["test_frameworks"].get("kind"),
            "reason": report["test_frameworks"].get("reason"),
            "names": report["test_frameworks"].get("names"),
        },
        "test_cochange": _rate(report["test_cochange"]),
        "corrective_rework": corrective,
        "origin_tenant_unique": (report["origin"].get("tenant_unique") or {}).get("value"),
    }


def tier1(rows: list[dict]) -> dict:
    failures: list[str] = []
    for row in rows:
        repo = row["repo"]
        group = row["group"]
        co = row["test_cochange"]
        if group == "D":
            if co.get("status") != "not_observed":
                failures.append(f"{repo}: D expected not_observed co-change, got {co}")
            elif co.get("reason") not in {
                "no_test_framework_or_directory",
                "pending_attribution",
            }:
                failures.append(f"{repo}: D reason {co.get('reason')!r} not in protocol")
        if group == "A" and row.get("identity_bearing"):
            if co.get("status") != "observed" or co.get("narrate_rate") is not True:
                failures.append(f"{repo}: identity-bearing A must narrate co-change, got {co}")
    return {"verdict": "fail" if failures else "pass", "failures": failures}


def main() -> int:
    rows: list[dict] = []
    for name, meta in A_IDENTITY.items():
        row = analyze_named(
            name,
            identity_path=meta["identity"],
            fork=meta["fork"],
            parent=meta["parent"],
        )
        row["group"] = "A"
        row["identity_bearing"] = True
        rows.append(row)
    for name, meta in A_MARKER.items():
        row = analyze_named(name, identity_path=None, fork=meta["fork"], parent=meta["parent"])
        row["group"] = "A"
        row["identity_bearing"] = False
        rows.append(row)
    for name, meta in D_PINS.items():
        row = analyze_named(name, identity_path=None, fork=meta["fork"], parent=meta["parent"])
        row["group"] = "D"
        row["identity_bearing"] = False
        rows.append(row)

    a_rates = [
        r["test_cochange"]["value"]
        for r in rows
        if r["group"] == "A"
        and r["test_cochange"].get("status") == "observed"
        and r["test_cochange"].get("narrate_rate") is True
    ]
    d_rates = [
        r["test_cochange"]["value"]
        for r in rows
        if r["group"] == "D"
        and r["test_cochange"].get("status") == "observed"
        and r["test_cochange"].get("narrate_rate") is True
    ]
    if len(a_rates) >= 2 and len(d_rates) >= 2:
        tier2 = {"verdict": "not_implemented_here", "note": "n>=2 both groups"}
    else:
        tier2 = {
            "verdict": "inconclusive_small_n",
            "n_A_narratable": len(a_rates),
            "n_D_narratable": len(d_rates),
        }

    payload = {
        "protocol": "docs/corpus-protocol.md",
        "criteria_registered_before_run": True,
        "tier1_observation_status": tier1(rows),
        "tier2_rates": tier2,
        "rows": rows,
        "narrative_lock": ("corrective_rework low is not a bug count; it is fresh-work stability"),
    }
    out = ROOT / "corpus" / "ad-pilot.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(payload["tier1_observation_status"], indent=2) + "\n")
    sys.stdout.write(json.dumps(payload["tier2_rates"], indent=2) + "\n")
    return 0 if payload["tier1_observation_status"]["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
