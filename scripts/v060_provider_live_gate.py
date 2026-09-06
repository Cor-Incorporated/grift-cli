#!/usr/bin/env python3
"""Run and verify the explicit v0.6 provider live gate.

The generator is intentionally absent from ordinary CI.  It consumes full
clones prepared by the manual workflow and keeps raw provider CAS bundles in a
temporary directory.  It emits a closed, source-bound summary and guard
ledger; the PR tier can additionally export a sanitized digest-only registry
without raw response bodies.  The verifier is used by the publish workflow to
prove that a successful release-tier run observed the exact commit being
published.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote_to_bytes

from tep_core.public_evidence import verify_public_evidence
from tep_core.secure_output import (
    SecureOutputError,
    lexical_absolute,
    lstat_at,
    open_directory_at,
    open_secure_parent,
    trusted_top_alias,
    write_private_at,
)

from v060_scenario_matrix import (
    ScenarioContractError,
    build_summary,
    build_runner_binding,
    isolated_subprocess_environment,
    public_acquisition_digest,
    materialize_read_only_repo,
    report_metrics,
    verify_digest_only_registry,
)

SCHEMA_VERSION = "v060-provider-live-summary-v1"
GUARD_ID = "v060-provider-live"
TOTAL_TIMEOUT_SECONDS = 30 * 60
RETIRE_CONDITION = (
    "retire only after two consecutive releases use an equivalent provider-neutral "
    "live gate with the same six fixed-OID assertions and publish admission"
)
PAIR_CONTRACT = "SCENARIOS declaration -> validate_scenario_result enforcement"
NEGATIVE_CASE = "expectation mutation must produce FAIL and process exit 1"
PUBLIC_REGISTRY_SUITE_ID = "v060-public-live-gates"
PUBLIC_REGISTRY_DEFINITION_VERSION = "scenario-public-v2"
MERGE_BASIS = (
    "repo_human_nonmerge_commits + merge_count = "
    "attribution_human_including_merges + attribution_unresolved_commit_count"
)
_HEX = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_TEXT = (
    "/Users/",
    "/tmp/",
    "https://",
    "http://",
    "authorization:",
    "bearer ",
    "private-token",
    "access_token=",
    "blobs/sha256",
)
_PRIVATE_RESUME_MARKER = ".grift-v060-private-resume-v1"
_PRIVATE_RESUME_MARKER_BODY = b"grift-v060-private-resume-v1\n"
_SAFE_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_PROVIDER_TOKEN_ENVS = ("V060_GITHUB_TOKEN", "V060_GITLAB_TOKEN")


class GateError(RuntimeError):
    """A closed live-gate contract was not satisfied."""


class GateTimeout(GateError):
    """A scenario exceeded its declared wall-clock deadline."""


@dataclass(frozen=True)
class ExpectedCounts:
    total: int
    raw_nonmerge: int
    raw_merge: int
    human_nonmerge: int
    human_merge: int
    bots: int
    actors: int


@dataclass(frozen=True)
class AcquisitionContext:
    """The acquisition chain fixed before a scenario starts."""

    collection_mode: str = "fresh"
    prior_evidence_digests: dict[str, dict[str, str]] | None = None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    tiers: tuple[str, ...]
    repo_dir: str
    provider: str
    target_oid: str
    counts: ExpectedCounts
    max_pages: int
    expected_pages: int
    expected_items: int
    expected_missing: int
    expected_coverage: str
    timeout_seconds: int
    account_linkage: str

    @property
    def expected_partial(self) -> bool:
        return self.expected_coverage == "partial"


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "P01-cloudflare-full",
        ("pr", "release"),
        "cloudflare-os",
        "github",
        "4f42d625a994a7bff4a3091a6b06897ab2e4d79c",
        ExpectedCounts(667, 442, 225, 438, 225, 4, 18),
        100,
        7,
        667,
        0,
        "complete",
        180,
        "complete",
    ),
    Scenario(
        "P02-vite-forced-partial",
        ("pr", "release"),
        "vite",
        "github",
        "e2b597de0ef14598901703f5aa52f8c962007d02",
        ExpectedCounts(9642, 9572, 70, 9102, 70, 470, 1368),
        1,
        1,
        100,
        9542,
        "partial",
        600,
        "complete",
    ),
    Scenario(
        "P03-gitlab-release-cli-full",
        ("pr", "release"),
        "release-cli",
        "gitlab",
        "07d5e21c6610f781b65d7196c5d0e86e73bcc6be",
        ExpectedCounts(453, 290, 163, 290, 163, 0, 47),
        100,
        5,
        453,
        0,
        "complete",
        180,
        "unsupported",
    ),
    Scenario(
        "L01-vite-full",
        ("release",),
        "vite",
        "github",
        "e2b597de0ef14598901703f5aa52f8c962007d02",
        ExpectedCounts(9642, 9572, 70, 9102, 70, 470, 1368),
        100,
        97,
        9642,
        0,
        "complete",
        600,
        "complete",
    ),
    Scenario(
        "L02-voicevox-full",
        ("release",),
        "voicevox",
        "github",
        "c72a94cbcf501be054a239446c7eb8cf53be34b4",
        ExpectedCounts(1899, 1810, 89, 1810, 89, 0, 118),
        100,
        19,
        1899,
        0,
        "complete",
        180,
        "complete",
    ),
    Scenario(
        "L03-gitlab-cli-full",
        ("release",),
        "cli",
        "gitlab",
        "05e9a796977441dcede9d1cc691f55c5ff4cc07b",
        ExpectedCounts(6127, 3642, 2485, 3422, 2482, 223, 369),
        100,
        62,
        6127,
        0,
        "complete",
        600,
        "unsupported",
    ),
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _definition_payload(tier: str) -> list[dict[str, Any]]:
    return [
        {
            **dataclasses.asdict(spec),
            "counts": dataclasses.asdict(spec.counts),
        }
        for spec in SCENARIOS
        if tier in spec.tiers
    ]


def definition_digest(tier: str) -> str:
    return _sha256(_canonical(_definition_payload(tier)))


def _selected(tier: str) -> tuple[Scenario, ...]:
    selected = tuple(spec for spec in SCENARIOS if tier in spec.tiers)
    if tier not in {"pr", "release"} or not selected:
        raise GateError("unsupported gate tier")
    ids = [spec.scenario_id for spec in selected]
    if len(ids) != len(set(ids)):
        raise GateError("scenario declaration contains duplicate IDs")
    return selected


def _safe_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def _reject_symlink_components(path: Path) -> Path:
    try:
        absolute = lexical_absolute(path)
    except SecureOutputError as exc:
        raise GateError("private resume path is not lexically safe") from exc
    root = Path(absolute.anchor)
    root_metadata = root.lstat()
    candidate = root
    for index, component in enumerate(absolute.parts[1:]):
        candidate /= component
        try:
            metadata = candidate.lstat()
            mode = metadata.st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            if trusted_top_alias(
                index=index,
                component=component,
                entry_stat=metadata,
                root_stat=root_metadata,
            ):
                continue
            raise GateError("private resume path must not traverse a symlink")
    return absolute


def _read_open_file(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _validate_private_marker(root_fd: int, *, create: bool) -> bool:
    marker_metadata = lstat_at(root_fd, _PRIVATE_RESUME_MARKER)
    if marker_metadata is None:
        if os.listdir(root_fd):
            raise GateError("refusing an unowned non-empty private resume root")
        if not create:
            return False
        try:
            write_private_at(root_fd, _PRIVATE_RESUME_MARKER, _PRIVATE_RESUME_MARKER_BODY)
        except SecureOutputError as exc:
            raise GateError("private resume root marker cannot be created safely") from exc
        marker_metadata = lstat_at(root_fd, _PRIVATE_RESUME_MARKER)
    if (
        marker_metadata is None
        or stat.S_ISLNK(marker_metadata.st_mode)
        or not stat.S_ISREG(marker_metadata.st_mode)
    ):
        raise GateError("private resume root marker is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        marker_fd = os.open(_PRIVATE_RESUME_MARKER, flags, dir_fd=root_fd)
    except OSError as exc:
        raise GateError("private resume root marker cannot be opened safely") from exc
    try:
        opened = os.fstat(marker_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != marker_metadata.st_dev
            or opened.st_ino != marker_metadata.st_ino
        ):
            raise GateError("private resume root marker changed while opening")
        if _read_open_file(marker_fd) != _PRIVATE_RESUME_MARKER_BODY:
            raise GateError("private resume root marker differs")
        os.fchmod(marker_fd, 0o600)
    finally:
        os.close(marker_fd)
    return True


@contextmanager
def _open_private_resume_root(path: Path, *, create: bool):
    root = _reject_symlink_components(path)
    try:
        parent_context = open_secure_parent(root, create=create)
    except SecureOutputError as exc:
        if not create and not root.exists():
            yield None
            return
        raise GateError("private resume root parent is unsafe") from exc
    with parent_context as parent:
        metadata = lstat_at(parent.fd, parent.leaf)
        if metadata is None:
            if not create:
                yield None
                return
            try:
                os.mkdir(parent.leaf, mode=0o700, dir_fd=parent.fd)
            except OSError as exc:
                raise GateError("private resume root cannot be created") from exc
        try:
            root_fd = open_directory_at(parent.fd, parent.leaf)
        except SecureOutputError as exc:
            raise GateError("private resume root must be a real directory") from exc
        try:
            opened = os.fstat(root_fd)
            if opened.st_uid != os.getuid():
                raise GateError("private resume root must be owned by the current user")
            os.fchmod(root_fd, 0o700)
            if not _validate_private_marker(root_fd, create=create):
                yield None
                return
            yield (parent.path / parent.leaf, root_fd)
        finally:
            os.close(root_fd)


def _private_resume_root(path: Path, *, create: bool) -> Path | None:
    with _open_private_resume_root(path, create=create) as opened:
        return None if opened is None else opened[0]


def _private_bundle_path(root: Path, spec: Scenario, *, create_root: bool) -> Path | None:
    if _SAFE_SCENARIO_ID.fullmatch(spec.scenario_id) is None:
        raise GateError("scenario ID is unsafe for private resume storage")
    owned_root = _private_resume_root(root, create=create_root)
    return None if owned_root is None else owned_root / spec.scenario_id


def _paths_overlap(first: Path, second: Path) -> bool:
    lexical_left = Path(os.path.abspath(first))
    lexical_right = Path(os.path.abspath(second))
    physical_left = Path(os.path.realpath(lexical_left))
    physical_right = Path(os.path.realpath(lexical_right))

    def overlaps(left: Path, right: Path) -> bool:
        return left == right or left in right.parents or right in left.parents

    return overlaps(lexical_left, lexical_right) or overlaps(physical_left, physical_right)


def _validate_resumable_bundle(bundle: Path, spec: Scenario) -> dict[str, Any]:
    _preflight_private_bundle_source(bundle)
    verified = verify_public_evidence(bundle)
    if verified.get("status") != "VERIFIED":
        raise GateError("private resume bundle failed offline verification")
    manifest = _load_object(bundle / "manifest.json")
    pagination = manifest.get("pagination")
    coverage = manifest.get("coverage")
    target = manifest.get("target_oid")
    if manifest.get("provider") != spec.provider:
        raise GateError("private resume bundle provider differs")
    if not isinstance(target, Mapping) or target.get("value") != spec.target_oid:
        raise GateError("private resume bundle target differs")
    if not isinstance(coverage, Mapping) or coverage.get("status") == "complete":
        raise GateError("private resume bundle is not partial")
    if not isinstance(pagination, Mapping) or not isinstance(
        pagination.get("next_request"), Mapping
    ):
        raise GateError("private resume bundle has no safe cursor")
    return manifest


def _prior_evidence_digests(
    bundle: Path,
    spec: Scenario,
    *,
    secrets: Sequence[str] = (),
) -> dict[str, dict[str, str]]:
    """Bind a resume run to the exact verified bundle it continued."""

    _secure_private_bundle_tree(bundle, secrets=secrets)
    manifest = _validate_resumable_bundle(bundle, spec)
    manifest_body = (bundle / "manifest.json").read_bytes()
    payload = manifest.get("bundle_payload_sha256")
    if _SHA256.fullmatch(str(payload or "")) is None:
        raise GateError("private resume bundle payload digest is malformed")
    return {
        "manifest": {"algorithm": "sha256", "value": _sha256(manifest_body)},
        "payload": {"algorithm": "sha256", "value": str(payload)},
    }


def _acquisition_context(
    root: Path,
    spec: Scenario,
    *,
    secrets: Sequence[str] = (),
) -> AcquisitionContext:
    if spec.expected_partial:
        return AcquisitionContext()
    preserved = _private_bundle_path(root, spec, create_root=False)
    if preserved is None or not preserved.exists():
        return AcquisitionContext()
    return AcquisitionContext(
        collection_mode="resume",
        prior_evidence_digests=_prior_evidence_digests(
            preserved,
            spec,
            secrets=secrets,
        ),
    )


def _preflight_private_bundle_source(bundle: Path) -> None:
    """Reject links/devices before any bundle member is opened or copied."""

    try:
        root_mode = bundle.lstat().st_mode
    except FileNotFoundError as exc:
        raise GateError("private resume bundle is unavailable") from exc
    if not stat.S_ISDIR(root_mode) or stat.S_ISLNK(root_mode):
        raise GateError("private resume bundle is not a real directory")
    pending = [bundle]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    raise GateError("private resume bundle contains a symlink")
                child = Path(entry.path)
                if stat.S_ISDIR(mode):
                    pending.append(child)
                elif not stat.S_ISREG(mode):
                    raise GateError("private resume bundle contains a non-regular member")


def _secure_private_bundle_tree(
    bundle: Path,
    *,
    secrets: Sequence[str] = (),
) -> None:
    secret_bytes = tuple(secret.encode("utf-8") for secret in secrets if secret)
    for path in (bundle, *bundle.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise GateError("private resume bundle contains a symlink")
        if stat.S_ISDIR(mode):
            path.chmod(0o700)
            continue
        if not stat.S_ISREG(mode):
            raise GateError("private resume bundle contains a non-regular member")
        body = path.read_bytes()
        if secret_bytes:
            decoded = body
            for depth in range(17):
                if any(secret in decoded for secret in secret_bytes):
                    raise GateError("private resume bundle contains a provider credential")
                candidate = unquote_to_bytes(decoded)
                if candidate == decoded:
                    break
                if depth == 16:
                    raise GateError("private resume bundle is excessively percent encoded")
                decoded = candidate
        path.chmod(0o600)
    manifest_text = (bundle / "manifest.json").read_text(encoding="utf-8").casefold()
    if '"authorization"' in manifest_text or '"private-token"' in manifest_text:
        raise GateError("private resume manifest contains an authentication header")


def _seed_private_bundle(
    source: Path,
    destination: Path,
    spec: Scenario,
    *,
    secrets: Sequence[str] = (),
) -> None:
    _preflight_private_bundle_source(source)
    _secure_private_bundle_tree(source, secrets=secrets)
    _validate_resumable_bundle(source, spec)
    if destination.exists():
        raise GateError("temporary resume destination already exists")
    shutil.copytree(source, destination, symlinks=True)
    _secure_private_bundle_tree(destination, secrets=secrets)
    _validate_resumable_bundle(destination, spec)


def _preserve_private_bundle(
    source: Path,
    root: Path,
    spec: Scenario,
    *,
    secrets: Sequence[str] = (),
) -> Path:
    _preflight_private_bundle_source(source)
    _secure_private_bundle_tree(source, secrets=secrets)
    _validate_resumable_bundle(source, spec)
    target = _private_bundle_path(root, spec, create_root=True)
    assert target is not None
    owned_root = target.parent
    staging = Path(tempfile.mkdtemp(prefix=f".{spec.scenario_id}.staging-", dir=owned_root))
    backup: Path | None = None
    try:
        shutil.copytree(source, staging, symlinks=True, dirs_exist_ok=True)
        _secure_private_bundle_tree(staging, secrets=secrets)
        _validate_resumable_bundle(staging, spec)
        if target.exists():
            if target.is_symlink():
                raise GateError("private resume target is a symlink")
            _validate_resumable_bundle(target, spec)
            backup = Path(tempfile.mkdtemp(prefix=f".{spec.scenario_id}.backup-", dir=owned_root))
            backup.rmdir()
            os.replace(target, backup)
        try:
            os.replace(staging, target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return target
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _remove_private_bundle(root: Path, spec: Scenario) -> None:
    target = _private_bundle_path(root, spec, create_root=False)
    if target is None or not target.exists():
        return
    _validate_resumable_bundle(target, spec)
    shutil.rmtree(target)


def _has_private_bundle(root: Path, spec: Scenario) -> bool:
    try:
        target = _private_bundle_path(root, spec, create_root=False)
        if target is None or not target.exists():
            return False
        _validate_resumable_bundle(target, spec)
    except GateError:
        return False
    return True


def _write_json(path: Path, value: Any) -> bytes:
    body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    _assert_sanitized(body)
    _safe_write(path, body)
    return body


def _assert_sanitized(body: bytes, *, secrets: Sequence[str] = ()) -> None:
    text = body.decode("utf-8", errors="replace")
    folded = text.casefold()
    for needle in _FORBIDDEN_TEXT:
        if needle.casefold() in folded:
            raise GateError("sanitized evidence contains a forbidden location or credential marker")
    for secret in secrets:
        if secret and secret in text:
            raise GateError("sanitized evidence contains a provider credential")


def _environment(
    project_root: Path,
    *,
    selected_token_env: str | None = None,
    provider_tokens: Mapping[str, str] | None = None,
) -> dict[str, str]:
    pythonpath = str(project_root / "src")
    if os.environ.get("PYTHONPATH"):
        pythonpath += os.pathsep + os.environ["PYTHONPATH"]
    environment = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    token_values = dict(provider_tokens or {})
    for name in {*_DEFAULT_PROVIDER_TOKEN_ENVS, *token_values}:
        environment.pop(name, None)
    if selected_token_env is not None:
        selected = token_values.get(selected_token_env, "")
        if selected:
            environment[selected_token_env] = selected
    return environment


def _execute(
    argv: Sequence[str],
    *,
    project_root: Path,
    timeout_seconds: float,
    selected_token_env: str | None = None,
    provider_tokens: Mapping[str, str] | None = None,
) -> dict[str, int]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=project_root,
            env=_environment(
                project_root,
                selected_token_env=selected_token_env,
                provider_tokens=provider_tokens,
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.001, timeout_seconds),
        )
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
    return {
        "exit_code": exit_code,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }


def _remaining(deadline: float) -> float:
    return max(0.001, deadline - time.monotonic())


@contextmanager
def _wall_clock_deadline(seconds: float):
    """Interrupt every operation, including helper Git calls, at the deadline."""

    if not hasattr(signal, "setitimer"):
        raise GateError("wall-clock deadline enforcement is unavailable")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def expired(_signum: int, _frame: object) -> None:
        raise GateTimeout("scenario wall-clock deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _repo_command(
    repo: Path,
    spec: Scenario,
    output: Path,
    *,
    mode: str,
    bundle: Path | None,
    token_env: str | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tep_cli",
        "repo",
        str(repo),
        "--rev",
        spec.target_oid,
        "--actors",
        "--format",
        "both",
        "--out",
        str(output),
    ]
    if mode in {"fetch", "resume"}:
        assert bundle is not None
        command.extend(["--forge-provider", spec.provider])
        if mode == "fetch":
            command.extend(["--fetch-public", "--public-evidence-out", str(bundle)])
        else:
            command.extend(["--resume-public-evidence", str(bundle)])
        command.extend(["--max-public-pages", str(spec.max_pages)])
        if token_env is not None:
            command.extend(["--auth-token-env", token_env])
    elif mode == "replay":
        assert bundle is not None
        command.extend(["--public-evidence", str(bundle)])
    elif mode != "offline":
        raise GateError("unknown repository command mode")
    return command


def _verify_bundle_command(repo: Path, bundle: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tep_cli",
        "verify",
        "--public-evidence",
        str(bundle),
        "--repo",
        str(repo),
    ]


def _verify_collection_command(repo: Path, collection: Path, bundle: Path | None) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tep_cli",
        "verify",
        str(collection),
        "--repo",
        str(repo),
    ]
    if bundle is not None:
        command.extend(["--public-evidence", str(bundle)])
    return command


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError("required live-gate JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise GateError("required live-gate JSON is not an object")
    return value


def _provider_independent_repo(value: Any, path: tuple[str | int, ...] = ()) -> Any:
    """Remove only public display/coverage and runtime-varying report fields.

    The resulting value is deliberately broader than the existing count and
    partition checks.  It makes every other JSON difference observable while
    permitting the documented public-account display and provider coverage to
    differ between offline, partial, full and replay runs.  Fixed-tree license
    evidence remains in the projection because it is provider independent.
    """

    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, child in sorted(value.items(), key=lambda item: str(item[0])):
            key = str(raw_key)
            child_path = (*path, key)
            if path == ("attribution",) and key == "public_join":
                continue
            if path == ("input_coverage", "public_forge") and key != "repository_license":
                continue
            if path == ("provenance",) and key in {
                "analyzed_at",
                "public_evidence_digest",
            }:
                continue
            if path == ("provenance", "input_digests") and key == "public_evidence":
                continue
            if (
                len(path) == 3
                and path[:2] == ("actor_directory", "actors")
                and key in {"public_account_status", "public_accounts"}
            ):
                continue
            normalized[key] = _provider_independent_repo(child, child_path)
        return normalized
    if isinstance(value, list):
        return [
            _provider_independent_repo(child, (*path, index)) for index, child in enumerate(value)
        ]
    return value


def _provider_independent_actor_card(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _provider_independent_repo(child, (str(key),))
        for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        if str(key) not in {"account_status", "accounts"}
    }


def _numeric_digest(value: Any) -> str:
    leaves: list[dict[str, Any]] = []

    def visit(node: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            leaves.append({"path": list(path), "value": node})
            return
        if isinstance(node, float):
            if not math.isfinite(node):
                raise GateError("provider-independent numeric projection is non-finite")
            leaves.append({"path": list(path), "value": node})
            return
        if isinstance(node, Mapping):
            for raw_key, child in sorted(node.items(), key=lambda item: str(item[0])):
                visit(child, (*path, str(raw_key)))
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, (*path, index))

    visit(value, ())
    return _sha256(_canonical(leaves))


def _collection_state(root: Path) -> dict[str, Any]:
    report = _load_object(root / "repo-report.json")
    index = _load_object(root / "actor-index.json")
    card_payloads: dict[str, dict[str, Any]] = {}
    for card_path in sorted((root / "actors").glob("*.json")):
        card_payloads[card_path.name] = _load_object(card_path)
    if not card_payloads:
        raise GateError("provider-neutral actor cards are unavailable")
    normalized_repo = _provider_independent_repo(report)
    normalized_actors = {
        "index": index,
        "cards": {
            name: _provider_independent_actor_card(card) for name, card in card_payloads.items()
        },
    }
    metrics = report_metrics(report, index)
    attribution = report.get("attribution")
    population = report.get("population")
    partition = attribution.get("actor_partition") if isinstance(attribution, Mapping) else None
    if not isinstance(partition, Mapping) or not isinstance(population, Mapping):
        raise GateError("actor partition metadata is unavailable")
    digests: dict[str, str] = {}
    for relative in (
        "repo-report.json",
        "repo-report.md",
        "actor-index.json",
        "actor-index.md",
        "collection-manifest.json",
    ):
        path = root / relative
        try:
            digests[relative] = _sha256(path.read_bytes())
        except OSError as exc:
            raise GateError("required actor collection member is unavailable") from exc
    population_digest = population.get("population_digest")
    provenance = report.get("provenance")
    input_digests = provenance.get("input_digests") if isinstance(provenance, Mapping) else None
    license_evidence_digest = (
        input_digests.get("license_evidence") if isinstance(input_digests, Mapping) else None
    )
    # The CLI emits the closed digest object {algorithm, value}; accept only
    # that shape (sha256), never a bare string, so the state stays closed.
    if not isinstance(license_evidence_digest, Mapping):
        raise GateError("fixed-tree license evidence digest is unavailable")
    if (
        license_evidence_digest.get("algorithm") != "sha256"
        or _SHA256.fullmatch(str(license_evidence_digest.get("value") or "")) is None
    ):
        raise GateError("fixed-tree license evidence digest is unavailable")
    directory = report.get("actor_directory")
    actors = directory.get("actors") if isinstance(directory, Mapping) else None
    if actors is None:
        # The strict collection keeps the actor population in actor-index.json
        # and the per-actor account evidence in actors/<actor-id>.json cards.
        # Public account linkage is read from the cards only.
        actors = []
        for entry in card_payloads.values():
            if not isinstance(entry, Mapping):
                raise GateError("provider-neutral actor card is malformed")
            actors.append(
                {
                    "public_account_status": entry.get("account_status"),
                    "public_accounts": entry.get("accounts"),
                }
            )
    if not isinstance(actors, list):
        raise GateError("provider-neutral actor directory is unavailable")
    stable_accounts: set[tuple[str, str, str]] = set()
    account_statuses: dict[str, int] = {}
    public_handle_actors = 0
    for actor in actors:
        if not isinstance(actor, Mapping):
            raise GateError("provider-neutral actor directory is malformed")
        status = str(actor.get("public_account_status") or "unknown")
        account_statuses[status] = account_statuses.get(status, 0) + 1
        accounts = actor.get("public_accounts")
        if not isinstance(accounts, list):
            raise GateError("provider-neutral public account list is malformed")
        if accounts:
            public_handle_actors += 1
        for account in accounts:
            if not isinstance(account, Mapping):
                raise GateError("provider-neutral public account is malformed")
            key = tuple(str(account.get(name) or "") for name in ("provider", "host", "account_id"))
            if not all(key):
                raise GateError("provider-neutral public account lacks a stable key")
            stable_accounts.add(key)
    return {
        "counts": metrics["counts"],
        "partition_digest": metrics["partition_digest"],
        "sha_to_actor_digest": partition.get("sha_to_actor_digest"),
        "population_digest": (
            population_digest.get("value") if isinstance(population_digest, Mapping) else None
        ),
        "target_oid": (metrics.get("target_oid") or {}).get("value"),
        "merge_basis": metrics["merge_basis"],
        "output_sha256": digests,
        "license_evidence_digest": str(license_evidence_digest.get("value") or ""),
        "repo_provider_independent_digest": _sha256(_canonical(normalized_repo)),
        "repo_provider_independent_numeric_digest": _numeric_digest(normalized_repo),
        "actor_provider_independent_digest": _sha256(_canonical(normalized_actors)),
        "actor_provider_independent_numeric_digest": _numeric_digest(normalized_actors),
        "account_counts": {
            "stable": len(stable_accounts),
            "public_handle_actors": public_handle_actors,
            "statuses": account_statuses,
        },
    }


def _git_count(
    repo: Path,
    oid: str,
    *extra: str,
    timeout_seconds: float = 120,
    provider_tokens: Mapping[str, str] | None = None,
) -> int:
    completed = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            "rev-list",
            "--count",
            *extra,
            oid,
        ],
        env=_environment(Path.cwd(), provider_tokens=provider_tokens),
        capture_output=True,
        text=True,
        timeout=max(0.001, timeout_seconds),
    )
    if completed.returncode:
        raise GateError("fixed OID is absent from the prepared repository")
    try:
        return int(completed.stdout.strip())
    except ValueError as exc:
        raise GateError("Git count is not an integer") from exc


def _manifest_state(
    bundle: Path,
    repo: Path,
    spec: Scenario,
    *,
    provider_tokens: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    manifest_path = bundle / "manifest.json"
    manifest_body = manifest_path.read_bytes()
    manifest = _load_object(manifest_path)
    coverage = manifest.get("coverage")
    pagination = manifest.get("pagination")
    pages = manifest.get("pages")
    commit_oids = manifest.get("commit_oids")
    duplicates = manifest.get("duplicate_commit_oids")
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (coverage, Mapping),
            (pagination, Mapping),
            (pages, list),
            (commit_oids, list),
            (duplicates, list),
        )
    ):
        raise GateError("public evidence manifest shape is invalid")
    local = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            "rev-list",
            spec.target_oid,
        ],
        env=_environment(Path.cwd(), provider_tokens=provider_tokens),
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    ).stdout.splitlines()
    local_set = set(local)
    observed_set = {value for value in commit_oids if isinstance(value, str)}
    page_body_sha256: list[str] = []
    for page in pages:
        digest = page.get("body_sha256") if isinstance(page, Mapping) else None
        if _SHA256.fullmatch(str(digest or "")) is None:
            raise GateError("provider page body digest is malformed")
        blob = bundle / "blobs" / "sha256" / str(digest)
        try:
            body = blob.read_bytes()
        except OSError as exc:
            raise GateError("provider page CAS body is unavailable") from exc
        if _sha256(body) != digest:
            raise GateError("provider page CAS body digest differs")
        page_body_sha256.append(str(digest))
    payload_digest = manifest.get("bundle_payload_sha256")
    if _SHA256.fullmatch(str(payload_digest or "")) is None:
        raise GateError("provider bundle payload digest is malformed")
    sha_to_account = manifest.get("sha_to_account")
    if not isinstance(sha_to_account, Mapping):
        raise GateError("provider SHA-to-account mapping is malformed")
    stable_accounts: set[tuple[str, str, str]] = set()
    for account in sha_to_account.values():
        if not isinstance(account, Mapping):
            raise GateError("provider account mapping is malformed")
        key = tuple(str(account.get(name) or "") for name in ("provider", "host", "account_id"))
        if not all(key):
            raise GateError("provider account mapping lacks a stable key")
        stable_accounts.add(key)
    replay_verification = verify_public_evidence(bundle)
    resumable = (
        replay_verification.get("status") == "VERIFIED"
        and coverage.get("status") != "complete"
        and isinstance(pagination.get("next_request"), Mapping)
    )
    return {
        "coverage": str(coverage.get("status") or ""),
        "stop_reason": str(pagination.get("stop_reason") or ""),
        "pages": len(pages),
        "items": coverage.get("item_count"),
        "expected_oids": len(local_set),
        "observed_oids": len(observed_set),
        "missing_oids": len(local_set - observed_set),
        "extra_oids": len(observed_set - local_set),
        "duplicate_oids": len(duplicates),
        "account_linkage": manifest.get("account_linkage"),
        "bundle_payload_sha256": payload_digest,
        "manifest_sha256": _sha256(manifest_body),
        "page_body_sha256": page_body_sha256,
        "sha_to_account_count": len(sha_to_account),
        "stable_account_count": len(stable_accounts),
        "rate_partial": _is_long_rate_partial(manifest),
        "resumable": resumable,
    }


def _is_long_rate_partial(manifest: Mapping[str, Any]) -> bool:
    coverage = manifest.get("coverage")
    pages = manifest.get("pages")
    pagination = manifest.get("pagination")
    if not isinstance(coverage, Mapping) or coverage.get("status") == "complete":
        return False
    if not isinstance(pages, list) or not pages or not isinstance(pagination, Mapping):
        return False
    last = pages[-1]
    headers = last.get("response_headers") if isinstance(last, Mapping) else None
    if not isinstance(headers, Mapping):
        return False
    remaining = headers.get("x-ratelimit-remaining", headers.get("ratelimit-remaining"))
    reset_value = headers.get("x-ratelimit-reset", headers.get("ratelimit-reset"))
    try:
        reset_wait = int(str(reset_value)) - int(time.time())
    except (TypeError, ValueError):
        reset_wait = 0
    try:
        retry_after = int(str(headers.get("retry-after", "0")))
    except (TypeError, ValueError):
        retry_after = 0
    stopped_on_http = str(pagination.get("stop_reason", "")).startswith("http_")
    return stopped_on_http and (retry_after > 30 or (str(remaining) == "0" and reset_wait > 30))


def _expected_exit_contract(spec: Scenario, *, rate_partial: bool = False) -> dict[str, int]:
    partial = spec.expected_partial or rate_partial
    return {
        "offline": 0,
        "offline_collection_verify": 0,
        "fetch": 3 if partial else 0,
        "bundle_verify": 2 if partial else 0,
        "live_collection_verify": 2 if partial else 0,
        "replay": 3 if partial else 0,
        "replay_collection_verify": 2 if partial else 0,
    }


def validate_scenario_result(spec: Scenario, result: Mapping[str, Any]) -> list[str]:
    """Return stable mismatch IDs; declaration mutations must turn this red."""

    mismatch: list[str] = []

    def expect(identifier: str, expected: Any, actual: Any) -> None:
        if expected != actual:
            mismatch.append(identifier)

    states = result.get("states")
    provider = result.get("provider_evidence")
    exits = result.get("exit_contract")
    raw = result.get("git_counts")
    if not all(isinstance(value, Mapping) for value in (states, provider, exits, raw)):
        return ["result-shape"]
    assert isinstance(states, Mapping)
    assert isinstance(provider, Mapping)
    assert isinstance(exits, Mapping)
    assert isinstance(raw, Mapping)
    offline = states.get("offline")
    live = states.get("live")
    replay = states.get("replay")
    if not all(isinstance(value, Mapping) for value in (offline, live, replay)):
        return ["collection-state-shape"]
    assert isinstance(offline, Mapping)
    assert isinstance(live, Mapping)
    assert isinstance(replay, Mapping)
    expected_state_keys = {
        "counts",
        "partition_digest",
        "sha_to_actor_digest",
        "population_digest",
        "target_oid",
        "merge_basis",
        "output_sha256",
        "license_evidence_digest",
        "repo_provider_independent_digest",
        "repo_provider_independent_numeric_digest",
        "actor_provider_independent_digest",
        "actor_provider_independent_numeric_digest",
        "account_counts",
    }
    expected_target = {"algorithm": "sha1", "value": spec.target_oid}
    expect("result-target-oid", expected_target, result.get("target_oid"))
    expect("provider", spec.provider, result.get("provider"))
    expect("scenario-timeout-contract", spec.timeout_seconds, result.get("timeout_seconds"))
    duration = result.get("duration_ms")
    expect(
        "scenario-duration",
        True,
        isinstance(duration, int)
        and not isinstance(duration, bool)
        and 0 <= duration <= spec.timeout_seconds * 1000,
    )
    expect("no-sleep", 0, result.get("sleep_seconds"))
    staged = result.get("resumable_partial_staged")
    expect("resumable-partial-flag", True, isinstance(staged, bool))
    if isinstance(provider.get("resumable"), bool):
        expect(
            "resumable-partial-staged",
            provider.get("resumable") is True and not spec.expected_partial,
            staged,
        )
    else:
        mismatch.append("provider-resumable-flag")
    collection_mode = result.get("collection_mode")
    prior_digests = result.get("prior_evidence_digests")
    expect("collection-mode", True, collection_mode in {"fresh", "resume"})
    if collection_mode == "fresh":
        expect("fresh-prior-evidence", None, prior_digests)
    elif collection_mode == "resume":
        if not isinstance(prior_digests, Mapping) or set(prior_digests) != {
            "manifest",
            "payload",
        }:
            mismatch.append("resume-prior-evidence-shape")
        else:
            for label in ("manifest", "payload"):
                digest = prior_digests.get(label)
                if not isinstance(digest, Mapping) or digest != {
                    "algorithm": "sha256",
                    "value": str(digest.get("value") or "") if isinstance(digest, Mapping) else "",
                }:
                    mismatch.append(f"resume-prior-{label}-closed")
                elif _SHA256.fullmatch(str(digest.get("value") or "")) is None:
                    mismatch.append(f"resume-prior-{label}-digest")
    expect("merge-basis", MERGE_BASIS, offline.get("merge_basis"))
    expect("git-total", spec.counts.total, raw.get("total"))
    expect("git-nonmerge", spec.counts.raw_nonmerge, raw.get("nonmerge"))
    expect("git-merge", spec.counts.raw_merge, raw.get("merge"))
    counts = offline.get("counts")
    if not isinstance(counts, Mapping):
        mismatch.append("report-count-shape")
    else:
        expect("human-nonmerge", spec.counts.human_nonmerge, counts.get("report.human_nonmerge"))
        expect("human-merge", spec.counts.human_merge, counts.get("report.merge"))
        expect("bot-commits", spec.counts.bots, counts.get("report.bot"))
        expect("actor-count", spec.counts.actors, counts.get("actors.full"))
    expected_outputs = {
        "repo-report.json",
        "repo-report.md",
        "actor-index.json",
        "actor-index.md",
        "collection-manifest.json",
    }
    for label, state in (("offline", offline), ("live", live), ("replay", replay)):
        if set(state) != expected_state_keys:
            mismatch.append(f"collection-state-members-{label}")
        expect(f"target-oid-{label}", spec.target_oid, state.get("target_oid"))
        expect(f"merge-basis-{label}", MERGE_BASIS, state.get("merge_basis"))
        expect(f"counts-{label}", counts, state.get("counts"))
        outputs = state.get("output_sha256")
        if not isinstance(outputs, Mapping) or set(outputs) != expected_outputs:
            mismatch.append(f"output-digest-members-{label}")
        elif any(_SHA256.fullmatch(str(value)) is None for value in outputs.values()):
            mismatch.append(f"output-digest-value-{label}")
        for field in (
            "partition_digest",
            "sha_to_actor_digest",
            "population_digest",
            "repo_provider_independent_digest",
            "repo_provider_independent_numeric_digest",
            "actor_provider_independent_digest",
            "actor_provider_independent_numeric_digest",
        ):
            if _SHA256.fullmatch(str(state.get(field) or "")) is None:
                mismatch.append(f"{field}-format-{label}")
            expect(f"{field}-offline-{label}", offline.get(field), state.get(field))
    live_outputs = live.get("output_sha256")
    replay_outputs = replay.get("output_sha256")
    if isinstance(live_outputs, Mapping) and isinstance(replay_outputs, Mapping):
        for relative in ("actor-index.json", "actor-index.md"):
            expect(
                f"live-replay-{relative}-digest",
                live_outputs.get(relative),
                replay_outputs.get(relative),
            )
    rate_partial = bool(provider.get("rate_partial")) and not spec.expected_partial
    expected_exits = _expected_exit_contract(spec, rate_partial=rate_partial)
    for name, expected in expected_exits.items():
        expect(f"exit-{name}", expected, exits.get(name))
    if not rate_partial:
        expect("provider-coverage", spec.expected_coverage, provider.get("coverage"))
        expect(
            "provider-stop-reason",
            "max_pages_reached" if spec.expected_partial else "no_next_page",
            provider.get("stop_reason"),
        )
        expect("provider-pages", spec.expected_pages, provider.get("pages"))
        expect("provider-items", spec.expected_items, provider.get("items"))
        expect("oid-missing", spec.expected_missing, provider.get("missing_oids"))
        expect(
            "oid-observed", spec.counts.total - spec.expected_missing, provider.get("observed_oids")
        )
    expect("oid-expected", spec.counts.total, provider.get("expected_oids"))
    expect("oid-extra", 0, provider.get("extra_oids"))
    expect("oid-duplicates", 0, provider.get("duplicate_oids"))
    expect("account-linkage", spec.account_linkage, provider.get("account_linkage"))
    for identifier, key in (
        ("bundle-payload-digest", "bundle_payload_sha256"),
        ("public-manifest-digest", "manifest_sha256"),
    ):
        if _SHA256.fullmatch(str(provider.get(key) or "")) is None:
            mismatch.append(identifier)
    page_digests = provider.get("page_body_sha256")
    if (
        not isinstance(page_digests, list)
        or len(page_digests) != provider.get("pages")
        or any(_SHA256.fullmatch(str(value)) is None for value in page_digests)
    ):
        mismatch.append("provider-page-body-digests")
    if _SHA256.fullmatch(str(offline.get("license_evidence_digest") or "")) is None:
        mismatch.append("license-evidence-digest")
    return mismatch


def _digest(value: Any, *, label: str) -> dict[str, str]:
    text = str(value or "")
    if _SHA256.fullmatch(text) is None:
        raise GateError(f"{label} is not a SHA-256 digest")
    return {"algorithm": "sha256", "value": text}


def _public_runner(source: Mapping[str, Any], *, project_root: Path) -> dict[str, Any]:
    required = {
        "tool_version",
        "commit_oid",
        "source_tree_digest",
        "file_count",
        "definition_version",
    }
    if set(source) != required:
        raise GateError("public registry source binding is not closed")
    commit = source.get("commit_oid")
    if not isinstance(commit, Mapping) or not isinstance(commit.get("value"), str):
        raise GateError("public registry requires an immutable source commit")
    current = _source_summary(build_runner_binding(project_root), str(commit["value"]))
    if dict(source) != current:
        raise GateError("public registry source binding is stale")
    return {
        "tool_version": source["tool_version"],
        "source_binding": {
            "definition_version": source["definition_version"],
            "source_tree_digest": dict(source["source_tree_digest"]),
            "file_count": source["file_count"],
            "commit_oid": dict(commit),
        },
    }


def _logical_output_digests(spec: Scenario, result: Mapping[str, Any]) -> dict[str, Any]:
    states = result.get("states")
    provider = result.get("provider_evidence")
    if not isinstance(states, Mapping) or not isinstance(provider, Mapping):
        raise GateError("public registry live result lacks digest inputs")
    offline = states.get("offline")
    live = states.get("live")
    replay = states.get("replay")
    if not all(isinstance(value, Mapping) for value in (offline, live, replay)):
        raise GateError("public registry collection states are incomplete")
    assert isinstance(offline, Mapping)
    assert isinstance(live, Mapping)
    assert isinstance(replay, Mapping)
    logical: dict[str, Any] = {
        "derived/license-evidence": _digest(
            offline.get("license_evidence_digest"), label="license evidence digest"
        ),
        "derived/population": _digest(offline.get("population_digest"), label="population digest"),
        "derived/sha-to-actor": _digest(
            offline.get("sha_to_actor_digest"), label="SHA-to-Actor digest"
        ),
        "derived/repo-provider-independent": _digest(
            offline.get("repo_provider_independent_digest"),
            label="provider-independent repository digest",
        ),
        "derived/repo-provider-independent-numeric": _digest(
            offline.get("repo_provider_independent_numeric_digest"),
            label="provider-independent repository numeric digest",
        ),
        "derived/actor-provider-independent": _digest(
            offline.get("actor_provider_independent_digest"),
            label="provider-independent actor digest",
        ),
        "derived/actor-provider-independent-numeric": _digest(
            offline.get("actor_provider_independent_numeric_digest"),
            label="provider-independent actor numeric digest",
        ),
        "public-evidence/manifest.json": _digest(
            provider.get("manifest_sha256"), label="public manifest digest"
        ),
        "public-evidence/payload": _digest(
            provider.get("bundle_payload_sha256"), label="public payload digest"
        ),
    }
    pages = provider.get("page_body_sha256")
    if not isinstance(pages, list) or len(pages) != provider.get("pages"):
        raise GateError("public registry page digest sequence is incomplete")
    for number, value in enumerate(pages, start=1):
        logical[f"public-evidence/page-{number:02d}.body"] = _digest(
            value, label=f"public page {number} digest"
        )
    public_phase = "partial" if provider.get("coverage") != "complete" else "live"
    for state, phase in ((offline, "offline"), (live, public_phase), (replay, "replay")):
        outputs = state.get("output_sha256")
        if not isinstance(outputs, Mapping):
            raise GateError(f"{phase} collection digest map is unavailable")
        for relative, value in outputs.items():
            logical[f"{phase}/{relative}"] = _digest(
                value, label=f"{phase} collection member digest"
            )
    return logical


def _public_counts(result: Mapping[str, Any]) -> dict[str, int]:
    raw = result["git_counts"]
    states = result["states"]
    offline = states["offline"]
    live = states["live"]
    measured = offline["counts"]
    provider = result["provider_evidence"]
    exits = result["exit_contract"]
    collection_exits = [
        exits[name]
        for name in (
            "offline_collection_verify",
            "live_collection_verify",
            "replay_collection_verify",
        )
    ]
    counts = {
        "git.total": int(raw["total"]),
        "git.nonmerge": int(raw["nonmerge"]),
        "git.merge": int(raw["merge"]),
        "git.human": int(measured["report.human_nonmerge"]) + int(measured["report.merge"]),
        "git.bot": int(measured["report.bot"]),
        "actor.full": int(measured["actors.full"]),
        "metric.human-nonmerge.numerator": int(
            measured.get("metric.human_nonmerge.numerator", measured["report.human_nonmerge"])
        ),
        "metric.human-nonmerge.denominator": int(
            measured.get(
                "metric.human_nonmerge.denominator",
                int(measured["report.human_nonmerge"]) + int(measured["report.merge"]),
            )
        ),
        "provider.pages": int(provider["pages"]),
        "provider.items": int(provider["items"]),
        "provider.sha-to-account": int(provider.get("sha_to_account_count", 0)),
        "oid.expected": int(provider["expected_oids"]),
        "oid.observed": int(provider["observed_oids"]),
        "oid.missing": int(provider["missing_oids"]),
        "oid.extra": int(provider["extra_oids"]),
        "oid.duplicates": int(provider["duplicate_oids"]),
        "account.stable": int(provider.get("stable_account_count", 0)),
        "account.commit-linked": int(provider.get("sha_to_account_count", 0)),
        "verify.collections": len(collection_exits),
        "verify.verified": sum(value == 0 for value in collection_exits),
        "verify.cannot-verify": sum(value == 2 for value in collection_exits),
    }
    account_counts = live.get("account_counts")
    if isinstance(account_counts, Mapping):
        counts["account.stable"] = int(account_counts.get("stable", counts["account.stable"]))
        counts["account.public-handle-actors"] = int(account_counts.get("public_handle_actors", 0))
        statuses = account_counts.get("statuses")
        if isinstance(statuses, Mapping):
            for status, value in statuses.items():
                normalized = re.sub(r"[^a-z0-9.-]+", "-", str(status).casefold()).strip("-")
                if normalized:
                    counts[f"account.status-{normalized}-actors"] = int(value)
    if any(isinstance(value, bool) or value < 0 for value in counts.values()):
        raise GateError("public registry contains an invalid count")
    return counts


def _assertion(identifier: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "status": "PASS" if expected == actual else "FAIL",
        "expected": expected,
        "actual": actual,
    }


def _public_collection_argv(
    spec: Scenario,
    *,
    phase: str,
    collection_mode: str,
) -> list[str]:
    command = [
        "python",
        "-m",
        "tep_cli",
        "repo",
        f"${{DISPOSABLE_REPO}}/{spec.repo_dir}",
        "--rev",
        spec.target_oid,
        "--actors",
        "--format",
        "both",
        "--out",
        f"${{OUTPUT_ROOT}}/{spec.scenario_id}/{phase}",
        "--forge-provider",
        spec.provider,
    ]
    if collection_mode == "fresh":
        command.extend(
            [
                "--fetch-public",
                "--public-evidence-out",
                f"${{RAW_BUNDLE_ROOT}}/{spec.scenario_id}",
            ]
        )
    elif collection_mode == "resume":
        command.extend(
            [
                "--resume-public-evidence",
                f"${{RAW_BUNDLE_ROOT}}/{spec.scenario_id}",
            ]
        )
    else:
        raise GateError("provider collection mode is invalid")
    command.extend(["--max-public-pages", str(spec.max_pages)])
    return command


def _public_result(
    spec: Scenario,
    result: Mapping[str, Any],
    runner: Mapping[str, Any],
) -> dict[str, Any]:
    if result.get("outcome") != "PASS" or validate_scenario_result(spec, result):
        raise GateError(
            f"public registry scenario is not a successful live observation: {spec.scenario_id}"
        )
    provider = result["provider_evidence"]
    states = result["states"]
    offline = states["offline"]
    expected_exits = _expected_exit_contract(spec)
    exits = result["exit_contract"]
    collection_mode = result["collection_mode"]
    prior_evidence_digests = result["prior_evidence_digests"]
    coverage = (
        {"kind": "observed", "provided": True}
        if provider["coverage"] == "complete"
        else {
            "kind": "not_proven",
            "provided": True,
            "reason": "public_evidence_partial",
        }
    )
    phase = "partial" if spec.expected_partial else "live"
    public: dict[str, Any] = {
        "schema_version": "tep-public-scenario-result-v2",
        "scenario_id": spec.scenario_id,
        "runner": dict(runner),
        "target_oid": dict(result["target_oid"]),
        "argv": _public_collection_argv(
            spec,
            phase=phase,
            collection_mode=str(collection_mode),
        ),
        "collection_mode": collection_mode,
        "prior_evidence_digests": prior_evidence_digests,
        "exit_code": int(exits["fetch"]),
        "duration_ms": int(result["duration_ms"]),
        "counts": _public_counts(result),
        "partition_digest": _digest(
            offline.get("partition_digest"), label="actor partition digest"
        ),
        "provider_coverage": coverage,
        "output_digests": _logical_output_digests(spec, result),
        "assertions": [
            _assertion("runner-tool-version", runner["tool_version"], runner["tool_version"]),
            _assertion("target-oid", spec.target_oid, result["target_oid"]["value"]),
            *[
                _assertion(f"{name}-exit", expected, exits.get(name))
                for name, expected in expected_exits.items()
            ],
            _assertion("provider-coverage", spec.expected_coverage, provider.get("coverage")),
            _assertion("provider-pages", spec.expected_pages, provider.get("pages")),
            _assertion("provider-items", spec.expected_items, provider.get("items")),
            _assertion("oid-expected", spec.counts.total, provider.get("expected_oids")),
            _assertion(
                "oid-observed",
                spec.counts.total - spec.expected_missing,
                provider.get("observed_oids"),
            ),
            _assertion("oid-missing", spec.expected_missing, provider.get("missing_oids")),
            _assertion("oid-extra", 0, provider.get("extra_oids")),
            _assertion("oid-duplicate", 0, provider.get("duplicate_oids")),
            _assertion("git-total", spec.counts.total, result["git_counts"]["total"]),
            _assertion(
                "human-nonmerge",
                spec.counts.human_nonmerge,
                offline["counts"]["report.human_nonmerge"],
            ),
            _assertion("human-merge", spec.counts.human_merge, offline["counts"]["report.merge"]),
            _assertion("bot-commits", spec.counts.bots, offline["counts"]["report.bot"]),
            _assertion("actor-count", spec.counts.actors, offline["counts"]["actors.full"]),
            _assertion("account-linkage", spec.account_linkage, provider.get("account_linkage")),
            _assertion(
                "duration-within-limit",
                True,
                int(result["duration_ms"]) <= spec.timeout_seconds * 1000,
            ),
        ],
        "verdict": "PASS",
    }
    receipt = public_acquisition_digest(public)
    public["assertions"].append(
        {
            "id": "acquisition-receipt-digest",
            "status": "PASS",
            "expected": receipt["value"],
            "actual": receipt["value"],
        }
    )
    if any(row["status"] != "PASS" for row in public["assertions"]):
        raise GateError(f"public registry assertion failed: {spec.scenario_id}")
    return public


def _publish_public_registry(staged: Path, output_root: Path, *, replace: bool) -> None:
    if output_root.exists():
        if not replace:
            raise GateError("public registry output already exists; pass --replace-registry")
        existing = _load_object(output_root / "manifest.json")
        if (
            existing.get("schema_version") != "tep-scenario-manifest-v1"
            or existing.get("suite_id") != PUBLIC_REGISTRY_SUITE_ID
        ):
            raise GateError("refusing to replace an unrelated public registry")
        backup = output_root.parent / f".{output_root.name}.previous-{os.getpid()}"
        if backup.exists():
            raise GateError("public registry replacement backup already exists")
        os.replace(output_root, backup)
        try:
            os.replace(staged, output_root)
        except Exception:
            os.replace(backup, output_root)
            raise
        shutil.rmtree(backup)
        return
    os.replace(staged, output_root)


def export_public_registry(
    tier: str,
    results: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    output_root: Path,
    *,
    replace: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically export only sanitized PR-tier result/hash evidence."""

    if tier != "pr":
        raise GateError("the committed public registry is defined only for the PR tier")
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    runner = _public_runner(source, project_root=root)
    specs = _selected("pr")
    if [row.get("scenario_id") for row in results] != [spec.scenario_id for spec in specs]:
        raise GateError("public registry scenario membership or order differs")
    output_root = output_root.resolve()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".v060-public-registry-", dir=output_root.parent
    ) as temporary:
        staged = Path(temporary) / output_root.name
        staged.mkdir()
        manifest = {
            "schema_version": "tep-scenario-manifest-v1",
            "suite_id": PUBLIC_REGISTRY_SUITE_ID,
            "definition_version": PUBLIC_REGISTRY_DEFINITION_VERSION,
            "scenarios": [
                {
                    "id": spec.scenario_id,
                    "tier": "live-pr",
                    "target_oid": {"algorithm": "sha1", "value": spec.target_oid},
                    "expected_artifacts": ["scenario-result.json"],
                    "timeout_seconds": spec.timeout_seconds,
                }
                for spec in specs
            ],
        }
        manifest_path = staged / "manifest.json"
        _write_json(manifest_path, manifest)
        result_paths: list[Path] = []
        for spec, result in zip(specs, results, strict=True):
            public = _public_result(spec, result, runner)
            result_path = staged / spec.scenario_id / "scenario-result.json"
            _write_json(result_path, public)
            result_paths.append(result_path)
        summary = build_summary(manifest_path, result_paths)
        _write_json(staged / "summary.json", summary)
        verified = verify_digest_only_registry(staged, project_root=root)
        if verified != summary:
            raise GateError("public registry did not replay exactly")
        _publish_public_registry(staged, output_root, replace=replace)
        return summary


