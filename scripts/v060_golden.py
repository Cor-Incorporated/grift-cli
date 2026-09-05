#!/usr/bin/env python3
"""Offline v0.6 CLI golden runner with closed fixture and drift contracts.

Unlike the legacy live-clone tests, this runner materializes a deterministic
Git repository and invokes the installed CLI.  Expected artifacts are never
treated as command results: a successful run must create every registered
artifact again before comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

MANIFEST_SCHEMA = "tep-v060-golden-manifest-v2"
FIXTURE_SCHEMA = "tep-v060-git-fixture-v1"
OBSERVATION_SCHEMA = "tep-v060-golden-observation-v1"
RESULT_SCHEMA = "tep-v060-golden-result-v1"
DRIFT_POLICY_VERSION = "v060-drift-policy-1"
MIGRATION_SCHEMA = "tep-v060-golden-migration-log-v2"
# Initial baselines have no predecessor file.  A versioned sentinel digest
# makes that absence explicit without pretending an unknown old file existed.
MIGRATION_GENESIS_SHA256 = hashlib.sha256(b"tep-v060-golden-migration-genesis-v1\n").hexdigest()
ABSENT_BASELINE_SHA256 = hashlib.sha256(b"tep-v060-golden-baseline-absent-v1\n").hexdigest()

_ROOT_KEYS = frozenset(
    {"schema_version", "drift_policy_version", "registered_files", "migration_log", "cases"}
)
_CASE_KEYS = frozenset({"id", "fixture", "expected", "expected_artifacts", "timeout_seconds"})
_MIGRATION_REF_KEYS = frozenset({"path", "sha256"})
_MIGRATION_ROOT_KEYS = frozenset({"schema_version", "entries"})
_MIGRATION_ENTRY_KEYS = frozenset(
    {
        "migration_id",
        "case_id",
        "old_expected_state",
        "old_expected_sha256",
        "new_expected_sha256",
        "registered_files",
        "verdict",
        "drift_counts",
        "difference_count",
        "approval",
        "previous_entry_sha256",
        "record_sha256",
    }
)
_MIGRATION_APPROVAL_KEYS = frozenset({"status", "approved_by", "approved_at", "requirements"})
_DRIFT_CLASSES = ("D0", "D1", "D2", "D3", "D4")
_FIXTURE_KEYS = frozenset({"schema_version", "repository_name", "object_format", "commits"})
_COMMIT_KEYS = frozenset(
    {
        "message",
        "author_name",
        "author_email",
        "author_date",
        "committer_name",
        "committer_email",
        "committer_date",
        "files",
    }
)
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SAFE_MIGRATION_ID = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]{2,}$")
_HUMAN_APPROVER = re.compile(r"^(?:human|committee):[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMEZONE = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")

# Priority is important: definition/schema changes never become display drift,
# and population changes never become provider/source drift.
_D4_KEYS = frozenset(
    {
        "schema_version",
        "definition_version",
        "origin_definition_version",
        "activity_definition_version",
        "transformation_spec_digest",
    }
)
_D3_KEYS = frozenset(
    {
        "actor_id",
        "observed_count",
        "observed_actor_count",
        "actor_count",
        "commit_count",
        "commit_count_nonmerge",
        "attributed_commit_count",
        "human_commit_count",
        "repo_human_nonmerge_commits",
        "attribution_human_including_merges",
        "merge_count",
        "unresolved_commit_count",
        "population",
        "sample_size",
        "n",
        "numerator",
        "denominator",
        "window",
        "git_window",
        "event_window",
        "target_oid",
        "repo_scope_digest",
        "partition_digest",
        "sha_to_actor_digest",
    }
)
_D2_KEYS = frozenset(
    {
        "public_accounts",
        "public_account_status",
        "accounts",
        "account_status",
        "account_id",
        "handle",
        "profile_url",
        "public_join",
        "public_evidence_digest",
        "body_sha256",
        "etag",
        "pagination",
        "coverage_status",
        "provider",
        "host",
        "account_match_status",
        "evidence",
    }
)
_D1_KEYS = frozenset({"display_name", "display_status"})
_D0_KEYS = frozenset(
    {
        "analyzed_at",
        "executed_at",
        "generated_at",
        "collected_at",
        "started_at",
        "finished_at",
        "duration_ms",
        "duration_seconds",
        "elapsed_ms",
        "rate_state",
        "rate_reset_at",
        "rate_remaining",
    }
)


class GoldenContractError(RuntimeError):
    """The fixture, registry, CLI result, or expected baseline is invalid."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenContractError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GoldenContractError(f"{label} must be a JSON object: {path}")
    return value


