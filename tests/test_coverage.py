"""golden/coverage.md must match the computed matrix and track HOLEs with issues.

Master instruction §3-2 / golden-v2 §1-1: holes must be explicit and issue-
tracked, never silent. This test (a) regenerates the table body and diffs it
against the committed file, (b) requires every HOLE row to appear in
KNOWN_HOLES with an issue URL, (c) forbids KNOWN_HOLES entries whose row is
no longer a hole (stale entries → update the table + close the issue).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from coverage_matrix import FIELD_ROWS, STATUS_HOLE, compute_matrix, pin_ids, row_status  # noqa: E402

COVERAGE_MD = ROOT / "golden" / "coverage.md"

# HOLE rows must carry an issue URL. When a hole is closed (pin added etc.),
# remove the row here and close the issue.
KNOWN_HOLES: dict[str, str] = {
    "origin.template_inherited": "https://github.com/Cor-Incorporated/grift-cli-dev/issues/11",
}


def test_coverage_file_exists_and_pins_current() -> None:
    text = COVERAGE_MD.read_text(encoding="utf-8")
    for pin_id in pin_ids():
        assert pin_id in text, f"{pin_id} missing from coverage.md"


def test_committed_table_matches_computed() -> None:
    matrix = compute_matrix()
    lines = COVERAGE_MD.read_text(encoding="utf-8").splitlines()
    table_lines = [
        line
        for line in lines
        if line.startswith("| ") and " | " in line and "field" not in line and "---" not in line
    ]
    by_label = {}
    for line in table_lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0] != "pin":
            by_label[cells[0]] = cells
    ids = pin_ids()
    for row in FIELD_ROWS:
        assert row.label in by_label, f"row {row.label} missing in coverage.md"
        cells = by_label[row.label]
        expected_cells = [matrix[row.path][i] for i in ids]
        actual_cells = cells[3 : 3 + len(ids)]
        assert actual_cells == expected_cells, (
            f"{row.label}: committed cells {actual_cells} != computed {expected_cells} — "
            "run scripts/gen_coverage_table.py and commit the result"
        )
        status = row_status(row, matrix[row.path])
        assert cells[3 + len(ids)] == status, (
            f"{row.label}: status cell {cells[3 + len(ids)]} != computed {status}"
        )


def test_holes_are_issue_tracked_and_not_stale() -> None:
    matrix = compute_matrix()
    holes = {row.path for row in FIELD_ROWS if row_status(row, matrix[row.path]) == STATUS_HOLE}
    untracked = holes - set(KNOWN_HOLES)
    assert not untracked, f"HOLE rows without an issue URL: {sorted(untracked)}"
    stale = set(KNOWN_HOLES) - holes
    assert not stale, (
        f"KNOWN_HOLES entries whose row is no longer a hole (close the issue and "
        f"remove the entry): {sorted(stale)}"
    )


def test_pin_count_within_master_limit() -> None:
    assert len(pin_ids()) <= 13, "master instruction §3-1: golden total must stay <= 13"


def test_every_pin_has_selection_metadata() -> None:
    import re
    import tomllib

    with (ROOT / "golden" / "pins.toml").open("rb") as handle:
        pins = tomllib.load(handle)["repos"]
    for pin in pins:
        match = re.match(r"G(\d+)-", pin["id"])
        if not match or int(match.group(1)) <= 5:
            continue  # G1-G5 predate the persona expansion
        tags = pin.get("tags") or {}
        for key in ("collaboration", "lifecycle", "era", "ecosystem", "persona_questions"):
            assert tags.get(key), f"{pin['id']}: tags.{key} missing"
        assert (pin.get("reason") or {}).get("text"), f"{pin['id']}: reason.text missing"
