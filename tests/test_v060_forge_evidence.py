"""Falsification tests for provider-neutral public Forge evidence."""

from __future__ import annotations

import json
import hashlib
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.forge_public import (
    GitObjectId,
    HttpResponse,
    RequestSpec,
    UnsafeRequestError,
    assert_valid_commit_request,
    parse_forge_locator,
)
from tep_core.public_evidence import (
    collect_public_evidence,
    collect_revision_license_evidence,
    load_public_evidence,
    not_requested_manifest,
    read_fixed_history_oids,
    reconcile_commit_coverage,
    resolve_fixed_target,
    verify_public_evidence,
)
from tep_core.public_fetch import collect_public_handles, load_public_handles
from tep_core.public_fetch import _read_request


def test_locator_is_provider_neutral_and_strips_credentials() -> None:
    github = parse_forge_locator("git@github.com:Acme/widget.git")
    assert github.provider == "github"
    assert github.host == "github.com"
    assert github.project_path == "Acme/widget"
    assert github.sanitized_remote == "github.com/Acme/widget"

    gitlab = parse_forge_locator(
        "https://gitlab.example.test:8443/group/sub/repo.git",
        provider="gitlab",
        api_base="https://gitlab.example.test:8443/api/v4",
    )
    assert gitlab.provider == "gitlab"
    assert gitlab.host == "gitlab.example.test:8443"
    assert gitlab.project_path == "group/sub/repo"
    assert gitlab.api_base == "https://gitlab.example.test:8443/api/v4"

    ipv6 = parse_forge_locator(
        "ssh://git@[2001:db8::7]:2222/group/repo.git",
        provider="gitlab",
        api_base="https://[2001:db8::7]:8443/api/v4",
    )
    assert ipv6.host == "[2001:db8::7]:2222"
    assert ipv6.project_path == "group/repo"


@pytest.mark.parametrize(
    "remote",
    [
        "https://token@github.com/acme/widget.git",
        "https://alice:secret@github.com/acme/widget.git",
        "ssh://git:secret@github.com/acme/widget.git",
    ],
)
def test_live_forge_locator_rejects_credential_userinfo(remote: str) -> None:
    with pytest.raises(UnsafeRequestError, match="credential userinfo"):
        parse_forge_locator(remote)


def test_locator_does_not_guess_self_managed_provider() -> None:
    with pytest.raises(ValueError, match="provider must be explicit"):
        parse_forge_locator("ssh://git@forge.example.test/group/repo.git")


def test_locator_requires_https_api_base() -> None:
    with pytest.raises(ValueError, match="absolute HTTPS"):
        parse_forge_locator(
            "git@forge.example.test:acme/widget.git",
            provider="github",
            api_base="http://forge.example.test/api/v3",
        )


@pytest.mark.parametrize(
    ("remote", "provider", "api_base"),
    [
        ("github.com/acme/widget", "github", None),
        (
            "git@gitlab.example.test:group/widget.git",
            "gitlab",
            "https://gitlab.example.test/api/v4",
        ),
    ],
)
def test_public_evidence_keeps_sha256_oid_generic_across_providers(
    tmp_path: Path,
    remote: str,
    provider: str,
    api_base: str | None,
) -> None:
    locator = parse_forge_locator(remote, provider=provider, api_base=api_base)
    target = GitObjectId("sha256", "a" * 64)
    observed = "1" * 64

    def transport(request: RequestSpec) -> HttpResponse:
        reference_key = "sha" if provider == "github" else "ref_name"
        assert f"{reference_key}={target.value}" in request.url
        row = {"sha": observed, "author": None} if provider == "github" else {"id": observed}
        return HttpResponse(status=200, body=json.dumps([row]).encode(), headers={})

    bundle = tmp_path / provider
    manifest = collect_public_evidence(
        locator,
        target,
        transport=transport,
        evidence_dir=bundle,
    )
    assert manifest["target_oid"] == {"algorithm": "sha256", "value": target.value}
    assert manifest["commit_oids"] == [observed]
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


def test_request_manifest_rejects_url_credentials_and_token_query() -> None:
    with pytest.raises(UnsafeRequestError, match="userinfo"):
        RequestSpec("GET", "https://user:secret@api.github.com/repos/a/b").sanitized()
    with pytest.raises(UnsafeRequestError, match="credential query"):
        RequestSpec(
            "GET", "https://api.github.com/repos/a/b?per_page=100&access_token=secret"
        ).sanitized()
    for key in ("access-token", "authorization", "session"):
        with pytest.raises(UnsafeRequestError, match="credential query"):
            RequestSpec(
                "GET", f"https://api.github.com/repos/a/b?per_page=100&{key}=secret"
            ).sanitized()
    with pytest.raises(UnsafeRequestError, match="duplicate query"):
        RequestSpec(
            "GET", "https://api.github.com/repos/a/b?per_page=100&page=1&page=2"
        ).sanitized()
    with pytest.raises(UnsafeRequestError, match="fragment"):
        RequestSpec(
            "GET", "https://api.github.com/repos/a/b?per_page=100#session-secret"
        ).sanitized()

    safe = RequestSpec(
        "GET",
        "https://api.github.com/repos/a/b?per_page=100",
        headers={"Authorization": "Bearer secret", "Accept": "application/json"},
    ).sanitized()
    assert safe["headers"] == {"Accept": "application/json"}
    assert "secret" not in json.dumps(safe)
    with pytest.raises(UnsafeRequestError, match="cleartext"):
        RequestSpec(
            "GET",
            "http://forge.example.test/api/v4/projects/1",
            headers={"PRIVATE-TOKEN": "secret"},
        ).sanitized()


