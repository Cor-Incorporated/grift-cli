"""Fail-closed CLI and verifier checks for public-evidence-v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.forge_public import GitObjectId, HttpResponse, RequestSpec, parse_forge_locator
from tep_core.public_evidence import collect_public_evidence, verify_public_evidence


def _bundle(tmp_path: Path) -> tuple[Path, dict]:
    bundle = tmp_path / "bundle"
    manifest = collect_public_evidence(
        parse_forge_locator("github.com/acme/widget"),
        GitObjectId("sha1", "a" * 40),
        transport=lambda _request: HttpResponse(
            status=200,
            body=json.dumps([{"sha": "1" * 40, "author": None}]).encode(),
            headers={},
        ),
        evidence_dir=bundle,
        fetched_at="2026-08-31T00:00:00Z",
    )
    return bundle, manifest


def _rewrite_with_self_digest(bundle: Path, manifest: dict) -> None:
    unsigned = dict(manifest)
    unsigned.pop("bundle_payload_sha256", None)
    encoded = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    manifest["bundle_payload_sha256"] = hashlib.sha256(encoded).hexdigest()
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("location", ["root", "nested"])
def test_verifier_rejects_unknown_schema_key_after_self_digest_rewrite(
    tmp_path: Path, location: str
) -> None:
    bundle, manifest = _bundle(tmp_path)
    if location == "root":
        manifest["unknown_root"] = "must-not-be-accepted"
    else:
        manifest["source"]["unknown_nested"] = "must-not-be-accepted"
    _rewrite_with_self_digest(bundle, manifest)

    result = verify_public_evidence(bundle)

    assert result["status"] == "MISMATCH"
    assert result["reason"] == "schema_validation_failed"
    assert any("unknown key" in error for error in result["errors"])


@pytest.mark.parametrize("location", ["root", "nested"])
def test_verify_cli_rejects_unknown_schema_key_after_self_digest_rewrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], location: str
) -> None:
    bundle, manifest = _bundle(tmp_path)
    if location == "root":
        manifest["unknown_root"] = "must-not-be-accepted"
    else:
        manifest["pages"][0]["unknown_nested"] = "must-not-be-accepted"
    _rewrite_with_self_digest(bundle, manifest)

    code = main(["verify", "--public-evidence", str(bundle), "--repo", str(tmp_path)])
    result = json.loads(capsys.readouterr().out)

    assert code == 1
    assert result["status"] == "MISMATCH"
    assert result["reason"] == "schema_validation_failed"


@pytest.mark.parametrize("invalid", ["0", "-1"])
def test_max_public_pages_rejects_non_positive_value_before_network(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    calls = 0

    def must_not_run(_request: RequestSpec) -> HttpResponse:
        nonlocal calls
        calls += 1
        raise AssertionError("network must not run")

    monkeypatch.setattr("tep_core.public_fetch._read_request", must_not_run)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "repo",
                ".",
                "--fetch-public",
                "--public-evidence-out",
                "unused",
                "--max-public-pages",
                invalid,
            ]
        )

    assert exc.value.code == 2
    assert calls == 0
