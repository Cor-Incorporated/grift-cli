from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import tep_core.attest as attest_module
from tep_core.attest import (
    CANNOT_VERIFY,
    INVALID,
    MISMATCH,
    VERIFIED,
    AttestationError,
    CosignSigningConfig,
    CosignTrustPolicy,
    SSHSigningConfig,
    SSHTrustPolicy,
    SigningToolUnavailable,
    VerificationPart,
    build_attestation_statement,
    canonical_json_bytes,
    create_attestation_bundle,
    load_attestation_bundle,
    validate_attestation_statement,
    verify_attestation_bundle,
)
from tep_core.digest import file_digest
from test_v060_schema_contracts import _base_instances


def _report(path: Path, *, oid: str = "a" * 40) -> Path:
    algorithm = "sha1" if len(oid) == 40 else "sha256"
    payload = {
        "schema_version": "report-v1",
        "subject": {"kind": "actor", "canonical_id": "subject_01"},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "definition_version": "tep-v0.6.0-test",
            "analysis_scope": "tenant",
            "target_oid": {"algorithm": algorithm, "value": oid},
            "public_evidence_digest": "b" * 64,
        },
        "identity": {"pending_attribution": False, "actor_count": 1},
        "activity": {"tenant_commits": {"kind": "observed", "value": 4, "unit": "commits"}},
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _report_v2(path: Path) -> Path:
    payload = _base_instances()["report-v2"]
    payload["provenance"].update(
        {
            "definition_version": "tep-v0.6.0-test",
            "origin_definition_version": "origin-v1",
            "activity_definition_version": "activity-v1",
            "input_digests": {
                "forge": "c" * 64,
                "tracker": None,
                "public_evidence": "b" * 64,
                "tagset": "d" * 64,
            },
            "public_evidence_digest": "b" * 64,
            "tagset_digest": "d" * 64,
        }
    )
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _ssh_material(root: Path, *, principal: str = "trusted-builder") -> tuple[Path, Path]:
    executable = shutil.which("ssh-keygen")
    assert executable, "OpenSSH ssh-keygen is required for the real attestation E2E"
    private_key = root / "id_ed25519"
    subprocess.run(
        [executable, "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    os.chmod(private_key, 0o600)
    public = private_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    allowed = root / "allowed_signers"
    allowed.write_text(f"{principal} {public}\n", encoding="utf-8")
    return private_key, allowed


def _signed_bundle(tmp_path: Path) -> tuple[Path, Path, SSHTrustPolicy]:
    report = _report(tmp_path / "report.json")
    private_key, allowed = _ssh_material(tmp_path)
    bundle = tmp_path / "bundle"
    create_attestation_bundle(
        report,
        bundle,
        signing=SSHSigningConfig(private_key=private_key, principal="trusted-builder"),
        executed_at="2026-08-31T01:02:03Z",
    )
    return report, bundle, SSHTrustPolicy(allowed, "trusted-builder")


def _rewrite_manifest_digest(bundle: Path, member: str, digest: str) -> None:
    path = bundle / "bundle-manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[member]["digest"]["value"] = digest
    path.write_bytes(canonical_json_bytes(payload))


def test_statement_is_closed_canonical_and_accepts_sha256_git_oid(tmp_path: Path) -> None:
    report = _report(tmp_path / "report.json", oid="c" * 64)
    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
        repo_hint="github.com/example/project.git",
    )

    assert statement["target"]["oid"] == {"algorithm": "sha256", "value": "c" * 64}
    assert statement["repo_hint"] == "github.com/example/project"
    assert statement["report"]["digest"]["value"] == file_digest(report)
    assert canonical_json_bytes(statement) == canonical_json_bytes(statement)
    assert b"\n" not in canonical_json_bytes(statement)
    assert validate_attestation_statement(statement) == []

    statement["score"] = 99
    assert "unknown key" in "\n".join(validate_attestation_statement(statement))


def test_statement_creation_applies_the_packaged_draft_contract(tmp_path: Path) -> None:
    report = _report(tmp_path / "report.json")
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["schema_version"] = "report-evil"
    payload["provenance"]["tool_name"] = "not-grift"
    payload["provenance"]["tool_version"] = "not-semver"
    report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(AttestationError, match=r"\$\.schema_version|measurement.tool_name"):
        build_attestation_statement(
            report,
            expected_signer_policy={
                "kind": "ssh",
                "namespace": "grift-attestation-v1",
                "principal": "builder",
            },
            executed_at="2026-08-31T00:00:00Z",
        )


def test_report_v2_statement_binds_inputs_definitions_public_tagset_and_scope(
    tmp_path: Path,
) -> None:
    report = _report_v2(tmp_path / "report-v2.json")
    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
    )

    assert statement["scope"] == {"analysis_scope": "repo"}
    assert statement["inputs"]["members"] == {
        "forge": {"algorithm": "sha256", "value": "c" * 64},
        "public_evidence": {"algorithm": "sha256", "value": "b" * 64},
        "tagset": {"algorithm": "sha256", "value": "d" * 64},
        "tracker": None,
    }
    assert statement["public_evidence"] == {"digest": {"algorithm": "sha256", "value": "b" * 64}}
    assert statement["tagset"] == {"digest": {"algorithm": "sha256", "value": "d" * 64}}
    assert statement["definition_versions"]["digest"]["algorithm"] == "sha256"
    assert validate_attestation_statement(statement) == []

    # Aggregate membership and the two separately named inputs are closed
    # invariants, not documentation-only fields.
    statement["inputs"]["members"]["forge"]["value"] = "e" * 64
    assert "canonical members" in "\n".join(validate_attestation_statement(statement))
    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
    )
    statement["tagset"]["digest"]["value"] = "e" * 64
    errors = "\n".join(validate_attestation_statement(statement))
    assert "inputs.members.tagset" in errors

    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
    )
    statement["inputs"]["members"].pop("tagset")
    statement["tagset"]["digest"] = None
    errors = "\n".join(validate_attestation_statement(statement))
    assert "inputs.members.tagset: is required" in errors
    assert "tagset.digest: is required" in errors