@pytest.mark.parametrize(
    "path",
    [
        "/api/token/v1",
        "/api/%74oken/v1",
        "/api/%2574oken/v1",
        "/api/ghp_1234567890abcdef/v1",
        "/api/glpat-1234567890abcdef/v1",
    ],
)
def test_api_base_rejects_credential_shaped_path(path: str) -> None:
    with pytest.raises(UnsafeRequestError, match="credential path|token-shaped path"):
        parse_forge_locator(
            "git@forge.example.test:acme/widget.git",
            provider="github",
            api_base="https://forge.example.test" + path,
        )


def test_collection_rejects_actual_runtime_token_in_api_path_before_transport(
    tmp_path: Path,
) -> None:
    token = "opaque-runtime-secret"
    locator = parse_forge_locator(
        "git@forge.example.test:acme/widget.git",
        provider="github",
        api_base=f"https://forge.example.test/api/{token}",
    )
    calls = 0

    def must_not_run(_request: RequestSpec) -> HttpResponse:
        nonlocal calls
        calls += 1
        return HttpResponse(status=200, body=b"[]", headers={})

    bundle = tmp_path / "token-path-bundle"
    with pytest.raises(UnsafeRequestError, match="token in request URL"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=must_not_run,
            evidence_dir=bundle,
            auth_token=token,
        )
    assert calls == 0
    assert not bundle.exists()


def test_collection_rejects_nested_encoded_runtime_token_before_transport(
    tmp_path: Path,
) -> None:
    token = "opaque/runtime-secret"
    encoded_token = token.replace("/", "%252F")
    locator = parse_forge_locator(
        "git@forge.example.test:acme/widget.git",
        provider="github",
        api_base=f"https://forge.example.test/api/{encoded_token}",
    )
    calls = 0

    def must_not_run(_request: RequestSpec) -> HttpResponse:
        nonlocal calls
        calls += 1
        return HttpResponse(status=200, body=b"[]", headers={})

    with pytest.raises(UnsafeRequestError, match="token in request URL"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=must_not_run,
            evidence_dir=tmp_path / "nested-token-path-bundle",
            auth_token=token,
        )
    assert calls == 0


def test_default_transport_never_follows_redirect() -> None:
    target_headers: list[str | None] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            target_headers.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, _format: str, *args: object) -> None:
            del args

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target.server_address[1]}/credential-sink",
            )
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            del args

    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    try:
        response = _read_request(
            RequestSpec(
                "GET",
                f"http://127.0.0.1:{source.server_address[1]}/redirect",
            ),
        )
        assert response.status == 302
        assert target_headers == []
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()


def test_collection_rejects_response_that_echoes_runtime_token(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b'{"debug":"runtime-secret"}', headers={})

    with pytest.raises(UnsafeRequestError, match="echoed authentication token"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=tmp_path / "bundle",
            auth_token="runtime-secret",
        )


def test_collection_rejects_header_that_echoes_runtime_token(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=b"[]",
            headers={"ETag": '"runtime-secret"'},
        )

    with pytest.raises(UnsafeRequestError, match="headers echoed authentication token"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=tmp_path / "bundle",
            auth_token="runtime-secret",
        )


def test_github_cas_bundle_uses_stable_account_id_and_mode_0600(tmp_path: Path) -> None:
    locator = parse_forge_locator("https://github.com/acme/widget.git")
    oid = GitObjectId("sha1", "a" * 40)
    seen: list[RequestSpec] = []

    def transport(request: RequestSpec) -> HttpResponse:
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer runtime-secret"
        body = json.dumps(
            [
                {
                    "sha": "1" * 40,
                    "author": {
                        "id": 42,
                        "node_id": "MDQ6VXNlcjQy",
                        "login": "Alice-New-Handle",
                        "html_url": "https://github.com/Alice-New-Handle",
                    },
                },
                {"sha": "2" * 40, "author": None},
            ]
        )
        return HttpResponse(
            status=200,
            body=body.encode(),
            headers={"ETag": '"page-1"', "X-RateLimit-Remaining": "59"},
        )

    bundle = tmp_path / "evidence"
    manifest = collect_public_evidence(
        locator,
        oid,
        transport=transport,
        evidence_dir=bundle,
        auth_token="runtime-secret",
        fetched_at="2026-08-31T00:00:00Z",
    )

    assert manifest["coverage"]["status"] == "complete"
    assert manifest["account_linkage"] == "complete"
    account = manifest["sha_to_account"]["1" * 40]
    assert account["account_id"] == "42"
    assert account["handle"] == "Alice-New-Handle"
    assert manifest["unlinked_commit_count"] == 1
    assert "runtime-secret" not in (bundle / "manifest.json").read_text()
    blob = bundle / "blobs" / "sha256" / manifest["pages"][0]["body_sha256"]
    assert stat.S_IMODE(blob.stat().st_mode) == 0o600
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"
    assert load_public_evidence(bundle)["sha_to_account"] == manifest["sha_to_account"]
    assert seen and "sha=" + ("a" * 40) in seen[0].url


def test_github_node_id_without_top_level_author_id_is_not_account_evidence(
    tmp_path: Path,
) -> None:
    locator = parse_forge_locator("https://github.com/acme/widget.git")

    def transport(_request: RequestSpec) -> HttpResponse:
        body = json.dumps(
            [
                {
                    "sha": "1" * 40,
                    "author": {
                        "node_id": "MDQ6VXNlcjQy",
                        "login": "alice",
                        "html_url": "https://github.com/alice",
                    },
                }
            ]
        )
        return HttpResponse(status=200, body=body.encode(), headers={})

    bundle = tmp_path / "node-id-is-not-evidence"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )

    assert manifest["sha_to_account"] == {}
    assert manifest["unlinked_commit_count"] == 1
    assert "commit.author.node_id" not in (bundle / "manifest.json").read_text(encoding="utf-8")
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


