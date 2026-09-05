"""Signed, deterministic attestations for Grift reports.

The statement is deliberately small and canonical.  Cryptographic signing is
delegated to OpenSSH or cosign; this module never implements a signature
primitive.  Verification keeps four independent results so that a valid
signature is never presented as proof that the measured values are correct.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from tep_core.digest import file_digest
from tep_core.secure_output import (
    SecureOutputError,
    create_private_directory_at,
    fsync_directory,
    open_secure_directory,
    open_secure_parent,
    read_private_at,
    remove_directory_at,
    require_absent_at,
    set_private_file_mode_at,
    validate_closed_directory_at,
    write_private_at,
)

ATTESTATION_SCHEMA_VERSION = "tep-attest-v1"
ATTESTATION_BUNDLE_SCHEMA_VERSION = "tep-attest-bundle-v1"
ATTESTATION_STATEMENT_TYPE = "grift-report-attestation"
SSH_NAMESPACE = "grift-attestation-v1"

VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
INVALID = "INVALID"
CANNOT_VERIFY = "CANNOT_VERIFY"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SAFE_PRINCIPAL_RE = re.compile(r"^[^\s,]{1,255}$")
_SAFE_HINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
_INPUT_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")

_STATEMENT_KEYS = frozenset(
    {
        "schema_version",
        "statement_type",
        "report",
        "target",
        "measurement",
        "scope",
        "inputs",
        "definition_versions",
        "public_evidence",
        "tagset",
        "runner_hint",
        "executed_at",
        "expected_signer_policy",
        "repo_hint",
    }
)
_REPORT_KEYS = frozenset({"schema_version", "digest"})
_TARGET_KEYS = frozenset({"oid"})
_MEASUREMENT_KEYS = frozenset({"tool_name", "tool_version", "definition_version", "analysis_scope"})
_SCOPE_KEYS = frozenset({"analysis_scope"})
_INPUTS_KEYS = frozenset({"aggregate_digest", "members"})
_DEFINITION_VERSIONS_KEYS = frozenset({"digest"})
_PUBLIC_EVIDENCE_KEYS = frozenset({"digest"})
_TAGSET_KEYS = frozenset({"digest"})
_DIGEST_KEYS = frozenset({"algorithm", "value"})
_OID_KEYS = frozenset({"algorithm", "value"})
_BUNDLE_KEYS = frozenset({"schema_version", "statement", "signature"})
_BUNDLE_FILE_KEYS = frozenset({"path", "digest"})
_BUNDLE_SIGNATURE_KEYS = frozenset({"kind", "path", "digest"})


class AttestationError(ValueError):
    """The attestation input, bundle, or external signer is invalid."""


class SigningToolUnavailable(AttestationError):
    """The explicitly selected external signing implementation is absent."""


@dataclass(frozen=True)
class SSHSigningConfig:
    private_key: Path
    principal: str
    ssh_keygen: str = "ssh-keygen"
    namespace: str = SSH_NAMESPACE


@dataclass(frozen=True)
class CosignSigningConfig:
    certificate_identity: str | None = None
    certificate_oidc_issuer: str | None = None
    key: Path | None = None
    public_key: Path | None = None
    cosign: str = "cosign"


SigningConfig = SSHSigningConfig | CosignSigningConfig


@dataclass(frozen=True)
class SSHTrustPolicy:
    allowed_signers: Path
    principal: str
    ssh_keygen: str = "ssh-keygen"
    namespace: str = SSH_NAMESPACE


@dataclass(frozen=True)
class CosignTrustPolicy:
    certificate_identity: str | None = None
    certificate_oidc_issuer: str | None = None
    public_key: Path | None = None
    cosign: str = "cosign"


TrustPolicy = SSHTrustPolicy | CosignTrustPolicy


@dataclass(frozen=True)
class VerificationPart:
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class AttestationVerification:
    statement: VerificationPart
    signature: VerificationPart
    report_hash: VerificationPart
    recompute: VerificationPart
    overall: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement.to_dict(),
            "signature": self.signature.to_dict(),
            "report_hash": self.report_hash.to_dict(),
            "recompute": self.recompute.to_dict(),
            "overall": self.overall,
        }


@dataclass(frozen=True)
class AttestationBundle:
    directory: Path
    statement_path: Path
    signature_path: Path
    manifest_path: Path
    statement: dict[str, Any]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class _VerificationBundleInspection:
    bundle: AttestationBundle | None
    statement: VerificationPart
    signature_integrity: VerificationPart
    statement_usable: bool


Recompute = Callable[[Path, Path], VerificationPart | str | bool]


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON and reject NaN/Infinity."""

    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AttestationError("attestation: value is not canonical JSON") from exc
    return text.encode("utf-8")


def normalize_repo_hint(value: str) -> str:
    """Validate an explicitly opted-in, credential-free repository hint."""

    original = value.strip()
    hint = original.strip("/").removesuffix(".git")
    if (
        original.startswith(("/", "~"))
        or not _SAFE_HINT_RE.fullmatch(hint)
        or "@" in hint
        or "\\" in hint
        or "//" in hint
        or any(part == ".." for part in hint.split("/"))
    ):
        raise AttestationError(
            "attestation: repo_hint must be a credential-free host/path, for example github.com/org/repo"
        )
    return hint


def ssh_signer_policy(principal: str, *, namespace: str = SSH_NAMESPACE) -> dict[str, str]:
    _validate_principal(principal)
    if namespace != SSH_NAMESPACE:
        raise AttestationError(f"attestation: SSH namespace must be {SSH_NAMESPACE}")
    return {"kind": "ssh", "namespace": namespace, "principal": principal}


def cosign_keyless_signer_policy(
    certificate_identity: str, certificate_oidc_issuer: str
) -> dict[str, str]:
    _validate_policy_text(certificate_identity, "certificate_identity")
    _validate_policy_text(certificate_oidc_issuer, "certificate_oidc_issuer")
    return {
        "kind": "cosign-keyless",
        "certificate_identity": certificate_identity,
        "certificate_oidc_issuer": certificate_oidc_issuer,
    }


