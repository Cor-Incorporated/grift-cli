"""Forbidden-vocabulary linter for Markdown reports."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_forbidden_vocab",
        ROOT / "scripts" / "check_forbidden_vocab.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_report_passes() -> None:
    module = _load()
    text = (
        "Origin: tenant_unique 12 commits.\n"
        "Active days: 36 days.\n"
        "Commits per active day: 6.3 commits/active-day.\n"
    )
    assert module.violations(text) == []


def test_grade_words_fail() -> None:
    module = _load()
    found = module.violations("このリポは素晴らしい成果です")
    assert found, "must reject 素晴らしい"


def test_multiplier_fails() -> None:
    module = _load()
    found = module.violations("平均の3倍の活動密度")
    assert found, "must reject N倍 wording"
