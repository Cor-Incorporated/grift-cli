#!/usr/bin/env python3
"""Build and install both distributions while a dirty-source sentinel exists.

The release artifact is the system under test.  This script intentionally places
files in directories that previously leaked from dirty checkouts, builds from the
working tree, inventories every member, then installs wheel and sdist independently.
It never follows or removes pre-existing paths.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

MAX_SDIST_BYTES = 5 * 1024 * 1024
FORBIDDEN_PARTS = {".worktrees", ".claude", "smoke", "grift-cli"}
FORBIDDEN_FILES = {"uv.lock"}
# Build backends necessarily synthesize a small, closed metadata surface.  All
# other distribution members must map back to a Git-tracked source path.
GENERATED_SDIST_MEMBERS = frozenset({"PKG-INFO"})
GENERATED_WHEEL_DIST_INFO_MEMBERS = frozenset(
    {
        "METADATA",
        "RECORD",
        "WHEEL",
        "entry_points.txt",
        "licenses/LICENSE",
    }
)
# Keep the canary itself out of release members: it must only exist in the
# deliberately untracked files created immediately before the build.
SENTINEL_TEXT = "GRIFT_PACKAGE_" + "DIRTY_SENTINEL_" + "DO_NOT_SHIP"
STATIC_SECRET_NEEDLES = {
    "openssh_private_key": b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
    "pkcs8_private_key": b"-----BEGIN " + b"PRIVATE KEY-----",
    "rsa_private_key": b"-----BEGIN " + b"RSA PRIVATE KEY-----",
    "ec_private_key": b"-----BEGIN " + b"EC PRIVATE KEY-----",
}
STATIC_SECRET_PATTERNS = {
    "github_token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
}
LOCAL_MACHINE_PATH_PREFIXES = {
    # Construct these needles so the scanner does not detect its own source.
    "developer_home": b"/" + b"Users" + b"/" + b"teradakousuke" + b"/",
    "macos_private_temp": (b"/" + b"private" + b"/" + b"var" + b"/" + b"folders" + b"/"),
    "macos_temp": b"/" + b"var" + b"/" + b"folders" + b"/",
}
_RELEASE_REHEARSAL_MEMBER = "docs/RELEASE-REHEARSAL-v051-20260822.md"
_RELEASE_REHEARSAL_PLACEHOLDER = b"/" + b"var" + b"/" + b"folders" + b"/.../opencode/rehearsal-v051"
REQUIRED_WHEEL_SUFFIXES = {
    "tep_cli/__main__.py",
    "tep_core/version.py",
    "tep_core/schemas/v060-contracts.schema.json",
    "tep_core/benchmark_assets/v060/sources.json",
}
REQUIRED_SDIST_SUFFIXES = {
    "pyproject.toml",
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "LICENSE",
    "src/tep_cli/__main__.py",
    "src/tep_core/version.py",
    "src/tep_core/schemas/v060-contracts.schema.json",
    "scripts/v060_golden.py",
    "benchmarks/v060/sources.json",
    "benchmarks/v060/golden/manifest.json",
    "golden/pins.toml",
    "tests/test_v060_golden_runner.py",
    "tests/test_package_contract.py",
}


class PackageContractError(RuntimeError):
    pass


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if result.returncode:
        raise PackageContractError(
            f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def _source_version(root: Path) -> str:
    """Read the one literal release version without importing source modules."""

    path = root / "src" / "tep_core" / "version.py"
    if path.is_symlink() or not path.is_file():
        raise PackageContractError("version SSOT must be a regular tracked file")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise PackageContractError("version SSOT is not valid UTF-8 Python") from exc
    values: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in targets
        ):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            raise PackageContractError("version SSOT must define a literal __version__")
        values.append(value.value)
    if len(values) != 1 or not values[0] or values[0].strip() != values[0]:
        raise PackageContractError("version SSOT must define one non-empty literal __version__")
    return values[0]


def _source_binding(
    root: Path,
) -> tuple[dict[str, object], frozenset[str], dict[str, str]]:
    """Bind a package run to one clean Git tree and its tracked path inventory."""

    repository_root = Path(_git_output(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if repository_root != root.resolve():
        raise PackageContractError(
            f"package root must be the Git toplevel: root={root.resolve()} git={repository_root}"
        )
    tracked_status = _git_output(root, "status", "--porcelain=v1", "--untracked-files=no")
    if tracked_status:
        changed = [line[3:] for line in tracked_status.splitlines() if len(line) > 3]
        raise PackageContractError(
            "tracked source must be clean before package build: " + ", ".join(changed[:10])
        )
    tracked_raw = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        capture_output=True,
        env=_git_env(),
    )
    if tracked_raw.returncode:
        raise PackageContractError(
            f"git ls-files failed ({tracked_raw.returncode}): "
            f"{tracked_raw.stderr.decode('utf-8', 'replace').strip()}"
        )
    try:
        tracked_paths = frozenset(
            item.decode("utf-8") for item in tracked_raw.stdout.split(b"\0") if item
        )
    except UnicodeDecodeError as exc:
        raise PackageContractError("tracked package paths must be UTF-8") from exc
    if not tracked_paths:
        raise PackageContractError("tracked package path inventory is empty")
    for relative in tracked_paths:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
            raise PackageContractError(f"unsafe tracked package path: {relative}")
    tracked_content_sha256: dict[str, str] = {}
    for relative in sorted(tracked_paths):
        source_path = root / relative
        if source_path.is_symlink() or not source_path.is_file():
            raise PackageContractError(f"tracked package source must be a regular file: {relative}")
        tracked_content_sha256[relative] = hashlib.sha256(source_path.read_bytes()).hexdigest()

    algorithm = _git_output(root, "rev-parse", "--show-object-format").strip()
    if algorithm not in {"sha1", "sha256"}:
        raise PackageContractError(f"unsupported Git object format: {algorithm}")
    source_version = _source_version(root)
    if "src/tep_core/version.py" not in tracked_paths:
        raise PackageContractError("version SSOT must be tracked by Git")
    binding: dict[str, object] = {
        "schema_version": "grift-package-source-binding-v1",
        "object_format": algorithm,
        "head_commit_oid": _git_output(root, "rev-parse", "HEAD").strip(),
        "head_tree_oid": _git_output(root, "rev-parse", "HEAD^{tree}").strip(),
        "source_version": source_version,
        "tracked_clean": True,
        "tracked_path_count": len(tracked_paths),
        "tracked_path_inventory_sha256": hashlib.sha256(
            json.dumps(
                sorted(tracked_paths),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "tracked_content_inventory_sha256": hashlib.sha256(
            json.dumps(
                sorted(tracked_content_sha256.items()),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "content_equality_policy": "all_non_generated_members_match_tracked_worktree_sha256",
        "generated_metadata_exceptions": {
            "sdist": sorted(GENERATED_SDIST_MEMBERS),
            "wheel_dist_info": sorted(GENERATED_WHEEL_DIST_INFO_MEMBERS),
        },
    }
    binding["binding_sha256"] = hashlib.sha256(
        json.dumps(
            binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return binding, tracked_paths, tracked_content_sha256


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise PackageContractError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _members(path: Path) -> tuple[list[tuple[str, bytes]], list[str]]:
    violations: list[str] = []
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            rows: list[tuple[str, bytes]] = []
            for info in archive.infolist():
                name = info.filename
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    violations.append(f"unsafe archive path: {name}")
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type == 0o120000:
                    violations.append(f"symlink member is forbidden: {name}")
                if not info.is_dir():
                    rows.append((name, archive.read(info)))
            return rows, violations
    with tarfile.open(path, "r:gz") as archive:
        rows: list[tuple[str, bytes]] = []
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts:
                violations.append(f"unsafe archive path: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                violations.append(f"link/device member is forbidden: {member.name}")
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            rows.append((member.name, stream.read() if stream is not None else b""))
        return rows, violations


def _has_suffix(names: set[str], suffix: str) -> bool:
    return any(name == suffix or name.endswith("/" + suffix) for name in names)


def _local_machine_path_violations(
    name: str,
    body: bytes,
    *,
    prefixes: Mapping[str, bytes] = LOCAL_MACHINE_PATH_PREFIXES,
) -> list[str]:
    """Return host-path findings while preserving one documented placeholder.

    The v0.5.1 rehearsal document contains an intentionally non-resolvable
    ``...`` example.  It is documentation, not captured machine state.  No
    other archive member receives a content exception.
    """

    scanned = body
    if name == _RELEASE_REHEARSAL_MEMBER or name.endswith("/" + _RELEASE_REHEARSAL_MEMBER):
        scanned = scanned.replace(_RELEASE_REHEARSAL_PLACEHOLDER, b"")
    findings: list[str] = []
    # Check/remove the longest prefix first so /private/var/folders is reported
    # once instead of also matching its /var/folders suffix.
    rows = sorted(prefixes.items(), key=lambda item: len(item[1]), reverse=True)
    for label, prefix in rows:
        if prefix in scanned:
            findings.append(f"local machine path prefix {label} in: {name}")
            scanned = scanned.replace(prefix, b"")
    return findings


def _assert_required_members(path: Path, rows: list[tuple[str, bytes]]) -> list[str]:
    names = {name for name, _body in rows}
    required = REQUIRED_WHEEL_SUFFIXES if path.suffix == ".whl" else REQUIRED_SDIST_SUFFIXES
    violations = [
        f"required package member missing: {suffix}"
        for suffix in sorted(required)
        if not _has_suffix(names, suffix)
    ]
    benchmark_manifest_suffix = (
        "tep_core/benchmark_assets/v060/sources.json"
        if path.suffix == ".whl"
        else "benchmarks/v060/sources.json"
    )
    manifest_rows = [
        body
        for name, body in rows
        if name == benchmark_manifest_suffix or name.endswith("/" + benchmark_manifest_suffix)
    ]
    if len(manifest_rows) != 1:
        violations.append("packaged benchmark manifest must appear exactly once")
        return violations
    try:
        benchmark_manifest = json.loads(manifest_rows[0].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        violations.append("packaged benchmark manifest is malformed")
        return violations
    registry = benchmark_manifest.get("local_artifact_sha256")
    if not isinstance(registry, dict):
        violations.append("packaged benchmark manifest has no artifact registry")
        return violations
    prefix = "tep_core/benchmark_assets/v060/" if path.suffix == ".whl" else "benchmarks/v060/"
    for relative in sorted(registry):
        if not _has_suffix(names, prefix + str(relative)):
            violations.append(f"registered benchmark member missing: {relative}")
    if path.name.endswith(".tar.gz"):
        golden_manifest_suffix = "benchmarks/v060/golden/manifest.json"
        golden_rows = [
            body
            for name, body in rows
            if name == golden_manifest_suffix or name.endswith("/" + golden_manifest_suffix)
        ]
        if len(golden_rows) != 1:
            violations.append("packaged golden manifest must appear exactly once")
            return violations
        try:
            golden_manifest = json.loads(golden_rows[0].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            violations.append("packaged golden manifest is malformed")
            return violations
        golden_registry = golden_manifest.get("registered_files")
        if not isinstance(golden_registry, dict) or not golden_registry:
            violations.append("packaged golden manifest has no file registry")
            return violations
        for relative, expected_digest in sorted(golden_registry.items()):
            suffix = f"benchmarks/v060/golden/{relative}"
            matches = [body for name, body in rows if name == suffix or name.endswith("/" + suffix)]
            if len(matches) != 1:
                violations.append(f"registered golden member missing: {relative}")
            elif hashlib.sha256(matches[0]).hexdigest() != expected_digest:
                violations.append(f"registered golden hash mismatch: {relative}")
    return violations


def _tracked_inventory_violations(
    path: Path,
    rows: list[tuple[str, bytes]],
    *,
    tracked_paths: frozenset[str],
    tracked_content_sha256: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, object]]:
    """Reject every archive member outside tracked sources and closed metadata."""

    violations: list[str] = []
    source_members: list[str] = []
    generated_members: list[str] = []
    names = [name for name, _body in rows]
    if path.name.endswith(".tar.gz"):
        top_levels = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
        expected_top_level = path.name.removesuffix(".tar.gz")
        if top_levels != {expected_top_level}:
            violations.append(
                "sdist top-level directory must exactly match its distribution filename"
            )
        for name, body in rows:
            parts = PurePosixPath(name).parts
            if len(parts) < 2:
                violations.append(f"sdist member has no source-relative path: {name}")
                continue
            relative = PurePosixPath(*parts[1:]).as_posix()
            if relative in GENERATED_SDIST_MEMBERS:
                generated_members.append(relative)
            elif relative in tracked_paths:
                source_members.append(relative)
                if tracked_content_sha256 is not None and hashlib.sha256(body).hexdigest() != (
                    tracked_content_sha256.get(relative)
                ):
                    violations.append(f"tracked package member content mismatch: {relative}")
            else:
                violations.append(f"untracked package member: {relative}")
        missing_generated = sorted(GENERATED_SDIST_MEMBERS - set(generated_members))
        unexpected_generated = sorted(set(generated_members) - GENERATED_SDIST_MEMBERS)
        duplicate_generated = sorted(
            member for member in set(generated_members) if generated_members.count(member) != 1
        )
        if missing_generated:
            violations.append(f"generated sdist metadata missing: {missing_generated}")
        if unexpected_generated:
            violations.append(f"generated sdist metadata is not allowed: {unexpected_generated}")
        if duplicate_generated:
            violations.append(f"generated sdist metadata duplicated: {duplicate_generated}")
    else:
        wheel_filename_parts = path.name.removesuffix(".whl").split("-")
        expected_dist_info = (
            f"{wheel_filename_parts[0]}-{wheel_filename_parts[1]}.dist-info"
            if len(wheel_filename_parts) >= 5
            else None
        )
        dist_info_prefixes = {
            parts[0]
            for name in names
            if (parts := PurePosixPath(name).parts) and parts[0].endswith(".dist-info")
        }
        if expected_dist_info is None or dist_info_prefixes != {expected_dist_info}:
            violations.append(
                "wheel .dist-info directory must exactly match its distribution filename"
            )
        dist_info_prefix = expected_dist_info
        for name, body in rows:
            parts = PurePosixPath(name).parts
            if not parts:
                violations.append("wheel member path is empty")
                continue
            if parts[0] in {"tep_cli", "tep_core"}:
                relative = PurePosixPath("src", *parts).as_posix()
                if relative in tracked_paths:
                    source_members.append(relative)
                    if tracked_content_sha256 is not None and hashlib.sha256(body).hexdigest() != (
                        tracked_content_sha256.get(relative)
                    ):
                        violations.append(f"tracked package member content mismatch: {relative}")
                else:
                    violations.append(f"untracked package member: {relative}")
                continue
            if dist_info_prefix is not None and parts[0] == dist_info_prefix:
                relative = PurePosixPath(*parts[1:]).as_posix()
                if relative in GENERATED_WHEEL_DIST_INFO_MEMBERS:
                    generated_members.append(relative)
                else:
                    violations.append(f"unapproved generated wheel metadata: {relative}")
                continue
            violations.append(f"untracked package member: {name}")
        missing_generated = sorted(GENERATED_WHEEL_DIST_INFO_MEMBERS - set(generated_members))
        duplicate_generated = sorted(
            member for member in set(generated_members) if generated_members.count(member) != 1
        )
        if missing_generated:
            violations.append(f"generated wheel metadata missing: {missing_generated}")
        if duplicate_generated:
            violations.append(f"generated wheel metadata duplicated: {duplicate_generated}")
        for prerequisite in ("LICENSE", "pyproject.toml"):
            if prerequisite not in tracked_paths:
                violations.append(f"generated wheel metadata source is not tracked: {prerequisite}")
    duplicate_sources = sorted(
        member for member in set(source_members) if source_members.count(member) != 1
    )
    if duplicate_sources:
        violations.append(f"tracked package members duplicated: {duplicate_sources}")
    return violations, {
        "enforced": True,
        "tracked_source_member_count": len(source_members),
        "generated_member_count": len(generated_members),
        "generated_members": sorted(generated_members),
    }


def inspect_distribution(
    path: Path,
    *,
    extra_needle: bytes | None = None,
    tracked_paths: frozenset[str] | None = None,
    tracked_content_sha256: Mapping[str, str] | None = None,
    extra_local_path_prefixes: Mapping[str, bytes] | None = None,
) -> dict[str, object]:
    rows, violations = _members(path)
    tracked_result: dict[str, object] = {"enforced": False}
    local_path_prefixes = dict(LOCAL_MACHINE_PATH_PREFIXES)
    if extra_local_path_prefixes is not None:
        local_path_prefixes.update(extra_local_path_prefixes)
    needles = [SENTINEL_TEXT.encode("utf-8")]
    if extra_needle:
        needles.append(extra_needle)
    for name, body in rows:
        pure = PurePosixPath(name)
        if FORBIDDEN_PARTS.intersection(pure.parts):
            violations.append(f"forbidden path: {name}")
        if pure.name in FORBIDDEN_FILES:
            violations.append(f"forbidden file: {name}")
        for needle in needles:
            if needle and needle in body:
                violations.append(f"forbidden needle in: {name}")
        for label, needle in STATIC_SECRET_NEEDLES.items():
            if needle in body:
                violations.append(f"secret pattern {label} in: {name}")
        for label, pattern in STATIC_SECRET_PATTERNS.items():
            if pattern.search(body):
                violations.append(f"secret pattern {label} in: {name}")
        violations.extend(_local_machine_path_violations(name, body, prefixes=local_path_prefixes))
    violations.extend(_assert_required_members(path, rows))
    if tracked_paths is not None:
        tracked_violations, tracked_result = _tracked_inventory_violations(
            path,
            rows,
            tracked_paths=tracked_paths,
            tracked_content_sha256=tracked_content_sha256,
        )
        violations.extend(tracked_violations)
    if path.name.endswith(".tar.gz") and path.stat().st_size >= MAX_SDIST_BYTES:
        violations.append(f"sdist too large: {path.stat().st_size} >= {MAX_SDIST_BYTES} bytes")
    if violations:
        raise PackageContractError("\n".join(violations))
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "member_count": len(rows),
        "members": sorted(name for name, _ in rows),
        "secret_patterns_scanned": sorted([*STATIC_SECRET_NEEDLES, *STATIC_SECRET_PATTERNS]),
        "local_machine_path_prefixes_scanned": sorted(local_path_prefixes),
        "tracked_inventory": tracked_result,
    }


def _write_ledger(path: Path, *, stage: str, status: str, detail: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "stage": stage,
        "status": status,
        "detail": detail,
        "observed_at_unix": int(time.time()),
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _dirty_sentinels(root: Path) -> tuple[list[Path], list[Path], bytes]:
    token = uuid.uuid4().hex
    secret_needle = f"GRIFT_PACKAGE_SECRET_CANARY_{token}".encode("ascii")
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    candidates = [
        root / "smoke" / f"package-sentinel-{token}.txt",
        root / ".claude" / f"package-sentinel-{token}.txt",
        root / ".worktrees" / f"package-sentinel-{token}.txt",
        root / "grift-cli" / f"package-sentinel-{token}.txt",
    ]
    try:
        if root.is_symlink() or not root.is_dir():
            raise PackageContractError("package root must be a real directory, not a symlink")
        for candidate in candidates:
            _prepare_sentinel_parent(root, candidate.parent, created_dirs)
            _write_exclusive_sentinel(
                candidate,
                SENTINEL_TEXT.encode("utf-8") + b"\n" + secret_needle,
                created_files,
            )
        lock = root / "uv.lock"
        # Existing owner paths, including dangling symlinks, are preserved.
        if not lock.exists() and not lock.is_symlink():
            _write_exclusive_sentinel(lock, SENTINEL_TEXT.encode("utf-8"), created_files)
    except BaseException:
        # Assignment in the caller has not happened yet when creation fails.
        # Clean up here as well so a partial sentinel set is never orphaned.
        _cleanup_sentinels(created_files, created_dirs)
        raise
    return created_files, created_dirs, secret_needle


def _prepare_sentinel_parent(root: Path, parent: Path, created_dirs: list[Path]) -> None:
    """Create a parent below ``root`` without following an owner symlink."""

    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise PackageContractError(f"sentinel parent escapes package root: {parent}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PackageContractError(f"sentinel parent must not be a symlink: {current}")
        if current.exists():
            if not current.is_dir():
                raise PackageContractError(f"sentinel parent must be a directory: {current}")
            continue
        current.mkdir(mode=0o700)
        created_dirs.append(current)


def _write_exclusive_sentinel(path: Path, body: bytes, created_files: list[Path]) -> None:
    """Create one canary through a checked directory descriptor and never overwrite."""

    if os.open not in os.supports_dir_fd:
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise PackageContractError(f"sentinel parent is not a real directory: {path.parent}")
        with path.open("xb") as stream:
            created_files.append(path)
            stream.write(body)
        return
    parent_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        parent_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_fd = os.open(path.parent, parent_flags)
    try:
        if not stat.S_ISDIR(os.fstat(parent_fd).st_mode):
            raise PackageContractError(f"sentinel parent is not a directory: {path.parent}")
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        file_fd = os.open(path.name, file_flags, 0o600, dir_fd=parent_fd)
        created_files.append(path)
        with os.fdopen(file_fd, "wb") as stream:
            stream.write(body)
    finally:
        os.close(parent_fd)


def _cleanup_sentinels(files: list[Path], directories: list[Path]) -> None:
    for path in files:
        if path.parent.is_symlink():
            # Never traverse a parent replaced after sentinel creation.
            continue
        path.unlink(missing_ok=True)
    for path in reversed(directories):
        try:
            path.rmdir()
        except OSError:
            pass


def _venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_script(directory: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return directory / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
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
            "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
    )
    return env


def _create_smoke_repo(workspace: Path) -> tuple[Path, Path]:
    repo = workspace / "repo"
    repo.mkdir()
    env = _runtime_env() | {
        "GIT_AUTHOR_NAME": "Package Smoke",
        "GIT_AUTHOR_EMAIL": "package-smoke@example.test",
        "GIT_AUTHOR_DATE": "2024-01-01T00:00:00Z",
        "GIT_COMMITTER_NAME": "Package Smoke",
        "GIT_COMMITTER_EMAIL": "package-smoke@example.test",
        "GIT_COMMITTER_DATE": "2024-01-01T00:00:00Z",
    }
    _run(["git", "init", "-q", "--template=", str(repo)], cwd=workspace, env=env)
    source = repo / "src" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text("def answer():\n    return 42\n", encoding="utf-8")
    test = repo / "tests" / "test_sample.py"
    test.parent.mkdir(parents=True)
    test.write_text(
        "from src.sample import answer\n\ndef test_answer():\n    assert answer() == 42\n",
        encoding="utf-8",
    )
    _run(["git", "-C", str(repo), "add", "-A"], cwd=workspace, env=env)
    _run(
        [
            "git",
            "-C",
            str(repo),
            "commit",
            "-q",
            "--no-gpg-sign",
            "--no-verify",
            "-m",
            "feat: fixture",
        ],
        cwd=workspace,
        env=env,
    )
    identity = workspace / "identity.toml"
    identity.write_text(
        'schema_version = "identity-v1"\n\n'
        '[[actors]]\ncanonical_id = "package-smoke"\n'
        'emails = ["package-smoke@example.test"]\n'
        'attribution_state = "verified"\n',
        encoding="utf-8",
    )
    return repo, identity


def _record_command(
    outputs: dict[str, str],
    key: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> str:
    output = _run(command, cwd=cwd, env=env).strip()
    outputs[key] = output[:200]
    return output


def _install_smoke(
    artifact: Path,
    *,
    root: Path,
    label: str,
    expected_version: str,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"grift-{label}-venv-") as raw_venv:
        env_dir = Path(raw_venv)
        # Create the clean venv through the interpreter CLI rather than the
        # venv.EnvBuilder API: when this script itself runs from a virtual
        # environment, EnvBuilder copies the launcher binary into the child
        # venv instead of symlinking the base interpreter.  Distribution-built
        # interpreters that rely on @executable_path-relative dyld resolution
        # then abort at load time ("Library missing", SIGABRT).  The CLI form
        # symlinks the base interpreter and is the supported invocation.
        base = Path(getattr(sys, "_base_executable", None) or sys.executable)
        _run(
            [str(base), "-m", "venv", "--clear", str(env_dir)],
            cwd=env_dir.parent,
            env=_runtime_env(),
        )
        python = _venv_python(env_dir)
        grift = _venv_script(env_dir, "grift")
        env = _runtime_env()
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(artifact),
            ],
            cwd=env_dir,
            env=env,
        )
        if not grift.is_file() or (os.name != "nt" and not os.access(grift, os.X_OK)):
            raise PackageContractError("installed distribution has no executable grift entry point")
        workspace = env_dir / "workspace"
        workspace.mkdir()
        repo, identity = _create_smoke_repo(workspace)
        help_commands = [
            ["--help"],
            ["repo", "--help"],
            ["actor", "--help"],
            ["project", "--help"],
            ["align", "--help"],
            ["analyze", "--help"],
            ["report", "--help"],
            ["verify", "--help"],
            ["contribute", "--help"],
            ["benchmark", "--help"],
            ["update", "--help"],
            ["attest", "--help"],
            ["portfolio", "--help"],
        ]
        outputs: dict[str, str] = {}
        version_output = _record_command(
            outputs,
            "--version",
            [str(grift), "--version"],
            cwd=workspace,
            env=env,
        )
        if version_output != f"grift {expected_version}":
            raise PackageContractError(
                "installed grift version mismatch: "
                f"expected=grift {expected_version!s} actual={version_output!r}"
            )
        metadata_version = _record_command(
            outputs,
            "installed metadata version",
            [
                str(python),
                "-c",
                ("import importlib.metadata as m; print(m.version('grift-cli'), end='')"),
            ],
            cwd=workspace,
            env=env,
        )
        if metadata_version != expected_version:
            raise PackageContractError(
                "installed metadata version mismatch: "
                f"expected={expected_version!r} actual={metadata_version!r}"
            )
        for args in help_commands:
            key = " ".join(args)
            _record_command(
                outputs,
                key,
                [str(grift), *args],
                cwd=workspace,
                env=env,
            )
        cli = [str(grift)]
        _record_command(
            outputs, "benchmark list", [*cli, "benchmark", "list"], cwd=workspace, env=env
        )
        _record_command(
            outputs,
            "benchmark inspect",
            [*cli, "benchmark", "inspect", "gharchive-2024-01-15-to-21-selected-repos"],
            cwd=workspace,
            env=env,
        )
        _record_command(
            outputs, "benchmark validate", [*cli, "benchmark", "validate"], cwd=workspace, env=env
        )
        tenant_out = workspace / "tenant-out"
        _record_command(
            outputs,
            "analyze minimal",
            [
                *cli,
                "analyze",
                str(repo),
                "--identity",
                str(identity),
                "--scope",
                "tenant",
                "--format",
                "json",
                "--out",
                str(tenant_out),
            ],
            cwd=workspace,
            env=env,
        )
        repo_out = workspace / "repo-out"
        _record_command(
            outputs,
            "repo minimal",
            [*cli, "repo", str(repo), "--format", "both", "--actors", "--out", str(repo_out)],
            cwd=workspace,
            env=env,
        )
        actor_out = workspace / "actor-out"
        _record_command(
            outputs,
            "actor minimal",
            [
                *cli,
                "actor",
                "--all",
                str(repo),
                "--identity",
                str(identity),
                "--format",
                "both",
                "--out",
                str(actor_out),
            ],
            cwd=workspace,
            env=env,
        )
        _record_command(
            outputs,
            "verify minimal",
            [
                *cli,
                "verify",
                str(tenant_out / "report.json"),
                "--repo",
                str(repo),
                "--identity",
                str(identity),
            ],
            cwd=workspace,
            env=env,
        )
        _record_command(
            outputs,
            "verify actor collection",
            [*cli, "verify", str(repo_out), "--repo", str(repo)],
            cwd=workspace,
            env=env,
        )
        contribution = workspace / "contribution.json"
        _record_command(
            outputs,
            "contribute minimal",
            [
                *cli,
                "contribute",
                str(repo_out / "repo-report.json"),
                "--privacy",
                "aggregate",
                "--door",
                "local",
                "--yes",
                "--out",
                str(contribution),
            ],
            cwd=workspace,
            env=env,
        )
        ssh_keygen = shutil.which("ssh-keygen")
        if ssh_keygen is None:
            raise PackageContractError("ssh-keygen is required for attest package smoke")
        key = workspace / "package-smoke-ed25519"
        _run(
            [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            cwd=workspace,
            env=env,
        )
        os.chmod(key, 0o600)
        bundle = workspace / "attestation"
        _record_command(
            outputs,
            "attest minimal",
            [
                *cli,
                "attest",
                str(tenant_out / "report.json"),
                "--repo",
                str(repo),
                "--identity",
                str(identity),
                "--out",
                str(bundle),
                "--sign",
                "ssh",
                "--ssh-key",
                str(key),
                "--principal",
                "package-smoke",
                # portfolio (079d43a) binds every report-v1 entry to a repository:
                # either the report carries repo_subject_id or the attestation
                # statement carries an opt-in repo_hint. The smoke uses the
                # attested hint so the wheel exercises that path end to end.
                "--repo-hint",
                "example.test/package-smoke/fixture",
            ],
            cwd=workspace,
            env=env,
        )
        portfolio_manifest = workspace / "portfolio.toml"
        portfolio_manifest.write_text(
            'schema_version = "tep-portfolio-manifest-v1"\n'
            'portfolio_id = "package-smoke"\nsubject_id = "package-smoke"\n'
            'subject_binding = "self_declared"\neligible_repository_count = 1\n\n'
            '[[entries]]\nentry_id = "fixture"\nsubject_id = "package-smoke"\n'
            'context = "package"\nrole = "maintainer"\n'
            'period_start = "2024-01-01"\nperiod_end = "2024-01-31"\n'
            'activity_month_count = 1\nreport = "tenant-out/report.json"\n'
            'attestation_bundle = "attestation"\n'
            'repo_hint = "example.test/package-smoke/fixture"\n',
            encoding="utf-8",
        )
        _record_command(
            outputs,
            "portfolio minimal",
            [
                *cli,
                "portfolio",
                "--manifest",
                str(portfolio_manifest),
                "--format",
                "both",
                "--out",
                str(workspace / "portfolio-out"),
            ],
            cwd=workspace,
            env=env,
        )
        required_outputs = [
            tenant_out / "report.json",
            repo_out / "repo-report.json",
            repo_out / "actor-index.json",
            actor_out / "actor-index.json",
            contribution,
            bundle / "bundle-manifest.json",
            workspace / "portfolio-out" / "portfolio.json",
            workspace / "portfolio-out" / "portfolio.md",
        ]
        missing = [
            str(path.relative_to(workspace)) for path in required_outputs if not path.is_file()
        ]
        if missing:
            raise PackageContractError(f"clean-install smoke outputs missing: {missing}")
        return {
            "artifact": artifact.name,
            "console_entrypoint": "grift",
            "installed_version": expected_version,
            "workspace_outside_checkout": not workspace.resolve().is_relative_to(root),
            "commands": outputs,
            "required_outputs": [str(path.relative_to(workspace)) for path in required_outputs],
        }


def _negative_guard_probe(
    tracked_paths: frozenset[str] | None = None,
) -> dict[str, object]:
    """Prove the guard rejects dirty, untracked, secret, and host-path members."""

    with tempfile.TemporaryDirectory(prefix="grift-package-negative-") as raw:
        archive_path = Path(raw) / "negative.tar.gz"
        body = SENTINEL_TEXT.encode("utf-8")
        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo("grift-cli-0.6.0/.worktrees/leaked/report.json")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
            local_path = b"\n".join(
                [
                    (
                        b"/"
                        + b"Users"
                        + b"/"
                        + b"teradakousuke"
                        + b"/Developer/grift-cli/private-result.json"
                    ),
                    b"/" + b"var" + b"/" + b"folders" + b"/aa/result.json",
                    (b"/" + b"private" + b"/" + b"var" + b"/" + b"folders" + b"/bb/result.json"),
                ]
            )
            local_info = tarfile.TarInfo("grift-cli-0.6.0/docs/captured-path.txt")
            local_info.size = len(local_path)
            archive.addfile(local_info, io.BytesIO(local_path))
            owner_unknown = b"OWNER_UNKNOWN = True\n"
            owner_unknown_info = tarfile.TarInfo(
                "grift-cli-0.6.0/src/tep_core/owner_unknown_probe.py"
            )
            owner_unknown_info.size = len(owner_unknown)
            archive.addfile(owner_unknown_info, io.BytesIO(owner_unknown))
        try:
            inspect_distribution(
                archive_path,
                tracked_paths=tracked_paths if tracked_paths is not None else frozenset(),
            )
        except PackageContractError as exc:
            detail = str(exc)
            required = (
                "forbidden path",
                "forbidden needle",
                "untracked package member: src/tep_core/owner_unknown_probe.py",
                "local machine path prefix developer_home",
                "local machine path prefix macos_private_temp",
                "local machine path prefix macos_temp",
            )
            if any(item not in detail for item in required):
                raise PackageContractError(
                    "negative guard did not exercise path, needle, and host-path enforcement"
                ) from exc
            return {
                "incident": (
                    "dirty worktree member, owner-unknown allowlist member, sentinel content, "
                    "and captured host path"
                ),
                "result": "blocked",
                "regression_evidence": {
                    "before_fix": "ACCEPTED member_count=371 contains_owner_unknown=True",
                    "after_fix": (
                        "REJECTED untracked package member: src/tep_core/owner_unknown_probe.py"
                    ),
                },
                "enforced": [
                    "forbidden path",
                    "forbidden needle",
                    "untracked allowlist member",
                    "local machine path prefix developer_home",
                    "local machine path prefix macos_private_temp",
                    "local machine path prefix macos_temp",
                ],
            }
        raise PackageContractError("negative guard unexpectedly accepted a dirty worktree member")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    out = (args.out or Path(tempfile.mkdtemp(prefix="grift-package-dist-"))).resolve()
    ledger = (args.ledger or out / "guard-ledger.jsonl").resolve()
    out.mkdir(parents=True, exist_ok=True)
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    try:
        source_binding, tracked_paths, tracked_content_sha256 = _source_binding(root)
        source_version = str(source_binding["source_version"])
        source_binding_path = out / "package-source-binding.json"
        source_binding_path.write_text(
            json.dumps(source_binding, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_ledger(ledger, stage="source-binding", status="passed", detail=source_binding)
        negative = _negative_guard_probe(tracked_paths)
        _write_ledger(ledger, stage="guard-negative", status="blocked", detail=negative)
        _write_ledger(
            ledger,
            stage="guard-contract",
            status="declared",
            detail={
                "declaration": "pyproject allowlists plus package inventory",
                "enforcement": "scripts/package_smoke.py inspect_distribution",
                "retirement_condition": (
                    "retire only after build backend proves tracked-only membership and "
                    "equivalent negative mutations remain required CI checks"
                ),
            },
        )
        created_files, created_dirs, secret_needle = _dirty_sentinels(root)
        _write_ledger(ledger, stage="dirty-source", status="created", detail=len(created_files))
        _run(
            [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(out)],
            cwd=root,
            env=_runtime_env(),
        )
        (
            post_build_binding,
            post_build_tracked_paths,
            post_build_tracked_content_sha256,
        ) = _source_binding(root)
        if (
            post_build_binding != source_binding
            or post_build_tracked_paths != tracked_paths
            or post_build_tracked_content_sha256 != tracked_content_sha256
        ):
            raise PackageContractError("tracked source changed while distributions were built")
        _write_ledger(
            ledger,
            stage="source-binding-recheck",
            status="passed",
            detail=post_build_binding["binding_sha256"],
        )
        artifacts = sorted([*out.glob("*.whl"), *out.glob("*.tar.gz")])
        if len(artifacts) != 2:
            raise PackageContractError(f"expected wheel+sdist, found {[p.name for p in artifacts]}")
        expected_artifacts = {
            f"grift_cli-{source_version}-py3-none-any.whl",
            f"grift_cli-{source_version}.tar.gz",
        }
        actual_artifacts = {path.name for path in artifacts}
        if actual_artifacts != expected_artifacts:
            raise PackageContractError(
                "distribution filenames are not bound to source version: "
                f"expected={sorted(expected_artifacts)} actual={sorted(actual_artifacts)}"
            )
        extra = os.environ.get("GRIFT_PACKAGE_SECRET_NEEDLE")
        inventories = [
            inspect_distribution(
                path,
                extra_needle=extra.encode() if extra else secret_needle,
                tracked_paths=tracked_paths,
                tracked_content_sha256=tracked_content_sha256,
                extra_local_path_prefixes={
                    "build_source_root": root.as_posix().encode("utf-8") + b"/",
                    "builder_home": Path.home().as_posix().encode("utf-8") + b"/",
                },
            )
            for path in artifacts
        ]
        inventory_path = out / "package-inventory.json"
        inventory_path.write_text(
            json.dumps(inventories, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _write_ledger(ledger, stage="inventory", status="passed", detail=inventories)
        installs: list[dict[str, object]] = []
        if not args.skip_install:
            for artifact in artifacts:
                installs.append(
                    _install_smoke(
                        artifact,
                        root=root,
                        label="wheel" if artifact.suffix == ".whl" else "sdist",
                        expected_version=source_version,
                    )
                )
            _write_ledger(ledger, stage="clean-install", status="passed", detail=installs)
        public_inventories = [
            {key: value for key, value in inventory.items() if key != "members"}
            for inventory in inventories
        ]
        print(
            json.dumps(
                {
                    "ok": True,
                    "artifacts": public_inventories,
                    "inventory": str(inventory_path),
                    "source_binding": source_binding,
                    "source_binding_file": str(source_binding_path),
                    "installs": installs,
                    "ledger": str(ledger),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - turn every package failure into ledger evidence
        _write_ledger(ledger, stage="package-smoke", status="failed", detail=str(exc))
        print(f"package smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _cleanup_sentinels(created_files, created_dirs)


if __name__ == "__main__":
    raise SystemExit(main())