@pytest.mark.parametrize(
    "account_id",
    [True, False, 0, -1, "", "0", "01", "+1", " 1 ", "alice", 1.0],
)
def test_github_author_id_requires_positive_canonical_decimal(
    tmp_path: Path, account_id: object
) -> None:
    locator = parse_forge_locator("https://github.com/acme/widget.git")

    def transport(_request: RequestSpec) -> HttpResponse:
        body = json.dumps([{"sha": "1" * 40, "author": {"id": account_id, "login": "alice"}}])
        return HttpResponse(status=200, body=body.encode(), headers={})

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=tmp_path / "invalid-stable-account-id",
    )
    assert manifest["sha_to_account"] == {}
    assert manifest["unlinked_commit_count"] == 1


@pytest.mark.parametrize("account_id", [42, "42"])
def test_github_author_id_accepts_canonical_positive_decimal(
    tmp_path: Path, account_id: object
) -> None:
    locator = parse_forge_locator("https://github.com/acme/widget.git")

    def transport(_request: RequestSpec) -> HttpResponse:
        body = json.dumps([{"sha": "1" * 40, "author": {"id": account_id, "login": "alice"}}])
        return HttpResponse(status=200, body=body.encode(), headers={})

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=tmp_path / "valid-stable-account-id",
    )
    assert manifest["sha_to_account"]["1" * 40]["account_id"] == "42"


def test_self_managed_github_account_uses_web_host_not_ssh_port(tmp_path: Path) -> None:
    locator = parse_forge_locator(
        "ssh://git@ghe.example.test:2222/acme/widget.git",
        provider="github",
        api_base="https://ghe.example.test/api/v3",
    )

    def transport(_request: RequestSpec) -> HttpResponse:
        body = json.dumps(
            [
                {
                    "sha": "1" * 40,
                    "author": {
                        "id": 42,
                        "login": "alice",
                        "html_url": "https://ghe.example.test/alice",
                    },
                }
            ]
        )
        return HttpResponse(status=200, body=body.encode(), headers={})

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=tmp_path / "ghes",
    )
    account = manifest["sha_to_account"]["1" * 40]
    assert account["host"] == "ghe.example.test"
    assert account["profile_url"] == "https://ghe.example.test/alice"


@pytest.mark.parametrize(
    "unsafe_profile",
    [
        "https://github.com/alice?access_token=super-secret",
        "https://github.com/alice#access_token=super-secret",
        "https://github.com/alice?tab=repositories#profile",
        "https://credential@github.com/alice",
        "https://github.com.evil.example/alice",
        "https://github.com/alice/settings",
        "https://github.com/alice/",
        "http://github.com/alice",
    ],
)
def test_github_profile_url_rejects_credentials_and_noncanonical_locations(
    tmp_path: Path, unsafe_profile: str
) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        body = json.dumps(
            [
                {
                    "sha": "1" * 40,
                    "author": {
                        "id": 42,
                        "login": "alice",
                        "html_url": unsafe_profile,
                    },
                }
            ]
        )
        return HttpResponse(status=200, body=body.encode(), headers={})

    bundle = tmp_path / "profile-bundle"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )
    account = manifest["sha_to_account"]["1" * 40]
    assert account["account_id"] == "42"
    assert account["profile_url"] is None
    manifest_text = (bundle / "manifest.json").read_text(encoding="utf-8")
    assert "super-secret" not in manifest_text
    assert "credential@" not in manifest_text
    assert "github.com.evil.example" not in manifest_text


def test_cross_origin_github_next_link_is_rejected(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=b"[]",
            headers={
                "Link": '<https://evil.example/steal?token=secret>; rel="next"',
            },
        )

    with pytest.raises(UnsafeRequestError, match="cross-origin"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=tmp_path / "cross-origin-bundle",
        )
    assert not (tmp_path / "cross-origin-bundle").exists()


def test_cross_origin_non_next_link_is_also_rejected(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=b"[]",
            headers={"Link": '<https://evil.example/steal>; rel="last"'},
        )

    with pytest.raises(UnsafeRequestError, match="cross-origin"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=tmp_path / "cross-origin-non-next",
        )
    assert not (tmp_path / "cross-origin-non-next").exists()


def test_collection_refuses_symlink_parent_without_writing_outside(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b"[]", headers={})

    with pytest.raises(UnsafeRequestError, match="must not traverse a symlink"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=linked_parent / "bundle",
        )
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "unknown_key",
    ["access-token", "authorization", "session", "arbitrary-unknown"],
)
def test_github_pagination_rejects_unknown_query_keys_before_manifest_write(
    tmp_path: Path, unknown_key: str
) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    calls = 0

    def transport(_request: RequestSpec) -> HttpResponse:
        nonlocal calls
        calls += 1
        link = (
            "https://api.github.com/repos/acme/widget/commits?"
            f"sha={oid.value}&per_page=100&page=2&{unknown_key}=secret"
        )
        return HttpResponse(
            status=200,
            body=b"[]",
            headers={"Link": f'<{link}>; rel="next"'},
        )

    bundle = tmp_path / f"unknown-{unknown_key}"
    with pytest.raises(UnsafeRequestError, match="credential query parameter|query is not allowed"):
        collect_public_evidence(
            locator,
            oid,
            transport=transport,
            evidence_dir=bundle,
        )
    assert calls == 1
    assert not (bundle / "manifest.json").exists()


