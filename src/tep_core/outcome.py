"""W6 — what happened after the work, for the part git cannot see.

Whether a project shipped, held up in production, or was renewed is the half of
"the right person for this work" that no commit records. grift already measures
several outcome-shaped things from history -- `post_release_fixes`,
`adopted_creations`, `self_maintenance_returns`, `cross_author_modification_share`
-- but all of them are proxies read off the repository. Delivery is not.

So this is a declaration channel, and the whole design is about keeping it from
contaminating the evidence.

**A declaration is never an observation.** Every outcome here carries
`kind: "declared"`. It cannot become `observed` by any path, because the moment
an unverifiable claim is presented as a measurement, the one property that makes
this tool worth more than a résumé -- that a third party can recompute it --
is gone. `verify` recomputes observations; it cannot recompute someone's word.

**Who said it, and on what authority.** A self-declared outcome and one attested
by the commissioning party are different objects, and a reader who cannot tell
them apart is being misled by omission. Both are accepted; both say which they are.

**Absence is not failure.** No declaration file means `not_observed`, never "the
work did not ship" (norms §1). Most work has no attestation and never will.

**Declaration is not negative either.** A project that declares an outcome and a
project that does not are not comparable on that basis (norms §3, the same rule
that governs `declared_ai_assist`).

The file is a local input, exactly like the forge and tracker exports: read from
disk, digested, never fetched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tep_core.observation import NotObserved
from tep_core.secrets_guard import InputValidationError

OUTCOME_SCHEMA_VERSION = "tep-outcome-declaration-v1"
OUTCOME_DEFINITION_VERSION = "outcome-v1-2026-09-03"

NOT_PROVIDED_REASON = "outcome_declaration_not_provided"

# Who stands behind the claim. The vocabulary is closed so that "attested" means
# one thing; a free-text authority would let any submission call itself verified.
ATTESTATION_KINDS = {
    # The person who did the work says so. Carries no external corroboration and
    # is labelled as such wherever it is shown.
    "self_declared",
    # The commissioning party says so, in a record the submitter holds.
    "counterparty_attested",
    # A record that exists outside either party (a published release note, a
    # public incident review, a contract milestone).
    "third_party_record",
}

# What is being claimed. Deliberately coarse: finer categories invite scoring,
# and this channel must not become a scale.
OUTCOME_KINDS = {
    "delivered",
    "not_delivered",
    "partially_delivered",
    "superseded",
}

SELF_DECLARED_LIMITATION = (
    "Self-declared: stated by the party who did the work, with no external "
    "corroboration. It is a claim, not a measurement, and no part of this tool "
    "verifies it."
)
# Says what the exclusion in tep_core.verify.NOT_RECOMPUTED_PATHS costs the
# reader. "Not recomputed" alone reads as a protection; it is the opposite --
# nothing is checked here, so nothing detects a change. A reader who takes an
# unguarded field for a guarded one is worse off than one told plainly.
DECLARATION_LIMITATION = (
    "Declared outcomes are not observations. `grift verify` neither recomputes "
    "nor compares them; a modified declaration is not detected by verify. "
    "Their absence is not evidence that work did not ship (norms §1, §3)."
)


@dataclass(frozen=True)
class OutcomeInput:
    digest: str
    declarations: tuple[dict[str, Any], ...]
    source_format: str = OUTCOME_SCHEMA_VERSION


def _require(node: Mapping[str, Any], key: str, path: str) -> Any:
    value = node.get(key)
    if value is None:
        raise InputValidationError(f"{path}.{key} is required")
    return value


def _validate_declaration(raw: Any, index: int) -> dict[str, Any]:
    path = f"declarations[{index}]"
    if not isinstance(raw, Mapping):
        raise InputValidationError(f"{path} must be an object")

    outcome = _require(raw, "outcome", path)
    if outcome not in OUTCOME_KINDS:
        raise InputValidationError(
            f"{path}.outcome must be one of {', '.join(sorted(OUTCOME_KINDS))}"
        )
    attestation = _require(raw, "attestation", path)
    if attestation not in ATTESTATION_KINDS:
        raise InputValidationError(
            f"{path}.attestation must be one of {', '.join(sorted(ATTESTATION_KINDS))}"
        )
    scope = _require(raw, "scope", path)
    if not isinstance(scope, str) or not scope.strip():
        raise InputValidationError(f"{path}.scope must be a non-empty string")

    declaration: dict[str, Any] = {
        "kind": "declared",
        "outcome": str(outcome),
        "attestation": str(attestation),
        "scope": scope.strip(),
        "definition_version": OUTCOME_DEFINITION_VERSION,
    }
    # An attesting party is required for anything claiming external backing;
    # "counterparty_attested" with nobody named is a self-declaration wearing a
    # better label.
    attested_by = raw.get("attested_by")
    if attestation != "self_declared":
        if not isinstance(attested_by, str) or not attested_by.strip():
            raise InputValidationError(
                f"{path}.attested_by is required when attestation is {attestation!r}; "
                "an unattributed attestation is a self-declaration"
            )
        declaration["attested_by"] = attested_by.strip()
    elif attested_by is not None:
        raise InputValidationError(f"{path}.attested_by must be absent for self_declared outcomes")

    for optional in ("occurred_on", "reference"):
        value = raw.get(optional)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise InputValidationError(f"{path}.{optional} must be a non-empty string")
            declaration[optional] = value.strip()

    limitations = [DECLARATION_LIMITATION]
    if attestation == "self_declared":
        limitations.insert(0, SELF_DECLARED_LIMITATION)
    declaration["limitations"] = limitations
    return declaration


def load_outcome_input(path: Path | None) -> OutcomeInput | None:
    """Read and validate a declaration file, or return None when none was given."""
    if path is None:
        return None
    if not path.is_file():
        raise InputValidationError("outcome-declaration file not found")
    body = path.read_bytes()
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"outcome-declaration is not valid JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise InputValidationError("outcome-declaration root must be an object")
    if document.get("schema_version") != OUTCOME_SCHEMA_VERSION:
        raise InputValidationError(
            f"outcome-declaration requires schema_version={OUTCOME_SCHEMA_VERSION!r}"
        )
    raw_list = document.get("declarations")
    if not isinstance(raw_list, list) or not raw_list:
        raise InputValidationError("outcome-declaration must carry a non-empty declarations list")
    declarations = tuple(_validate_declaration(item, index) for index, item in enumerate(raw_list))
    return OutcomeInput(
        digest=hashlib.sha256(body).hexdigest(),
        declarations=declarations,
    )


def outcome_payload(outcome: OutcomeInput | None) -> dict[str, Any]:
    """The report block, or the reason there is none.

    There is no summary field. A count of "delivered" against "not_delivered"
    would be a score built out of claims, which is the one thing this channel
    must not become.
    """
    if outcome is None:
        return {
            **NotObserved(NOT_PROVIDED_REASON).to_dict(),
            "definition_version": OUTCOME_DEFINITION_VERSION,
            "limitations": [DECLARATION_LIMITATION],
        }
    return {
        "kind": "declared",
        "definition_version": OUTCOME_DEFINITION_VERSION,
        "source_format": outcome.source_format,
        "digest": outcome.digest,
        "declarations": list(outcome.declarations),
        "limitations": [DECLARATION_LIMITATION],
    }
