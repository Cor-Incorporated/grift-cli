"""Fail-closed actor presentation basis shared by CLI and renderers."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from tep_core.v2_constants import (
    ACTOR_ADMIN_NOTICE,
    ACTOR_CLAIMED_NOTICE,
    ACTOR_CONSENT_NOTICE,
    ACTOR_NONCONSENT_NOTICE,
    ACTOR_UNKNOWN_NOTICE,
    ACTOR_VIEW_NOTICE,
    PUBLIC_ACTOR_NOTICE,
)


class ActorBasis(str, Enum):
    PUBLIC_INFERRED = "public_inferred"
    ADMIN_VERIFIED = "admin_verified"
    SELF_CLAIMED = "self_claimed"
    EXPLICIT_NONCONSENT = "explicit_nonconsent"
    UNKNOWN = "unknown"


_NONCONSENT_STATES = frozenset({"inferred", "unresolved", "external", "bot"})
_ACTOR_BASIS_NOTICES = frozenset(
    {
        ACTOR_ADMIN_NOTICE,
        ACTOR_CLAIMED_NOTICE,
        ACTOR_CONSENT_NOTICE,
        ACTOR_NONCONSENT_NOTICE,
        ACTOR_UNKNOWN_NOTICE,
        ACTOR_VIEW_NOTICE,
        PUBLIC_ACTOR_NOTICE,
    }
)


def classify_actor_basis(selection: object, attribution_state: object) -> ActorBasis:
    """Classify presentation semantics without inferring consent from absence."""

    if selection == "inferred_actor":
        return ActorBasis.PUBLIC_INFERRED if attribution_state is None else ActorBasis.UNKNOWN
    if selection != "explicit_actor":
        return ActorBasis.UNKNOWN
    if attribution_state == "verified":
        return ActorBasis.ADMIN_VERIFIED
    if attribution_state == "claimed":
        return ActorBasis.SELF_CLAIMED
    if attribution_state in _NONCONSENT_STATES:
        return ActorBasis.EXPLICIT_NONCONSENT
    return ActorBasis.UNKNOWN


def actor_analysis_scope(selection: object, attribution_state: object) -> str:
    """Return the machine scope implied by an actor presentation basis."""

    basis = classify_actor_basis(selection, attribution_state)
    if basis in {ActorBasis.ADMIN_VERIFIED, ActorBasis.SELF_CLAIMED}:
        return "tenant"
    return "actor_cluster"


def actor_basis_notice(basis: ActorBasis) -> str:
    return {
        ActorBasis.PUBLIC_INFERRED: PUBLIC_ACTOR_NOTICE,
        ActorBasis.ADMIN_VERIFIED: ACTOR_ADMIN_NOTICE,
        ActorBasis.SELF_CLAIMED: ACTOR_CLAIMED_NOTICE,
        ActorBasis.EXPLICIT_NONCONSENT: ACTOR_NONCONSENT_NOTICE,
        ActorBasis.UNKNOWN: ACTOR_UNKNOWN_NOTICE,
    }[basis]


def actor_basis_notices(selection: object, attribution_state: object) -> list[str]:
    """Return display notices; only a claimed basis gets personal-view copy."""

    basis = classify_actor_basis(selection, attribution_state)
    notices = [actor_basis_notice(basis)]
    if basis is ActorBasis.SELF_CLAIMED:
        notices.insert(0, ACTOR_VIEW_NOTICE)
    return notices


def without_actor_basis_notices(notices: Iterable[str]) -> list[str]:
    """Drop persisted basis copy so renderers can recompute it from subject."""

    return [notice for notice in notices if notice not in _ACTOR_BASIS_NOTICES]
