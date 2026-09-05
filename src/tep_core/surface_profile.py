"""Surface aggregations for report-v2. Path lists are never emitted."""

from __future__ import annotations

from collections import Counter
from typing import Any

from tep_core.gitutil import GitCommit
from tep_core.observation import NotObserved, Observed
from tep_core.path_surface import CLASSIFICATION_BASIS, classify_surface, surface_flags
from tep_core.v2_constants import MIN_POPULATION_FOR_RATES, SURFACE_LIMITATION, SURFACES
from tep_core.version import SURFACE_DEFINITION_VERSION


def _top_module(path: str) -> str | None:
    parts = path.replace("\\", "/").lstrip("./").split("/")
    if not parts or parts[0] in {".", ""}:
        return None
    if len(parts) == 1:
        return None
    return parts[0]


def _pair_key(left: str, right: str) -> str:
    first, second = sorted((left, right))
    return f"{first}+{second}"


def surface_profile(commits: list[GitCommit], *, empty_reason: str) -> dict[str, Any]:
    if not commits:
        payload = NotObserved(empty_reason).to_dict()
        payload["definition_version"] = SURFACE_DEFINITION_VERSION
        payload["classification_basis"] = CLASSIFICATION_BASIS
        payload["limitations"] = [SURFACE_LIMITATION]
        return payload
    if not any(commit.files for commit in commits):
        payload = NotObserved("commit_paths_unavailable").to_dict()
        payload["definition_version"] = SURFACE_DEFINITION_VERSION
        payload["classification_basis"] = CLASSIFICATION_BASIS
        payload["limitations"] = [SURFACE_LIMITATION]
        return payload

    counts: Counter[str] = Counter()
    file_events: Counter[str] = Counter()
    unique_files: dict[str, set[str]] = {name: set() for name in SURFACES}
    line_counts: Counter[str] = Counter()
    pairs: Counter[str] = Counter()
    modules: Counter[str] = Counter()
    unclassified = 0
    ambiguous = 0
    touched = 0
    has_numstat = any(commit.numstat for commit in commits)
    for commit in commits:
        if not commit.files:
            continue
        per_path = {path: added + deleted for path, added, deleted in commit.numstat}
        surfaces: set[str] = set()
        for path in commit.files:
            surface, is_ambiguous, is_unclassified = surface_flags(path)
            surfaces.add(surface)
            file_events[surface] += 1
            unique_files[surface].add(path)
            if path in per_path:
                line_counts[surface] += per_path[path]
            if is_unclassified:
                unclassified += 1
            if is_ambiguous:
                ambiguous += 1
            module = _top_module(path)
            if module:
                modules[module] += 1
        if not surfaces:
            continue
        touched += 1
        for surface in surfaces:
            counts[surface] += 1
        named = sorted(surfaces)
        for index, left in enumerate(named):
            for right in named[index + 1 :]:
                pairs[_pair_key(left, right)] += 1
    unique_values = {name: len(unique_files[name]) for name in SURFACES}
    unique_total = sum(unique_values.values())

    denominator = touched
    share_block: dict[str, Any]
    if denominator < MIN_POPULATION_FOR_RATES:
        share_block = NotObserved("insufficient_population").to_dict()
        share_block["population"] = denominator
    else:
        share_block = {
            "kind": "observed",
            "unit": "ratio",
            "sample_size": denominator,
            "values": {
                name: round(counts[name] / denominator, 4) if denominator else 0.0
                for name in SURFACES
            },
        }

    top_share: dict[str, Any]
    if not modules or denominator < MIN_POPULATION_FOR_RATES:
        top_share = NotObserved(
            "insufficient_population" if denominator < MIN_POPULATION_FOR_RATES else "no_modules"
        ).to_dict()
    else:
        top_count = modules.most_common(1)[0][1]
        top_share = Observed(
            round(top_count / sum(modules.values()), 4),
            "ratio",
            sample_size=sum(modules.values()),
        ).to_dict()

    if "values" in share_block:
        share_block["denominator_definition"] = (
            "non-merge human commits that touched at least one path"
        )
        share_block["population"] = denominator
    return {
        "kind": "observed",
        "unit": "profile",
        "definition_version": SURFACE_DEFINITION_VERSION,
        "sample_size": len(commits),
        "classification_basis": CLASSIFICATION_BASIS,
        "denominator_definition": "non-merge human commits that touched at least one path",
        "population": denominator,
        "unclassified_count": unclassified,
        "ambiguous_count": ambiguous,
        "surface_commit_counts": {
            "kind": "observed",
            "unit": "commits",
            "values": {name: int(counts[name]) for name in SURFACES},
            "definition_version": SURFACE_DEFINITION_VERSION,
        },
        "surface_commit_share": share_block,
        "surface_file_counts": {
            "kind": "observed",
            "unit": "file-changes",
            "values": {name: int(file_events[name]) for name in SURFACES},
            "sample_size": int(sum(file_events.values())),
            "denominator_definition": "path occurrences in non-merge human commits",
        },
        "surface_unique_file_counts": {
            "kind": "observed",
            "unit": "files",
            "values": unique_values,
            "sample_size": unique_total,
            "denominator_definition": "distinct paths in the scoped commits",
        },
        "surface_file_share": _file_share(unique_values, unique_total),
        "cross_surface_cochange": {
            "kind": "observed",
            "unit": "commit-pairs",
            "values": dict(sorted(pairs.items())),
        },
        "module_breadth": Observed(len(modules), "modules", sample_size=len(commits)).to_dict(),
        "top_module_share": top_share,
        "surface_line_counts": _line_block(line_counts, has_numstat),
        "limitations": [SURFACE_LIMITATION],
    }


def _file_share(unique_values: dict[str, int], unique_total: int) -> dict[str, Any]:
    if unique_total < MIN_POPULATION_FOR_RATES:
        payload = NotObserved("insufficient_population").to_dict()
        payload["population"] = unique_total
        payload["unit"] = "ratio"
        return payload
    return {
        "kind": "observed",
        "unit": "ratio",
        "sample_size": unique_total,
        "population": unique_total,
        "denominator_definition": "distinct paths in the scoped commits",
        "values": {
            name: round(unique_values[name] / unique_total, 4) if unique_total else 0.0
            for name in SURFACES
        },
    }


def _line_block(line_counts: Counter[str], has_numstat: bool) -> dict[str, Any]:
    if not has_numstat:
        return {
            "kind": "not_observed",
            "reason": "numstat_unavailable",
            "unit": "lines",
            "limitations": ["Changed lines are omitted unless git numstat is available. Not zero."],
        }
    return {
        "kind": "observed",
        "unit": "lines",
        "values": {name: int(line_counts[name]) for name in SURFACES},
        "denominator_definition": "added plus deleted lines from git numstat",
        "sample_size": int(sum(line_counts.values())),
    }


def classify_path(path: str) -> str:
    return classify_surface(path)
