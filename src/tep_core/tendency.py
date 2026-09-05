"""Directional tendency. Never rewrites observed values. Not ability or hire."""

from __future__ import annotations

from typing import Any

from tep_core.v2_constants import (
    CONFIDENCE_LEVELS,
    MIN_ACTIVE_DAYS_FOR_SHAPE,
    MIN_EVENTS_FOR_SHAPE,
    MIN_N_DIRECTIONAL,
    MIN_N_NOT_PROVEN,
    MIN_POPULATION_FOR_RATES,
    MIN_WINDOW_DAYS_FOR_SHAPE,
    RELATIONSHIPS,
    STRENGTH_LEVELS,
    SURFACE_LIMITATION,
    SURFACES,
    TENDENCY_CHANGE_NOTE,
    TENDENCY_RATIO_SIMILAR_HIGH,
    TENDENCY_RATIO_SIMILAR_LOW,
    TENDENCY_SHARE_MODERATE,
    TENDENCY_SHARE_STRONG,
)


def _not_proven(reason: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "kind": "not_proven",
        "reason": reason,
        "confidence": "not_proven",
        "limitations": [TENDENCY_CHANGE_NOTE, SURFACE_LIMITATION],
    }
    payload.update(extra)
    return payload


def _numeric(node: Any) -> float | None:
    if not isinstance(node, dict):
        return None
    if node.get("kind") != "observed":
        return None
    value = node.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _share_strength(share: float) -> str:
    if share >= TENDENCY_SHARE_STRONG:
        return "strong"
    if share >= TENDENCY_SHARE_MODERATE:
        return "moderate"
    return "weak"


def surface_tendency(profile: dict[str, Any], *, window: str, source: list[str]) -> dict[str, Any]:
    if profile.get("kind") == "not_observed":
        return _not_proven(profile.get("reason") or "surface_not_observed")
    shares = (profile.get("surface_file_share") or {}).get("values") or {}
    counts = (profile.get("surface_file_counts") or {}).get("values") or {}
    sample = (profile.get("surface_file_counts") or {}).get("sample_size") or 0
    if not isinstance(sample, int) or sample < MIN_POPULATION_FOR_RATES:
        return _not_proven("insufficient_population", n=sample)
    ranked = sorted(
        ((name, float(shares.get(name) or 0.0), int(counts.get(name) or 0)) for name in SURFACES),
        key=lambda item: item[1],
        reverse=True,
    )
    name, share, count = ranked[0]
    return {
        "kind": "directional",
        "value": f"{name}_surface_prominent",
        "strength": _share_strength(share),
        "confidence": "directional",
        "basis": {
            "metric": f"surface_profile.surface_file_share.{name}",
            "observed": share,
            "reference": None,
            "n": sample,
            "denominator": "distinct paths or file-changes in scoped commits",
            "source": source,
            "window": window,
            "count": count,
        },
        "limitations": [
            SURFACE_LIMITATION,
            TENDENCY_CHANGE_NOTE,
            "これは職種ラベルではない。能力・採用・将来成果を示さない。",
        ],
    }


def rhythm_tendency(profile: dict[str, Any], *, window: str, source: list[str]) -> dict[str, Any]:
    if profile.get("kind") == "not_observed":
        return _not_proven(profile.get("reason") or "rhythm_not_observed")
    sample = profile.get("sample_size") or 0
    days = profile.get("window_days") or 0
    if not isinstance(sample, int) or sample < MIN_EVENTS_FOR_SHAPE:
        return _not_proven("insufficient_population", n=sample)
    if not isinstance(days, int) or days < MIN_WINDOW_DAYS_FOR_SHAPE:
        return _not_proven("window_too_short_for_shape", window_days=days)
    median_gap = _numeric(
        profile.get("median_gap_days") or profile.get("inter_event_gap_median_hours")
    )
    label = "regular_submission_direction" if median_gap is not None else "rhythm_observed"
    return {
        "kind": "directional",
        "value": label,
        "strength": "moderate",
        "confidence": "directional",
        "basis": {
            "metric": "change_rhythm.median_gap_days",
            "observed": median_gap,
            "reference": None,
            "n": sample,
            "denominator": profile.get("population") or days,
            "source": source,
            "window": window,
        },
        "limitations": [
            "間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。",
            TENDENCY_CHANGE_NOTE,
        ],
    }


