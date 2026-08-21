"""Reference distribution lookup. Same-scope only. n<30 suppresses position."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from tep_core.observation import NotObserved
from tep_core.scope import require_same_scope

REFERENCE_VERSION = "v2026.09"
MIN_N = 30
_DATA = Path(__file__).resolve().parent / "data" / "v2026.09" / "distributions.json"


@lru_cache(maxsize=1)
def load_distributions() -> dict:
    if not _DATA.is_file():
        return {
            "version": REFERENCE_VERSION,
            "analysis_scope": "repo",
            "metrics": {},
        }
    return json.loads(_DATA.read_text(encoding="utf-8"))


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
) -> dict[str, object]:
    dist = load_distributions()
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
    decile = _quantile_index(sorted(values), value)
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
