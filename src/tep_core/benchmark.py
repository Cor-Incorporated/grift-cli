"""Local v0.6 benchmark catalog. Offline. No ranking, no role truth."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from tep_core.digest import file_digest, sha256_bytes
from tep_core.secrets_guard import InputValidationError

REQUIRED_FIELDS = (
    "id",
    "kind",
    "source_url",
    "source_version",
    "as_of",
    "window",
    "n",
    "denominator",
    "coverage",
    "sha256",
    "use_for",
    "do_not_use_for",
    "limitations",
    "quality_notes",
)

_PACK_ENV = "GRIFT_BENCHMARK_PACK"
_RESOURCE_STACK = ExitStack()


def portable_manifest_ref(path: Path | None) -> str | None:
    """Record a non-absolute identifier. Never emit /Users or /home paths."""
    if path is None:
        return None
    name = path.name
    if name and name != path.as_posix() and "/" not in name and "\\" not in name:
        return name
    return path.name or None


def default_manifest() -> Path:
    env = os.environ.get(_PACK_ENV)
    if env:
        path = Path(env)
        return path if path.name == "sources.json" else path / "sources.json"
    candidate = Path.cwd() / "benchmarks" / "v060" / "sources.json"
    if candidate.is_file():
        return candidate
    resource = files("tep_core").joinpath("benchmark_assets", "v060", "sources.json")
    if resource.is_file():
        return _RESOURCE_STACK.enter_context(as_file(resource))
    raise InputValidationError(
        "benchmark pack not found; pass sources.json or set GRIFT_BENCHMARK_PACK"
    )


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or default_manifest()
    if not manifest_path.is_file():
        raise InputValidationError(f"benchmark manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputValidationError("benchmark manifest is not JSON") from exc
    if not isinstance(data, dict):
        raise InputValidationError("benchmark manifest must be an object")
    for key in ("pack_id", "pack_version", "as_of", "purpose", "policy", "artifacts"):
        if key not in data:
            raise InputValidationError(f"benchmark manifest missing {key}")
    data["_manifest_path"] = str(manifest_path)
    data["_pack_root"] = str(manifest_path.parent)
    return data


def _n_from_artifact(artifact: dict[str, Any]) -> int | None:
    for key in ("rows", "sample_rows"):
        value = artifact.get(key)
        if isinstance(value, int):
            return value
    scale = artifact.get("reported_scale") or {}
    for key in ("projects", "full_instances", "issues"):
        value = scale.get(key)
        if isinstance(value, int):
            return value
    population = artifact.get("population")
    if isinstance(population, str) and population.split() and population.split()[0].isdigit():
        return int(population.split()[0])
    return None


def catalog_entry(artifact: dict[str, Any], *, pack_as_of: str) -> dict[str, Any]:
    sha = artifact.get("sha256")
    unavailable = None
    if not sha:
        unavailable = (
            artifact.get("raw_distribution")
            or artifact.get("quality_notes")
            and "not bundled"
            or "sha256 not published in this pack"
        )
        if isinstance(unavailable, list):
            unavailable = "; ".join(str(item) for item in unavailable)
    notes = artifact.get("quality_notes") or []
    if isinstance(notes, str):
        notes = [notes]
    limitations = artifact.get("limitations")
    if limitations is None:
        limitations = list(notes)
    coverage = artifact.get("coverage")
    return {
        "id": artifact.get("id"),
        "kind": artifact.get("kind"),
        "source_url": artifact.get("source_url"),
        "source_version": artifact.get("source_version")
        or artifact.get("published")
        or artifact.get("last_updated")
        or pack_as_of,
        "as_of": artifact.get("as_of") or pack_as_of,
        "window": artifact.get("window") or artifact.get("source_window"),
        "n": artifact.get("n") if "n" in artifact else _n_from_artifact(artifact),
        "denominator": artifact.get("denominator"),
        "coverage": coverage,
        "sha256": sha,
        "sha256_unavailable_reason": None if sha else str(unavailable),
        "use_for": list(artifact.get("use_for") or []),
        "do_not_use_for": list(artifact.get("do_not_use_for") or []),
        "limitations": list(limitations) if not isinstance(limitations, str) else [limitations],
        "quality_notes": list(notes),
        "artifact": artifact.get("artifact"),
    }


def catalog(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    as_of = str(manifest.get("as_of") or "")
    entries = [catalog_entry(item, pack_as_of=as_of) for item in manifest.get("artifacts") or []]
    for entry in entries:
        missing = [
            key
            for key in ("id", "kind", "source_url", "use_for", "do_not_use_for")
            if not entry.get(key)
        ]
        if missing:
            raise InputValidationError(f"catalog entry missing {missing}")
    return entries


def find_entry(manifest: dict[str, Any], source_id: str) -> dict[str, Any]:
    for entry in catalog(manifest):
        if entry["id"] == source_id:
            return entry
    raise InputValidationError(f"unknown reference id: {source_id}")


def registered_paths(manifest: dict[str, Any]) -> dict[str, str]:
    hashes = manifest.get("local_artifact_sha256") or {}
    if not isinstance(hashes, dict):
        raise InputValidationError("local_artifact_sha256 must be an object")
    return {str(key): str(value) for key, value in hashes.items()}


def resolve_registered(manifest: dict[str, Any], relative: str) -> Path:
    root = Path(str(manifest["_pack_root"]))
    hashes = registered_paths(manifest)
    if relative not in hashes:
        raise InputValidationError(f"unregistered fixture path: {relative}")
    unresolved = root / relative
    if unresolved.is_symlink():
        raise InputValidationError(f"fixture path must not be a symlink: {relative}")
    path = unresolved.resolve()
    pack = root.resolve()
    try:
        path.relative_to(pack)
    except ValueError as exc:
        raise InputValidationError(f"fixture path escapes pack: {relative}") from exc
    if not path.is_file():
        raise InputValidationError(f"registered fixture missing: {relative}")
    return path


def assert_registered_file(manifest: dict[str, Any], path: Path) -> str:
    root = Path(str(manifest["_pack_root"])).resolve()
    resolved = path.resolve()
    try:
        relative = str(resolved.relative_to(root)).replace("\\", "/")
    except ValueError as exc:
        raise InputValidationError(f"unregistered fixture path: {path}") from exc
    hashes = registered_paths(manifest)
    if relative not in hashes:
        raise InputValidationError(f"unregistered fixture path: {relative}")
    digest = file_digest(resolved)
    expected = hashes[relative]
    if digest != expected:
        raise InputValidationError(f"fixture hash mismatch: {relative}")
    return digest


def validate_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest = load_manifest(path)
    errors: list[str] = []
    root = Path(str(manifest["_pack_root"]))
    hashes = registered_paths(manifest)
    entries = catalog(manifest)
    ids = [entry.get("id") for entry in entries]
    duplicates = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
    if duplicates:
        errors.append(f"duplicate artifact ids: {duplicates}")
    for entry in entries:
        for field in REQUIRED_FIELDS:
            if field == "sha256":
                if not entry.get("sha256") and not entry.get("sha256_unavailable_reason"):
                    errors.append(
                        f"{entry.get('id')}: sha256 or sha256_unavailable_reason required"
                    )
                continue
            if entry.get(field) in (None, "", []):
                errors.append(f"{entry.get('id')}: missing {field}")
        artifact = entry.get("artifact")
        if artifact:
            if artifact not in hashes:
                errors.append(f"{entry.get('id')}: artifact is unregistered: {artifact}")
            elif entry.get("sha256") != hashes.get(artifact):
                errors.append(f"{entry.get('id')}: artifact sha256 does not match registry")
    if errors:
        raise InputValidationError("benchmark validate failed:\n" + "\n".join(errors))
    for relative, expected in hashes.items():
        file_path = root / relative
        if file_path.is_symlink():
            errors.append(f"symlink fixture is forbidden: {relative}")
            continue
        if not file_path.is_file():
            errors.append(f"missing {relative}")
            continue
        digest = sha256_bytes(file_path.read_bytes())
        if digest != expected:
            errors.append(f"hash mismatch {relative}")
    registered = set(hashes)
    actual: set[str] = set()
    for folder in ("data", "expected", "schemas"):
        base = root / folder
        if not base.is_dir():
            continue
        for file_path in base.rglob("*"):
            if file_path.is_symlink():
                errors.append(
                    "symlink fixture is forbidden: " + file_path.relative_to(root).as_posix()
                )
                continue
            if file_path.is_file():
                actual.add(file_path.relative_to(root).as_posix())
    unregistered = sorted(actual - registered)
    stale = sorted(registered - actual)
    if unregistered:
        errors.append(f"unregistered local artifacts: {unregistered}")
    if stale:
        errors.append(f"registered paths missing from pack: {stale}")
    gharchive = next(
        (
            entry
            for entry in entries
            if entry.get("id") == "gharchive-2024-01-15-to-21-selected-repos"
        ),
        None,
    )
    if gharchive is not None:
        coverage = gharchive.get("coverage")
        expected_coverage = {
            "status": "partial",
            "observed": 7,
            "expected": 168,
            "missing": 161,
            "unit": "hours",
            "rate": 0.0417,
        }
        if coverage != expected_coverage:
            errors.append("GH Archive coverage must record 7/168 hours (4.17%, partial)")
    if errors:
        raise InputValidationError("benchmark validate failed:\n" + "\n".join(errors))
    return {
        "ok": True,
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "as_of": manifest["as_of"],
        "checked": len(hashes),
        "artifacts": len(entries),
        "offline": True,
        "required_fields": list(REQUIRED_FIELDS),
    }


def attach_reference(
    *,
    source_id: str,
    observed: dict[str, Any] | None,
    metric_id: str,
    limitations: list[str],
    missing: list[str] | None = None,
    interpretation: str = "observed value only; not a verdict",
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    entry = find_entry(manifest, source_id)
    n = entry.get("n")
    if isinstance(n, int) and n < 30:
        reference: dict[str, Any] = {
            "kind": "not_proven",
            "reason": "reference_too_small",
            "source_id": source_id,
            "n": n,
        }
    elif entry.get("sha256") is None:
        reference = {
            "kind": "not_proven",
            "reason": "distribution_not_bundled",
            "source_id": source_id,
            "n": n,
            "summary": "distribution unavailable in local pack",
        }
    else:
        reference = {
            "source_id": source_id,
            "n": n,
            "kind": entry.get("kind"),
            "window": entry.get("window"),
            "sha256": entry.get("sha256"),
            "sha256_unavailable_reason": entry.get("sha256_unavailable_reason"),
            "summary": "local pack metadata only; no pass/fail threshold",
        }
    status = "partial" if missing else "present"
    if reference.get("kind") == "not_proven":
        status = "partial"
    return {
        "metric_id": metric_id,
        "observed": observed,
        "reference": reference,
        "coverage": {"status": status, "missing": missing or []},
        "limitations": limitations,
        "interpretation": interpretation,
    }