def cosign_key_signer_policy(public_key: Path) -> dict[str, str]:
    _require_regular_file(public_key, "cosign public key")
    return {"kind": "cosign-key", "public_key_sha256": file_digest(public_key)}


def build_attestation_statement(
    report_path: Path,
    *,
    expected_signer_policy: Mapping[str, Any],
    executed_at: str | None = None,
    runner_hint: str = "grift attest",
    repo_hint: str | None = None,
) -> dict[str, Any]:
    """Bind a report's bytes and recorded measurement target into a statement."""

    report = _load_json_object(report_path, "report")
    report_errors = validate_attestable_report(report)
    if report_errors:
        raise AttestationError("attestation: report schema is invalid: " + "; ".join(report_errors))
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise AttestationError("attestation: report.provenance must be an object")
    report_schema = _required_text(report.get("schema_version"), "report.schema_version")
    input_members = _input_digest_members(provenance, report_schema=report_schema)
    public_evidence = _public_evidence_digest(provenance)
    tagset = _tagset_digest(provenance, report_schema=report_schema)
    if report_schema == "report-v2":
        if input_members.get("public_evidence") != public_evidence:
            raise AttestationError(
                "attestation: report-v2 public evidence digest differs from input_digests"
            )
        if input_members.get("tagset") != tagset:
            raise AttestationError(
                "attestation: report-v2 tagset digest differs from input_digests"
            )
    policy = dict(expected_signer_policy)
    _validate_signer_policy(policy)
    timestamp = executed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _validate_timestamp(timestamp)
    _validate_policy_text(runner_hint, "runner_hint")

    statement: dict[str, Any] = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "statement_type": ATTESTATION_STATEMENT_TYPE,
        "report": {
            "schema_version": report_schema,
            "digest": _sha256_digest(file_digest(report_path)),
        },
        "target": {"oid": _target_oid(provenance)},
        "measurement": {
            "tool_name": _required_text(provenance.get("tool_name"), "provenance.tool_name"),
            "tool_version": _required_text(
                provenance.get("tool_version"), "provenance.tool_version"
            ),
            "definition_version": _required_text(
                provenance.get("definition_version"), "provenance.definition_version"
            ),
            "analysis_scope": _required_text(
                provenance.get("analysis_scope"), "provenance.analysis_scope"
            ),
        },
        "scope": {
            "analysis_scope": _required_text(
                provenance.get("analysis_scope"), "provenance.analysis_scope"
            )
        },
        "inputs": {
            "aggregate_digest": _aggregate_input_digest(input_members),
            "members": input_members,
        },
        "definition_versions": {
            "digest": _definition_versions_digest(report),
        },
        "public_evidence": {"digest": public_evidence},
        "tagset": {"digest": tagset},
        "runner_hint": runner_hint,
        "executed_at": timestamp,
        "expected_signer_policy": policy,
    }
    if repo_hint is not None:
        statement["repo_hint"] = normalize_repo_hint(repo_hint)
    errors = validate_attestation_statement(statement)
    if errors:
        raise AttestationError("attestation statement invalid: " + "; ".join(errors))
    return statement


def create_attestation_bundle(
    report_path: Path,
    out_dir: Path,
    *,
    signing: SigningConfig,
    executed_at: str | None = None,
    runner_hint: str = "grift attest",
    repo_hint: str | None = None,
) -> AttestationBundle:
    """Create an atomic statement/signature bundle using an external signer."""

    _require_regular_file(report_path, "report")
    policy = _signing_policy(signing)
    statement = build_attestation_statement(
        report_path,
        expected_signer_policy=policy,
        executed_at=executed_at,
        runner_hint=runner_hint,
        repo_hint=repo_hint,
    )
    staging_name: str | None = None
    staging_fd = -1
    try:
        with open_secure_parent(out_dir, create=True) as parent:
            require_absent_at(parent.fd, parent.leaf)
            staging_name, staging_fd = create_private_directory_at(
                parent.fd, prefix=".grift-attest-"
            )
            staging_path = parent.path / staging_name
            statement_path = staging_path / "statement.json"
            statement_bytes = canonical_json_bytes(statement)
            write_private_at(staging_fd, statement_path.name, statement_bytes)
            signature_path = _sign(statement_path, signing)
            set_private_file_mode_at(staging_fd, signature_path.name)
            signature_bytes = read_private_at(staging_fd, signature_path.name)
            manifest = {
                "schema_version": ATTESTATION_BUNDLE_SCHEMA_VERSION,
                "statement": {
                    "path": statement_path.name,
                    "digest": _sha256_digest(hashlib.sha256(statement_bytes).hexdigest()),
                },
                "signature": {
                    "kind": policy["kind"],
                    "path": signature_path.name,
                    "digest": _sha256_digest(hashlib.sha256(signature_bytes).hexdigest()),
                },
            }
            manifest_path = staging_path / "bundle-manifest.json"
            write_private_at(staging_fd, manifest_path.name, canonical_json_bytes(manifest))
            validate_closed_directory_at(
                staging_fd,
                {statement_path.name, signature_path.name, manifest_path.name},
                required_file_mode=0o600,
            )
            fsync_directory(staging_fd)
            os.close(staging_fd)
            staging_fd = -1
            require_absent_at(parent.fd, parent.leaf)
            os.rename(
                staging_name,
                parent.leaf,
                src_dir_fd=parent.fd,
                dst_dir_fd=parent.fd,
            )
            staging_name = None
            fsync_directory(parent.fd)
            published = parent.path / parent.leaf
    except SecureOutputError as exc:
        raise AttestationError(f"attestation: {exc}") from exc
    except OSError as exc:
        raise AttestationError("attestation: bundle could not be published atomically") from exc
    finally:
        if staging_fd >= 0:
            os.close(staging_fd)
        if staging_name is not None:
            try:
                with open_secure_parent(out_dir, create=False) as parent:
                    remove_directory_at(parent.fd, staging_name)
            except (OSError, SecureOutputError):
                pass
    return load_attestation_bundle(published)


