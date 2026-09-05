"""Read the repository-versioned AI co-author identity set at a fixed Git OID.

The file is deliberately small and closed.  It identifies AI co-authors only
by an exact email or the existing domain-separated ``identity-v2`` email
digest.  Display names, provider handles, and fuzzy matching are not accepted.
The blob is read through Git plumbing, never from the working tree.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tep_core.identity import (
    EMAIL_SHA256_RE,
    IdentityValidationError,
    email_identity_sha256,
    normalize_email,
)

AI_IDENTITY_PATH = ".tep/ai-identities.toml"
AI_IDENTITY_SCHEMA_VERSION = "ai-identity-v1"
_ALLOWED_KEYS = frozenset({"schema_version", "emails", "email_sha256"})
_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+$")
_MAX_BLOB_BYTES = 64 * 1024


@dataclass(frozen=True)
class AiIdentitySet:
    emails: tuple[str, ...] = ()
    email_sha256: tuple[str, ...] = ()
    blob_oid: str | None = None


def _git(repo: Path, args: list[str]) -> bytes:
    try:
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
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise IdentityValidationError("fixed AI identity Git read timed out") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise IdentityValidationError(message or "fixed AI identity Git read failed")
    return result.stdout


def _string_array(document: dict[str, object], key: str) -> tuple[str, ...]:
    value = document.get(key, [])
    if not isinstance(value, list):
        raise IdentityValidationError(f"{AI_IDENTITY_PATH}.{key} must be an array of strings")
    rows: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise IdentityValidationError(
                f"{AI_IDENTITY_PATH}.{key}[{index}] must be a non-empty string"
            )
        rows.append(item)
    return tuple(rows)


def parse_ai_identities(text: str, *, blob_oid: str | None = None) -> AiIdentitySet:
    """Parse the closed ``ai-identity-v1`` document without leaking values."""

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise IdentityValidationError(f"invalid {AI_IDENTITY_PATH}: {exc}") from exc
    unknown = sorted(set(document) - _ALLOWED_KEYS)
    if unknown:
        rendered = ", ".join(repr(key) for key in unknown)
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} contains unknown key(s): {rendered}")
    if document.get("schema_version") != AI_IDENTITY_SCHEMA_VERSION:
        raise IdentityValidationError(
            f"{AI_IDENTITY_PATH}.schema_version must be {AI_IDENTITY_SCHEMA_VERSION!r}"
        )

    raw_emails = _string_array(document, "emails")
    raw_digests = _string_array(document, "email_sha256")
    emails: list[str] = []
    for index, value in enumerate(raw_emails):
        normalized = normalize_email(value)
        if not _EMAIL_RE.fullmatch(normalized):
            raise IdentityValidationError(
                f"{AI_IDENTITY_PATH}.emails[{index}] must be an email address"
            )
        emails.append(normalized)
    if len(emails) != len(set(emails)):
        raise IdentityValidationError(f"{AI_IDENTITY_PATH}.emails contains a duplicate identity")

    digests: list[str] = []
    for index, value in enumerate(raw_digests):
        if value != value.lower() or not EMAIL_SHA256_RE.fullmatch(value):
            raise IdentityValidationError(
                f"{AI_IDENTITY_PATH}.email_sha256[{index}] must be 64 lowercase hex"
            )
        digests.append(value)
    if len(digests) != len(set(digests)):
        raise IdentityValidationError(
            f"{AI_IDENTITY_PATH}.email_sha256 contains a duplicate identity"
        )
    if {email_identity_sha256(value) for value in emails}.intersection(digests):
        raise IdentityValidationError(
            f"{AI_IDENTITY_PATH} repeats one identity across plaintext and digest forms"
        )
    if not emails and not digests:
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} must declare at least one identity")
    return AiIdentitySet(
        emails=tuple(sorted(emails)),
        email_sha256=tuple(sorted(digests)),
        blob_oid=blob_oid,
    )


def load_ai_identities_at_revision(repo: Path, revision: str) -> AiIdentitySet:
    """Load the regular blob at ``revision``; ignore all checkout-only data."""

    normalized_revision = revision.strip().lower()
    if not _OID_RE.fullmatch(normalized_revision):
        raise IdentityValidationError("AI identity revision must be a full Git object id")
    listing = _git(repo, ["ls-tree", "-z", normalized_revision, "--", AI_IDENTITY_PATH])
    if not listing:
        return AiIdentitySet()
    rows = [row for row in listing.split(b"\0") if row]
    if len(rows) != 1 or b"\t" not in rows[0]:
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} tree entry is ambiguous")
    metadata, path = rows[0].split(b"\t", 1)
    try:
        mode, object_type, blob_oid = metadata.decode("ascii").split()
        rendered_path = path.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} tree entry is invalid") from exc
    if rendered_path != AI_IDENTITY_PATH:
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} tree entry has an unexpected path")
    if mode not in {"100644", "100755"} or object_type != "blob" or not _OID_RE.fullmatch(blob_oid):
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} must be a regular Git blob")
    raw = _git(repo, ["cat-file", "blob", blob_oid])
    if len(raw) > _MAX_BLOB_BYTES:
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} exceeds {_MAX_BLOB_BYTES} bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise IdentityValidationError(f"{AI_IDENTITY_PATH} must be UTF-8") from exc
    return parse_ai_identities(text, blob_oid=blob_oid)
