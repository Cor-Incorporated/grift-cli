"""Test-framework observation at HEAD. not_observed != 0."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tep_core.observation import NotObserved

FRAMEWORK_MARKERS = (
    "vitest",
    "jest",
    "playwright",
    "cypress",
    "mocha",
    "jasmine",
    "pytest",
    "unittest",
    "nyc",
    "testing-library",
    "ava",
    "karma",
    "selenium",
    "testify",
    "ginkgo",
)

TEST_DIRECTORIES = (
    "tests",
    "test",
    "__tests__",
    "spec",
)

_QUOTED_TOKEN = re.compile(r"[\"']([A-Za-z0-9_.-]+)")


def _package_json_names(root: Path) -> set[str]:
    path = root / "package.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    keys = {
        **(data.get("dependencies") or {}),
        **(data.get("devDependencies") or {}),
    }
    return {str(name).lower() for name in keys}


def _quoted_tokens(text: str) -> set[str]:
    return {match.group(1).lower() for match in _QUOTED_TOKEN.finditer(text)}


def _manifest_names(root: Path) -> set[str]:
    names: set[str] = set()
    names |= _package_json_names(root)
    for rel in ("pyproject.toml", "tox.ini", "setup.cfg", "Pipfile", "go.mod", "Gemfile"):
        path = root / rel
        if path.is_file():
            names |= _quoted_tokens(path.read_text(encoding="utf-8", errors="replace"))
    for req in root.glob("requirements*.txt"):
        names |= _quoted_tokens(req.read_text(encoding="utf-8", errors="replace"))
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            token = re.split(r"[<>=!~;\s]", line.strip(), maxsplit=1)[0].lower()
            if token:
                names.add(token)
    return names


def _matched_markers(package_names: set[str]) -> list[str]:
    found: list[str] = []
    for marker in FRAMEWORK_MARKERS:
        if any(marker in pkg for pkg in package_names):
            found.append(marker)
    return found


def _test_directories(root: Path) -> list[str]:
    found: list[str] = []
    for name in TEST_DIRECTORIES:
        candidate = root / name
        if candidate.is_dir():
            found.append(name)
    return found


def observe_test_frameworks(root: Path) -> dict[str, object]:
    names = _matched_markers(_manifest_names(root))
    directories = _test_directories(root)
    if not names and not directories:
        return NotObserved("no_test_framework_or_directory").to_dict()
    return {
        "kind": "observed",
        "value": True,
        "names": names,
        "directories": directories,
        "unit": "boolean",
    }