def test_github_pagination_rejects_duplicate_query_key_and_wrong_path(
    tmp_path: Path,
) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    suffixes = (
        f"repos/acme/widget/commits?sha={oid.value}&per_page=100&page=2&page=3",
        f"repos/acme/widget/issues?sha={oid.value}&per_page=100&page=2",
    )
    expected_errors = ("duplicate query", "path is not allowed")
    for index, (suffix, expected_error) in enumerate(zip(suffixes, expected_errors)):
        bundle = tmp_path / f"closed-path-{index}"

        def transport(_request: RequestSpec, *, value: str = suffix) -> HttpResponse:
            return HttpResponse(
                status=200,
                body=b"[]",
                headers={"Link": f'<https://api.github.com/{value}>; rel="next"'},
            )

        with pytest.raises(UnsafeRequestError, match=expected_error):
            collect_public_evidence(
                locator,
                oid,
                transport=transport,
                evidence_dir=bundle,
            )
        assert not (bundle / "manifest.json").exists()


def test_github_numeric_link_is_never_used_as_transport_route(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    numeric = (
        f"https://api.github.com/repositories/999999/commits?sha={oid.value}&per_page=100&page=2"
    )
    with pytest.raises(UnsafeRequestError, match="path is not allowed"):
        assert_valid_commit_request(RequestSpec("GET", numeric), locator, oid)

    seen: list[str] = []

    def transport(request: RequestSpec) -> HttpResponse:
        seen.append(request.url)
        if len(seen) == 1:
            return HttpResponse(
                status=200,
                body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
                headers={"Link": f'<{numeric}>; rel="next"'},
            )
        return HttpResponse(status=200, body=b"[]", headers={})

    bundle = tmp_path / "numeric-link-normalized"
    manifest = collect_public_evidence(
        locator,
        oid,
        transport=transport,
        evidence_dir=bundle,
    )
    assert len(seen) == 2
    assert "/repositories/" not in seen[1]
    assert "/repos/acme/widget/commits" in seen[1]
    assert manifest["pages"][0]["next_request"]["url"] == seen[1]
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


def test_cas_rejects_symlinked_blob_directory(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    bundle = tmp_path / "bundle"
    outside = tmp_path / "outside"
    bundle.mkdir()
    bundle.chmod(0o700)
    outside.mkdir()
    (bundle / "blobs").symlink_to(outside, target_is_directory=True)

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b"[]", headers={})

    with pytest.raises(UnsafeRequestError, match="symlink|non-directory"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=bundle,
        )
    assert list(outside.iterdir()) == []


def test_partial_bundle_resumes_without_refetching_first_page(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    bundle = tmp_path / "bundle"
    first_calls: list[str] = []

    def first_transport(request: RequestSpec) -> HttpResponse:
        first_calls.append(request.url)
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={
                "Link": (
                    "<https://api.github.com/repos/acme/widget/commits?"
                    "sha=" + ("a" * 40) + '&per_page=100&page=2>; rel="next"'
                )
            },
        )

    partial = collect_public_evidence(
        locator,
        oid,
        transport=first_transport,
        evidence_dir=bundle,
        max_pages=1,
        fetched_at="2026-08-31T00:00:00Z",
    )
    assert partial["coverage"]["status"] == "partial"
    assert partial["pagination"]["stop_reason"] == "max_pages_reached"
    assert len(first_calls) == 1

    resumed_calls: list[str] = []

    def resumed_transport(request: RequestSpec) -> HttpResponse:
        resumed_calls.append(request.url)
        assert "page=2" in request.url
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "2" * 40, "author": None}]).encode(),
            headers={},
        )

    complete = collect_public_evidence(
        locator,
        oid,
        transport=resumed_transport,
        evidence_dir=bundle,
        resume=True,
        fetched_at="2026-08-31T00:01:00Z",
    )
    assert complete["coverage"]["status"] == "complete"
    assert complete["commit_oids"] == ["1" * 40, "2" * 40]
    assert len(complete["pages"]) == 2
    assert len(resumed_calls) == 1
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


def test_repo_and_actor_return_partial_exit_three_until_bundle_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "partial-cli-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "fixture@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/widget.git"],
        check=True,
    )
    for index in range(2):
        (repo / "app.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", f"commit {index}"],
            check=True,
        )
    history = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    head, parent = history
    locator = parse_forge_locator("https://github.com/acme/widget.git")
    oid = GitObjectId("sha1", head)
    next_url = f"https://api.github.com/repos/acme/widget/commits?sha={head}&per_page=100&page=2"

    def first_page(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": head, "author": None}]).encode("utf-8"),
            headers={"Link": f'<{next_url}>; rel="next"'},
        )

    bundle = tmp_path / "partial-cli-evidence"
    manifest = collect_public_evidence(
        locator,
        oid,
        transport=first_page,
        evidence_dir=bundle,
        max_pages=1,
    )
    assert manifest["coverage"]["status"] == "partial"

    shared = [str(repo), "--rev", head, "--public-evidence", str(bundle), "--format", "json"]
    assert main(["repo", *shared]) == 3
    assert json.loads(capsys.readouterr().out)["subject"]["kind"] == "repo"
    assert main(["actor", "--all", *shared]) == 3
    assert json.loads(capsys.readouterr().out)["schema_version"] == "actor-index-v1"

    def second_page(request: RequestSpec) -> HttpResponse:
        assert "page=2" in request.url
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": parent, "author": None}]).encode("utf-8"),
            headers={},
        )

    resumed = collect_public_evidence(
        locator,
        oid,
        transport=second_page,
        evidence_dir=bundle,
        resume=True,
    )
    assert resumed["coverage"] == {"status": "complete", "item_count": 2, "missing": []}
    assert main(["repo", *shared]) == 0
    assert json.loads(capsys.readouterr().out)["subject"]["kind"] == "repo"


