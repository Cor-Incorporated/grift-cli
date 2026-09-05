"""Cross-repository evidence portfolio without scoring or person inference."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from tep_core.attest import (
    VERIFIED,
    AttestationError,
    TrustPolicy,
    canonical_json_bytes,
    load_attestation_bundle,
    normalize_repo_hint,
    validate_attestable_report,
    verify_attestation_bundle,
)
from tep_core.digest import file_digest
from tep_core.secrets_guard import assert_no_secrets
from tep_core.secure_output import (
    SecureOutputError,
    create_private_directory_at,
    fsync_directory,
    lstat_at,
    open_directory_at,
    open_secure_parent,
    remove_directory_at,
    validate_closed_directory_at,
    write_private_at,
)

PORTFOLIO_MANIFEST_SCHEMA_VERSION = "tep-portfolio-manifest-v1"
PORTFOLIO_SCHEMA_VERSION = "tep-portfolio-v1"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REPO_SUBJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "portfolio_id",
        "subject_id",
        "subject_binding",
        "eligible_repository_count",
        "entries",
    }
)
_ENTRY_KEYS = frozenset(
    {
        "entry_id",
        "subject_id",
        "context",
        "role",
        "period_start",
        "period_end",
        "activity_month_count",
        "report",
        "attestation_bundle",
        "subject_binding",
        "repo_hint",
    }
)
_OPTIONAL_ENTRY_KEYS = frozenset({"subject_binding", "repo_hint"})
_FORBIDDEN_KEYS = frozenset(
    {
        "score",
        "scores",
        "rank",
        "ranking",
        "grade",
        "rating",
        "average",
        "mean",
        "weight",
        "weighted",
        "percentile",
    }
)


class PortfolioValidationError(ValueError):
    """A portfolio declaration or evidence binding is invalid."""


def load_portfolio_manifest(path: Path) -> dict[str, Any]:
    """Read and strictly validate a declared or attestation-bound manifest."""

    try:
        raw = path.read_text(encoding="utf-8")
        assert_no_secrets(raw, source="portfolio manifest")
        payload = tomllib.loads(raw)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise PortfolioValidationError("portfolio: manifest is not readable TOML") from exc
    except ValueError as exc:
        raise PortfolioValidationError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise PortfolioValidationError("portfolio: manifest root must be a table")
    _require_closed(payload, _ROOT_KEYS, "portfolio")
    if payload.get("schema_version") != PORTFOLIO_MANIFEST_SCHEMA_VERSION:
        raise PortfolioValidationError(
            f"portfolio: schema_version must be {PORTFOLIO_MANIFEST_SCHEMA_VERSION}"
        )
    portfolio_id = _require_id(payload.get("portfolio_id"), "portfolio_id")
    subject_id = _require_id(payload.get("subject_id"), "subject_id")
    subject_binding = _require_binding_method(payload.get("subject_binding"), "subject_binding")
    eligible = payload.get("eligible_repository_count")
    if not isinstance(eligible, int) or isinstance(eligible, bool) or eligible < 1:
        raise PortfolioValidationError(
            "portfolio: eligible_repository_count must be an integer >= 1"
        )
    rows = payload.get("entries")
    if not isinstance(rows, list) or not rows:
        raise PortfolioValidationError("portfolio: entries must be a non-empty array")
    if len(rows) > eligible:
        raise PortfolioValidationError(
            "portfolio: included entries exceed eligible_repository_count"
        )

    normalized: list[dict[str, Any]] = []
    entry_ids: set[str] = set()
    report_refs: set[str] = set()
    for index, row in enumerate(rows):
        item = _load_manifest_entry(row, index, subject_id, subject_binding)
        if item["entry_id"] in entry_ids:
            raise PortfolioValidationError(f"portfolio: duplicate entry_id {item['entry_id']!r}")
        if item["report"] in report_refs:
            raise PortfolioValidationError(
                "portfolio: the same report path cannot be counted more than once"
            )
        entry_ids.add(item["entry_id"])
        report_refs.add(item["report"])
        normalized.append(item)
    normalized_payload = {
        "schema_version": PORTFOLIO_MANIFEST_SCHEMA_VERSION,
        "portfolio_id": portfolio_id,
        "subject_id": subject_id,
        "subject_binding": subject_binding,
        "eligible_repository_count": eligible,
        "entries": sorted(normalized, key=lambda item: item["entry_id"]),
    }
    from tep_core.schema import validate_schema

    schema_errors = validate_schema("portfolio-manifest-v1", normalized_payload)
    if schema_errors:
        raise PortfolioValidationError(
            "portfolio: manifest schema rejected input: " + "; ".join(schema_errors)
        )
    return normalized_payload


def build_portfolio(
    manifest_path: Path, *, trust_policy: TrustPolicy | None = None
) -> dict[str, Any]:
    """Build a deterministic portfolio after checking its selected identity binding."""

    manifest_path = manifest_path.resolve()
    manifest = load_portfolio_manifest(manifest_path)
    base = manifest_path.parent.resolve()
    entries: list[dict[str, Any]] = []
    report_digests: set[str] = set()
    canonical_report_digests: set[str] = set()
    seen_repo_bindings: set[str] = set()
    binding_method = manifest["subject_binding"]
    if binding_method == "attested" and trust_policy is None:
        raise PortfolioValidationError(
            "portfolio: attested subject binding requires a recipient-supplied trust policy"
        )
    if binding_method == "self_declared" and trust_policy is not None:
        raise PortfolioValidationError(
            "portfolio: a trust policy cannot be mixed with self_declared subject binding"
        )

    for declaration in manifest["entries"]:
        report_path = _resolve_member(base, declaration["report"], expect_directory=False)
        bundle_dir = _resolve_member(base, declaration["attestation_bundle"], expect_directory=True)
        report = _load_report(report_path)
        _validate_report_for_portfolio(
            report,
            declaration["subject_id"],
            require_embedded_subject=binding_method == "attested",
        )
        report_digest = file_digest(report_path)
        if report_digest in report_digests:
            raise PortfolioValidationError(
                "portfolio: the same report bytes cannot be counted more than once"
            )
        report_digests.add(report_digest)
        canonical_report_digest = _canonical_report_digest(report)
        if canonical_report_digest in canonical_report_digests:
            raise PortfolioValidationError(
                "portfolio: the same canonical report cannot be counted more than once"
            )
        canonical_report_digests.add(canonical_report_digest)
        try:
            bundle = load_attestation_bundle(bundle_dir)
        except AttestationError as exc:
            raise PortfolioValidationError(
                f"portfolio: entry {declaration['entry_id']} attestation is invalid: {exc}"
            ) from exc
        signed_report = bundle.statement["report"]
        if signed_report["digest"]["value"] != report_digest:
            raise PortfolioValidationError(
                f"portfolio: entry {declaration['entry_id']} report digest is not attested"
            )
        if signed_report["schema_version"] != report["schema_version"]:
            raise PortfolioValidationError(
                f"portfolio: entry {declaration['entry_id']} report schema is not attested"
            )
        report_oid = _target_oid(report.get("provenance") or {})
        if bundle.statement["target"]["oid"] != report_oid:
            raise PortfolioValidationError(
                f"portfolio: entry {declaration['entry_id']} target OID is not attested"
            )
        entry_repo_bindings = _entry_repo_bindings(
            report,
            declaration,
            bundle.statement,
        )
        for binding_kind, binding_value in entry_repo_bindings.items():
            if binding_value in seen_repo_bindings:
                raise PortfolioValidationError(
                    f"portfolio: the same {binding_kind} cannot be counted more than once"
                )
            seen_repo_bindings.add(binding_value)
        if binding_method == "attested":
            verification = verify_attestation_bundle(
                bundle_dir,
                report_path,
                trust_policy=trust_policy,
            )
            required_parts = {
                "statement": verification.statement,
                "signature": verification.signature,
                "report_hash": verification.report_hash,
            }
            failures = [
                f"{name}={part.status} ({part.detail})"
                for name, part in required_parts.items()
                if part.status != VERIFIED
            ]
            if failures:
                raise PortfolioValidationError(
                    f"portfolio: entry {declaration['entry_id']} recipient trust verification "
                    f"failed: {'; '.join(failures)}"
                )

        signature_verification = (
            "recipient_trust_verified"
            if binding_method == "attested"
            else "not_verified_self_declared"
        )
        attestation_evidence: dict[str, Any] = {
            "statement_digest": bundle.manifest["statement"]["digest"],
            "bundle_manifest_digest": _digest(file_digest(bundle.manifest_path)),
            "signature_digest": bundle.manifest["signature"]["digest"],
            "signer_policy": bundle.statement["expected_signer_policy"],
            "signature_verification": signature_verification,
        }
        if binding_method == "attested":
            attestation_evidence["bound_subject_id"] = manifest["subject_id"]
        evidence = {
            "report": {
                "schema_version": report["schema_version"],
                "digest": _digest(report_digest),
                "target_oid": report_oid,
                "definition_version": report["provenance"]["definition_version"],
            },
            "attestation": attestation_evidence,
        }
        entry: dict[str, Any] = {
            "entry_id": declaration["entry_id"],
            "subject_binding": {
                "method": binding_method,
                "subject_id": manifest["subject_id"],
            },
            "context": declaration["context"],
            "role": declaration["role"],
            "period": {
                "start": declaration["period_start"],
                "end": declaration["period_end"],
                "unit": "date-range",
            },
            "activity_month_count": declaration["activity_month_count"],
            "repository_bindings": [
                _digest(value) for value in sorted(entry_repo_bindings.values())
            ],
            "evidence": evidence,
        }
        if "repo_hint" in declaration:
            entry["repo_hint"] = declaration["repo_hint"]
        entries.append(entry)

    eligible = manifest["eligible_repository_count"]
    included = len(entries)
    starts = [entry["period"]["start"] for entry in entries]
    ends = [entry["period"]["end"] for entry in entries]
    payload = {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "report_kind": "portfolio",
        "portfolio_id": manifest["portfolio_id"],
        "subject_binding": {
            "method": binding_method,
            "subject_id": manifest["subject_id"],
        },
        "summary": {
            "eligible_repository_count": eligible,
            "included_repository_count": included,
            "disclosure": {
                "kind": "declared",
                "numerator": included,
                "denominator": eligible,
                "value": round(included / eligible, 12),
                "unit": "ratio",
            },
            "period": {
                "start": min(starts),
                "end": max(ends),
                "unit": "date-range",
            },
        },
        "entries": entries,
        "limitations": [
            (
                "The subject binding is a submitter declaration, not an inferred "
                "cross-repository identity."
                if binding_method == "self_declared"
                else "The shared subject identifier is read from each recipient-trusted, "
                "signed report; it is not inferred from email, handle, or name similarity."
            ),
            "The eligible repository count and included selection are submitter declarations.",
            "Context, role, period, and activity month fields are submitter declarations.",
            (
                "Attestation signatures were not trust-verified because subject binding uses "
                "the explicit submitter declaration."
                if binding_method == "self_declared"
                else "Every detached signature was verified against the recipient-supplied "
                "trust policy; this does not prove metric correctness or subject superiority."
            ),
        ],
        "notices": [
            "選択性注意: 未掲載リポジトリを含む母集団は提出者の申告であり、全活動を自動保証しません。",
            "この成果物は文脈別の証拠台帳であり、人物の優劣判定を生成しません。",
        ],
    }
    validate_portfolio_payload(payload)
    return payload


def validate_portfolio_payload(payload: Any) -> None:
    """Fail closed on output arithmetic or forbidden aggregate fields."""

    if not isinstance(payload, dict):
        raise PortfolioValidationError("portfolio output must be an object")
    allowed = frozenset(
        {
            "schema_version",
            "report_kind",
            "portfolio_id",
            "subject_binding",
            "summary",
            "entries",
            "limitations",
            "notices",
        }
    )
    _require_closed(payload, allowed, "portfolio output")
    if payload.get("schema_version") != PORTFOLIO_SCHEMA_VERSION:
        raise PortfolioValidationError(
            f"portfolio output schema_version must be {PORTFOLIO_SCHEMA_VERSION}"
        )
    if payload.get("report_kind") != "portfolio":
        raise PortfolioValidationError("portfolio output report_kind must be portfolio")
    _reject_forbidden_keys(payload)
    _validate_binding(payload.get("subject_binding"), "portfolio output.subject_binding")
    _require_id(payload.get("portfolio_id"), "output.portfolio_id")
    summary = payload.get("summary")
    entries = payload.get("entries")
    if not isinstance(summary, dict) or not isinstance(entries, list):
        raise PortfolioValidationError("portfolio output summary and entries are required")
    _require_closed(
        summary,
        frozenset(
            {
                "eligible_repository_count",
                "included_repository_count",
                "disclosure",
                "period",
            }
        ),
        "portfolio output.summary",
    )
    eligible = summary.get("eligible_repository_count")
    included = summary.get("included_repository_count")
    disclosure = summary.get("disclosure")
    if (
        not isinstance(eligible, int)
        or isinstance(eligible, bool)
        or eligible < 1
        or not isinstance(included, int)
        or isinstance(included, bool)
        or included != len(entries)
        or included > eligible
    ):
        raise PortfolioValidationError("portfolio output repository counts are inconsistent")
    if not isinstance(disclosure, dict):
        raise PortfolioValidationError("portfolio output disclosure is required")
    _require_closed(
        disclosure,
        frozenset({"kind", "numerator", "denominator", "value", "unit"}),
        "portfolio output.summary.disclosure",
    )
    if disclosure.get("kind") != "declared":
        raise PortfolioValidationError("portfolio output disclosure must be declared")
    if disclosure.get("numerator") != included or disclosure.get("denominator") != eligible:
        raise PortfolioValidationError("portfolio output disclosure arithmetic is inconsistent")
    expected = round(included / eligible, 12)
    if disclosure.get("value") != expected or disclosure.get("unit") != "ratio":
        raise PortfolioValidationError("portfolio output disclosure ratio is inconsistent")
    ids = [entry.get("entry_id") for entry in entries if isinstance(entry, dict)]
    if len(ids) != len(entries) or len(set(ids)) != len(ids):
        raise PortfolioValidationError("portfolio output entry IDs must be unique")
    summary_start, summary_end = _validate_period(
        summary.get("period"), "portfolio output.summary.period"
    )
    expected_subject = payload["subject_binding"]["subject_id"]
    expected_method = payload["subject_binding"]["method"]
    for index, entry in enumerate(entries):
        _validate_output_entry(entry, index, expected_subject, expected_method)
    report_digests = [
        entry["evidence"]["report"]["digest"]["value"]
        for entry in entries
        if isinstance(entry, dict)
    ]
    if len(report_digests) != len(set(report_digests)):
        raise PortfolioValidationError("portfolio output report digests must be unique")
    repository_binding_values = [
        binding["value"]
        for entry in entries
        for binding in entry["repository_bindings"]
        if isinstance(entry, dict) and isinstance(binding, dict)
    ]
    if len(repository_binding_values) != len(set(repository_binding_values)):
        raise PortfolioValidationError("portfolio output repository bindings must be unique")
    repo_hints = [
        entry["repo_hint"] for entry in entries if isinstance(entry, dict) and "repo_hint" in entry
    ]
    if len(repo_hints) != len(set(repo_hints)):
        raise PortfolioValidationError("portfolio output repository hints must be unique")
    if entries:
        entry_starts = [
            _parse_date(entry["period"]["start"], f"portfolio output.entries[{index}].period.start")
            for index, entry in enumerate(entries)
        ]
        entry_ends = [
            _parse_date(entry["period"]["end"], f"portfolio output.entries[{index}].period.end")
            for index, entry in enumerate(entries)
        ]
        if summary_start != min(entry_starts) or summary_end != max(entry_ends):
            raise PortfolioValidationError(
                "portfolio output summary period must equal the exact entry span"
            )
    if expected_method == "attested":
        policies = {
            json.dumps(
                entry["evidence"]["attestation"]["signer_policy"],
                sort_keys=True,
                separators=(",", ":"),
            )
            for entry in entries
        }
        if len(policies) != 1:
            raise PortfolioValidationError(
                "portfolio output attested entries must share one recipient trust policy"
            )
    if not isinstance(payload.get("limitations"), list) or not all(
        isinstance(item, str) and item for item in payload["limitations"]
    ):
        raise PortfolioValidationError("portfolio output limitations must be strings")
    if not isinstance(payload.get("notices"), list) or not all(
        isinstance(item, str) and item for item in payload["notices"]
    ):
        raise PortfolioValidationError("portfolio output notices must be strings")
    if not any("選択性注意" in str(item) for item in payload.get("notices") or []):
        raise PortfolioValidationError("portfolio output must always include a selection warning")
    from tep_core.schema import validate_schema

    schema_errors = validate_schema("portfolio-v1", payload)
    if schema_errors:
        raise PortfolioValidationError(
            "portfolio output schema rejected input: " + "; ".join(schema_errors)
        )


def render_portfolio_markdown(payload: Mapping[str, Any]) -> str:
    validate_portfolio_payload(dict(payload))
    summary = payload["summary"]
    subject = payload["subject_binding"]
    lines = [
        "# Grift evidence portfolio",
        "",
        "## Scope",
        f"- portfolio: `{payload['portfolio_id']}`",
        f"- subject: `{subject['subject_id']}` ({subject['method']})",
        (
            "- disclosure: "
            f"{summary['included_repository_count']} of {summary['eligible_repository_count']} "
            "declared eligible repositories"
        ),
        f"- period: {summary['period']['start']} to {summary['period']['end']}",
        "",
        "## Evidence entries",
    ]
    for entry in payload["entries"]:
        lines.extend(
            [
                f"### {entry['entry_id']}",
                f"- context: {entry['context']}",
                f"- role: {entry['role']}",
                f"- period: {entry['period']['start']} to {entry['period']['end']}",
                f"- activity months: {entry['activity_month_count']} months",
                f"- report SHA-256: `{entry['evidence']['report']['digest']['value']}`",
                (
                    "- attestation statement SHA-256: `"
                    f"{entry['evidence']['attestation']['statement_digest']['value']}`"
                ),
                (
                    "- signature verification: `"
                    f"{entry['evidence']['attestation']['signature_verification']}`"
                ),
            ]
        )
        if entry["evidence"]["attestation"].get("bound_subject_id"):
            lines.append(
                f"- signed report subject: `{entry['evidence']['attestation']['bound_subject_id']}`"
            )
        if entry.get("repo_hint"):
            lines.append(f"- repository hint (opt-in): `{entry['repo_hint']}`")
        lines.append("")
    lines.extend(["## Limitations", *[f"- {item}" for item in payload["limitations"]], ""])
    lines.extend(["## Notices", *[f"- {item}" for item in payload["notices"]], ""])
    return "\n".join(lines)


def publish_portfolio_artifacts(
    out_dir: Path,
    *,
    json_text: str | None,
    markdown_text: str | None,
) -> None:
    """Stage every selected artifact before atomically publishing the directory.

    Existing output is accepted only when it is a closed portfolio directory.
    It is moved aside as one unit and restored if publication or cleanup fails,
    so a JSON/Markdown pair can never be left half-updated.
    """

    artifacts = {
        name: text.encode("utf-8")
        for name, text in {
            "portfolio.json": json_text,
            "portfolio.md": markdown_text,
        }.items()
        if text is not None
    }
    if not artifacts:
        raise PortfolioValidationError("no output artifact was selected")

    staging_name: str | None = None
    staging_fd = -1
    backup_name: str | None = None
    try:
        with open_secure_parent(out_dir, create=True) as parent:
            staging_name, staging_fd = create_private_directory_at(
                parent.fd, prefix=".grift-portfolio-stage-"
            )
            for name, data in artifacts.items():
                write_private_at(staging_fd, name, data)
            validate_closed_directory_at(staging_fd, set(artifacts), required_file_mode=0o600)
            fsync_directory(staging_fd)
            os.close(staging_fd)
            staging_fd = -1

            existing = lstat_at(parent.fd, parent.leaf)
            if existing is None:
                os.rename(
                    staging_name,
                    parent.leaf,
                    src_dir_fd=parent.fd,
                    dst_dir_fd=parent.fd,
                )
                staging_name = None
                fsync_directory(parent.fd)
                return

            existing_fd = open_directory_at(parent.fd, parent.leaf)
            try:
                existing_names = set(os.listdir(existing_fd))
                allowed_names = {"portfolio.json", "portfolio.md"}
                if not existing_names <= allowed_names:
                    raise SecureOutputError(
                        "portfolio output directory contains unregistered members"
                    )
                validate_closed_directory_at(existing_fd, existing_names)
            finally:
                os.close(existing_fd)

            backup_name = _unused_output_name(parent.fd, prefix=".grift-portfolio-backup-")
            os.rename(
                parent.leaf,
                backup_name,
                src_dir_fd=parent.fd,
                dst_dir_fd=parent.fd,
            )
            try:
                os.rename(
                    staging_name,
                    parent.leaf,
                    src_dir_fd=parent.fd,
                    dst_dir_fd=parent.fd,
                )
                staging_name = None
            except OSError as publish_error:
                try:
                    os.rename(
                        backup_name,
                        parent.leaf,
                        src_dir_fd=parent.fd,
                        dst_dir_fd=parent.fd,
                    )
                    backup_name = None
                except OSError as rollback_error:
                    raise SecureOutputError(
                        "portfolio publication failed and the previous directory "
                        "could not be restored"
                    ) from rollback_error
                raise SecureOutputError(
                    "portfolio publication failed; the previous directory was restored"
                ) from publish_error

            try:
                remove_directory_at(parent.fd, backup_name)
                backup_name = None
            except (OSError, SecureOutputError) as cleanup_error:
                discard_name = _unused_output_name(parent.fd, prefix=".grift-portfolio-discard-")
                try:
                    os.rename(
                        parent.leaf,
                        discard_name,
                        src_dir_fd=parent.fd,
                        dst_dir_fd=parent.fd,
                    )
                    os.rename(
                        backup_name,
                        parent.leaf,
                        src_dir_fd=parent.fd,
                        dst_dir_fd=parent.fd,
                    )
                    backup_name = None
                    remove_directory_at(parent.fd, discard_name)
                except (OSError, SecureOutputError) as rollback_error:
                    raise SecureOutputError(
                        "portfolio cleanup failed and the previous directory could not be restored"
                    ) from rollback_error
                raise SecureOutputError(
                    "portfolio cleanup failed; the previous directory was restored"
                ) from cleanup_error
            fsync_directory(parent.fd)
    except SecureOutputError as exc:
        raise PortfolioValidationError(str(exc)) from exc
    except OSError as exc:
        raise PortfolioValidationError(
            "output directory could not be published atomically"
        ) from exc
    finally:
        if staging_fd >= 0:
            os.close(staging_fd)
        if staging_name is not None or backup_name is not None:
            try:
                with open_secure_parent(out_dir, create=False) as parent:
                    if staging_name is not None:
                        remove_directory_at(parent.fd, staging_name)
                    if backup_name is not None and lstat_at(parent.fd, parent.leaf) is not None:
                        # A retained backup is preferable to deleting the only old copy.
                        pass
            except (OSError, SecureOutputError):
                pass


def _unused_output_name(parent_fd: int, *, prefix: str) -> str:
    for _attempt in range(64):
        name = f"{prefix}{secrets.token_hex(12)}"
        if lstat_at(parent_fd, name) is None:
            return name
    raise SecureOutputError("portfolio temporary name could not be allocated")


def _load_manifest_entry(
    row: Any, index: int, subject_id: str, subject_binding: str
) -> dict[str, Any]:
    path = f"entries[{index}]"
    if not isinstance(row, dict):
        raise PortfolioValidationError(f"portfolio: {path} must be a table")
    _require_closed(row, _ENTRY_KEYS, path, optional=_OPTIONAL_ENTRY_KEYS)
    _reject_forbidden_keys(row)
    entry_id = _require_id(row.get("entry_id"), f"{path}.entry_id")
    declared_subject = _require_id(row.get("subject_id"), f"{path}.subject_id")
    if declared_subject != subject_id:
        raise PortfolioValidationError(
            f"portfolio: {path}.subject_id differs from the portfolio subject"
        )
    declared_binding = _require_binding_method(
        row.get("subject_binding", subject_binding), f"{path}.subject_binding"
    )
    if declared_binding != subject_binding:
        raise PortfolioValidationError(
            f"portfolio: {path}.subject_binding differs from the portfolio subject binding"
        )
    context = _require_label(row.get("context"), f"{path}.context")
    role = _require_label(row.get("role"), f"{path}.role")
    start = _parse_date(row.get("period_start"), f"{path}.period_start")
    end = _parse_date(row.get("period_end"), f"{path}.period_end")
    if end < start:
        raise PortfolioValidationError(f"portfolio: {path} period_end precedes period_start")
    months = row.get("activity_month_count")
    max_months = (end.year - start.year) * 12 + end.month - start.month + 1
    if not isinstance(months, int) or isinstance(months, bool) or months < 0 or months > max_months:
        raise PortfolioValidationError(
            f"portfolio: {path}.activity_month_count must be 0..{max_months}"
        )
    report = _require_relative_path(row.get("report"), f"{path}.report")
    bundle = _require_relative_path(row.get("attestation_bundle"), f"{path}.attestation_bundle")
    item: dict[str, Any] = {
        "entry_id": entry_id,
        "subject_id": declared_subject,
        "subject_binding": declared_binding,
        "context": context,
        "role": role,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "activity_month_count": months,
        "report": report,
        "attestation_bundle": bundle,
    }
    if "repo_hint" in row:
        try:
            item["repo_hint"] = normalize_repo_hint(row["repo_hint"])
        except (AttestationError, AttributeError) as exc:
            raise PortfolioValidationError(f"portfolio: {path}.repo_hint is invalid") from exc
    return item


def _validate_report_for_portfolio(
    report: dict[str, Any], subject_id: str, *, require_embedded_subject: bool = False
) -> None:
    schema_errors = validate_attestable_report(report)
    if schema_errors:
        raise PortfolioValidationError(
            "portfolio: report schema is invalid: " + "; ".join(schema_errors)
        )
    if report.get("schema_version") not in {"report-v1", "report-v2"}:
        raise PortfolioValidationError("portfolio: entries require report-v1 or report-v2 inputs")
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise PortfolioValidationError("portfolio: report.provenance must be an object")
    if provenance.get("analysis_scope") != "tenant":
        raise PortfolioValidationError("portfolio: entries require tenant-scope reports")
    for key in ("tool_name", "tool_version", "definition_version"):
        if not isinstance(provenance.get(key), str) or not provenance[key]:
            raise PortfolioValidationError(f"portfolio: report.provenance.{key} is required")
    _target_oid(provenance)
    identity = report.get("identity")
    if not isinstance(identity, dict):
        raise PortfolioValidationError("portfolio: report.identity must be an object")
    if identity.get("pending_attribution") is not False or identity.get("actor_count") != 1:
        raise PortfolioValidationError(
            "portfolio: each report must have exactly one explicitly configured actor"
        )
    report_subject = report.get("subject")
    if require_embedded_subject and not isinstance(report_subject, dict):
        raise PortfolioValidationError(
            "portfolio: attested binding requires report.subject with an explicit subject_id"
        )
    if isinstance(report_subject, dict):
        if require_embedded_subject and report_subject.get("kind") != "actor":
            raise PortfolioValidationError(
                "portfolio: attested binding requires report.subject.kind=actor"
            )
        embedded_values = [
            report_subject[key]
            for key in ("canonical_id", "subject_id")
            if report_subject.get(key) is not None
        ]
        if require_embedded_subject and not embedded_values:
            raise PortfolioValidationError(
                "portfolio: attested binding requires report.subject.canonical_id or subject_id"
            )
        if any(embedded != subject_id for embedded in embedded_values):
            raise PortfolioValidationError(
                "portfolio: report subject differs from the declared portfolio subject"
            )


def _validate_output_entry(
    entry: Any, index: int, expected_subject: str, expected_method: str
) -> None:
    path = f"portfolio output.entries[{index}]"
    if not isinstance(entry, dict):
        raise PortfolioValidationError(f"{path} must be an object")
    _require_closed(
        entry,
        frozenset(
            {
                "entry_id",
                "subject_binding",
                "context",
                "role",
                "period",
                "activity_month_count",
                "repository_bindings",
                "evidence",
                "repo_hint",
            }
        ),
        path,
        optional=frozenset({"repo_hint"}),
    )
    _require_id(entry.get("entry_id"), f"output.entries[{index}].entry_id")
    _require_label(entry.get("context"), f"output.entries[{index}].context")
    _require_label(entry.get("role"), f"output.entries[{index}].role")
    _validate_binding(entry.get("subject_binding"), f"{path}.subject_binding")
    if entry["subject_binding"]["subject_id"] != expected_subject:
        raise PortfolioValidationError(f"portfolio: {path} has a different subject")
    if entry["subject_binding"]["method"] != expected_method:
        raise PortfolioValidationError(f"portfolio: {path} has a different binding method")
    period_start, period_end = _validate_period(entry.get("period"), f"{path}.period")
    months = entry.get("activity_month_count")
    max_months = (
        (period_end.year - period_start.year) * 12 + period_end.month - period_start.month + 1
    )
    if not isinstance(months, int) or isinstance(months, bool) or months < 0 or months > max_months:
        raise PortfolioValidationError(f"portfolio: {path}.activity_month_count is invalid")
    bindings = entry.get("repository_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise PortfolioValidationError(f"portfolio: {path}.repository_bindings is required")
    binding_values: list[str] = []
    for binding_index, binding in enumerate(bindings):
        _validate_digest(binding, f"{path}.repository_bindings[{binding_index}]")
        binding_values.append(binding["value"])
    if len(binding_values) != len(set(binding_values)):
        raise PortfolioValidationError(
            f"portfolio: {path}.repository_bindings must be unique"
        )
    if "repo_hint" in entry:
        try:
            normalize_repo_hint(entry["repo_hint"])
        except (AttestationError, AttributeError) as exc:
            raise PortfolioValidationError(f"portfolio: {path}.repo_hint is invalid") from exc
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict):
        raise PortfolioValidationError(f"portfolio: {path}.evidence must be an object")
    _require_closed(evidence, frozenset({"report", "attestation"}), f"{path}.evidence")
    report = evidence.get("report")
    if not isinstance(report, dict):
        raise PortfolioValidationError(f"portfolio: {path}.evidence.report must be an object")
    _require_closed(
        report,
        frozenset({"schema_version", "digest", "target_oid", "definition_version"}),
        f"{path}.evidence.report",
    )
    if report.get("schema_version") not in {"report-v1", "report-v2"}:
        raise PortfolioValidationError(
            f"portfolio: {path} requires report-v1 or report-v2 evidence"
        )
    if not isinstance(report.get("definition_version"), str) or not report["definition_version"]:
        raise PortfolioValidationError(f"portfolio: {path} definition_version is required")
    _validate_digest(report.get("digest"), f"{path}.evidence.report.digest")
    _validate_oid(report.get("target_oid"), f"{path}.evidence.report.target_oid")
    attestation = evidence.get("attestation")
    if not isinstance(attestation, dict):
        raise PortfolioValidationError(f"portfolio: {path}.evidence.attestation must be an object")
    _require_closed(
        attestation,
        frozenset(
            {
                "statement_digest",
                "bundle_manifest_digest",
                "signature_digest",
                "signer_policy",
                "signature_verification",
                "bound_subject_id",
            }
        ),
        f"{path}.evidence.attestation",
        optional=frozenset({"bound_subject_id"}),
    )
    for key in ("statement_digest", "bundle_manifest_digest", "signature_digest"):
        _validate_digest(attestation.get(key), f"{path}.evidence.attestation.{key}")
    _validate_signer_policy(
        attestation.get("signer_policy"), f"{path}.evidence.attestation.signer_policy"
    )
    verification = attestation.get("signature_verification")
    expected_verification = (
        "recipient_trust_verified"
        if expected_method == "attested"
        else "not_verified_self_declared"
    )
    if verification != expected_verification:
        raise PortfolioValidationError(
            f"portfolio: {path}.evidence.attestation.signature_verification must be "
            f"{expected_verification}"
        )
    bound_subject = attestation.get("bound_subject_id")
    if expected_method == "attested":
        if bound_subject != expected_subject:
            raise PortfolioValidationError(
                f"portfolio: {path}.evidence.attestation.bound_subject_id differs from subject"
            )
    elif "bound_subject_id" in attestation:
        raise PortfolioValidationError(
            f"portfolio: {path}.evidence.attestation.bound_subject_id is forbidden for "
            "self_declared binding"
        )


def _validate_binding(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise PortfolioValidationError(f"portfolio: {path} must be an object")
    _require_closed(node, frozenset({"method", "subject_id"}), path)
    _require_binding_method(node.get("method"), f"{path}.method")
    _require_id(node.get("subject_id"), f"{path}.subject_id")


def _validate_signer_policy(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise PortfolioValidationError(f"portfolio: {path} must be an object")
    kind = node.get("kind")
    if kind == "ssh":
        _require_closed(node, frozenset({"kind", "namespace", "principal"}), path)
        if node.get("namespace") != "grift-attestation-v1":
            raise PortfolioValidationError(
                f"portfolio: {path}.namespace must be grift-attestation-v1"
            )
        if not isinstance(node.get("principal"), str) or not node["principal"]:
            raise PortfolioValidationError(f"portfolio: {path}.principal is invalid")
        return
    if kind == "cosign-keyless":
        _require_closed(
            node,
            frozenset({"kind", "certificate_identity", "certificate_oidc_issuer"}),
            path,
        )
        if not all(
            isinstance(node.get(key), str) and node[key]
            for key in ("certificate_identity", "certificate_oidc_issuer")
        ):
            raise PortfolioValidationError(f"portfolio: {path} keyless identity is invalid")
        return
    if kind == "cosign-key":
        _require_closed(node, frozenset({"kind", "public_key_sha256"}), path)
        value = node.get("public_key_sha256")
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise PortfolioValidationError(
                f"portfolio: {path}.public_key_sha256 must be a SHA-256 digest"
            )
        return
    raise PortfolioValidationError(f"portfolio: {path}.kind is unsupported")


def _validate_period(node: Any, path: str) -> tuple[date, date]:
    if not isinstance(node, dict):
        raise PortfolioValidationError(f"portfolio: {path} must be an object")
    _require_closed(node, frozenset({"start", "end", "unit"}), path)
    start = _parse_date(node.get("start"), f"{path}.start")
    end = _parse_date(node.get("end"), f"{path}.end")
    if end < start:
        raise PortfolioValidationError(f"portfolio: {path}.end precedes start")
    if node.get("unit") != "date-range":
        raise PortfolioValidationError(f"portfolio: {path}.unit must be date-range")
    return start, end


def _validate_digest(node: Any, path: str) -> None:
    if (
        not isinstance(node, dict)
        or set(node) != {"algorithm", "value"}
        or node.get("algorithm") != "sha256"
        or not isinstance(node.get("value"), str)
        or not _SHA256_RE.fullmatch(node["value"])
    ):
        raise PortfolioValidationError(f"portfolio: {path} must be a SHA-256 digest")


def _validate_oid(node: Any, path: str) -> None:
    if not isinstance(node, dict) or set(node) != {"algorithm", "value"}:
        raise PortfolioValidationError(f"portfolio: {path} must be a Git OID")
    algorithm = node.get("algorithm")
    value = node.get("value")
    pattern = _SHA1_RE if algorithm == "sha1" else _SHA256_RE if algorithm == "sha256" else None
    if pattern is None or not isinstance(value, str) or not pattern.fullmatch(value):
        raise PortfolioValidationError(f"portfolio: {path} does not match its algorithm")


def _target_oid(provenance: Mapping[str, Any]) -> dict[str, str]:
    raw = provenance.get("target_oid")
    if raw is None:
        raw = provenance.get("analyzed_commit_oid")
    if raw is None:
        raw = provenance.get("analyzed_commit_sha")
    if isinstance(raw, str):
        if _SHA1_RE.fullmatch(raw):
            return {"algorithm": "sha1", "value": raw}
        if _SHA256_RE.fullmatch(raw):
            return {"algorithm": "sha256", "value": raw}
    if isinstance(raw, dict):
        algorithm = raw.get("algorithm")
        value = raw.get("value")
        pattern = _SHA1_RE if algorithm == "sha1" else _SHA256_RE if algorithm == "sha256" else None
        if (
            set(raw) == {"algorithm", "value"}
            and pattern
            and isinstance(value, str)
            and pattern.fullmatch(value)
        ):
            return {"algorithm": algorithm, "value": value}
    raise PortfolioValidationError("portfolio: report target OID is missing or invalid")


def _resolve_member(base: Path, value: str, *, expect_directory: bool) -> Path:
    candidate = base / value
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PortfolioValidationError(
            f"portfolio: evidence member {value!r} is unavailable"
        ) from exc
    if not resolved.is_relative_to(base):
        raise PortfolioValidationError("portfolio: evidence path escapes the manifest directory")
    if candidate.is_symlink():
        raise PortfolioValidationError("portfolio: evidence path must not be a symlink")
    if expect_directory and not resolved.is_dir():
        raise PortfolioValidationError("portfolio: attestation_bundle must be a directory")
    if not expect_directory and not resolved.is_file():
        raise PortfolioValidationError("portfolio: report must be a file")
    return resolved


def _load_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: _raise_nonfinite(value),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PortfolioValidationError("portfolio: report is not valid finite JSON") from exc
    if not isinstance(payload, dict):
        raise PortfolioValidationError("portfolio: report must be a JSON object")
    return payload


def _canonical_report_digest(report: Mapping[str, Any]) -> str:
    try:
        encoded = canonical_json_bytes(report)
    except AttestationError as exc:
        raise PortfolioValidationError("portfolio: report is not canonicalizable JSON") from exc
    return hashlib.sha256(b"tep-portfolio-canonical-report-v1\0" + encoded).hexdigest()


def _report_repo_scope_digest(report: Mapping[str, Any]) -> str | None:
    candidates: list[Any] = []
    provenance = report.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("repo_scope_digest") is not None:
        candidates.append(provenance["repo_scope_digest"])
    attribution = report.get("attribution")
    if isinstance(attribution, Mapping):
        partition = attribution.get("actor_partition")
        if isinstance(partition, Mapping) and partition.get("repo_scope_digest") is not None:
            candidates.append(partition["repo_scope_digest"])
    if not candidates:
        return None
    normalized: set[str] = set()
    for raw in candidates:
        if isinstance(raw, Mapping):
            if set(raw) != {"algorithm", "value"} or raw.get("algorithm") != "sha256":
                raise PortfolioValidationError("portfolio: report repo_scope_digest is invalid")
            raw = raw.get("value")
        if not isinstance(raw, str) or not _SHA256_RE.fullmatch(raw):
            raise PortfolioValidationError("portfolio: report repo_scope_digest is invalid")
        normalized.add(raw)
    if len(normalized) != 1:
        raise PortfolioValidationError("portfolio: report repo_scope_digest values disagree")
    return next(iter(normalized))


def _entry_repo_bindings(
    report: Mapping[str, Any],
    declaration: Mapping[str, Any],
    statement: Mapping[str, Any],
) -> dict[str, str]:
    """Return domain-separated, non-disclosing repository identity bindings."""

    bindings: dict[str, str] = {}
    report_schema = report.get("schema_version")
    repo_scope_digest = _report_repo_scope_digest(report)
    if repo_scope_digest is not None:
        bindings["repository scope"] = _opaque_repo_binding("repo-scope", repo_scope_digest)

    repo_subject_id = report.get("repo_subject_id")
    if repo_subject_id is not None:
        if (
            report_schema != "report-v1"
            or not isinstance(repo_subject_id, str)
            or _REPO_SUBJECT_ID_RE.fullmatch(repo_subject_id) is None
        ):
            raise PortfolioValidationError(
                "portfolio: report-v1 repo_subject_id must be an opaque identifier"
            )
        bindings["repository subject"] = _opaque_repo_binding("repo-subject", repo_subject_id)

    declared_hint = declaration.get("repo_hint")
    signed_hint = statement.get("repo_hint")
    if signed_hint is not None:
        try:
            normalized_signed_hint = normalize_repo_hint(signed_hint)
        except (AttestationError, AttributeError) as exc:
            raise PortfolioValidationError(
                "portfolio: attested repository hint is invalid"
            ) from exc
        if declared_hint is not None and declared_hint != normalized_signed_hint:
            raise PortfolioValidationError(
                "portfolio: declared repository hint differs from the attested repository hint"
            )
        bindings["repository hint"] = _opaque_repo_binding("repo-hint", normalized_signed_hint)
    elif declared_hint is not None:
        raise PortfolioValidationError("portfolio: declared repository hint is not attested")

    if report_schema == "report-v1" and not (
        "repository subject" in bindings or "repository hint" in bindings
    ):
        raise PortfolioValidationError(
            "portfolio: report-v1 entries require repo_subject_id or an attested repo_hint"
        )
    if not bindings:
        raise PortfolioValidationError(
            "portfolio: every entry requires an opaque repository binding"
        )
    return bindings


def _opaque_repo_binding(kind: str, value: str) -> str:
    payload = (
        b"tep-portfolio-repo-binding-v1\0" + kind.encode("ascii") + b"\0" + value.encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_closed(
    node: Mapping[str, Any],
    allowed: frozenset[str],
    path: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown = set(node) - allowed
    missing = allowed - optional - set(node)
    if unknown:
        raise PortfolioValidationError(
            f"portfolio: {path} has unknown keys: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise PortfolioValidationError(
            f"portfolio: {path} is missing keys: {', '.join(sorted(missing))}"
        )


def _reject_forbidden_keys(node: Any, path: str = "portfolio") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise PortfolioValidationError(f"portfolio: {path}.{key} is forbidden")
            _reject_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_forbidden_keys(value, f"{path}[{index}]")


def _require_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise PortfolioValidationError(f"portfolio: {path} must match {_ID_RE.pattern}")
    return value


def _require_binding_method(value: Any, path: str) -> str:
    if value not in {"self_declared", "attested"}:
        raise PortfolioValidationError(f"portfolio: {path} must be self_declared or attested")
    return str(value)


def _require_label(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _LABEL_RE.fullmatch(value):
        raise PortfolioValidationError(f"portfolio: {path} must match {_LABEL_RE.pattern}")
    return value


def _parse_date(value: Any, path: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise PortfolioValidationError(f"portfolio: {path} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PortfolioValidationError(f"portfolio: {path} must be YYYY-MM-DD") from exc


def _require_relative_path(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise PortfolioValidationError(f"portfolio: {path} must be a relative path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or value.startswith("~"):
        raise PortfolioValidationError(f"portfolio: {path} must stay under the manifest directory")
    return candidate.as_posix()


def _digest(value: str) -> dict[str, str]:
    if not _SHA256_RE.fullmatch(value):
        raise PortfolioValidationError("portfolio: invalid SHA-256 digest")
    return {"algorithm": "sha256", "value": value}


def _raise_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")
