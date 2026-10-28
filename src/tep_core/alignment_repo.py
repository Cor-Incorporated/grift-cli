"""The alignment `grift align --repo` writes, built in one place.

`grift verify <alignment.json> --repo --identity --project` recomputes the actor
report and rebuilds the whole alignment with `repo_alignment_payload`, the same
function `grift align --repo` uses. Nothing in the comparison is copied from the
saved file: a copied provenance field or limitation verified whatever the file
said (#102 review). Only the recompute inputs are read from the saved file
(as_of and role_lens from its provenance; vendor_scan, survival and reference_id
from `actor_provenance`, where this payload records them), and changing one of
those changes the recomputation, not the comparison.
"""

from __future__ import annotations

from typing import Any

from tep_core.actor_basis import actor_analysis_scope, actor_basis_notice, classify_actor_basis
from tep_core.alignment import alignment_payload, alignment_subject
from tep_core.v2_constants import (
    ALIGNMENT_NOTICE,
    EVIDENCE_DISCLAIMER,
    FORGE_NOT_OBSERVED_NOTE,
    PROJECT_OBSERVED_MISSING_NOTE,
    TRACKER_NOT_OBSERVED_NOTE,
)
from tep_core.version import DEFINITION_VERSION, __version__

# The only mode an alignment carries: made from two saved reports.
SAVED_REPORTS_MODE = "saved_reports"


def alignment_limitations(actor_report: dict[str, Any]) -> list[str]:
    """The limitations every alignment carries for its actor report."""

    subject = actor_report.get("subject") or {}
    basis = classify_actor_basis(subject.get("selection"), subject.get("attribution_state"))
    notes = [ALIGNMENT_NOTICE, EVIDENCE_DISCLAIMER, actor_basis_notice(basis)]
    coverage = actor_report.get("input_coverage") or {}
    if (coverage.get("forge") or {}).get("kind") == "not_observed":
        notes.append(FORGE_NOT_OBSERVED_NOTE)
    if (coverage.get("tracker") or {}).get("kind") == "not_observed":
        notes.append(TRACKER_NOT_OBSERVED_NOTE)
    return notes


def repo_alignment_payload(
    actor_report: dict[str, Any],
    *,
    declared: dict[str, Any],
    project_id: object,
    project_digest: str | None,
    analyzed_at: str | None,
) -> dict[str, Any]:
    """The alignment-v1 payload of `grift align --repo --identity --actor --project`."""

    subject = actor_report.get("subject") or {}
    provenance = actor_report["provenance"]
    payload = alignment_payload(
        actor_report=actor_report,
        declared=declared,
        provenance={
            "tool_name": "grift",
            "tool_version": __version__,
            "definition_version": DEFINITION_VERSION,
            "analysis_scope": actor_analysis_scope(
                subject.get("selection"), subject.get("attribution_state")
            ),
            "analyzed_commit_sha": provenance["analyzed_commit_sha"],
            "analyzed_at": analyzed_at,
            "observation_date": provenance["observation_date"],
            "window_basis": provenance["window_basis"],
            "identity_digest": provenance.get("identity_digest"),
            "actor_commit_sha": provenance["analyzed_commit_sha"],
            "project_commit_sha": None,
            "role_lens": (actor_report.get("role_lens") or {}).get("name"),
            "input_digests": {
                **(provenance.get("input_digests") or {}),
                "project": project_digest,
                "actor_report": None,
            },
        },
        subject=alignment_subject(actor_report, project_id=project_id),
        limitations=alignment_limitations(actor_report) + [PROJECT_OBSERVED_MISSING_NOTE],
    )
    if actor_report.get("reference"):
        payload["reference"] = actor_report["reference"]
    return payload
