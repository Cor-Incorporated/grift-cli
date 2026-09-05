"""project-v1: declared requirements and observed operating signature."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomllib

from tep_core.identity import CANONICAL_ID_RE
from tep_core.secrets_guard import InputValidationError, assert_no_secrets
from tep_core.v2_constants import INPUT_KINDS, ROLE_LENSES, SURFACES, VERIFICATION_TYPES
from tep_core.version import PROJECT_SCHEMA_VERSION, PROJECT_TOML_SCHEMA_VERSION

PROJECT_TEMPLATE = """schema_version = \"tep-project-v1\"
project_id = \"\"
title = \"\"

[requirements.change_rhythm]
# 未記入の値は要求なし。単位は日。CLI は空欄を 0 や不足にしない。
# active_days_180d_min =
# median_gap_days_max =
# p90_gap_days_max =

[requirements.surfaces]
required = []
# 任意: 面ごとに「その人の作業に占める最低比率」を宣言できる。
# 未記入なら従来どおり「観測があるか否か」の突合になる。
# [requirements.surfaces.min_share]
# backend = 0.20

[requirements.verification]
required = []
# [requirements.verification.min_share]
# unit = 0.10

[requirements.inputs]
required = []

[requirements.role_lens]
# name =
"""

_RHYTHM_KEYS = (
    "active_days_180d_min",
    "median_gap_days_max",
    "p90_gap_days_max",
)


def init_project_template(path: Path) -> None:
    if path.exists():
        raise InputValidationError("project --init refuses to overwrite an existing file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PROJECT_TEMPLATE, encoding="utf-8")


def _not_declared() -> dict[str, Any]:
    return {"kind": "not_declared", "reason": "requirement_not_provided"}



def _with_min_share(
    node: dict[str, Any],
    block: Any,
    allowed: list[str],
    label: str,
) -> dict[str, Any]:
    """Attach declared minimum shares, when the brief states any.

    A floor says what the work needs; it is not a correction applied to the
    observation, which is still reported as measured (norms §7). Omitting it
    keeps the presence comparison, so existing briefs are unchanged.
    """
    if not isinstance(block, dict):
        return node
    floors = block.get("min_share")
    if floors is None:
        return node
    if not isinstance(floors, dict):
        raise InputValidationError(f"project: {label} must be a table")
    parsed: dict[str, float] = {}
    for key, value in floors.items():
        if key not in allowed:
            raise InputValidationError(f"project: {label}.{key} is not in required")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputValidationError(f"project: {label}.{key} must be a number")
        if not 0 <= float(value) <= 1:
            raise InputValidationError(f"project: {label}.{key} must be between 0 and 1")
        parsed[key] = float(value)
    if parsed:
        node = {**node, "min_share": parsed}
    return node


def _declared(value: Any, unit: str) -> dict[str, Any]:
    return {"kind": "declared", "value": value, "unit": unit}


def _as_list(value: Any, path: str, allowed: tuple[str, ...]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InputValidationError(f"{path}: must be an array of strings")
    for item in value:
        if item not in allowed:
            raise InputValidationError(f"{path}: unsupported value")
    return list(value)


def load_project_toml(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    assert_no_secrets(raw, source="project")
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise InputValidationError("project: malformed TOML") from exc
    if not isinstance(data, dict):
        raise InputValidationError("project: root must be a table")
    schema = data.get("schema_version")
    if schema != PROJECT_TOML_SCHEMA_VERSION:
        raise InputValidationError("project: schema_version must be tep-project-v1")
    project_id = str(data.get("project_id") or "")
    if project_id and not CANONICAL_ID_RE.fullmatch(project_id):
        raise InputValidationError("project: project_id must match the canonical_id regex")
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        raise InputValidationError("project: title must be a string")
    requirements = data.get("requirements") or {}
    if not isinstance(requirements, dict):
        raise InputValidationError("project: requirements must be a table")
    return {
        "schema_version": schema,
        "project_id": project_id,
        "title": title or "",
        "requirements": requirements,
        "source_basename": path.name,
    }


def declared_view(loaded: dict[str, Any]) -> dict[str, Any]:
    req = loaded.get("requirements") or {}
    rhythm = req.get("change_rhythm") or {}
    if rhythm and not isinstance(rhythm, dict):
        raise InputValidationError("project: requirements.change_rhythm must be a table")
    declared_rhythm: dict[str, Any] = {}
    for key in _RHYTHM_KEYS:
        value = rhythm.get(key) if isinstance(rhythm, dict) else None
        if value is None:
            declared_rhythm[key] = _not_declared()
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InputValidationError(f"project: {key} must be a non-negative integer")
        declared_rhythm[key] = _declared(value, "days")

    surfaces = _as_list(
        (req.get("surfaces") or {}).get("required")
        if isinstance(req.get("surfaces"), dict)
        else None,
        "requirements.surfaces.required",
        SURFACES,
    )
    verification = _as_list(
        (req.get("verification") or {}).get("required")
        if isinstance(req.get("verification"), dict)
        else None,
        "requirements.verification.required",
        VERIFICATION_TYPES,
    )
    inputs = _as_list(
        (req.get("inputs") or {}).get("required") if isinstance(req.get("inputs"), dict) else None,
        "requirements.inputs.required",
        INPUT_KINDS,
    )
    lens_table = req.get("role_lens") if isinstance(req.get("role_lens"), dict) else {}
    lens_name = lens_table.get("name") if isinstance(lens_table, dict) else None
    if lens_name is not None and lens_name not in ROLE_LENSES:
        raise InputValidationError("project: requirements.role_lens.name is not a known lens")

    project_id = loaded.get("project_id") or ""
    return {
        "project_id": _declared(project_id, "id") if project_id else _not_declared(),
        "title": _declared(loaded.get("title") or "", "text")
        if loaded.get("title")
        else _not_declared(),
        "change_rhythm": declared_rhythm,
        "surfaces": (
            _with_min_share(
                _declared(surfaces, "surface-names"),
                req.get("surfaces"),
                surfaces,
                "requirements.surfaces.min_share",
            )
            if surfaces
            else _not_declared()
        ),
        "verification": (
            _with_min_share(
                _declared(verification, "verification-types"),
                req.get("verification"),
                verification,
                "requirements.verification.min_share",
            )
            if verification
            else _not_declared()
        ),
        "inputs": _declared(inputs, "input-kinds") if inputs else _not_declared(),
        "role_lens": _declared(lens_name, "lens") if lens_name else _not_declared(),
    }


def build_project_report(
    *,
    declared: dict[str, Any],
    observed: dict[str, Any] | None,
    provenance: dict[str, Any],
    subject: dict[str, Any],
    limitations: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "report_kind": "project",
        "subject": subject,
        "provenance": provenance,
        "declared": declared,
        "limitations": limitations,
        "notices": [
            "案件側の宣言と観測された運用の形は別セクションです。空欄を推測で埋めません。",
        ],
    }
    if observed is not None:
        payload["observed"] = observed
    else:
        payload["observed"] = {
            "kind": "not_observed",
            "reason": "repository_not_provided",
        }
    return payload


def empty_declared() -> dict[str, Any]:
    return declared_view(
        {
            "project_id": "",
            "title": "",
            "requirements": {},
        }
    )
