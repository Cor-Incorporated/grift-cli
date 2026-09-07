"""Golden corpus: pinned public repositories vs expected JSON written first."""

from __future__ import annotations

import json
import shutil
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


def _is_promisor(dest: Path) -> bool:
    """True when the cache was built by a partial clone."""
    probe = subprocess.run(
        ["git", "-C", str(dest), "config", "--get", "remote.origin.promisor"],
        capture_output=True,
        text=True,
    )
    return probe.stdout.strip() == "true"


def _has_interrupted_pack(dest: Path) -> bool:
    """True when a killed fetch left a temporary pack behind.

    Git then refuses the next fetch with `error: garbage found:
    .git/objects/pack/tmp_pack_*` and exits 128, which reads as a corpus
    failure rather than the stale cache it is.
    """
    return any((dest / ".git" / "objects" / "pack").glob("tmp_pack_*"))


def _ensure_clone(url: str, dest: Path, sha: str) -> None:
    """Materialize the pinned revision as a COMPLETE clone.

    Deliberately not `--filter=blob:none`.  grift runs every git subprocess
    with `GIT_NO_LAZY_FETCH=1` (`tep_core.gitutil._run_git`, introduced with
    the v0.6.0 core runtime) so that analysis never silently reaches the
    network.  On a promisor clone that makes `git log --name-only` fail with
    `could not fetch <oid> from promisor remote`, the per-commit path list is
    lost, and every path-derived observation degrades to
    `not_observed(commit_paths_unavailable)` -- `test_cochange` among them.

    The golden expectations are the values of the complete history, so the
    fixture is what has to change: fetching the blobs is the corpus's job,
    not something the expected values should absorb.  Reported as G1-click
    failing with `.test_cochange.kind: 'not_observed' != 'observed'`.

    A cache left behind by the old partial-clone fixture, or by a killed
    fetch, is rebuilt instead of reused.
    """
    if (dest / ".git").exists() and (_is_promisor(dest) or _has_interrupted_pack(dest)):
        shutil.rmtree(dest)
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", url, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "fetch", "origin"], check=True)
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
