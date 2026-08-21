"""Repo-level time-decayed survival (EIS-style, tau=180d). No person scorecards."""

from __future__ import annotations

import math
import re
from pathlib import Path

from tep_core.gitutil import GitError, _run_git
from tep_core.observation import NotObserved

SURVIVAL_DEFINITION_VERSION = "survival-v1-2026-08-22"
TAU_DAYS = 180
TAU_SECONDS = TAU_DAYS * 86400
SRC_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".vue", ".svelte", ".astro", ".swift")
EXCLUDE = re.compile(r"node_modules/|vendor/|dist/|build/|\.min\.|generated")
DEFAULT_MAX_FILES = 40
BLAME_TIMEOUT = 12


def survival_metrics(
    repo: Path,
    *,
    enabled: bool,
    max_files: int = DEFAULT_MAX_FILES,
) -> dict[str, object]:
    if not enabled:
        return NotObserved("survival_scan_disabled").to_dict()
    try:
        listed = _run_git(repo, ["ls-files"]).splitlines()
        head_ts = int(_run_git(repo, ["log", "-1", "--format=%at"]).strip() or "0")
    except GitError:
        return NotObserved("git_unavailable").to_dict()

    files = [f for f in listed if f.endswith(SRC_EXT) and not EXCLUDE.search(f)]
    if not files:
        return NotObserved("no_source_files").to_dict()

    step = max(1, len(files) // max_files)
    sample = files[::step][:max_files]
    weights = 0.0
    lines = 0
    scanned = 0
    for path in sample:
        try:
            out = _run_git(
                repo,
                ["blame", "--line-porcelain", "HEAD", "--", path],
                timeout=BLAME_TIMEOUT,
            )
        except GitError:
            continue
        if not out:
            continue
        scanned += 1
        for line in out.splitlines():
            if line.startswith("author-time "):
                ts = int(line.split()[1])
                age = max(0, head_ts - ts)
                weights += math.exp(-age / TAU_SECONDS)
                lines += 1
    if lines == 0 or scanned == 0:
        return NotObserved("blame_unavailable").to_dict()
    return {
        "kind": "observed",
        "definition_version": SURVIVAL_DEFINITION_VERSION,
        "tau_days": TAU_DAYS,
        "files_sampled": scanned,
        "source_files": len(files),
        "lines_sampled": lines,
        "survival_index": round(weights / lines, 4),
        "unit": "dimensionless",
    }
