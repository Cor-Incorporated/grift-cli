"""publish.yml and ci.yml pin the same frozen v0.5.9 compatibility baseline.

The pin must name one commit that exists in the PUBLIC repository
(`Cor-Incorporated/grift-cli`), because publish.yml only runs there. The first
real publish (v0.7.1, run 34046881828) failed with `not our ref` because the
pin was a grift-cli-dev commit. This test links the literals so they cannot
drift apart, and records the public commit that the v0.5.9 tag points at.

The P0 falsification suite consumes that baseline through `GRIFT_V059_ROOT`.
It used to run in publish.yml alone, so a P0 failure surfaced at release time
rather than on the pull request that introduced it (v0.7.1, run 34069987423,
`P0-not-observed-not-absence`). ci.yml now runs it too, which means the same
pin exists in two workflow files -- exactly the declaration pair that has to be
machine-linked instead of kept in sync by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PUBLIC_V059_COMMIT = "6711a3cdcb71f2a2a84276ac5e7a5abd4a7bf79f"


def _baseline_pins(text: str, *, require_python: bool) -> list[str]:
    checkout = re.search(
        r"Checkout frozen v0\.5\.9 compatibility baseline.*?ref: ([0-9a-f]{40})", text, re.S
    )
    shell = re.search(r'rev-parse HEAD\)" = \\\n\s*"([0-9a-f]{40})"', text)
    assert checkout, "the baseline checkout pin is missing"
    assert shell, "the baseline shell pin is missing"
    pins = [checkout.group(1), shell.group(1)]
    python = re.search(r'expected_commit = "([0-9a-f]{40})"', text)
    if require_python:
        assert python, "the baseline python pin is missing"
    if python:
        pins.append(python.group(1))
    return pins


def test_the_three_baseline_pins_name_one_public_commit() -> None:
    pins = _baseline_pins(PUBLISH.read_text(encoding="utf-8"), require_python=True)
    assert len(pins) == 3, pins
    assert len(set(pins)) == 1, pins
    assert pins[0] == PUBLIC_V059_COMMIT, pins[0]


def test_the_baseline_oracle_still_requires_version_0_5_9() -> None:
    assert 'version != "0.5.9"' in PUBLISH.read_text(encoding="utf-8")


def test_ci_runs_the_p0_suite_against_the_pinned_baseline() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "tests/fixtures/v060/run_p0_falsify.py" in text, (
        "ci.yml does not run the P0 falsification suite; a norms regression "
        "would again reach a release run before a pull request"
    )
    assert "GRIFT_V059_ROOT" in text, "ci.yml does not hand the P0 suite its v0.5.9 baseline"
    pins = _baseline_pins(text, require_python=False)
    assert set(pins) == {PUBLIC_V059_COMMIT}, pins


def test_ci_and_publish_pin_the_same_baseline() -> None:
    ci_pins = set(_baseline_pins(CI.read_text(encoding="utf-8"), require_python=False))
    publish_pins = set(_baseline_pins(PUBLISH.read_text(encoding="utf-8"), require_python=True))
    assert ci_pins == publish_pins, (
        f"ci.yml pins {sorted(ci_pins)} but publish.yml pins {sorted(publish_pins)}; "
        "the P0 suite would compare against two different v0.5.9 oracles"
    )
    assert ci_pins == {PUBLIC_V059_COMMIT}, sorted(ci_pins)
