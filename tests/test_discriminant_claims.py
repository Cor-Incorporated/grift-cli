"""Tag-gate: v0.5.2 discriminant claims must match DISCRIMINANT-v2026.11 verbatim.

Addendum16 §3: the old A-vs-C `separated` verdict must no longer be used as
the basis of any explanation. Allowed mentions: the reversal disclosure
itself and the v2026.09 history file. This test parses the discriminant JSON
(verbatim source of truth) and requires every README/persona-answers verdict
line to match it, and forbids old-verdict phrasings outside reversal context.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DISC_MD = (ROOT / "corpus" / "DISCRIMINANT-v2026.11.md").read_text(encoding="utf-8")
DISC = json.loads(
    (ROOT / "corpus" / "runs-v2026.11" / "discriminant-v2026.11.json").read_text(encoding="utf-8")
) if (ROOT / "corpus" / "runs-v2026.11" / "discriminant-v2026.11.json").is_file() else None


def _verdicts() -> dict[str, str]:
    out = {}
    import re
    for line in DISC_MD.splitlines():
        m = re.match(r"^(test_cochange [A-D] vs [A-D]): (\w+)", line)
        if m:
            out[m.group(1)] = m.group(2)
    if DISC is not None:  # dev-side cross-check against the JSON source
        for result in DISC["results"]:
            out[result["comparison"]] = result["verdict"]
    return out


def test_readme_ja_carries_v2026_11_verbatim() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "DISCRIMINANT-v2026.11.md" in text
    for name, verdict in _verdicts().items():
        if not name.startswith("test_cochange"):
            continue
        pattern = rf"{re.escape(name)}`? → `{verdict}`".replace("test_cochange`", "test_cochange")
        # names look like "test_cochange A vs C" — README writes them in backticks
        pattern = rf"`{re.escape(name)}` → `{verdict}`"
        assert re.search(pattern, text), f"README.md missing verbatim {pattern}"
    assert "Cliff δ 0.9198" in text  # A vs D headline effect
    assert "Cliff δ 0.291" in text  # A vs C reversal effect


def test_readme_en_carries_v2026_11_verbatim() -> None:
    text = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "DISCRIMINANT-v2026.11.md" in text
    assert "Cliff δ 0.9198" in text
    assert "Cliff δ 0.291" in text
    assert "fail_tier2" in text


def test_no_stale_separated_basis_outside_reversal_disclosure() -> None:
    """Old A vs C `separated` (0.7143) must only appear inside a reversal
    sentence (a line that also mentions v2026.09 / was / では / fail_tier2)."""
    for rel in ("README.md", "README.en.md", "docs/persona-answers.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "0.7143" not in line:
                continue
            markers = ("v2026.09", "was", "では", "fail_tier2", "DISCRIMINANT-v2026.09")
            if not any(m in line for m in markers):
                raise AssertionError(f"{rel}: stale separated basis: {line.strip()[:120]}")


def test_persona_answers_discriminant_line_updated() -> None:
    text = (ROOT / "docs" / "persona-answers.md").read_text(encoding="utf-8")
    assert "0.9198" in text, "persona-answers must cite the A vs D separation"
    assert "fail_tier2" in text, "persona-answers must state the A vs C reversal"
    assert "0.7143・n=47" not in text, "the pre-v2026.11 claim line must be gone"


def test_discriminant_json_verbatim_matches_report_doc() -> None:
    """The published MD quotes the JSON verbatim lines exactly (dev-side)."""
    import pytest

    if DISC is None:
        pytest.skip("dev-only JSON not present in public snapshots")
    for result in DISC["results"]:
        assert result["verbatim"] in DISC_MD, f"DISCRIMINANT md lost verbatim: {result['verbatim']}"
