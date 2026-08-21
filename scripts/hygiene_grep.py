#!/usr/bin/env python3
"""Hygiene scan over the working tree.

Needles are loaded from TEP_HYGIENE_NEEDLES (comma-separated) or from
an untracked .hygiene-needles.txt. This module ships dummy defaults only
and does not embed a production needle list.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDLE_FILE = ROOT / ".hygiene-needles.txt"
DUMMY_DEFAULTS = ("example-corp", "sample-user-0000")


def load_needles() -> tuple[str, list[str]]:
    env = os.environ.get("TEP_HYGIENE_NEEDLES", "").strip()
    if env:
        return "env", [part.strip() for part in env.split(",") if part.strip()]
    if NEEDLE_FILE.is_file():
        lines = []
        for raw in NEEDLE_FILE.read_text(encoding="utf-8").splitlines():
            text = raw.strip()
            if text and not text.startswith("#"):
                lines.append(text)
        return "file", lines
    return "defaults", list(DUMMY_DEFAULTS)


def main() -> int:
    source, needles = load_needles()
    if source == "defaults":
        print("hygiene: ok (dummy defaults; tree scan skipped)")
        return 0
    if not needles:
        print("hygiene: ok (empty needle list)")
        return 0
    pattern = "|".join(needles)
    result = subprocess.run(
        [
            "git",
            "grep",
            "-nIE",
            pattern,
            "--",
            ".",
            ":!docs/ACCEPTANCE*",
            ":!docs/HANDOVER*",
            ":!docs/INSTRUCTION*",
            ":!docs/EVIDENCE-INDEX*",
            ":!docs/PREPUB*",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1 and not result.stdout.strip():
        print(f"hygiene: ok (0 matches; source={source})")
        return 0
    if result.returncode == 0 and result.stdout.strip():
        sys.stderr.write("hygiene FAIL: forbidden needles present\n")
        sys.stderr.write(result.stdout)
        return 1
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        return result.returncode
    print(f"hygiene: ok (0 matches; source={source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
