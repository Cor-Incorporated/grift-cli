"""alignment-v1: axis-by-axis comparison. No overall verdict."""

from __future__ import annotations

from typing import Any

from tep_core.actor_basis import consent_recorded
from tep_core.identity import RECORDED_EXPLICIT_CONSENT
from tep_core.v2_constants import (
    ACTIVE_DAYS_INFLATION_LIMITATION,
    ALIGNMENT_NOTICE,
    COMPARISONS,
    HISTORY_WINDOW_BASIS,
    HISTORY_WINDOW_PREFIX,
    RELATIONSHIP_COMPARED_UNIT,
    RELATIONSHIP_SCOPE_NOT_EQUIVALENT,
    SELECTIVITY_NOTICE,
)
from tep_core.version import ALIGNMENT_SCHEMA_VERSION

_RHYTHM_AXES = (
    ("change_rhythm.active_days_180d", "active_days_180d_min", "min"),
    ("change_rhythm.median_gap_days", "median_gap_days_max", "max"),
    ("change_rhythm.p90_gap_days", "p90_gap_days_max", "max"),
)


def _axis(
    *,
    axis: str,
    declared: dict[str, Any],
    observed: dict[str, Any],
    comparison: str,
    evidence_paths: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    if comparison not in COMPARISONS:
        raise ValueError(f"unknown comparison {comparison}")
    return {
        "axis": axis,
        "declared": declared,
        "observed": observed,
        "comparison": comparison,
        "evidence_paths": evidence_paths,
        "limitations": limitations,
    }


def _numeric_compare(declared: dict[str, Any], observed: dict[str, Any], bound: str) -> str:
    if declared.get("kind") == "not_declared":
        return "not_declared"
    if observed.get("kind") == "not_observed":
        return "not_observed"
    value = observed.get("value")
    target = declared.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "not_observed"
    if bound == "min":
        if value == 0:
            return "observed_zero"
        return "overlap" if value >= target else "outside_declared_range"
    if value == 0 and bound == "max":
        return "overlap"
    return "overlap" if value <= target else "outside_declared_range"


def _presence_compare(declared_items: dict[str, Any], observed_count: dict[str, Any]) -> str:
    if declared_items.get("kind") == "not_declared":
        return "not_declared"
    if observed_count.get("kind") == "not_observed":
        return "not_observed"
    value = observed_count.get("value", 0)
    if value == 0:
        return "observed_zero"
    return "overlap"


def _obs_count(profile: dict[str, Any], group: str, name: str) -> dict[str, Any]:
    if profile.get("kind") == "not_observed":
        return {"kind": "not_observed", "reason": profile.get("reason", "not_observed")}
    values = ((profile.get(group) or {}).get("values")) or {}
    return {
        "kind": "observed",
        "value": int(values.get(name, 0)),
        "unit": "commits",
    }


def _rhythm_obs(profile: dict[str, Any], key: str) -> dict[str, Any]:
    if profile.get("kind") == "not_observed":
        return {"kind": "not_observed", "reason": profile.get("reason", "not_observed")}
    node = profile.get(key) or {"kind": "not_observed", "reason": "not_observed"}
    return node


def _obs_share(profile: dict[str, Any], group: str, name: str) -> dict[str, Any]:
    """The share this name holds of the actor's own work, for a declared floor."""
    if profile.get("kind") == "not_observed":
        return {"kind": "not_observed", "reason": profile.get("reason", "not_observed")}
    values = ((profile.get(group) or {}).get("values")) or {}
    raw = values.get(name)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return {"kind": "not_observed", "reason": "share_not_observed"}
    return {"kind": "observed", "value": float(raw), "unit": "commit_share"}


_DECLARED_UNIT = {
    "surface_commit_counts": "surface",
    "test_type_distribution": "verification-type",
}


def _declared_floor(declared_block: dict[str, Any], name: str) -> float | None:
    """The minimum share the brief asked for, when it asked for one.

    A brief without `min_share` keeps the presence comparison, so existing
    project files mean exactly what they meant before.
    """
    floors = declared_block.get("min_share")
    if not isinstance(floors, dict):
        return None
    value = floors.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)


