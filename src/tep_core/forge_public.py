"""Provider-neutral public Forge primitives.

This module describes requests and provider responses.  It deliberately does
not know about Git actor clustering: provider accounts are display evidence
attached after the repository-local actor partition has been fixed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit


class UnsafeRequestError(ValueError):
    """A request could disclose credentials or leave the selected API origin."""


class ForgeResponseError(ValueError):
    """A Forge response does not satisfy the documented response contract."""


class ForgeTruncatedBodyError(OSError):
    """A response ended before its declared ``Content-Length`` was delivered.

    This is a transport failure, not a malformed response.  GitHub's ~400 KB
    commit pages intermittently terminate early: one ``read()`` returns fewer
    bytes than ``Content-Length`` and the next returns ``b""``.  Handing those
    cut bytes to the JSON decoder reports ``Forge response body is not valid
    UTF-8 JSON``, which blames the provider for our own incomplete read.  It
    subclasses ``OSError`` so the collection loop treats it like any other
    transport error: retry a bounded number of times, then stop with
    ``transport_error:ForgeTruncatedBodyError``.
    """


_HEX_RE = re.compile(r"^[0-9a-f]+$")
_SCP_REMOTE_RE = re.compile(r"^(?:(?P<user>[^@/:]+)@)?(?P<host>\[[^]]+\]|[^/:]+):(?P<path>.+)$")
_CREDENTIAL_QUERY_KEYS = frozenset(
    {
        "access_token",
        "access-token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "client_secret",
        "key",
        "oauth_token",
        "private_token",
        "session",
        "signature",
        "token",
    }
)
_SAFE_REQUEST_HEADERS = frozenset({"accept", "if-modified-since", "if-none-match", "user-agent"})
_CREDENTIAL_PATH_MARKERS = frozenset(
    {
        "access_token",
        "access-token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "oauth_token",
        "private_token",
        "token",
    }
)
_KNOWN_TOKEN_PATH_RE = re.compile(
    r"(?:"
    r"github_pat_[A-Za-z0-9_]{8,}"
    r"|gh[pousr]_[A-Za-z0-9]{8,}"
    r"|glpat-[A-Za-z0-9_-]{8,}"
    r"|[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"
    r")",
    re.IGNORECASE,
)


def _fully_unquote(value: str) -> str:
    """Decode nested percent encoding or reject an excessive encoding chain."""

    decoded = value
    for _ in range(16):
        candidate = unquote(decoded)
        if candidate == decoded:
            return decoded
        decoded = candidate
    raise UnsafeRequestError("Forge URL component is excessively percent encoded")


@dataclass(frozen=True)
class GitObjectId:
    """A Git object identifier that does not assume SHA-1 repositories."""

    algorithm: str
    value: str

    def __post_init__(self) -> None:
        algorithm = self.algorithm.lower().replace("-", "")
        value = self.value.lower()
        expected = {"sha1": 40, "sha256": 64}.get(algorithm)
        if expected is None:
            raise ValueError("Git OID algorithm must be sha1 or sha256")
        if len(value) != expected or _HEX_RE.fullmatch(value) is None:
            raise ValueError(f"{algorithm} Git OID must be {expected} lowercase hex characters")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "value", value)

    @classmethod
    def infer(cls, value: str) -> GitObjectId:
        return cls("sha256" if len(value) == 64 else "sha1", value)

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "value": self.value}


@dataclass(frozen=True)
class ForgeLocator:
    provider: str
    host: str
    project_path: str
    api_base: str
    sanitized_remote: str

    def __post_init__(self) -> None:
        clean_api = _sanitize_api_base(self.api_base)
        if clean_api != self.api_base:
            raise ValueError("Forge API base must use its canonical HTTPS form")

    @property
    def api_origin(self) -> tuple[str, str, int | None]:
        return url_origin(self.api_base)

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "host": self.host,
            "project_path": self.project_path,
            "api_base": self.api_base,
            "sanitized_remote": self.sanitized_remote,
        }


@dataclass(frozen=True)
class PublicAccount:
    provider: str
    host: str
    account_id: str
    handle: str | None
    profile_url: str | None
    evidence: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "host": self.host,
            "account_id": self.account_id,
            "handle": self.handle,
            "profile_url": self.profile_url,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class RequestSpec:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)

    def sanitized(self) -> dict[str, Any]:
        parts = urlsplit(self.url)
        if parts.username is not None or parts.password is not None:
            raise UnsafeRequestError("request URL userinfo is forbidden")
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise UnsafeRequestError("request URL must be absolute HTTP(S)")
        if parts.fragment:
            raise UnsafeRequestError("request URL fragment is forbidden")
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        query_keys = [key for key, _value in query_pairs]
        if len(query_keys) != len(set(query_keys)):
            raise UnsafeRequestError("request URL contains a duplicate query parameter")
        for key in query_keys:
            if key.casefold() in _CREDENTIAL_QUERY_KEYS:
                raise UnsafeRequestError("request URL contains a credential query parameter")
        has_credentials = any(
            key.casefold() in {"authorization", "cookie", "private-token"} for key in self.headers
        )
        if has_credentials and parts.scheme != "https":
            raise UnsafeRequestError("authentication over cleartext HTTP is forbidden")
        safe_headers = {
            key: str(value)
            for key, value in sorted(self.headers.items(), key=lambda item: item[0].casefold())
            if key.casefold() in _SAFE_REQUEST_HEADERS
        }
        return {"method": self.method.upper(), "url": self.url, "headers": safe_headers}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedPage:
    commit_oids: tuple[str, ...]
    sha_to_account: Mapping[str, PublicAccount]
    unlinked_commit_count: int
    item_count: int
    next_url: str | None


def canonical_account_profile_url(
    *, provider: str, host: str, handle: str | None, value: str | None
) -> str | None:
    """Return one credential-free provider profile URL or ``None``.

    Provider response fields are untrusted.  A profile is display enrichment,
    so it must never carry userinfo, query parameters, fragments, a different
    host, or a provider-internal path into a public actor artifact.
    """

    if provider not in {"github", "gitlab"} or not handle or not value:
        return None
    try:
        expected = urlsplit(f"https://{host}")
        profile = urlsplit(value)
        expected_port = expected.port
        profile_port = profile.port
    except ValueError:
        return None
    if (
        not expected.hostname
        or expected.username is not None
        or expected.password is not None
        or expected.path not in {"", "/"}
        or expected.query
        or expected.fragment
        or profile.scheme != "https"
        or not profile.hostname
        or profile.username is not None
        or profile.password is not None
        or profile.query
        or profile.fragment
        or profile.hostname.casefold() != expected.hostname.casefold()
        or profile_port != expected_port
        or profile.path.casefold() != f"/{handle}".casefold()
    ):
        return None
    canonical_host = _format_host(expected.hostname.casefold(), expected_port)
    return f"https://{canonical_host}/{handle}"


class ForgeAdapter(Protocol):
    provider_id: str
    api_version: str
    account_linkage: str

    def initial_request(
        self, locator: ForgeLocator, target_oid: GitObjectId, *, auth_token: str | None
    ) -> RequestSpec: ...

    def request_for_url(self, url: str, *, auth_token: str | None) -> RequestSpec: ...

    def parse_page(
        self, locator: ForgeLocator, request: RequestSpec, response: HttpResponse
    ) -> ParsedPage: ...


def _format_host(hostname: str, port: int | None) -> str:
    base = f"[{hostname}]" if ":" in hostname else hostname
    return f"{base}:{port}" if port is not None else base


def _clean_project_path(path: str) -> str:
    text = path.strip().lstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    text = text.strip("/")
    if len([part for part in text.split("/") if part]) < 2:
        raise ValueError("Forge remote must identify a namespace and repository")
    if any(part in {".", ".."} for part in text.split("/")):
        raise ValueError("Forge project path contains traversal")
    return text


def _parse_remote(remote: str) -> tuple[str, str, str]:
    text = remote.strip()
    if not text:
        raise ValueError("Forge remote is empty")
    if "://" in text:
        parts = urlsplit(text)
        if not parts.hostname:
            raise ValueError("Forge remote has no host")
        scheme = parts.scheme.casefold()
        if scheme not in {"http", "https", "ssh", "git", "git+ssh"}:
            raise ValueError("Forge remote scheme is unsupported")
        if parts.password is not None or (
            scheme in {"http", "https"} and parts.username is not None
        ):
            raise UnsafeRequestError("Forge remote credential userinfo is forbidden")
        if parts.query or parts.fragment:
            raise UnsafeRequestError("Forge remote query and fragment are forbidden")
        host = _format_host(parts.hostname.lower(), parts.port)
        return parts.hostname.lower(), host, _clean_project_path(parts.path)
    match = _SCP_REMOTE_RE.fullmatch(text)
    if match:
        raw_host = match.group("host")
        hostname = raw_host.strip("[]").lower()
        return hostname, raw_host.lower(), _clean_project_path(match.group("path"))
    if "/" not in text:
        raise ValueError("Forge remote must contain a project path")
    host, path = text.split("/", 1)
    hostname = host.split(":", 1)[0].strip("[]").lower()
    return hostname, host.lower(), _clean_project_path(path)


def _sanitize_api_base(api_base: str) -> str:
    parts = urlsplit(api_base.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Forge API base must be an absolute HTTPS URL")
    if parts.username is not None or parts.password is not None:
        raise UnsafeRequestError("Forge API base userinfo is forbidden")
    if parts.query or parts.fragment:
        raise UnsafeRequestError("Forge API base query and fragment are forbidden")
    decoded_path = _fully_unquote(parts.path)
    path_segments = [segment for segment in decoded_path.split("/") if segment]
    if any(segment.casefold() in _CREDENTIAL_PATH_MARKERS for segment in path_segments):
        raise UnsafeRequestError("Forge API base credential path component is forbidden")
    if _KNOWN_TOKEN_PATH_RE.search(decoded_path):
        raise UnsafeRequestError("Forge API base token-shaped path component is forbidden")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def parse_forge_locator(
    remote: str,
    *,
    provider: str = "auto",
    api_base: str | None = None,
) -> ForgeLocator:
    """Parse GitHub, GitLab, and explicitly selected self-managed remotes."""

    hostname, host, project_path = _parse_remote(remote)
    selected = provider.casefold()
    if selected == "auto":
        if hostname == "github.com":
            selected = "github"
        elif hostname == "gitlab.com":
            selected = "gitlab"
        else:
            raise ValueError("provider must be explicit for a self-managed Forge host")
    if selected not in {"github", "gitlab"}:
        raise ValueError("Forge provider must be auto, github, or gitlab")

    if api_base is None:
        if hostname == "github.com" and selected == "github":
            api_base = "https://api.github.com"
        elif hostname == "gitlab.com" and selected == "gitlab":
            api_base = "https://gitlab.com/api/v4"
        else:
            raise ValueError("api_base must be explicit for a self-managed Forge host")
    clean_api = _sanitize_api_base(api_base)
    return ForgeLocator(
        provider=selected,
        host=host,
        project_path=project_path,
        api_base=clean_api,
        sanitized_remote=f"{host}/{project_path}",
    )


def url_origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    if not parts.hostname:
        raise UnsafeRequestError("request URL has no origin")
    port = parts.port
    if port is None:
        port = 443 if parts.scheme.casefold() == "https" else 80
    return parts.scheme.casefold(), parts.hostname.casefold(), port


def assert_same_origin(url: str, expected_url: str) -> None:
    if url_origin(url) != url_origin(expected_url):
        raise UnsafeRequestError("cross-origin pagination URL is forbidden")


def assert_valid_commit_request(
    request: RequestSpec,
    locator: ForgeLocator,
    target_oid: GitObjectId,
    *,
    allow_github_numeric_link: bool = False,
) -> dict[str, Any]:
    """Validate the exact provider commit endpoint and its complete query.

    Same-origin alone is not enough: a provider response could otherwise place
    arbitrary credential-like or session query values into the persisted
    request record.  Both initial and pagination requests use the same closed
    contract, including replayed/resumed records.
    """

    if request.method.upper() != "GET":
        raise UnsafeRequestError("Forge commit request method must be GET")
    assert_same_origin(request.url, locator.api_base)
    safe = request.sanitized()
    parts = urlsplit(request.url)
    base_path = urlsplit(locator.api_base).path.rstrip("/")
    if locator.provider == "github":
        project = "/".join(quote(part, safe="") for part in locator.project_path.split("/"))
        expected_path = f"{base_path}/repos/{project}/commits"
        numeric_repository_path = re.fullmatch(
            re.escape(f"{base_path}/repositories/") + r"[1-9][0-9]*/commits",
            parts.path,
        )
        reference_key = "sha"
    elif locator.provider == "gitlab":
        project = quote(locator.project_path, safe="")
        expected_path = f"{base_path}/projects/{project}/repository/commits"
        reference_key = "ref_name"
    else:  # pragma: no cover - ForgeLocator construction is already closed.
        raise UnsafeRequestError("unsupported Forge provider request")
    if parts.path != expected_path and not (
        locator.provider == "github"
        and allow_github_numeric_link
        and numeric_repository_path is not None
    ):
        raise UnsafeRequestError("Forge commit request path is not allowed")

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = [key for key, _value in pairs]
    allowed = {reference_key, "per_page", "page"}
    if len(keys) != len(set(keys)):
        raise UnsafeRequestError("Forge commit request has a duplicate query parameter")
    if set(keys) != allowed or len(keys) != len(allowed):
        raise UnsafeRequestError("Forge commit request query is not allowed")
    values = dict(pairs)
    if values[reference_key] != target_oid.value:
        raise UnsafeRequestError("Forge commit request target does not match fixed OID")
    if values["per_page"] != "100":
        raise UnsafeRequestError("Forge commit request per_page must be 100")
    if re.fullmatch(r"[1-9][0-9]*", values["page"]) is None:
        raise UnsafeRequestError("Forge commit request page must be a positive integer")
    return safe


def _headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.casefold(): str(value) for key, value in headers.items()}


def _load_rows(response: HttpResponse) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ForgeResponseError("Forge response body is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, list) or not all(isinstance(row, dict) for row in decoded):
        raise ForgeResponseError("Forge commits response must be an array of objects")
    return decoded


def _valid_commit_oid(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.casefold()
    if len(lowered) not in {40, 64} or _HEX_RE.fullmatch(lowered) is None:
        return None
    return lowered


def _link_next(value: str) -> str | None:
    for part in value.split(","):
        pieces = [piece.strip() for piece in part.split(";")]
        if any(piece.casefold() == 'rel="next"' for piece in pieces[1:]):
            candidate = pieces[0].strip()
            if candidate.startswith("<") and candidate.endswith(">"):
                return candidate[1:-1]
    return None


def _github_account_id(value: Any) -> str | None:
    """Return the closed stable-ID representation accepted from GitHub.

    GitHub documents ``author.id`` as a numeric account identifier.  JSON
    booleans are Python integers, so accepting ``int`` without an explicit
    boolean guard would silently turn ``true`` into the stable key ``True``.
    Replayed fixtures may contain the canonical decimal string, but signs,
    whitespace, zero and leading zeroes are rejected.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        return value
    return None


