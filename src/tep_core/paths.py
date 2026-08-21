"""Path roles for test co-change and rework (clean-room)."""

from __future__ import annotations

import re

TEST_PATH_RE = re.compile(
    r"(^|/)(tests|test|__tests__|spec)/"
    r"|(^|/)(test_[^/]+|_test)\.py$"
    r"|_test\.go$"
    r"|\.spec\.(ts|tsx|js|jsx)$"
    r"|\.test\.(ts|tsx|js|jsx)$"
    r"|_spec\.rb$",
    re.I,
)

DOC_OR_CONFIG_RE = re.compile(
    r"\.(md|rst)$"
    r"|(^|/)(docs|documentation|\.github)(/|$)"
    r"|(^|/)(LICENSE|CHANGELOG|CONTRIBUTING)",
    re.I,
)


def normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH_RE.search(normalize(path)))


def is_doc_or_config_path(path: str) -> bool:
    p = normalize(path)
    if is_test_path(p):
        return False
    return bool(DOC_OR_CONFIG_RE.search(p))


def is_prod_path(path: str) -> bool:
    return not is_test_path(path) and not is_doc_or_config_path(path)


def split_paths(files: tuple[str, ...] | list[str]) -> tuple[list[str], list[str], list[str]]:
    prod = [f for f in files if is_prod_path(f)]
    tests = [f for f in files if is_test_path(f)]
    docs = [f for f in files if is_doc_or_config_path(f)]
    return prod, tests, docs
