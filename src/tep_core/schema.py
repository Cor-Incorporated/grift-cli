"""report-v1 structural schema (frozen 2026-08-22).

Pure standard library. Additive-only while report-v1 lives: new fields and
new reason codes may appear; renaming, removing, or re-semanting an existing
field requires report-v2. Unknown keys are therefore permitted so that
consumers pinned to report-v1 keep working across patch releases.
"""

from __future__ import annotations

import json
import math
import re
import hashlib
from datetime import date, datetime
from copy import deepcopy
from functools import lru_cache
from importlib import resources
from urllib.parse import urlparse
from typing import Any

from tep_core.origin import ORIGIN_CLASSES
from tep_core.version import REPORT_SCHEMA_VERSION

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

SCOPES = ("tenant", "repo")


def validate_report(report: Any, *, subset: bool = False) -> list[str]:
    """Validate a report dict against report-v1. Returns violation paths."""
    errors: list[str] = []
    ctx = _Ctx(errors, subset)
    if not isinstance(report, dict):
        ctx.err("$", "report must be a JSON object")
        return errors
    ctx.eq("$.schema_version", report.get("schema_version"), REPORT_SCHEMA_VERSION)
    _provenance(ctx, report.get("provenance"))
    _repository(ctx, report.get("repository"))
    _identity(ctx, report.get("identity"))
    _lineage(ctx, report.get("lineage"))
    _origin(ctx, report.get("origin"))
    _attribution(ctx, report.get("attribution"))
    _activity(ctx, report.get("activity"))
    _core_period(ctx, report.get("core_activity_period"))
    _test_frameworks(ctx, report.get("test_frameworks"))
    _cochange(ctx, report.get("test_cochange"))
    _rework(ctx, report.get("rework"))
    _survival(ctx, report.get("survival"))
    _interpretation(ctx, report.get("interpretation"))
    return errors


class _Ctx:
    def __init__(self, errors: list[str], subset: bool) -> None:
        self.errors = errors
        self.subset = subset

    def err(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def eq(self, path: str, value: Any, expected: Any) -> None:
        if value != expected:
            self.err(path, f"must be {expected!r}")

    def missing(self, path: str) -> bool:
        if self.subset:
            return True
        self.err(path, "required key missing")
        return True


def _req(ctx: _Ctx, node: dict, key: str, path: str) -> tuple[bool, Any]:
    if key not in node:
        if not ctx.subset:
            ctx.err(path, "required key missing")
        return False, None
    return True, node[key]


def _opt(ctx: _Ctx, node: dict, key: str, path: str) -> tuple[bool, Any]:
    if key not in node:
        return False, None
    return True, node[key]


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _observation(
    ctx: _Ctx,
    node: Any,
    path: str,
    *,
    value_check: str,
    unit: str | None = None,
    sample: bool = True,
) -> None:
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    kind = node.get("kind")
    if kind == "not_observed":
        reason = node.get("reason")
        if not _is_str(reason) or not _REASON_RE.match(reason):
            ctx.err(f"{path}.reason", "must be a snake_case string")
        return
    if kind != "observed":
        ctx.err(f"{path}.kind", "must be 'observed' or 'not_observed'")
        return
    checks = {
        "int>=0": lambda v: _is_int(v) and v >= 0,
        "num>=0": lambda v: _is_num(v) and v >= 0,
        "ratio": lambda v: _is_num(v) and 0 <= v <= 1,
        "bool": _is_bool,
        "true": lambda v: v is True,
        "num": _is_num,
        "int>=1": lambda v: _is_int(v) and v >= 1,
    }
    if value_check not in checks:
        raise ValueError(f"unknown value_check {value_check}")
    if not checks[value_check](node.get("value")):
        ctx.err(f"{path}.value", f"fails check {value_check}")
    if unit is not None and node.get("unit") != unit:
        ctx.err(f"{path}.unit", f"must be {unit!r}")
    if sample:
        has, size = _opt(ctx, node, "sample_size", f"{path}.sample_size")
        if has and not (_is_int(size) and size >= 1):
            ctx.err(f"{path}.sample_size", "must be an integer >= 1")


def _provenance(ctx: _Ctx, node: Any) -> None:
    path = "$.provenance"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    for key in (
        "tool_name",
        "method_name",
        "definition_version",
        "origin_definition_version",
        "activity_definition_version",
    ):
        has, value = _req(ctx, node, key, f"{path}.{key}")
        if has and not _is_str(value):
            ctx.err(f"{path}.{key}", "must be a string")
    has, value = _req(ctx, node, "tool_version", f"{path}.tool_version")
    if has and not (_is_str(value) and _SEMVER_RE.match(value)):
        ctx.err(f"{path}.tool_version", "must be SEMVER")
    has, value = _req(ctx, node, "analysis_scope", f"{path}.analysis_scope")
    if has and value not in SCOPES:
        ctx.err(f"{path}.analysis_scope", "must be 'tenant' or 'repo'")
    has, value = _req(ctx, node, "analyzed_commit_sha", f"{path}.analyzed_commit_sha")
    if has and not (_is_str(value) and _SHA_RE.match(value)):
        ctx.err(f"{path}.analyzed_commit_sha", "must be a 40-char lowercase hex sha")
    has, value = _req(ctx, node, "analyzed_at", f"{path}.analyzed_at")
    if has and not (_is_str(value) and _TS_RE.match(value)):
        ctx.err(f"{path}.analyzed_at", "must be UTC YYYY-MM-DDTHH:MM:SSZ")


def _repository(ctx: _Ctx, node: Any) -> None:
    path = "$.repository"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    has, value = _req(ctx, node, "name", f"{path}.name")
    if has and not _is_str(value):
        ctx.err(f"{path}.name", "must be a string")
    _req(ctx, node, "remote", f"{path}.remote")
    has, value = _opt(ctx, node, "path", f"{path}.path")
    if has and not _is_str(value):
        ctx.err(f"{path}.path", "must be a string")


def _identity(ctx: _Ctx, node: Any) -> None:
    path = "$.identity"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    has, value = _req(ctx, node, "pending_attribution", f"{path}.pending_attribution")
    if has and not _is_bool(value):
        ctx.err(f"{path}.pending_attribution", "must be a boolean")
    has, value = _req(ctx, node, "actor_count", f"{path}.actor_count")
    if has and not (_is_int(value) and value >= 0):
        ctx.err(f"{path}.actor_count", "must be an integer >= 0")


def _lineage(ctx: _Ctx, node: Any) -> None:
    path = "$.lineage"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    for key in ("is_fork", "has_upstream_lineage"):
        has, value = _req(ctx, node, key, f"{path}.{key}")
        if has and not _is_bool(value):
            ctx.err(f"{path}.{key}", "must be a boolean")
    has, value = _req(ctx, node, "parent", f"{path}.parent")
    if has and value is not None and not _is_str(value):
        ctx.err(f"{path}.parent", "must be a string or null")


def _origin(ctx: _Ctx, node: Any) -> None:
    path = "$.origin"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    for name in ORIGIN_CLASSES:
        _observation(
            ctx,
            node.get(name),
            f"{path}.{name}",
            value_check="int>=0",
            unit="commits",
            sample=False,
        )


def _attribution(ctx: _Ctx, node: Any) -> None:
    path = "$.attribution"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    _observation(
        ctx,
        node.get("bot"),
        f"{path}.bot",
        value_check="int>=0",
        unit="commits",
        sample=False,
    )


def _activity(ctx: _Ctx, node: Any) -> None:
    path = "$.activity"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    _observation(
        ctx,
        node.get("tenant_commits"),
        f"{path}.tenant_commits",
        value_check="int>=0",
        unit="commits",
        sample=False,
    )
    _observation(
        ctx,
        node.get("active_days"),
        f"{path}.active_days",
        value_check="int>=0",
        unit="days",
        sample=False,
    )
    _observation(
        ctx,
        node.get("commits_per_active_day"),
        f"{path}.commits_per_active_day",
        value_check="num>=0",
        unit="commits/active-day",
        sample=False,
    )
    _observation(
        ctx,
        node.get("commits_per_active_day_median"),
        f"{path}.commits_per_active_day_median",
        value_check="num>=0",
        unit="commits/active-day",
    )
    _observation(
        ctx,
        node.get("active_days_13w"),
        f"{path}.active_days_13w",
        value_check="int>=0",
        unit="days",
        sample=False,
    )


def _core_period(ctx: _Ctx, node: Any) -> None:
    path = "$.core_activity_period"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="num")
        return
    has, value = _req(ctx, node, "start", f"{path}.start")
    if has and not (_is_str(value) and _MONTH_RE.match(value)):
        ctx.err(f"{path}.start", "must be YYYY-MM")
    has, value = _req(ctx, node, "end", f"{path}.end")
    if has and not (_is_str(value) and _MONTH_RE.match(value)):
        ctx.err(f"{path}.end", "must be YYYY-MM")
    has, value = _req(ctx, node, "share", f"{path}.share")
    if has and not (_is_num(value) and 0 <= value <= 1):
        ctx.err(f"{path}.share", "must be a ratio 0..1")
    if node.get("unit") != "month-range":
        ctx.err(f"{path}.unit", "must be 'month-range'")
    has, value = _req(ctx, node, "definition_version", f"{path}.definition_version")
    if has and not _is_str(value):
        ctx.err(f"{path}.definition_version", "must be a string")


