"""Attestation binding for every replayable report-v2 input."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from git_fixture import commit, git, init_repo
import tep_cli.__main__ as cli_module
import tep_core.analyze_v2 as analyze_v2_module
from tep_core.attest import validate_attestation_statement
from tep_core.forge_public import GitObjectId, HttpResponse, parse_forge_locator
from tep_core.public_evidence import collect_public_evidence
from tep_core.schema import validate_schema
from tep_core.tagset import reachable_tagset_digest
from tep_core.verify import CANNOT_VERIFY, VerifyResult


ROOT = Path(__file__).resolve().parents[1]


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tep_cli", *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_identity(path: Path) -> Path:
    path.write_text(
        'schema_version = "identity-v2"\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["alice@example.test"]\n'
        'attribution_state = "verified"\n',
        encoding="utf-8",
    )
    return path


def _write_export(path: Path, repo: Path, *, kind: str) -> Path:
    schema = "tep-forge-export-v2" if kind == "forge" else "tep-tracker-export-v2"
    payload = {
        "schema_version": schema,
        "binding": {
            "provider": "github",
            "host": "github.com",
            "project_id": "R_attest_binding",
            "project_path": "acme/attest-binding",
            "target_oid": {"algorithm": "sha1", "value": _sha(repo)},
            "window": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-09-01T00:00:00Z",
            },
            "coverage": {
                "status": "complete",
                "observed": 31,
                "expected": 31,
                "missing": 0,
                "unit": "days",
            },
        },
        "events": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_reference_manifest(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "pack_id": "attest-test-pack",
                "pack_version": "1",
                "as_of": "2026-08-31",
                "purpose": "attestation input binding fixture",
                "policy": {},
                "artifacts": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _public_bundle(repo: Path, destination: Path) -> Path:
    sha = _sha(repo)
    # The public-evidence digest is bound independently of optional provider
    # account enrichment.  An unlinked row keeps this test focused on the
    # attestation input rather than on account display behavior.
    body = json.dumps([{"sha": sha, "author": None}]).encode("utf-8")

    def transport(_request: object) -> HttpResponse:
        return HttpResponse(status=200, body=body, headers={})

    collect_public_evidence(
        parse_forge_locator("https://github.com/acme/attest-binding.git"),
        GitObjectId("sha1", sha),
        transport=transport,
        evidence_dir=destination,
        fetched_at="2026-08-31T00:00:00Z",
    )
    return destination


def _ssh_material(root: Path) -> tuple[Path, Path]:
    ssh_keygen = shutil.which("ssh-keygen")
    assert ssh_keygen is not None
    private_key = root / "id_ed25519"
    subprocess.run(
        [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    os.chmod(private_key, 0o600)
    public_key = private_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    allowed_signers = root / "allowed_signers"
    allowed_signers.write_text(f"trusted-builder {public_key}\n", encoding="utf-8")
    return private_key, allowed_signers


def _bound_options(
    *, identity: Path, forge: Path, tracker: Path, reference: Path, public: Path
) -> list[str]:
    return [
        "--identity",
        str(identity),
        "--forge-export",
        str(forge),
        "--tracker-export",
        str(tracker),
        "--reference-manifest",
        str(reference),
        "--public-evidence",
        str(public),
    ]


def _fixture(tmp_path: Path) -> dict[str, Path]:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="alice@example.test",
        date="2026-08-15",
        message="feat: attest bound report",
        filename="src/app.py",
        name="Alice",
    )
    git(repo, "remote", "add", "origin", "https://github.com/acme/attest-binding.git")
    tag_env = {
        **os.environ,
        "GIT_COMMITTER_NAME": "Private Tagger",
        "GIT_COMMITTER_EMAIL": "private-tagger@example.test",
        "GIT_COMMITTER_DATE": "2026-08-16T12:00:00Z",
    }
    git(repo, "tag", "-a", "v1.0.0", "-m", "release", env=tag_env)
    identity = _write_identity(tmp_path / "identity.toml")
    forge = _write_export(tmp_path / "forge.json", repo, kind="forge")
    tracker = _write_export(tmp_path / "tracker.json", repo, kind="tracker")
    reference = _write_reference_manifest(tmp_path / "attest-sources.json")
    public = _public_bundle(repo, tmp_path / "public-evidence")
    return {
        "repo": repo,
        "identity": identity,
        "forge": forge,
        "tracker": tracker,
        "reference": reference,
        "public": public,
    }


def test_attest_routes_every_verify_input_to_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_verify(report: Path, repo: Path, identity: Path, **kwargs: object) -> VerifyResult:
        observed.update({"report": report, "repo": repo, "identity": identity, **kwargs})
        return VerifyResult(CANNOT_VERIFY, notes=["intentional preflight stop"])

    monkeypatch.setattr(cli_module, "verify_report", fake_verify)
    result = cli_module.main(
        [
            "attest",
            str(tmp_path / "report.json"),
            "--repo",
            str(tmp_path / "repo"),
            "--identity",
            str(tmp_path / "identity.toml"),
            "--public-evidence",
            str(tmp_path / "public"),
            "--forge-export",
            str(tmp_path / "forge.json"),
            "--tracker-export",
            str(tmp_path / "tracker.json"),
            "--reference-manifest",
            str(tmp_path / "sources.json"),
            "--project",
            str(tmp_path / "project.toml"),
            "--actor",
            "actor_01",
            "--actor-report",
            str(tmp_path / "actor.json"),
            "--project-report",
            str(tmp_path / "project.json"),
            "--out",
            str(tmp_path / "bundle"),
            "--sign",
            "ssh",
        ]
    )

    assert result == 2
    assert observed == {
        "report": tmp_path / "report.json",
        "repo": tmp_path / "repo",
        "identity": tmp_path / "identity.toml",
        "project_path": tmp_path / "project.toml",
        "forge_export": tmp_path / "forge.json",
        "tracker_export": tmp_path / "tracker.json",
        "actor_id": "actor_01",
        "actor_report_path": tmp_path / "actor.json",
        "project_report_path": tmp_path / "project.json",
        "reference_manifest": tmp_path / "sources.json",
        "public_evidence_path": tmp_path / "public",
    }


def test_report_refuses_a_tagset_that_changes_during_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = init_repo(tmp_path / "changing-tags")
    commit(
        repo,
        email="alice@example.test",
        date="2026-08-15",
        message="feat: fixed target",
    )
    real = analyze_v2_module.reachable_tagset_digest
    calls = 0

    def unstable(repository: Path, target: dict[str, str]) -> str:
        nonlocal calls
        calls += 1
        value = real(repository, target)
        return value if calls == 1 else "f" * 64

    monkeypatch.setattr(analyze_v2_module, "reachable_tagset_digest", unstable)

    assert cli_module.main(["repo", str(repo), "--format", "json"]) == 2
    assert "reachable tag set changed" in capsys.readouterr().err


def test_reachable_tagset_digest_binds_refs_without_exposing_tagger_identity(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    repo = paths["repo"]
    target = {"algorithm": "sha1", "value": _sha(repo)}
    first = reachable_tagset_digest(repo, target)

    assert len(first) == 64
    assert "private-tagger" not in first
    git(repo, "tag", "release-alias")
    second = reachable_tagset_digest(repo, target)
    assert second != first
    git(repo, "tag", "-d", "release-alias")
    assert reachable_tagset_digest(repo, target) == first
    commit(
        repo,
        email="alice@example.test",
        date="2026-08-17",
        message="feat: later commit",
        filename="src/later.py",
    )
    git(repo, "tag", "future-only")
    assert reachable_tagset_digest(repo, target) == first


def test_reachable_tagset_digest_accepts_a_real_sha256_repository(tmp_path: Path) -> None:
    repo = tmp_path / "sha256-repo"
    initialized = subprocess.run(
        ["git", "init", "--object-format=sha256", "-b", "main", str(repo)],
        capture_output=True,
        text=True,
    )
    if initialized.returncode != 0:
        pytest.skip("Git on this host does not support SHA-256 repositories")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.test")
    commit(
        repo,
        email="sha256@example.test",
        date="2026-08-15",
        message="feat: sha256 tagset",
    )
    git(repo, "tag", "v1")
    oid = _sha(repo)

    digest = reachable_tagset_digest(repo, {"algorithm": "sha256", "value": oid})

    assert len(oid) == 64
    assert len(digest) == 64


def test_attest_report_v2_requires_and_binds_every_replay_input(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    repo = paths["repo"]
    bound = _bound_options(
        identity=paths["identity"],
        forge=paths["forge"],
        tracker=paths["tracker"],
        reference=paths["reference"],
        public=paths["public"],
    )
    generated = _cli("repo", str(repo), *bound, "--format", "json")
    assert generated.returncode == 0, generated.stderr
    report = tmp_path / "report-v2.json"
    report.write_text(generated.stdout, encoding="utf-8")
    report_payload = json.loads(generated.stdout)
    provenance = report_payload["provenance"]
    assert provenance["tagset_digest"] == provenance["input_digests"]["tagset"]

    private_key, allowed_signers = _ssh_material(tmp_path)
    bundle = tmp_path / "attestation"
    signed = _cli(
        "attest",
        str(report),
        "--repo",
        str(repo),
        *bound,
        "--out",
        str(bundle),
        "--sign",
        "ssh",
        "--ssh-key",
        str(private_key),
        "--principal",
        "trusted-builder",
    )
    assert signed.returncode == 0, signed.stderr
    statement = json.loads((bundle / "statement.json").read_text(encoding="utf-8"))
    assert validate_attestation_statement(statement) == []
    assert validate_schema("attest-v1", statement) == []
    assert statement["target"]["oid"] == provenance["target_oid"]
    assert statement["scope"] == {"analysis_scope": "repo"}
    assert statement["public_evidence"]["digest"]["value"] == provenance["public_evidence_digest"]
    assert statement["tagset"]["digest"]["value"] == provenance["tagset_digest"]
    assert statement["inputs"]["members"]["forge"]["value"] == provenance["input_digests"]["forge"]
    assert (
        statement["inputs"]["members"]["tracker"]["value"] == provenance["input_digests"]["tracker"]
    )
    assert (
        statement["inputs"]["members"]["benchmark_manifest"]["value"]
        == provenance["reference_manifest_digest"]
    )
    serialized = json.dumps(statement, sort_keys=True)
    assert "alice@example.test" not in serialized
    assert "private-tagger@example.test" not in serialized

    verified = _cli(
        "verify",
        "--report",
        str(report),
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        *bound,
        "--allowed-signers",
        str(allowed_signers),
        "--principal",
        "trusted-builder",
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verified_payload: dict[str, Any] = json.loads(verified.stdout)
    assert verified_payload["signature"]["status"] == "VERIFIED"
    assert verified_payload["report_hash"]["status"] == "VERIFIED"
    assert verified_payload["recompute"]["status"] == "VERIFIED"

    # Omitting one recorded input must fail before any signature is produced.
    missing_forge = _cli(
        "attest",
        str(report),
        "--repo",
        str(repo),
        *_bound_options(
            identity=paths["identity"],
            forge=tmp_path / "missing-forge.json",
            tracker=paths["tracker"],
            reference=paths["reference"],
            public=paths["public"],
        ),
        "--out",
        str(tmp_path / "must-not-exist"),
        "--sign",
        "ssh",
        "--ssh-key",
        str(private_key),
        "--principal",
        "trusted-builder",
    )
    assert missing_forge.returncode == 2
    assert not (tmp_path / "must-not-exist").exists()

    # A new reachable tag changes only the repository recomputation result;
    # signature trust and report bytes remain independently valid.
    git(repo, "tag", "v1.0.1")
    drifted = _cli(
        "verify",
        "--report",
        str(report),
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        *bound,
        "--allowed-signers",
        str(allowed_signers),
        "--principal",
        "trusted-builder",
    )
    assert drifted.returncode == 1
    drifted_payload = json.loads(drifted.stdout)
    assert drifted_payload["signature"]["status"] == "VERIFIED"
    assert drifted_payload["report_hash"]["status"] == "VERIFIED"
    assert drifted_payload["recompute"]["status"] == "MISMATCH"
