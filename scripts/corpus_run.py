#!/usr/bin/env python3
"""WP1 corpus runner: clone pinned SHAs, analyze --scope repo, record failures.

Never silently drop a pin from the denominator. Failures go to failures.jsonl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tep_core.analyze import analyze_repository  # noqa: E402
from tep_core.identity import empty_identity  # noqa: E402
from tep_core.lineage import Lineage  # noqa: E402


def load_pins(path: Path) -> list[dict]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return list(data["repos"])


def ensure_clone(url: str, dest: Path, sha: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", url, str(dest)],
            check=True,
            timeout=300,
        )
    has = subprocess.run(
        ["git", "-C", str(dest), "cat-file", "-t", sha],
        capture_output=True,
        timeout=30,
    )
    if has.returncode != 0:
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--filter=blob:none", "origin"],
            check=True,
            timeout=300,
        )
    subprocess.run(["git", "-C", str(dest), "checkout", "--force", sha], check=True, timeout=120)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pins", type=Path, default=ROOT / "corpus" / "pins-v2026.09.toml")
    parser.add_argument("--cache", type=Path, default=ROOT / ".corpus-cache")
    parser.add_argument("--out", type=Path, default=ROOT / "corpus" / "runs")
    parser.add_argument("--survival", action="store_true")
    args = parser.parse_args()
    pins = load_pins(args.pins)
    args.out.mkdir(parents=True, exist_ok=True)
    failures_path = args.out / "failures.jsonl"
    results_path = args.out / "results.jsonl"
    # Do not truncate silently: append with a run header.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    failures_path.write_text("", encoding="utf-8")
    results_path.write_text("", encoding="utf-8")
    ok = 0
    for pin in pins:
        name = pin["name"]
        dest = args.cache / name
        record = {
            "run_id": run_id,
            "id": pin["id"],
            "group": pin["group"],
            "name": name,
            "url": pin["url"],
            "sha": pin["sha"],
            "analysis_scope": "repo",
        }
        try:
            ensure_clone(pin["url"], dest, pin["sha"])
            report = analyze_repository(
                dest,
                empty_identity(),
                Lineage(is_fork=bool(pin.get("fork")), parent=pin.get("parent") or None),
                survival=bool(args.survival),
                scope="repo",
            )
            slim = {
                **record,
                "status": "ok",
                "provenance": report["provenance"],
                "test_frameworks": report["test_frameworks"],
                "test_cochange": report["test_cochange"],
                "rework": report["rework"],
                "survival": report["survival"],
            }
            with results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(slim, ensure_ascii=False) + "\n")
            ok += 1
            sys.stderr.write(f"ok {pin['id']} ({ok}/{len(pins)})\n")
        except Exception as exc:  # noqa: BLE001 — record every failure with reason
            fail = {**record, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            with failures_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(fail, ensure_ascii=False) + "\n")
            sys.stderr.write(f"FAIL {pin['id']}: {fail['reason']}\n")
    summary = {
        "run_id": run_id,
        "pins": len(pins),
        "ok": ok,
        "failed": len(pins) - ok,
        "analysis_scope": "repo",
        "failures_path": str(failures_path),
        "results_path": str(results_path),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0 if ok >= 30 else 1


if __name__ == "__main__":
    raise SystemExit(main())