def _rewrite_manifest_with_self_digest(bundle: Path, manifest: dict) -> None:
    payload = dict(manifest)
    payload.pop("bundle_payload_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    manifest["bundle_payload_sha256"] = hashlib.sha256(encoded).hexdigest()
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_verify_rederives_partial_semantics_not_just_manifest_self_digest(
    tmp_path: Path,
) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    bundle = tmp_path / "bundle"

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={
                "Link": (
                    "<https://api.github.com/repos/acme/widget/commits?sha="
                    + ("a" * 40)
                    + '&per_page=100&page=2>; rel="next"'
                )
            },
        )

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
        max_pages=1,
    )
    assert manifest["coverage"]["status"] == "partial"
    manifest["coverage"] = {"status": "complete", "item_count": 1, "missing": []}
    manifest["pagination"].update(
        {"truncated": False, "stop_reason": "no_next_page", "next_request": None}
    )
    _rewrite_manifest_with_self_digest(bundle, manifest)
    assert verify_public_evidence(bundle) == {
        "status": "MISMATCH",
        "reason": "pagination_semantics_mismatch",
    }


def test_verify_rejects_cross_origin_link_on_non_success_page(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    bundle = tmp_path / "bundle"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=lambda _request: HttpResponse(status=429, body=b"{}", headers={}),
        evidence_dir=bundle,
    )
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"
    manifest["pages"][0]["response_headers"] = {
        "link": '<https://evil.example/steal?token=secret>; rel="next"'
    }
    _rewrite_manifest_with_self_digest(bundle, manifest)
    result = verify_public_evidence(bundle)
    assert result["status"] == "MISMATCH"
    assert "cross-origin" in result["reason"]


def test_verify_rederives_github_next_link_from_stored_header(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    bundle = tmp_path / "bundle"

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={
                "Link": (
                    "<https://api.github.com/repos/acme/widget/commits?sha="
                    + ("a" * 40)
                    + '&per_page=100&page=2>; rel="next"'
                )
            },
        )

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
        max_pages=1,
    )
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"
    manifest["pages"][0]["response_headers"].pop("link")
    _rewrite_manifest_with_self_digest(bundle, manifest)
    assert verify_public_evidence(bundle) == {
        "status": "MISMATCH",
        "reason": "page_next_request_mismatch",
    }


def test_duplicate_provider_commit_downgrades_and_fails_verify(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        row = {"sha": "1" * 40, "author": None}
        return HttpResponse(status=200, body=json.dumps([row, row]).encode(), headers={})

    bundle = tmp_path / "bundle"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )
    assert manifest["coverage"]["status"] == "partial"
    assert manifest["duplicate_commit_oids"] == ["1" * 40]
    assert verify_public_evidence(bundle)["reason"] == "duplicate_commit_oids"


def test_resume_verifies_existing_cas_before_network(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    bundle = tmp_path / "bundle"

    def first(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={
                "Link": (
                    "<https://api.github.com/repos/acme/widget/commits?sha="
                    + ("a" * 40)
                    + '&per_page=100&page=2>; rel="next"'
                )
            },
        )

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=first,
        evidence_dir=bundle,
        max_pages=1,
    )
    digest = manifest["pages"][0]["body_sha256"]
    (bundle / "blobs" / "sha256" / digest).write_bytes(b"tampered")
    calls = 0

    def must_not_run(_request: RequestSpec) -> HttpResponse:
        nonlocal calls
        calls += 1
        return HttpResponse(status=200, body=b"[]", headers={})

    with pytest.raises(ValueError, match="existing bundle verification failed"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=must_not_run,
            evidence_dir=bundle,
            resume=True,
        )
    assert calls == 0


def test_http_429_preserves_cursor_and_can_resume(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    bundle = tmp_path / "bundle"

    def first(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={
                "Link": (
                    "<https://api.github.com/repos/acme/widget/commits?sha="
                    + ("a" * 40)
                    + '&per_page=100&page=2>; rel="next"'
                )
            },
        )

    collect_public_evidence(locator, oid, transport=first, evidence_dir=bundle, max_pages=1)

    def limited(request: RequestSpec) -> HttpResponse:
        assert "page=2" in request.url
        return HttpResponse(status=429, body=b'{"message":"rate limited"}', headers={})

    limited_manifest = collect_public_evidence(
        locator, oid, transport=limited, evidence_dir=bundle, resume=True
    )
    assert limited_manifest["coverage"]["status"] == "partial"
    assert limited_manifest["pagination"]["stop_reason"] == "http_429"
    assert "page=2" in limited_manifest["pagination"]["next_request"]["url"]

    def recovered(request: RequestSpec) -> HttpResponse:
        assert "page=2" in request.url
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "2" * 40, "author": None}]).encode(),
            headers={},
        )

    complete = collect_public_evidence(
        locator, oid, transport=recovered, evidence_dir=bundle, resume=True
    )
    assert complete["coverage"]["status"] == "complete"
    assert complete["commit_oids"] == ["1" * 40, "2" * 40]


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_first_page_http_error_is_self_verifying_and_resumable(tmp_path: Path, status: int) -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    bundle = tmp_path / "bundle"
    limited = collect_public_evidence(
        locator,
        oid,
        transport=lambda _request: HttpResponse(
            status=status,
            body=json.dumps({"status": status}).encode(),
            headers={"retry-after": "60"},
        ),
        evidence_dir=bundle,
    )
    assert limited["coverage"] == {
        "status": "unavailable",
        "item_count": 0,
        "missing": ["first_successful_api_page"],
    }
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"

    resumed = collect_public_evidence(
        locator,
        oid,
        transport=lambda request: HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={},
        ),
        evidence_dir=bundle,
        resume=True,
    )
    assert resumed["coverage"] == {"status": "complete", "item_count": 1, "missing": []}
    assert resumed["commit_oids"] == ["1" * 40]
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


