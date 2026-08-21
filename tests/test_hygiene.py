"""Hygiene: dummy defaults always; real needles only when a needle file exists."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NEEDLE_FILE = ROOT / ".hygiene-needles.txt"
_CONCAT = re.compile(r'"[a-z@-]{2,}"\s*\+\s*"')
_AUDIT_PREFIXES = (
    "docs/ACCEPTANCE",
    "docs/HANDOVER",
    "docs/INSTRUCTION",
    "docs/EVIDENCE-INDEX",
    "docs/PREPUB",
)


def _is_audit_doc(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in _AUDIT_PREFIXES)


def test_hygiene_script_exits_zero() -> None:
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "hygiene_grep.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shipped_defaults_are_dummy_only() -> None:
    src = (ROOT / "scripts" / "hygiene_grep.py").read_text(encoding="utf-8")
    assert "example-corp" in src
    assert "sample-user-0000" in src
    assert _CONCAT.search(src) is None


def test_real_needles_absent_when_needle_file_present() -> None:
    if not NEEDLE_FILE.is_file():
        pytest.skip("needle file not present")
    needles = [
        line.strip()
        for line in NEEDLE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert needles, "needle file is empty"
    skip_dirs = {".git", ".venv", "venv", ".golden-cache", "dist", ".pytest_cache"}
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.resolve() == NEEDLE_FILE.resolve():
            continue
        if not path.is_file():
            continue
        rel = str(path.relative_to(ROOT))
        if _is_audit_doc(rel):
            continue
        if path.suffix not in {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            if needle in text:
                hits.append(rel)
                break
    assert hits == [], "forbidden needles in:\n" + "\n".join(hits)


def test_no_concatenated_string_needles_in_shipped_sources() -> None:
    roots = [ROOT / "src", ROOT / "tests", ROOT / "scripts"]
    hits: list[str] = []
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix != ".py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if _CONCAT.search(text):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == [], "concatenated string literals remain in:\n" + "\n".join(hits)
