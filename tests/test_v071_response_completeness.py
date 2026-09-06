"""Falsification tests for terminated Forge transfers.

The observed failure is a *terminated* transfer, not a short-but-continuing
read: one ``read()`` returns fewer bytes than the declared ``Content-Length``
and the next returns ``b""``.  A plain read-to-EOF loop therefore exits happily
with a cut body, and the cut bytes surface as ``Forge response body is not
valid UTF-8 JSON`` -- blaming the provider for our own incomplete read.

An earlier version of this file drove a synthetic stream that handed back the
remainder on the next call.  That shape does not occur in production, so the
test passed whether or not the bug was fixed.  Every stream here ends after its
first short read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_core import public_evidence
from tep_core.forge_public import (
    ForgeTruncatedBodyError,
    GitObjectId,
    HttpResponse,
    RequestSpec,
    parse_forge_locator,
)
from tep_core.public_evidence import collect_public_evidence, verify_public_evidence
from tep_core.public_fetch import _MAX_RESPONSE_BYTES, _read_body


class _TerminatedStream:
    """One short read, then EOF -- the shape GitHub actually produces."""

    def __init__(self, body: bytes, *, first: int) -> None:
        self._body = body
        self._first = first
        self.calls = 0

    def read(self, size: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return self._body[: min(size, self._first)]
        return b""


class _WholeStream:
    """A complete body delivered in one read, then EOF."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.calls = 0

    def read(self, size: int) -> bytes:
        self.calls += 1
        return self._body[:size] if self.calls == 1 else b""


def _payload(rows: int = 40) -> bytes:
    return json.dumps([{"sha": f"{index:040x}"} for index in range(rows)]).encode("utf-8")


# (a) declared Content-Length, one short read, then EOF -> truncated_body


def test_read_body_rejects_a_transfer_that_ended_before_content_length() -> None:
    payload = _payload()
    stream = _TerminatedStream(payload, first=len(payload) - 100)
    with pytest.raises(ForgeTruncatedBodyError) as caught:
        _read_body(stream, content_length=str(len(payload)))
    message = str(caught.value)
    assert "truncated_body" in message
    assert f"content_length={len(payload)}" in message
    assert f"received={len(payload) - 100}" in message
    # The real shape: the loop never gets a second chunk, so a read-to-EOF
    # loop alone cannot detect this.
    assert stream.calls == 2
    assert isinstance(caught.value, OSError)


def test_read_body_accepts_a_transfer_that_matches_content_length() -> None:
    payload = _payload()
    stream = _WholeStream(payload)
    assert _read_body(stream, content_length=str(len(payload))) == payload


# (d) no Content-Length (chunked) -> EOF is the only end marker


@pytest.mark.parametrize("content_length", [None, "", "not-a-number", "-1"])
def test_read_body_reads_to_eof_when_no_usable_content_length_is_declared(
    content_length: object,
) -> None:
    payload = _payload()
    stream = _TerminatedStream(payload, first=len(payload) - 100)
    assert _read_body(stream, content_length=content_length) == payload[: len(payload) - 100]


def test_read_body_still_rejects_a_body_over_the_byte_cap() -> None:
    oversized = _WholeStream(b"x" * (_MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ValueError, match="per-page byte limit"):
        _read_body(oversized)


def test_read_body_returns_an_empty_body_unchanged() -> None:
    assert _read_body(_TerminatedStream(b"", first=0)) == b""


# (b) and (c): the collection loop retries a bounded number of times


def _locator():
    return parse_forge_locator("https://github.com/acme/widget.git")


def _ok_response() -> HttpResponse:
    body = json.dumps(
        [
            {
                "sha": "1" * 40,
                "author": {
                    "id": 42,
                    "login": "alice",
                    "type": "User",
                    "html_url": "https://github.com/alice",
                },
            }
        ]
    ).encode("utf-8")
    return HttpResponse(status=200, body=body, headers={})


@pytest.fixture()
def no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(public_evidence, "_sleep", slept.append)
    return slept


def test_collection_retries_a_terminated_transfer_and_recovers(
    tmp_path: Path, no_backoff_sleep: list[float]
) -> None:
    attempts: list[RequestSpec] = []

    def transport(request: RequestSpec) -> HttpResponse:
        attempts.append(request)
        if len(attempts) == 1:
            raise ForgeTruncatedBodyError("truncated_body: content_length=100 received=40")
        return _ok_response()

    bundle = tmp_path / "retry-recovers"
    manifest = collect_public_evidence(
        _locator(),
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )

    assert len(attempts) == 2
    assert attempts[0].url == attempts[1].url
    assert manifest["pagination"]["stop_reason"] == "no_next_page"
    assert manifest["coverage"]["status"] == "complete"
    assert no_backoff_sleep == [0.5]
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"


def test_collection_does_not_retry_when_the_first_attempt_succeeds(
    tmp_path: Path, no_backoff_sleep: list[float]
) -> None:
    manifest = collect_public_evidence(
        _locator(),
        GitObjectId("sha1", "a" * 40),
        transport=lambda _request: _ok_response(),
        evidence_dir=tmp_path / "no-retry",
    )
    assert len(manifest["pages"]) == 1
    assert no_backoff_sleep == []


def test_collection_stops_after_the_attempt_budget_is_exhausted(
    tmp_path: Path, no_backoff_sleep: list[float]
) -> None:
    attempts: list[RequestSpec] = []

    def transport(request: RequestSpec) -> HttpResponse:
        attempts.append(request)
        raise ForgeTruncatedBodyError("truncated_body: content_length=436443 received=372299")

    manifest = collect_public_evidence(
        _locator(),
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=tmp_path / "retry-exhausted",
    )

    assert len(attempts) == 3
    assert manifest["pagination"]["stop_reason"] == "transport_error:ForgeTruncatedBodyError"
    assert manifest["coverage"]["status"] != "complete"
    assert manifest["pages"] == []
    assert no_backoff_sleep == [0.5, 1.0]


def test_collection_retries_a_timeout_the_same_way(
    tmp_path: Path, no_backoff_sleep: list[float]
) -> None:
    attempts: list[RequestSpec] = []

    def transport(request: RequestSpec) -> HttpResponse:
        attempts.append(request)
        if len(attempts) < 3:
            raise TimeoutError("read timed out")
        return _ok_response()

    manifest = collect_public_evidence(
        _locator(),
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=tmp_path / "timeout-recovers",
    )
    assert len(attempts) == 3
    assert manifest["pagination"]["stop_reason"] == "no_next_page"
    assert no_backoff_sleep == [0.5, 1.0]


def test_retry_budget_does_not_hide_a_persistent_timeout(
    tmp_path: Path, no_backoff_sleep: list[float]
) -> None:
    def transport(_request: RequestSpec) -> HttpResponse:
        raise TimeoutError("read timed out")

    manifest = collect_public_evidence(
        _locator(),
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=tmp_path / "timeout-exhausted",
    )
    assert manifest["pagination"]["stop_reason"] == "transport_error:TimeoutError"