def load_attestation_bundle(bundle_dir: Path) -> AttestationBundle:
    """Load a bundle and verify its closed manifest and content digests."""

    try:
        with open_secure_directory(bundle_dir, required_mode=0o700) as opened:
            directory = opened.path
            manifest_path = directory / "bundle-manifest.json"
            manifest_bytes = read_private_at(opened.fd, manifest_path.name)
            manifest = _load_json_object_bytes(manifest_bytes, "bundle manifest")
            if manifest_bytes != canonical_json_bytes(manifest):
                raise AttestationError("attestation: bundle manifest is not canonical JSON")
            errors = validate_bundle_manifest(manifest)
            if errors:
                raise AttestationError("attestation bundle invalid: " + "; ".join(errors))
            statement_name = manifest["statement"]["path"]
            signature_name = manifest["signature"]["path"]
            expected_members = {"bundle-manifest.json", statement_name, signature_name}
            validate_closed_directory_at(opened.fd, expected_members, required_file_mode=0o600)
            statement_bytes = read_private_at(opened.fd, statement_name)
            signature_bytes = read_private_at(opened.fd, signature_name)
            if (
                hashlib.sha256(statement_bytes).hexdigest()
                != manifest["statement"]["digest"]["value"]
            ):
                raise AttestationError("attestation: statement digest mismatch")
            if (
                hashlib.sha256(signature_bytes).hexdigest()
                != manifest["signature"]["digest"]["value"]
            ):
                raise AttestationError("attestation: signature digest mismatch")
            statement = _load_json_object_bytes(statement_bytes, "statement")
            if statement_bytes != canonical_json_bytes(statement):
                raise AttestationError("attestation: statement is not canonical JSON")
            statement_errors = validate_attestation_statement(statement)
            if statement_errors:
                raise AttestationError(
                    "attestation statement invalid: " + "; ".join(statement_errors)
                )
            expected_kind = statement["expected_signer_policy"]["kind"]
            if manifest["signature"]["kind"] != expected_kind:
                raise AttestationError(
                    "attestation: signature kind differs from expected signer policy"
                )
            statement_path = directory / statement_name
            signature_path = directory / signature_name
    except SecureOutputError as exc:
        raise AttestationError(f"attestation: {exc}") from exc
    return AttestationBundle(
        directory=directory,
        statement_path=statement_path,
        signature_path=signature_path,
        manifest_path=manifest_path,
        statement=statement,
        manifest=manifest,
    )


def _inspect_attestation_bundle(bundle_dir: Path) -> _VerificationBundleInspection:
    """Read independently verifiable bundle parts without collapsing their status.

    ``load_attestation_bundle`` remains the strict all-or-nothing loader used by
    consumers that require a closed bundle. Verification needs a different
    boundary: a missing or corrupt detached signature must not prevent a valid
    statement from binding the supplied report, and neither failure may suppress
    an otherwise possible repository recomputation.
    """

    try:
        with open_secure_directory(bundle_dir, required_mode=0o700) as opened:
            directory = opened.path
            manifest_path = directory / "bundle-manifest.json"
            manifest: dict[str, Any] = {}
            manifest_error: str | None = None
            try:
                manifest_bytes = read_private_at(opened.fd, manifest_path.name)
                manifest = _load_json_object_bytes(manifest_bytes, "bundle manifest")
                if manifest_bytes != canonical_json_bytes(manifest):
                    raise AttestationError("attestation: bundle manifest is not canonical JSON")
                manifest_errors = validate_bundle_manifest(manifest)
                if manifest_errors:
                    raise AttestationError(
                        "attestation bundle invalid: " + "; ".join(manifest_errors)
                    )
            except (AttestationError, SecureOutputError) as exc:
                manifest_error = str(exc)
                manifest = {}

            statement_path = directory / "statement.json"
            try:
                statement_bytes = read_private_at(opened.fd, statement_path.name)
                statement = _load_json_object_bytes(statement_bytes, "statement")
                if statement_bytes != canonical_json_bytes(statement):
                    raise AttestationError("attestation: statement is not canonical JSON")
            except (AttestationError, SecureOutputError) as exc:
                return _VerificationBundleInspection(
                    bundle=None,
                    statement=VerificationPart(INVALID, str(exc)),
                    signature_integrity=VerificationPart(
                        CANNOT_VERIFY, "readable signed statement unavailable"
                    ),
                    statement_usable=False,
                )

            statement_errors = validate_attestation_statement(statement)
            statement_usable = not statement_errors
            if statement_errors:
                statement_part = VerificationPart(
                    INVALID, "attestation statement invalid: " + "; ".join(statement_errors)
                )
            elif manifest_error is not None:
                statement_part = VerificationPart(INVALID, manifest_error)
            elif (
                hashlib.sha256(statement_bytes).hexdigest()
                != manifest["statement"]["digest"]["value"]
            ):
                statement_part = VerificationPart(INVALID, "attestation: statement digest mismatch")
            else:
                try:
                    actual_names = set(os.listdir(opened.fd))
                except OSError:
                    statement_part = VerificationPart(
                        INVALID, "attestation: bundle directory cannot be enumerated"
                    )
                else:
                    policy = statement.get("expected_signer_policy")
                    kind = policy.get("kind") if isinstance(policy, dict) else None
                    signature_name = "statement.json.sig" if kind == "ssh" else "cosign.bundle.json"
                    expected_names = {
                        "bundle-manifest.json",
                        "statement.json",
                        signature_name,
                    }
                    extras = actual_names - expected_names
                    if extras:
                        statement_part = VerificationPart(
                            INVALID,
                            "attestation: bundle directory contains unregistered members",
                        )
                    else:
                        statement_part = VerificationPart(
                            VERIFIED, "statement schema and bundle digests verified"
                        )

            policy = statement.get("expected_signer_policy")
            try:
                _validate_signer_policy(policy)
            except AttestationError as exc:
                return _VerificationBundleInspection(
                    bundle=None,
                    statement=statement_part,
                    signature_integrity=VerificationPart(CANNOT_VERIFY, str(exc)),
                    statement_usable=statement_usable,
                )
            kind = policy["kind"]
            signature_name = "statement.json.sig" if kind == "ssh" else "cosign.bundle.json"
            signature_path = directory / signature_name
            if manifest_error is not None:
                signature_integrity = VerificationPart(INVALID, manifest_error)
            else:
                try:
                    signature_bytes = read_private_at(opened.fd, signature_name)
                    if not signature_bytes:
                        raise AttestationError("attestation: detached signature is empty")
                except (AttestationError, SecureOutputError) as exc:
                    signature_integrity = VerificationPart(INVALID, str(exc))
                else:
                    if (
                        manifest["signature"]["kind"] != kind
                        or manifest["signature"]["path"] != signature_name
                    ):
                        signature_integrity = VerificationPart(
                            INVALID, "attestation: signature metadata differs from signed policy"
                        )
                    elif (
                        hashlib.sha256(signature_bytes).hexdigest()
                        != manifest["signature"]["digest"]["value"]
                    ):
                        signature_integrity = VerificationPart(
                            INVALID, "attestation: signature digest mismatch"
                        )
                    else:
                        signature_integrity = VerificationPart(
                            VERIFIED, "detached signature bytes and metadata are readable"
                        )

            bundle = AttestationBundle(
                directory=directory,
                statement_path=statement_path,
                signature_path=signature_path,
                manifest_path=manifest_path,
                statement=statement,
                manifest=manifest,
            )
    except SecureOutputError as exc:
        return _VerificationBundleInspection(
            bundle=None,
            statement=VerificationPart(INVALID, f"attestation: {exc}"),
            signature_integrity=VerificationPart(INVALID, "bundle directory is unavailable"),
            statement_usable=False,
        )
    return _VerificationBundleInspection(
        bundle=bundle,
        statement=statement_part,
        signature_integrity=signature_integrity,
        statement_usable=statement_usable,
    )