def _test_frameworks(ctx: _Ctx, node: Any) -> None:
    path = "$.test_frameworks"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="bool")
        return
    if node.get("value") is not True:
        ctx.err(f"{path}.value", "must be true when observed")
    if node.get("unit") != "boolean":
        ctx.err(f"{path}.unit", "must be 'boolean'")
    for key in ("names", "directories"):
        has, value = _opt(ctx, node, key, f"{path}.{key}")
        if has and not (isinstance(value, list) and all(_is_str(v) for v in value)):
            ctx.err(f"{path}.{key}", "must be an array of strings")


def _rate_block(ctx: _Ctx, node: Any, path: str) -> None:
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="num")
        return
    _observation(ctx, node, path, value_check="ratio", unit="ratio", sample=False)
    for key, minimum in (
        ("population", 0),
        ("cochanged", 0),
        ("test_only", 0),
        ("docs_or_config_excluded", 0),
    ):
        has, value = _opt(ctx, node, key, f"{path}.{key}")
        if has and not (_is_int(value) and value >= minimum):
            ctx.err(f"{path}.{key}", "must be an integer >= 0")
    has, value = _opt(ctx, node, "narrate_rate", f"{path}.narrate_rate")
    if has and not _is_bool(value):
        ctx.err(f"{path}.narrate_rate", "must be a boolean")


def _cochange(ctx: _Ctx, node: Any) -> None:
    path = "$.test_cochange"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="num")
        return
    for key in ("definition_version",):
        has, value = _opt(ctx, node, key, f"{path}.{key}")
        if has and not _is_str(value):
            ctx.err(f"{path}.{key}", "must be a string")
    has, value = _opt(ctx, node, "analysis_scope", f"{path}.analysis_scope")
    if has and value not in SCOPES:
        ctx.err(f"{path}.analysis_scope", "must be 'tenant' or 'repo'")
    _rate_block(ctx, node.get("all_time"), f"{path}.all_time")
    has, window = _opt(ctx, node, "last_13w", f"{path}.last_13w")
    if has and isinstance(window, dict) and window.get("kind") != "not_observed":
        _rate_block(ctx, window, f"{path}.last_13w")


def _rework_rate(
    ctx: _Ctx,
    node: Any,
    path: str,
    *,
    count_key: str,
    evidence_claim: bool | None,
) -> None:
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    _observation(ctx, node, path, value_check="ratio", unit="ratio", sample=False)
    for key, minimum in ((count_key, 0), ("population", 0)):
        has, value = _opt(ctx, node, key, f"{path}.{key}")
        if has and not (_is_int(value) and value >= minimum):
            ctx.err(f"{path}.{key}", "must be an integer >= 0")
    has, value = _opt(ctx, node, "narrate_rate", f"{path}.narrate_rate")
    if has and not _is_bool(value):
        ctx.err(f"{path}.narrate_rate", "must be a boolean")
    has, value = _opt(ctx, node, "evidence_claim", f"{path}.evidence_claim")
    if has and evidence_claim is not None and value != evidence_claim:
        ctx.err(f"{path}.evidence_claim", f"must be {evidence_claim!r}")


def _rework(ctx: _Ctx, node: Any) -> None:
    path = "$.rework"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="num")
        return
    has, value = _opt(ctx, node, "definition_version", f"{path}.definition_version")
    if has and not _is_str(value):
        ctx.err(f"{path}.definition_version", "must be a string")
    has, value = _opt(ctx, node, "analysis_scope", f"{path}.analysis_scope")
    if has and value not in SCOPES:
        ctx.err(f"{path}.analysis_scope", "must be 'tenant' or 'repo'")
    has, value = _opt(ctx, node, "window_days", f"{path}.window_days")
    if has and not (_is_int(value) and value >= 1):
        ctx.err(f"{path}.window_days", "must be an integer >= 1")
    _rework_rate(
        ctx,
        node.get("corrective_rework_rate"),
        f"{path}.corrective_rework_rate",
        count_key="corrective_commits",
        evidence_claim=False,
    )
    _rework_rate(
        ctx,
        node.get("path_retouch_rate"),
        f"{path}.path_retouch_rate",
        count_key="retouch_commits",
        evidence_claim=False,
    )
    _rework_rate(
        ctx,
        node.get("revert_rate"),
        f"{path}.revert_rate",
        count_key="reverts",
        evidence_claim=None,
    )
    line = node.get("line_rework")
    if line is not None:
        _observation(ctx, line, f"{path}.line_rework", value_check="num")


def _survival(ctx: _Ctx, node: Any) -> None:
    path = "$.survival"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="num")
        return
    _observation(ctx, node, path, value_check="num", unit="dimensionless", sample=False)
    for key, minimum in (
        ("tau_days", 1),
        ("files_sampled", 1),
        ("source_files", 1),
        ("lines_sampled", 1),
    ):
        has, value = _req(ctx, node, key, f"{path}.{key}")
        if has and not (_is_int(value) and value >= minimum):
            ctx.err(f"{path}.{key}", f"must be an integer >= {minimum}")
    has, value = _opt(ctx, node, "definition_version", f"{path}.definition_version")
    if has and not _is_str(value):
        ctx.err(f"{path}.definition_version", "must be a string")


def _interp_entry(ctx: _Ctx, node: Any, path: str) -> None:
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    if node.get("kind") == "not_observed":
        _observation(ctx, node, path, value_check="num")
        return
    _observation(ctx, node, path, value_check="ratio", sample=False)
    for key in ("reference_version", "unit", "metric_id"):
        has, value = _req(ctx, node, key, f"{path}.{key}")
        if has and not _is_str(value):
            ctx.err(f"{path}.{key}", "must be a string")
    if node.get("analysis_scope") != "repo":
        ctx.err(f"{path}.analysis_scope", "must be 'repo'")
    has, value = _req(ctx, node, "n", f"{path}.n")
    if has and not (_is_int(value) and value >= 1):
        ctx.err(f"{path}.n", "must be an integer >= 1")
    has, value = _req(ctx, node, "decile", f"{path}.decile")
    if has and not (_is_int(value) and 1 <= value <= 10):
        ctx.err(f"{path}.decile", "must be an integer 1..10")