def test_gitlab_nested_project_uses_encoded_path_and_never_infers_account(
    tmp_path: Path,
) -> None:
    locator = parse_forge_locator(
        "git@gitlab.example.test:group/sub/repo.git",
        provider="gitlab",
        api_base="https://gitlab.example.test/api/v4",
    )
    requested: list[str] = []

    def transport(request: RequestSpec) -> HttpResponse:
        requested.append(request.url)
        return HttpResponse(
            status=200,
            body=json.dumps(
                [
                    {
                        "id": "3" * 40,
                        "author_name": "Alice",
                        "author_email": "alice@example.test",
                    }
                ]
            ).encode(),
            headers={"X-Next-Page": ""},
        )

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "b" * 40),
        transport=transport,
        evidence_dir=tmp_path / "gitlab",
    )
    assert "%2F" in requested[0]
    assert manifest["provider"] == "gitlab"
    assert manifest["account_linkage"] == "unsupported"
    assert manifest["sha_to_account"] == {}
    assert manifest["commit_oids"] == ["3" * 40]


def test_gitlab_normal_pagination_keeps_closed_query_and_encoded_project(
    tmp_path: Path,
) -> None:
    locator = parse_forge_locator(
        "git@gitlab.example.test:group/sub/repo.git",
        provider="gitlab",
        api_base="https://gitlab.example.test/api/v4",
    )
    oid = GitObjectId("sha1", "b" * 40)
    requested: list[str] = []

    def transport(request: RequestSpec) -> HttpResponse:
        requested.append(request.url)
        page = len(requested)
        return HttpResponse(
            status=200,
            body=json.dumps([{"id": str(page) * 40, "author_name": "Alice"}]).encode(),
            headers={"X-Next-Page": "2" if page == 1 else ""},
        )

    bundle = tmp_path / "gitlab-pages"
    manifest = collect_public_evidence(
        locator,
        oid,
        transport=transport,
        evidence_dir=bundle,
    )

    assert len(requested) == 2
    assert all("/projects/group%2Fsub%2Frepo/repository/commits?" in url for url in requested)
    assert all(f"ref_name={oid.value}" in url and "per_page=100" in url for url in requested)
    assert "page=1" in requested[0]
    assert "page=2" in requested[1]
    assert manifest["coverage"] == {"status": "complete", "item_count": 2, "missing": []}
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


def test_gitlab_never_persists_or_consumes_non_authoritative_link_query(
    tmp_path: Path,
) -> None:
    locator = parse_forge_locator(
        "git@gitlab.example.test:group/repo.git",
        provider="gitlab",
        api_base="https://gitlab.example.test/api/v4",
    )

    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "b" * 40),
        transport=lambda _request: HttpResponse(
            status=200,
            body=json.dumps([{"id": "1" * 40}]).encode(),
            headers={
                "Link": (
                    "<https://gitlab.example.test/api/v4/projects/other/"
                    'repository/commits?session=must-not-persist>; rel="next"'
                ),
                "X-Next-Page": "",
            },
        ),
        evidence_dir=tmp_path / "gitlab-link-is-not-input",
    )

    assert "link" not in manifest["pages"][0]["response_headers"]
    assert "must-not-persist" not in json.dumps(manifest)
    assert verify_public_evidence(tmp_path / "gitlab-link-is-not-input")["status"] == "VERIFIED"


def test_not_requested_manifest_is_byte_deterministic() -> None:
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", "a" * 40)
    first = not_requested_manifest(locator, oid)
    second = not_requested_manifest(locator, oid)
    assert first == second
    assert first["fetched_at"] is None
    assert first["coverage"]["status"] == "not_requested"


def test_offline_compat_manifest_never_leaks_remote_userinfo() -> None:
    manifest = collect_public_handles(
        "https://alice:remote-secret@github.com/acme/widget.git",
        fetch=False,
    )
    encoded = json.dumps(manifest)
    assert "alice" not in encoded
    assert "remote-secret" not in encoded
    assert manifest["source_url"] == "github.com/acme/widget"


def test_verify_detects_body_tamper(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b"[]", headers={})

    bundle = tmp_path / "bundle"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )
    digest = manifest["pages"][0]["body_sha256"]
    (bundle / "blobs" / "sha256" / digest).write_bytes(b"tampered")
    result = verify_public_evidence(bundle)
    assert result["status"] == "MISMATCH"
    assert result["reason"] == "body_digest_mismatch"


@pytest.mark.parametrize("target", ["root", "manifest", "blob"])
def test_verify_rejects_public_bundle_permission_drift(tmp_path: Path, target: str) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b"[]", headers={})

    bundle = tmp_path / f"permission-{target}"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )
    if target == "root":
        bundle.chmod(0o755)
    elif target == "manifest":
        (bundle / "manifest.json").chmod(0o644)
    else:
        digest = manifest["pages"][0]["body_sha256"]
        (bundle / "blobs" / "sha256" / digest).chmod(0o644)

    result = verify_public_evidence(bundle)
    assert result["status"] == "MISMATCH"
    assert result["reason"] == "unsafe_bundle_mode"


