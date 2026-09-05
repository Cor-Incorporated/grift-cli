"""Load `.tep/identity.toml` (identity-v1 and identity-v2).

Vocabulary is shared with Grift actor_attributions:
canonical_id, emails, github_login, attribution_state.

``identity-v2`` adds privacy-preserving ``email_sha256`` aliases.  The
digest is deliberately domain separated so it cannot be confused with an
ordinary file/content hash::

    sha256(b"tep-email-v1\\0" + email.strip().lower().encode("utf-8"))

The loader accepts the legacy v1 shape unchanged.  V2 is closed at every
object level and rejects ambiguous identity material rather than silently
choosing one actor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

from tep_core.version import IDENTITY_SCHEMA_VERSION

ATTRIBUTION_STATES = frozenset({"verified", "claimed", "inferred", "unresolved", "external", "bot"})
TENANT_STATES = frozenset({"verified", "claimed", "inferred"})
RECORDED_EXPLICIT_CONSENT = "recorded-explicit-consent"
IDENTITY_AUTHORITIES = frozenset({"repository-owner-authorization", "subject-authorization"})
IDENTITY_V1 = "identity-v1"
IDENTITY_V2 = "identity-v2"
SUPPORTED_IDENTITY_VERSIONS = frozenset({IDENTITY_V1, IDENTITY_V2})
IDENTITY_PATH = ".tep/identity.toml"

EMAIL_SHA256_DOMAIN = b"tep-email-v1\0"
EMAIL_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_V2_TOP_LEVEL_KEYS = frozenset({"schema_version", "tenant", "actors"})
_V2_TENANT_KEYS = frozenset({"email_patterns"})
_V2_ACTOR_KEYS = frozenset(
    {
        "canonical_id",
        "emails",
        "email_sha256",
        "github_login",
        "attribution_state",
        "consent",
        "authority",
    }
)

# canonical_id validity (identity-schema.md keeps this regex verbatim;
# tests/test_identity_validation.py enforces the doc<->code match).
CANONICAL_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
CANONICAL_ID_PATTERN_VERSION = 1
CANONICAL_ID_RE = re.compile(CANONICAL_ID_PATTERN)


class IdentityValidationError(ValueError):
    """Producer-side rejection of an invalid identity file (F-P10-3).

    Raised for empty / invalid / duplicate canonical_id. The CLI turns this
    into a non-zero exit; no export may be written from an invalid identity.
    """


class ActorSelectionError(ValueError):
    """Actor view requires one explicit canonical_id and no email_patterns."""


@dataclass(frozen=True)
class Actor:
    canonical_id: str
    emails: tuple[str, ...]
    github_login: str | None
    attribution_state: str
    email_sha256: tuple[str, ...] = ()
    consent: str | None = None
    authority: str | None = None
    identity_schema_version: str = IDENTITY_V1


def has_recorded_explicit_consent(actor: Actor) -> bool:
    """Return whether the identity row records the closed consent marker.

    Only the closed identity-v2 consent + authority pair can unlock the
    observation.  Legacy identity-v1 rows remain readable, but never become
    consent evidence merely because an extension field happened to use the
    same marker.  This is still a local declaration, not proof of the
    declarer's identity, subject personhood, or real-world consent.
    """

    return (
        actor.identity_schema_version == IDENTITY_V2
        and actor.attribution_state in {"verified", "claimed"}
        and actor.consent == RECORDED_EXPLICIT_CONSENT
        and actor.authority in IDENTITY_AUTHORITIES
    )


@dataclass
class IdentityConfig:
    schema_version: str = IDENTITY_SCHEMA_VERSION
    email_patterns: tuple[re.Pattern[str], ...] = ()
    actors: tuple[Actor, ...] = ()
    source_path: Path | None = None
    pending_attribution: bool = True
    _email_to_actor: dict[str, Actor] = field(default_factory=dict, init=False, repr=False)
    _email_digest_to_actor: dict[str, Actor] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        mapping: dict[str, Actor] = {}
        digest_mapping: dict[str, Actor] = {}
        for actor in self.actors:
            for email in actor.emails:
                normalized = normalize_email(email)
                mapping[normalized] = actor
                digest_mapping[email_identity_sha256(normalized)] = actor
            for digest in actor.email_sha256:
                digest_mapping[digest.lower()] = actor
        self._email_to_actor = mapping
        self._email_digest_to_actor = digest_mapping

    @property
    def actor_count(self) -> int:
        return len(self.actors)

    def actor_for_email(self, email: str) -> Actor | None:
        normalized = normalize_email(email)
        actor = self._email_to_actor.get(normalized)
        if actor is not None:
            return actor
        return self._email_digest_to_actor.get(email_identity_sha256(normalized))

    def is_tenant_email(self, email: str) -> bool:
        actor = self.actor_for_email(email)
        if actor is not None and actor.attribution_state in TENANT_STATES:
            return True
        return any(pattern.search(email) for pattern in self.email_patterns)

    def state_for_email(self, email: str) -> str:
        actor = self.actor_for_email(email)
        if actor is not None:
            return actor.attribution_state
        if any(pattern.search(email) for pattern in self.email_patterns):
            return "inferred"
        return "unresolved"


def empty_identity() -> IdentityConfig:
    return IdentityConfig(pending_attribution=True)


def normalize_email(email: str) -> str:
    """Return the normalization used by both v1 matching and v2 hashing."""

    return email.strip().lower()


def email_identity_sha256(email: str) -> str:
    """Return an ``identity-v2`` domain-separated email digest."""

    normalized = normalize_email(email)
    return hashlib.sha256(EMAIL_SHA256_DOMAIN + normalized.encode("utf-8")).hexdigest()


def _reject_unknown_keys(row: dict[str, object], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(row) - allowed)
    if unknown:
        rendered = ", ".join(repr(key) for key in unknown)
        raise IdentityValidationError(f"{path} contains unknown key(s): {rendered}")


def _string_list(value: object, *, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise IdentityValidationError(f"{path} must be an array of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise IdentityValidationError(f"{path}[{index}] must be a non-empty string")
        result.append(item)
    return tuple(result)


def load_identity(
    path: Path | None,
    *,
    _document: dict[str, object] | None = None,
    _source_path: Path | None = None,
) -> IdentityConfig:
    if _document is None:
        if path is None or not path.is_file():
            return empty_identity()
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    else:
        data = _document
        path = _source_path
    if not isinstance(data, dict):
        raise IdentityValidationError("identity document must be an object")
    schema_version = str(data.get("schema_version") or IDENTITY_SCHEMA_VERSION)
    if schema_version not in SUPPORTED_IDENTITY_VERSIONS:
        raise IdentityValidationError(
            f"unsupported identity schema_version {schema_version!r}; "
            "expected identity-v1 or identity-v2"
        )
    strict_v2 = schema_version == IDENTITY_V2
    if strict_v2:
        _reject_unknown_keys(data, _V2_TOP_LEVEL_KEYS, "identity-v2")

    tenant = data.get("tenant", {}) or {}
    if not isinstance(tenant, dict):
        raise IdentityValidationError("tenant must be an object")
    if strict_v2:
        _reject_unknown_keys(tenant, _V2_TENANT_KEYS, "identity-v2.tenant")
    raw_patterns = list(_string_list(tenant.get("email_patterns"), path="tenant.email_patterns"))
    patterns = tuple(re.compile(p, re.I) for p in raw_patterns)
    actors: list[Actor] = []
    seen_ids: set[str] = set()
    seen_email_digests: dict[str, str] = {}
    raw_actors = data.get("actors", []) or []
    if not isinstance(raw_actors, list):
        raise IdentityValidationError("actors must be an array of objects")
    for index, row in enumerate(raw_actors):
        if not isinstance(row, dict):
            raise IdentityValidationError(f"actors[{index}] must be an object")
        if strict_v2:
            _reject_unknown_keys(row, _V2_ACTOR_KEYS, f"identity-v2.actors[{index}]")
        state = str(row.get("attribution_state", "unresolved"))
        if state not in ATTRIBUTION_STATES:
            raise IdentityValidationError(f"unknown attribution_state: {state}")
        consent = row.get("consent")
        if consent is not None and (
            not isinstance(consent, str) or consent != RECORDED_EXPLICIT_CONSENT
        ):
            raise IdentityValidationError(
                f"actors[{index}].consent must be {RECORDED_EXPLICIT_CONSENT!r}"
            )
        authority = row.get("authority")
        if authority is not None and (
            not isinstance(authority, str) or authority not in IDENTITY_AUTHORITIES
        ):
            allowed = ", ".join(sorted(IDENTITY_AUTHORITIES))
            raise IdentityValidationError(f"actors[{index}].authority must be one of: {allowed}")
        if strict_v2 and consent is not None and authority is None:
            raise IdentityValidationError(f"actors[{index}].consent requires an explicit authority")
        if consent is not None and state not in {"verified", "claimed"}:
            raise IdentityValidationError(
                f"actors[{index}].consent requires attribution_state verified or claimed"
            )
        canonical_id = str(row.get("canonical_id") or "")
        if not canonical_id:
            raise IdentityValidationError(
                "canonical_id must not be empty (identity-v1: ^[a-z0-9][a-z0-9._-]{0,63}$)"
            )
        if not CANONICAL_ID_RE.fullmatch(canonical_id):
            raise IdentityValidationError(
                f"invalid canonical_id {canonical_id!r}: must match "
                "^[a-z0-9][a-z0-9._-]{0,63}$ (no '@', whitespace, or control "
                "characters; starts with lowercase alphanumeric; max 64 chars)"
            )
        if canonical_id in seen_ids:
            raise IdentityValidationError(
                f"duplicate canonical_id {canonical_id!r}: each actor row must "
                "have a unique canonical_id"
            )
        seen_ids.add(canonical_id)
        emails = _string_list(row.get("emails"), path=f"actors[{index}].emails")
        email_digests = (
            _string_list(row.get("email_sha256"), path=f"actors[{index}].email_sha256")
            if strict_v2
            else ()
        )
        if strict_v2 and emails and email_digests:
            raise IdentityValidationError(
                f"actors[{index}] must use emails or email_sha256, not both"
            )

        # Preserve legacy v1 material byte-for-byte for identity_digest while
        # matching through the shared normalized lookup in IdentityConfig.
        normalized_emails = (
            tuple(normalize_email(email) for email in emails) if strict_v2 else emails
        )
        normalized_digests: list[str] = []
        for digest_index, digest in enumerate(email_digests):
            normalized = digest.lower()
            if digest != normalized or not EMAIL_SHA256_RE.fullmatch(normalized):
                raise IdentityValidationError(
                    f"actors[{index}].email_sha256[{digest_index}] must be 64 lowercase hex"
                )
            normalized_digests.append(normalized)

        # Treat plaintext aliases and pre-hashed aliases as the same identity
        # namespace.  This catches cross-form reuse without exposing the raw
        # address in an error message.
        actor_digests = [email_identity_sha256(email) for email in normalized_emails]
        actor_digests.extend(normalized_digests)
        if len(actor_digests) != len(set(actor_digests)):
            raise IdentityValidationError(
                f"actors[{index}] contains duplicate normalized email identity"
            )
        for digest in actor_digests:
            previous = seen_email_digests.get(digest)
            if previous is not None:
                raise IdentityValidationError(
                    "email identity digest is assigned to multiple actors: "
                    f"{previous!r} and {canonical_id!r}"
                )
            seen_email_digests[digest] = canonical_id

        github_login = row.get("github_login")
        if strict_v2 and github_login is not None and not isinstance(github_login, str):
            raise IdentityValidationError(f"actors[{index}].github_login must be a string")
        actors.append(
            Actor(
                canonical_id=canonical_id,
                emails=normalized_emails,
                github_login=github_login,
                attribution_state=state,
                email_sha256=tuple(normalized_digests),
                consent=consent,
                authority=authority,
                identity_schema_version=schema_version,
            )
        )
    pending = not patterns and not actors
    return IdentityConfig(
        schema_version=schema_version,
        email_patterns=patterns,
        actors=tuple(actors),
        source_path=path,
        pending_attribution=pending,
    )


def _fixed_identity_blob(repo: Path, revision: str) -> tuple[dict[str, object], str] | None:
    normalized_revision = revision.strip().lower()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", normalized_revision):
        raise IdentityValidationError("identity revision must be a full Git object id")

    def run(args: list[str]) -> bytes:
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
            raise IdentityValidationError("fixed identity Git read timed out") from exc
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise IdentityValidationError(message or "fixed identity Git read failed")
        return result.stdout

    listing = run(["ls-tree", "-z", normalized_revision, "--", IDENTITY_PATH])
    if not listing:
        return None
    rows = [row for row in listing.split(b"\0") if row]
    if len(rows) != 1 or b"\t" not in rows[0]:
        raise IdentityValidationError(f"{IDENTITY_PATH} tree entry is ambiguous")
    metadata, path_bytes = rows[0].split(b"\t", 1)
    try:
        mode, object_type, blob_oid = metadata.decode("ascii").split()
        rendered_path = path_bytes.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise IdentityValidationError(f"{IDENTITY_PATH} tree entry is invalid") from exc
    if rendered_path != IDENTITY_PATH:
        raise IdentityValidationError(f"{IDENTITY_PATH} tree entry has an unexpected path")
    if (
        mode not in {"100644", "100755"}
        or object_type != "blob"
        or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", blob_oid)
    ):
        raise IdentityValidationError(f"{IDENTITY_PATH} must be a regular Git blob")
    raw = run(["cat-file", "blob", blob_oid])
    if len(raw) > 1024 * 1024:
        raise IdentityValidationError(f"{IDENTITY_PATH} exceeds 1048576 bytes")
    try:
        document = tomllib.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise IdentityValidationError(f"invalid fixed {IDENTITY_PATH}: {exc}") from exc
    return document, blob_oid


def load_identity_at_revision(repo: Path, revision: str) -> IdentityConfig:
    """Load only the repo-local identity blob recorded at ``revision``."""

    loaded = _fixed_identity_blob(repo, revision)
    if loaded is None:
        return empty_identity()
    document, _blob_oid = loaded
    return load_identity(
        None,
        _document=document,
        _source_path=repo / IDENTITY_PATH,
    )


def load_subject_identity(
    repo: Path,
    explicit: Path | None,
    *,
    revision: str,
) -> IdentityConfig:
    """v0.6 identity boundary: explicit file or fixed repo blob, never CWD."""

    if explicit is not None:
        return load_identity(explicit)
    return load_identity_at_revision(repo, revision)


def discover_legacy_identity(repo: Path, explicit: Path | None) -> IdentityConfig:
    """Legacy v1 discovery, including the historical CWD compatibility fallback."""

    if explicit is not None:
        return load_identity(explicit)
    candidates = [repo / ".tep" / "identity.toml", Path.cwd() / ".tep" / "identity.toml"]
    for candidate in candidates:
        if candidate.is_file():
            return load_identity(candidate)
    return empty_identity()


def discover_identity(repo: Path, explicit: Path | None) -> IdentityConfig:
    """Compatibility alias for pre-v0.6 callers; subject commands never call this."""

    return discover_legacy_identity(repo, explicit)


def actor_ids(identity: IdentityConfig) -> tuple[str, ...]:
    return tuple(actor.canonical_id for actor in identity.actors)


def identity_digest(identity: IdentityConfig) -> str | None:
    """sha256 of normalized identity. Raw emails enter the digest only."""
    if identity.pending_attribution and not identity.actors and not identity.email_patterns:
        return None
    actor_rows: list[dict[str, object]] = []
    for actor in sorted(identity.actors, key=lambda item: item.canonical_id):
        row: dict[str, object] = {
            "canonical_id": actor.canonical_id,
            "attribution_state": actor.attribution_state,
            "emails": sorted(
                (
                    normalize_email(email)
                    if identity.schema_version == IDENTITY_V2
                    else email.lower()
                )
                for email in actor.emails
            ),
            "github_login": actor.github_login,
        }
        if identity.schema_version == IDENTITY_V2:
            row["email_sha256"] = sorted(actor.email_sha256)
        if actor.consent is not None:
            row["consent"] = actor.consent
        if actor.authority is not None:
            row["authority"] = actor.authority
        actor_rows.append(row)
    payload: dict[str, object] = {
        "actors": actor_rows,
        "email_patterns": sorted(pattern.pattern for pattern in identity.email_patterns),
    }
    if identity.schema_version == IDENTITY_V2:
        payload["schema_version"] = IDENTITY_V2
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def select_actor(identity: IdentityConfig, actor_id: str) -> IdentityConfig:
    """Return a temporary IdentityConfig for one actor. Never writes the file.

    email_patterns cannot be attributed to a single person, so actor view
    refuses them instead of guessing.
    """
    if identity.email_patterns:
        raise ActorSelectionError(
            "email_patterns cannot be safely assigned to one actor; "
            "grift actor requires explicit emails on the selected canonical_id"
        )
    if not CANONICAL_ID_RE.fullmatch(actor_id):
        raise ActorSelectionError("invalid actor id: must match ^[a-z0-9][a-z0-9._-]{0,63}$")
    matches = [actor for actor in identity.actors if actor.canonical_id == actor_id]
    if not matches:
        available = ", ".join(actor_ids(identity)) or "(none)"
        raise ActorSelectionError(f"unknown canonical_id {actor_id!r}; available: {available}")
    selected = matches[0]
    return IdentityConfig(
        schema_version=identity.schema_version,
        email_patterns=(),
        actors=(selected,),
        source_path=identity.source_path,
        pending_attribution=False,
    )
