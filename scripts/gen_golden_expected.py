#!/usr/bin/env python3
"""Generate slim expected JSON for new golden pins (existing report fields).

Usage: python3 scripts/gen_golden_expected.py [--only G6-x,G7-y]

Writes golden/expected/<id>.json with the same slim subset shape used by
G1-G5 (schema_version, identity, lineage, origin, attribution, activity,
core_activity_period, test_frameworks, test_cochange, rework, survival,
provenance subset, interpretation). Excludes analyzed_at / tool_version so
the file only freezes content that must never change silently.

Golden rule kept: expected files are a REGRESSION detector. Generating them
from the current implementation is allowed only for NEW pins whose values
are then frozen; existing G1-G5 files are never rewritten by this script
(it refuses to overwrite unless --force).
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from tep_core.analyze import analyze_repository  # noqa: E402
from tep_core.identity import empty_identity  # noqa: E402
from tep_core.lineage import Lineage  # noqa: E402


def slim(report: dict) -> dict:
    return {
        "schema_version": report["schema_version"],
        "identity": report["identity"],
        "lineage": report["lineage"],
        "origin": report["origin"],
        "attribution": report["attribution"],
        "activity": report["activity"],
        "core_activity_period": report["core_activity_period"],
        "test_frameworks": report["test_frameworks"],
        "test_cochange": report["test_cochange"],
        "rework": report["rework"],
        "survival": report["survival"],
        "provenance": {
            "analysis_scope": report["provenance"]["analysis_scope"],
            "analyzed_commit_sha": report["provenance"]["analyzed_commit_sha"],
        },
        "interpretation": report["interpretation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="comma-separated pin ids")
    parser.add_argument("--force", action="store_true", help="overwrite existing expected files")
    args = parser.parse_args()
    with (ROOT / "golden" / "pins.toml").open("rb") as handle:
        pins = list(tomllib.load(handle)["repos"])
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        pins = [pin for pin in pins if pin["id"] in wanted]
    import test_golden  # noqa: PLC0415 — reuses the clone helper

    failures = 0
    for pin in pins:
        dest = ROOT / ".golden-cache" / pin["name"]
        out_path = ROOT / "golden" / "expected" / f"{pin['id']}.json"
        if out_path.exists() and not args.force:
            print(f"skip {pin['id']} (expected exists; --force to overwrite)")
            continue
        try:
            test_golden._ensure_clone(pin["url"], dest, pin["sha"])
            identity = empty_identity()
            report = analyze_repository(
                dest,
                identity,
                Lineage(is_fork=bool(pin.get("fork")), parent=pin.get("parent") or None),
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {pin['id']}: {type(exc).__name__}: {exc}")
            continue
        out_path.write_text(
            json.dumps(slim(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {out_path.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
