"""golden/coverage.md must match the computed matrix and track HOLEs with issues.

Master instruction §3-2 / golden-v2 §1-1: holes must be explicit and issue-
tracked, never silent. This test (a) regenerates the table body and diffs it
against the committed file, (b) requires every HOLE row to appear in
KNOWN_HOLES with an issue URL, (c) forbids KNOWN_HOLES entries whose row is
no longer a hole (stale entries → update the table + close the issue).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from coverage_matrix import (  # noqa: E402
    FIELD_ROWS,
    REQUIREMENT_SYNTHETIC,
    STATUS_HOLE,
    STATUS_SYNTHETIC,
    compute_matrix,
    pin_ids,
    row_status,
)

COVERAGE_MD = ROOT / "golden" / "coverage.md"

# HOLE rows must carry an issue URL. When a hole is closed (pin added etc.),
# remove the row here and close the issue.
KNOWN_HOLES: dict[str, str] = {}

# The master limit was 13 pins. 0.9.6 raises it to 14 for exactly one pin:
# G1R-click-repo (issue #8). interpretation exists only at repo scope and every
# other pin runs at tenant scope, so no existing pin can excite it. The new pin
# reuses G1's click clone and sha (no extra clone cost) and a repo-scope analysis
# of one repo; raising the limit further needs a new rationale here.
MAX_PINS = 14


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


def test_actor_exactness_uses_synthetic_lane_not_public_expected() -> None:
    text = COVERAGE_MD.read_text(encoding="utf-8")
    assert "v0.6 supersession（2026-08-31）" in text
    assert "synthetic greenをblind pilotの代替にしない" in text

    matrix = compute_matrix()
    synthetic = [row for row in FIELD_ROWS if row.requirement == REQUIREMENT_SYNTHETIC]
    assert {row.path for row in synthetic} == {
        "experience.declared_ai_assist_share",
        "experience.cross_author_modification_share",
        "experience.founder_timing",
        "role_profile",
    }
    for row in synthetic:
        assert set(matrix[row.path].values()) == {"-"}, (
            f"{row.path}: actor fields must not be excited from public expected JSON"
        )
        assert row_status(row, matrix[row.path]) == STATUS_SYNTHETIC


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
    for field, url in KNOWN_HOLES.items():
        assert re.fullmatch(
            r"https://github\.com/Cor-Incorporated/grift-cli/issues/[1-9][0-9]*", url
        ), f"{field}: HOLE issue URL must use the public grift-cli repository: {url}"


def test_pin_count_within_master_limit() -> None:
    assert len(pin_ids()) <= MAX_PINS, (
        f"master instruction §3-1: golden total must stay <= {MAX_PINS} "
        "(13 + G1R-click-repo, issue #8)"
    )


def test_repo_scope_pin_shares_click_clone_with_g1() -> None:
    import tomllib

    with (ROOT / "golden" / "pins.toml").open("rb") as handle:
        pins = {pin["id"]: pin for pin in tomllib.load(handle)["repos"]}
    base, repo_pin = pins["G1-click"], pins["G1R-click-repo"]
    assert (repo_pin["url"], repo_pin["sha"]) == (base["url"], base["sha"])
    assert repo_pin["scope"] == "repo"
    assert not repo_pin["identity"]


def test_template_pin_and_repo_scope_pin_are_excited() -> None:
    matrix = compute_matrix()
    assert matrix["origin.template_inherited"]["G10-scvi-tools"] == "o"
    assert matrix["interpretation.test_cochange"]["G1R-click-repo"] == "o"
    assert matrix["interpretation.corrective_rework"]["G1R-click-repo"] == "o"


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
