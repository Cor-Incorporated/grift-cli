#!/usr/bin/env python3
"""Fail if a Markdown report uses TEP-forbidden vocabulary.

Used by unit tests against generated reports, and as a CLI helper.
"""

from __future__ import annotations

import re
import sys

FORBIDDEN_LITERALS = (
    "素晴らしい",
    "シニア相当",
    "ジュニア相当",
    "スコアカード",
)

# Grade / composite-score wording (Japanese and English).
FORBIDDEN_REGEXES = (
    re.compile(r"総合スコア"),
    re.compile(r"\bgrade\b", re.I),
    re.compile(r"\belite\b", re.I),
    re.compile(r"[0-9]+(\.[0-9]+)?\s*倍"),
    re.compile(r"シニア"),
    re.compile(r"ジュニア"),
)

# A bare integer/decimal on its own line or after a colon, with no unit.
BARE_NUMBER = re.compile(
    r"(^|\n)[^\n]*[:：]\s*[0-9]+(\.[0-9]+)?\s*($|\n)",
)


def violations(text: str) -> list[str]:
    found: list[str] = []
    for literal in FORBIDDEN_LITERALS:
        if literal in text:
            found.append(f"forbidden literal: {literal}")
    for regex in FORBIDDEN_REGEXES:
        if regex.search(text):
            found.append(f"forbidden pattern: {regex.pattern}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: check_forbidden_vocab.py <markdown-file>\n")
        return 2
    path = argv[1]
    text = open(path, encoding="utf-8").read()
    found = violations(text)
    if found:
        sys.stderr.write("forbidden vocabulary:\n")
        for item in found:
            sys.stderr.write(f"  {item}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
