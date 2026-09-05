"""Opt-in public Forge collection with a compatibility projection.

The public API is collected under the provider's API terms. ``robots.txt`` is
an HTML-crawler control and is intentionally not consulted on this REST path.
Actor clustering must be completed before the returned account display
evidence is attached.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tep_core.digest import sha256_text
from tep_core.forge_public import (
    GitObjectId,
    HttpResponse,
    RequestSpec,
    UnsafeRequestError,
    parse_forge_locator,
)
from tep_core.gitutil import normalize_remote
from tep_core.public_evidence import collect_public_evidence, load_public_evidence

Transport = Callable[[str], tuple[int, str, dict[str, str]]]
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _safe_remote_hint(remote: str | None) -> str | None:
    if not remote:
        return None
    text = remote.strip()
    if "://" in text:
        parts = urlsplit(text)
        if parts.hostname:
            host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
            if parts.port is not None:
                host = f"{host}:{parts.port}"
            path = parts.path.strip("/")
            if path.endswith(".git"):
                path = path[:-4]
            return f"{host.casefold()}/{path}" if path else host.casefold()
    text = text.split("?", 1)[0].split("#", 1)[0]
    text = re.sub(r"^[^/@]+@", "", text)
    normalized = normalize_remote(text)
    if normalized and "@" in normalized.split("/", 1)[0]:
        normalized = normalized.split("@", 1)[1]
    return normalized


def parse_robots(text: str, user_agent: str = "*") -> dict[str, list[str]]:
    """Parse legacy crawler policy fixtures; REST collection never calls it."""

    allowed: list[str] = []
    disallowed: list[str] = []
    applies = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            applies = agent == "*" or agent.lower() == user_agent.lower()
            continue
        if not applies:
            continue
        if line.lower().startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                disallowed.append(path)
        elif line.lower().startswith("allow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                allowed.append(path)
    return {"allow": allowed, "disallow": disallowed}


def path_allowed(rules: dict[str, list[str]], path: str) -> bool:
    """Apply RFC-9309 longest-match semantics to legacy crawler fixtures."""

    matches: list[tuple[int, bool]] = []
    for allowed in rules.get("allow") or []:
        if allowed and path.startswith(allowed):
            matches.append((len(allowed), True))
    for disallowed in rules.get("disallow") or []:
        if disallowed and path.startswith(disallowed):
            matches.append((len(disallowed), False))
    if not matches:
        return True
    longest = max(length for length, _allowed in matches)
    return any(allowed for length, allowed in matches if length == longest)


def empty_manifest(*, reason: str, remote: str | None) -> dict[str, Any]:
    """Return a deterministic compatibility manifest for an absent fetch."""

    status = {
        "fetch_not_requested": "not_requested",
        "unsupported_host": "unsupported",
        "remote_not_repo": "unsupported",
    }.get(reason, "unavailable")
    return {
        "schema_version": "public-evidence-v1",
        "source_url": remote,
        "source_type": "none",
        "provider": None,
        "fetched_at": None,
        "as_of": None,
        "http_status": None,
        "robots_status": reason,
        "license_status": "not_observed",
        "terms_status": "not_observed",
        "response_digest": None,
        "page_digests": [],
        "pagination": {
            "pages": 0,
            "per_page": 100,
            "truncated": status == "unavailable",
            "stop_reason": reason,
            "unfetched_range": "no public fetch attempted",
        },
        "target_commit_sha": None,
        "target_oid": None,
        "coverage": {"status": status, "item_count": 0, "missing": ["public_fetch"]},
        "skipped": [reason],
        "handles": {},
        "sha_to_login": {},
        "sha_to_account": {},
        "account_linkage": "not_requested",
        "fetched_login_count": 0,
        "commit_login_count": 0,
        "join": {
            "matched": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "bot": 0,
            "email_unlinked": 0,
            "non_default_branch": 0,
        },
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _read_request(request: RequestSpec, timeout: int = 10) -> HttpResponse:
    request.sanitized()
    native = Request(request.url, headers=dict(request.headers), method=request.method)
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(native, timeout=timeout) as response:  # noqa: S310
            headers = {key: str(value) for key, value in response.headers.items()}
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ValueError("Forge response exceeds the per-page byte limit")
            return HttpResponse(response.status, body, headers)
    except HTTPError as exc:
        body = exc.read(_MAX_RESPONSE_BYTES + 1) if exc.fp else b""
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("Forge response exceeds the per-page byte limit") from exc
        headers = {key: str(value) for key, value in (exc.headers or {}).items()}
        return HttpResponse(exc.code, body, headers)


def _adapt_transport(reader: Transport | None) -> Callable[[RequestSpec], HttpResponse]:
    if reader is None:
        return _read_request

    def adapted(request: RequestSpec) -> HttpResponse:
        status, body, headers = reader(request.url)
        return HttpResponse(
            status=int(status),
            body=body.encode("utf-8") if isinstance(body, str) else bytes(body),
            headers={key: str(value) for key, value in headers.items()},
        )

    return adapted


def _cas_account_projection(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], int]:
    """Derive legacy display fields solely from verified commit/account CAS data."""

    if manifest.get("provider") != "github":
        return {}, {}, 0
    sha_to_login: dict[str, str] = {}
    handles: dict[str, str] = {}
    stable_accounts: set[tuple[str, str, str]] = set()
    mapping = manifest.get("sha_to_account")
    if not isinstance(mapping, Mapping):
        return sha_to_login, handles, 0
    for oid, raw in sorted(mapping.items()):
        rows = raw if isinstance(raw, list) else [raw]
        valid: list[tuple[tuple[str, str, str], str]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            provider = str(row.get("provider") or "")
            host = str(row.get("host") or "")
            account_id = str(row.get("account_id") or "")
            handle = str(row.get("handle") or "")
            if provider != "github" or not all((host, account_id, handle)):
                continue
            key = (provider, host, account_id)
            valid.append((key, handle))
            stable_accounts.add(key)
            handles[handle.casefold()] = handle
        unique = {(key, handle) for key, handle in valid}
        if len(unique) == 1:
            sha_to_login[str(oid).casefold()] = next(iter(unique))[1]
    return sha_to_login, handles, len(stable_accounts)


def _compatibility_projection(
    evidence: dict[str, Any],
    *,
    head_sha: str | None,
) -> dict[str, Any]:
    sha_to_login, handles, stable_account_count = _cas_account_projection(evidence)
    pages = [
        {
            "url": page.get("request", {}).get("url"),
            "http_status": page.get("http_status"),
            "digest": page.get("body_sha256"),
            "item_count": page.get("item_count"),
        }
        for page in evidence.get("pages", [])
        if isinstance(page, dict)
    ]
    coverage = dict(evidence.get("coverage") or {})
    missing = list(coverage.get("missing") or [])
    if evidence.get("pagination", {}).get("truncated"):
        missing.append("sha_to_login_beyond_last_page")
    coverage["missing"] = sorted(set(missing))
    digests = [page["digest"] for page in pages if isinstance(page.get("digest"), str)]
    http_status = (
        evidence.get("pages", [{}])[-1].get("http_status") if evidence.get("pages") else None
    )
    pagination = dict(evidence.get("pagination") or {})
    pagination["unfetched_range"] = (
        "commits beyond the last fetched page are not in sha_to_login"
        if pagination.get("truncated")
        else None
    )
    return {
        **evidence,
        "source_url": (evidence.get("source") or {}).get("sanitized_remote"),
        "source_type": "forge_api",
        "target_commit_sha": head_sha,
        "as_of": str(evidence.get("fetched_at") or "")[:10] or None,
        "http_status": http_status,
        "robots_status": "not_applicable",
        "license_status": "not_observed",
        "terms_status": "not_observed",
        "response_digest": sha256_text(json.dumps(digests, sort_keys=True)),
        "page_digests": pages,
        "pagination": pagination,
        "coverage": coverage,
        "skipped": [],
        "handles": handles,
        "sha_to_login": sha_to_login,
        "fetched_login_count": None,
        "commit_login_count": stable_account_count,
        "join": {
            "matched": len(sha_to_login),
            "unmatched": int(evidence.get("unlinked_commit_count") or 0),
            "ambiguous": len(evidence.get("mapping_conflicts") or []),
            "bot": 0,
            "email_unlinked": int(evidence.get("unlinked_commit_count") or 0),
            "non_default_branch": 0,
        },
    }


def load_public_handles(evidence_dir: Path) -> dict[str, Any]:
    """Replay the exact live compatibility projection without any network call."""

    evidence = load_public_evidence(evidence_dir)
    target = evidence.get("target_oid")
    head_sha = str(target.get("value")) if isinstance(target, Mapping) else None
    return _compatibility_projection(evidence, head_sha=head_sha)


def collect_public_handles(
    remote: str | None,
    *,
    fetch: bool,
    head_sha: str | None = None,
    transport: Transport | None = None,
    max_pages: int = 100,
    provider: str = "auto",
    api_base: str | None = None,
    auth_token: str | None = None,
    evidence_out: Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Collect public commit evidence and expose report-v1 compatibility keys."""

    normalized = _safe_remote_hint(remote)
    if not fetch:
        return empty_manifest(reason="fetch_not_requested", remote=normalized)
    if not remote:
        return empty_manifest(reason="remote_not_repo", remote=None)
    try:
        locator = parse_forge_locator(remote, provider=provider, api_base=api_base)
    except UnsafeRequestError:
        raise
    except ValueError:
        return empty_manifest(reason="unsupported_host", remote=normalized)

    # v0.6 callers pass a full fixed OID. Historical synthetic tests used the
    # symbolic string "abc"; keep that helper path non-networking-compatible.
    try:
        target_oid = GitObjectId.infer(head_sha or "")
    except ValueError:
        if transport is None:
            raise ValueError("public fetch requires a full fixed Git OID") from None
        target_oid = GitObjectId("sha1", "0" * 40)
    if transport is None and evidence_out is None:
        raise ValueError("live public fetch requires a durable evidence_out directory")
    reader = _adapt_transport(transport)

    def run(root: Path) -> dict[str, Any]:
        evidence = collect_public_evidence(
            locator,
            target_oid,
            transport=reader,
            evidence_dir=root,
            max_pages=max_pages,
            auth_token=auth_token,
            resume=resume,
        )
        return _compatibility_projection(
            evidence,
            head_sha=head_sha,
        )

    if evidence_out is not None:
        return run(Path(evidence_out))
    with tempfile.TemporaryDirectory(prefix="grift-public-evidence-") as temporary:
        return run(Path(temporary))
