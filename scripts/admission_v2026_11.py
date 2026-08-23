#!/usr/bin/env python3
"""P1c admission: fix SHAs for the v2026.11 candidates and run repo-scope analysis.

Reads /tmp/candidates.json (from docs/CORPUS-CANDIDATES doc), excludes the
heavy-clone repos and any v2026.09 duplicate, clones (blob:none), re-pins the
default-branch HEAD (admission-time SHA), runs analyze_repository(scope=repo),
and writes corpus/pins-v2026.11.toml + corpus/runs-v2026.11/results.jsonl.

Narratable = test_frameworks observed AND repo-scope production population
>= 20 (rate narratable under H-5). Shortfall vs targets is recorded verbatim.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from tep_core.analyze import analyze_repository  # noqa: E402
from tep_core.identity import empty_identity  # noqa: E402
from tep_core.lineage import Lineage  # noqa: E402

EXCLUDE_REPOS = {
    # heavy clones (research notes)
    "wrtnlabs/autobe",
    "datawhalechina/vibe-vibe",
}


def sh(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def ensure_clone(url: str, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        r = sh("git", "clone", "--filter=blob:none", url, str(dest), timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"clone failed: {r.stderr[:200]}")
    # admission-time SHA = default branch HEAD right now
    r = sh("git", "-C", str(dest), "ls-remote", url, "HEAD")
    if r.returncode != 0:
        raise RuntimeError("ls-remote failed")
    head = r.stdout.split()[0]
    r = sh("git", "-C", str(dest), "cat-file", "-t", head)
    if r.returncode != 0:
        r = sh("git", "-C", str(dest), "fetch", "--filter=blob:none", "origin", timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"fetch failed: {r.stderr[:200]}")
    r = sh("git", "-C", str(dest), "checkout", "--force", head, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"checkout failed: {r.stderr[:200]}")
    return head


def main() -> int:
    candidates = json.loads(Path("/tmp/candidates.json").read_text(encoding="utf-8"))
    with (ROOT / "corpus" / "pins-v2026.09.toml").open("rb") as handle:
        old_pins = tomllib.load(handle)
    old_names = {p["name"] for p in old_pins["repos"]}
    out_root = ROOT / "corpus" / "runs-v2026.11"
    out_root.mkdir(parents=True, exist_ok=True)
    results_path = out_root / "results.jsonl"
    failures_path = out_root / "failures.jsonl"
    results_path.write_text("", encoding="utf-8")
    failures_path.write_text("", encoding="utf-8")

    pin_entries: list[dict] = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    counts = {"C": 0, "D": 0, "B": 0}
    narratable = {"C": 0, "D": 0}
    for group in ("C", "D", "B"):
        for cand in candidates[group]:
            name = cand["repo"].split("/")[-1]
            url = f"https://github.com/{cand['repo']}.git"
            if cand["repo"] in EXCLUDE_REPOS:
                print(f"skip {cand['repo']} (heavy clone)")
                continue
            if name in old_names:
                print(f"skip {cand['repo']} (already in v2026.09)")
                continue
            dest = ROOT / ".corpus-cache" / name
            record = {
                "run_id": run_id,
                "id": f"{group}-{name}",
                "group": group,
                "repo": cand["repo"],
                "url": url,
                "admitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            try:
                sha = ensure_clone(url, dest)
                record["sha"] = sha
                report = analyze_repository(dest, empty_identity(), Lineage(), scope="repo")
                tf = report.get("test_frameworks", {})
                cochange = report.get("test_cochange", {})
                inner = (
                    (cochange.get("all_time") or {}) if cochange.get("kind") == "observed" else {}
                )
                is_narratable = (
                    tf.get("kind") == "observed"
                    and inner.get("kind") == "observed"
                    and inner.get("narrate_rate") is True
                )
                record.update(
                    {
                        "status": "ok",
                        "test_frameworks_observed": tf.get("kind") == "observed",
                        "narratable": is_narratable,
                        "production_population": inner.get("population", 0),
                        "test_cochange_value": inner.get("value"),
                    }
                )
                if is_narratable:
                    narratable[group] = narratable.get(group, 0) + 1
                counts[group] += 1
                pin_entries.append(
                    {
                        "id": record["id"],
                        "group": group,
                        "name": name,
                        "url": url,
                        "sha": sha,
                        "license": cand["license"],
                        "tests_hint": cand["tests"],
                        "commits_hint": cand["commits"],
                        "reason": cand["reason"],
                        "narratable": is_narratable,
                    }
                )
                with results_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"ok {record['id']} narratable={is_narratable}")
            except Exception as exc:  # noqa: BLE001
                record.update({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
                with failures_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"FAIL {cand['repo']}: {record['reason'][:120]}")
    summary = {
        "run_id": run_id,
        "admitted": counts,
        "narratable": narratable,
        "target": {"C_narratable": 30, "D_total": 20},
    }
    (out_root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    Path("/tmp/pins-v2026.11.json").write_text(
        json.dumps(pin_entries, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