def shape_or_unproven(
    by_day_count: int, event_count: int, window_days: int, label: str
) -> dict[str, Any]:
    if event_count < MIN_EVENTS_FOR_SHAPE or by_day_count < MIN_ACTIVE_DAYS_FOR_SHAPE:
        return _not_proven("insufficient_population", n=event_count)
    if window_days < MIN_WINDOW_DAYS_FOR_SHAPE:
        return _not_proven("window_too_short_for_shape", window_days=window_days)
    return {
        "kind": "observed",
        "unit": "label",
        "value": label,
        "confidence": "directional",
        "limitations": [
            "Observational concentration label only. Not speed, productivity, or excellence.",
            TENDENCY_CHANGE_NOTE,
        ],
    }


def _units_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("unit") and left.get("unit") == right.get("unit")


def _sample_n(actor_n: Any, project_n: Any) -> int:
    values = [
        item
        for item in (actor_n, project_n)
        if isinstance(item, int) and not isinstance(item, bool)
    ]
    if not values:
        return 0
    return min(values)


def relationship(
    *,
    actor_node: dict[str, Any],
    project_node: dict[str, Any],
    declared_node: dict[str, Any],
    windows_comparable: bool,
    actor_n: Any = None,
    project_n: Any = None,
) -> dict[str, Any]:
    if not windows_comparable:
        return {
            "kind": "not_comparable",
            "confidence": "not_proven",
            "reason": "windows_not_equivalent",
            "limitations": ["Git window and project window must match to compare direction."],
        }
    actor_kind = actor_node.get("kind")
    project_kind = project_node.get("kind")
    if actor_kind != "observed" or project_kind != "observed":
        return {
            "kind": "not_comparable",
            "confidence": "not_proven",
            "reason": "observed_unavailable",
        }
    if not _units_match(actor_node, project_node):
        return {
            "kind": "not_comparable",
            "confidence": "not_proven",
            "reason": "unit_mismatch",
        }
    if actor_n is None or project_n is None:
        return {
            "kind": "not_comparable",
            "confidence": "not_proven",
            "reason": "n_missing",
            "actor_n": actor_n,
            "project_n": project_n,
        }
    actor_value = _numeric(actor_node)
    project_value = _numeric(project_node)
    if actor_value is None or project_value is None:
        return {
            "kind": "mixed",
            "confidence": "directional",
            "reason": "non_scalar_observed",
        }
    if project_value == 0 and actor_value == 0:
        direction = "similar_direction"
    elif project_value == 0 or actor_value == 0:
        direction = "different_direction"
    else:
        ratio = actor_value / project_value
        if TENDENCY_RATIO_SIMILAR_LOW <= ratio <= TENDENCY_RATIO_SIMILAR_HIGH:
            direction = "similar_direction"
        else:
            direction = "different_direction"
    if direction not in RELATIONSHIPS:
        direction = "not_comparable"
    sample = _sample_n(actor_n, project_n)
    if sample < MIN_N_NOT_PROVEN:
        return {
            "kind": "not_proven",
            "direction": direction,
            "confidence": "insufficient_data",
            "n": sample,
            "limitations": [
                "n<5 does not support similar_direction as a claim.",
                TENDENCY_CHANGE_NOTE,
            ],
        }
    if sample < MIN_N_DIRECTIONAL:
        return {
            "kind": "not_proven",
            "direction": direction,
            "confidence": "weak_signal",
            "n": sample,
            "limitations": [
                "5<=n<20 is a weak signal, not a determination.",
                TENDENCY_CHANGE_NOTE,
            ],
        }
    return {
        "kind": direction,
        "direction": direction,
        "confidence": "directional_candidate",
        "n": sample,
        "actor_vs_project_observed": direction,
        "limitations": [
            "similar_direction is not hire, fit, or ability.",
            TENDENCY_CHANGE_NOTE,
        ],
    }


def assert_enums(node: dict[str, Any], path: str, errors: list[str]) -> None:
    confidence = node.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE_LEVELS:
        errors.append(f"{path}.confidence: invalid")
    strength = node.get("strength")
    if strength is not None and strength not in STRENGTH_LEVELS:
        errors.append(f"{path}.strength: invalid")
    kind = node.get("kind")
    if kind in RELATIONSHIPS or kind in {"directional", "not_proven", "not_comparable", "mixed"}:
        return
