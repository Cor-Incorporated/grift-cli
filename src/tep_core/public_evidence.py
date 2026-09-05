"""Content-addressed, replayable public Forge evidence bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote

from tep_core.forge_public import (
    ForgeLocator,
    GitObjectId,
    HttpResponse,
    RequestSpec,
    UnsafeRequestError,
    adapter_for,
    assert_valid_commit_request,
)
from tep_core.schema import validate_schema

EvidenceTransport = Callable[[RequestSpec], HttpResponse]
_DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024

_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "etag",
        "last-modified",
        "link",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "retry-after",
        "x-next-page",
        "x-page",
        "x-per-page",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-total",
        "x-total-pages",
    }
)
_LICENSE_NAME_RE = re.compile(r"^(licen[cs]e|copying|notice)(\..*)?$", re.IGNORECASE)
_LINK_TARGET_RE = re.compile(r"<([^<>]+)>")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("bundle_payload_sha256", None)
    return _digest_bytes(_canonical_bytes(payload))


def manifest_fetched_login_count(manifest: Mapping[str, Any] | None) -> int | None:
    """Return only the legacy contributor-list count recorded in a manifest.

    Commit CAS account IDs are represented by ``sha_to_account`` and
    ``commit_login_count``; they must not be relabeled as a contributors-list
    observation.  New public-evidence manifests therefore return ``None`` for
    this legacy field, identically during production and offline replay.
    """

    if manifest is None:
        return None
    value = manifest.get("fetched_login_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _safe_response_headers(
    headers: Mapping[str, str], *, provider: str | None = None
) -> dict[str, str]:
    # GitLab pagination is derived exclusively from X-Next-Page.  Its Link
    # response contains server-added query keys outside the request contract,
    # so it is neither consumed nor persisted.
    allowlist = (
        _RESPONSE_HEADER_ALLOWLIST - {"link"}
        if provider == "gitlab"
        else _RESPONSE_HEADER_ALLOWLIST
    )
    return {
        key.casefold(): str(value)
        for key, value in sorted(headers.items(), key=lambda item: item[0].casefold())
        if key.casefold() in allowlist
    }


def _validate_link_header(
    headers: Mapping[str, str], locator: ForgeLocator, target_oid: GitObjectId
) -> None:
    if locator.provider == "gitlab":
        return
    value = next(
        (str(raw) for key, raw in headers.items() if key.casefold() == "link"),
        "",
    ).strip()
    if not value:
        return
    targets = _LINK_TARGET_RE.findall(value)
    if not targets or value.count("<") != len(targets) or value.count(">") != len(targets):
        raise UnsafeRequestError("Forge Link header is malformed")
    for target in targets:
        # Validate every relation, not only rel=next: a stored prev/last URL
        # must not become a credential or cross-origin exfiltration channel.
        assert_valid_commit_request(
            RequestSpec("GET", target),
            locator,
            target_oid,
            allow_github_numeric_link=True,
        )


def _assert_runtime_token_not_in_url(request: RequestSpec, auth_token: str | None) -> None:
    """Reject an actual runtime secret before transport or persistence.

    Static credential-key checks cannot recognize every opaque provider token.
    Compare the selected secret against both the raw and percent-decoded URL so
    an explicitly supplied API base cannot turn the evidence manifest into a
    credential sink.
    """

    decoded = request.url
    for _ in range(16):
        if auth_token and auth_token in decoded:
            raise UnsafeRequestError("authentication token in request URL is forbidden")
        candidate = unquote(decoded)
        if candidate == decoded:
            return
        decoded = candidate
    raise UnsafeRequestError("request URL is excessively percent encoded")


def _validate_path_parts(parts: tuple[str, ...]) -> None:
    if not parts or any(not part or part in {".", ".."} or "/" in part for part in parts):
        raise UnsafeRequestError("unsafe public evidence path component")


def _prepare_evidence_root(root: Path, *, create: bool) -> Path:
    """Reject lexical parent symlinks before opening a bundle root.

    ``Path.mkdir(parents=True)`` follows a symlink in any parent component.
    Public response bodies must never be redirected outside the selected
    evidence location, so every lexical component is checked with ``lstat``.
    The root itself is opened with ``O_NOFOLLOW`` immediately afterwards.
    """

    candidate = Path(os.path.abspath(Path(root).expanduser()))
    components = list(reversed((candidate, *candidate.parents)))
    for directory in components:
        try:
            metadata = directory.lstat()
            mode = metadata.st_mode
        except FileNotFoundError:
            if not create:
                raise
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                pass
            try:
                metadata = directory.lstat()
                mode = metadata.st_mode
            except OSError as exc:
                raise UnsafeRequestError("public evidence parent is unavailable") from exc
        except OSError as exc:
            raise UnsafeRequestError("public evidence parent is unavailable") from exc
        if stat.S_ISLNK(mode):
            system_root = Path(directory.anchor)
            root_metadata = system_root.lstat()
            trusted_system_alias = (
                directory.parent == system_root
                and metadata.st_uid == 0
                and root_metadata.st_uid == 0
                and not root_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            )
            if trusted_system_alias:
                continue
            raise UnsafeRequestError("public evidence path must not traverse a symlink")
        if not stat.S_ISDIR(mode):
            raise UnsafeRequestError("public evidence parent must be a directory")
    return candidate


def _open_secure_directory(
    root: Path, directories: tuple[str, ...], *, create: bool
) -> tuple[int, int]:
    _validate_path_parts(directories or ("root",))
    root = _prepare_evidence_root(root, create=create)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise UnsafeRequestError("public evidence root is not a safe directory") from exc
    current_fd = root_fd
    try:
        if create:
            os.fchmod(root_fd, 0o700)
        elif stat.S_IMODE(os.fstat(root_fd).st_mode) != 0o700:
            raise UnsafeRequestError("public evidence root mode must be 0700")
        for name in directories:
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
            try:
                child_fd = os.open(name, flags, dir_fd=current_fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise UnsafeRequestError(
                    "public evidence directory contains a symlink or non-directory"
                ) from exc
            if create:
                os.fchmod(child_fd, 0o700)
            elif stat.S_IMODE(os.fstat(child_fd).st_mode) != 0o700:
                os.close(child_fd)
                raise UnsafeRequestError("public evidence directory mode must be 0700")
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        return root_fd, current_fd
    except Exception:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
        raise


def _secure_read(root: Path, parts: tuple[str, ...]) -> bytes:
    _validate_path_parts(parts)
    root_fd, directory_fd = _open_secure_directory(root, parts[:-1], create=False)
    descriptor = -1
    try:
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeRequestError("public evidence entry is not a regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UnsafeRequestError("public evidence entry mode must be 0600")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise UnsafeRequestError("public evidence entry is a symlink or unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_fd != root_fd:
            os.close(directory_fd)
        os.close(root_fd)


def _write_private(root: Path, parts: tuple[str, ...], data: bytes) -> None:
    _validate_path_parts(parts)
    root_fd, directory_fd = _open_secure_directory(root, parts[:-1], create=True)
    temporary = f".{parts[-1]}.tmp-{os.getpid()}-{os.urandom(4).hex()}"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary,
            parts[-1],
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.chmod(parts[-1], 0o600, dir_fd=directory_fd, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        if directory_fd != root_fd:
            os.close(directory_fd)
        os.close(root_fd)


def _write_blob(root: Path, body: bytes) -> str:
    digest = _digest_bytes(body)
    parts = ("blobs", "sha256", digest)
    try:
        existing = _secure_read(root, parts)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if _digest_bytes(existing) != digest:
            raise ValueError("existing public evidence CAS blob has the wrong digest")
        return digest
    _write_private(root, parts, body)
    return digest


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    manifest["bundle_payload_sha256"] = _manifest_digest(manifest)
    _write_private(root, ("manifest.json",), _canonical_bytes(manifest) + b"\n")


def not_requested_manifest(locator: ForgeLocator, target_oid: GitObjectId) -> dict[str, Any]:
    """Return a byte-stable offline state; it never invents a collection time."""

    manifest: dict[str, Any] = {
        "schema_version": "public-evidence-v1",
        "provider": locator.provider,
        "api_version": adapter_for(locator).api_version,
        "source": locator.to_dict(),
        "target_oid": target_oid.to_dict(),
        "fetched_at": None,
        "updated_at": None,
        "collection_policy": {
            "network": "not_requested",
            "robots": "not_applicable_to_rest_api",
            "api_terms": "provider_terms_apply",
        },
        "account_linkage": adapter_for(locator).account_linkage,
        "coverage": {
            "status": "not_requested",
            "item_count": 0,
            "missing": ["public_evidence"],
        },
        "pagination": {
            "pages": 0,
            "per_page": 100,
            "truncated": False,
            "stop_reason": "fetch_not_requested",
            "next_request": None,
        },
        "pages": [],
        "commit_oids": [],
        "duplicate_commit_oids": [],
        "sha_to_account": {},
        "mapping_conflicts": [],
        "unlinked_commit_count": 0,
    }
    manifest["bundle_payload_sha256"] = _manifest_digest(manifest)
    return manifest


def _new_manifest(
    locator: ForgeLocator, target_oid: GitObjectId, fetched_at: str
) -> dict[str, Any]:
    adapter = adapter_for(locator)
    return {
        "schema_version": "public-evidence-v1",
        "provider": locator.provider,
        "api_version": adapter.api_version,
        "source": locator.to_dict(),
        "target_oid": target_oid.to_dict(),
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "collection_policy": {
            "network": "explicit_opt_in",
            "robots": "not_applicable_to_rest_api",
            "api_terms": "provider_terms_apply",
        },
        "account_linkage": adapter.account_linkage,
        "coverage": {"status": "partial", "item_count": 0, "missing": []},
        "pagination": {
            "pages": 0,
            "per_page": 100,
            "truncated": True,
            "stop_reason": "not_started",
            "next_request": None,
        },
        "pages": [],
        "commit_oids": [],
        "duplicate_commit_oids": [],
        "sha_to_account": {},
        "mapping_conflicts": [],
        "unlinked_commit_count": 0,
    }


def _load_manifest(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(_secure_read(root, ("manifest.json",)).decode("utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("public evidence manifest is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("public evidence manifest is malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("public evidence manifest root must be an object")
    return value


def _bundle_inventory_error(root: Path, expected_digests: set[str]) -> str | None:
    """Return an error for any unregistered bundle member or unsafe mode."""

    root = _prepare_evidence_root(root, create=False)

    def entries(directory: Path) -> dict[str, os.DirEntry[str]]:
        try:
            return {entry.name: entry for entry in os.scandir(directory)}
        except OSError as exc:
            raise UnsafeRequestError("public evidence inventory is unreadable") from exc

    root_entries = entries(root)
    if set(root_entries) - {"manifest.json", "blobs"}:
        return "unregistered_bundle_member"
    manifest_entry = root_entries.get("manifest.json")
    if manifest_entry is None:
        return None  # _load_manifest reports the more specific missing status.
    if manifest_entry.is_symlink() or not manifest_entry.is_file(follow_symlinks=False):
        return "unsafe_bundle_member"
    if stat.S_IMODE(manifest_entry.stat(follow_symlinks=False).st_mode) != 0o600:
        return "unsafe_bundle_mode"

    blobs_entry = root_entries.get("blobs")
    if blobs_entry is None:
        return None
    if blobs_entry.is_symlink() or not blobs_entry.is_dir(follow_symlinks=False):
        return "unsafe_bundle_member"
    if stat.S_IMODE(blobs_entry.stat(follow_symlinks=False).st_mode) != 0o700:
        return "unsafe_bundle_mode"
    blob_entries = entries(root / "blobs")
    if set(blob_entries) != {"sha256"}:
        return "unregistered_bundle_member"
    sha_entry = blob_entries["sha256"]
    if sha_entry.is_symlink() or not sha_entry.is_dir(follow_symlinks=False):
        return "unsafe_bundle_member"
    if stat.S_IMODE(sha_entry.stat(follow_symlinks=False).st_mode) != 0o700:
        return "unsafe_bundle_mode"

    found: set[str] = set()
    for name, entry in entries(root / "blobs" / "sha256").items():
        if re.fullmatch(r"[0-9a-f]{64}", name) is None:
            return "unregistered_bundle_member"
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            return "unsafe_bundle_member"
        if stat.S_IMODE(entry.stat(follow_symlinks=False).st_mode) != 0o600:
            return "unsafe_bundle_mode"
        found.add(name)
    if found - expected_digests:
        return "unregistered_cas_blob"
    return None


def _assert_resume_target(
    manifest: Mapping[str, Any], locator: ForgeLocator, target_oid: GitObjectId
) -> None:
    if manifest.get("schema_version") != "public-evidence-v1":
        raise ValueError("resume bundle schema_version does not match public-evidence-v1")
    if manifest.get("provider") != locator.provider:
        raise ValueError("resume bundle provider does not match")
    if manifest.get("source") != locator.to_dict():
        raise ValueError("resume bundle source does not match")
    if manifest.get("target_oid") != target_oid.to_dict():
        raise ValueError("resume bundle target_oid does not match")
    recorded = manifest.get("bundle_payload_sha256")
    if not isinstance(recorded, str) or recorded != _manifest_digest(manifest):
        raise ValueError("resume bundle manifest digest mismatch")


def _merge_page(manifest: dict[str, Any], parsed: Any) -> None:
    seen = set(manifest["commit_oids"])
    duplicates = set(manifest["duplicate_commit_oids"])
    conflicts = list(manifest["mapping_conflicts"])
    accounts: dict[str, Any] = manifest["sha_to_account"]
    for oid in parsed.commit_oids:
        if oid in seen:
            duplicates.add(oid)
        else:
            manifest["commit_oids"].append(oid)
            seen.add(oid)
    for oid, account in parsed.sha_to_account.items():
        account_payload = account.to_dict()
        previous = accounts.get(oid)
        if previous is not None and previous != account_payload:
            conflicts.append({"commit_oid": oid, "first": previous, "second": account_payload})
            continue
        accounts[oid] = account_payload
    manifest["duplicate_commit_oids"] = sorted(duplicates)
    manifest["mapping_conflicts"] = sorted(conflicts, key=lambda item: item["commit_oid"])
    manifest["unlinked_commit_count"] += parsed.unlinked_commit_count


def collect_public_evidence(
    locator: ForgeLocator,
    target_oid: GitObjectId,
    *,
    transport: EvidenceTransport,
    evidence_dir: Path,
    max_pages: int = 100,
    auth_token: str | None = None,
    resume: bool = False,
    fetched_at: str | None = None,
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
    max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """Collect bounded API pages into a private content-addressed bundle.

    Authentication is carried only in the runtime ``RequestSpec``.  The
    persisted request is sanitized before the transport is called so unsafe
    credential URLs fail before network access.
    """

    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if max_body_bytes < 1 or max_total_bytes < max_body_bytes:
        raise ValueError("public evidence byte limits are invalid")
    root = Path(evidence_dir)
    adapter = adapter_for(locator)
    instant = fetched_at or _now()
    if resume:
        existing_verification = verify_public_evidence(root)
        if existing_verification.get("status") != "VERIFIED":
            raise ValueError(
                "existing bundle verification failed: "
                + str(existing_verification.get("reason") or "unknown")
            )
        manifest = _load_manifest(root)
        _assert_resume_target(manifest, locator, target_oid)
        cursor = manifest.get("pagination", {}).get("next_request")
        if not isinstance(cursor, dict) or not isinstance(cursor.get("url"), str):
            raise ValueError("public evidence bundle has no resumable next request")
        next_request = adapter.request_for_url(cursor["url"], auth_token=auth_token)
    else:
        try:
            _secure_read(root, ("manifest.json",))
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("public evidence manifest exists; use resume=True")
        manifest = _new_manifest(locator, target_oid, instant)
        next_request = adapter.initial_request(locator, target_oid, auth_token=auth_token)

    pages_this_run = 0
    total_body_bytes = sum(
        int(page.get("body_bytes") or 0)
        for page in manifest.get("pages", [])
        if isinstance(page, Mapping)
    )
    stop_reason = "no_next_page"
    while next_request is not None and pages_this_run < max_pages:
        _assert_runtime_token_not_in_url(next_request, auth_token)
        safe_request = assert_valid_commit_request(next_request, locator, target_oid)
        try:
            response = transport(next_request)
        except (OSError, TimeoutError) as exc:
            stop_reason = f"transport_error:{type(exc).__name__}"
            break
        if not isinstance(response, HttpResponse):
            raise TypeError("public evidence transport must return HttpResponse")
        if auth_token and auth_token.encode("utf-8") in response.body:
            raise UnsafeRequestError("Forge response echoed authentication token")
        if auth_token and auth_token in json.dumps(dict(response.headers), sort_keys=True):
            raise UnsafeRequestError("Forge response headers echoed authentication token")
        if len(response.body) > max_body_bytes:
            raise ValueError("Forge response exceeds the per-page byte limit")
        if total_body_bytes + len(response.body) > max_total_bytes:
            raise ValueError("Forge evidence exceeds the aggregate byte limit")
        # Validate all response-controlled navigation and parse the body before
        # persisting it.  A rejected cross-origin Link or malformed page must
        # not leave an unregistered raw-response blob behind.
        _validate_link_header(response.headers, locator, target_oid)
        response_headers = _safe_response_headers(response.headers, provider=locator.provider)
        parsed = None
        candidate = None
        if response.status == 200:
            parsed = adapter.parse_page(locator, next_request, response)
            if parsed.next_url is not None:
                candidate = adapter.request_for_url(parsed.next_url, auth_token=auth_token)
                _assert_runtime_token_not_in_url(candidate, auth_token)
                assert_valid_commit_request(candidate, locator, target_oid)
            _merge_page(manifest, parsed)
        total_body_bytes += len(response.body)
        body_digest = _write_blob(root, response.body)
        page: dict[str, Any] = {
            "number": len(manifest["pages"]) + 1,
            "request": safe_request,
            "http_status": response.status,
            "response_headers": response_headers,
            "body_sha256": body_digest,
            "body_bytes": len(response.body),
            "item_count": 0,
        }
        if response.status != 200:
            page["next_request"] = safe_request
            manifest["pages"].append(page)
            stop_reason = f"http_{response.status}"
            pages_this_run += 1
            break
        assert parsed is not None
        page["item_count"] = parsed.item_count
        pages_this_run += 1
        if parsed.next_url is None:
            next_request = None
            page["next_request"] = None
            stop_reason = "no_next_page"
        else:
            assert candidate is not None
            next_request = candidate
            page["next_request"] = assert_valid_commit_request(candidate, locator, target_oid)
            stop_reason = "max_pages_reached"
        manifest["pages"].append(page)

    if next_request is not None:
        next_cursor = assert_valid_commit_request(next_request, locator, target_oid)
        successful_pages = sum(
            int(page.get("http_status") == 200)
            for page in manifest["pages"]
            if isinstance(page, Mapping)
        )
        status = "partial" if successful_pages else "unavailable"
        truncated = True
        missing = ["commits_beyond_last_page" if successful_pages else "first_successful_api_page"]
    elif stop_reason.startswith("http_"):
        next_cursor = None
        status = "unavailable" if len(manifest["pages"]) == 1 else "partial"
        truncated = True
        missing = ["successful_page_after_http_error"]
    else:
        next_cursor = None
        status = "complete"
        truncated = False
        missing = []

    if manifest["mapping_conflicts"]:
        status = "partial"
        missing.append("unambiguous_sha_to_account_mapping")
    if manifest["duplicate_commit_oids"]:
        status = "partial"
        missing.append("duplicate_free_commit_population")
    manifest["updated_at"] = instant
    manifest["coverage"] = {
        "status": status,
        "item_count": sum(int(page["item_count"]) for page in manifest["pages"]),
        "missing": sorted(set(missing)),
    }
    manifest["pagination"] = {
        "pages": len(manifest["pages"]),
        "per_page": 100,
        "truncated": truncated,
        "stop_reason": stop_reason,
        "next_request": next_cursor,
    }
    _write_manifest(root, manifest)
    return manifest


def _locator_from_manifest(manifest: Mapping[str, Any]) -> ForgeLocator:
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("public evidence source is missing")
    required = ("provider", "host", "project_path", "api_base", "sanitized_remote")
    if not all(isinstance(source.get(key), str) for key in required):
        raise ValueError("public evidence source is invalid")
    return ForgeLocator(**{key: source[key] for key in required})


def _request_from_record(
    value: Any, locator: ForgeLocator, target_oid: GitObjectId
) -> tuple[RequestSpec, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("request record must be an object")
    request = RequestSpec(
        str(value.get("method", "")),
        str(value.get("url", "")),
        value.get("headers") if isinstance(value.get("headers"), dict) else {},
    )
    sanitized = assert_valid_commit_request(request, locator, target_oid)
    if sanitized != value:
        raise ValueError("request record is not in canonical sanitized form")
    return request, sanitized


def verify_public_evidence(
    evidence_dir: Path,
    expected_oids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Replay stored pages and rederive pagination/coverage without networking."""

    root = Path(evidence_dir)
    try:
        manifest = _load_manifest(root)
    except UnsafeRequestError as exc:
        reason = "unsafe_bundle_mode" if "mode must be" in str(exc) else "unsafe_bundle_member"
        return {"status": "MISMATCH", "reason": reason, "detail": str(exc)}
    except ValueError as exc:
        return {"status": "CANNOT_VERIFY", "reason": str(exc)}
    if manifest.get("schema_version") != "public-evidence-v1":
        return {"status": "MISMATCH", "reason": "schema_version_mismatch"}
    schema_errors = validate_schema("public-evidence-v1", manifest)
    if schema_errors:
        return {
            "status": "MISMATCH",
            "reason": "schema_validation_failed",
            "errors": schema_errors,
        }
    if manifest.get("bundle_payload_sha256") != _manifest_digest(manifest):
        return {"status": "MISMATCH", "reason": "manifest_digest_mismatch"}
    pages_for_inventory = manifest.get("pages")
    expected_blob_digests = (
        {
            str(page.get("body_sha256"))
            for page in pages_for_inventory
            if isinstance(page, Mapping) and isinstance(page.get("body_sha256"), str)
        }
        if isinstance(pages_for_inventory, list)
        else set()
    )
    try:
        inventory_error = _bundle_inventory_error(root, expected_blob_digests)
    except UnsafeRequestError as exc:
        return {"status": "MISMATCH", "reason": "unsafe_bundle_member", "detail": str(exc)}
    except OSError as exc:
        return {"status": "CANNOT_VERIFY", "reason": str(exc)}
    if inventory_error is not None:
        return {"status": "MISMATCH", "reason": inventory_error}
    try:
        locator = _locator_from_manifest(manifest)
        adapter = adapter_for(locator)
        target_oid = GitObjectId(**manifest["target_oid"])
        if manifest.get("provider") != locator.provider:
            return {"status": "MISMATCH", "reason": "provider_mismatch"}
        if manifest.get("api_version") != adapter.api_version:
            return {"status": "MISMATCH", "reason": "api_version_mismatch"}
        if manifest.get("account_linkage") != adapter.account_linkage:
            return {"status": "MISMATCH", "reason": "account_linkage_mismatch"}
        pages = manifest.get("pages")
        if not isinstance(pages, list):
            return {"status": "MISMATCH", "reason": "pages_invalid"}
        replay = _new_manifest(locator, target_oid, "replay")
        expected_request = assert_valid_commit_request(
            adapter.initial_request(locator, target_oid, auth_token=None),
            locator,
            target_oid,
        )
        successful_pages = 0
        item_count = 0
        for index, page in enumerate(pages, 1):
            if not isinstance(page, dict) or not isinstance(page.get("body_sha256"), str):
                return {"status": "MISMATCH", "reason": "page_record_invalid"}
            if page.get("number") != index:
                return {"status": "MISMATCH", "reason": "page_number_mismatch"}
            request, safe_request = _request_from_record(page.get("request"), locator, target_oid)
            if safe_request != expected_request:
                return {"status": "MISMATCH", "reason": "request_chain_mismatch"}
            digest = page["body_sha256"]
            try:
                body = _secure_read(root, ("blobs", "sha256", digest))
            except FileNotFoundError:
                return {"status": "CANNOT_VERIFY", "reason": "body_missing", "digest": digest}
            if _digest_bytes(body) != digest:
                return {"status": "MISMATCH", "reason": "body_digest_mismatch"}
            if page.get("body_bytes") != len(body):
                return {"status": "MISMATCH", "reason": "body_bytes_mismatch"}
            status = page.get("http_status")
            if not isinstance(status, int) or isinstance(status, bool):
                return {"status": "MISMATCH", "reason": "http_status_invalid"}
            response_headers = (
                page.get("response_headers")
                if isinstance(page.get("response_headers"), dict)
                else {}
            )
            if response_headers != _safe_response_headers(
                response_headers, provider=locator.provider
            ):
                return {"status": "MISMATCH", "reason": "response_headers_not_sanitized"}
            _validate_link_header(response_headers, locator, target_oid)
            next_record = page.get("next_request")
            if next_record is None:
                next_safe = None
            else:
                _next_request, next_safe = _request_from_record(next_record, locator, target_oid)
            if status != 200:
                if page.get("item_count") != 0 or next_safe != safe_request:
                    return {"status": "MISMATCH", "reason": "http_retry_semantics_mismatch"}
                expected_request = next_safe
                continue
            response = HttpResponse(
                status=200,
                body=body,
                headers=response_headers,
            )
            parsed = adapter.parse_page(locator, request, response)
            if page.get("item_count") != parsed.item_count:
                return {"status": "MISMATCH", "reason": "item_count_mismatch"}
            if parsed.next_url is not None:
                parsed_next = assert_valid_commit_request(
                    adapter.request_for_url(parsed.next_url, auth_token=None),
                    locator,
                    target_oid,
                )
                if next_safe != parsed_next:
                    return {"status": "MISMATCH", "reason": "page_next_request_mismatch"}
            elif next_safe is not None:
                return {"status": "MISMATCH", "reason": "page_next_request_mismatch"}
            _merge_page(replay, parsed)
            successful_pages += 1
            item_count += parsed.item_count
            expected_request = next_safe
            if next_safe is None and index != len(pages):
                return {"status": "MISMATCH", "reason": "request_chain_terminated_early"}
    except (KeyError, TypeError, ValueError, UnsafeRequestError) as exc:
        return {"status": "MISMATCH", "reason": f"replay_invalid:{exc}"}

    comparisons = {
        "commit_oids": replay["commit_oids"],
        "duplicate_commit_oids": replay["duplicate_commit_oids"],
        "sha_to_account": replay["sha_to_account"],
        "mapping_conflicts": replay["mapping_conflicts"],
        "unlinked_commit_count": replay["unlinked_commit_count"],
    }
    for key, replayed in comparisons.items():
        if manifest.get(key) != replayed:
            return {"status": "MISMATCH", "reason": f"{key}_mismatch"}
    if replay["duplicate_commit_oids"]:
        return {"status": "MISMATCH", "reason": "duplicate_commit_oids"}
    if replay["mapping_conflicts"]:
        return {"status": "MISMATCH", "reason": "sha_to_account_conflicts"}

    cursor = expected_request
    truncated = cursor is not None
    if truncated:
        coverage_status = "partial" if successful_pages else "unavailable"
        missing = ["commits_beyond_last_page" if successful_pages else "first_successful_api_page"]
    else:
        coverage_status = "complete"
        missing = []
    expected_coverage = {
        "status": coverage_status,
        "item_count": item_count,
        "missing": missing,
    }
    if manifest.get("coverage") != expected_coverage:
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}
    pagination = manifest.get("pagination")
    if not isinstance(pagination, dict):
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}
    expected_pagination = {
        "pages": len(pages),
        "per_page": 100,
        "truncated": truncated,
        "next_request": cursor,
    }
    if any(pagination.get(key) != value for key, value in expected_pagination.items()):
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}
    last_status = pages[-1].get("http_status") if pages else None
    stop_reason = pagination.get("stop_reason")
    if not truncated and stop_reason != "no_next_page":
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}
    if truncated and pages and last_status != 200 and stop_reason != f"http_{last_status}":
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}
    if (
        truncated
        and pages
        and last_status == 200
        and not (
            stop_reason == "max_pages_reached"
            or (isinstance(stop_reason, str) and stop_reason.startswith("transport_error:"))
        )
    ):
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}
    if (
        truncated
        and not pages
        and not (isinstance(stop_reason, str) and stop_reason.startswith("transport_error:"))
    ):
        return {"status": "MISMATCH", "reason": "pagination_semantics_mismatch"}

    reconciliation = None
    if expected_oids is not None:
        reconciliation = reconcile_commit_coverage(manifest, expected_oids)
        if reconciliation["status"] == "mismatch":
            return {
                "status": "MISMATCH",
                "reason": "commit_coverage_mismatch",
                "reconciliation": reconciliation,
            }
    return {
        "status": "VERIFIED",
        "coverage": coverage_status,
        "pages": len(pages),
        "bundle_payload_sha256": manifest["bundle_payload_sha256"],
        "reconciliation": reconciliation or {"status": "not_requested"},
    }