@pytest.mark.parametrize(
    ("mutation", "detail"),
    (
        ("input", "input digests"),
        ("definition", "definition versions"),
        ("public", "public evidence"),
        ("tagset", "reachable tagset"),
        ("scope", "scope"),
    ),
)
def test_report_binding_checks_each_signed_condition_independently(
    tmp_path: Path,
    mutation: str,
    detail: str,
) -> None:
    report = _report_v2(tmp_path / "report-v2.json")
    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    provenance = payload["provenance"]
    if mutation == "input":
        provenance["input_digests"]["forge"] = "e" * 64
    elif mutation == "definition":
        provenance["origin_definition_version"] = "origin-v2"
    elif mutation == "public":
        provenance["public_evidence_digest"] = "e" * 64
        provenance["input_digests"]["public_evidence"] = "e" * 64
    elif mutation == "tagset":
        provenance["tagset_digest"] = "e" * 64
        provenance["input_digests"]["tagset"] = "e" * 64
    elif mutation == "scope":
        provenance["analysis_scope"] = "tenant"
        # Keep the legacy measurement copy aligned so this mutation reaches
        # the separately signed scope node.
        statement["measurement"]["analysis_scope"] = "tenant"
    report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    statement["report"]["digest"]["value"] = file_digest(report)
    if mutation in {"public", "tagset"}:
        rebound = build_attestation_statement(
            report,
            expected_signer_policy={
                "kind": "ssh",
                "namespace": "grift-attestation-v1",
                "principal": "builder",
            },
            executed_at="2026-08-31T00:00:00Z",
        )
        statement["inputs"] = rebound["inputs"]

    result = attest_module._verify_report_binding(statement, report)

    assert result.status == MISMATCH
    assert detail in result.detail


def test_schema_invalid_report_is_rejected_before_external_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(tmp_path / "report.json")
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["activity"]["tenant_commits"]["value"] = -1
    report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    private_key, _allowed = _ssh_material(tmp_path)
    called = False

    def unexpected_sign(_statement_path: Path, _signing: object) -> Path:
        nonlocal called
        called = True
        raise AssertionError("external signer must not receive a schema-invalid report")

    monkeypatch.setattr(attest_module, "_sign", unexpected_sign)

    with pytest.raises(AttestationError, match=r"activity\.tenant_commits\.value"):
        create_attestation_bundle(
            report,
            tmp_path / "bundle",
            signing=SSHSigningConfig(private_key, "trusted-builder"),
            executed_at="2026-08-31T00:00:00Z",
        )

    assert called is False
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("schema_version", ["report-v1", "report-v2"])
def test_binding_rejects_schema_mutation_even_when_statement_hash_is_updated(
    tmp_path: Path,
    schema_version: str,
) -> None:
    report = (
        _report(tmp_path / "report.json")
        if schema_version == "report-v1"
        else _report_v2(tmp_path / "report.json")
    )
    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    if schema_version == "report-v1":
        payload["activity"]["tenant_commits"]["unit"] = "bytes"
    else:
        payload["unknown_contract_key"] = "must-fail-closed"
    report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    statement["report"]["digest"]["value"] = file_digest(report)

    result = attest_module._verify_report_binding(statement, report)

    assert result.status == INVALID
    assert "report schema is invalid" in result.detail