def _interpretation(ctx: _Ctx, node: Any) -> None:
    path = "$.interpretation"
    if node is None:
        ctx.missing(path)
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    _interp_entry(ctx, node.get("test_cochange"), f"{path}.test_cochange")
    _interp_entry(ctx, node.get("corrective_rework"), f"{path}.corrective_rework")


# v0.6 strict contracts -----------------------------------------------------
#
# report-v1 above is intentionally additive.  New v0.6 contracts use the
# asset-backed validator below instead: every fixed-shape object is closed and
# cross-field invariants are checked after structural validation.  Keeping the
# two entry points separate prevents tightening v0.6 from breaking frozen v1
# consumers.

_CONTRACT_CATALOG = "v060-contracts.schema.json"


@lru_cache(maxsize=1)
def _contract_catalog() -> dict[str, Any]:
    package = resources.files("tep_core.schemas")
    with package.joinpath(_CONTRACT_CATALOG).open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    if catalog.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise RuntimeError("v0.6 schema catalog must declare Draft 2020-12")
    definitions = catalog.get("$defs")
    if not isinstance(definitions, dict) or not definitions:
        raise RuntimeError("v0.6 schema catalog has no $defs")
    return catalog


def schema_names() -> tuple[str, ...]:
    """Return the public strict-contract names shipped with grift."""

    catalog = _contract_catalog()
    names = catalog.get("x-grift-contracts")
    if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
        raise RuntimeError("v0.6 schema catalog has an invalid contract index")
    return tuple(names)


def load_schema(name: str) -> dict[str, Any]:
    """Load one self-contained Draft 2020-12 contract schema.

    A deep copy is returned so callers cannot mutate the process-wide catalog.
    ``jsonschema.Draft202012Validator`` can validate this object directly in
    development; the runtime validator below remains standard-library only.
    """

    if name not in schema_names():
        raise ValueError(f"unknown v0.6 schema {name!r}")
    catalog = _contract_catalog()
    return {
        "$schema": catalog["$schema"],
        "$id": f"https://grift.dev/schema/v060/{name}.schema.json",
        "$defs": deepcopy(catalog["$defs"]),
        "$ref": f"#/$defs/{name}",
    }


def validate_schema(name: str, instance: Any) -> list[str]:
    """Validate a v0.6 contract without importing a third-party package.

    Returned entries are stable JSON-path-like strings.  Structural checks are
    driven by the shipped Draft 2020-12 asset; arithmetic, interval and
    membership rules use the catalog's ``x-grift-invariants`` extension.
    """

    schema = load_schema(name)
    errors: list[str] = []
    _validate_json_schema(instance, schema, schema, "$", errors)
    if not errors:
        _validate_contract_invariants(name, instance, errors)
    return errors


def _json_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _resolve_schema_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise RuntimeError(f"external schema reference is forbidden: {ref}")
    node: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            raise RuntimeError(f"unresolved schema reference: {ref}")
        node = node[key]
    if not isinstance(node, dict):
        raise RuntimeError(f"schema reference does not resolve to an object: {ref}")
    return node


def _branch_valid(value: Any, branch: dict[str, Any], root: dict[str, Any]) -> bool:
    branch_errors: list[str] = []
    _validate_json_schema(value, branch, root, "$", branch_errors)
    return not branch_errors


def _validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        _validate_json_schema(value, _resolve_schema_ref(root, ref), root, path, errors)
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: must be one of {enum!r}")

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for branch in all_of:
            _validate_json_schema(value, branch, root, path, errors)
    conditional = schema.get("if")
    if isinstance(conditional, dict):
        selected = (
            schema.get("then") if _branch_valid(value, conditional, root) else schema.get("else")
        )
        if isinstance(selected, dict):
            _validate_json_schema(value, selected, root, path, errors)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(
        _branch_valid(value, branch, root) for branch in any_of
    ):
        errors.append(f"{path}: must match at least one allowed shape")
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        count = sum(_branch_valid(value, branch, root) for branch in one_of)
        if count != 1:
            errors.append(f"{path}: must match exactly one allowed shape (matched {count})")
    not_schema = schema.get("not")
    if isinstance(not_schema, dict) and _branch_valid(value, not_schema, root):
        errors.append(f"{path}: matches a forbidden shape")

    expected = schema.get("type")
    if isinstance(expected, str):
        allowed_types = [expected]
    elif isinstance(expected, list):
        allowed_types = [item for item in expected if isinstance(item, str)]
    else:
        allowed_types = []
    if allowed_types and not any(_json_type(value, item) for item in allowed_types):
        errors.append(f"{path}: must be type {' or '.join(allowed_types)}")
        return

    if isinstance(value, dict):
        _validate_schema_object(value, schema, root, path, errors)
    elif isinstance(value, list):
        _validate_schema_array(value, schema, root, path, errors)
    elif isinstance(value, str):
        _validate_schema_string(value, schema, path, errors)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_schema_number(value, schema, path, errors)


