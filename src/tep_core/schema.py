"""report-v1 structural schema (frozen 2026-08-22).

Pure standard library. Additive-only while report-v1 lives: new fields and
new reason codes may appear; renaming, removing, or re-semanting an existing
field requires report-v2. Unknown keys are therefore permitted so that
consumers pinned to report-v1 keep working across patch releases.
"""

from __future__ import annotations

import re
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
