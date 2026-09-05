"""Provider-neutral binding contract for local forge/tracker exports."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from tep_core.dates import parse_iso_utc
from tep_core.secrets_guard import InputValidationError

_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")
_PROJECT_PATH_RE = re.compile(r"^[^/@\s][^@\s]*/[^/@\s][^@\s]*$")
_HEX_RE = re.compile(r"^[0-9a-f]+$")
_BINDING_KEYS = frozenset(
    {"provider", "host", "project_id", "project_path", "target_oid", "window", "coverage"}
)
_OID_KEYS = frozenset({"algorithm", "value"})
_WINDOW_KEYS = frozenset({"start", "end"})
_COVERAGE_KEYS = frozenset({"status", "observed", "expected", "unit", "missing"})


@dataclass(frozen=True)
class GitObjectId:
    algorithm: str
    value: str


@dataclass(frozen=True)
class SourceWindow:
    start: str
    end: str


@dataclass(frozen=True)
class SourceCoverage:
    status: str
    observed: int
    expected: int
    unit: str
    missing: int


@dataclass(frozen=True)
class SourceBinding:
    provider: str
    host: str
    project_id: str
    project_path: str
    target_oid: GitObjectId
    window: SourceWindow
    coverage: SourceCoverage
    digest: str


def source_binding_payload(binding: SourceBinding) -> dict[str, Any]:
    """Return the canonical, credential-free binding recorded in reports.

    The source export digest binds the complete input bytes, while this
    projection keeps the provider/project/target/window/coverage contract
    independently inspectable by a report consumer.
    """

    return {
        "provider": binding.provider,
        "host": binding.host,
        "project_id": binding.project_id,
        "project_path": binding.project_path,
        "target_oid": {
            "algorithm": binding.target_oid.algorithm,
            "value": binding.target_oid.value,
        },
        "window": {"start": binding.window.start, "end": binding.window.end},
        "coverage": {
            "status": binding.coverage.status,
            "observed": binding.coverage.observed,
            "expected": binding.coverage.expected,
            "missing": binding.coverage.missing,
            "unit": binding.coverage.unit,
        },
        "digest": binding.digest,
    }


def _closed(node: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    extra = set(node) - allowed
    if extra:
        raise InputValidationError(f"{path}: unknown keys {sorted(extra)}")


def _required_text(node: Mapping[str, Any], key: str, path: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(f"{path}: {key} must be a non-empty string")
    return value.strip()


def _timestamp(value: str, path: str) -> datetime:
    if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
        raise InputValidationError(f"{path}: must include an explicit timezone")
    try:
        return parse_iso_utc(value)
    except ValueError as exc:
        raise InputValidationError(f"{path}: must be ISO-8601 with timezone") from exc


def _valid_host(value: str) -> bool:
    if "/" in value or "@" in value or value.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlsplit("//" + value)
        _ = parsed.port
    except ValueError:
        return False
    return bool(parsed.hostname and not parsed.username and not parsed.password)


def parse_source_binding(node: Any, *, source: str) -> SourceBinding:
    path = f"{source}.binding"
    if not isinstance(node, Mapping):
        raise InputValidationError(f"{path}: must be an object")
    _closed(node, _BINDING_KEYS, path)
    provider = _required_text(node, "provider", path).lower()
    host = _required_text(node, "host", path).lower()
    project_id = _required_text(node, "project_id", path)
    project_path = _required_text(node, "project_path", path)
    if not _PROVIDER_RE.fullmatch(provider):
        raise InputValidationError(f"{path}: provider is invalid")
    if not _valid_host(host):
        raise InputValidationError(f"{path}: host is invalid")
    if not _PROJECT_PATH_RE.fullmatch(project_path) or ".." in project_path.split("/"):
        raise InputValidationError(f"{path}: project_path is invalid")

    oid_node = node.get("target_oid")
    if not isinstance(oid_node, Mapping):
        raise InputValidationError(f"{path}.target_oid: must be an object")
    _closed(oid_node, _OID_KEYS, f"{path}.target_oid")
    algorithm = _required_text(oid_node, "algorithm", f"{path}.target_oid").lower()
    value = _required_text(oid_node, "value", f"{path}.target_oid").lower()
    length = {"sha1": 40, "sha256": 64}.get(algorithm)
    if length is None or len(value) != length or not _HEX_RE.fullmatch(value):
        raise InputValidationError(f"{path}.target_oid: algorithm/value mismatch")

    window_node = node.get("window")
    if not isinstance(window_node, Mapping):
        raise InputValidationError(f"{path}.window: must be an object")
    _closed(window_node, _WINDOW_KEYS, f"{path}.window")
    start = _required_text(window_node, "start", f"{path}.window")
    end = _required_text(window_node, "end", f"{path}.window")
    if _timestamp(start, f"{path}.window.start") >= _timestamp(end, f"{path}.window.end"):
        raise InputValidationError(f"{path}.window: start must be earlier than end")

    coverage_node = node.get("coverage")
    if not isinstance(coverage_node, Mapping):
        raise InputValidationError(f"{path}.coverage: must be an object")
    _closed(coverage_node, _COVERAGE_KEYS, f"{path}.coverage")
    status = coverage_node.get("status")
    if status not in {"complete", "partial"}:
        raise InputValidationError(f"{path}.coverage: status must be complete or partial")
    counts: dict[str, int] = {}
    for key in ("observed", "expected", "missing"):
        number = coverage_node.get(key)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise InputValidationError(f"{path}.coverage.{key}: must be integer >= 0")
        counts[key] = number
    unit = _required_text(coverage_node, "unit", f"{path}.coverage")
    if counts["expected"] < 1 or counts["observed"] + counts["missing"] != counts["expected"]:
        raise InputValidationError(f"{path}.coverage: observed + missing must equal expected")
    if status == "complete" and counts["missing"] != 0:
        raise InputValidationError(f"{path}.coverage: complete requires missing=0")
    if status == "partial" and counts["missing"] == 0:
        raise InputValidationError(f"{path}.coverage: partial requires missing>0")

    canonical = {
        "provider": provider,
        "host": host,
        "project_id": project_id,
        "project_path": project_path,
        "target_oid": {"algorithm": algorithm, "value": value},
        "window": {"start": start, "end": end},
        "coverage": {"status": status, **counts, "unit": unit},
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SourceBinding(
        provider=provider,
        host=host,
        project_id=project_id,
        project_path=project_path,
        target_oid=GitObjectId(algorithm=algorithm, value=value),
        window=SourceWindow(start=start, end=end),
        coverage=SourceCoverage(status=status, unit=unit, **counts),
        digest=digest,
    )


def assert_binding_matches(actual: SourceBinding | None, expected: SourceBinding) -> None:
    if actual is None:
        raise InputValidationError("source export is unbound; tep-*-export-v2 is required")
    fields = (
        "provider",
        "host",
        "project_id",
        "project_path",
        "target_oid",
        "window",
    )
    mismatches = [field for field in fields if getattr(actual, field) != getattr(expected, field)]
    if mismatches:
        raise InputValidationError(f"source export target mismatch: {', '.join(mismatches)}")


def assert_subject_binding(
    binding: SourceBinding | None,
    *,
    repository_origin: str | None,
    target_oid: Mapping[str, str],
    event_window: Sequence[str] | None = None,
    source: str,
) -> SourceBinding:
    """Bind one v2 export to the repository subject being measured.

    A subject command may not accept a self-consistent export merely because
    its JSON validates.  The provider/host/project path must identify the
    repository origin, the generic Git OID must equal the fixed analysis
    target, and an explicitly requested event window must equal the export's
    declared window.  ``project_id`` remains provider-issued opaque data; it
    is cross-checked when forge and tracker bindings are paired by
    :func:`assert_binding_matches`.
    """

    if binding is None:
        raise InputValidationError(f"{source}: unbound export; tep-*-export-v2 is required")
    if not repository_origin:
        raise InputValidationError(
            f"{source}: repository origin is required to verify provider/host/project binding"
        )

    # Import lazily so the low-level JSON loader remains independent from the
    # public HTTP adapter.  parse_forge_locator is a pure, credential-rejecting
    # remote parser here; no network operation is performed.
    from tep_core.forge_public import parse_forge_locator

    try:
        locator = parse_forge_locator(
            repository_origin,
            provider=binding.provider,
            # Self-managed hosts require an explicit API base in the public
            # fetch path.  Source binding needs only the remote identity, so a
            # syntactically valid same-host placeholder avoids inventing an
            # endpoint while retaining the shared parser's safety checks.
            api_base=f"https://{binding.host}",
        )
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            f"{source}: repository origin is not a valid forge remote"
        ) from exc

    mismatches: list[str] = []
    try:
        inferred_locator = parse_forge_locator(repository_origin, provider="auto")
    except (TypeError, ValueError):
        # Self-managed forges deliberately require the explicit provider from
        # the bound export.  github.com/gitlab.com are inferred and therefore
        # cannot be relabelled as one another.
        inferred_locator = None
    if inferred_locator is not None and inferred_locator.provider != binding.provider:
        mismatches.append("provider")
    if locator.provider != binding.provider:
        mismatches.append("provider")
    if locator.host != binding.host:
        mismatches.append("host")
    if locator.project_path != binding.project_path:
        mismatches.append("project_path")

    expected_algorithm = str(target_oid.get("algorithm") or "").lower().replace("-", "")
    expected_value = str(target_oid.get("value") or "").lower()
    if (
        binding.target_oid.algorithm != expected_algorithm
        or binding.target_oid.value != expected_value
    ):
        mismatches.append("target_oid")

    if event_window is not None:
        if len(event_window) != 2:
            raise InputValidationError(f"{source}: event window must contain start and end")
        requested = tuple(str(value) for value in event_window)
        declared = (
            _timestamp(binding.window.start, f"{source}.binding.window.start").date().isoformat(),
            _timestamp(binding.window.end, f"{source}.binding.window.end").date().isoformat(),
        )
        if requested != declared:
            mismatches.append("window")

    if mismatches:
        raise InputValidationError(
            f"{source}: source export target mismatch: {', '.join(mismatches)}"
        )
    return binding


def event_in_window(timestamp: str, binding: SourceBinding, *, path: str) -> None:
    instant = _timestamp(timestamp, path)
    start = _timestamp(binding.window.start, f"{path}.binding.start")
    end = _timestamp(binding.window.end, f"{path}.binding.end")
    if instant < start or instant >= end:
        raise InputValidationError(f"{path}: timestamp outside binding window")


def assert_event_project(item: Mapping[str, Any], binding: SourceBinding, *, path: str) -> None:
    for key in ("project_id", "project_path"):
        value = item.get(key)
        if value is not None and value != getattr(binding, key):
            raise InputValidationError(f"{path}: mixed source {key}")