def _validate_schema_object(
    value: dict[str, Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    required = schema.get("required") or []
    for key in required:
        if key not in value:
            errors.append(f"{path}.{key}: required key missing")
    minimum = schema.get("minProperties")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: needs at least {minimum} properties")
    maximum = schema.get("maxProperties")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: allows at most {maximum} properties")

    properties = schema.get("properties") or {}
    patterns = schema.get("patternProperties") or {}
    additional = schema.get("additionalProperties", True)
    for key, child in value.items():
        child_path = f"{path}.{key}"
        if key in properties:
            _validate_json_schema(child, properties[key], root, child_path, errors)
            continue
        matching = [node for pattern, node in patterns.items() if re.search(pattern, key)]
        if matching:
            for node in matching:
                _validate_json_schema(child, node, root, child_path, errors)
            continue
        if additional is False:
            errors.append(f"{child_path}: unknown key")
        elif isinstance(additional, dict):
            _validate_json_schema(child, additional, root, child_path, errors)

    property_names = schema.get("propertyNames")
    if isinstance(property_names, dict):
        for key in value:
            _validate_json_schema(key, property_names, root, f"{path}.{key}<key>", errors)
    dependencies = schema.get("dependentRequired") or {}
    for key, needed in dependencies.items():
        if key in value:
            for required_key in needed:
                if required_key not in value:
                    errors.append(f"{path}.{required_key}: required when {path}.{key} is present")


def _validate_schema_array(
    value: list[Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    minimum = schema.get("minItems")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: needs at least {minimum} items")
    maximum = schema.get("maxItems")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: allows at most {maximum} items")
    if schema.get("uniqueItems") is True:
        seen: set[str] = set()
        for index, item in enumerate(value):
            marker = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if marker in seen:
                errors.append(f"{path}[{index}]: duplicate item")
            seen.add(marker)
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate_json_schema(item, item_schema, root, f"{path}[{index}]", errors)


def _validate_schema_string(
    value: str, schema: dict[str, Any], path: str, errors: list[str]
) -> None:
    minimum = schema.get("minLength")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: must contain at least {minimum} characters")
    maximum = schema.get("maxLength")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: must contain at most {maximum} characters")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        errors.append(f"{path}: does not match {pattern!r}")
    fmt = schema.get("format")
    if fmt == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"{path}: must be an RFC 3339 full-date")
    elif fmt == "date-time":
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None:
            errors.append(f"{path}: must be an RFC 3339 date-time with timezone")
    elif fmt == "uri":
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "ssh"} or not parsed.netloc:
            errors.append(f"{path}: must be an absolute https or ssh URI")


def _validate_schema_number(
    value: int | float, schema: dict[str, Any], path: str, errors: list[str]
) -> None:
    if not math.isfinite(float(value)):
        errors.append(f"{path}: must be finite")
        return
    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and value < minimum:
        errors.append(f"{path}: must be >= {minimum}")
    maximum = schema.get("maximum")
    if isinstance(maximum, (int, float)) and value > maximum:
        errors.append(f"{path}: must be <= {maximum}")
    exclusive_minimum = schema.get("exclusiveMinimum")
    if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
        errors.append(f"{path}: must be > {exclusive_minimum}")
    exclusive_maximum = schema.get("exclusiveMaximum")
    if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
        errors.append(f"{path}: must be < {exclusive_maximum}")


def _validate_contract_invariants(name: str, instance: Any, errors: list[str]) -> None:
    if not isinstance(instance, dict):
        return
    _walk_numeric_invariants(instance, "$", errors)
    _walk_windows(instance, "$", errors)
    if name == "actor-index-v1":
        _actor_index_invariants(instance, errors)
    elif name == "actor-card-v1":
        _actor_card_invariants(instance, errors)
    elif name == "report-v2":
        _report_v2_invariants(instance, errors)
    elif name == "alignment-v1":
        _alignment_invariants(instance, errors)
    elif name == "public-evidence-v1":
        _public_evidence_invariants(instance, errors)
    elif name == "contribution-v2":
        _contribution_invariants(instance, errors)
    elif name == "attest-bundle-v1":
        _attest_bundle_invariants(instance, errors)
    elif name == "portfolio-v1":
        _portfolio_invariants(instance, errors)
    elif name == "portfolio-manifest-v1":
        _portfolio_manifest_invariants(instance, errors)
    elif name == "scenario-summary-v1":
        _scenario_summary_invariants(instance, errors)
    elif name in {"forge-export-v2", "tracker-export-v2"}:
        _bound_export_invariants(instance, errors)
    elif name == "identity-v2":
        _identity_v2_invariants(instance, errors)
    elif name == "experience-v1":
        _experience_invariants(instance, errors)
    elif name == "role-profile-v1":
        _role_profile_invariants(instance, errors)


def _walk_numeric_invariants(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        numerator = node.get("numerator")
        denominator = node.get("denominator")
        n = node.get("n")
        if _is_int(numerator) and _is_int(denominator):
            if numerator > denominator:
                errors.append(f"{path}.numerator: must not exceed denominator")
            unit = node.get("unit")
            if (
                isinstance(unit, str)
                and (unit == "ratio" or unit.endswith("_share"))
                and _is_num(node.get("value"))
            ):
                expected = numerator / denominator if denominator else 0.0
                accepted = {round(expected, 4), round(expected, 12), expected}
                if not any(
                    math.isclose(float(node["value"]), item, rel_tol=0.0, abs_tol=1e-12)
                    for item in accepted
                ):
                    errors.append(f"{path}.value: must equal numerator / denominator")
        if _is_int(n) and _is_int(denominator) and n > denominator:
            errors.append(f"{path}.n: must not exceed denominator")
        for key, value in node.items():
            _walk_numeric_invariants(value, f"{path}.{key}", errors)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_numeric_invariants(value, f"{path}[{index}]", errors)


def _walk_windows(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        start = node.get("start")
        end = node.get("end")
        if isinstance(start, str) and isinstance(end, str):
            left = _temporal_value(start)
            right = _temporal_value(end)
            if left is not None and right is not None and left > right:
                errors.append(f"{path}: window start must not be after end")
        for key, value in node.items():
            _walk_windows(value, f"{path}.{key}", errors)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_windows(value, f"{path}[{index}]", errors)


def _temporal_value(value: str) -> datetime | date | None:
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.fromisoformat(value)
    except ValueError:
        return None


def _actor_index_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    actors = instance.get("actors") or []
    population = instance.get("population") or {}
    selection = instance.get("selection") or {}
    if population.get("actor_count") != len(actors):
        errors.append("$.population.actor_count: must equal len($.actors)")
    actor_ids = {actor.get("actor_id") for actor in actors if isinstance(actor, dict)}
    selected = selection.get("actor_ids") or []
    if selection.get("selected_count") != len(selected):
        errors.append("$.selection.selected_count: must equal len($.selection.actor_ids)")
    missing = sorted(set(selected) - actor_ids)
    if missing:
        errors.append(
            "$.selection.actor_ids: IDs are not members of $.actors: " + ",".join(missing)
        )
    actor_commit_total = 0
    for index, actor in enumerate(actors):
        if not isinstance(actor, dict):
            continue
        commit_count = actor.get("commit_count")
        nonmerge = actor.get("nonmerge_commit_count")
        merges = actor.get("merge_commit_count")
        if _is_int(commit_count):
            actor_commit_total += commit_count
        if _is_int(commit_count) and _is_int(nonmerge) and _is_int(merges):
            if nonmerge + merges != commit_count:
                errors.append(
                    f"$.actors[{index}].commit_count: must equal nonmerge_commit_count + merge_commit_count"
                )
    if population.get("human_commit_count") != actor_commit_total:
        errors.append("$.population.human_commit_count: must equal the actor commit total")
    if selection.get("mode") == "all" and set(selected) != actor_ids:
        errors.append("$.selection.actor_ids: all mode must select every actor")


def _actor_card_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    status = instance.get("account_status")
    accounts = instance.get("accounts") or []
    if status == "matched" and len(accounts) != 1:
        errors.append("$.accounts: matched account_status requires exactly one account")
    if status in {"not_requested", "unsupported", "unavailable", "unmatched"} and accounts:
        errors.append(f"$.accounts: must be empty when account_status is {status}")
    if status == "ambiguous" and len(accounts) < 2:
        errors.append("$.accounts: ambiguous account_status requires at least two accounts")
    actor_id = instance.get("actor_id")
    for key in ("experience", "role_profile"):
        detail = instance.get(key)
        if isinstance(detail, dict) and detail.get("actor_id") != actor_id:
            errors.append(f"$.{key}.actor_id: must equal $.actor_id")


def _report_v2_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    provenance = instance.get("provenance") or {}
    tagset_digest = provenance.get("tagset_digest")
    input_tagset_digest = (provenance.get("input_digests") or {}).get("tagset")
    if tagset_digest != input_tagset_digest:
        errors.append("$.provenance.input_digests.tagset: must equal $.provenance.tagset_digest")
    population = instance.get("population") or {}
    nonmerge = population.get("nonmerge_commit_count")
    merges = population.get("merge_commit_count")
    human = population.get("human_commit_count")
    if _is_int(nonmerge) and _is_int(merges) and _is_int(human):
        if nonmerge + merges != human:
            errors.append(
                "$.population.human_commit_count: must equal nonmerge_commit_count + merge_commit_count"
            )
    revision = provenance.get("revision_completeness") or {}
    if revision.get("complete") is True and (
        revision.get("shallow") is True or revision.get("promisor") is True
    ):
        errors.append(
            "$.provenance.revision_completeness.complete: shallow or promisor history is not complete"
        )
    target_oid = (instance.get("target") or {}).get("oid")
    provenance_oid = provenance.get("target_oid")
    if target_oid != provenance_oid:
        errors.append("$.target.oid: must equal $.provenance.target_oid")
    analyzed_commit = provenance.get("analyzed_commit_sha")
    if analyzed_commit is not None and isinstance(target_oid, dict):
        if analyzed_commit != target_oid.get("value"):
            errors.append("$.provenance.analyzed_commit_sha: must equal $.target.oid.value")
    subject = instance.get("subject") or {}
    if subject.get("kind") == "actor" and subject.get("actor_id") != subject.get("canonical_id"):
        errors.append("$.subject.actor_id: must equal $.subject.canonical_id")
    attribution = instance.get("attribution") or {}
    _attribution_invariants(attribution, "$.attribution", errors)
    if attribution.get("observed_actor_count") != population.get("actor_count"):
        errors.append("$.attribution.observed_actor_count: must equal $.population.actor_count")
    partition = attribution.get("actor_partition") or {}
    population_partition = population.get("partition_digest") or {}
    if partition.get("partition_digest") != population_partition.get("value"):
        errors.append(
            "$.attribution.actor_partition.partition_digest: must equal $.population.partition_digest.value"
        )
    expected_population_digest = _population_digest_value(population)
    actual_population_digest = population.get("population_digest") or {}
    if actual_population_digest.get("value") != expected_population_digest:
        errors.append(
            "$.population.population_digest.value: must equal the canonical population digest"
        )
    if population.get("human_commit_count") != (
        attribution.get("attributed_commit_count", 0)
        + attribution.get("unresolved_commit_count", 0)
    ):
        errors.append(
            "$.population.human_commit_count: must equal attributed_commit_count + unresolved_commit_count"
        )
    if population.get("nonmerge_commit_count") != attribution.get("repo_human_nonmerge_commits"):
        errors.append(
            "$.population.nonmerge_commit_count: must equal attribution repo_human_nonmerge_commits"
        )
    if population.get("merge_commit_count") != attribution.get("merge_count"):
        errors.append("$.population.merge_commit_count: must equal attribution merge_count")
    report_window = instance.get("window")
    for name, metric in (instance.get("metrics") or {}).items():
        if isinstance(metric, dict) and metric.get("window") != report_window:
            errors.append(f"$.metrics.{name}.window: must equal $.window")
    directory = instance.get("actor_directory")
    if isinstance(directory, dict):
        actors = directory.get("actors") or []
        if directory.get("observed_count") != len(actors):
            errors.append(
                "$.actor_directory.observed_count: must equal len($.actor_directory.actors)"
            )
        if directory.get("attribution") != attribution:
            errors.append("$.actor_directory.attribution: must equal $.attribution")
        for index, actor in enumerate(actors):
            if not isinstance(actor, dict):
                continue
            status = actor.get("public_account_status")
            accounts = actor.get("public_accounts") or []
            if status in {"not_requested", "unlinked"} and accounts:
                errors.append(
                    f"$.actor_directory.actors[{index}].public_accounts: must be empty when status is {status}"
                )
            if status == "linked" and len(accounts) != 1:
                errors.append(
                    f"$.actor_directory.actors[{index}].public_accounts: linked requires exactly one account"
                )
    _bound_report_source_invariants(instance, errors)


def _bound_report_source_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    event = instance.get("event_observation") or {}
    if event.get("source_format") == "tep-forge-export-v2":
        _bound_summary_invariants(event, "$.event_observation", errors)
        counts = (event.get("event_type_counts") or {}).get("values") or {}
        daily = (event.get("daily_event_counts") or {}).get("values") or {}
        repositories = (event.get("repository_event_counts") or {}).get("values") or {}
        sample = event.get("sample_size")
        for path, values in (
            ("event_type_counts", counts),
            ("daily_event_counts", daily),
            ("repository_event_counts", repositories),
        ):
            if isinstance(sample, int) and isinstance(values, dict):
                if sum(value for value in values.values() if _is_int(value)) != sample:
                    errors.append(f"$.event_observation.{path}: values must sum to sample_size")
    tracker = instance.get("tracker_lifecycle") or {}
    if tracker.get("source_format") == "tep-tracker-export-v2":
        _bound_summary_invariants(tracker, "$.tracker_lifecycle", errors)
        sample = tracker.get("sample_size")
        for path in ("event_kind_counts", "record_state_counts"):
            values = tracker.get(path) or {}
            if isinstance(sample, int) and isinstance(values, dict):
                if sum(value for value in values.values() if _is_int(value)) != sample:
                    errors.append(f"$.tracker_lifecycle.{path}: values must sum to sample_size")


def _bound_summary_invariants(node: dict[str, Any], path: str, errors: list[str]) -> None:
    binding = node.get("binding") or {}
    if not isinstance(node.get("digest"), str):
        errors.append(f"{path}.digest: bound summary requires input digest")
    if node.get("window") != binding.get("window"):
        errors.append(f"{path}.window: must equal binding window")
    coverage = binding.get("coverage") or {}
    interval = node.get("interval_coverage")
    if isinstance(interval, dict):
        for key in ("status", "observed", "expected", "missing", "unit"):
            if interval.get(key) != coverage.get(key):
                errors.append(f"{path}.interval_coverage.{key}: must equal binding coverage")
    coverage_status = node.get("coverage_status")
    if coverage_status is not None and coverage_status != coverage.get("status"):
        errors.append(f"{path}.coverage_status: must equal binding coverage status")


def _population_digest_value(population: dict[str, Any]) -> str:
    body = {
        key: population.get(key)
        for key in (
            "actor_count",
            "human_commit_count",
            "nonmerge_commit_count",
            "merge_commit_count",
            "basis",
            "partition_digest",
        )
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(b"tep-population-v1\0" + encoded).hexdigest()


def _attribution_invariants(attribution: dict[str, Any], path: str, errors: list[str]) -> None:
    attributed = attribution.get("attributed_commit_count")
    unresolved = attribution.get("unresolved_commit_count")
    total = attributed + unresolved if _is_int(attributed) and _is_int(unresolved) else None
    coverage = attribution.get("attribution_coverage") or {}
    if total is not None:
        if coverage.get("sample_size") != total:
            errors.append(
                f"{path}.attribution_coverage.sample_size: must equal attributed + unresolved"
            )
        expected = attributed / total if total else 0.0
        if not _is_num(coverage.get("value")) or not math.isclose(
            float(coverage.get("value", 0.0)), round(expected, 4), rel_tol=0.0, abs_tol=1e-12
        ):
            errors.append(f"{path}.attribution_coverage.value: must equal attributed / sample_size")
    aliases = (
        ("attribution_human_including_merges", "attributed_commit_count"),
        ("attribution_unresolved_commit_count", "unresolved_commit_count"),
    )
    for alias, source in aliases:
        if attribution.get(alias) != attribution.get(source):
            errors.append(f"{path}.{alias}: must equal {source}")
    nonmerge = attribution.get("repo_human_nonmerge_commits")
    merges = attribution.get("merge_count")
    if all(_is_int(item) for item in (nonmerge, merges, attributed, unresolved)):
        if nonmerge + merges != attributed + unresolved:
            errors.append(f"{path}: repo nonmerge + merge must equal attributed + unresolved")


def _alignment_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    for index, axis in enumerate(instance.get("axes") or []):
        if not isinstance(axis, dict):
            continue
        for prefix in ("actor", "project"):
            numerator = axis.get(f"{prefix}_n")
            denominator = axis.get(f"{prefix}_denominator")
            if _is_int(numerator) and _is_int(denominator) and numerator > denominator:
                errors.append(f"$.axes[{index}].{prefix}_n: must not exceed {prefix}_denominator")


def _public_evidence_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    coverage = instance.get("coverage") or {}
    commit_oids = instance.get("commit_oids") or []
    item_count = coverage.get("item_count")
    duplicates = instance.get("duplicate_commit_oids") or []
    if duplicates:
        # The manifest retains a set-like commit population and a separate
        # duplicate signal. Exact multiplicity is rederived from CAS bodies by
        # ``verify_public_evidence``; the schema can still reject an impossible
        # count without erasing the negative evidence before replay.
        if isinstance(item_count, int) and item_count < len(commit_oids) + len(duplicates):
            errors.append("$.coverage.item_count: must cover unique and duplicate commit OIDs")
    elif item_count != len(commit_oids):
        errors.append("$.coverage.item_count: must equal len($.commit_oids)")
    pagination = instance.get("pagination") or {}
    pages = instance.get("pages") or []
    if pagination.get("pages") != len(pages):
        errors.append("$.pagination.pages: must equal len($.pages)")
    if coverage.get("status") == "complete":
        if coverage.get("missing"):
            errors.append("$.coverage.missing: must be empty when status is complete")
        if instance.get("duplicate_commit_oids"):
            errors.append("$.duplicate_commit_oids: must be empty when status is complete")
        if pagination.get("truncated") is not False:
            errors.append("$.pagination.truncated: must be false when status is complete")
    target = instance.get("target_oid") or {}
    expected_length = 40 if target.get("algorithm") == "sha1" else 64
    for path, oid in _iter_public_oids(instance):
        if isinstance(oid, str) and len(oid) != expected_length:
            errors.append(f"{path}: length must match $.target_oid.algorithm")
    if instance.get("account_linkage") == "unsupported" and instance.get("sha_to_account"):
        errors.append("$.sha_to_account: must be empty when account linkage is unsupported")
    for path, request in _iter_public_requests(instance):
        url = request.get("url") if isinstance(request, dict) else None
        if isinstance(url, str):
            parsed = urlparse(url)
            if parsed.username or parsed.password:
                errors.append(f"{path}.url: userinfo is forbidden")
            query = parsed.query.lower()
            if any(needle in query for needle in ("token=", "access_token=", "private_token=")):
                errors.append(f"{path}.url: credential query parameter is forbidden")


def _iter_public_oids(instance: dict[str, Any]) -> list[tuple[str, Any]]:
    values: list[tuple[str, Any]] = []
    for key in ("commit_oids", "duplicate_commit_oids"):
        values.extend(
            (f"$.{key}[{index}]", oid) for index, oid in enumerate(instance.get(key) or [])
        )
    values.extend(
        (f"$.sha_to_account.{oid}<key>", oid) for oid in (instance.get("sha_to_account") or {})
    )
    for index, conflict in enumerate(instance.get("mapping_conflicts") or []):
        if isinstance(conflict, dict):
            values.append((f"$.mapping_conflicts[{index}].commit_oid", conflict.get("commit_oid")))
    return values


def _iter_public_requests(instance: dict[str, Any]) -> list[tuple[str, Any]]:
    values = [
        (f"$.pages[{index}].request", page.get("request"))
        for index, page in enumerate(instance.get("pages") or [])
        if isinstance(page, dict)
    ]
    pagination = instance.get("pagination") or {}
    if pagination.get("next_request") is not None:
        values.append(("$.pagination.next_request", pagination.get("next_request")))
    return values


def _contribution_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    from tep_core.contribution_v2 import (
        SOURCE_REPLAY_BY_PROFILE,
        TRANSFORMATION_SPEC_DIGESTS,
        _aggregate_output_problems,
        _masked_output_problems,
        _named_output_problems,
    )

    profile = instance.get("privacy_profile")
    door = instance.get("door")
    policy = instance.get("policy") or {}
    public = profile in {"aggregate", "named-public"}
    externally_public = door == "public-pr"
    if policy.get("access_class") != ("public" if externally_public else "controlled_local"):
        errors.append("$.policy.access_class: inconsistent with door")
    if policy.get("public_payload") is not externally_public:
        errors.append("$.policy.public_payload: inconsistent with door")
    expected_replay = SOURCE_REPLAY_BY_PROFILE.get(profile)
    if expected_replay is None or policy.get("source_replay") != expected_replay:
        errors.append("$.policy.source_replay: inconsistent with privacy_profile")
    expected_digest = TRANSFORMATION_SPEC_DIGESTS.get(profile)
    if expected_digest is None or instance.get("transformation_spec_digest") != expected_digest:
        errors.append("$.transformation_spec_digest: inconsistent with privacy_profile")
    if public and door == "controlled":
        errors.append("$.door: public profiles do not use the controlled door")
    if not public and door == "public-pr":
        errors.append("$.door: controlled profiles cannot use public-pr")
    if profile == "aggregate":
        errors.extend(
            f"$.data: {problem}" for problem in _aggregate_output_problems(instance.get("data"))
        )
        text = json.dumps(instance.get("data"), sort_keys=True, ensure_ascii=False)
        leak_patterns = (
            r"@",
            r"https?://",
            r"\b[0-9a-f]{40}\b",
            r"\b[0-9a-f]{64}\b",
            r"\d{4}-\d{2}-\d{2}T",
        )
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in leak_patterns):
            errors.append("$.data: aggregate profile contains source-identifying material")
    if profile == "named-public":
        errors.extend(
            f"$.data: {problem}" for problem in _named_output_problems(instance.get("data"))
        )
        forbidden = {"actor_id", "actor_pid", "email", "emails", "canonical_id"}
        for path, key in _walk_keys(instance.get("data"), "$.data"):
            if key in forbidden:
                errors.append(f"{path}: forbidden named-public identity key")
    if profile == "masked":
        errors.extend(
            f"$.data: {problem}" for problem in _masked_output_problems(instance.get("data"))
        )
        data = instance.get("data") or {}
        population = data.get("population") or {}
        actors = data.get("actors") or []
        n = population.get("n")
        denominator = population.get("denominator")
        if _is_int(n) and n != len(actors):
            errors.append("$.data.population.n: must equal len($.data.actors)")
        actor_total = 0
        pids: set[str] = set()
        for index, actor in enumerate(actors):
            if not isinstance(actor, dict):
                continue
            pid = actor.get("actor_pid")
            if isinstance(pid, str):
                if pid in pids:
                    errors.append(f"$.data.actors[{index}].actor_pid: must be unique")
                pids.add(pid)
            measurements = actor.get("measurements") or {}
            actor_n = measurements.get("n")
            if _is_int(actor_n):
                actor_total += actor_n
            if measurements.get("denominator") != denominator:
                errors.append(
                    f"$.data.actors[{index}].measurements.denominator: must equal population denominator"
                )
            nonmerge = measurements.get("nonmerge_n")
            merges = measurements.get("merge_n")
            if all(_is_int(value) for value in (actor_n, nonmerge, merges)) and (
                nonmerge + merges != actor_n
            ):
                errors.append(
                    f"$.data.actors[{index}].measurements.n: must equal nonmerge_n + merge_n"
                )
        if _is_int(denominator) and actor_total != denominator:
            errors.append("$.data.population.denominator: must equal the actor n total")


def _walk_keys(node: Any, path: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            values.append((child, key))
            values.extend(_walk_keys(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            values.extend(_walk_keys(value, f"{path}[{index}]"))
    return values


def _attest_bundle_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    signature = instance.get("signature") or {}
    expected = "statement.json.sig" if signature.get("kind") == "ssh" else "cosign.bundle.json"
    if signature.get("path") != expected:
        errors.append("$.signature.path: must match signature kind")


def _portfolio_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    summary = instance.get("summary") or {}
    entries = instance.get("entries") or []
    included = summary.get("included_repository_count")
    eligible = summary.get("eligible_repository_count")
    disclosure = summary.get("disclosure") or {}
    if included != len(entries):
        errors.append("$.summary.included_repository_count: must equal len($.entries)")
    if _is_int(included) and _is_int(eligible) and included > eligible:
        errors.append("$.summary.included_repository_count: must not exceed eligible count")
    if disclosure.get("numerator") != included:
        errors.append("$.summary.disclosure.numerator: must equal included_repository_count")
    if disclosure.get("denominator") != eligible:
        errors.append("$.summary.disclosure.denominator: must equal eligible_repository_count")
    bindings = {json.dumps(entry.get("subject_binding"), sort_keys=True) for entry in entries}
    bindings.add(json.dumps(instance.get("subject_binding"), sort_keys=True))
    if len(bindings) > 1:
        errors.append("$.entries: every subject_binding must match the portfolio subject_binding")
    binding = instance.get("subject_binding") or {}
    method = binding.get("method")
    subject_id = binding.get("subject_id")
    signer_policies: set[str] = set()
    for index, entry in enumerate(entries):
        attestation = (entry.get("evidence") or {}).get("attestation") or {}
        expected_status = (
            "recipient_trust_verified" if method == "attested" else "not_verified_self_declared"
        )
        if attestation.get("signature_verification") != expected_status:
            errors.append(
                f"$.entries[{index}].evidence.attestation.signature_verification: "
                f"must be {expected_status}"
            )
        if method == "attested":
            if attestation.get("bound_subject_id") != subject_id:
                errors.append(
                    f"$.entries[{index}].evidence.attestation.bound_subject_id: "
                    "must equal the portfolio subject"
                )
            signer_policies.add(json.dumps(attestation.get("signer_policy"), sort_keys=True))
        elif "bound_subject_id" in attestation:
            errors.append(
                f"$.entries[{index}].evidence.attestation.bound_subject_id: "
                "forbidden for self_declared binding"
            )
    if method == "attested" and len(signer_policies) > 1:
        errors.append("$.entries: attested binding requires one recipient trust policy")


def _portfolio_manifest_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    subject_id = instance.get("subject_id")
    method = instance.get("subject_binding")
    for index, entry in enumerate(instance.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        if entry.get("subject_id") != subject_id:
            errors.append(f"$.entries[{index}].subject_id: must equal the portfolio subject_id")
        if entry.get("subject_binding", method) != method:
            errors.append(
                f"$.entries[{index}].subject_binding: must equal the portfolio subject_binding"
            )


def _scenario_summary_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    counts = instance.get("counts") or {}
    subtotal = sum(counts.get(key, 0) for key in ("pass", "fail", "not_proven", "source_drift"))
    if counts.get("total") != subtotal:
        errors.append("$.counts.total: must equal the sum of verdict counts")


def _bound_export_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    binding = instance.get("binding") or {}
    coverage = binding.get("coverage") or {}
    if _is_int(coverage.get("observed")) and _is_int(coverage.get("missing")):
        if coverage["observed"] + coverage["missing"] != coverage.get("expected"):
            errors.append("$.binding.coverage: observed + missing must equal expected")
    if coverage.get("status") == "complete" and coverage.get("missing") != 0:
        errors.append("$.binding.coverage.missing: complete coverage requires 0")
    if coverage.get("status") == "partial" and coverage.get("missing") == 0:
        errors.append("$.binding.coverage.missing: partial coverage requires a missing item")
    events = instance.get("events") or []
    seen: set[str] = set()
    window = binding.get("window") or {}
    target = binding.get("target_oid") or {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        if isinstance(event_id, str):
            if event_id in seen:
                errors.append(f"$.events[{index}].event_id: duplicate event ID")
            seen.add(event_id)
        for key in ("project_id", "project_path"):
            if key in event and event.get(key) != binding.get(key):
                errors.append(f"$.events[{index}].{key}: must match $.binding.{key}")
        timestamp = event.get("timestamp")
        if isinstance(timestamp, str):
            instant = _temporal_value(timestamp)
            start = _temporal_value(str(window.get("start")))
            end = _temporal_value(str(window.get("end")))
            if (
                instant is not None
                and start is not None
                and end is not None
                and (instant < start or instant >= end)
            ):
                errors.append(f"$.events[{index}].timestamp: outside binding window")
        commit_sha = event.get("commit_sha")
        if isinstance(commit_sha, str):
            expected_length = 40 if target.get("algorithm") == "sha1" else 64
            if len(commit_sha) != expected_length:
                errors.append(f"$.events[{index}].commit_sha: length must match target OID")
    if instance.get("schema_version") == "tep-tracker-export-v2":
        _tracker_export_invariants(events, errors)


def _tracker_export_invariants(events: list[Any], errors: list[str]) -> None:
    rows = [event for event in events if isinstance(event, dict)]
    by_id = {
        event.get("event_id"): event for event in rows if isinstance(event.get("event_id"), str)
    }
    positions = {
        event.get("event_id"): index
        for index, event in enumerate(rows)
        if isinstance(event.get("event_id"), str)
    }
    instants = [_temporal_value(str(event.get("timestamp"))) for event in rows]
    for index, (left, right) in enumerate(zip(instants, instants[1:]), start=1):
        if left is not None and right is not None and right < left:
            errors.append(f"$.events[{index}].timestamp: tracker events must be in order")

    latest: dict[tuple[Any, Any], dict[str, Any]] = {}
    successors: set[str] = set()
    for index, event in enumerate(rows):
        path = f"$.events[{index}]"
        record_type = event.get("record_type")
        record_id = event.get("record_id")
        state = event.get("state")
        kind = event.get("kind")
        key = (record_type, record_id)
        previous = latest.get(key)
        linked_id = event.get("linked_event_id")
        if kind != "issue_linked" and linked_id is not None:
            errors.append(f"{path}.linked_event_id: only issue_linked may declare a link")
        initial = kind in {"issue_opened", "milestone_set"}
        expected_initial = {
            "issue_opened": ("issue", "open"),
            "milestone_set": ("milestone", "active"),
        }.get(kind)
        if initial:
            if expected_initial != (record_type, state):
                errors.append(f"{path}: kind/state/record_type mismatch")
            if previous is not None:
                errors.append(f"{path}: duplicate initial state for record_id")
            if any(
                event.get(name) is not None
                for name in ("previous_state", "previous_event_id", "duration_seconds")
            ):
                errors.append(f"{path}: initial state cannot declare a predecessor")
            latest[key] = event
            continue

        expected_transition = {
            "issue_triaged": ("issue", "triaged", {"open"}),
            "issue_closed": ("issue", "closed", {"open", "triaged"}),
            "milestone_closed": ("milestone", "closed", {"active"}),
        }.get(kind)
        if expected_transition is not None:
            expected_type, expected_state, allowed_previous = expected_transition
            if (record_type, state) != (expected_type, expected_state):
                errors.append(f"{path}: kind/state/record_type mismatch")
            if previous is None:
                errors.append(f"{path}: state transition is missing an initial event")
            else:
                if (
                    event.get("previous_event_id") != previous.get("event_id")
                    or event.get("previous_state") != previous.get("state")
                    or event.get("previous_state") not in allowed_previous
                ):
                    errors.append(f"{path}: transition does not reference the latest state")
                previous_id = previous.get("event_id")
                if isinstance(previous_id, str) and previous_id in successors:
                    errors.append(f"{path}: predecessor already has a successor")
                if isinstance(previous_id, str):
                    successors.add(previous_id)
            _tracker_predecessor_invariant(event, path, by_id, positions, errors)
            latest[key] = event
            continue

        if kind == "issue_linked":
            if record_type != "issue" or previous is None:
                errors.append(f"{path}: issue_linked is missing an issue state")
            elif (
                event.get("previous_event_id") != previous.get("event_id")
                or event.get("previous_state") != previous.get("state")
                or state != previous.get("state")
            ):
                errors.append(f"{path}: issue_linked state is inconsistent")
            if state not in {"open", "triaged"}:
                errors.append(f"{path}.state: a closed issue cannot be linked")
            _tracker_predecessor_invariant(event, path, by_id, positions, errors)
            target_event = by_id.get(linked_id)
            if target_event is None:
                errors.append(f"{path}.linked_event_id: broken link")
            elif (
                positions.get(linked_id, index) >= index
                or target_event.get("record_type") != "milestone"
                or target_event.get("state") != "active"
            ):
                errors.append(
                    f"{path}.linked_event_id: must reference an earlier active milestone event"
                )
        elif kind is not None:
            errors.append(f"{path}: unknown tracker transition kind")


def _tracker_predecessor_invariant(
    event: dict[str, Any],
    path: str,
    by_id: dict[Any, dict[str, Any]],
    positions: dict[Any, int],
    errors: list[str],
) -> None:
    previous_id = event.get("previous_event_id")
    previous = by_id.get(previous_id)
    index = positions.get(event.get("event_id"), -1)
    if previous is None:
        errors.append(f"{path}.previous_event_id: broken link")
        return
    if positions.get(previous_id, index) >= index:
        errors.append(f"{path}.previous_event_id: must reference an earlier event")
    if (previous.get("record_type"), previous.get("record_id")) != (
        event.get("record_type"),
        event.get("record_id"),
    ):
        errors.append(f"{path}.previous_event_id: crosses tracker records")
    left = _temporal_value(str(previous.get("timestamp")))
    right = _temporal_value(str(event.get("timestamp")))
    duration = event.get("duration_seconds")
    if not _is_num(duration):
        errors.append(f"{path}.duration_seconds: transition requires a finite number")
        return
    if left is None or right is None:
        return
    elapsed = (right - left).total_seconds()
    if elapsed < 0:
        errors.append(f"{path}.duration_seconds: negative transition duration")
    elif not math.isclose(float(duration), elapsed, rel_tol=0.0, abs_tol=1e-6):
        errors.append(f"{path}.duration_seconds: must equal timestamp difference")


def _identity_v2_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    seen: dict[str, str] = {}
    for index, actor in enumerate(instance.get("actors") or []):
        if not isinstance(actor, dict):
            continue
        canonical_id = str(actor.get("canonical_id") or index)
        digests: list[str] = []
        for email in actor.get("emails") or []:
            if isinstance(email, str):
                normalized = email.strip().lower()
                digests.append(
                    hashlib.sha256(b"tep-email-v1\0" + normalized.encode("utf-8")).hexdigest()
                )
        digests.extend(actor.get("email_sha256") or [])
        if len(digests) != len(set(digests)):
            errors.append(f"$.actors[{index}]: duplicate normalized email identity")
        for digest in digests:
            previous = seen.get(str(digest))
            if previous is not None and previous != canonical_id:
                errors.append(f"$.actors[{index}]: email identity is already owned by {previous}")
            seen[str(digest)] = canonical_id


def _experience_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    if instance.get("kind") != "observed":
        return
    metrics = instance.get("metrics") or {}
    cadence = metrics.get("cadence") or {}
    if isinstance(cadence, dict) and cadence.get("kind") == "observed":
        denominator = cadence.get("denominator")
        if _is_int(denominator) and cadence.get("numerator") != max(denominator - 1, 0):
            errors.append("$.metrics.cadence.numerator: must equal the adjacent interval count")
    timeline = metrics.get("language_domain_timeline") or {}
    if isinstance(timeline, dict) and timeline.get("kind") == "observed":
        periods = timeline.get("periods") or []
        period_commit_total = sum(
            period.get("commit_n", 0) for period in periods if isinstance(period, dict)
        )
        if period_commit_total != timeline.get("denominator"):
            errors.append(
                "$.metrics.language_domain_timeline.denominator: must equal the period commit total"
            )
        contributing_commit_total = sum(
            period.get("path_touch_commit_n", 0) for period in periods if isinstance(period, dict)
        )
        if contributing_commit_total != timeline.get("numerator"):
            errors.append(
                "$.metrics.language_domain_timeline.numerator: must equal the period path-touch commit total"
            )
        for index, period in enumerate(periods):
            if not isinstance(period, dict):
                continue
            path_touch_commit_n = period.get("path_touch_commit_n")
            commit_n = period.get("commit_n")
            if (
                _is_int(path_touch_commit_n)
                and _is_int(commit_n)
                and path_touch_commit_n > commit_n
            ):
                errors.append(
                    f"$.metrics.language_domain_timeline.periods[{index}].path_touch_commit_n: must not exceed commit_n"
                )
            for field in ("languages", "domains"):
                distribution = period.get(field) or {}
                denominator = distribution.get("denominator")
                values = distribution.get("values") or {}
                n_total = sum(
                    item.get("n", 0) for item in values.values() if isinstance(item, dict)
                )
                path = f"$.metrics.language_domain_timeline.periods[{index}].{field}"
                if n_total != denominator:
                    errors.append(f"{path}.denominator: must equal the value n total")
                if _is_int(denominator):
                    for name, item in values.items():
                        if not isinstance(item, dict) or not _is_int(item.get("n")):
                            continue
                        expected = item["n"] / denominator if denominator else 0.0
                        share = item.get("share")
                        if not _is_num(share) or not math.isclose(
                            float(share), round(expected, 4), rel_tol=0.0, abs_tol=1e-12
                        ):
                            errors.append(f"{path}.values.{name}.share: must equal n / denominator")
    sizes = metrics.get("repository_size_at_contribution_points") or {}
    if isinstance(sizes, dict) and sizes.get("kind") == "observed":
        points = sizes.get("points") or {}
        distinct_snapshot_commits = {
            (points.get(name) or {}).get("commit_oid")
            for name in ("first", "median", "last")
            if isinstance(points.get(name), dict)
        }
        distinct_snapshot_commits.discard(None)
        if sizes.get("numerator") != len(distinct_snapshot_commits):
            errors.append(
                "$.metrics.repository_size_at_contribution_points.numerator: must equal the distinct snapshot commit count"
            )
        ranks = [
            (points.get(name) or {}).get("target_contribution_rank")
            for name in ("first", "median", "last")
        ]
        if all(_is_int(rank) for rank in ranks):
            if not (ranks[0] <= ranks[1] <= ranks[2]):
                errors.append(
                    "$.metrics.repository_size_at_contribution_points.points: ranks must be ordered"
                )
            if ranks[0] != 1 or ranks[2] != sizes.get("denominator"):
                errors.append(
                    "$.metrics.repository_size_at_contribution_points.points: first/last ranks must bind the denominator"
                )


def _role_profile_invariants(instance: dict[str, Any], errors: list[str]) -> None:
    if instance.get("kind") != "observed":
        return
    dimensions = instance.get("dimensions") or {}
    time = dimensions.get("time") or {}
    dimension_rows = [
        ("domain", dimensions.get("domain")),
        ("work_type", dimensions.get("work_type")),
        ("time.phase", time.get("phase") if isinstance(time, dict) else None),
        (
            "time.calendar_year",
            time.get("calendar_year") if isinstance(time, dict) else None,
        ),
        ("process_position", dimensions.get("process_position")),
    ]
    for name, dimension in dimension_rows:
        if not isinstance(dimension, dict):
            continue
        entries = [node for node in dimension.values() if isinstance(node, dict)]
        if not entries:
            continue
        denominators = {node.get("denominator") for node in entries}
        if len(denominators) != 1:
            errors.append(f"$.dimensions.{name}: entries must use one denominator")
        if name in {"time.phase", "time.calendar_year", "process_position"}:
            observed = [node for node in entries if node.get("kind") == "observed"]
            if len(observed) == len(entries):
                numerator_total = sum(node.get("numerator", 0) for node in observed)
                denominator = next(iter(denominators)) if len(denominators) == 1 else None
                if numerator_total != denominator:
                    errors.append(
                        f"$.dimensions.{name}: observed numerator total must equal denominator"
                    )
