"""Actor directory and collection artifacts for report-v2 repo scope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tep_core.attribution import AttributionIndex, attribution_payload
from tep_core.gitutil import GitCommit
from tep_core.observation import Observed
from tep_core.rhythm import change_rhythm
from tep_core.surface_profile import surface_profile
from tep_core.schema_v2 import validate_actor_card
from tep_core.v2_constants import ACTOR_CARD_SCHEMA_VERSION
from tep_core.version import (
    COORDINATION_DEFINITION_VERSION,
    DEFINITION_VERSION,
    VERIFICATION_DEFINITION_VERSION,
)


def _public_accounts(actor: Any) -> list[dict[str, Any]]:
    status = str(getattr(actor, "public_account_status", "not_requested"))
    rows: list[dict[str, Any]] = []
    for account in getattr(actor, "public_accounts", ()):
        rows.append(
            {
                "provider": account.provider,
                "host": account.host,
                "account_id": account.account_id,
                "handle": account.handle,
                "profile_url": account.profile_url,
                "evidence": {
                    "basis": account.evidence or "provider_commit_account",
                    "account_match_status": status,
                },
            }
        )
    return rows


def actor_directory_payload(index: AttributionIndex, *, human_commit_count: int) -> dict[str, Any]:
    attr = attribution_payload(index, human_commit_count)
    actors = [
        {
            "actor_id": actor.actor_id,
            "internal_actor_id": actor.internal_actor_id,
            "display_name": actor.display_name,
            "display_status": actor.display_status,
            "commit_count": len(actor.commit_shas),
            "commit_count_includes_merges": True,
            "commit_count_nonmerge": actor.nonmerge_count,
            "public_account_status": actor.public_account_status,
            "public_accounts": _public_accounts(actor),
        }
        for actor in index.actors
    ]
    return {
        "observed_count": len(index.actors),
        "actors": actors,
        "attribution": attr,
    }


def actor_card(
    actor: Any,
    commits: list[GitCommit],
    *,
    observation_date: str,
    empty_reason: str = "no_actor_commits",
    git_window: Any = None,
    analyzed_commit_sha: str | None = None,
) -> dict[str, Any]:
    scoped = [item for item in commits if item.sha in set(actor.commit_shas)]
    nonmerge = [item for item in scoped if not item.is_merge]
    surfaces = surface_profile(nonmerge, empty_reason=empty_reason)
    rhythm = change_rhythm(nonmerge, observation_date=observation_date, empty_reason=empty_reason)
    is_public = actor.display_status == "public_handle"
    basis = getattr(actor, "public_handle_basis", None)
    if not is_public:
        join_basis = "git_author_name_or_stable_hash"
    elif basis:
        join_basis = basis
    else:
        join_basis = "unattributed"
    return {
        "schema_version": ACTOR_CARD_SCHEMA_VERSION,
        "report_kind": "actor_card",
        "actor_id": actor.actor_id,
        "display_name": actor.display_name,
        "display_status": actor.display_status,
        "subject": {
            "kind": "actor",
            "canonical_id": actor.actor_id,
            "selection": "inferred_actor",
        },
        "provenance": {
            "definition_version": DEFINITION_VERSION,
            "observation_date": observation_date,
            "git_window": git_window,
            "analyzed_commit_sha": analyzed_commit_sha,
        },
        "identity_join": {
            "identity_source": (
                "declared_identity_toml"
                if "identity_declared" in join_basis
                else "inferred_from_git"
            ),
            "display_status": actor.display_status,
            "join_basis": join_basis,
            "personhood_note": (
                "public_handle with identity_declared basis comes from a consented "
                "identity.toml github_login; public_handle with commit_sha_to_login "
                "basis is a commit-SHA to login join on the public forge API. "
                "grift does not verify account ownership or personhood."
            ),
        },
        "observed": {
            "commits": Observed(len(scoped), "commits").to_dict(),
            "commits_including_merges": Observed(len(scoped), "commits").to_dict(),
            "commits_nonmerge": Observed(len(nonmerge), "commits").to_dict(),
            "active_days": Observed(len({item.date for item in scoped}), "days").to_dict(),
            "surface_profile": surfaces,
            "change_rhythm": rhythm,
        },
        "attribution": {
            "coverage": Observed(
                1.0 if scoped else 0.0, "ratio", sample_size=len(scoped)
            ).to_dict(),
            "ambiguous_count": 0,
            "bot_count": 0,
            "merge_count": actor.merge_count,
            "coauthored_count": actor.coauthored_count,
            "commit_count_includes_merges": True,
        },
        "population": {
            "attribution_human_including_merges": len(scoped),
            "repo_human_nonmerge_commits": len(nonmerge),
            "merge_count": actor.merge_count,
        },
    }


def write_actor_collection(
    dest: Path,
    *,
    report: dict[str, Any],
    markdown: str,
    cards: list[dict[str, Any]],
    manifest: dict[str, Any] | None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (dest / "report.md").write_text(markdown, encoding="utf-8")
    actors_dir = dest / "actors"
    actors_dir.mkdir(parents=True, exist_ok=True)
    listing = {
        "observed_count": len(cards),
        "actors": [
            {
                "actor_id": card["actor_id"],
                "display_name": card["display_name"],
                "display_status": card["display_status"],
                "commit_count": (card.get("observed") or {}).get("commits", {}).get("value"),
            }
            for card in cards
        ],
    }
    (dest / "actors.json").write_text(
        json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for card in cards:
        errors = validate_actor_card(card)
        if errors:
            raise ValueError(
                "actor card validation failed: "
                + "; ".join(errors)
                + f" (actor_id={card.get('actor_id')})"
            )
        safe = str(card["actor_id"]).replace(":", "_")
        (actors_dir / f"{safe}.json").write_text(
            json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if manifest is not None:
        (dest / "collection-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def actor_report_from_card(card: dict[str, Any]) -> dict[str, Any]:
    observed = card.get("observed") or {}
    provenance = dict(card.get("provenance") or {})
    actor_id = card.get("actor_id") or (card.get("subject") or {}).get("canonical_id")
    return {
        "schema_version": "report-v2",
        "report_kind": "evidence",
        "subject": {
            "kind": "actor",
            "canonical_id": actor_id,
            "selection": "inferred_actor",
        },
        "provenance": provenance,
        "surface_profile": observed.get("surface_profile")
        or {"kind": "not_observed", "reason": "card_surface_not_computed"},
        "change_rhythm": observed.get("change_rhythm")
        or {"kind": "not_observed", "reason": "card_rhythm_not_computed"},
        "verification_profile": {
            "kind": "not_observed",
            "reason": "card_verification_not_computed",
            "definition_version": VERIFICATION_DEFINITION_VERSION,
        },
        "coordination_profile": {
            "kind": "not_observed",
            "reason": "card_coordination_not_computed",
            "definition_version": COORDINATION_DEFINITION_VERSION,
        },
        "input_coverage": {
            "git": {"kind": "observed", "value": True, "unit": "boolean", "provided": True},
            "forge": {"kind": "not_observed", "reason": "forge_export_not_provided"},
            "tracker": {"kind": "not_observed", "reason": "tracker_export_not_provided"},
        },
        "role_lens": None,
        "limitations": [
            "actor-card-v1 is an observation card, not a complete report-v2 evidence document.",
        ],
    }
