#!/usr/bin/env python3
"""Run the v0.6 fixed-OID repo/actor scenario matrix without mutating sources.

The runner never clones, fetches, checks out, or registers a worktree in a
Developer repository.  It creates a disposable repository whose object store
uses Git's read-only alternates mechanism, materializes the fixed commit there,
and invokes the current CLI against that isolated checkout.

Raw Forge response bodies are never copied into the evidence directory.  A
saved public-evidence bundle may be replayed, but only the CLI reports and the
sanitized collection manifest are registered as scenario artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

from tep_core.actor_artifacts import (
    ActorArtifactError,
    verify_actor_artifact_directory,
)
from tep_core.forge_public import GitObjectId, parse_forge_locator
from tep_core.schema import validate_schema
from tep_core.version import __version__

SCHEMA_MANIFEST = "tep-scenario-manifest-v1"
SCHEMA_RESULT = "tep-scenario-result-v1"
SCHEMA_PUBLIC_RESULT = "tep-public-scenario-result-v2"
SCHEMA_SUMMARY = "tep-scenario-summary-v1"
SUITE_ID = "v060-real-repositories"
DEFINITION_VERSION = "scenario-v1"
SOURCE_BINDING_DEFINITION_VERSION = "grift-tool-source-tree-v1"
PUBLIC_ACQUISITION_DEFINITION_VERSION = "provider-live-acquisition-v2"
PUBLIC_REGISTRY_SUITE_ID = "v060-public-live-gates"
PUBLIC_REGISTRY_DEFINITION_VERSION = "scenario-public-v2"
_DEFAULT_PROVIDER_TOKEN_ENVS = ("V060_GITHUB_TOKEN", "V060_GITLAB_TOKEN")
_SENSITIVE_SUBPROCESS_ENV: ContextVar[tuple[str, ...]] = ContextVar(
    "v060_sensitive_subprocess_env",
    default=(),
)
PUBLIC_PR_SCENARIO_CONTRACT: tuple[dict[str, Any], ...] = (
    {
        "id": "P01-cloudflare-full",
        "repo_dir": "cloudflare-os",
        "provider": "github",
        "target_oid": "4f42d625a994a7bff4a3091a6b06897ab2e4d79c",
        "timeout_seconds": 180,
        "max_pages": 100,
        "coverage": "complete",
        "account_linkage": "complete",
        "counts": {
            "git.total": 667,
            "git.nonmerge": 442,
            "git.merge": 225,
            "git.human": 663,
            "git.bot": 4,
            "actor.full": 18,
            "metric.human-nonmerge.numerator": 438,
            "metric.human-nonmerge.denominator": 663,
            "provider.pages": 7,
            "provider.items": 667,
            "oid.expected": 667,
            "oid.observed": 667,
            "oid.missing": 0,
            "oid.extra": 0,
            "oid.duplicates": 0,
        },
    },
    {
        "id": "P02-vite-forced-partial",
        "repo_dir": "vite",
        "provider": "github",
        "target_oid": "e2b597de0ef14598901703f5aa52f8c962007d02",
        "timeout_seconds": 600,
        "max_pages": 1,
        "coverage": "partial",
        "account_linkage": "complete",
        "counts": {
            "git.total": 9642,
            "git.nonmerge": 9572,
            "git.merge": 70,
            "git.human": 9172,
            "git.bot": 470,
            "actor.full": 1368,
            "metric.human-nonmerge.numerator": 9102,
            "metric.human-nonmerge.denominator": 9172,
            "provider.pages": 1,
            "provider.items": 100,
            "oid.expected": 9642,
            "oid.observed": 100,
            "oid.missing": 9542,
            "oid.extra": 0,
            "oid.duplicates": 0,
        },
    },
    {
        "id": "P03-gitlab-release-cli-full",
        "repo_dir": "release-cli",
        "provider": "gitlab",
        "target_oid": "07d5e21c6610f781b65d7196c5d0e86e73bcc6be",
        "timeout_seconds": 180,
        "max_pages": 100,
        "coverage": "complete",
        "account_linkage": "unsupported",
        "counts": {
            "git.total": 453,
            "git.nonmerge": 290,
            "git.merge": 163,
            "git.human": 453,
            "git.bot": 0,
            "actor.full": 47,
            "metric.human-nonmerge.numerator": 290,
            "metric.human-nonmerge.denominator": 453,
            "provider.pages": 5,
            "provider.items": 453,
            "oid.expected": 453,
            "oid.observed": 453,
            "oid.missing": 0,
            "oid.extra": 0,
            "oid.duplicates": 0,
        },
    },
)
SOURCE_BINDING_PATHS = (
    "pyproject.toml",
    "src",
    "scripts/v060_provider_live_gate.py",
    "scripts/v060_scenario_matrix.py",
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
MERGE_BASIS = (
    "repo_human_nonmerge_commits + merge_count = "
    "attribution_human_including_merges + attribution_unresolved_commit_count"
)
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_URL = re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
_RAW_PROVIDER_PARTS = frozenset({"blobs", "raw-provider", "raw_response", "responses"})
_DIGEST_ONLY_DERIVED = frozenset(
    {
        "derived/license-evidence",
        "derived/population",
        "derived/sha-to-actor",
        "derived/repo-provider-independent",
        "derived/repo-provider-independent-numeric",
        "derived/actor-provider-independent",
        "derived/actor-provider-independent-numeric",
    }
)
_DIGEST_ONLY_COLLECTION_MEMBERS = frozenset(
    {
        "actor-index.json",
        "actor-index.md",
        "collection-manifest.json",
        "repo-report.json",
        "repo-report.md",
    }
)
_PUBLIC_PAGE_DIGEST = re.compile(r"^public-evidence/page-([0-9]{2,3})\.body$")
_DIGEST_ONLY_FORBIDDEN = (
    b"/users/",
    b"/home/",
    b"/tmp/",
    b"/private/var/",
    b"file://",
    b"ssh://",
    b"git@",
    b"https://",
    b"http://",
    b"authorization:",
    b"bearer ",
    b"private-token",
    b"access_token=",
    b"ghp_",
    b"github_pat_",
    b"glpat-",
)


class ScenarioContractError(RuntimeError):
    """The runner or generated evidence violated a closed scenario contract."""


@dataclass(frozen=True)
class ExpectedCounts:
    total: int
    nonmerge: int
    merge: int
    actors: int
    human_nonmerge: int | None = None
    bots: int = 0

    @property
    def report_human_nonmerge(self) -> int:
        return self.nonmerge if self.human_nonmerge is None else self.human_nonmerge


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    tier: str
    repo_relative: str
    target_oid: str
    expected: ExpectedCounts
    timeout_seconds: int
    expected_complete: bool
    requires_public_evidence: bool = False
    # When set, the runner builds its own shallow clone of `repo_relative` at
    # `target_oid` to this depth and measures that, instead of reading the
    # working copy directly. An incomplete-history scenario cannot depend on a
    # developer checkout staying shallow: R03 previously pinned 34 commits of
    # an external repository, and silently began failing the day someone
    # unshallowed it. Cloning from a fixed OID to a fixed depth is reproducible
    # no matter how far the source repository has moved on.
    shallow_depth: int | None = None


LOCAL_SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        scenario_id="R01-benevolent-director",
        tier="local",
        repo_relative="BenevolentDirector",
        target_oid="a650ffa6b5921b93fcc32398ab01e0043ce962ec",
        expected=ExpectedCounts(total=3994, nonmerge=2607, merge=1387, actors=3),
        timeout_seconds=600,
        expected_complete=True,
    ),
    ScenarioSpec(
        scenario_id="R02-grift-landing-blueprint",
        tier="local",
        repo_relative="grift-landing-blueprint",
        target_oid="7efd09e22d06caa813149af891ae2001bebf6cb4",
        expected=ExpectedCounts(total=54, nonmerge=34, merge=20, actors=2),
        timeout_seconds=180,
        expected_complete=True,
    ),
    ScenarioSpec(
        scenario_id="R03-shallow-history",
        tier="local",
        repo_relative="grift-cli",
        target_oid="fa9bc317cc0ac1953ed09cbab11d3de2232c2fb0",
        expected=ExpectedCounts(total=33, nonmerge=20, merge=13, actors=1),
        timeout_seconds=180,
        expected_complete=False,
        shallow_depth=20,
    ),
    ScenarioSpec(
        scenario_id="R04-grift-cli-baseline",
        tier="local",
        repo_relative="grift-cli",
        target_oid="fa9bc317cc0ac1953ed09cbab11d3de2232c2fb0",
        expected=ExpectedCounts(total=164, nonmerge=110, merge=54, actors=2),
        timeout_seconds=180,
        expected_complete=True,
    ),
)

OSS_OFFLINE_SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        scenario_id="R07-voicevox",
        tier="local",
        repo_relative="oss/voicevox",
        target_oid="c72a94cbcf501be054a239446c7eb8cf53be34b4",
        expected=ExpectedCounts(total=1899, nonmerge=1810, merge=89, actors=118),
        timeout_seconds=180,
        expected_complete=True,
    ),
    ScenarioSpec(
        scenario_id="R08-kilo",
        tier="local",
        repo_relative="oss/kilo",
        target_oid="323d93b29bd89a2cb446de90c4ed4fea1764176e",
        expected=ExpectedCounts(total=20, nonmerge=16, merge=4, actors=7),
        timeout_seconds=180,
        expected_complete=True,
    ),
)

REGISTERED_OFFLINE_SCENARIOS: tuple[ScenarioSpec, ...] = (
    *LOCAL_SCENARIOS,
    *OSS_OFFLINE_SCENARIOS,
)

CLOUDFLARE_REPLAY = ScenarioSpec(
    scenario_id="R05-cloudflare-os-replay",
    tier="replay",
    repo_relative="cor-os/vendor/cloudflare-os",
    target_oid="4f42d625a994a7bff4a3091a6b06897ab2e4d79c",
    expected=ExpectedCounts(
        total=667,
        nonmerge=442,
        merge=225,
        actors=18,
        human_nonmerge=438,
        bots=4,
    ),
    timeout_seconds=180,
    expected_complete=True,
    requires_public_evidence=True,
)


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest_record(value: bytes) -> dict[str, str]:
    return {"algorithm": "sha256", "value": hashlib.sha256(value).hexdigest()}


def public_acquisition_digest(result: Mapping[str, Any]) -> dict[str, str]:
    """Bind sanitized live digests and measurements to the runner source.

    The receipt deliberately excludes mutable presentation fields such as the
    assertion list and elapsed time.  Replacing only ``runner`` on an older
    result therefore invalidates the receipt instead of relabelling old live
    evidence as an observation made by new source bytes.
    """

    payload = {
        "definition_version": PUBLIC_ACQUISITION_DEFINITION_VERSION,
        "scenario_id": result.get("scenario_id"),
        "runner": result.get("runner"),
        "target_oid": result.get("target_oid"),
        "collection_mode": result.get("collection_mode"),
        "prior_evidence_digests": result.get("prior_evidence_digests"),
        "exit_code": result.get("exit_code"),
        "counts": result.get("counts"),
        "partition_digest": result.get("partition_digest"),
        "provider_coverage": result.get("provider_coverage"),
        "output_digests": result.get("output_digests"),
    }
    return digest_record(canonical_json(payload))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _schema_name(schema_version: str) -> str:
    names = {
        SCHEMA_MANIFEST: "scenario-manifest-v1",
        SCHEMA_RESULT: "scenario-result-v1",
        SCHEMA_PUBLIC_RESULT: "scenario-result-v1",
        SCHEMA_SUMMARY: "scenario-summary-v1",
    }
    try:
        return names[schema_version]
    except KeyError as exc:
        raise ScenarioContractError(f"unknown scenario schema: {schema_version}") from exc


def _validate(value: Mapping[str, Any]) -> None:
    schema_version = str(value.get("schema_version") or "")
    errors = validate_schema(_schema_name(schema_version), dict(value))
    if errors:
        raise ScenarioContractError(f"{schema_version} validation failed: " + "; ".join(errors))


def _oid(value: str) -> dict[str, str]:
    return GitObjectId.infer(value).to_dict()


def _source_digest(entries: Sequence[tuple[str, str, bytes]]) -> dict[str, str]:
    """Hash an ordered path/mode/body inventory without ambiguous concatenation."""

    digest = hashlib.sha256()
    for relative, mode, body in sorted(entries, key=lambda row: row[0]):
        path_bytes = relative.encode("utf-8")
        mode_bytes = mode.encode("ascii")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(mode_bytes).to_bytes(2, "big"))
        digest.update(mode_bytes)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return {"algorithm": "sha256", "value": digest.hexdigest()}


def _source_inventory(project_root: Path) -> list[tuple[str, str, bytes]]:
    """Read the exact working files that implement and execute the scenario CLI."""

    raw_inventory = _git_bytes(
        project_root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *SOURCE_BINDING_PATHS,
    )
    try:
        relative_paths = sorted(
            path.decode("utf-8", errors="strict") for path in raw_inventory.split(b"\0") if path
        )
    except UnicodeDecodeError as exc:
        raise ScenarioContractError("tool source paths must be UTF-8") from exc
    if not relative_paths:
        raise ScenarioContractError("tool source inventory is empty")
    if len(relative_paths) != len(set(relative_paths)):
        raise ScenarioContractError("tool source inventory contains duplicate paths")
    inventory: list[tuple[str, str, bytes]] = []
    root = project_root.resolve()
    for relative in relative_paths:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ScenarioContractError("tool source inventory contains an unsafe path")
        path = project_root / relative
        if path.is_symlink() or not path.is_file():
            raise ScenarioContractError(f"tool source is not a regular file: {relative}")
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise ScenarioContractError(
                f"tool source escapes the project root: {relative}"
            ) from exc
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        inventory.append((pure.as_posix(), mode, path.read_bytes()))
    return inventory


def _commit_source_inventory(
    project_root: Path,
    commit_oid: str,
) -> list[tuple[str, str, bytes]]:
    """Read the bound source inventory from one immutable Git commit."""

    listing = _git_bytes(
        project_root,
        "ls-tree",
        "-r",
        "-z",
        commit_oid,
        "--",
        *SOURCE_BINDING_PATHS,
    )
    inventory: list[tuple[str, str, bytes]] = []
    for raw in (row for row in listing.split(b"\0") if row):
        try:
            metadata, raw_relative = raw.split(b"\t", 1)
            raw_mode, raw_object_type, raw_object_oid = metadata.split(b" ", 2)
            mode = raw_mode.decode("ascii", errors="strict")
            object_type = raw_object_type.decode("ascii", errors="strict")
            object_oid = raw_object_oid.decode("ascii", errors="strict")
            relative = raw_relative.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ScenarioContractError("committed tool source inventory is malformed") from exc
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ScenarioContractError(f"committed tool source is not regular: {relative}")
        body = _git_bytes(project_root, "cat-file", "blob", object_oid)
        inventory.append((PurePosixPath(relative).as_posix(), mode, body))
    if not inventory:
        raise ScenarioContractError("committed tool source inventory is empty")
    return inventory


def _git_bytes(repo: Path, *args: str, timeout: int = 120) -> bytes:
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            *args,
        ],
        env=_git_environment(),
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ScenarioContractError(message or f"git {' '.join(args)} failed")
    return result.stdout


def build_runner_binding(project_root: Path) -> dict[str, Any]:
    """Bind results to executable source bytes, plus a commit when one represents them."""

    project_root = project_root.resolve()
    inventory = _source_inventory(project_root)
    tree_digest = _source_digest(inventory)
    head = _git(project_root, "rev-parse", "HEAD").stdout.strip()
    commit_oid: dict[str, str] | None = None
    try:
        committed_inventory = _commit_source_inventory(project_root, head)
    except ScenarioContractError:
        committed_inventory = []
    if committed_inventory and _source_digest(committed_inventory) == tree_digest:
        commit_oid = _oid(head)
    return {
        "tool_version": __version__,
        "source_binding": {
            "definition_version": SOURCE_BINDING_DEFINITION_VERSION,
            "source_tree_digest": tree_digest,
            "file_count": len(inventory),
            "commit_oid": commit_oid,
        },
    }


def verify_runner_binding(
    recorded: Mapping[str, Any],
    *,
    project_root: Path,
    current: Mapping[str, Any] | None = None,
) -> None:
    """Fail when evidence was produced by different executable source bytes."""

    actual = dict(current or build_runner_binding(project_root))
    if recorded.get("tool_version") != actual.get("tool_version"):
        raise ScenarioContractError("scenario runner tool version is stale")
    recorded_source = recorded.get("source_binding")
    actual_source = actual.get("source_binding")
    if not isinstance(recorded_source, Mapping) or not isinstance(actual_source, Mapping):
        raise ScenarioContractError("scenario runner source binding is missing")
    for key in ("definition_version", "source_tree_digest", "file_count"):
        if recorded_source.get(key) != actual_source.get(key):
            raise ScenarioContractError(f"scenario runner source binding is stale: {key}")

    commit = recorded_source.get("commit_oid")
    if commit is None:
        # Once the same source bytes are represented by HEAD, checked-in evidence
        # must name that immutable commit rather than retain a pre-commit null.
        if actual_source.get("commit_oid") is not None:
            raise ScenarioContractError("scenario runner commit binding is missing")
        return
    if not isinstance(commit, Mapping):
        raise ScenarioContractError("scenario runner commit binding is malformed")
    value = commit.get("value")
    if not isinstance(value, str):
        raise ScenarioContractError("scenario runner commit binding is malformed")
    committed_inventory = _commit_source_inventory(project_root, value)
    if _source_digest(committed_inventory) != recorded_source.get("source_tree_digest"):
        raise ScenarioContractError("scenario runner commit does not contain the bound source tree")
    if len(committed_inventory) != recorded_source.get("file_count"):
        raise ScenarioContractError("scenario runner commit source file count is stale")


def build_manifest(specs: Sequence[ScenarioSpec]) -> dict[str, Any]:
    if not specs:
        raise ScenarioContractError("scenario manifest must not be empty")
    ids = [spec.scenario_id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ScenarioContractError("scenario manifest contains duplicate IDs")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_MANIFEST,
        "suite_id": SUITE_ID,
        "definition_version": DEFINITION_VERSION,
        "scenarios": [
            {
                "id": spec.scenario_id,
                "tier": spec.tier,
                "target_oid": _oid(spec.target_oid),
                "expected_artifacts": [
                    "artifacts/repo-report.json",
                    "artifacts/repo-report.md",
                    "artifacts/actor-index.json",
                    "artifacts/actor-index.md",
                    "artifacts/actors/*.json",
                    "artifacts/actors/*.md",
                    "artifacts/collection-manifest.json",
                    "scenario-result.json",
                ],
                "timeout_seconds": spec.timeout_seconds,
            }
            for spec in specs
        ],
    }
    _validate(value)
    return value


def compare(assertion_id: str, expected: Any, actual: Any) -> dict[str, Any]:
    scalar_types = (str, int, float, bool, type(None))
    if not isinstance(expected, scalar_types) or not isinstance(actual, scalar_types):
        raise ScenarioContractError("scenario assertion values must be JSON scalars")
    return {
        "id": assertion_id,
        "status": "PASS" if expected == actual else "FAIL",
        "expected": expected,
        "actual": actual,
    }


def observed(assertion_id: str, actual: Any, *, proven: bool = True) -> dict[str, Any]:
    if not isinstance(actual, (str, int, float, bool, type(None))):
        raise ScenarioContractError("scenario observation must be a JSON scalar")
    return {
        "id": assertion_id,
        "status": "PASS" if proven else "NOT_PROVEN",
        "expected": "observed",
        "actual": actual,
    }


def verdict_from_assertions(assertions: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(row.get("status")) for row in assertions}
    for verdict in ("FAIL", "SOURCE_DRIFT", "NOT_PROVEN"):
        if verdict in statuses:
            return verdict
    return "PASS"


@contextmanager
def isolated_subprocess_environment(names: Sequence[str]) -> Iterator[None]:
    """Keep named credentials out of Git and offline CLI child processes."""

    current = _SENSITIVE_SUBPROCESS_ENV.get()
    token = _SENSITIVE_SUBPROCESS_ENV.set(tuple(dict.fromkeys((*current, *names))))
    try:
        yield
    finally:
        _SENSITIVE_SUBPROCESS_ENV.reset(token)


def _git_environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    for name in {*_DEFAULT_PROVIDER_TOKEN_ENVS, *_SENSITIVE_SUBPROCESS_ENV.get()}:
        environment.pop(name, None)
    return environment


def _git(
    repo: Path,
    *args: str,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            *args,
        ],
        env=_git_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and result.returncode:
        raise ScenarioContractError(
            result.stderr.strip() or f"git {' '.join(args)} failed with {result.returncode}"
        )
    return result


def _safe_remote(source: Path) -> str | None:
    result = _git(source, "remote", "get-url", "origin", timeout=30, check=False)
    if result.returncode or not result.stdout.strip():
        return None
    try:
        locator = parse_forge_locator(result.stdout.strip())
    except ValueError:
        return None
    return f"https://{locator.sanitized_remote}.git"


def _copy_tag_refs(source: Path, target: Path) -> None:
    result = _git(
        source,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        "refs/tags",
        timeout=60,
    )
    for line in result.stdout.splitlines():
        if not line:
            continue
        try:
            refname, object_name = line.split("\x00", 1)
        except ValueError as exc:
            raise ScenarioContractError("malformed tag ref inventory") from exc
        _git(target, "update-ref", refname, object_name, timeout=30)


def _copy_completeness_state(source: Path, target: Path) -> None:
    common = Path(
        _git(source, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    )
    shallow = common / "shallow"
    if shallow.is_file():
        target_git = Path(
            _git(target, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip()
        )
        (target_git / "shallow").write_bytes(shallow.read_bytes())
    partial = _git(source, "config", "--get", "extensions.partialClone", check=False)
    promisor = _git(
        source,
        "config",
        "--get-regexp",
        r"^remote\..*\.promisor$",
        check=False,
    )
    if partial.returncode == 0 and partial.stdout.strip():
        _git(target, "config", "extensions.partialClone", partial.stdout.strip())
    if any(line.strip().lower().endswith(" true") for line in promisor.stdout.splitlines()):
        _git(target, "config", "remote.origin.promisor", "true")


@contextmanager
def materialize_read_only_repo(source: Path, target_oid: str) -> Iterator[Path]:
    """Materialize ``target_oid`` without writing to or registering in ``source``."""

    source = source.resolve()
    if not source.is_dir():
        raise ScenarioContractError(f"source repository is unavailable: {source.name}")
    exists = _git(source, "cat-file", "-e", f"{target_oid}^{{commit}}", check=False)
    if exists.returncode:
        raise ScenarioContractError("fixed target OID is not present in the local object store")
    object_format = _git(source, "rev-parse", "--show-object-format").stdout.strip()
    if object_format not in {"sha1", "sha256"}:
        raise ScenarioContractError(f"unsupported Git object format: {object_format}")
    common = Path(
        _git(source, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    )
    object_directory = (common / "objects").resolve()
    if "\n" in str(object_directory) or not object_directory.is_dir():
        raise ScenarioContractError("source object directory is unsafe or unavailable")

    with tempfile.TemporaryDirectory(prefix="grift-v060-readonly-") as temporary:
        materialized = Path(temporary) / source.name
        init = ["git", "init", "-q", "--template="]
        if object_format == "sha256":
            init.append("--object-format=sha256")
        init.append(str(materialized))
        subprocess.run(
            init,
            env=_git_environment(),
            capture_output=True,
            text=True,
            check=True,
        )
        git_dir = Path(
            _git(
                materialized,
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
            ).stdout.strip()
        )
        alternates = git_dir / "objects" / "info" / "alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(str(object_directory) + "\n", encoding="utf-8")
        _git(materialized, "update-ref", "refs/heads/grift-scenario", target_oid)
        _git(materialized, "symbolic-ref", "HEAD", "refs/heads/grift-scenario")
        safe_remote = _safe_remote(source)
        if safe_remote is not None:
            _git(materialized, "remote", "add", "origin", safe_remote)
        _copy_tag_refs(source, materialized)
        _git(materialized, "reset", "--hard", target_oid, timeout=300)
        _copy_completeness_state(source, materialized)
        yield materialized


def _source_complete(repo: Path) -> bool:
    shallow = _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    promisor = _git(
        repo,
        "config",
        "--get-regexp",
        r"^remote\..*\.promisor$",
        check=False,
    )
    is_promisor = any(
        line.strip().lower().endswith(" true") for line in promisor.stdout.splitlines()
    )
    return not shallow and not is_promisor


def _git_count(repo: Path, target_oid: str, *filters: str) -> int:
    value = _git(repo, "rev-list", "--count", *filters, target_oid, timeout=300).stdout.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise ScenarioContractError("git rev-list did not return an integer count") from exc


def _expected_window(repo: Path, target_oid: str) -> dict[str, Any]:
    raw = _git(repo, "show", "-s", "--format=%as", target_oid).stdout.strip()
    try:
        end = date.fromisoformat(raw)
    except ValueError as exc:
        raise ScenarioContractError("fixed target author date is not ISO YYYY-MM-DD") from exc
    return {"start": (end - timedelta(days=180)).isoformat(), "end": raw, "days": 180}


def _provider_coverage(
    public_bundle: Path | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Project a sanitized bundle status without copying any response body."""

    if public_bundle is None:
        return {
            "kind": "not_observed",
            "provided": False,
            "reason": "public_evidence_not_provided",
        }, {}
    try:
        manifest = json.loads((public_bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "kind": "not_proven",
            "provided": True,
            "reason": "public_evidence_manifest_invalid",
        }, {}
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    if not isinstance(coverage, Mapping):
        return {
            "kind": "not_proven",
            "provided": True,
            "reason": "public_evidence_coverage_missing",
        }, {}
    counts: dict[str, int] = {}
    item_count = coverage.get("item_count")
    if isinstance(item_count, int) and not isinstance(item_count, bool) and item_count >= 0:
        counts["provider.item_count"] = item_count
    pages = manifest.get("pages")
    if isinstance(pages, list):
        counts["provider.pages"] = len(pages)
    status = str(coverage.get("status") or "unavailable")
    if status == "complete":
        return {"kind": "observed", "provided": True}, counts
    reason = re.sub(r"[^a-z0-9_.-]+", "_", status.casefold()).strip("_")
    return {
        "kind": "not_proven",
        "provided": True,
        "reason": f"public_evidence_{reason or 'unavailable'}",
    }, counts


def report_metrics(
    report: Mapping[str, Any],
    actor_index: Mapping[str, Any],
) -> dict[str, Any]:
    provenance = report.get("provenance")
    attribution = report.get("attribution")
    population = report.get("population")
    window = report.get("window")
    index_population = actor_index.get("population")
    selection = actor_index.get("selection")
    if not all(
        isinstance(value, Mapping)
        for value in (
            provenance,
            attribution,
            population,
            window,
            index_population,
            selection,
        )
    ):
        raise ScenarioContractError(
            "strict actor collection lacks provenance/attribution/population/window/index"
        )
    assert isinstance(provenance, Mapping)
    assert isinstance(attribution, Mapping)
    assert isinstance(population, Mapping)
    assert isinstance(window, Mapping)
    assert isinstance(index_population, Mapping)
    assert isinstance(selection, Mapping)
    partition = attribution.get("actor_partition")
    if not isinstance(partition, Mapping):
        raise ScenarioContractError("report lacks actor partition metadata")
    partition_digest = str(partition.get("partition_digest") or "")
    if _HEX_64.fullmatch(partition_digest) is None:
        raise ScenarioContractError("report partition digest is missing or malformed")
    for label, value in (
        ("population", population.get("partition_digest")),
        ("actor index", actor_index.get("partition_digest")),
    ):
        if not isinstance(value, Mapping) or value.get("value") != partition_digest:
            raise ScenarioContractError(f"{label} partition digest is inconsistent")

    def integer(node: Mapping[str, Any], key: str) -> int:
        value = node.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ScenarioContractError(f"report metric {key} is not a non-negative integer")
        return value

    counts = {
        "report.human_nonmerge": integer(attribution, "repo_human_nonmerge_commits"),
        "report.attributed_including_merges": integer(
            attribution, "attribution_human_including_merges"
        ),
        "report.unresolved": integer(attribution, "attribution_unresolved_commit_count"),
        "report.bot": integer(attribution, "bot_count"),
        "report.merge": integer(attribution, "merge_count"),
        "population.human": integer(population, "human_commit_count"),
        "population.nonmerge": integer(population, "nonmerge_commit_count"),
        "population.merge": integer(population, "merge_commit_count"),
        "actors.full": integer(population, "actor_count"),
        "actors.selected": integer(selection, "selected_count"),
    }
    metric_map = report.get("metrics")
    human_share = (
        metric_map.get("human_nonmerge_commit_share") if isinstance(metric_map, Mapping) else None
    )
    if not isinstance(human_share, Mapping):
        raise ScenarioContractError("report human nonmerge metric is missing")
    counts["metric.human_nonmerge.numerator"] = integer(human_share, "numerator")
    counts["metric.human_nonmerge.denominator"] = integer(human_share, "denominator")
    start = str(window.get("start") or "")
    end = str(window.get("end") or "")
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError as exc:
        raise ScenarioContractError("report window dates are invalid") from exc
    target = report.get("target")
    target_oid = target.get("oid") if isinstance(target, Mapping) else None
    return {
        "counts": counts,
        "partition_digest": partition_digest,
        "window": {
            "start": start,
            "end": end,
            "days": days,
            "unit": str(window.get("unit") or ""),
            "basis": str(window.get("basis") or ""),
        },
        "merge_basis": str(attribution.get("population_identity") or ""),
        "target_oid": target_oid,
        "revision_complete": bool(
            (provenance.get("revision_completeness") or {}).get("complete")
            if isinstance(provenance.get("revision_completeness"), Mapping)
            else False
        ),
    }


def artifact_digests(
    root: Path,
    *,
    forbidden_needles: Sequence[str],
) -> dict[str, dict[str, str]]:
    """Inventory safe report artifacts; refuse raw bodies, links, and local paths."""

    result: dict[str, dict[str, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ScenarioContractError(f"scenario artifact is a symlink: {relative.as_posix()}")
        if not path.is_file():
            continue
        if _RAW_PROVIDER_PARTS.intersection(relative.parts):
            raise ScenarioContractError(
                "raw provider body directory cannot enter scenario evidence"
            )
        if path.suffix.casefold() not in {".json", ".md"}:
            raise ScenarioContractError(
                f"unregistered scenario artifact type: {relative.as_posix()}"
            )
        body = path.read_bytes()
        for needle in forbidden_needles:
            if needle and needle.encode("utf-8") in body:
                raise ScenarioContractError(
                    f"scenario artifact leaks a local path: {relative.as_posix()}"
                )
        text = body.decode("utf-8", errors="replace")
        if _CREDENTIAL_URL.search(text):
            raise ScenarioContractError(
                f"scenario artifact contains URL userinfo: {relative.as_posix()}"
            )
        result[relative.as_posix()] = digest_record(body)
    return result


def build_shallow_fixture(source: Path, spec: ScenarioSpec, destination: Path) -> Path:
    """Clone `spec.target_oid` to `spec.shallow_depth` and return the new repo.

    Reproducible because both the OID and the depth are pinned: the graft
    boundary is a fixed function of the two, so the fixture is identical no
    matter how many commits the source has gained since. Nothing is written to
    the source repository.
    """
    if spec.shallow_depth is None:
        raise ScenarioContractError(f"{spec.scenario_id} has no shallow_depth to build")
    destination.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}

    def git(*args: str) -> None:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(destination), *args],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise ScenarioContractError(
                f"{spec.scenario_id} fixture: git {args[0]} failed: "
                f"{result.stderr.strip()[:200]}"
            )

    git("init", "-q")
    git("fetch", "-q", "--depth", str(spec.shallow_depth), f"file://{source}", spec.target_oid)
    git("checkout", "-q", "--detach", "FETCH_HEAD")
    shallow = destination / ".git" / "shallow"
    if not shallow.is_file():
        raise ScenarioContractError(
            f"{spec.scenario_id} fixture is not shallow; the scenario would test nothing"
        )
    return destination


# Fields whose value describes the whole repository and therefore cannot be
# measured from a truncated clone. Kept here, beside the assertion that uses
# them, so a reader sees what "incomplete history" is required to suppress.
DEPTH_DEPENDENT_REPORT_FIELDS = (
    "context_profile.repo_age_days",
    "context_profile.resolved_human_actors",
    "context_profile.lifecycle_stage",
    "context_profile.actor_turnover",
    "context_profile.scale.first_commit",
    "context_profile.scale.human_commits",
    "activity.repo_human_nonmerge_commits",
    "activity.repo_active_days",
)


def _degraded_kinds(report: Mapping[str, Any]) -> dict[str, str]:
    """Read the `kind` of each depth-dependent field, or say it was missing."""
    kinds: dict[str, str] = {}
    for path in DEPTH_DEPENDENT_REPORT_FIELDS:
        node: Any = report
        for key in path.split("."):
            node = node.get(key) if isinstance(node, Mapping) else None
        kinds[path] = node.get("kind") if isinstance(node, Mapping) else "<missing>"
    return kinds


def _plain_repo_argv(project_root: Path, source: Path, spec: ScenarioSpec) -> list[str]:
    """The default repo report, which is where the depth-dependent fields live."""
    return [
        sys.executable,
        "-m",
        "tep_cli",
        "repo",
        str(source),
        "--rev",
        spec.target_oid,
        "--format",
        "json",
    ]


def recorded_repo_argv(spec: ScenarioSpec, *, public_evidence: bool) -> list[str]:
    argv = [
        "python",
        "-m",
        "tep_cli",
        "repo",
        f"${{DEVELOPER_ROOT}}/{spec.repo_relative}",
        "--rev",
        spec.target_oid,
        "--actors",
        "--format",
        "both",
        "--out",
        f"${{OUTPUT_ROOT}}/{spec.scenario_id}/artifacts",
    ]
    if public_evidence:
        argv.extend(["--public-evidence", "${PUBLIC_EVIDENCE_BUNDLE}"])
    return argv


def _actual_repo_argv(
    project_root: Path,
    repo: Path,
    spec: ScenarioSpec,
    artifact_root: Path,
    public_bundle: Path | None,
) -> list[str]:
    del project_root
    argv = [
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
        str(artifact_root),
    ]
    if public_bundle is not None:
        argv.extend(["--public-evidence", str(public_bundle)])
    return argv


def _cli_environment(project_root: Path) -> dict[str, str]:
    pythonpath = str(project_root / "src")
    existing = os.environ.get("PYTHONPATH")
    if existing:
        pythonpath += os.pathsep + existing
    return {
        **_git_environment(),
        "PYTHONPATH": pythonpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }


def _execute(
    argv: Sequence[str],
    *,
    project_root: Path,
    timeout_seconds: float,
) -> CommandResult:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(argv),
            cwd=project_root,
            env=_cli_environment(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.001, timeout_seconds),
        )
        return CommandResult(
            argv=tuple(argv),
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return CommandResult(
            argv=tuple(argv),
            exit_code=124,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round((time.monotonic() - started) * 1000),
        )


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return 0.001
    return remaining


def _verify_argv(
    artifact_directory: Path,
    repo: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tep_cli",
        "verify",
        str(artifact_directory),
        "--repo",
        str(repo),
    ]


def _unavailable_result(
    spec: ScenarioSpec,
    *,
    started: float,
    assertion_id: str,
    actual: str,
    runner: Mapping[str, Any],
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_RESULT,
        "scenario_id": spec.scenario_id,
        "runner": dict(runner),
        "target_oid": _oid(spec.target_oid),
        "argv": recorded_repo_argv(spec, public_evidence=spec.requires_public_evidence),
        "exit_code": 2,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "counts": {},
        "partition_digest": {"algorithm": "sha256", "value": EMPTY_SHA256},
        "provider_coverage": {
            "kind": "not_proven",
            "provided": False,
            "reason": "scenario_input_unavailable",
        },
        "output_digests": {},
        "assertions": [
            {
                "id": assertion_id,
                "status": "NOT_PROVEN",
                "expected": "available",
                "actual": actual,
            }
        ],
        "verdict": "NOT_PROVEN",
    }
    _validate(value)
    return value


def run_scenario(
    spec: ScenarioSpec,
    *,
    source: Path,
    project_root: Path,
    scenario_root: Path,
    public_bundle: Path | None = None,
    runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + spec.timeout_seconds
    runner_binding = dict(runner or build_runner_binding(project_root))
    if spec.requires_public_evidence and public_bundle is None:
        return _unavailable_result(
            spec,
            started=started,
            assertion_id="public-evidence-bundle",
            actual="not_found",
            runner=runner_binding,
        )
    if public_bundle is not None and not (public_bundle / "manifest.json").is_file():
        return _unavailable_result(
            spec,
            started=started,
            assertion_id="public-evidence-bundle",
            actual="manifest_missing",
            runner=runner_binding,
        )
    if not source.is_dir():
        return _unavailable_result(
            spec,
            started=started,
            assertion_id="source-repository",
            actual="not_found",
            runner=runner_binding,
        )
    target_check = _git(source, "cat-file", "-e", f"{spec.target_oid}^{{commit}}", check=False)
    if target_check.returncode:
        return _unavailable_result(
            spec,
            started=started,
            assertion_id="fixed-target",
            actual="object_missing",
            runner=runner_binding,
        )

    git_total = _git_count(source, spec.target_oid)
    git_nonmerge = _git_count(source, spec.target_oid, "--no-merges")
    git_merge = _git_count(source, spec.target_oid, "--merges")
    expected_window = _expected_window(source, spec.target_oid)
    source_complete = _source_complete(source)
    assertions: list[dict[str, Any]] = [
        compare("git-total", spec.expected.total, git_total),
        compare("git-nonmerge", spec.expected.nonmerge, git_nonmerge),
        compare("git-merge", spec.expected.merge, git_merge),
        compare("git-total-arithmetic", git_total, git_nonmerge + git_merge),
        compare("revision-completeness", spec.expected_complete, source_complete),
    ]
    counts: dict[str, int] = {
        "git.total": git_total,
        "git.nonmerge": git_nonmerge,
        "git.merge": git_merge,
    }
    exit_codes: list[int] = []
    provider_coverage, provider_counts = _provider_coverage(public_bundle)
    counts.update(provider_counts)
    partition_digest = EMPTY_SHA256

    if scenario_root.exists():
        raise ScenarioContractError(
            "scenario destination must not exist before atomic scenario publication"
        )
    scenario_root.mkdir(parents=True)
    artifact_root = scenario_root / "artifacts"
    with materialize_read_only_repo(source, spec.target_oid) as materialized:
        repo_command = _execute(
            _actual_repo_argv(
                project_root,
                materialized,
                spec,
                artifact_root,
                public_bundle,
            ),
            project_root=project_root,
            timeout_seconds=_remaining(deadline),
        )
        exit_codes.append(repo_command.exit_code)
        assertions.append(compare("repo-command-exit", 0, repo_command.exit_code))
        report_path = artifact_root / "repo-report.json"
        markdown_path = artifact_root / "repo-report.md"
        index_path = artifact_root / "actor-index.json"
        index_markdown_path = artifact_root / "actor-index.md"
        collection_manifest = artifact_root / "collection-manifest.json"
        assertions.append(compare("repo-json-generated", True, report_path.is_file()))
        assertions.append(compare("repo-markdown-generated", True, markdown_path.is_file()))
        assertions.append(compare("actor-index-json-generated", True, index_path.is_file()))
        assertions.append(
            compare("actor-index-markdown-generated", True, index_markdown_path.is_file())
        )
        assertions.append(
            compare("collection-manifest-generated", True, collection_manifest.is_file())
        )

        report: dict[str, Any] | None = None
        actor_index: dict[str, Any] | None = None
        metrics: dict[str, Any] | None = None
        if report_path.is_file() and index_path.is_file():
            try:
                loaded = json.loads(report_path.read_text(encoding="utf-8"))
                loaded_index = json.loads(index_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("report root is not an object")
                if not isinstance(loaded_index, dict):
                    raise ValueError("actor index root is not an object")
                report = loaded
                actor_index = loaded_index
                metrics = report_metrics(report, actor_index)
            except (OSError, ValueError, json.JSONDecodeError, ScenarioContractError):
                assertions.append(compare("collection-json-parse", "valid", "invalid"))
            else:
                assertions.append(compare("collection-json-parse", "valid", "valid"))

        if collection_manifest.is_file():
            try:
                verified = verify_actor_artifact_directory(artifact_root)
            except ActorArtifactError:
                assertions.append(compare("verify-collection-core", "VERIFIED", "MISMATCH"))
            else:
                counts["collection.members"] = verified.member_count
                counts["actors.full"] = verified.full_actor_count
                counts["actors.selected"] = verified.selected_actor_count
                assertions.append(compare("verify-collection-core", "VERIFIED", "VERIFIED"))

        if metrics is not None and report is not None and actor_index is not None:
            counts.update(metrics["counts"])
            partition_digest = str(metrics["partition_digest"])
            report_provenance = report.get("provenance")
            report_tool_version = (
                report_provenance.get("tool_version")
                if isinstance(report_provenance, Mapping)
                else None
            )
            assertions.extend(
                [
                    compare(
                        "runner-tool-version",
                        runner_binding["tool_version"],
                        report_tool_version,
                    ),
                    compare(
                        "target-oid", spec.target_oid, (metrics["target_oid"] or {}).get("value")
                    ),
                    compare(
                        "report-human-nonmerge",
                        spec.expected.report_human_nonmerge,
                        counts["report.human_nonmerge"],
                    ),
                    compare("report-merge", spec.expected.merge, counts["report.merge"]),
                    compare("report-bot", spec.expected.bots, counts["report.bot"]),
                    compare("actor-count", spec.expected.actors, counts["actors.full"]),
                    compare("merge-basis", MERGE_BASIS, metrics["merge_basis"]),
                    compare("window-start", expected_window["start"], metrics["window"]["start"]),
                    compare("window-end", expected_window["end"], metrics["window"]["end"]),
                    compare("window-days", expected_window["days"], metrics["window"]["days"]),
                    compare("window-unit", "date-range", metrics["window"]["unit"]),
                    compare("window-basis", "legacy_head_date", metrics["window"]["basis"]),
                    compare(
                        "metric-numerator",
                        spec.expected.report_human_nonmerge,
                        counts["metric.human_nonmerge.numerator"],
                    ),
                    compare(
                        "metric-denominator",
                        spec.expected.total - spec.expected.bots,
                        counts["metric.human_nonmerge.denominator"],
                    ),
                    compare(
                        "report-revision-completeness",
                        spec.expected_complete,
                        metrics["revision_complete"],
                    ),
                ]
            )
        if not spec.expected_complete:
            # Asserting the flag alone is what let the defect through: R03
            # checked `complete is False` for the whole of v0.6.0 while the
            # repo report went on to publish repo_age_days, first_commit and
            # resolved_human_actors as `observed` values measured from the
            # truncated slice. The flag and the values must agree.
            #
            # The collection artifacts above carry population counts, not
            # repository-wide claims, so this runs the plain repo report --
            # the document those fields actually live in -- against the same
            # fixture and checks each one degraded.
            plain = _execute(
                _plain_repo_argv(project_root, source, spec),
                project_root=project_root,
                timeout_seconds=spec.timeout_seconds,
            )
            assertions.append(compare("degrade-report-exit", 0, plain.exit_code))
            try:
                plain_report = json.loads(plain.stdout)
                if not isinstance(plain_report, Mapping):
                    raise ValueError("repo report root is not an object")
            except (ValueError, json.JSONDecodeError):
                assertions.append(compare("degrade-report-parse", "valid", "invalid"))
            else:
                assertions.append(compare("degrade-report-parse", "valid", "valid"))
                assertions.extend(
                    compare(f"degrade-{name.replace('.', '-')}", "not_observed", kind)
                    for name, kind in _degraded_kinds(plain_report).items()
                )
            repo_verify = _execute(
                _verify_argv(
                    artifact_root,
                    materialized,
                ),
                project_root=project_root,
                timeout_seconds=_remaining(deadline),
            )
            exit_codes.append(repo_verify.exit_code)
            counts["verify.collection_cli_pass"] = int(repo_verify.exit_code == 0)
            assertions.append(compare("verify-collection-cli", 0, repo_verify.exit_code))
            selected = metrics["counts"]["actors.selected"]
            json_cards = list((artifact_root / "actors").glob("*.json"))
            markdown_cards = list((artifact_root / "actors").glob("*.md"))
            counts["actor_cards.json"] = len(json_cards)
            counts["actor_cards.markdown"] = len(markdown_cards)
            assertions.append(compare("actor-json-card-count", selected, len(json_cards)))
            assertions.append(compare("actor-markdown-card-count", selected, len(markdown_cards)))

    try:
        output_digests = artifact_digests(
            scenario_root,
            forbidden_needles=(str(source.resolve()),),
        )
    except ScenarioContractError:
        output_digests = {}
        assertions.append(compare("artifact-safety", "safe", "unsafe"))
    else:
        assertions.append(compare("artifact-safety", "safe", "safe"))

    verdict = verdict_from_assertions(assertions)
    first_nonzero = next((code for code in exit_codes if code != 0), 0)
    value = {
        "schema_version": SCHEMA_RESULT,
        "scenario_id": spec.scenario_id,
        "runner": runner_binding,
        "target_oid": _oid(spec.target_oid),
        "argv": recorded_repo_argv(spec, public_evidence=public_bundle is not None),
        "exit_code": first_nonzero,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "counts": counts,
        "partition_digest": {"algorithm": "sha256", "value": partition_digest},
        "provider_coverage": provider_coverage,
        "output_digests": output_digests,
        "assertions": assertions,
        "verdict": verdict,
    }
    _validate(value)
    return value


def build_summary(manifest_path: Path, result_paths: Sequence[Path]) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioContractError(f"scenario manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ScenarioContractError("scenario manifest root must be an object")
    _validate(manifest)
    expected_ids = [str(row["id"]) for row in manifest["scenarios"]]
    if len(expected_ids) != len(set(expected_ids)):
        raise ScenarioContractError("scenario manifest contains duplicate IDs")
    results: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in result_paths:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenarioContractError(f"scenario result is unreadable: {path.name}") from exc
        if not isinstance(result, dict):
            raise ScenarioContractError("scenario result root must be an object")
        _validate(result)
        scenario_id = str(result.get("scenario_id") or "")
        if scenario_id in results:
            raise ScenarioContractError(f"duplicate scenario result: {scenario_id}")
        results[scenario_id] = (result, path)
    missing = sorted(set(expected_ids) - set(results))
    extra = sorted(set(results) - set(expected_ids))
    if missing:
        raise ScenarioContractError("missing result for: " + ", ".join(missing))
    if extra:
        raise ScenarioContractError("unregistered result for: " + ", ".join(extra))

    verdicts = [str(results[scenario_id][0]["verdict"]) for scenario_id in expected_ids]
    result_digests = [
        digest_record(results[scenario_id][1].read_bytes()) for scenario_id in expected_ids
    ]
    digest_values = [row["value"] for row in result_digests]
    if len(digest_values) != len(set(digest_values)):
        raise ScenarioContractError("duplicate scenario result digest")
    counts = {
        "total": len(verdicts),
        "pass": verdicts.count("PASS"),
        "fail": verdicts.count("FAIL"),
        "not_proven": verdicts.count("NOT_PROVEN"),
        "source_drift": verdicts.count("SOURCE_DRIFT"),
    }
    summary_assertions = [
        {"status": verdict, "id": scenario_id}
        for scenario_id, verdict in zip(expected_ids, verdicts, strict=True)
    ]
    value: dict[str, Any] = {
        "schema_version": SCHEMA_SUMMARY,
        "suite_id": str(manifest["suite_id"]),
        "manifest_digest": digest_record(manifest_path.read_bytes()),
        "result_digests": result_digests,
        "counts": counts,
        "verdict": verdict_from_assertions(summary_assertions),
    }
    _validate(value)
    return value


def verify_evidence_registry(
    root: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Verify registry closure and bind it to the current executable source tree."""

    root = root.resolve()
    source_root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    current_runner = build_runner_binding(source_root)
    manifest_path = root / "manifest.json"
    summary_path = root / "summary.json"
    if manifest_path.is_symlink() or summary_path.is_symlink():
        raise ScenarioContractError("scenario registry files must not be symlinks")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioContractError(f"scenario registry is unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(recorded_summary, dict):
        raise ScenarioContractError("scenario registry roots must be objects")
    _validate(manifest)
    _validate(recorded_summary)

    scenario_rows = manifest["scenarios"]
    scenario_ids = [str(row["id"]) for row in scenario_rows]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ScenarioContractError("scenario manifest contains duplicate IDs")
    registered_root_entries = {"manifest.json", "summary.json", *scenario_ids}
    actual_root_entries = {path.name for path in root.iterdir()}
    if actual_root_entries != registered_root_entries:
        missing = sorted(registered_root_entries - actual_root_entries)
        extra = sorted(actual_root_entries - registered_root_entries)
        raise ScenarioContractError(
            f"scenario root registry mismatch: missing={missing}, unregistered={extra}"
        )

    result_paths: list[Path] = []
    for row in scenario_rows:
        scenario_id = str(row["id"])
        scenario_root = root / scenario_id
        if scenario_root.is_symlink() or not scenario_root.is_dir():
            raise ScenarioContractError(f"scenario directory is unsafe: {scenario_id}")
        result_path = scenario_root / "scenario-result.json"
        if result_path.is_symlink():
            raise ScenarioContractError(f"scenario result is a symlink: {scenario_id}")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenarioContractError(
                f"scenario result is unreadable: {scenario_id}: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise ScenarioContractError(f"scenario result root is not an object: {scenario_id}")
        _validate(result)
        if result.get("scenario_id") != scenario_id:
            raise ScenarioContractError(f"scenario result ID mismatch: {scenario_id}")
        if result.get("target_oid") != row.get("target_oid"):
            raise ScenarioContractError(f"scenario target OID mismatch: {scenario_id}")
        verify_runner_binding(
            result.get("runner") if isinstance(result.get("runner"), Mapping) else {},
            project_root=source_root,
            current=current_runner,
        )
        assertion_ids = [str(assertion["id"]) for assertion in result["assertions"]]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ScenarioContractError(f"duplicate assertion ID: {scenario_id}")
        if result.get("verdict") == "PASS":
            version_assertions = [
                assertion
                for assertion in result["assertions"]
                if assertion.get("id") == "runner-tool-version"
            ]
            tool_version = result["runner"]["tool_version"]
            if len(version_assertions) != 1 or version_assertions[0] != {
                "id": "runner-tool-version",
                "status": "PASS",
                "expected": tool_version,
                "actual": tool_version,
            }:
                raise ScenarioContractError(
                    f"scenario runner tool version is not proven by output: {scenario_id}"
                )
        if result.get("verdict") != verdict_from_assertions(result["assertions"]):
            raise ScenarioContractError(
                f"scenario verdict does not match assertions: {scenario_id}"
            )

        files: dict[str, Path] = {}
        for path in sorted(scenario_root.rglob("*")):
            relative = path.relative_to(scenario_root).as_posix()
            if path.is_symlink():
                raise ScenarioContractError(
                    f"scenario artifact is a symlink: {scenario_id}/{relative}"
                )
            if path.is_file():
                if _RAW_PROVIDER_PARTS.intersection(PurePosixPath(relative).parts):
                    raise ScenarioContractError(
                        f"raw provider body entered scenario registry: {scenario_id}/{relative}"
                    )
                body = path.read_bytes()
                if any(needle in body for needle in (b"/Users/", b"/tmp/", b"/private/var/")):
                    raise ScenarioContractError(
                        f"scenario registry contains an absolute local path: "
                        f"{scenario_id}/{relative}"
                    )
                if _CREDENTIAL_URL.search(body.decode("utf-8", errors="replace")):
                    raise ScenarioContractError(
                        f"scenario registry contains URL userinfo: {scenario_id}/{relative}"
                    )
                files[relative] = path
        actual_artifacts = set(files) - {"scenario-result.json"}
        recorded_artifacts = set(result["output_digests"])
        if actual_artifacts != recorded_artifacts:
            missing = sorted(recorded_artifacts - actual_artifacts)
            extra = sorted(actual_artifacts - recorded_artifacts)
            raise ScenarioContractError(
                f"scenario artifact registry mismatch: {scenario_id}: "
                f"missing={missing}, unregistered={extra}"
            )
        for relative in sorted(actual_artifacts):
            expected_digest = result["output_digests"][relative]
            actual_digest = digest_record(files[relative].read_bytes())
            if actual_digest != expected_digest:
                raise ScenarioContractError(
                    f"scenario artifact hash mismatch: {scenario_id}/{relative}"
                )

        expected_patterns = [str(pattern) for pattern in row["expected_artifacts"]]
        actual_files = set(files)
        for pattern in expected_patterns:
            if not any(PurePosixPath(relative).match(pattern) for relative in actual_files):
                raise ScenarioContractError(
                    f"scenario expected artifact is missing: {scenario_id}/{pattern}"
                )
        unregistered_files = sorted(
            relative
            for relative in actual_files
            if not any(PurePosixPath(relative).match(pattern) for pattern in expected_patterns)
        )
        if unregistered_files:
            raise ScenarioContractError(
                f"scenario contains unregistered files: {scenario_id}: {unregistered_files}"
            )
        result_paths.append(result_path)

    rebuilt_summary = build_summary(manifest_path, result_paths)
    if rebuilt_summary != recorded_summary:
        raise ScenarioContractError("scenario summary digest/count registry mismatch")
    return rebuilt_summary


def _verify_digest_only_output_map(result: Mapping[str, Any], scenario_id: str) -> None:
    """Validate logical artifact digests without requiring raw artifacts on disk."""

    output_digests = result.get("output_digests")
    counts = result.get("counts")
    coverage = result.get("provider_coverage")
    if not isinstance(output_digests, Mapping):
        raise ScenarioContractError(f"logical digest map is missing: {scenario_id}")
    if not isinstance(counts, Mapping) or not isinstance(coverage, Mapping):
        raise ScenarioContractError(f"logical digest metadata is missing: {scenario_id}")
    collection_mode = result.get("collection_mode")
    prior_digests = result.get("prior_evidence_digests")
    argv = result.get("argv")
    if not isinstance(argv, list) or not all(isinstance(value, str) for value in argv):
        raise ScenarioContractError(f"provider collection argv is invalid: {scenario_id}")
    schema_version = result.get("schema_version")
    if schema_version == SCHEMA_RESULT:
        # Frozen v1 digest-only fixtures predate resumable acquisition. They
        # remain readable, while all newly exported provider evidence uses v2.
        if collection_mode is not None or prior_digests is not None:
            raise ScenarioContractError(f"legacy collection has v2 fields: {scenario_id}")
    elif collection_mode == "fresh":
        if prior_digests is not None:
            raise ScenarioContractError(f"fresh collection has prior evidence: {scenario_id}")
        if (
            "--fetch-public" not in argv
            or "--public-evidence-out" not in argv
            or "--resume-public-evidence" in argv
        ):
            raise ScenarioContractError(f"fresh collection argv differs: {scenario_id}")
    elif collection_mode == "resume":
        if (
            not isinstance(prior_digests, Mapping)
            or set(prior_digests) != {"manifest", "payload"}
        ):
            raise ScenarioContractError(f"resume prior evidence is not closed: {scenario_id}")
        for label in ("manifest", "payload"):
            digest = prior_digests.get(label)
            if not isinstance(digest, Mapping) or digest != {
                "algorithm": "sha256",
                "value": str(digest.get("value") or "")
                if isinstance(digest, Mapping)
                else "",
            }:
                raise ScenarioContractError(
                    f"resume prior {label} digest is not closed: {scenario_id}"
                )
            if _HEX_64.fullmatch(str(digest.get("value") or "")) is None:
                raise ScenarioContractError(
                    f"resume prior {label} digest is malformed: {scenario_id}"
                )
        if (
            "--resume-public-evidence" not in argv
            or "--fetch-public" in argv
            or "--public-evidence-out" in argv
        ):
            raise ScenarioContractError(f"resume collection argv differs: {scenario_id}")
    else:
        raise ScenarioContractError(f"provider collection mode is invalid: {scenario_id}")
    pages = counts.get("provider.pages")
    if not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= 100:
        raise ScenarioContractError(f"provider page digest count is invalid: {scenario_id}")
    coverage_kind = coverage.get("kind")
    if coverage_kind == "observed":
        if coverage != {"kind": "observed", "provided": True}:
            raise ScenarioContractError(f"public digest coverage is not closed: {scenario_id}")
        public_phase = "live"
    elif coverage_kind == "not_proven":
        if coverage != {
            "kind": "not_proven",
            "provided": True,
            "reason": "public_evidence_partial",
        }:
            raise ScenarioContractError(f"public digest coverage is not closed: {scenario_id}")
        public_phase = "partial"
    else:
        raise ScenarioContractError(f"public digest coverage kind is invalid: {scenario_id}")
    expected = set(_DIGEST_ONLY_DERIVED)
    for phase in ("offline", public_phase, "replay"):
        expected.update(f"{phase}/{relative}" for relative in _DIGEST_ONLY_COLLECTION_MEMBERS)
    expected.update({"public-evidence/manifest.json", "public-evidence/payload"})
    expected.update(f"public-evidence/page-{number:02d}.body" for number in range(1, pages + 1))
    actual = set(output_digests)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ScenarioContractError(
            f"logical digest registry mismatch: {scenario_id}: "
            f"missing={missing}, unregistered={extra}"
        )
    observed_pages: list[int] = []
    for relative, digest in output_digests.items():
        pure = PurePosixPath(str(relative))
        if pure.is_absolute() or ".." in pure.parts or "\\" in str(relative):
            raise ScenarioContractError(f"logical digest path is unsafe: {scenario_id}")
        match = _PUBLIC_PAGE_DIGEST.fullmatch(str(relative))
        if match is not None:
            observed_pages.append(int(match.group(1)))
        if not isinstance(digest, Mapping) or digest != {
            "algorithm": "sha256",
            "value": str(digest.get("value") or "") if isinstance(digest, Mapping) else "",
        }:
            raise ScenarioContractError(f"logical digest record is not closed: {scenario_id}")
        if _HEX_64.fullmatch(str(digest.get("value") or "")) is None:
            raise ScenarioContractError(f"logical digest value is malformed: {scenario_id}")
    if sorted(observed_pages) != list(range(1, pages + 1)):
        raise ScenarioContractError(f"provider page digest sequence is not closed: {scenario_id}")


def _assert_digest_only_sanitized(body: bytes, label: str) -> None:
    folded = body.lower()
    if any(needle in folded for needle in _DIGEST_ONLY_FORBIDDEN):
        raise ScenarioContractError(f"digest-only registry leaks source data: {label}")


def verify_digest_only_registry(
    root: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Verify a sanitized result/hash registry whose raw artifacts are intentionally absent."""

    root = root.resolve()
    source_root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    current_runner = build_runner_binding(source_root)
    manifest_path = root / "manifest.json"
    summary_path = root / "summary.json"
    if manifest_path.is_symlink() or summary_path.is_symlink():
        raise ScenarioContractError("digest-only registry files must not be symlinks")
    try:
        manifest_body = manifest_path.read_bytes()
        summary_body = summary_path.read_bytes()
        _assert_digest_only_sanitized(manifest_body, "manifest.json")
        _assert_digest_only_sanitized(summary_body, "summary.json")
        manifest = json.loads(manifest_body.decode("utf-8"))
        recorded_summary = json.loads(summary_body.decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioContractError(f"digest-only registry is unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(recorded_summary, dict):
        raise ScenarioContractError("digest-only registry roots must be objects")
    _validate(manifest)
    _validate(recorded_summary)
    scenario_rows = manifest["scenarios"]
    scenario_ids = [str(row["id"]) for row in scenario_rows]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ScenarioContractError("digest-only manifest contains duplicate IDs")
    expected_root = {"manifest.json", "summary.json", *scenario_ids}
    actual_root = {path.name for path in root.iterdir()}
    if actual_root != expected_root:
        raise ScenarioContractError(
            "digest-only root registry mismatch: "
            f"missing={sorted(expected_root - actual_root)}, "
            f"unregistered={sorted(actual_root - expected_root)}"
        )

    result_paths: list[Path] = []
    for row in scenario_rows:
        scenario_id = str(row["id"])
        if row.get("tier") != "live-pr":
            raise ScenarioContractError(f"digest-only scenario tier differs: {scenario_id}")
        if row.get("expected_artifacts") != ["scenario-result.json"]:
            raise ScenarioContractError(
                f"digest-only expected artifact contract differs: {scenario_id}"
            )
        scenario_root = root / scenario_id
        if scenario_root.is_symlink() or not scenario_root.is_dir():
            raise ScenarioContractError(f"digest-only scenario directory is unsafe: {scenario_id}")
        members = list(scenario_root.iterdir())
        if len(members) != 1 or members[0].name != "scenario-result.json":
            raise ScenarioContractError(
                f"digest-only scenario member registry mismatch: {scenario_id}"
            )
        result_path = members[0]
        if result_path.is_symlink() or not result_path.is_file():
            raise ScenarioContractError(f"digest-only result is unsafe: {scenario_id}")
        body = result_path.read_bytes()
        _assert_digest_only_sanitized(body, scenario_id)
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScenarioContractError(f"digest-only result is unreadable: {scenario_id}") from exc
        if not isinstance(result, dict):
            raise ScenarioContractError(f"digest-only result root is not an object: {scenario_id}")
        _validate(result)
        if result.get("scenario_id") != scenario_id:
            raise ScenarioContractError(f"digest-only result ID mismatch: {scenario_id}")
        if result.get("target_oid") != row.get("target_oid"):
            raise ScenarioContractError(f"digest-only target OID mismatch: {scenario_id}")
        verify_runner_binding(
            result.get("runner") if isinstance(result.get("runner"), Mapping) else {},
            project_root=source_root,
            current=current_runner,
        )
        assertion_ids = [str(assertion["id"]) for assertion in result["assertions"]]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ScenarioContractError(f"duplicate digest-only assertion ID: {scenario_id}")
        if result.get("verdict") != verdict_from_assertions(result["assertions"]):
            raise ScenarioContractError(f"digest-only verdict differs: {scenario_id}")
        _verify_digest_only_output_map(result, scenario_id)
        if result.get("verdict") == "PASS":
            tool_version = result["runner"]["tool_version"]
            version_rows = [
                assertion
                for assertion in result["assertions"]
                if assertion.get("id") == "runner-tool-version"
            ]
            if version_rows != [
                {
                    "id": "runner-tool-version",
                    "status": "PASS",
                    "expected": tool_version,
                    "actual": tool_version,
                }
            ]:
                raise ScenarioContractError(
                    f"digest-only runner version is not proven: {scenario_id}"
                )
            receipt = public_acquisition_digest(result)
            receipt_rows = [
                assertion
                for assertion in result["assertions"]
                if assertion.get("id") == "acquisition-receipt-digest"
            ]
            if receipt_rows != [
                {
                    "id": "acquisition-receipt-digest",
                    "status": "PASS",
                    "expected": receipt["value"],
                    "actual": receipt["value"],
                }
            ]:
                raise ScenarioContractError(
                    f"digest-only acquisition receipt differs: {scenario_id}"
                )
        result_paths.append(result_path)

    rebuilt_summary = build_summary(manifest_path, result_paths)
    if rebuilt_summary != recorded_summary:
        raise ScenarioContractError("digest-only summary/result hash registry mismatch")
    return rebuilt_summary


def _selection(names: Sequence[str], *, include_cloudflare: bool) -> list[ScenarioSpec]:
    available = {spec.scenario_id: spec for spec in REGISTERED_OFFLINE_SCENARIOS}
    if include_cloudflare:
        available[CLOUDFLARE_REPLAY.scenario_id] = CLOUDFLARE_REPLAY
    if not names:
        return list(REGISTERED_OFFLINE_SCENARIOS) + (
            [CLOUDFLARE_REPLAY] if include_cloudflare else []
        )
    unknown = sorted(set(names) - set(available))
    if unknown:
        raise ScenarioContractError("unknown scenario IDs: " + ", ".join(unknown))
    return [available[name] for name in names]


def _parse_source_overrides(
    values: Sequence[str],
    *,
    selected_ids: set[str],
) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        scenario_id, separator, raw_path = value.partition("=")
        if not separator or not scenario_id or not raw_path:
            raise ScenarioContractError("--source must be SCENARIO_ID=PATH")
        if scenario_id not in selected_ids:
            raise ScenarioContractError(f"--source scenario is not selected: {scenario_id}")
        if scenario_id in overrides:
            raise ScenarioContractError(f"duplicate --source override: {scenario_id}")
        overrides[scenario_id] = Path(raw_path).resolve()
    return overrides


def _default_developer_root(project_root: Path) -> Path:
    for ancestor in project_root.parents:
        if ancestor.name == ".worktrees":
            return ancestor.parent.parent
    return project_root.parent


def _assert_safe_output_root(output_root: Path, developer_root: Path, project_root: Path) -> None:
    resolved = output_root.resolve()
    forbidden = {Path("/").resolve(), developer_root.resolve(), project_root.resolve()}
    if resolved in forbidden:
        raise ScenarioContractError("scenario output root is too broad")


def _publish(staged: Path, output_root: Path, *, replace: bool) -> None:
    if output_root.exists():
        if not replace:
            raise ScenarioContractError(
                f"scenario output already exists: {output_root}; pass --replace to replace it"
            )
        manifest = output_root / "manifest.json"
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenarioContractError(
                "refusing to replace an output directory without a v0.6 scenario manifest"
            ) from exc
        if existing.get("schema_version") != SCHEMA_MANIFEST:
            raise ScenarioContractError(
                "refusing to replace an output directory owned by another artifact"
            )
        backup = output_root.parent / f".{output_root.name}.previous-{os.getpid()}"
        if backup.exists():
            raise ScenarioContractError("scenario publication backup path already exists")
        os.replace(output_root, backup)
        try:
            os.replace(staged, output_root)
        except Exception:
            os.replace(backup, output_root)
            raise
        shutil.rmtree(backup)
        return
    os.replace(staged, output_root)


def run_matrix(
    specs: Sequence[ScenarioSpec],
    *,
    developer_root: Path,
    project_root: Path,
    output_root: Path,
    cloudflare_bundle: Path | None,
    replace: bool,
    source_overrides: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    developer_root = developer_root.resolve()
    project_root = project_root.resolve()
    output_root = output_root.resolve()
    _assert_safe_output_root(output_root, developer_root, project_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    if output_root.exists() and not replace:
        raise ScenarioContractError(
            f"scenario output already exists: {output_root}; pass --replace to replace it"
        )
    with tempfile.TemporaryDirectory(
        prefix=".v060-scenario-stage-",
        dir=output_root.parent,
    ) as temporary:
        staged = Path(temporary) / output_root.name
        staged.mkdir()
        runner_binding = build_runner_binding(project_root)
        manifest = build_manifest(specs)
        manifest_path = staged / "manifest.json"
        write_json(manifest_path, manifest)
        result_paths: list[Path] = []
        resolved_sources = dict(source_overrides or {})
        for spec in specs:
            scenario_root = staged / spec.scenario_id
            bundle = cloudflare_bundle if spec.requires_public_evidence else None
            scenario_source = resolved_sources.get(
                spec.scenario_id,
                developer_root / spec.repo_relative,
            )
            if spec.shallow_depth is not None:
                scenario_source = build_shallow_fixture(
                    scenario_source, spec, Path(temporary) / f"{spec.scenario_id}-fixture"
                )
            result = run_scenario(
                spec,
                source=scenario_source,
                project_root=project_root,
                scenario_root=scenario_root,
                public_bundle=bundle,
                runner=runner_binding,
            )
            result_path = scenario_root / "scenario-result.json"
            write_json(result_path, result)
            result_paths.append(result_path)
        summary = build_summary(manifest_path, result_paths)
        write_json(staged / "summary.json", summary)
        verify_evidence_registry(staged, project_root=project_root)
        _publish(staged, output_root, replace=replace)
        return summary


def main(argv: Sequence[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run v0.6 fixed-OID repo/actor scenarios without mutating source repos."
    )
    parser.add_argument(
        "--developer-root",
        type=Path,
        default=_default_developer_root(project_root),
        help="Read-only repository parent (default: parent of this checkout).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_root / "evidence" / "v060" / "scenarios",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Scenario ID to run (repeatable; default: all six registered local scenarios).",
    )
    parser.add_argument(
        "--cloudflare-bundle",
        type=Path,
        default=None,
        help="Saved public-evidence directory. Supplying it enables R05 replay.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="SCENARIO_ID=PATH",
        help=(
            "Read-only source override for an explicitly selected scenario; "
            "repeatable and never recorded in evidence"
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace only an existing tep-scenario-manifest-v1 output directory.",
    )
    parser.add_argument("--list", action="store_true", help="List scenario IDs and exit.")
    parser.add_argument(
        "--verify-registry",
        action="store_true",
        help="Verify hashes and current tool-source binding without running scenarios.",
    )
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help=(
            "With --verify-registry, validate the sanitized public result/hash registry "
            "without requiring intentionally uncommitted raw provider artifacts."
        ),
    )
    parser.add_argument(
        "--print-runner-binding",
        action="store_true",
        help="Print the current tool version/source binding for external live scenarios.",
    )
    args = parser.parse_args(argv)
    if args.digest_only and (not args.verify_registry or args.list or args.print_runner_binding):
        print(
            "v0.6 scenario matrix failed: --digest-only requires --verify-registry as the only mode",
            file=sys.stderr,
        )
        return 2
    include_cloudflare = args.cloudflare_bundle is not None
    available = list(REGISTERED_OFFLINE_SCENARIOS) + [CLOUDFLARE_REPLAY]
    if args.list:
        for spec in available:
            print(spec.scenario_id)
        return 0
    if args.print_runner_binding:
        if (
            args.scenario
            or args.source
            or args.cloudflare_bundle is not None
            or args.replace
            or args.verify_registry
            or args.digest_only
        ):
            print(
                "v0.6 scenario matrix failed: --print-runner-binding cannot be combined "
                "with run/verify options",
                file=sys.stderr,
            )
            return 2
        try:
            binding = build_runner_binding(project_root)
        except (OSError, subprocess.SubprocessError, ScenarioContractError) as exc:
            print(f"v0.6 scenario matrix failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(binding, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.verify_registry:
        if args.scenario or args.source or args.cloudflare_bundle is not None or args.replace:
            print(
                "v0.6 scenario matrix failed: --verify-registry only accepts --output-root",
                file=sys.stderr,
            )
            return 2
        try:
            verifier = verify_digest_only_registry if args.digest_only else verify_evidence_registry
            summary = verifier(args.output_root)
        except (OSError, ScenarioContractError) as exc:
            print(f"v0.6 scenario matrix failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if summary["verdict"] == "PASS" else 1
    try:
        specs = _selection(args.scenario, include_cloudflare=include_cloudflare)
        source_overrides = _parse_source_overrides(
            args.source,
            selected_ids={spec.scenario_id for spec in specs},
        )
        summary = run_matrix(
            specs,
            developer_root=args.developer_root,
            project_root=project_root,
            output_root=args.output_root,
            cloudflare_bundle=(
                args.cloudflare_bundle.resolve() if args.cloudflare_bundle is not None else None
            ),
            replace=args.replace,
            source_overrides=source_overrides,
        )
    except (OSError, subprocess.SubprocessError, ScenarioContractError) as exc:
        print(f"v0.6 scenario matrix failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    verdict = summary["verdict"]
    if verdict == "PASS":
        return 0
    if verdict == "NOT_PROVEN":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