def test_report_v1_additive_unknown_field_remains_signable(tmp_path: Path) -> None:
    report = _report(tmp_path / "report.json")
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["future_additive_field"] = {"version": 1}
    report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    statement = build_attestation_statement(
        report,
        expected_signer_policy={
            "kind": "ssh",
            "namespace": "grift-attestation-v1",
            "principal": "builder",
        },
        executed_at="2026-08-31T00:00:00Z",
    )

    assert statement["report"]["schema_version"] == "report-v1"
    assert statement["report"]["digest"]["value"] == file_digest(report)


def test_report_v2_unknown_key_is_rejected_before_statement_creation(tmp_path: Path) -> None:
    report = _report_v2(tmp_path / "report-v2.json")
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["unknown_contract_key"] = "must-fail-closed"
    report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(AttestationError, match="unknown key"):
        build_attestation_statement(
            report,
            expected_signer_policy={
                "kind": "ssh",
                "namespace": "grift-attestation-v1",
                "principal": "builder",
            },
            executed_at="2026-08-31T00:00:00Z",
        )


def test_real_ssh_signature_verifies_without_claiming_recomputation(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.statement.status == VERIFIED
    assert result.signature.status == VERIFIED
    assert result.report_hash.status == VERIFIED
    assert result.recompute.status == CANNOT_VERIFY
    assert result.overall == CANNOT_VERIFY


def test_real_ssh_signature_and_explicit_recomputation_verify_independently(
    tmp_path: Path,
) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    result = verify_attestation_bundle(
        bundle,
        report,
        trust_policy=trust,
        repo=repo,
        recompute=lambda _report_path, _repo: VerificationPart(VERIFIED, "exact fixture match"),
    )

    assert result.to_dict() == {
        "statement": {
            "status": VERIFIED,
            "detail": "statement schema and bundle digests verified",
        },
        "signature": {
            "status": VERIFIED,
            "detail": "detached signature and recipient trust policy verified",
        },
        "report_hash": {
            "status": VERIFIED,
            "detail": "report SHA-256 and signed metadata binding verified",
        },
        "recompute": {"status": VERIFIED, "detail": "exact fixture match"},
        "overall": VERIFIED,
    }


def test_statement_tamper_is_rejected_even_when_manifest_digest_is_rewritten(
    tmp_path: Path,
) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    path = bundle / "statement.json"
    statement = json.loads(path.read_text(encoding="utf-8"))
    statement["executed_at"] = "2026-08-31T01:02:04Z"
    path.write_bytes(canonical_json_bytes(statement))
    _rewrite_manifest_digest(bundle, "statement", file_digest(path))

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.statement.status == VERIFIED
    assert result.signature.status == INVALID
    assert result.report_hash.status == VERIFIED
    assert result.overall == MISMATCH


def test_signature_tamper_is_rejected(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    path = bundle / "statement.json.sig"
    path.write_bytes(path.read_bytes().replace(b"A", b"B", 1))
    _rewrite_manifest_digest(bundle, "signature", file_digest(path))

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.statement.status == VERIFIED
    assert result.signature.status == INVALID
    assert result.report_hash.status == VERIFIED
    assert result.recompute.status == CANNOT_VERIFY
    assert result.overall == MISMATCH


def test_unreadable_signature_does_not_suppress_report_or_recomputation(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (bundle / "statement.json.sig").unlink()

    result = verify_attestation_bundle(
        bundle,
        report,
        trust_policy=trust,
        repo=repo,
        recompute=lambda _report_path, _repo: VerificationPart(VERIFIED, "exact fixture match"),
    )

    assert result.statement.status == VERIFIED
    assert result.signature.status == INVALID
    assert result.report_hash.status == VERIFIED
    assert result.recompute.status == VERIFIED
    assert result.overall == MISMATCH


def test_load_and_verify_apply_draft_contract_to_externally_signed_statement(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path / "report.json")
    private_key, allowed = _ssh_material(tmp_path)
    bundle = tmp_path / "bundle"
    create_attestation_bundle(
        report,
        bundle,
        signing=SSHSigningConfig(private_key, "trusted-builder"),
        executed_at="2026-08-31T00:00:00Z",
    )
    statement_path = bundle / "statement.json"
    statement = json.loads(statement_path.read_text(encoding="utf-8"))
    statement["measurement"]["tool_name"] = "not-grift"
    statement_path.write_bytes(canonical_json_bytes(statement))
    signature_path = bundle / "statement.json.sig"
    signature_path.unlink()
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(private_key),
            "-n",
            "grift-attestation-v1",
            str(statement_path),
        ],
        check=True,
        capture_output=True,
    )
    os.chmod(signature_path, 0o600)
    _rewrite_manifest_digest(bundle, "statement", file_digest(statement_path))
    _rewrite_manifest_digest(bundle, "signature", file_digest(signature_path))

    with pytest.raises(AttestationError, match="measurement.tool_name"):
        load_attestation_bundle(bundle)

    repo = tmp_path / "repo"
    repo.mkdir()
    result = verify_attestation_bundle(
        bundle,
        report,
        trust_policy=SSHTrustPolicy(allowed, "trusted-builder"),
        repo=repo,
        recompute=lambda _report_path, _repo: VerificationPart(VERIFIED, "exact fixture match"),
    )
    assert result.statement.status == INVALID
    assert result.signature.status == VERIFIED
    assert result.report_hash.status == CANNOT_VERIFY
    assert result.recompute.status == VERIFIED
    assert result.overall == MISMATCH


def test_bundle_manifest_tamper_fails_closed(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    path = bundle / "bundle-manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unregistered"] = {"path": "other"}
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.statement.status == INVALID
    assert result.signature.status == INVALID
    assert result.report_hash.status == VERIFIED
    assert result.overall == MISMATCH


def test_unregistered_bundle_member_fails_closed(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    (bundle / "extra.json").write_text("{}", encoding="utf-8")

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.statement.status == INVALID
    assert "unregistered" in result.statement.detail


def test_bundle_create_rejects_parent_and_leaf_symlinks_without_escape(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path / "report.json")
    private_key, _allowed = _ssh_material(tmp_path)
    signing = SSHSigningConfig(private_key, "trusted-builder")
    outside = tmp_path / "outside"
    outside.mkdir()

    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AttestationError, match="parent must not be a symlink"):
        create_attestation_bundle(
            report,
            linked_parent / "bundle",
            signing=signing,
            executed_at="2026-08-31T00:00:00Z",
        )
    assert list(outside.iterdir()) == []

    leaf = tmp_path / "bundle-link"
    leaf.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AttestationError, match="already exists"):
        create_attestation_bundle(
            report,
            leaf,
            signing=signing,
            executed_at="2026-08-31T00:00:00Z",
        )
    assert list(outside.iterdir()) == []
    assert not any(path.name.startswith(".grift-attest-") for path in tmp_path.iterdir())


