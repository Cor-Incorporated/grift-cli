"""publish.yml pins a frozen v0.5.9 compatibility baseline in three places.

The pin must name one commit that exists in the PUBLIC repository
(`Cor-Incorporated/grift-cli`), because publish.yml only runs there. The first
real publish (v0.7.1, run 34046881828) failed with `not our ref` because the
pin was a grift-cli-dev commit. This test links the three literals so they
cannot drift apart, and records the public commit that the v0.5.9 tag points at.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"
PUBLIC_V059_COMMIT = "6711a3cdcb71f2a2a84276ac5e7a5abd4a7bf79f"


def _baseline_pins(text: str) -> list[str]:
    checkout = re.search(
        r"Checkout frozen v0\.5\.9 compatibility baseline.*?ref: ([0-9a-f]{40})", text, re.S
    )
    shell = re.search(r'rev-parse HEAD\)" = \\\n\s*"([0-9a-f]{40})"', text)
    python = re.search(r'expected_commit = "([0-9a-f]{40})"', text)
    assert checkout and shell and python, "one of the three baseline pins is missing"
    return [checkout.group(1), shell.group(1), python.group(1)]


def test_the_three_baseline_pins_name_one_public_commit() -> None:
    pins = _baseline_pins(PUBLISH.read_text(encoding="utf-8"))
    assert len(set(pins)) == 1, pins
    assert pins[0] == PUBLIC_V059_COMMIT, pins[0]


def test_the_baseline_oracle_still_requires_version_0_5_9() -> None:
    assert 'version != "0.5.9"' in PUBLISH.read_text(encoding="utf-8")
