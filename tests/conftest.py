"""Pytest hooks."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "golden: live clone of pinned public repositories (network)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TEP_GOLDEN") == "1":
        return
    skip = pytest.mark.skip(reason="set TEP_GOLDEN=1 to run live golden clones")
    for item in items:
        if "golden" in item.keywords:
            item.add_marker(skip)