def test_verify_rejects_unregistered_root_member_and_orphan_cas(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b"[]", headers={})

    bundle = tmp_path / "inventory"
    collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )
    extra = bundle / "unexpected.txt"
    extra.write_text("unregistered\n", encoding="utf-8")
    extra.chmod(0o600)
    result = verify_public_evidence(bundle)
    assert result == {"status": "MISMATCH", "reason": "unregistered_bundle_member"}

    extra.unlink()
    orphan = bundle / "blobs" / "sha256" / ("f" * 64)
    orphan.write_bytes(b"orphan")
    orphan.chmod(0o600)
    result = verify_public_evidence(bundle)
    assert result == {"status": "MISMATCH", "reason": "unregistered_cas_blob"}


def test_invalid_provider_commit_oid_fails_closed(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps([{"sha": "not-an-oid", "author": None}]).encode(),
            headers={},
        )

    with pytest.raises(ValueError, match="invalid Git OID"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=tmp_path / "bundle",
        )


def test_local_git_coverage_reconciliation_separates_partial_and_mismatch() -> None:
    manifest = {
        "coverage": {"status": "partial"},
        "commit_oids": ["1" * 40],
        "duplicate_commit_oids": [],
    }
    partial = reconcile_commit_coverage(manifest, ["1" * 40, "2" * 40])
    assert partial == {
        "status": "partial",
        "expected_count": 2,
        "observed_count": 1,
        "missing": ["2" * 40],
        "extra": [],
        "duplicates": [],
    }

    manifest["coverage"] = {"status": "complete"}
    false_complete = reconcile_commit_coverage(manifest, ["1" * 40, "2" * 40])
    assert false_complete["status"] == "mismatch"
    manifest["commit_oids"] = ["1" * 40, "f" * 40]
    extra = reconcile_commit_coverage(manifest, ["1" * 40])
    assert extra["status"] == "mismatch"
    assert extra["extra"] == ["f" * 40]


def test_fixed_target_license_and_history_ignore_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "fixture@example.test"],
        check=True,
    )
    committed = b"MIT fixture license\n"
    (repo / "LICENSE").write_bytes(committed)
    subprocess.run(["git", "-C", str(repo), "add", "LICENSE"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "license"], check=True)
    target = resolve_fixed_target(repo, "HEAD")
    (repo / "LICENSE").write_text("uncommitted replacement\n", encoding="utf-8")

    evidence = collect_revision_license_evidence(repo, target)
    assert evidence["status"] == "observed"
    assert evidence["target_oid"] == target.to_dict()
    assert evidence["files"][0]["path"] == "LICENSE"
    assert evidence["files"][0]["sha256"] == hashlib.sha256(committed).hexdigest()
    assert evidence["files"][0]["bytes"] == len(committed)
    assert evidence["digest"]["algorithm"] == "sha256"
    assert read_fixed_history_oids(repo, target) == [target.value]


