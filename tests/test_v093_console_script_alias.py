"""A1 (v0.9.3): the package must provide an executable named ``grift-cli``.

Measured RED on 0.9.2 (2026-11-20): ``uvx grift-cli --version`` fails with
"An executable named `grift-cli` is not provided by package `grift-cli`".
The package therefore declares a second console script carrying the package
name, so ``uvx grift-cli`` works without ``--from``.  This file checks the
declaration offline; the published-package check re-runs after the release
is uploaded (human gate).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_grift_cli_alias() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["grift-cli"] == "tep_cli.__main__:main"
    assert scripts["grift"] == "tep_cli.__main__:main"


def test_alias_target_exists() -> None:
    from tep_cli.__main__ import main  # noqa: F401