def load_public_evidence(
    evidence_dir: Path,
    expected_oids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Load a verified bundle for offline replay and account attachment."""

    result = verify_public_evidence(evidence_dir, expected_oids=expected_oids)
    if result.get("status") != "VERIFIED":
        raise ValueError(
            "public evidence cannot be replayed: "
            + str(result.get("reason") or result.get("status") or "unknown")
        )
    return _load_manifest(Path(evidence_dir))


def reconcile_commit_coverage(
    manifest: Mapping[str, Any], expected_oids: list[str] | tuple[str, ...]
) -> dict[str, Any]:
    """Compare API pages with ``git rev-list <fixed-oid>`` output.

    A declared-complete API bundle with a missing commit is a mismatch, not a
    partial success. A deliberately bounded bundle may report missing commits
    as ``partial``. Extra or duplicate API commits always indicate mismatch.
    """

    expected_rows = [value.casefold() for value in expected_oids]
    if len(expected_rows) != len(set(expected_rows)):
        raise ValueError("expected Git OID population contains duplicates")
    observed_raw = manifest.get("commit_oids")
    if not isinstance(observed_raw, list) or not all(
        isinstance(value, str) for value in observed_raw
    ):
        raise ValueError("public evidence commit_oids must be an array of strings")
    observed_rows = [value.casefold() for value in observed_raw]
    expected = set(expected_rows)
    observed = set(observed_rows)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    declared_duplicates = manifest.get("duplicate_commit_oids")
    duplicates = (
        sorted(
            set(value.casefold() for value in declared_duplicates if isinstance(value, str))
            | {value for value in observed if observed_rows.count(value) > 1}
        )
        if isinstance(declared_duplicates, list)
        else sorted(value for value in observed if observed_rows.count(value) > 1)
    )
    declared_status = (
        manifest.get("coverage", {}).get("status")
        if isinstance(manifest.get("coverage"), Mapping)
        else None
    )
    if extra or duplicates or (missing and declared_status == "complete"):
        status = "mismatch"
    elif missing or declared_status != "complete":
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "expected_count": len(expected),
        "observed_count": len(observed),
        "missing": missing,
        "extra": extra,
        "duplicates": duplicates,
    }


def _git_read(repo: Path, args: list[str], *, timeout: int = 120) -> bytes:
    environment = os.environ.copy()
    environment["GIT_NO_LAZY_FETCH"] = "1"
    result = subprocess.run(  # noqa: S603
        [
            "git",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        timeout=timeout,
        env=environment,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or f"git {' '.join(args)} failed")
    return result.stdout


def _git_optional(repo: Path, args: list[str], *, timeout: int = 30) -> bytes:
    environment = os.environ.copy()
    environment["GIT_NO_LAZY_FETCH"] = "1"
    result = subprocess.run(  # noqa: S603
        [
            "git",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        timeout=timeout,
        env=environment,
    )
    if result.returncode == 1:
        return b""
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or f"git {' '.join(args)} failed")
    return result.stdout


def resolve_fixed_target(repo: Path, revision: str) -> GitObjectId:
    """Resolve a user revision once, without checkout or lazy object fetching."""

    if not revision or "\x00" in revision:
        raise ValueError("revision must be a non-empty Git revision")
    raw = _git_read(
        Path(repo), ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"]
    )
    value = raw.decode("ascii", errors="strict").strip()
    return GitObjectId.infer(value)


def read_fixed_history_oids(repo: Path, target_oid: GitObjectId) -> list[str]:
    """Read the exact ancestry population used to reconcile Forge pagination."""

    shallow = _git_read(Path(repo), ["rev-parse", "--is-shallow-repository"])
    if shallow.decode("ascii", errors="replace").strip() == "true":
        raise ValueError("history_incomplete: shallow repository")
    partial_extension = _git_optional(Path(repo), ["config", "--get", "extensions.partialClone"])
    promisor = _git_optional(Path(repo), ["config", "--get-regexp", r"^remote\..*\.promisor$"])
    if partial_extension.strip() or promisor.strip():
        raise ValueError("history_incomplete: promisor or partial-clone repository")
    raw = _git_read(Path(repo), ["rev-list", target_oid.value])
    rows = [line.strip().casefold() for line in raw.decode("ascii").splitlines() if line.strip()]
    for value in rows:
        GitObjectId(target_oid.algorithm, value)
    return rows


def collect_revision_license_evidence(repo: Path, target_oid: GitObjectId) -> dict[str, Any]:
    """Digest root license files from the fixed Git tree, not the checkout."""

    raw_paths = _git_read(Path(repo), ["ls-tree", "-r", "-z", "--name-only", target_oid.value])
    paths = [
        value.decode("utf-8", errors="surrogateescape") for value in raw_paths.split(b"\0") if value
    ]
    selected = sorted(
        path for path in paths if "/" not in path and _LICENSE_NAME_RE.fullmatch(path)
    )
    files: list[dict[str, Any]] = []
    for path in selected:
        blob_raw = _git_read(Path(repo), ["rev-parse", "--verify", f"{target_oid.value}:{path}"])
        blob_oid = GitObjectId.infer(blob_raw.decode("ascii").strip())
        body = _git_read(Path(repo), ["cat-file", "blob", blob_oid.value])
        files.append(
            {
                "path": path,
                "blob_oid": blob_oid.to_dict(),
                "sha256": _digest_bytes(body),
                "bytes": len(body),
            }
        )
    result: dict[str, Any] = {
        "definition_version": "revision-license-v1",
        "status": "observed" if files else "not_observed",
        "target_oid": target_oid.to_dict(),
        "files": files,
        "terms_status": "separate_from_license_evidence",
    }
    result["digest"] = {
        "algorithm": "sha256",
        "value": _digest_bytes(b"tep-revision-license-v1\0" + _canonical_bytes(result)),
    }
    return result