def _canonical_github_next_url(
    locator: ForgeLocator,
    current_request: RequestSpec,
    candidate: str,
) -> str:
    """Validate a GitHub Link target and keep pagination on the bound project.

    GitHub may emit ``/repositories/<numeric-id>/commits`` links.  The numeric
    ID is not independently bound to ``locator.project_path``, so it is never
    used as the next transport route.  Only its closed pagination query is
    retained and the next request is rebuilt on the initial owner/project
    endpoint.
    """

    current_parts = urlsplit(current_request.url)
    current_query = dict(parse_qsl(current_parts.query, keep_blank_values=True))
    raw_target = current_query.get("sha", "")
    try:
        target_oid = GitObjectId.infer(raw_target)
    except ValueError as exc:
        raise UnsafeRequestError("GitHub pagination source has an invalid fixed OID") from exc
    assert_valid_commit_request(current_request, locator, target_oid)
    assert_valid_commit_request(
        RequestSpec("GET", candidate),
        locator,
        target_oid,
        allow_github_numeric_link=True,
    )
    candidate_parts = urlsplit(candidate)
    normalized = urlunsplit(
        (
            current_parts.scheme,
            current_parts.netloc,
            current_parts.path,
            candidate_parts.query,
            "",
        )
    )
    assert_valid_commit_request(RequestSpec("GET", normalized), locator, target_oid)
    return normalized