def test_bundle_load_rejects_lexical_parent_and_member_symlinks(tmp_path: Path) -> None:
    report = _report(tmp_path / "report.json")
    private_key, _allowed = _ssh_material(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    bundle = outside / "bundle"
    create_attestation_bundle(
        report,
        bundle,
        signing=SSHSigningConfig(private_key, "trusted-builder"),
        executed_at="2026-08-31T00:00:00Z",
    )

    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AttestationError, match="parent must not be a symlink"):
        load_attestation_bundle(linked_parent / "bundle")

    statement = bundle / "statement.json"
    original = statement.read_bytes()
    statement.unlink()
    victim = tmp_path / "victim.json"
    victim.write_bytes(original)
    statement.symlink_to(victim)
    with pytest.raises(AttestationError, match="cannot be opened|non-symlink"):
        load_attestation_bundle(bundle)


def test_bundle_modes_are_private_and_enforced_on_load(tmp_path: Path) -> None:
    _report_path, bundle, _trust = _signed_bundle(tmp_path)

    assert (bundle.stat().st_mode & 0o777) == 0o700
    assert all((member.stat().st_mode & 0o777) == 0o600 for member in bundle.iterdir())

    os.chmod(bundle, 0o755)
    with pytest.raises(AttestationError, match="permissions must be 0700"):
        load_attestation_bundle(bundle)
    os.chmod(bundle, 0o700)

    os.chmod(bundle / "statement.json", 0o644)
    with pytest.raises(AttestationError, match="permissions must be 0600"):
        load_attestation_bundle(bundle)