def _run_scenario_inner(
    spec: Scenario,
    *,
    source: Path,
    project_root: Path,
    token_env: str | None,
    provider_tokens: Mapping[str, str],
    acquisition: AcquisitionContext,
    suite_deadline: float,
    partial_bundle_root: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = min(suite_deadline, started + spec.timeout_seconds)
    raw_counts = {
        "total": _git_count(
            source,
            spec.target_oid,
            timeout_seconds=_remaining(deadline),
            provider_tokens=provider_tokens,
        ),
        "nonmerge": _git_count(
            source,
            spec.target_oid,
            "--no-merges",
            timeout_seconds=_remaining(deadline),
            provider_tokens=provider_tokens,
        ),
        "merge": _git_count(
            source,
            spec.target_oid,
            "--merges",
            timeout_seconds=_remaining(deadline),
            provider_tokens=provider_tokens,
        ),
    }
    with tempfile.TemporaryDirectory(prefix="grift-v060-live-") as temporary:
        temporary_root = Path(temporary)
        bundle = temporary_root / "public-evidence"
        offline = temporary_root / "offline"
        live = temporary_root / "live"
        replay = temporary_root / "replay"
        preserved_source = _private_bundle_path(
            partial_bundle_root,
            spec,
            create_root=False,
        )
        if spec.expected_partial and preserved_source is not None and preserved_source.exists():
            # A forced-partial scenario is a fixed one-page measurement, not a
            # resumable acquisition.  Remove only our owned legacy staging
            # directory so a prior run cannot silently grow the fixture.
            _remove_private_bundle(partial_bundle_root, spec)
            preserved_source = None
        resuming = acquisition.collection_mode == "resume"
        collection_mode = acquisition.collection_mode
        prior_evidence_digests = acquisition.prior_evidence_digests
        credential_values = tuple(value for value in provider_tokens.values() if value)
        staged = False
        if resuming:
            if preserved_source is None or not preserved_source.exists():
                raise GateError("fixed resume bundle disappeared before collection")
            _seed_private_bundle(
                preserved_source,
                bundle,
                spec,
                secrets=credential_values,
            )
        with materialize_read_only_repo(source, spec.target_oid) as repo:
            commands: dict[str, dict[str, int]] = {}
            commands["offline"] = _execute(
                _repo_command(repo, spec, offline, mode="offline", bundle=None, token_env=None),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                provider_tokens=provider_tokens,
            )
            commands["offline_collection_verify"] = _execute(
                _verify_collection_command(repo, offline, None),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                provider_tokens=provider_tokens,
            )
            commands["fetch"] = _execute(
                _repo_command(
                    repo,
                    spec,
                    live,
                    mode="resume" if resuming else "fetch",
                    bundle=bundle,
                    token_env=token_env,
                ),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                selected_token_env=token_env,
                provider_tokens=provider_tokens,
            )
            manifest_path = bundle / "manifest.json"
            if manifest_path.is_file():
                interim_manifest = _load_object(manifest_path)
                interim_coverage = interim_manifest.get("coverage")
                interim_pagination = interim_manifest.get("pagination")
                if (
                    not spec.expected_partial
                    and isinstance(interim_coverage, Mapping)
                    and interim_coverage.get("status") != "complete"
                    and isinstance(interim_pagination, Mapping)
                    and isinstance(interim_pagination.get("next_request"), Mapping)
                ):
                    _preserve_private_bundle(
                        bundle,
                        partial_bundle_root,
                        spec,
                        secrets=credential_values,
                    )
                    staged = True
            commands["bundle_verify"] = _execute(
                _verify_bundle_command(repo, bundle),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                provider_tokens=provider_tokens,
            )
            commands["live_collection_verify"] = _execute(
                _verify_collection_command(repo, live, bundle),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                provider_tokens=provider_tokens,
            )
            commands["replay"] = _execute(
                _repo_command(repo, spec, replay, mode="replay", bundle=bundle, token_env=None),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                provider_tokens=provider_tokens,
            )
            commands["replay_collection_verify"] = _execute(
                _verify_collection_command(repo, replay, bundle),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
                provider_tokens=provider_tokens,
            )
            states = {
                "offline": _collection_state(offline),
                "live": _collection_state(live),
                "replay": _collection_state(replay),
            }
            provider = _manifest_state(
                bundle,
                repo,
                spec,
                provider_tokens=provider_tokens,
            )
        if not spec.expected_partial and provider.get("resumable") is True and not staged:
            _preserve_private_bundle(
                bundle,
                partial_bundle_root,
                spec,
                secrets=credential_values,
            )
            staged = True
        elif resuming and provider.get("coverage") == "complete":
            _remove_private_bundle(partial_bundle_root, spec)
        result: dict[str, Any] = {
            "scenario_id": spec.scenario_id,
            "provider": spec.provider,
            "target_oid": {"algorithm": "sha1", "value": spec.target_oid},
            "timeout_seconds": spec.timeout_seconds,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "git_counts": raw_counts,
            "exit_contract": {name: value["exit_code"] for name, value in commands.items()},
            "command_duration_ms": {name: value["duration_ms"] for name, value in commands.items()},
            "provider_evidence": provider,
            "states": states,
            "sleep_seconds": 0,
            "collection_mode": collection_mode,
            "prior_evidence_digests": prior_evidence_digests,
            "resumable_partial_staged": staged,
        }
        mismatches = validate_scenario_result(spec, result)
        result["mismatch_ids"] = mismatches
        if not mismatches and provider["rate_partial"] and not spec.expected_partial:
            result["outcome"] = "PARTIAL"
        else:
            result["outcome"] = "PASS" if not mismatches else "FAIL"
        return result


def _run_scenario(
    spec: Scenario,
    *,
    source: Path,
    project_root: Path,
    token_env: str | None,
    provider_tokens: Mapping[str, str],
    acquisition: AcquisitionContext,
    suite_deadline: float,
    partial_bundle_root: Path,
) -> dict[str, Any]:
    limit = min(float(spec.timeout_seconds), _remaining(suite_deadline))
    with isolated_subprocess_environment(tuple(provider_tokens)):
        with _wall_clock_deadline(limit):
            return _run_scenario_inner(
                spec,
                source=source,
                project_root=project_root,
                token_env=token_env,
                provider_tokens=provider_tokens,
                acquisition=acquisition,
                suite_deadline=suite_deadline,
                partial_bundle_root=partial_bundle_root,
            )


def _failure_detail(error: BaseException | None, secrets: Sequence[str] = ()) -> str | None:
    """Return one sanitized ``ClassName: message`` line, or ``None``.

    A bare ``scenario-execution-failed`` mismatch id says nothing about why the
    run died, which is how the v0.7.0 release tier hid a hard ``exit 2``.  The
    detail is display text on an untrusted exception message, so it is held to
    the same sanitization contract as every other emitted byte: if it would not
    survive ``_assert_sanitized`` the message is dropped and only the exception
    class survives.  Never widen this by pre-scrubbing the message in place.
    """

    if error is None:
        return None
    detail = f"{type(error).__name__}: {str(error)[:200]}"
    try:
        _assert_sanitized(detail.encode("utf-8"), secrets=secrets)
    except GateError:
        return f"{type(error).__name__}: <redacted>"
    return detail


def _failure_result(
    spec: Scenario,
    reason: str,
    started: float,
    *,
    partial_staged: bool = False,
    acquisition: AcquisitionContext | None = None,
    error: BaseException | None = None,
    secrets: Sequence[str] = (),
) -> dict[str, Any]:
    fixed = acquisition or AcquisitionContext()
    return {
        "scenario_id": spec.scenario_id,
        "provider": spec.provider,
        "target_oid": {"algorithm": "sha1", "value": spec.target_oid},
        "timeout_seconds": spec.timeout_seconds,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "git_counts": {},
        "exit_contract": {},
        "command_duration_ms": {},
        "provider_evidence": {},
        "states": {},
        "sleep_seconds": 0,
        "collection_mode": fixed.collection_mode,
        "prior_evidence_digests": fixed.prior_evidence_digests,
        "resumable_partial_staged": partial_staged,
        "mismatch_ids": [reason],
        "failure_detail": _failure_detail(error, secrets),
        "outcome": "FAIL",
    }


def _ledger_bytes(tier: str, results: Sequence[Mapping[str, Any]], definition: str) -> bytes:
    rows = [
        {
            "guard_id": GUARD_ID,
            "tier": tier,
            "scenario_id": result["scenario_id"],
            "outcome": result["outcome"],
            "definition_digest": definition,
            "negative_case": NEGATIVE_CASE,
            "retire_condition": RETIRE_CONDITION,
            "pair_contract": PAIR_CONTRACT,
        }
        for result in results
    ]
    return b"".join(_canonical(row) + b"\n" for row in rows)


def _source_summary(binding: Mapping[str, Any], expected_commit: str) -> dict[str, Any]:
    source = binding.get("source_binding")
    if not isinstance(source, Mapping):
        raise GateError("runner source binding is unavailable")
    commit = source.get("commit_oid")
    if not isinstance(commit, Mapping) or commit.get("value") != expected_commit:
        raise GateError("runner source is not represented by the expected immutable commit")
    digest = source.get("source_tree_digest")
    if not isinstance(digest, Mapping) or _SHA256.fullmatch(str(digest.get("value") or "")) is None:
        raise GateError("runner source tree digest is invalid")
    return {
        "tool_version": binding.get("tool_version"),
        "commit_oid": dict(commit),
        "source_tree_digest": dict(digest),
        "file_count": source.get("file_count"),
        "definition_version": source.get("definition_version"),
    }


def run_gate(args: argparse.Namespace) -> int:
    started = time.monotonic()
    tier = args.tier
    specs = _selected(tier)
    registry_output = getattr(args, "registry_output", None)
    replace_registry = bool(getattr(args, "replace_registry", False))
    partial_bundle_root = Path(
        getattr(args, "partial_bundle_root", None)
        or (args.summary.parent / "private-resume-staging")
    )
    partial_bundle_root = _reject_symlink_components(partial_bundle_root)
    if registry_output is not None and tier != "pr":
        raise GateError("--registry-output is available only for the PR tier")
    if replace_registry and registry_output is None:
        raise GateError("--replace-registry requires --registry-output")
    protected_paths = [args.summary, args.ledger, args.repo_root]
    if registry_output is not None:
        protected_paths.append(registry_output)
    if any(_paths_overlap(partial_bundle_root, path) for path in protected_paths):
        raise GateError("private resume root must not overlap outputs, registry, or source repos")
    token_env_names = (args.github_token_env, args.gitlab_token_env)
    if any(_ENV_NAME.fullmatch(name) is None for name in token_env_names):
        raise GateError("provider credential environment variable name is invalid")
    if len(set(token_env_names)) != len(token_env_names):
        raise GateError("provider credential environment variables must be distinct")
    provider_tokens = {name: os.environ.get(name, "") for name in token_env_names}
    github_token = provider_tokens[args.github_token_env]
    gitlab_token = provider_tokens[args.gitlab_token_env]
    if tier == "release" and (not github_token or not gitlab_token):
        raise GateError("release tier requires both provider credential environment variables")
    if not isinstance(args.source_commit, str) or _HEX.fullmatch(args.source_commit) is None:
        raise GateError("an immutable source commit is required")

    project_root = Path(__file__).resolve().parents[1]
    with isolated_subprocess_environment(token_env_names):
        binding = build_runner_binding(project_root)
    source = _source_summary(binding, args.source_commit)
    definition = definition_digest(tier)
    suite_deadline = started + TOTAL_TIMEOUT_SECONDS
    if args.suite_deadline_epoch is not None:
        remaining_from_workflow = args.suite_deadline_epoch - time.time()
        suite_deadline = min(suite_deadline, time.monotonic() + max(0.001, remaining_from_workflow))
    results: list[dict[str, Any]] = []
    for spec in specs:
        scenario_started = time.monotonic()
        acquisition = AcquisitionContext()
        try:
            acquisition = _acquisition_context(
                partial_bundle_root,
                spec,
                secrets=tuple(provider_tokens.values()),
            )
        except (GateError, OSError, ValueError) as error:
            results.append(
                _failure_result(
                    spec,
                    "resume-preflight-failed",
                    scenario_started,
                    partial_staged=False,
                    acquisition=acquisition,
                    error=error,
                    secrets=tuple(provider_tokens.values()),
                )
            )
            continue
        if _remaining(suite_deadline) <= 0.001:
            results.append(
                _failure_result(
                    spec,
                    "suite-timeout",
                    scenario_started,
                    partial_staged=_has_private_bundle(partial_bundle_root, spec),
                    acquisition=acquisition,
                )
            )
            continue
        token_env = args.github_token_env if spec.provider == "github" else args.gitlab_token_env
        if not provider_tokens.get(token_env):
            token_env = None
        try:
            result = _run_scenario(
                spec,
                source=args.repo_root / spec.repo_dir,
                project_root=project_root,
                token_env=token_env,
                provider_tokens=provider_tokens,
                acquisition=acquisition,
                suite_deadline=suite_deadline,
                partial_bundle_root=partial_bundle_root,
            )
        except (GateError, OSError, subprocess.SubprocessError, ValueError) as error:
            result = _failure_result(
                spec,
                "scenario-execution-failed",
                scenario_started,
                partial_staged=_has_private_bundle(partial_bundle_root, spec),
                acquisition=acquisition,
                error=error,
                secrets=tuple(provider_tokens.values()),
            )
        results.append(result)

    ledger = _ledger_bytes(tier, results, definition)
    _assert_sanitized(ledger, secrets=(github_token, gitlab_token))
    _safe_write(args.ledger, ledger)
    outcomes = [str(result["outcome"]) for result in results]
    verdict = "FAIL" if "FAIL" in outcomes else ("PARTIAL" if "PARTIAL" in outcomes else "PASS")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "guard_id": GUARD_ID,
        "tier": tier,
        "verdict": verdict,
        "source": source,
        "definition_digest": definition,
        "scenario_count": len(results),
        "suite_timeout_seconds": TOTAL_TIMEOUT_SECONDS,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "ledger_sha256": _sha256(ledger),
        "results": results,
    }
    if registry_output is not None and verdict == "PASS":
        with isolated_subprocess_environment(token_env_names):
            export_public_registry(
                tier,
                results,
                source,
                registry_output,
                replace=replace_registry,
                project_root=project_root,
            )
    _assert_sanitized(
        json.dumps(summary, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        secrets=(github_token, gitlab_token),
    )
    _write_json(args.summary, summary)
    print(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "tier": tier, "verdict": verdict},
            sort_keys=True,
        )
    )
    return 1 if verdict == "FAIL" else (3 if verdict == "PARTIAL" else 0)


