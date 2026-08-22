"""Load `.tep/identity.toml` (identity-v1).

Vocabulary is shared with Grift actor_attributions:
canonical_id, emails, github_login, attribution_state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

from tep_core.version import IDENTITY_SCHEMA_VERSION

ATTRIBUTION_STATES = frozenset({"verified", "claimed", "inferred", "unresolved", "external", "bot"})
TENANT_STATES = frozenset({"verified", "claimed", "inferred"})

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


@dataclass(frozen=True)
class Actor:
    canonical_id: str
    emails: tuple[str, ...]
    github_login: str | None
    attribution_state: str


@dataclass
class IdentityConfig:
    schema_version: str = IDENTITY_SCHEMA_VERSION
    email_patterns: tuple[re.Pattern[str], ...] = ()
    actors: tuple[Actor, ...] = ()
    source_path: Path | None = None
    pending_attribution: bool = True
    _email_to_actor: dict[str, Actor] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        mapping: dict[str, Actor] = {}
        for actor in self.actors:
            for email in actor.emails:
                mapping[email.lower()] = actor
        self._email_to_actor = mapping

    @property
    def actor_count(self) -> int:
        return len(self.actors)

    def actor_for_email(self, email: str) -> Actor | None:
        return self._email_to_actor.get(email.lower())

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


def load_identity(path: Path | None) -> IdentityConfig:
    if path is None or not path.is_file():
        return empty_identity()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    raw_patterns = list(data.get("tenant", {}).get("email_patterns", []) or [])
    patterns = tuple(re.compile(p, re.I) for p in raw_patterns)
    actors: list[Actor] = []
    seen_ids: set[str] = set()
    for row in data.get("actors", []) or []:
        state = str(row.get("attribution_state", "unresolved"))
        if state not in ATTRIBUTION_STATES:
            raise ValueError(f"unknown attribution_state: {state}")
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
        emails = tuple(str(e) for e in (row.get("emails") or []) if e)
        actors.append(
            Actor(
                canonical_id=canonical_id,
                emails=emails,
                github_login=row.get("github_login"),
                attribution_state=state,
            )
        )
    pending = not patterns and not actors
    return IdentityConfig(
        schema_version=str(data.get("schema_version") or IDENTITY_SCHEMA_VERSION),
        email_patterns=patterns,
        actors=tuple(actors),
        source_path=path,
        pending_attribution=pending,
    )


def discover_identity(repo: Path, explicit: Path | None) -> IdentityConfig:
    if explicit is not None:
        return load_identity(explicit)
    candidates = [repo / ".tep" / "identity.toml", Path.cwd() / ".tep" / "identity.toml"]
    for candidate in candidates:
        if candidate.is_file():
            return load_identity(candidate)
    return empty_identity()