def test_report_tamper_does_not_change_signature_result(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["activity"]["tenant_commits"]["value"] = 400
    report.write_text(json.dumps(payload), encoding="utf-8")

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.signature.status == VERIFIED
    assert result.report_hash.status == MISMATCH
    assert result.overall == MISMATCH


def test_recipient_trust_policy_must_match_signed_policy(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    wrong = SSHTrustPolicy(trust.allowed_signers, "other-builder")

    result = verify_attestation_bundle(bundle, report, trust_policy=wrong)

    assert result.signature.status == MISMATCH
    assert "differs" in result.signature.detail
    assert result.report_hash.status == VERIFIED


def test_repository_mismatch_is_separate_from_signature_and_report_hash(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    result = verify_attestation_bundle(
        bundle,
        report,
        trust_policy=trust,
        repo=repo,
        recompute=lambda _report_path, _repo: MISMATCH,
    )

    assert result.signature.status == VERIFIED
    assert result.report_hash.status == VERIFIED
    assert result.recompute.status == MISMATCH
    assert result.overall == MISMATCH


def test_missing_cosign_is_reported_before_any_output_is_created(tmp_path: Path) -> None:
    report = _report(tmp_path / "report.json")
    output = tmp_path / "bundle"

    with pytest.raises(SigningToolUnavailable, match="unavailable"):
        create_attestation_bundle(
            report,
            output,
            signing=CosignSigningConfig(
                certificate_identity="https://github.com/example/project/.github/workflows/release.yml@refs/heads/main",
                certificate_oidc_issuer="https://token.actions.githubusercontent.com",
                cosign="cosign-command-that-does-not-exist",
            ),
            executed_at="2026-08-31T00:00:00Z",
        )
    assert not output.exists()


def test_cosign_keyless_invocation_binds_exact_recipient_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report(tmp_path / "report.json")
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        _label: str,
        *,
        input_bytes: bytes | None = None,
        timeout: int = 30,
    ) -> None:
        del input_bytes, timeout
        commands.append(command)
        if command[1] == "sign-blob":
            bundle_path = Path(command[command.index("--bundle") + 1])
            bundle_path.write_text('{"fake":"cosign-bundle"}', encoding="utf-8")

    monkeypatch.setattr(attest_module, "_require_executable", lambda _program: "/test/cosign")
    monkeypatch.setattr(attest_module, "_run_command", fake_run)
    identity = "https://github.com/example/project/.github/workflows/release.yml@refs/heads/main"
    issuer = "https://token.actions.githubusercontent.com"
    bundle = tmp_path / "bundle"

    create_attestation_bundle(
        report,
        bundle,
        signing=CosignSigningConfig(
            certificate_identity=identity,
            certificate_oidc_issuer=issuer,
        ),
        executed_at="2026-08-31T00:00:00Z",
    )
    result = verify_attestation_bundle(
        bundle,
        report,
        trust_policy=CosignTrustPolicy(
            certificate_identity=identity,
            certificate_oidc_issuer=issuer,
        ),
    )

    assert commands[0][1:4] == ["sign-blob", "--yes", "--bundle"]
    assert Path(commands[0][4]).name == "cosign.bundle.json"
    assert Path(commands[0][-1]).name == "statement.json"
    assert commands[1][1:4] == ["verify-blob", "--bundle", str(bundle / "cosign.bundle.json")]
    assert commands[1][4:8] == [
        "--certificate-identity",
        identity,
        "--certificate-oidc-issuer",
        issuer,
    ]
    assert result.signature.status == VERIFIED
    assert result.report_hash.status == VERIFIED


def test_noncanonical_statement_bytes_are_rejected_before_signature_check(tmp_path: Path) -> None:
    report, bundle, trust = _signed_bundle(tmp_path)
    statement = json.loads((bundle / "statement.json").read_text(encoding="utf-8"))
    path = bundle / "statement.json"
    path.write_text(json.dumps(statement, indent=2), encoding="utf-8")
    _rewrite_manifest_digest(bundle, "statement", file_digest(path))

    result = verify_attestation_bundle(bundle, report, trust_policy=trust)

    assert result.statement.status == INVALID
    assert "canonical JSON" in result.statement.detail


@pytest.mark.parametrize(
    "repo_hint",
    [
        "/Users/example/project",
        "https://token@example.com/org/repo",
        "git@example.com:org/repo",
        "github.com/../private",
    ],
)
def test_repo_hint_rejects_paths_credentials_and_parent_segments(
    tmp_path: Path, repo_hint: str
) -> None:
    report = _report(tmp_path / "report.json")
    with pytest.raises(AttestationError, match="repo_hint"):
        build_attestation_statement(
            report,
            expected_signer_policy={
                "kind": "ssh",
                "namespace": "grift-attestation-v1",
                "principal": "builder",
            },
            executed_at="2026-08-31T00:00:00Z",
            repo_hint=repo_hint,
        )