def verify_attestation_bundle(
    bundle_dir: Path,
    report_path: Path | None,
    *,
    trust_policy: TrustPolicy | None,
    repo: Path | None = None,
    recompute: Recompute | None = None,
) -> AttestationVerification:
    """Verify schema, signature, report hash, and repository independently."""

    recompute_part = _verify_recompute(report_path, repo, recompute)
    inspection = _inspect_attestation_bundle(bundle_dir)
    bundle = inspection.bundle
    if bundle is None:
        return _verification_result(
            statement=inspection.statement,
            signature=inspection.signature_integrity,
            report_hash=VerificationPart(CANNOT_VERIFY, "validated statement unavailable"),
            recompute=recompute_part,
        )

    if inspection.signature_integrity.status == VERIFIED:
        signature_part = _verify_signature(bundle, trust_policy)
    else:
        signature_part = inspection.signature_integrity
    report_part = (
        _verify_report_binding(bundle.statement, report_path)
        if inspection.statement_usable
        else VerificationPart(CANNOT_VERIFY, "validated statement unavailable")
    )
    return _verification_result(
        statement=inspection.statement,
        signature=signature_part,
        report_hash=report_part,
        recompute=recompute_part,
    )


def validate_attestation_statement(statement: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(statement, dict):
        return ["$: must be an object"]
    _closed_keys(statement, _STATEMENT_KEYS, "$", errors, optional={"repo_hint"})
    if statement.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        errors.append(f"$.schema_version: must be {ATTESTATION_SCHEMA_VERSION}")
    if statement.get("statement_type") != ATTESTATION_STATEMENT_TYPE:
        errors.append(f"$.statement_type: must be {ATTESTATION_STATEMENT_TYPE}")
    _validate_report_node(statement.get("report"), errors)
    _validate_target_node(statement.get("target"), errors)
    _validate_measurement_node(statement.get("measurement"), errors)
    _validate_scope_node(statement.get("scope"), errors)
    _validate_inputs_node(statement.get("inputs"), errors)
    _validate_definition_versions_node(statement.get("definition_versions"), errors)
    _validate_public_evidence_node(statement.get("public_evidence"), errors)
    _validate_tagset_node(statement.get("tagset"), errors)
    measurement = statement.get("measurement")
    scope = statement.get("scope")
    if isinstance(measurement, dict) and isinstance(scope, dict):
        if measurement.get("analysis_scope") != scope.get("analysis_scope"):
            errors.append("$.scope.analysis_scope: must equal $.measurement.analysis_scope")
    report = statement.get("report")
    inputs = statement.get("inputs")
    public_evidence = statement.get("public_evidence")
    tagset = statement.get("tagset")
    if (
        isinstance(report, dict)
        and report.get("schema_version") == "report-v2"
        and isinstance(inputs, dict)
        and isinstance(inputs.get("members"), dict)
    ):
        members = inputs["members"]
        if "public_evidence" not in members:
            errors.append("$.inputs.members.public_evidence: is required for report-v2")
        if "tagset" not in members:
            errors.append("$.inputs.members.tagset: is required for report-v2")
        if isinstance(public_evidence, dict) and members.get(
            "public_evidence"
        ) != public_evidence.get("digest"):
            errors.append("$.inputs.members.public_evidence: must equal $.public_evidence.digest")
        if isinstance(tagset, dict) and members.get("tagset") != tagset.get("digest"):
            errors.append("$.inputs.members.tagset: must equal $.tagset.digest")
        if isinstance(tagset, dict) and tagset.get("digest") is None:
            errors.append("$.tagset.digest: is required for report-v2")
    try:
        _validate_policy_text(statement.get("runner_hint"), "runner_hint")
    except AttestationError as exc:
        errors.append(f"$.runner_hint: {exc}")
    try:
        _validate_timestamp(statement.get("executed_at"))
    except AttestationError as exc:
        errors.append(f"$.executed_at: {exc}")
    policy = statement.get("expected_signer_policy")
    try:
        _validate_signer_policy(policy)
    except AttestationError as exc:
        errors.append(f"$.expected_signer_policy: {exc}")
    if "repo_hint" in statement:
        try:
            normalize_repo_hint(statement["repo_hint"])
        except (AttestationError, AttributeError) as exc:
            errors.append(f"$.repo_hint: {exc}")
    _append_contract_schema_errors("attest-v1", statement, errors)
    return errors


def validate_attestable_report(report: Any) -> list[str]:
    """Validate a report before it can be signed or accepted as bound.

    ``report-v1`` remains additive by contract, so its compatibility validator
    checks every known field that is present without requiring newer optional
    sections.  ``report-v2`` is a closed Draft 2020-12 contract and therefore
    rejects unknown fields as well as broken arithmetic invariants.
    """

    if not isinstance(report, dict):
        return ["$: report must be a JSON object"]
    schema_version = report.get("schema_version")
    if schema_version == "report-v1":
        from tep_core.schema import validate_report

        return validate_report(report, subset=True)
    if schema_version == "report-v2":
        from tep_core.schema import validate_schema

        return validate_schema("report-v2", report)
    return ["$.schema_version: must be 'report-v1' or 'report-v2'"]


def validate_bundle_manifest(manifest: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["$: must be an object"]
    _closed_keys(manifest, _BUNDLE_KEYS, "$", errors)
    if manifest.get("schema_version") != ATTESTATION_BUNDLE_SCHEMA_VERSION:
        errors.append(f"$.schema_version: must be {ATTESTATION_BUNDLE_SCHEMA_VERSION}")
    for key, allowed in (("statement", _BUNDLE_FILE_KEYS), ("signature", _BUNDLE_SIGNATURE_KEYS)):
        node = manifest.get(key)
        if not isinstance(node, dict):
            errors.append(f"$.{key}: must be an object")
            continue
        _closed_keys(node, allowed, f"$.{key}", errors)
        path = node.get("path")
        if not isinstance(path, str) or path not in {
            "statement.json",
            "statement.json.sig",
            "cosign.bundle.json",
        }:
            errors.append(f"$.{key}.path: unsupported bundle filename")
        _validate_digest_node(node.get("digest"), f"$.{key}.digest", errors)
    signature = manifest.get("signature")
    if isinstance(signature, dict) and signature.get("kind") not in {
        "ssh",
        "cosign-keyless",
        "cosign-key",
    }:
        errors.append("$.signature.kind: unsupported")
    if isinstance(manifest.get("statement"), dict):
        if manifest["statement"].get("path") != "statement.json":
            errors.append("$.statement.path: must be statement.json")
    if isinstance(signature, dict):
        kind = signature.get("kind")
        expected_path = "statement.json.sig" if kind == "ssh" else "cosign.bundle.json"
        if signature.get("path") != expected_path:
            errors.append(f"$.signature.path: must be {expected_path}")
    _append_contract_schema_errors("attest-bundle-v1", manifest, errors)
    return errors


def _append_contract_schema_errors(name: str, payload: Any, errors: list[str]) -> None:
    """Apply the packaged Draft 2020-12 contract in addition to runtime invariants."""

    from tep_core.schema import validate_schema

    for error in validate_schema(name, payload):
        if error not in errors:
            errors.append(error)


def _signing_policy(signing: SigningConfig) -> dict[str, str]:
    if isinstance(signing, SSHSigningConfig):
        _require_secret_key(signing.private_key, "SSH private key")
        _require_executable(signing.ssh_keygen)
        return ssh_signer_policy(signing.principal, namespace=signing.namespace)
    _require_executable(signing.cosign)
    if signing.key is None:
        if not signing.certificate_identity or not signing.certificate_oidc_issuer:
            raise AttestationError(
                "attestation: keyless cosign requires expected certificate identity and issuer"
            )
        return cosign_keyless_signer_policy(
            signing.certificate_identity, signing.certificate_oidc_issuer
        )
    if signing.public_key is None:
        raise AttestationError("attestation: keyful cosign requires a public key trust anchor")
    _require_secret_key(signing.key, "cosign private key")
    return cosign_key_signer_policy(signing.public_key)


def _sign(statement_path: Path, signing: SigningConfig) -> Path:
    if isinstance(signing, SSHSigningConfig):
        command = [
            _require_executable(signing.ssh_keygen),
            "-Y",
            "sign",
            "-f",
            str(signing.private_key),
            "-n",
            signing.namespace,
            str(statement_path),
        ]
        _run_command(command, "ssh-keygen signing")
        signature = statement_path.with_suffix(statement_path.suffix + ".sig")
    else:
        signature = statement_path.parent / "cosign.bundle.json"
        command = [
            _require_executable(signing.cosign),
            "sign-blob",
            "--yes",
            "--bundle",
            str(signature),
        ]
        if signing.key is not None:
            command.extend(["--key", str(signing.key)])
        command.append(str(statement_path))
        _run_command(command, "cosign signing", timeout=120)
    if not signature.is_file() or signature.stat().st_size == 0:
        raise AttestationError("attestation: external signer did not create a detached signature")
    return signature


def _verify_signature(
    bundle: AttestationBundle, trust_policy: TrustPolicy | None
) -> VerificationPart:
    expected = bundle.statement["expected_signer_policy"]
    if trust_policy is None:
        return VerificationPart(CANNOT_VERIFY, "recipient trust policy was not supplied")
    try:
        actual = _trust_policy_payload(trust_policy)
    except AttestationError as exc:
        return VerificationPart(CANNOT_VERIFY, str(exc))
    if actual != expected:
        return VerificationPart(MISMATCH, "recipient trust policy differs from signed policy")

    if isinstance(trust_policy, SSHTrustPolicy):
        try:
            executable = _require_executable(trust_policy.ssh_keygen)
            _require_regular_file(trust_policy.allowed_signers, "SSH allowed_signers")
        except AttestationError as exc:
            return VerificationPart(CANNOT_VERIFY, str(exc))
        command = [
            executable,
            "-Y",
            "verify",
            "-f",
            str(trust_policy.allowed_signers),
            "-I",
            trust_policy.principal,
            "-n",
            trust_policy.namespace,
            "-s",
            str(bundle.signature_path),
        ]
    else:
        try:
            executable = _require_executable(trust_policy.cosign)
        except AttestationError as exc:
            return VerificationPart(CANNOT_VERIFY, str(exc))
        command = [executable, "verify-blob", "--bundle", str(bundle.signature_path)]
        if trust_policy.public_key is not None:
            command.extend(["--key", str(trust_policy.public_key)])
        else:
            command.extend(
                [
                    "--certificate-identity",
                    str(trust_policy.certificate_identity),
                    "--certificate-oidc-issuer",
                    str(trust_policy.certificate_oidc_issuer),
                ]
            )
        command.append(str(bundle.statement_path))
    try:
        _run_command(
            command,
            "signature verification",
            input_bytes=(
                bundle.statement_path.read_bytes()
                if isinstance(trust_policy, SSHTrustPolicy)
                else None
            ),
        )
    except AttestationError:
        return VerificationPart(INVALID, "external verifier rejected the detached signature")
    return VerificationPart(VERIFIED, "detached signature and recipient trust policy verified")


def _trust_policy_payload(policy: TrustPolicy) -> dict[str, str]:
    if isinstance(policy, SSHTrustPolicy):
        return ssh_signer_policy(policy.principal, namespace=policy.namespace)
    if policy.public_key is not None:
        return cosign_key_signer_policy(policy.public_key)
    if not policy.certificate_identity or not policy.certificate_oidc_issuer:
        raise AttestationError(
            "attestation: cosign trust requires a public key or exact certificate identity and issuer"
        )
    return cosign_keyless_signer_policy(policy.certificate_identity, policy.certificate_oidc_issuer)


def _verify_report_binding(
    statement: Mapping[str, Any], report_path: Path | None
) -> VerificationPart:
    if report_path is None or not report_path.is_file():
        return VerificationPart(CANNOT_VERIFY, "report file was not supplied")
    expected_digest = statement["report"]["digest"]["value"]
    try:
        report = _load_json_object(report_path, "report")
        report_errors = validate_attestable_report(report)
        if report_errors:
            raise AttestationError(
                "attestation: report schema is invalid: " + "; ".join(report_errors)
            )
        provenance = report.get("provenance")
        if not isinstance(provenance, dict):
            raise AttestationError("attestation: report.provenance must be an object")
        if file_digest(report_path) != expected_digest:
            return VerificationPart(MISMATCH, "report SHA-256 differs from signed statement")
        if report.get("schema_version") != statement["report"]["schema_version"]:
            return VerificationPart(MISMATCH, "report schema differs from signed statement")
        if _target_oid(provenance) != statement["target"]["oid"]:
            return VerificationPart(MISMATCH, "report target OID differs from signed statement")
        observed_measurement = {
            "tool_name": provenance.get("tool_name"),
            "tool_version": provenance.get("tool_version"),
            "definition_version": provenance.get("definition_version"),
            "analysis_scope": provenance.get("analysis_scope"),
        }
        if observed_measurement != statement["measurement"]:
            return VerificationPart(MISMATCH, "report measurement contract differs from statement")
        observed_scope = {"analysis_scope": provenance.get("analysis_scope")}
        if observed_scope != statement["scope"]:
            return VerificationPart(MISMATCH, "report scope differs from statement")
        report_schema = str(report.get("schema_version") or "")
        input_members = _input_digest_members(provenance, report_schema=report_schema)
        observed_inputs = {
            "aggregate_digest": _aggregate_input_digest(input_members),
            "members": input_members,
        }
        if observed_inputs != statement["inputs"]:
            return VerificationPart(MISMATCH, "report input digests differ from statement")
        observed_definitions = {"digest": _definition_versions_digest(report)}
        if observed_definitions != statement["definition_versions"]:
            return VerificationPart(MISMATCH, "report definition versions differ from statement")
        if _public_evidence_digest(provenance) != statement["public_evidence"]["digest"]:
            return VerificationPart(MISMATCH, "report public evidence differs from statement")
        if _tagset_digest(provenance, report_schema=report_schema) != statement["tagset"]["digest"]:
            return VerificationPart(MISMATCH, "report reachable tagset differs from statement")
    except AttestationError as exc:
        return VerificationPart(INVALID, str(exc))
    return VerificationPart(VERIFIED, "report SHA-256 and signed metadata binding verified")


def _verify_recompute(
    report_path: Path | None, repo: Path | None, recompute: Recompute | None
) -> VerificationPart:
    if report_path is None or not report_path.is_file():
        return VerificationPart(CANNOT_VERIFY, "report file was not supplied")
    if repo is None:
        return VerificationPart(CANNOT_VERIFY, "target repository was not supplied")
    if not repo.exists():
        return VerificationPart(CANNOT_VERIFY, "target repository is unavailable")
    try:
        result = (
            recompute(report_path, repo)
            if recompute is not None
            else _default_recompute(report_path, repo)
        )
    except Exception as exc:  # noqa: BLE001 - adapter boundary; never crash verification
        return VerificationPart(
            CANNOT_VERIFY, f"repository recomputation failed: {type(exc).__name__}"
        )
    if isinstance(result, VerificationPart):
        return result
    if result is True or result == VERIFIED:
        return VerificationPart(VERIFIED, "repository recomputation matched")
    if result is False or result == MISMATCH:
        return VerificationPart(MISMATCH, "repository recomputation differed")
    if result == CANNOT_VERIFY:
        return VerificationPart(CANNOT_VERIFY, "repository recomputation could not be completed")
    return VerificationPart(CANNOT_VERIFY, "repository verifier returned an unsupported result")


def _default_recompute(report_path: Path, repo: Path) -> VerificationPart:
    from tep_core.verify import verify_report

    result = verify_report(report_path, repo)
    detail = "; ".join(result.differences or result.notes) or "repository verification completed"
    if result.status == VERIFIED:
        return VerificationPart(VERIFIED, detail)
    if result.status == MISMATCH:
        return VerificationPart(MISMATCH, detail)
    return VerificationPart(CANNOT_VERIFY, detail)


def _verification_result(
    *,
    statement: VerificationPart,
    signature: VerificationPart,
    report_hash: VerificationPart,
    recompute: VerificationPart,
) -> AttestationVerification:
    statuses = {statement.status, signature.status, report_hash.status, recompute.status}
    if statuses & {MISMATCH, INVALID}:
        overall = MISMATCH
    elif CANNOT_VERIFY in statuses:
        overall = CANNOT_VERIFY
    else:
        overall = VERIFIED
    return AttestationVerification(statement, signature, report_hash, recompute, overall)


def _target_oid(provenance: Mapping[str, Any]) -> dict[str, str]:
    raw = provenance.get("target_oid")
    if raw is None:
        raw = provenance.get("analyzed_commit_oid")
    if raw is None:
        raw = provenance.get("analyzed_commit_sha")
    if isinstance(raw, str):
        algorithm = (
            "sha1" if _SHA1_RE.fullmatch(raw) else "sha256" if _SHA256_RE.fullmatch(raw) else ""
        )
        raw = {"algorithm": algorithm, "value": raw}
    errors: list[str] = []
    _validate_oid_node(raw, "provenance.target_oid", errors)
    if errors:
        raise AttestationError("attestation: " + "; ".join(errors))
    return {"algorithm": raw["algorithm"], "value": raw["value"]}


def _public_evidence_digest(provenance: Mapping[str, Any]) -> dict[str, str] | None:
    raw: Any = provenance.get("public_evidence_digest")
    if raw is None and isinstance(provenance.get("public_evidence"), dict):
        raw = provenance["public_evidence"].get("digest")
    return _normalize_digest(raw, "provenance.public_evidence_digest")


def _tagset_digest(provenance: Mapping[str, Any], *, report_schema: str) -> dict[str, str] | None:
    raw = provenance.get("tagset_digest")
    if raw is None and report_schema == "report-v2":
        raise AttestationError("attestation: report-v2 provenance.tagset_digest is required")
    return _normalize_digest(raw, "provenance.tagset_digest")


def _input_digest_members(
    provenance: Mapping[str, Any], *, report_schema: str
) -> dict[str, dict[str, str] | None]:
    raw = provenance.get("input_digests")
    if raw is None:
        if report_schema == "report-v2":
            raise AttestationError("attestation: report-v2 provenance.input_digests is required")
        return {}
    if not isinstance(raw, Mapping):
        raise AttestationError("attestation: provenance.input_digests must be an object")
    members: dict[str, dict[str, str] | None] = {}
    for key in sorted(raw):
        if not isinstance(key, str) or _INPUT_NAME_RE.fullmatch(key) is None:
            raise AttestationError("attestation: provenance.input_digests has an invalid key")
        members[key] = _normalize_digest(raw[key], f"provenance.input_digests.{key}")
    if report_schema == "report-v2" and "tagset" not in members:
        raise AttestationError("attestation: report-v2 input_digests.tagset is required")
    return members


def _aggregate_input_digest(
    members: Mapping[str, dict[str, str] | None],
) -> dict[str, str]:
    encoded = canonical_json_bytes({"members": dict(members)})
    value = hashlib.sha256(b"tep-attest-input-digests-v1\0" + encoded).hexdigest()
    return _sha256_digest(value)


def _definition_versions_digest(report: Mapping[str, Any]) -> dict[str, str]:
    members: dict[str, str] = {}
    _collect_definition_versions(report, "", members)
    if "/provenance/definition_version" not in members:
        raise AttestationError("attestation: provenance.definition_version is required")
    encoded = canonical_json_bytes({"members": members})
    value = hashlib.sha256(b"tep-attest-definition-versions-v1\0" + encoded).hexdigest()
    return _sha256_digest(value)


def _collect_definition_versions(node: Any, path: str, members: dict[str, str]) -> None:
    if isinstance(node, Mapping):
        for key in sorted(node):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            child_path = f"{path}/{escaped}"
            value = node[key]
            if key == "definition_version" or str(key).endswith("_definition_version"):
                if (
                    not isinstance(value, str)
                    or not value
                    or any(char in value for char in "\r\n\0")
                ):
                    raise AttestationError(f"attestation: {child_path} must be a version string")
                members[child_path] = value
            _collect_definition_versions(value, child_path, members)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _collect_definition_versions(value, f"{path}/{index}", members)


def _normalize_digest(raw: Any, path: str) -> dict[str, str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = _sha256_digest(raw)
    errors: list[str] = []
    _validate_digest_node(raw, path, errors)
    if errors:
        raise AttestationError("attestation: " + "; ".join(errors))
    return {"algorithm": "sha256", "value": raw["value"]}


def _validate_report_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.report: must be an object")
        return
    _closed_keys(node, _REPORT_KEYS, "$.report", errors)
    if not isinstance(node.get("schema_version"), str) or not node.get("schema_version"):
        errors.append("$.report.schema_version: required string")
    _validate_digest_node(node.get("digest"), "$.report.digest", errors)


def _validate_target_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.target: must be an object")
        return
    _closed_keys(node, _TARGET_KEYS, "$.target", errors)
    _validate_oid_node(node.get("oid"), "$.target.oid", errors)


def _validate_measurement_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.measurement: must be an object")
        return
    _closed_keys(node, _MEASUREMENT_KEYS, "$.measurement", errors)
    for key in sorted(_MEASUREMENT_KEYS):
        if not isinstance(node.get(key), str) or not node.get(key):
            errors.append(f"$.measurement.{key}: required string")


def _validate_scope_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.scope: must be an object")
        return
    _closed_keys(node, _SCOPE_KEYS, "$.scope", errors)
    if node.get("analysis_scope") not in {"repo", "tenant", "actor_cluster"}:
        errors.append("$.scope.analysis_scope: must be repo, tenant, or actor_cluster")


def _validate_inputs_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.inputs: must be an object")
        return
    _closed_keys(node, _INPUTS_KEYS, "$.inputs", errors)
    _validate_digest_node(node.get("aggregate_digest"), "$.inputs.aggregate_digest", errors)
    members = node.get("members")
    if not isinstance(members, dict):
        errors.append("$.inputs.members: must be an object")
        return
    normalized: dict[str, dict[str, str] | None] = {}
    for key, value in members.items():
        if not isinstance(key, str) or _INPUT_NAME_RE.fullmatch(key) is None:
            errors.append(f"$.inputs.members.{key}: invalid input digest name")
            continue
        if value is not None:
            _validate_digest_node(value, f"$.inputs.members.{key}", errors)
        normalized[key] = value
    try:
        expected = _aggregate_input_digest(normalized)
    except AttestationError as exc:
        errors.append(f"$.inputs.aggregate_digest: {exc}")
    else:
        if node.get("aggregate_digest") != expected:
            errors.append("$.inputs.aggregate_digest: does not match canonical members")


def _validate_definition_versions_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.definition_versions: must be an object")
        return
    _closed_keys(node, _DEFINITION_VERSIONS_KEYS, "$.definition_versions", errors)
    _validate_digest_node(node.get("digest"), "$.definition_versions.digest", errors)


def _validate_public_evidence_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.public_evidence: must be an object")
        return
    _closed_keys(node, _PUBLIC_EVIDENCE_KEYS, "$.public_evidence", errors)
    if node.get("digest") is not None:
        _validate_digest_node(node.get("digest"), "$.public_evidence.digest", errors)


def _validate_tagset_node(node: Any, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append("$.tagset: must be an object")
        return
    _closed_keys(node, _TAGSET_KEYS, "$.tagset", errors)
    if node.get("digest") is not None:
        _validate_digest_node(node.get("digest"), "$.tagset.digest", errors)


def _validate_digest_node(node: Any, path: str, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append(f"{path}: must be an object")
        return
    _closed_keys(node, _DIGEST_KEYS, path, errors)
    if node.get("algorithm") != "sha256":
        errors.append(f"{path}.algorithm: must be sha256")
    if not isinstance(node.get("value"), str) or not _SHA256_RE.fullmatch(node["value"]):
        errors.append(f"{path}.value: must be 64 lowercase hex characters")


def _validate_oid_node(node: Any, path: str, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append(f"{path}: must be an object")
        return
    _closed_keys(node, _OID_KEYS, path, errors)
    algorithm = node.get("algorithm")
    value = node.get("value")
    if algorithm not in {"sha1", "sha256"}:
        errors.append(f"{path}.algorithm: must be sha1 or sha256")
    pattern = _SHA1_RE if algorithm == "sha1" else _SHA256_RE if algorithm == "sha256" else None
    if pattern is None or not isinstance(value, str) or not pattern.fullmatch(value):
        errors.append(f"{path}.value: does not match {algorithm or 'declared'}")


def _validate_signer_policy(policy: Any) -> None:
    if not isinstance(policy, dict):
        raise AttestationError("must be an object")
    kind = policy.get("kind")
    if kind == "ssh":
        required = frozenset({"kind", "namespace", "principal"})
        _raise_unknown_or_missing(policy, required, "SSH signer policy")
        if policy.get("namespace") != SSH_NAMESPACE:
            raise AttestationError(f"SSH namespace must be {SSH_NAMESPACE}")
        _validate_principal(policy.get("principal"))
    elif kind == "cosign-keyless":
        required = frozenset({"kind", "certificate_identity", "certificate_oidc_issuer"})
        _raise_unknown_or_missing(policy, required, "cosign keyless signer policy")
        _validate_policy_text(policy.get("certificate_identity"), "certificate_identity")
        _validate_policy_text(policy.get("certificate_oidc_issuer"), "certificate_oidc_issuer")
    elif kind == "cosign-key":
        required = frozenset({"kind", "public_key_sha256"})
        _raise_unknown_or_missing(policy, required, "cosign key signer policy")
        if not isinstance(policy.get("public_key_sha256"), str) or not _SHA256_RE.fullmatch(
            policy["public_key_sha256"]
        ):
            raise AttestationError("public_key_sha256 must be 64 lowercase hex characters")
    else:
        raise AttestationError("unsupported signer policy kind")


def _closed_keys(
    node: Mapping[str, Any],
    allowed: frozenset[str],
    path: str,
    errors: list[str],
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    for key in sorted(set(node) - allowed):
        errors.append(f"{path}.{key}: unknown key")
    for key in sorted(allowed - optional - set(node)):
        errors.append(f"{path}.{key}: required")


def _raise_unknown_or_missing(
    node: Mapping[str, Any], required: frozenset[str], label: str
) -> None:
    unknown = set(node) - required
    missing = required - set(node)
    if unknown:
        raise AttestationError(f"{label} has unknown keys: {', '.join(sorted(unknown))}")
    if missing:
        raise AttestationError(f"{label} is missing keys: {', '.join(sorted(missing))}")


def _validate_principal(value: Any) -> None:
    if not isinstance(value, str) or not _SAFE_PRINCIPAL_RE.fullmatch(value):
        raise AttestationError("SSH principal must be a non-whitespace token without commas")


def _validate_policy_text(value: Any, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or any(char in value for char in "\r\n\0")
    ):
        raise AttestationError(f"{name} must be a non-empty single-line string")


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        raise AttestationError("must be UTC in YYYY-MM-DDTHH:MM:SSZ form")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise AttestationError("contains an invalid calendar timestamp") from exc


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\0"):
        raise AttestationError(f"attestation: {path} must be a non-empty single-line string")
    return value


def _sha256_digest(value: str) -> dict[str, str]:
    if not _SHA256_RE.fullmatch(value):
        raise AttestationError("attestation: SHA-256 must be 64 lowercase hex characters")
    return {"algorithm": "sha256", "value": value}


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AttestationError(f"attestation: {label} is not readable canonical JSON") from exc
    return _load_json_object_bytes(raw, label)


def _load_json_object_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda value: _raise_nonfinite(value),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise AttestationError(f"attestation: {label} is not readable canonical JSON") from exc
    if not isinstance(payload, dict):
        raise AttestationError(f"attestation: {label} must be a JSON object")
    return payload


def _raise_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise AttestationError(f"attestation: {label} is unavailable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise AttestationError(f"attestation: {label} must be a regular non-symlink file")


def _require_secret_key(path: Path, label: str) -> None:
    _require_regular_file(path, label)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AttestationError(
            f"attestation: {label} permissions must not grant group/other access"
        )


def _require_executable(program: str) -> str:
    resolved = shutil.which(program)
    if resolved is None:
        raise SigningToolUnavailable(
            f"attestation: external signing tool {program!r} is unavailable"
        )
    return resolved


def _run_command(
    command: list[str],
    label: str,
    *,
    input_bytes: bytes | None = None,
    timeout: int = 30,
) -> None:
    try:
        result = subprocess.run(  # noqa: S603
            command,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AttestationError(f"attestation: {label} failed") from exc
    if result.returncode != 0:
        raise AttestationError(f"attestation: {label} failed")
