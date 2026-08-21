"""Golden corpus: pinned public repositories vs expected JSON written first."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity, load_identity
from tep_core.lineage import Lineage

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "golden" / "pins.toml"
CACHE = ROOT / ".golden-cache"


def _load_pins() -> list[dict]:
    import tomllib

    with PINS.open("rb") as handle:
        return list(tomllib.load(handle)["repos"])


def _ensure_clone(url: str, dest: Path, sha: str) -> None:
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--filter=blob:none", url, str(dest)],
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(dest), "fetch", "--filter=blob:none", "origin"],
        check=True,
    )
    subprocess.run(["git", "-C", str(dest), "checkout", "--force", sha], check=True)


def _subset_equal(expected: object, actual: object, path: str = "") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key} missing"
            _subset_equal(value, actual[key], f"{path}.{key}")
        return
    if isinstance(expected, list):
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
        return
    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


@pytest.mark.golden
@pytest.mark.parametrize("pin", _load_pins(), ids=lambda p: p["id"])
def test_golden_repo(pin: dict) -> None:
    dest = CACHE / pin["name"]
    _ensure_clone(pin["url"], dest, pin["sha"])
    identity_rel = pin.get("identity") or ""
    identity_path = ROOT / identity_rel if identity_rel else None
    identity = load_identity(identity_path) if identity_path else empty_identity()
    parent = pin.get("parent") or None
    lineage = Lineage(is_fork=bool(pin.get("fork")), parent=parent)
    report = analyze_repository(dest, identity, lineage, include_files=False)
    expected = json.loads(
        (ROOT / "golden" / "expected" / f"{pin['id']}.json").read_text(encoding="utf-8")
    )
    _subset_equal(expected, report)
