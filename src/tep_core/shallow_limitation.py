"""The limitation report-v2 carries when its commit graph is truncated (0.9.1 J4).

0.9.0 wrote "repository-wide counts, spans and actor totals are reported as
not_observed rather than measured from the fetched slice", while surface_profile,
change_rhythm and an actor's own activity were still observed from the fetched
commits. The sentence is now read off the finished payload: it names every value
the truncation made not_observed (reason `history_incomplete`) and the blocks whose
other values count only the commits the shallow clone holds. Nothing is removed
from the payload; only the sentence describing it changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tep_core.context_profile import HISTORY_INCOMPLETE_REASON

# Blocks measured from the commits a shallow clone holds. One is named only when
# the payload carries it with an observed value (or, like population, plain counts).
# coordination_profile is named by its git part: review and tracker come from a
# bound forge or tracker export. survival blames the fetched commits, so a line older
# than the cut counts as written by the oldest fetched commit. interpretation places
# test_cochange and rework. Not named: test_frameworks (files at HEAD),
# input_coverage, the export-fed blocks, outcome, role_lens, and reference (the forge
# event rhythm on a catalog). tests/test_v091_shallow_json.py checks this both ways.
_COUNTED_PATHS = (
    "origin",
    "attribution",
    "activity",
    "actor_directory",
    "core_activity_period",
    "test_cochange",
    "rework",
    "survival",
    "context_profile",
    "surface_profile",
    "change_rhythm",
    "verification_profile",
    "coordination_profile.git",
    "population",
    "metrics",
    "interpretation",
)


def _degraded(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and node.get("kind") == "not_observed"
        and node.get("reason") == HISTORY_INCOMPLETE_REASON
    )


def _children(node: Any, path: str) -> Iterator[tuple[str, Any]]:
    items = node.items() if isinstance(node, dict) else enumerate(node)
    for key, value in items:
        yield (f"{path}.{key}" if path else str(key)), value


def _kind_nodes(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict) and "kind" in node:
        yield node
    if isinstance(node, (dict, list)):
        for _path, value in _children(node, ""):
            yield from _kind_nodes(value)


def _missing(node: Any, path: str = "") -> list[str]:
    """Paths of every history_incomplete value; a block whose every value is one
    is named once, as the block."""
    if _degraded(node):
        return [path]
    if not isinstance(node, (dict, list)):
        return []
    found = [item for child, value in _children(node, path) for item in _missing(value, child)]
    whole = isinstance(node, dict) and "kind" not in node
    if path and found and whole and all(_degraded(item) for item in _kind_nodes(node)):
        return [path]
    return found


def _at(payload: dict[str, Any], path: str) -> Any:
    node: Any = payload
    for key in path.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _counted(node: Any) -> bool:
    if not isinstance(node, dict) or node.get("kind") == "not_observed":
        return False
    kinds = [item.get("kind") for item in _kind_nodes(node)]
    return not kinds or "observed" in kinds


def shallow_limitation(payload: dict[str, Any]) -> str:
    missing = _missing(payload)
    order = {name: index for index, name in enumerate(payload)}
    present = [path for path in _COUNTED_PATHS if path.split(".")[0] in order]
    counted = [
        path
        for path in sorted(present, key=lambda path: order[path.split(".")[0]])
        if path not in missing and _counted(_at(payload, path))
    ]
    return (
        "The commit graph is truncated (shallow clone). "
        f"Reported as not_observed ({HISTORY_INCOMPLETE_REASON}): "
        f"{', '.join(missing) or 'none'}. "
        "Every other value in these blocks counts only the fetched commits: "
        f"{', '.join(counted)}."
    )