def test_cli_license_evidence_is_fixed_tree_bound_replay_stable_and_verified(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "fixture@example.test"],
        check=True,
    )
    committed = b"MIT fixture license body that must never be emitted\n"
    (repo / "LICENSE").write_bytes(committed)
    (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "LICENSE", "app.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "license"], check=True)
    target = resolve_fixed_target(repo, "HEAD")

    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://forge.example.test/acme/widget.git",
        ],
        check=True,
    )
    (repo / "LICENSE").write_text("uncommitted replacement\n", encoding="utf-8")

    def fixed_transport(request: RequestSpec) -> HttpResponse:
        assert request.url.startswith("https://forge.example.test/api/v3/")
        body = json.dumps([{"sha": target.value, "author": None}]).encode("utf-8")
        return HttpResponse(status=200, body=body, headers={})

    monkeypatch.setattr("tep_core.public_fetch._read_request", fixed_transport)

    offline = tmp_path / "offline"
    live = tmp_path / "live"
    replay = tmp_path / "replay"
    bundle = tmp_path / "public-evidence"
    collection = tmp_path / "actor-collection"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--rev",
                target.value,
                "--format",
                "both",
                "--out",
                str(offline),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "repo",
                str(repo),
                "--rev",
                target.value,
                "--fetch-public",
                "--forge-provider",
                "github",
                "--forge-api-base",
                "https://forge.example.test/api/v3",
                "--public-evidence-out",
                str(bundle),
                "--format",
                "both",
                "--out",
                str(live),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "repo",
                str(repo),
                "--rev",
                target.value,
                "--public-evidence",
                str(bundle),
                "--format",
                "both",
                "--out",
                str(replay),
            ]
        )
        == 0
    )
    capsys.readouterr()

    reports = [
        json.loads((root / "report.json").read_text(encoding="utf-8"))
        for root in (offline, live, replay)
    ]
    license_rows = [
        report["input_coverage"]["public_forge"]["repository_license"] for report in reports
    ]
    assert license_rows[0] == license_rows[1] == license_rows[2]
    license_row = license_rows[0]
    assert license_row["target_oid"] == target.to_dict()
    assert license_row["files"] == [
        {
            "path": "LICENSE",
            "blob_oid": license_row["files"][0]["blob_oid"],
            "sha256": hashlib.sha256(committed).hexdigest(),
            "bytes": len(committed),
        }
    ]
    assert (
        reports[0]["provenance"]["input_digests"]["license_evidence"]
        == (license_row["digest"]["value"])
    )
    assert license_row["terms_status"] == "separate_from_license_evidence"
    assert reports[1]["input_coverage"]["public_forge"]["provider_api_terms"] == {
        "kind": "not_observed",
        "reason": "provider_api_terms_not_recorded",
    }
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (offline, live, replay)
        for path in (root / "report.json", root / "report.md")
    )
    assert committed.decode().strip() not in rendered
    assert "uncommitted replacement" not in rendered
    assert "bytes" in rendered

    assert (
        main(
            [
                "repo",
                str(repo),
                "--rev",
                target.value,
                "--actors",
                "--format",
                "both",
                "--out",
                str(collection),
            ]
        )
        == 0
    )
    capsys.readouterr()
    collection_report = json.loads((collection / "repo-report.json").read_text(encoding="utf-8"))
    assert collection_report["input_coverage"]["public_forge"]["repository_license"] == license_row
    collection_markdown = (collection / "repo-report.md").read_text(encoding="utf-8")
    assert "License evidence digest" in collection_markdown
    assert "body omitted" in collection_markdown
    assert committed.decode().strip() not in collection_markdown

    offline_report = offline / "report.json"
    assert main(["verify", str(offline_report), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    tampered = json.loads(offline_report.read_text(encoding="utf-8"))
    tampered["input_coverage"]["public_forge"]["repository_license"]["files"][0]["sha256"] = (
        "f" * 64
    )
    offline_report.write_text(json.dumps(tampered), encoding="utf-8")
    assert main(["verify", str(offline_report), "--repo", str(repo)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_fixed_history_refuses_shallow_repository(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", str(origin)], check=True)
    subprocess.run(["git", "-C", str(origin), "config", "user.name", "Fixture"], check=True)
    subprocess.run(
        ["git", "-C", str(origin), "config", "user.email", "fixture@example.test"],
        check=True,
    )
    for index in range(2):
        (origin / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(origin), "add", "file.txt"], check=True)
        subprocess.run(["git", "-C", str(origin), "commit", "-qm", f"commit {index}"], check=True)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth=1", origin.as_uri(), str(shallow)], check=True)
    target = resolve_fixed_target(shallow, "HEAD")
    with pytest.raises(ValueError, match="history_incomplete.*shallow"):
        read_fixed_history_oids(shallow, target)


def test_legacy_public_fetch_uses_rest_terms_not_robots(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(url: str):
        calls.append(url)
        if url.endswith("robots.txt"):
            raise AssertionError("REST API collection must not consult robots.txt")
        if "/commits" in url:
            return (
                200,
                json.dumps(
                    [
                        {
                            "sha": "4" * 40,
                            "author": {"id": 7, "login": "alice"},
                        }
                    ]
                ),
                {},
            )
        if "/contributors" in url:
            raise AssertionError("commit CAS collection must not call contributors")
        if "/license" in url:
            return 404, "", {}
        return 404, "", {}

    manifest = collect_public_handles(
        "github.com/acme/widget",
        fetch=True,
        head_sha="a" * 40,
        transport=transport,
        evidence_out=tmp_path / "evidence",
    )
    assert manifest["robots_status"] == "not_applicable"
    assert manifest["coverage"]["status"] == "complete"
    assert manifest["sha_to_login"] == {"4" * 40: "alice"}
    assert manifest["sha_to_account"]["4" * 40]["account_id"] == "7"
    assert manifest["fetched_login_count"] is None
    assert manifest["commit_login_count"] == 1
    assert not any(url.endswith("robots.txt") for url in calls)
    assert not any("/contributors" in url for url in calls)
    assert verify_public_evidence(tmp_path / "evidence")["status"] == "VERIFIED"
    assert load_public_handles(tmp_path / "evidence") == manifest


def test_legacy_public_fetch_supports_explicit_self_managed_gitlab(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(url: str):
        calls.append(url)
        return 200, json.dumps([{"id": "5" * 40, "author_name": "Alice"}]), {}

    manifest = collect_public_handles(
        "git@gitlab.example.test:group/sub/repo.git",
        fetch=True,
        head_sha="a" * 40,
        transport=transport,
        provider="gitlab",
        api_base="https://gitlab.example.test/api/v4",
        evidence_out=tmp_path / "gitlab",
    )
    assert manifest["provider"] == "gitlab"
    assert manifest["account_linkage"] == "unsupported"
    assert manifest["sha_to_login"] == {}
    assert "%2F" in calls[0]


def test_compat_projection_never_calls_unrecorded_contributors(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(url: str):
        calls.append(url)
        if "/commits" in url:
            return 200, "[]", {}
        if "/contributors" in url:
            raise AssertionError("contributors request escaped the CAS page budget")
        return 404, "", {}

    live = collect_public_handles(
        "github.com/acme/widget",
        fetch=True,
        head_sha="a" * 40,
        transport=transport,
        auth_token="runtime-secret",
        evidence_out=tmp_path / "bundle",
    )
    replay = load_public_handles(tmp_path / "bundle")
    assert live == replay
    assert all("/contributors" not in url for url in calls)


def test_live_compat_fetch_requires_durable_bundle_and_full_oid(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full fixed Git OID"):
        collect_public_handles(
            "github.com/acme/widget",
            fetch=True,
            head_sha="HEAD",
            evidence_out=tmp_path / "invalid",
        )
    with pytest.raises(ValueError, match="durable evidence_out"):
        collect_public_handles(
            "github.com/acme/widget",
            fetch=True,
            head_sha="a" * 40,
        )


def test_collection_enforces_body_byte_limit(tmp_path: Path) -> None:
    locator = parse_forge_locator("github.com/acme/widget")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=b"01234567890", headers={})

    with pytest.raises(ValueError, match="per-page byte limit"):
        collect_public_evidence(
            locator,
            GitObjectId("sha1", "a" * 40),
            transport=transport,
            evidence_dir=tmp_path / "bundle",
            max_body_bytes=10,
            max_total_bytes=10,
        )