def _compare_named_axis(
    declared_block: dict[str, Any],
    profile: dict[str, Any],
    count_group: str,
    share_group: str,
    name: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Presence when no floor is declared; a share comparison when one is.

    Stating what the work needs is not weighting: the observation is still
    reported as measured, and the verdict vocabulary is unchanged (norms §7).
    The declared node names what was declared, a surface or a verification type;
    0.8.0 called every declared name a surface (trait-profile design §1.4 row 7).
    """
    unit_label = _DECLARED_UNIT.get(count_group, "surface")
    floor = _declared_floor(declared_block, name)
    if floor is None:
        observed = _obs_count(profile, count_group, name)
        declared_node = {"kind": "declared", "value": name, "unit": unit_label}
        return declared_node, observed, _presence_compare(declared_block, observed)
    counted = _obs_count(profile, count_group, name)
    if counted.get("kind") == "observed" and counted.get("value") == 0:
        # A measured zero keeps its own verdict; it is not a range miss.
        declared_node = {"kind": "declared", "value": floor, "unit": "commit_share"}
        return declared_node, counted, "observed_zero"
    observed = _obs_share(profile, share_group, name)
    declared_node = {"kind": "declared", "value": floor, "unit": "commit_share"}
    return declared_node, observed, _numeric_compare(declared_node, observed, "min")


def build_alignment(
    *,
    actor_report: dict[str, Any],
    declared: dict[str, Any],
    actor_digest: str | None,
    project_digest: str,
) -> list[dict[str, Any]]:
    rhythm = actor_report.get("change_rhythm") or {}
    surfaces = actor_report.get("surface_profile") or {}
    verification = actor_report.get("verification_profile") or {}
    coverage = actor_report.get("input_coverage") or {}
    axes: list[dict[str, Any]] = []
    declared_rhythm = declared.get("change_rhythm") or {}
    for axis, req_key, bound in _RHYTHM_AXES:
        obs_key = axis.split(".", 1)[1]
        declared_node = declared_rhythm.get(req_key) or {
            "kind": "not_declared",
            "reason": "requirement_not_provided",
        }
        observed_node = _rhythm_obs(rhythm, obs_key)
        axes.append(
            _axis(
                axis=axis,
                declared=declared_node,
                observed=observed_node,
                comparison=_numeric_compare(declared_node, observed_node, bound),
                evidence_paths=[
                    f"actor.change_rhythm.{obs_key}",
                    f"project.declared.requirements.change_rhythm.{req_key}",
                ],
                limitations=[
                    "Range comparison is not an ability judgement.",
                    "Gap days are Git author-timestamp intervals, not labor time.",
                    # Only the volume axis carries the volume disclosure (ADR-0001 R4).
                    *([ACTIVE_DAYS_INFLATION_LIMITATION] if obs_key == "active_days_180d" else []),
                ],
            )
        )

    required_surfaces = (
        declared["surfaces"]["value"]
        if declared.get("surfaces", {}).get("kind") == "declared"
        else []
    )
    if required_surfaces:
        for name in required_surfaces:
            declared_node, observed_node, surface_comparison = _compare_named_axis(
                declared.get("surfaces") or {},
                surfaces,
                "surface_commit_counts",
                "surface_commit_share",
                name,
            )
            axes.append(
                _axis(
                    axis=f"surfaces.{name}",
                    declared=declared_node,
                    observed=observed_node,
                    comparison=surface_comparison,
                    evidence_paths=[
                        f"actor.surface_profile.surface_commit_counts.{name}",
                        "project.declared.requirements.surfaces",
                    ],
                    limitations=["A zero here is evidence in this scope, not inexperience."],
                )
            )
    else:
        axes.append(
            _axis(
                axis="surfaces.required",
                declared=declared.get("surfaces")
                or {"kind": "not_declared", "reason": "requirement_not_provided"},
                observed={"kind": "not_observed", "reason": "not_declared"},
                comparison="not_declared",
                evidence_paths=["project.declared.requirements.surfaces"],
                limitations=["No surface requirement was declared."],
            )
        )

    required_ver = (
        declared["verification"]["value"]
        if declared.get("verification", {}).get("kind") == "declared"
        else []
    )
    if required_ver:
        for name in required_ver:
            declared_node, observed_node, ver_comparison = _compare_named_axis(
                declared.get("verification") or {},
                verification,
                "test_type_distribution",
                "test_type_share",
                name,
            )
            axes.append(
                _axis(
                    axis=f"verification.{name}",
                    declared=declared_node,
                    observed=observed_node,
                    comparison=ver_comparison,
                    evidence_paths=[
                        f"actor.verification_profile.test_type_distribution.{name}",
                        "project.declared.requirements.verification",
                    ],
                    limitations=["Test-type labels are path heuristics, not QA certification."],
                )
            )
    else:
        axes.append(
            _axis(
                axis="verification.required",
                declared=declared.get("verification")
                or {"kind": "not_declared", "reason": "requirement_not_provided"},
                observed={"kind": "not_observed", "reason": "not_declared"},
                comparison="not_declared",
                evidence_paths=["project.declared.requirements.verification"],
                limitations=["No verification requirement was declared."],
            )
        )

    required_inputs = (
        declared["inputs"]["value"] if declared.get("inputs", {}).get("kind") == "declared" else []
    )
    input_map = {
        "git": coverage.get("git") or {"kind": "observed", "value": True, "unit": "boolean"},
        "forge": coverage.get("forge"),
        "tracker": coverage.get("tracker"),
    }
    if required_inputs:
        for name in required_inputs:
            observed_node = input_map.get(name) or {
                "kind": "not_observed",
                "reason": f"{name}_export_not_provided",
            }
            comparison = _input_compare(name, observed_node)
            axes.append(
                _axis(
                    axis=f"inputs.{name}",
                    declared={"kind": "declared", "value": name, "unit": "input"},
                    observed=observed_node,
                    comparison=comparison,
                    evidence_paths=[
                        f"actor.input_coverage.{name}",
                        "project.declared.requirements.inputs",
                    ],
                    limitations=[
                        "Missing local export is not evidence that the work did not happen."
                    ],
                )
            )
    else:
        axes.append(
            _axis(
                axis="inputs.required",
                declared=declared.get("inputs")
                or {"kind": "not_declared", "reason": "requirement_not_provided"},
                observed={"kind": "not_observed", "reason": "not_declared"},
                comparison="not_declared",
                evidence_paths=["project.declared.requirements.inputs"],
                limitations=["No input requirement was declared."],
            )
        )

    axes.append(
        _axis(
            axis="role_lens",
            declared=declared.get("role_lens")
            or {"kind": "not_declared", "reason": "requirement_not_provided"},
            observed=actor_report.get("role_lens")
            or {"kind": "not_observed", "reason": "role_lens_not_set"},
            comparison=_lens_compare(declared.get("role_lens"), actor_report.get("role_lens")),
            evidence_paths=["actor.role_lens", "project.declared.requirements.role_lens"],
            limitations=["role_lens is a display preset, not a job classification."],
        )
    )
    return axes


def _input_compare(name: str, observed: dict[str, Any]) -> str:
    if observed.get("kind") == "not_observed":
        return "not_observed"
    if name == "git":
        return "overlap"
    if observed.get("provided") is True or observed.get("value") is True:
        return "overlap"
    return "not_observed"


def _lens_compare(declared: dict[str, Any] | None, observed: dict[str, Any] | None) -> str:
    if not declared or declared.get("kind") == "not_declared":
        return "not_declared"
    if not observed:
        return "not_observed"
    if observed.get("name") == declared.get("value"):
        return "overlap"
    return "outside_declared_range"


def forbidden_key_hits(node: Any, prefix: str = "") -> list[str]:
    from tep_core.v2_constants import FORBIDDEN_VERDICT_KEYS

    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_VERDICT_KEYS:
                hits.append(path)
            hits.extend(forbidden_key_hits(value, path))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            hits.extend(forbidden_key_hits(value, f"{prefix}[{index}]"))
    return hits


def _node_unit(node: Any) -> Any:
    if isinstance(node, dict):
        return node.get("unit")
    return None


def _node_n(node: Any) -> Any:
    if isinstance(node, dict):
        return node.get("sample_size", node.get("n"))
    return None


def _node_denominator(node: Any) -> Any:
    if isinstance(node, dict):
        return node.get("population", node.get("denominator"))
    return None


def _project_axis_value(axis_name: str, observed: dict[str, Any] | None) -> dict[str, Any]:
    if not observed or observed.get("kind") == "not_observed":
        return {
            "kind": "not_observed",
            "reason": (observed or {}).get("reason") or "project_observed_not_provided",
        }
    if axis_name.startswith("change_rhythm."):
        key = axis_name.split(".", 1)[1]
        rhythm = observed.get("change_rhythm") or {}
        return _rhythm_obs(rhythm, key)
    if axis_name.startswith("surfaces."):
        name = axis_name.split(".", 1)[1]
        return _obs_count(observed.get("surface_profile") or {}, "surface_commit_counts", name)
    if axis_name.startswith("verification."):
        name = axis_name.split(".", 1)[1]
        return _obs_count(
            observed.get("verification_profile") or {}, "test_type_distribution", name
        )
    if axis_name.startswith("inputs."):
        name = axis_name.split(".", 1)[1]
        coverage = observed.get("input_coverage") or {}
        return coverage.get(name) or {
            "kind": "not_observed",
            "reason": f"{name}_export_not_provided",
        }
    return {"kind": "not_observed", "reason": "axis_not_in_project_observed"}


def _basis(node: dict[str, Any], *, source: list[str], window: Any) -> dict[str, Any]:
    return {
        "metric_kind": node.get("kind"),
        "unit": _node_unit(node),
        "n": _node_n(node),
        "denominator": _node_denominator(node),
        "source": source,
        "window": window,
    }


_HISTORY_AXES = ("surfaces.", "verification.")
_SHARE_SOURCES = {
    "surfaces.": ("surface_profile", "surface_commit_share"),
    "verification.": ("verification_profile", "test_type_share"),
}


def _history_window(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """What surface and verification counts cover: every scoped commit to the date."""
    end = ((report or {}).get("provenance") or {}).get("observation_date")
    if not end:
        return None
    return {"end": end, "unit": "date-range", "basis": HISTORY_WINDOW_BASIS}


def enrich_axes(
    axes: list[dict[str, Any]],
    project_observed: dict[str, Any] | None,
    *,
    actor_report: dict[str, Any],
    project_report: dict[str, Any] | None = None,
) -> None:
    from tep_core.tendency import relationship, rhythm_tendency, surface_tendency

    rhythm = (
        (actor_report.get("provenance") or {}).get("git_window"),
        ((project_report or {}).get("provenance") or {}).get("git_window"),
    )
    history = (_history_window(actor_report), _history_window(project_report))
    sources = (["git:path", "git:author_timestamp"], ["git:path", "git:author_timestamp"])
    helpers = (relationship, surface_tendency, rhythm_tendency)
    for axis in axes:
        windows = history if str(axis.get("axis") or "").startswith(_HISTORY_AXES) else rhythm
        _enrich_one_axis(
            axis,
            project_observed,
            actor_report=actor_report,
            windows=windows,
            windows_comparable=_windows_equivalent(*windows) if project_report else False,
            sources=sources,
            helpers=helpers,
        )


def _windows_equivalent(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return left.get("start") == right.get("start") and left.get("end") == right.get("end")


def _enrich_one_axis(
    axis: dict[str, Any],
    project_observed: dict[str, Any] | None,
    *,
    actor_report: dict[str, Any],
    windows: tuple[Any, Any],
    windows_comparable: bool,
    sources: tuple[list[str], list[str]],
    helpers: tuple[Any, Any, Any],
) -> None:
    relationship_fn, surface_tendency, rhythm_tendency = helpers
    (actor_window, project_window), (actor_src, project_src) = windows, sources
    actor_node = axis.get("observed") or {}
    project_node = _project_axis_value(str(axis.get("axis")), project_observed)
    declared_node = axis.get("declared") or {}
    _copy_axis_observations(
        axis,
        actor_node,
        project_node,
        declared_node,
        actor_src=actor_src,
        project_src=project_src,
        actor_window=actor_window,
        project_window=project_window,
    )
    if axis["actor_n"] is None:
        axis["actor_n"] = _node_n(actor_report.get("surface_profile") or {}) or _node_n(
            actor_report.get("change_rhythm") or {}
        )
    if axis["project_n"] is None and project_observed:
        axis["project_n"] = _node_n(project_observed.get("surface_profile") or {}) or _node_n(
            project_observed.get("change_rhythm") or {}
        )
    _assign_axis_tendency(
        axis,
        actor_report=actor_report,
        project_observed=project_observed,
        actor_window=actor_window,
        project_window=project_window,
        actor_src=actor_src,
        project_src=project_src,
        surface_tendency=surface_tendency,
        rhythm_tendency=rhythm_tendency,
    )
    nodes = (actor_node, project_node, declared_node)
    _assign_axis_relationship(
        axis,
        nodes=nodes,
        actor_report=actor_report,
        project_observed=project_observed,
        windows_comparable=windows_comparable,
        relationship_fn=relationship_fn,
    )


def _copy_axis_observations(
    axis: dict[str, Any],
    actor_node: dict[str, Any],
    project_node: dict[str, Any],
    declared_node: dict[str, Any],
    *,
    actor_src: list[str],
    project_src: list[str],
    actor_window: Any,
    project_window: Any,
) -> None:
    axis["actor_observed"] = actor_node
    axis["project_observed"] = project_node
    axis["project_declared"] = declared_node
    axis["actor_n"] = _node_n(actor_node)
    axis["project_n"] = _node_n(project_node)
    axis["actor_denominator"] = _node_denominator(actor_node)
    axis["project_denominator"] = _node_denominator(project_node)
    axis["actor_source"] = list(actor_src)
    axis["project_source"] = list(project_src)
    axis["actor_basis"] = _basis(actor_node, source=actor_src, window=actor_window)
    axis["project_basis"] = _basis(project_node, source=project_src, window=project_window)
    axis["actor_window"] = actor_window
    axis["project_window"] = project_window
    axis["definition_version"] = {"actor": None, "project": None}
    axis["unit"] = _node_unit(actor_node) or _node_unit(project_node)
    axis["n"] = axis["actor_n"]
    axis["denominator"] = axis["actor_denominator"]
    axis["source"] = "actor.report + project.declared"


def _assign_axis_tendency(
    axis: dict[str, Any],
    *,
    actor_report: dict[str, Any],
    project_observed: dict[str, Any] | None,
    actor_window: Any,
    project_window: Any,
    actor_src: list[str],
    project_src: list[str],
    surface_tendency: Any,
    rhythm_tendency: Any,
) -> None:
    name = str(axis.get("axis") or "")
    unproven = {"kind": "not_proven", "reason": "no_tendency_for_axis", "confidence": "not_proven"}
    if name.startswith("surfaces."):
        axis["actor_tendency"] = surface_tendency(
            actor_report.get("surface_profile") or {},
            window=_window_str(actor_window),
            source=actor_src,
        )
        axis["project_tendency"] = surface_tendency(
            (project_observed or {}).get("surface_profile") or {},
            window=_window_str(project_window),
            source=project_src,
        )
        return
    if name.startswith("change_rhythm."):
        axis["actor_tendency"] = rhythm_tendency(
            actor_report.get("change_rhythm") or {},
            window=_window_str(actor_window),
            source=actor_src,
        )
        axis["project_tendency"] = rhythm_tendency(
            (project_observed or {}).get("change_rhythm") or {},
            window=_window_str(project_window),
            source=project_src,
        )
        return
    axis["actor_tendency"] = dict(unproven)
    axis["project_tendency"] = dict(unproven)


def _assign_axis_relationship(
    axis: dict[str, Any],
    *,
    nodes: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    actor_report: dict[str, Any],
    project_observed: dict[str, Any] | None,
    windows_comparable: bool,
    relationship_fn: Any,
) -> None:
    if not project_observed or project_observed.get("kind") == "not_observed":
        axis["relationship"] = {
            "kind": "not_comparable",
            "confidence": "not_proven",
            "reason": "project_observed_not_provided",
        }
        axis["incomparable_reason"] = "project_observed_not_provided"
        axis["coverage"] = {"status": "partial", "missing": ["project_observed"]}
        return
    axis["source"] = "actor.report + project.observed + project.declared"
    name = str(axis.get("axis") or "")
    if name.startswith("change_rhythm."):
        relation = _scope_not_equivalent()
    else:
        relation = _axis_relationship(
            axis, nodes, actor_report, project_observed, windows_comparable, relationship_fn
        )
    axis["relationship"] = relation
    if relation.get("kind") == "not_comparable":
        scope = relation.get("reason") == RELATIONSHIP_SCOPE_NOT_EQUIVALENT
        missing = "comparable_scope" if scope else "comparable_windows_or_units"
        axis["incomparable_reason"] = relation.get("reason")
        axis["coverage"] = {"status": "partial", "missing": [missing]}
        return
    axis["incomparable_reason"] = None
    axis["coverage"] = {"status": "present", "missing": []}


def _scope_not_equivalent() -> dict[str, Any]:
    """One person's gaps and day counts against a whole repository's are not one scale."""
    return {
        "kind": "not_comparable",
        "confidence": "not_proven",
        "reason": RELATIONSHIP_SCOPE_NOT_EQUIVALENT,
        "limitations": [
            "An actor's commits and a repository's commits are different populations; "
            "gap and day counts change with the number of people, so they are not compared."
        ],
    }


def _share_with_n(profile: dict[str, Any], group: str, name: str) -> tuple[dict[str, Any], Any]:
    """The share node the relationship compares, with its own reason and n."""
    block = profile.get(group) or {}
    if profile.get("kind") != "not_observed" and block.get("kind") not in (None, "observed"):
        node = {"kind": "not_observed", "reason": block.get("reason") or "share_not_observed"}
    else:
        node = _obs_share(profile, group, name)
    sample = block.get("sample_size")
    if isinstance(sample, bool) or not isinstance(sample, int):
        sample = None
    if node.get("kind") == "observed" and sample is not None:
        node = {**node, "sample_size": sample}
    return node, sample


def _axis_relationship(
    axis: dict[str, Any],
    nodes: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    actor_report: dict[str, Any],
    project_observed: dict[str, Any],
    windows_comparable: bool,
    relationship_fn: Any,
) -> dict[str, Any]:
    """Surfaces and test types compare within-scope shares, never raw counts.

    Dividing one person's commit count by a team's made the direction a measure
    of team size (trait-profile design §1.4 row 1).
    """
    actor_node, project_node, declared_node = nodes
    name = str(axis.get("axis") or "")
    prefix = next((key for key in _SHARE_SOURCES if name.startswith(key)), None)
    if prefix is None:
        return relationship_fn(
            actor_node=actor_node,
            project_node=project_node,
            declared_node=declared_node,
            windows_comparable=windows_comparable,
            actor_n=axis.get("actor_n"),
            project_n=axis.get("project_n"),
        )
    profile_key, group = _SHARE_SOURCES[prefix]
    item = name.split(".", 1)[1]
    actor_share, actor_n = _share_with_n(actor_report.get(profile_key) or {}, group, item)
    project_share, project_n = _share_with_n(project_observed.get(profile_key) or {}, group, item)
    relation = relationship_fn(
        actor_node=actor_share,
        project_node=project_share,
        declared_node=declared_node,
        windows_comparable=windows_comparable,
        actor_n=actor_n,
        project_n=project_n,
    )
    return {
        **relation,
        "compared": RELATIONSHIP_COMPARED_UNIT,
        "actor_share": actor_share,
        "project_share": project_share,
    }


def _window_str(window: Any) -> str:
    if isinstance(window, dict) and window.get("basis") == HISTORY_WINDOW_BASIS:
        return f"{HISTORY_WINDOW_PREFIX}{window.get('end')}"
    if isinstance(window, dict) and window.get("start"):
        return f"{window.get('start')}/{window.get('end')}"
    return "unspecified"


def alignment_subject(
    actor_report: dict[str, Any],
    *,
    project_id: object,
    mode: str | None = None,
) -> dict[str, object]:
    """The alignment subject. Optional actor fields stay absent instead of null.

    `actor_consent` copies the consent record with the same check as the actor
    report's trait section (T7), so the alignment asks interview questions under
    the same rule, and `grift verify` rebuilds it from the actor report instead
    of trusting the saved value.
    """

    actor_subject = actor_report.get("subject") or {}
    subject: dict[str, object] = {
        "kind": "alignment",
        "actor_canonical_id": actor_subject.get("canonical_id"),
        "project_id": project_id,
    }
    if actor_subject.get("selection") is not None:
        subject["actor_selection"] = actor_subject["selection"]
    if actor_subject.get("attribution_state") is not None:
        subject["actor_attribution_state"] = actor_subject["attribution_state"]
    if actor_subject.get("selection") != "inferred_actor" and consent_recorded(actor_report):
        subject["actor_consent"] = RECORDED_EXPLICIT_CONSENT
    if mode is not None:
        subject["mode"] = mode
    return subject


def alignment_payload(
    *,
    actor_report: dict[str, Any],
    declared: dict[str, Any],
    provenance: dict[str, Any],
    subject: dict[str, Any],
    limitations: list[str],
    project_report: dict[str, Any] | None = None,
    actor_report_digest: str | None = None,
    project_report_digest: str | None = None,
) -> dict[str, Any]:
    axes = build_alignment(
        actor_report=actor_report,
        declared=declared,
        actor_digest=provenance.get("identity_digest"),
        project_digest=str(provenance.get("input_digests", {}).get("project") or ""),
    )
    project_observed = (project_report or {}).get("observed") if project_report else None
    enrich_axes(
        axes,
        project_observed,
        actor_report=actor_report,
        project_report=project_report,
    )
    payload = {
        "schema_version": ALIGNMENT_SCHEMA_VERSION,
        "report_kind": "alignment",
        "subject": subject,
        "provenance": provenance,
        "declared": declared,
        "observed_subject": {
            "kind": actor_report.get("subject", {}).get("kind"),
            "canonical_id": actor_report.get("subject", {}).get("canonical_id"),
        },
        "axes": axes,
        "missing_axes": [
            axis["axis"]
            for axis in axes
            if axis.get("comparison") in {"not_observed", "not_declared"}
        ],
        "coverage": {
            "status": "partial"
            if any(axis.get("comparison") in {"not_observed", "not_declared"} for axis in axes)
            else "present",
            "missing": [
                axis["axis"]
                for axis in axes
                if axis.get("comparison") in {"not_observed", "not_declared"}
            ],
        },
        "limitations": limitations,
        "notices": [ALIGNMENT_NOTICE, SELECTIVITY_NOTICE],
        "actor_observed": {
            "surface_profile": actor_report.get("surface_profile"),
            "change_rhythm": actor_report.get("change_rhythm"),
            "verification_profile": actor_report.get("verification_profile"),
            "input_coverage": actor_report.get("input_coverage"),
        },
        "project_declared": declared,
        "project_observed": project_observed
        or {"kind": "not_observed", "reason": "project_report_not_provided"},
        "actor_provenance": actor_report.get("provenance"),
        "project_provenance": (project_report or {}).get("provenance"),
        "actor_report_digest": actor_report_digest,
        "project_report_digest": project_report_digest,
    }
    hits = forbidden_key_hits(payload)
    if hits:
        raise RuntimeError(f"alignment payload contained forbidden keys: {hits}")
    return payload
