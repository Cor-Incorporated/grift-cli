"""W5 — what a team collectively does not cover, stated without ranking anyone.

The one place grift looks at several actors at once. It exists because the
question a client actually has is not "who is best" but "is anything my project
needs missing here", and the question the team actually has is the same one
asked earlier: *before* signing, not halfway through.

Everything about the shape follows from those two readers.

**Counts, never values.** A requirement reports how many actors meet the
declared floor and how many have touched it at all. No individual's measurement
leaves this module, not even anonymously as a maximum. Two integers carry what
the client needs -- "nobody meets 0.20, but three people have worked in it" is a
ramp-up story, "nobody meets it and nobody has touched it" is a from-scratch
one, and those price differently -- while ranking one person against another
stays impossible because no per-person number is ever emitted.

**Three states, not two.** `covered` / `below_declared` / `not_observed`.
Folding the third into the second is the defect this codebase keeps finding --
reporting what was not measured as if it were measured -- and here it would land
on someone's livelihood: "this team has no integration-test evidence" reads as
incapacity when the truth may be that no test framework was detected.

**Observability first.** A report where six of nine requirements could not be
observed is misleading no matter how carefully each row is worded, because a
reader takes "2 of 3 covered" and forgets the six. The rate is emitted ahead of
the requirements and repeated in the limitations.

**A minimum team size.** Below three actors, "the team covers it, 1 of 2" is a
per-person value wearing a count's clothing, and complementarity is not a real
question anyway -- read the two reports. The module refuses instead.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from tep_core.alignment import _compare_named_axis
from tep_core.observation import NotObserved

COMPLEMENTARITY_DEFINITION_VERSION = "complementarity-v1-2026-09-03"

# Below this, a count is an identity. See the module docstring.
MIN_TEAM_SIZE = 3

COVERED = "covered"
BELOW_DECLARED = "below_declared"
NOT_OBSERVED = "not_observed"

# Which declared blocks name individual requirements, and where each is measured
# in an actor report. Adding a block here without a profile to read it from
# would silently produce "not covered" for something never looked at.
_NAMED_AXES = (
    ("surfaces", "surface_profile", "surface_commit_counts", "surface_commit_share"),
    ("verification", "verification_profile", "test_type_distribution", "test_type_share"),
)

TEAM_LIMITATION = (
    "Counts describe how many actors met a declared requirement, never which "
    "ones and never by how much. This report cannot rank the team and is not "
    "input to a decision about any individual."
)
NOT_COMPARABLE_LIMITATION = (
    "Two complementarity reports are not comparable. Each is computed against "
    "the floors one project declared, so the counts share no scale."
)
ABSENCE_LIMITATION = (
    "A requirement below its floor is a statement about this evidence, not "
    "about anyone's ability. Work that leaves no trace in the analysed history "
    "cannot appear here (norms §1)."
)


def _observability_limitation(observable: int, total: int) -> str:
    return (
        f"{observable} of {total} declared requirements could be observed. "
        f"The remaining {total - observable} were not measured and are neither "
        "covered nor uncovered; read the coverage counts only against the "
        f"{observable} that were."
    )


def _declared_names(block: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(block, Mapping) or block.get("kind") == "not_declared":
        return []
    value = block.get("value")
    return sorted(str(item) for item in value) if isinstance(value, list) else []


def _requirement(
    *,
    axis: str,
    declared_block: Mapping[str, Any],
    name: str,
    profiles: Sequence[Mapping[str, Any]],
    count_group: str,
    share_group: str,
) -> dict[str, Any]:
    """One requirement, reduced to counts before it leaves this function."""
    meeting = 0
    with_any = 0
    observed_for = 0
    declared_node: dict[str, Any] = {"kind": "not_declared"}
    for profile in profiles:
        declared_node, observed, verdict = _compare_named_axis(
            dict(declared_block), dict(profile), count_group, share_group, name
        )
        if verdict == "not_observed":
            continue
        observed_for += 1
        if verdict == "overlap":
            meeting += 1
            with_any += 1
        elif verdict != "observed_zero":
            # Measured, non-zero, and short of the floor: someone has worked
            # here. That distinction is the difference between ramp-up and
            # from-scratch, and it is the reason this second count exists.
            with_any += 1
        _ = observed  # individual values are deliberately discarded here

    if observed_for == 0:
        return {
            "requirement": axis,
            "state": NOT_OBSERVED,
            "reason": "no_actor_observation_for_this_requirement",
            "declared": declared_node,
            "team_size": len(profiles),
            "actors_observed": 0,
        }
    return {
        "requirement": axis,
        "state": COVERED if meeting > 0 else BELOW_DECLARED,
        "declared": declared_node,
        "meeting_declared": meeting,
        "with_any_observation": with_any,
        "actors_observed": observed_for,
        "team_size": len(profiles),
    }


def build_complementarity(
    *,
    actor_reports: Iterable[Mapping[str, Any]],
    declared: Mapping[str, Any],
    project_digest: str,
) -> dict[str, Any]:
    """Coverage gaps for a team against one project's declared requirements."""
    reports = list(actor_reports)
    if len(reports) < MIN_TEAM_SIZE:
        return {
            **NotObserved("insufficient_team_size").to_dict(),
            "definition_version": COMPLEMENTARITY_DEFINITION_VERSION,
            "limitations": [
                f"Complementarity needs at least {MIN_TEAM_SIZE} actors. Below "
                "that a coverage count identifies individuals, and the question "
                "is answered by reading each actor's own report."
            ],
        }

    requirements: list[dict[str, Any]] = []
    for block_name, profile_key, count_group, share_group in _NAMED_AXES:
        declared_block = declared.get(block_name) or {}
        profiles = [dict(report.get(profile_key) or {}) for report in reports]
        for name in _declared_names(declared_block):
            requirements.append(
                _requirement(
                    axis=f"{block_name}.{name}",
                    declared_block=declared_block,
                    name=name,
                    profiles=profiles,
                    count_group=count_group,
                    share_group=share_group,
                )
            )

    if not requirements:
        return {
            **NotObserved("no_named_requirements_declared").to_dict(),
            "definition_version": COMPLEMENTARITY_DEFINITION_VERSION,
            "limitations": [
                "The project declared no named surface or verification "
                "requirements, so there is nothing to be missing."
            ],
        }

    total = len(requirements)
    observable = sum(1 for item in requirements if item["state"] != NOT_OBSERVED)
    return {
        "kind": "observed",
        "definition_version": COMPLEMENTARITY_DEFINITION_VERSION,
        "project_digest": project_digest,
        "team_size": len(reports),
        # Emitted before the requirements so a reader meets the rate first.
        "observability": {
            "declared_requirements": total,
            "observable": observable,
            "not_observable": total - observable,
            "share": round(observable / total, 4),
        },
        "requirements": requirements,
        "limitations": [
            _observability_limitation(observable, total),
            TEAM_LIMITATION,
            NOT_COMPARABLE_LIMITATION,
            ABSENCE_LIMITATION,
        ],
    }