class GitHubAdapter:
    provider_id = "github"
    api_version = "2022-11-28"
    account_linkage = "complete"

    def _headers(self, auth_token: str | None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "grift-cli-public-evidence",
            "X-GitHub-Api-Version": self.api_version,
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def initial_request(
        self, locator: ForgeLocator, target_oid: GitObjectId, *, auth_token: str | None
    ) -> RequestSpec:
        owner_repo = "/".join(quote(part, safe="") for part in locator.project_path.split("/"))
        query = urlencode({"per_page": 100, "sha": target_oid.value, "page": 1})
        return RequestSpec(
            "GET",
            f"{locator.api_base}/repos/{owner_repo}/commits?{query}",
            self._headers(auth_token),
        )

    def request_for_url(self, url: str, *, auth_token: str | None) -> RequestSpec:
        return RequestSpec("GET", url, self._headers(auth_token))

    def parse_page(
        self, locator: ForgeLocator, request: RequestSpec, response: HttpResponse
    ) -> ParsedPage:
        rows = _load_rows(response)
        commit_oids: list[str] = []
        accounts: dict[str, PublicAccount] = {}
        unlinked = 0
        for row in rows:
            sha = _valid_commit_oid(row.get("sha"))
            if sha is None:
                raise ForgeResponseError("GitHub commits response contains an invalid Git OID")
            commit_oids.append(sha)
            author = row.get("author")
            if not isinstance(author, dict):
                unlinked += 1
                continue
            account_id = _github_account_id(author.get("id"))
            if not account_id:
                unlinked += 1
                continue
            # A Bot / app installation author (``dependabot[bot]``,
            # ``renovate[bot]``, ``Copilot``) is not a person.  Its profile
            # lives under ``/apps/<slug>`` and its login carries brackets the
            # downstream intake handle contract rejects, so it can never
            # satisfy the human-account requirement in ``_account_rows``.
            # Count the commit as unlinked instead of attaching an account
            # that would abort artifact emission.
            if author.get("type") == "Bot":
                unlinked += 1
                continue
            handle = author.get("login")
            if not isinstance(handle, str) or not handle:
                handle = None
            source_host = locator.host
            if source_host.startswith("["):
                source_hostname = source_host[1:].split("]", 1)[0]
            else:
                source_hostname = source_host.split(":", 1)[0]
            raw_profile_url = author.get("html_url")
            profile_url = canonical_account_profile_url(
                provider="github",
                host=source_hostname,
                handle=handle,
                value=raw_profile_url if isinstance(raw_profile_url, str) else None,
            )
            # A public account row must carry both a handle and a canonical
            # credential-free profile URL (actor_artifacts._account_rows).
            # Attaching an account that cannot satisfy that requirement turns
            # a display gap into a hard artifact failure, so drop the linkage
            # and count the commit as unlinked.
            if handle is None or profile_url is None:
                unlinked += 1
                continue
            accounts[sha] = PublicAccount(
                provider="github",
                # The account namespace is the Forge hostname, not the clone
                # transport port.  An SSH remote may use :2222 while the same
                # account is served over HTTPS on the default port.
                host=source_hostname,
                account_id=account_id,
                handle=handle,
                profile_url=profile_url,
                evidence={"basis": "commit.author.id", "commit_oid": sha},
            )
        raw_next_url = _link_next(_headers(response.headers).get("link", ""))
        next_url = (
            _canonical_github_next_url(locator, request, raw_next_url)
            if raw_next_url is not None
            else None
        )
        return ParsedPage(
            commit_oids=tuple(commit_oids),
            sha_to_account=accounts,
            unlinked_commit_count=unlinked,
            item_count=len(rows),
            next_url=next_url,
        )


class GitLabAdapter:
    provider_id = "gitlab"
    api_version = "v4"
    account_linkage = "unsupported"

    def _headers(self, auth_token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "grift-cli-public-evidence"}
        if auth_token:
            headers["PRIVATE-TOKEN"] = auth_token
        return headers

    def initial_request(
        self, locator: ForgeLocator, target_oid: GitObjectId, *, auth_token: str | None
    ) -> RequestSpec:
        project = quote(locator.project_path, safe="")
        query = urlencode({"ref_name": target_oid.value, "per_page": 100, "page": 1})
        return RequestSpec(
            "GET",
            f"{locator.api_base}/projects/{project}/repository/commits?{query}",
            self._headers(auth_token),
        )

    def request_for_url(self, url: str, *, auth_token: str | None) -> RequestSpec:
        return RequestSpec("GET", url, self._headers(auth_token))

    def parse_page(
        self, locator: ForgeLocator, request: RequestSpec, response: HttpResponse
    ) -> ParsedPage:
        del locator
        rows = _load_rows(response)
        commit_oids_list: list[str] = []
        for row in rows:
            sha = _valid_commit_oid(row.get("id"))
            if sha is None:
                raise ForgeResponseError("GitLab commits response contains an invalid Git OID")
            commit_oids_list.append(sha)
        commit_oids = tuple(commit_oids_list)
        next_page = _headers(response.headers).get("x-next-page", "").strip()
        next_url = None
        if next_page:
            parts = urlsplit(request.url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query["page"] = next_page
            next_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        return ParsedPage(
            commit_oids=commit_oids,
            sha_to_account={},
            unlinked_commit_count=len(commit_oids),
            item_count=len(rows),
            next_url=next_url,
        )


def adapter_for(locator: ForgeLocator) -> ForgeAdapter:
    if locator.provider == "github":
        return GitHubAdapter()
    if locator.provider == "gitlab":
        return GitLabAdapter()
    raise ValueError(f"unsupported Forge provider: {locator.provider}")
