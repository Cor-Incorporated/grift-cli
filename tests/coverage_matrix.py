"""Golden coverage matrix: field x repo, computed from expected JSONs.

Shared by scripts/gen_coverage_table.py (writes golden/coverage.md) and
tests/test_coverage.py (verifies the committed table does not drift and that
holes are explicit, not silent). Wave-1 tracks existing report-v1 fields and
wave-2 tracks repo-level context detectors.  The historical wave-3
experience/role rows are retained as an explicit synthetic-only lane: current
v0.6 policy does not infer an identity in public-OSS golden repositories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "golden" / "expected"

REQUIREMENT_EXCITED = "excited"  # need >= 1 observed ('o')
REQUIREMENT_BOTH = "both"  # need >= 1 'o' AND >= 1 'x' (new observations)
REQUIREMENT_INFO = "info"  # shown for context; no machine requirement
REQUIREMENT_SYNTHETIC = "synthetic"  # actor exactness is tested outside public golden
STATUS_HOLE = "HOLE"  # requirement unmet — must be listed with an issue
STATUS_SYNTHETIC = "synthetic"  # intentional '-' cells; not a public-golden gap


@dataclass(frozen=True)
class FieldRow:
    path: str
    label: str
    wave: str
    requirement: str
    note: str = ""


# Wave-1 map over existing report-v1 fields. `path` navigates the expected
# JSON; a path ending ".kind" yields the cell directly, otherwise the node's
# kind is read (dicts carry kind=observed/not_observed).
FIELD_ROWS: tuple[FieldRow, ...] = (
    FieldRow("origin.tenant_unique", "origin: tenant_unique", "1", REQUIREMENT_EXCITED),
    FieldRow(
        "origin.tenant_merge_or_sync", "origin: tenant_merge_or_sync", "1", REQUIREMENT_EXCITED
    ),
    FieldRow("origin.upstream_sync", "origin: upstream_sync", "1", REQUIREMENT_EXCITED),
    FieldRow("origin.inherited_upstream", "origin: inherited_upstream", "1", REQUIREMENT_EXCITED),
    FieldRow(
        "origin.generated_or_vendor",
        "origin: generated_or_vendor",
        "1",
        REQUIREMENT_EXCITED,
        "--vendor-scan ピンなし（全 pin で observed 0）",
    ),
    FieldRow(
        "origin.template_inherited",
        "origin: template_inherited",
        "1",
        REQUIREMENT_EXCITED,
        "--template ピンなし（全 pin not_observed）",
    ),
    FieldRow(
        "origin.tenant_derivative",
        "origin: tenant_derivative",
        "1",
        REQUIREMENT_INFO,
        "--parent-repo ピンなし（設計上 not_observed）",
    ),
    FieldRow(
        "origin.external_upstream_contribution",
        "origin: external_upstream_contribution",
        "1",
        REQUIREMENT_INFO,
        "--parent-repo ピンなし（設計上 not_observed）",
    ),
    FieldRow(
        "origin.ambiguous_origin",
        "origin: ambiguous_origin",
        "1",
        REQUIREMENT_INFO,
        "空メール fixture のみで励起（golden では observed 0）",
    ),
    FieldRow("origin.unresolved", "origin: unresolved", "1", REQUIREMENT_EXCITED),
    FieldRow("origin.bot", "origin: bot", "1", REQUIREMENT_EXCITED),
    FieldRow("attribution.bot", "attribution: bot", "1", REQUIREMENT_EXCITED),
    FieldRow("activity.active_days", "activity: active_days", "1", REQUIREMENT_EXCITED),
    FieldRow(
        "activity.commits_per_active_day_median", "activity: cpad median", "1", REQUIREMENT_EXCITED
    ),
    FieldRow("activity.active_days_13w", "activity: active_days_13w", "1", REQUIREMENT_EXCITED),
    FieldRow("core_activity_period", "core_activity_period", "1", REQUIREMENT_EXCITED),
    FieldRow("test_frameworks", "test_frameworks", "1", REQUIREMENT_BOTH),
    FieldRow("test_cochange", "test_cochange", "1", REQUIREMENT_BOTH),
    FieldRow(
        "rework.corrective_rework_rate", "rework: corrective_rework_rate", "1", REQUIREMENT_BOTH
    ),
    FieldRow("rework.path_retouch_rate", "rework: path_retouch_rate", "1", REQUIREMENT_BOTH),
    FieldRow(
        "rework.revert_rate",
        "rework: revert_rate",
        "1",
        REQUIREMENT_EXCITED,
        "G1 expected は subset（revert_rate 未ピン）→ 再生成必要",
    ),
    FieldRow(
        "survival",
        "survival",
        "1",
        REQUIREMENT_INFO,
        "opt-in（--survival）。golden では恒常 not_observed。corpus runs で実測",
    ),
    FieldRow(
        "interpretation",
        "interpretation",
        "1",
        REQUIREMENT_INFO,
        "repo スコープ専用。golden は tenant スコープ（scope_is_tenant）。corpus v2026.09 で励起",
    ),
    # --- wave 2: public-OSS, repo-level detector placeholders ---
    FieldRow(
        "context_profile.lifecycle_stage",
        "context v2: lifecycle_stage",
        "2",
        REQUIREMENT_BOTH,
        "repo-level detector。public golden expected未ピン、release acceptance未証明",
    ),
    FieldRow(
        "context_profile.language_composition",
        "context v2: language_composition",
        "2",
        REQUIREMENT_BOTH,
        "repo-level detector。public golden expected未ピン、release acceptance未証明",
    ),
    # --- historical wave 3: actor exactness moved to exact synthetic tests ---
    # A public actor or identity-less repository must remain not_observed for
    # experience/role.  '-' is intentional here; never manufacture an identity
    # or regenerate expected JSON merely to excite these rows.
    FieldRow(
        "experience.declared_ai_assist_share",
        "experience: declared_ai_assist_share",
        "3",
        REQUIREMENT_SYNTHETIC,
        "public OSSではactor観測しない。exact synthetic + blind pilotで検証",
    ),
    FieldRow(
        "experience.cross_author_modification_share",
        "experience: cross_author_modification_share",
        "3",
        REQUIREMENT_SYNTHETIC,
        "public OSSではactor観測しない。exact synthetic + blind pilotで検証",
    ),
    FieldRow(
        "experience.founder_timing",
        "experience: founder 時期性",
        "3",
        REQUIREMENT_SYNTHETIC,
        "public OSSではactor観測しない。exact synthetic + blind pilotで検証",
    ),
    FieldRow(
        "role_profile",
        "role_profile: 4 dimensions",
        "3",
        REQUIREMENT_SYNTHETIC,
        "public OSSではactor観測しない。exact synthetic + blind pilotで検証",
    ),
)


def load_expected(pin_id: str) -> dict:
    return json.loads((EXPECTED / f"{pin_id}.json").read_text(encoding="utf-8"))


def pin_ids() -> list[str]:
    import tomllib

    with (ROOT / "golden" / "pins.toml").open("rb") as handle:
        return [pin["id"] for pin in tomllib.load(handle)["repos"]]


def _navigate(payload: dict, path: str):
    node = payload
    for key in path.split("."):
        if not isinstance(node, dict):
            return ("stop", node)
        if key not in node:
            # A not_observed parent legitimately has no children: the child
            # cell inherits the parent's not_observed.
            if node.get("kind") == "not_observed":
                return ("not_observed", node)
            return ("missing", None)
        node = node[key]
    return ("ok", node)


def cell_for(payload: dict, row: FieldRow) -> str:
    status, node = _navigate(payload, row.path)
    if status == "not_observed":
        return "x"
    if status != "ok" or node is None:
        return "-"
    kind = node.get("kind") if isinstance(node, dict) else None
    if kind == "observed":
        return "o"
    if kind == "not_observed":
        return "x"
    return "-"


CURRENT_WAVE = 1


def compute_matrix() -> dict[str, dict[str, str]]:
    ids = pin_ids()
    payloads = {pin_id: load_expected(pin_id) for pin_id in ids}
    return {
        row.path: {pin_id: cell_for(payloads[pin_id], row) for pin_id in ids} for row in FIELD_ROWS
    }


def row_status(row: FieldRow, cells: dict[str, str]) -> str:
    if row.requirement == REQUIREMENT_SYNTHETIC:
        return STATUS_SYNTHETIC
    if int(row.wave) > CURRENT_WAVE:
        return "future"
    values = list(cells.values())
    has_o = "o" in values
    has_x = "x" in values
    if row.requirement == REQUIREMENT_EXCITED and not has_o:
        return STATUS_HOLE
    if row.requirement == REQUIREMENT_BOTH and not (has_o and has_x):
        return STATUS_HOLE
    return "ok"