def _closed(node: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    extra = sorted(set(node) - allowed)
    if extra:
        raise GoldenContractError(f"{path}: unknown keys {extra}")


def _safe_relative(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise GoldenContractError(f"{path}: relative path is required")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts or ".git" in pure.parts:
        raise GoldenContractError(f"{path}: unsafe relative path")
    return pure.as_posix()


def _resolve_registered(root: Path, relative: str) -> Path:
    path = root / relative
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor /= part
        if cursor.is_symlink():
            raise GoldenContractError(f"registered golden file crosses a symlink: {relative}")
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise GoldenContractError(f"registered golden file escapes root: {relative}") from exc
    if not resolved.is_file():
        raise GoldenContractError(f"registered golden file is missing: {relative}")
    return resolved


def _migration_record_sha256(entry: Mapping[str, Any]) -> str:
    """Return the digest that seals one migration record and its approval."""

    unsigned = {key: value for key, value in entry.items() if key != "record_sha256"}
    return _sha256_bytes(_canonical_bytes(unsigned))


def _validate_approval(node: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise GoldenContractError(f"{path} must be an object")
    _closed(node, _MIGRATION_APPROVAL_KEYS, path)
    if node.get("status") != "approved":
        raise GoldenContractError(f"{path}.status must be approved")
    approved_by = node.get("approved_by")
    if not isinstance(approved_by, str) or not _HUMAN_APPROVER.fullmatch(approved_by):
        raise GoldenContractError(f"{path}.approved_by must identify a human or committee")
    approved_at = node.get("approved_at")
    if not isinstance(approved_at, str) or not _TIMEZONE.search(approved_at):
        raise GoldenContractError(f"{path}.approved_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoldenContractError(f"{path}.approved_at must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise GoldenContractError(f"{path}.approved_at must include a timezone")
    requirements = node.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise GoldenContractError(f"{path}.requirements must be a non-empty array")
    if any(
        not isinstance(item, str) or not _REQUIREMENT_ID.fullmatch(item) for item in requirements
    ):
        raise GoldenContractError(f"{path}.requirements contains an invalid requirement ID")
    if requirements != sorted(set(requirements)):
        raise GoldenContractError(f"{path}.requirements must be unique and sorted")
    return dict(node)


def _validate_migration_log(
    root: Path,
    reference: Any,
    *,
    registry: Mapping[str, str],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate the append-only D4 approval chain against the active registry."""

    if not isinstance(reference, dict):
        raise GoldenContractError("manifest.migration_log must be an object")
    _closed(reference, _MIGRATION_REF_KEYS, "manifest.migration_log")
    relative = _safe_relative(reference.get("path"), path="manifest.migration_log.path")
    if relative != "migrations.json":
        raise GoldenContractError("manifest.migration_log.path must be migrations.json")
    expected_log_digest = reference.get("sha256")
    if not isinstance(expected_log_digest, str) or not _SHA256.fullmatch(expected_log_digest):
        raise GoldenContractError("manifest.migration_log.sha256 must be SHA-256")
    migration_path = _resolve_registered(root, relative)
    raw = migration_path.read_bytes()
    if _sha256_bytes(raw) != expected_log_digest:
        raise GoldenContractError("golden migration log hash mismatch")

    payload = _read_json(migration_path, label="golden migration log")
    _closed(payload, _MIGRATION_ROOT_KEYS, "migrations")
    if payload.get("schema_version") != MIGRATION_SCHEMA:
        raise GoldenContractError(f"migrations.schema_version must be {MIGRATION_SCHEMA}")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise GoldenContractError("migrations.entries must be a non-empty array")

    case_by_id = {str(case["id"]): case for case in cases}
    latest_by_case: dict[str, dict[str, Any]] = {}
    seen_migration_ids: set[str] = set()
    previous_record = MIGRATION_GENESIS_SHA256
    normalized_entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entries):
        path = f"migrations.entries[{index}]"
        if not isinstance(raw_entry, dict):
            raise GoldenContractError(f"{path} must be an object")
        _closed(raw_entry, _MIGRATION_ENTRY_KEYS, path)
        migration_id = raw_entry.get("migration_id")
        if not isinstance(migration_id, str) or not _SAFE_MIGRATION_ID.fullmatch(migration_id):
            raise GoldenContractError(f"{path}.migration_id is invalid")
        if migration_id in seen_migration_ids:
            raise GoldenContractError(f"duplicate golden migration id: {migration_id}")
        seen_migration_ids.add(migration_id)
        case_id = raw_entry.get("case_id")
        if not isinstance(case_id, str) or case_id not in case_by_id:
            raise GoldenContractError(f"{path}.case_id does not name a registered case")
        case = case_by_id[case_id]

        old_state = raw_entry.get("old_expected_state")
        old_digest = raw_entry.get("old_expected_sha256")
        new_digest = raw_entry.get("new_expected_sha256")
        for field, digest in (
            ("old_expected_sha256", old_digest),
            ("new_expected_sha256", new_digest),
            ("previous_entry_sha256", raw_entry.get("previous_entry_sha256")),
            ("record_sha256", raw_entry.get("record_sha256")),
        ):
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise GoldenContractError(f"{path}.{field} must be SHA-256")
        prior_case_entry = latest_by_case.get(case_id)
        if prior_case_entry is None:
            if old_state != "absent" or old_digest != ABSENT_BASELINE_SHA256:
                raise GoldenContractError(
                    f"{path}: first case migration must bind the absent-baseline digest"
                )
        elif old_state != "registered" or old_digest != prior_case_entry["new_expected_sha256"]:
            raise GoldenContractError(
                f"{path}: old expected digest breaks the case migration chain"
            )
        if new_digest == old_digest:
            raise GoldenContractError(f"{path}: old and new expected digests must differ")

        registered_files = raw_entry.get("registered_files")
        if not isinstance(registered_files, dict):
            raise GoldenContractError(f"{path}.registered_files must be an object")
        required_paths = {str(case["fixture"]), str(case["expected"])}
        if set(registered_files) != required_paths:
            raise GoldenContractError(
                f"{path}.registered_files must bind the case fixture and expected baseline"
            )
        for registered_path, digest in registered_files.items():
            _safe_relative(registered_path, path=f"{path}.registered_files")
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise GoldenContractError(
                    f"{path}.registered_files.{registered_path} must be SHA-256"
                )
        if registered_files[str(case["expected"])] != new_digest:
            raise GoldenContractError(f"{path}: new expected digest is not registered")

        if raw_entry.get("verdict") != "MIGRATION_REQUIRED":
            raise GoldenContractError(f"{path}.verdict must be MIGRATION_REQUIRED")
        drift_counts = raw_entry.get("drift_counts")
        if not isinstance(drift_counts, dict) or set(drift_counts) != set(_DRIFT_CLASSES):
            raise GoldenContractError(f"{path}.drift_counts must contain D0-D4 exactly")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in drift_counts.values()
        ):
            raise GoldenContractError(f"{path}.drift_counts must be non-negative integers")
        if drift_counts["D4"] < 1:
            raise GoldenContractError(f"{path}: an approved baseline migration requires D4 drift")
        difference_count = raw_entry.get("difference_count")
        if (
            not isinstance(difference_count, int)
            or isinstance(difference_count, bool)
            or difference_count != sum(drift_counts.values())
        ):
            raise GoldenContractError(f"{path}.difference_count must equal the D0-D4 sum")
        _validate_approval(raw_entry.get("approval"), path=f"{path}.approval")
        if raw_entry["previous_entry_sha256"] != previous_record:
            raise GoldenContractError(f"{path}: previous migration record digest mismatch")
        calculated_record = _migration_record_sha256(raw_entry)
        if raw_entry["record_sha256"] != calculated_record:
            raise GoldenContractError(f"{path}: migration record digest mismatch")
        previous_record = calculated_record
        normalized_entry = dict(raw_entry)
        normalized_entries.append(normalized_entry)
        latest_by_case[case_id] = normalized_entry

    missing_cases = sorted(set(case_by_id) - set(latest_by_case))
    if missing_cases:
        raise GoldenContractError(
            f"registered golden cases lack an approved migration: {missing_cases}"
        )
    for case_id, case in case_by_id.items():
        latest = latest_by_case[case_id]
        active_files = {
            str(case["fixture"]): registry[str(case["fixture"])],
            str(case["expected"]): registry[str(case["expected"])],
        }
        if latest["registered_files"] != active_files:
            raise GoldenContractError(
                f"latest migration for {case_id} does not bind the active registered fixtures"
            )
        if latest["new_expected_sha256"] != registry[str(case["expected"])]:
            raise GoldenContractError(
                f"latest migration for {case_id} does not bind the active expected baseline"
            )
    payload["entries"] = normalized_entries
    payload["_path"] = str(migration_path)
    payload["_sha256"] = expected_log_digest
    return payload


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and validate a closed manifest and every registered file digest."""

    manifest_path = path.resolve()
    payload = _read_json(manifest_path, label="golden manifest")
    _closed(payload, _ROOT_KEYS, "manifest")
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise GoldenContractError(f"manifest.schema_version must be {MANIFEST_SCHEMA}")
    if payload.get("drift_policy_version") != DRIFT_POLICY_VERSION:
        raise GoldenContractError(f"manifest.drift_policy_version must be {DRIFT_POLICY_VERSION}")
    registry = payload.get("registered_files")
    cases = payload.get("cases")
    if not isinstance(registry, dict) or not registry:
        raise GoldenContractError("manifest.registered_files must be a non-empty object")
    if not isinstance(cases, list) or not cases:
        raise GoldenContractError("manifest.cases must be a non-empty array")

    root = manifest_path.parent
    normalized_registry: dict[str, str] = {}
    for raw_relative, raw_digest in sorted(registry.items()):
        relative = _safe_relative(raw_relative, path="manifest.registered_files")
        if not isinstance(raw_digest, str) or not _SHA256.fullmatch(raw_digest):
            raise GoldenContractError(f"manifest.registered_files.{relative}: invalid SHA-256")
        registered = _resolve_registered(root, relative)
        actual = _sha256_bytes(registered.read_bytes())
        if actual != raw_digest:
            raise GoldenContractError(f"registered golden hash mismatch: {relative}")
        normalized_registry[relative] = raw_digest

    actual_files: set[str] = set()
    for folder in ("fixtures", "expected"):
        base = root / folder
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise GoldenContractError(f"golden fixture symlink is forbidden: {relative}")
            if candidate.is_file():
                actual_files.add(relative)
    unregistered = sorted(actual_files - set(normalized_registry))
    stale = sorted(set(normalized_registry) - actual_files)
    if unregistered:
        raise GoldenContractError(f"unregistered golden files: {unregistered}")
    if stale:
        raise GoldenContractError(f"registered golden files are missing: {stale}")

    normalized_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    referenced: Counter[str] = Counter()
    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, dict):
            raise GoldenContractError(f"manifest.cases[{index}] must be an object")
        _closed(raw_case, _CASE_KEYS, f"manifest.cases[{index}]")
        case_id = raw_case.get("id")
        if not isinstance(case_id, str) or not _SAFE_ID.fullmatch(case_id):
            raise GoldenContractError(f"manifest.cases[{index}].id is invalid")
        if case_id in seen_ids:
            raise GoldenContractError(f"duplicate golden case id: {case_id}")
        seen_ids.add(case_id)
        fixture = _safe_relative(raw_case.get("fixture"), path=f"case {case_id}.fixture")
        expected = _safe_relative(raw_case.get("expected"), path=f"case {case_id}.expected")
        for relative in (fixture, expected):
            if relative not in normalized_registry:
                raise GoldenContractError(
                    f"case {case_id} references unregistered file: {relative}"
                )
            referenced[relative] += 1
        artifacts = raw_case.get("expected_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise GoldenContractError(f"case {case_id}.expected_artifacts must be non-empty")
        normalized_artifacts = [
            _safe_relative(item, path=f"case {case_id}.expected_artifacts") for item in artifacts
        ]
        if len(set(normalized_artifacts)) != len(normalized_artifacts):
            raise GoldenContractError(f"case {case_id}.expected_artifacts has duplicates")
        timeout = raw_case.get("timeout_seconds")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 180:
            raise GoldenContractError(f"case {case_id}.timeout_seconds must be 1..180")
        normalized_cases.append(
            {
                "id": case_id,
                "fixture": fixture,
                "expected": expected,
                "expected_artifacts": sorted(normalized_artifacts),
                "timeout_seconds": timeout,
            }
        )
    if set(referenced) != set(normalized_registry):
        raise GoldenContractError(
            "registered golden files must be referenced by exactly one declared case"
        )
    duplicate_references = sorted(relative for relative, count in referenced.items() if count != 1)
    if duplicate_references:
        raise GoldenContractError(
            f"registered golden files referenced more than once: {duplicate_references}"
        )
    migration_log = _validate_migration_log(
        root,
        payload.get("migration_log"),
        registry=normalized_registry,
        cases=normalized_cases,
    )
    payload["registered_files"] = normalized_registry
    payload["cases"] = normalized_cases
    payload["_migration_log"] = migration_log
    payload["_manifest_path"] = str(manifest_path)
    payload["_manifest_digest"] = _sha256_bytes(manifest_path.read_bytes())
    return payload


def _validate_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    _closed(payload, _FIXTURE_KEYS, "fixture")
    if payload.get("schema_version") != FIXTURE_SCHEMA:
        raise GoldenContractError(f"fixture.schema_version must be {FIXTURE_SCHEMA}")
    name = payload.get("repository_name")
    if not isinstance(name, str) or not _SAFE_ID.fullmatch(name):
        raise GoldenContractError("fixture.repository_name is invalid")
    if payload.get("object_format") not in {"sha1", "sha256"}:
        raise GoldenContractError("fixture.object_format must be sha1 or sha256")
    commits = payload.get("commits")
    if not isinstance(commits, list) or not commits:
        raise GoldenContractError("fixture.commits must be a non-empty array")
    for index, commit in enumerate(commits):
        if not isinstance(commit, dict):
            raise GoldenContractError(f"fixture.commits[{index}] must be an object")
        _closed(commit, _COMMIT_KEYS, f"fixture.commits[{index}]")
        for key in _COMMIT_KEYS - {"files"}:
            value = commit.get(key)
            if not isinstance(value, str) or not value:
                raise GoldenContractError(f"fixture.commits[{index}].{key} is required")
        for key in ("author_date", "committer_date"):
            if not _TIMEZONE.search(str(commit[key])):
                raise GoldenContractError(
                    f"fixture.commits[{index}].{key} requires an explicit timezone"
                )
        files = commit.get("files")
        if not isinstance(files, dict) or not files:
            raise GoldenContractError(f"fixture.commits[{index}].files must be non-empty")
        for relative, content in files.items():
            _safe_relative(relative, path=f"fixture.commits[{index}].files")
            if content is not None and not isinstance(content, str):
                raise GoldenContractError(
                    f"fixture.commits[{index}].files.{relative} must be string or null"
                )
    return payload


def _git(argv: list[str], *, repo: Path, env: Mapping[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *argv],
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise GoldenContractError(
            f"fixture git command failed ({result.returncode}): {' '.join(argv)}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def materialize_fixture(fixture_path: Path, workspace: Path) -> tuple[Path, str]:
    """Create the deterministic Git repository described by one registered fixture."""

    fixture = _validate_fixture(_read_json(fixture_path, label="golden fixture"))
    repo = workspace / fixture["repository_name"]
    repo.mkdir(parents=True, exist_ok=False)
    result = subprocess.run(
        ["git", "init", "-q", f"--object-format={fixture['object_format']}", str(repo)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise GoldenContractError(f"git init failed: {result.stderr.strip()}")
    _git(["config", "core.autocrlf", "false"], repo=repo)
    _git(["config", "core.filemode", "false"], repo=repo)
    base_env = os.environ.copy()
    base_env.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
        }
    )
    for index, commit in enumerate(fixture["commits"]):
        for raw_relative, content in sorted(commit["files"].items()):
            relative = _safe_relative(raw_relative, path=f"fixture.commits[{index}].files")
            target = repo / relative
            if content is None:
                if target.exists() and target.is_file() and not target.is_symlink():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        _git(["add", "-A"], repo=repo, env=base_env)
        env = base_env | {
            "GIT_AUTHOR_NAME": commit["author_name"],
            "GIT_AUTHOR_EMAIL": commit["author_email"],
            "GIT_AUTHOR_DATE": commit["author_date"],
            "GIT_COMMITTER_NAME": commit["committer_name"],
            "GIT_COMMITTER_EMAIL": commit["committer_email"],
            "GIT_COMMITTER_DATE": commit["committer_date"],
        }
        _git(["commit", "-q", "--no-gpg-sign", "-m", commit["message"]], repo=repo, env=env)
    return repo, _git(["rev-parse", "HEAD"], repo=repo, env=base_env)


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TEP_GOLDEN", None)
    for secret_name in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITLAB_TOKEN",
        "CI_JOB_TOKEN",
        "COSIGN_PASSWORD",
    ):
        env.pop(secret_name, None)
    env.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    source = Path(__file__).resolve().parents[1] / "src"
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(source) if not current else os.pathsep.join((str(source), current))
    return env


def run_command(argv: list[str], *, cwd: Path, timeout_seconds: int, python: Path) -> CommandResult:
    started = time.monotonic()
    try:
        result = subprocess.run(
            [str(python), "-m", "tep_cli", *argv],
            cwd=cwd,
            env=_command_env(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise GoldenContractError(
            f"CLI timeout after {timeout_seconds}s: {' '.join(argv)}"
        ) from exc
    return CommandResult(
        argv=tuple(argv),
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def _normalize_d0(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: "<D0:runtime>" if key in _D0_KEYS else _normalize_d0(value)
            for key, value in sorted(node.items())
        }
    if isinstance(node, list):
        return [_normalize_d0(value) for value in node]
    return node


def _normalize_verified_member_metadata(node: dict[str, Any]) -> dict[str, Any]:
    """Remove digest cascades only after the CLI verified the raw collection.

    A D0 timestamp in ``repo-report.json`` changes that file's byte count/hash
    in ``collection-manifest.json``.  Provider display drift can do the same.
    Comparing those derived fields again would incorrectly promote D0/D1/D2
    into D3.  The raw bytes were already checked by the CLI collection verifier;
    the golden comparison classifies the underlying registered artifact itself.
    """

    result = dict(node)
    members = result.get("members")
    if not isinstance(members, list):
        return result
    normalized_members: list[Any] = []
    for member in members:
        if not isinstance(member, dict):
            normalized_members.append(member)
            continue
        normalized = dict(member)
        if "bytes" in normalized:
            normalized["bytes"] = "<VERIFIED:derived-member-metadata>"
        if "sha256" in normalized:
            normalized["sha256"] = "<VERIFIED:derived-member-metadata>"
        normalized_members.append(normalized)
    result["members"] = normalized_members
    return result


def observe_case(
    case: Mapping[str, Any], *, root: Path, workspace: Path, python: Path
) -> dict[str, Any]:
    """Run repo and verify through the CLI, then read only newly produced artifacts."""

    repo, head = materialize_fixture(root / str(case["fixture"]), workspace)
    out = workspace / "artifacts"
    repo_result = run_command(
        [
            "repo",
            str(repo),
            "--rev",
            head,
            "--format",
            "both",
            "--actors",
            "--out",
            str(out),
        ],
        cwd=workspace,
        timeout_seconds=int(case["timeout_seconds"]),
        python=python,
    )
    if repo_result.exit_code != 0:
        raise GoldenContractError(
            f"case {case['id']} repo CLI failed ({repo_result.exit_code}): "
            f"{repo_result.stderr.strip()}"
        )
    verify_result = run_command(
        ["verify", str(out), "--repo", str(repo)],
        cwd=workspace,
        timeout_seconds=int(case["timeout_seconds"]),
        python=python,
    )
    if verify_result.exit_code != 0 or not verify_result.stdout.startswith("VERIFIED:"):
        raise GoldenContractError(
            f"case {case['id']} verify CLI did not verify ({verify_result.exit_code}): "
            f"{verify_result.stdout.strip()} {verify_result.stderr.strip()}"
        )

    actual_files = sorted(
        candidate.relative_to(out).as_posix() for candidate in out.rglob("*") if candidate.is_file()
    )
    expected_files = list(case["expected_artifacts"])
    if actual_files != expected_files:
        raise GoldenContractError(
            f"case {case['id']} artifact inventory mismatch: "
            f"actual={actual_files}, expected={expected_files}"
        )
    artifacts: dict[str, Any] = {}
    for relative in actual_files:
        path = out / relative
        raw = path.read_bytes()
        if path.suffix == ".json":
            content = _normalize_d0(_read_json(path, label=f"artifact {relative}"))
            if relative == "collection-manifest.json":
                content = _normalize_verified_member_metadata(content)
            artifacts[relative] = {
                "kind": "json",
                "content": content,
            }
        else:
            artifacts[relative] = {
                "kind": "bytes",
                "sha256": _sha256_bytes(raw),
                "size": len(raw),
            }
    return {
        "schema_version": OBSERVATION_SCHEMA,
        "case_id": case["id"],
        "target_oid": {"algorithm": "sha256" if len(head) == 64 else "sha1", "value": head},
        "commands": {
            "repo": {"exit_code": repo_result.exit_code},
            "verify": {
                "exit_code": verify_result.exit_code,
                "stdout": verify_result.stdout.strip(),
                "mode": "strict_actor_collection",
            },
        },
        "artifacts": artifacts,
    }


def _flatten(node: Any, path: str = "$") -> dict[str, Any]:
    if isinstance(node, dict):
        if not node:
            return {path: {}}
        result: dict[str, Any] = {}
        for key, value in sorted(node.items()):
            result.update(_flatten(value, f"{path}.{key}"))
        return result
    if isinstance(node, list):
        if not node:
            return {path: []}
        result = {}
        for index, value in enumerate(node):
            result.update(_flatten(value, f"{path}[{index}]"))
        return result
    return {path: node}


def classify_drift(path: str) -> str:
    """Classify one changed JSON path using fail-closed D0-D4 priority."""

    components = set(re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", path))
    if components & _D4_KEYS:
        return "D4"
    if components & _D3_KEYS:
        return "D3"
    if components & _D2_KEYS:
        return "D2"
    if components & _D1_KEYS:
        return "D1"
    if components & _D0_KEYS:
        return "D0"
    if ".artifacts.actors/" in path:
        return "D3"
    return "D3"


def compare_observation(expected: Any, actual: Any) -> list[dict[str, Any]]:
    left = _flatten(expected)
    right = _flatten(actual)
    differences: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        expected_value = left.get(path, "<MISSING>")
        actual_value = right.get(path, "<MISSING>")
        if expected_value == actual_value:
            continue
        differences.append(
            {
                "path": path,
                "class": classify_drift(path),
                "expected": expected_value,
                "actual": actual_value,
            }
        )
    return differences


def _verdict(differences: list[dict[str, Any]]) -> str:
    classes = {item["class"] for item in differences}
    if "D4" in classes:
        return "MIGRATION_REQUIRED"
    if "D3" in classes:
        return "FAIL"
    if "D2" in classes:
        return "SOURCE_DRIFT"
    if classes:
        return "PASS_WITH_ALLOWED_DRIFT"
    return "PASS"


def run_manifest(
    manifest_path: Path,
    *,
    python: Path = Path(sys.executable),
    work_root: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    root = Path(manifest["_manifest_path"]).parent
    owned_temp = None
    if work_root is None:
        owned_temp = tempfile.TemporaryDirectory(prefix="grift-v060-golden-")
        work_root = Path(owned_temp.name)
    work_root.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(manifest["cases"]):
            case_workspace = work_root / f"{index:02d}-{case['id']}"
            case_workspace.mkdir(parents=True, exist_ok=False)
            observed = observe_case(case, root=root, workspace=case_workspace, python=python)
            expected = _read_json(root / case["expected"], label="golden expected")
            differences = compare_observation(expected, observed)
            counts = Counter(item["class"] for item in differences)
            case_results.append(
                {
                    "id": case["id"],
                    "verdict": _verdict(differences),
                    "drift_counts": {
                        key: counts.get(key, 0) for key in ("D0", "D1", "D2", "D3", "D4")
                    },
                    "differences": differences,
                    "observation_sha256": _sha256_bytes(_canonical_bytes(observed)),
                    "cli_executed": ["repo", "verify"],
                }
            )
    finally:
        if owned_temp is not None:
            owned_temp.cleanup()
    verdicts = {item["verdict"] for item in case_results}
    if "MIGRATION_REQUIRED" in verdicts:
        overall = "MIGRATION_REQUIRED"
    elif "FAIL" in verdicts:
        overall = "FAIL"
    elif "SOURCE_DRIFT" in verdicts:
        overall = "SOURCE_DRIFT"
    elif "PASS_WITH_ALLOWED_DRIFT" in verdicts:
        overall = "PASS_WITH_ALLOWED_DRIFT"
    else:
        overall = "PASS"
    return {
        "schema_version": RESULT_SCHEMA,
        "manifest_sha256": manifest["_manifest_digest"],
        "drift_policy_version": DRIFT_POLICY_VERSION,
        "overall": overall,
        "case_count": len(case_results),
        "cases": case_results,
        "baseline_update": "forbidden_automatic",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "v060"
        / "golden"
        / "manifest.json",
    )
    parser.add_argument("--result", type=Path, default=None)
    parser.add_argument("--work-root", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args(argv)
    try:
        result = run_manifest(
            args.manifest,
            python=args.python,
            work_root=args.work_root,
        )
    except GoldenContractError as exc:
        failure = {
            "schema_version": RESULT_SCHEMA,
            "overall": "CANNOT_VERIFY",
            "error": str(exc),
            "baseline_update": "forbidden_automatic",
        }
        encoded = json.dumps(failure, indent=2, ensure_ascii=False) + "\n"
        if args.result is not None:
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(encoded, encoding="utf-8")
        sys.stderr.write(encoded)
        return 2
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.result is not None:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if result["overall"] in {"PASS", "PASS_WITH_ALLOWED_DRIFT"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