def verify_summary(
    summary_path: Path,
    ledger_path: Path,
    *,
    expected_tier: str,
    expected_commit: str,
    project_root: Path,
) -> None:
    summary_body = summary_path.read_bytes()
    ledger = ledger_path.read_bytes()
    _assert_sanitized(summary_body)
    _assert_sanitized(ledger)
    summary = _load_object(summary_path)
    required = {
        "schema_version",
        "guard_id",
        "tier",
        "verdict",
        "source",
        "definition_digest",
        "scenario_count",
        "suite_timeout_seconds",
        "duration_ms",
        "ledger_sha256",
        "results",
    }
    if set(summary) != required:
        raise GateError("provider live summary is not a closed object")
    if summary["schema_version"] != SCHEMA_VERSION or summary["guard_id"] != GUARD_ID:
        raise GateError("provider live summary contract does not match")
    if summary["tier"] != expected_tier or summary["verdict"] != "PASS":
        raise GateError("provider live summary is not a successful expected-tier result")
    if summary["ledger_sha256"] != _sha256(ledger):
        raise GateError("provider live ledger digest mismatch")
    if summary["definition_digest"] != definition_digest(expected_tier):
        raise GateError("provider live scenario definition is stale")
    if summary["suite_timeout_seconds"] != TOTAL_TIMEOUT_SECONDS:
        raise GateError("provider live suite timeout contract differs")
    if not isinstance(summary["duration_ms"], int) or not 0 <= summary["duration_ms"] <= 1_800_000:
        raise GateError("provider live suite exceeded the 30 minute contract")
    results = summary.get("results")
    specs = _selected(expected_tier)
    if not isinstance(results, list) or len(results) != len(specs):
        raise GateError("provider live result registry is incomplete")
    if [row.get("scenario_id") for row in results if isinstance(row, Mapping)] != [
        spec.scenario_id for spec in specs
    ]:
        raise GateError("provider live result registry order or membership differs")
    for spec, result in zip(specs, results, strict=True):
        if not isinstance(result, Mapping) or result.get("outcome") != "PASS":
            raise GateError("provider live scenario is not successful")
        expected_result_keys = {
            "scenario_id",
            "provider",
            "target_oid",
            "timeout_seconds",
            "duration_ms",
            "git_counts",
            "exit_contract",
            "command_duration_ms",
            "provider_evidence",
            "states",
            "sleep_seconds",
            "collection_mode",
            "prior_evidence_digests",
            "resumable_partial_staged",
            "mismatch_ids",
            "outcome",
        }
        if set(result) != expected_result_keys:
            raise GateError("provider live scenario is not a closed object")
        if validate_scenario_result(spec, result):
            raise GateError("provider live scenario assertions do not replay")
    current = _source_summary(build_runner_binding(project_root), expected_commit)
    if summary.get("source") != current:
        raise GateError("provider live source binding does not match publish checkout")
    if summary.get("scenario_count") != len(specs):
        raise GateError("provider live scenario count differs")
    ledger_rows = [json.loads(line) for line in ledger.splitlines() if line]
    if len(ledger_rows) != len(specs):
        raise GateError("provider live guard ledger is incomplete")
    if [row.get("scenario_id") for row in ledger_rows] != [spec.scenario_id for spec in specs]:
        raise GateError("provider live guard ledger membership differs")
    expected_ledger_keys = {
        "guard_id",
        "tier",
        "scenario_id",
        "outcome",
        "definition_digest",
        "negative_case",
        "retire_condition",
        "pair_contract",
    }
    if any(
        not isinstance(row, Mapping)
        or set(row) != expected_ledger_keys
        or row.get("guard_id") != GUARD_ID
        or row.get("tier") != expected_tier
        or row.get("outcome") != "PASS"
        or row.get("definition_digest") != summary["definition_digest"]
        or row.get("negative_case") != NEGATIVE_CASE
        or row.get("retire_condition") != RETIRE_CONDITION
        or row.get("pair_contract") != PAIR_CONTRACT
        for row in ledger_rows
    ):
        raise GateError("provider live guard ledger contract differs")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("pr", "release"))
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--github-token-env", default="V060_GITHUB_TOKEN")
    parser.add_argument("--gitlab-token-env", default="V060_GITLAB_TOKEN")
    parser.add_argument("--source-commit")
    parser.add_argument("--suite-deadline-epoch", type=int)
    parser.add_argument(
        "--partial-bundle-root",
        type=Path,
        help=(
            "Private run-local resumable CAS staging root. An explicit persistent path "
            "may be reused by a later local invocation; never include it in the public "
            "registry or sanitized artifact upload."
        ),
    )
    parser.add_argument(
        "--registry-output",
        type=Path,
        help="PR tier only: atomically export the sanitized digest-only public registry.",
    )
    parser.add_argument(
        "--replace-registry",
        action="store_true",
        help="Replace only an existing v060-public-live-gates registry.",
    )
    parser.add_argument("--verify-summary", type=Path)
    parser.add_argument("--verify-ledger", type=Path)
    parser.add_argument("--expected-tier", choices=("pr", "release"))
    parser.add_argument("--expected-source-commit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verify_summary is not None:
            if (
                args.registry_output is not None
                or args.replace_registry
                or args.partial_bundle_root is not None
            ):
                raise GateError("summary verification cannot mutate evidence storage")
            if not args.verify_ledger or not args.expected_tier or not args.expected_source_commit:
                raise GateError("summary verification requires ledger, tier, and source commit")
            verify_summary(
                args.verify_summary,
                args.verify_ledger,
                expected_tier=args.expected_tier,
                expected_commit=args.expected_source_commit,
                project_root=Path(__file__).resolve().parents[1],
            )
            print("v0.6 provider live evidence: VERIFIED")
            return 0
        if not args.tier or not args.repo_root or not args.summary or not args.ledger:
            raise GateError("generation requires tier, repo root, summary, and ledger")
        return run_gate(args)
    except (GateError, ScenarioContractError, OSError, json.JSONDecodeError) as exc:
        print(f"v0.6 provider live gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
