"""Reference distribution lookup. Same-scope only. n<30 suppresses position."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from tep_core.observation import NotObserved
from tep_core.scope import require_same_scope

REFERENCE_VERSION = "v2026.11"
MIN_N = 30
_DATA_DIR = Path(__file__).resolve().parent / "data"
_AVAILABLE_VERSIONS = tuple(
    sorted(p.name for p in _DATA_DIR.iterdir() if p.is_dir() and p.name.startswith("v"))
)
_DATA = _DATA_DIR / REFERENCE_VERSION / "distributions.json"


def distributions_path(version: str | None = None) -> Path:
    """Path to a distribution file; defaults to the current REFERENCE_VERSION.
    v2026.09 remains immutable and selectable (P1c-2: growth ships as new
    versions; old ones stay)."""
    if version is None or version == REFERENCE_VERSION:
        return _DATA
    if version not in _AVAILABLE_VERSIONS:
        raise ValueError(
            f"unknown reference version {version!r}; available: {', '.join(_AVAILABLE_VERSIONS)}"
        )
    return _DATA_DIR / version / "distributions.json"


@lru_cache(maxsize=4)
def load_distributions(version: str | None = None) -> dict:
    path = distributions_path(version)
    if not path.is_file():
        return {
            "version": version or REFERENCE_VERSION,
            "analysis_scope": "repo",
            "metrics": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _quantile_index(sorted_values: list[float], value: float) -> int:
    """1-based decile in 1..10 (ceil of 10 * fraction at-or-below)."""
    if not sorted_values:
        return 1
    below = sum(1 for item in sorted_values if item <= value)
    frac = below / len(sorted_values)
    decile = int(frac * 10)
    if decile < 1:
        return 1
    if decile > 10:
        return 10
    return decile


def interpret_metric(
    *,
    report_scope: str,
    metric_id: str,
    observation: dict,
    reference_version: str | None = None,
) -> dict[str, object]:
    dist = load_distributions(reference_version)
    if report_scope != "repo":
        return NotObserved("scope_is_tenant").to_dict()
    require_same_scope(report_scope, str(dist.get("analysis_scope") or "repo"))
    if observation.get("kind") != "observed":
        return NotObserved("metric_not_observed").to_dict()
    inner = observation.get("all_time") or observation
    if inner.get("kind") != "observed" or inner.get("value") is None:
        return NotObserved("metric_not_observed").to_dict()
    population = inner.get("population")
    if inner.get("narrate_rate") is False or (isinstance(population, int) and population < 20):
        return NotObserved("insufficient_population").to_dict()
    block = (dist.get("metrics") or {}).get(metric_id) or {}
    values = list(block.get("values") or [])
    n = int(block.get("n") or len(values))
    if n < MIN_N:
        return NotObserved("reference_too_small").to_dict()
    value = float(inner["value"])
    decile = _quantile_index(sorted(values), value) if values else _decile_from_bounds(block, value)
    return {
        "kind": "observed",
        "reference_version": dist.get("version", REFERENCE_VERSION),
        "analysis_scope": "repo",
        "n": n,
        "decile": decile,
        "value": value,
        "unit": inner.get("unit", "ratio"),
        "metric_id": metric_id,
    }


def _decile_from_bounds(block: dict, value: float) -> int:
    """Decile from published decile bounds (v2026.11+ ships bounds, not raw
    values — no per-repo league table reconstructability from the wheel)."""
    bounds = list(block.get("deciles") or [])
    if not bounds:
        return 1
    for index in range(10):
        if value <= bounds[index]:
            return index + 1
    return 10
