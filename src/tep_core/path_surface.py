"""Deterministic path→surface classification. Does not change split_paths()."""

from __future__ import annotations

import re

from tep_core.origin import is_vendor_path
from tep_core.paths import TEST_PATH_RE
from tep_core.v2_constants import SURFACES

CLASSIFICATION_BASIS = "path_pattern_and_extension_heuristic"

_DOCS_RE = re.compile(
    r"(^|/)(docs|documentation)(/|$)"
    r"|\.(md|rst|adoc)$"
    r"|(^|/)(LICENSE|CHANGELOG|CONTRIBUTING)(\.|$)",
    re.I,
)
_CI_RE = re.compile(
    r"(^|/)\.github/workflows/"
    r"|(^|/)\.gitlab-ci"
    r"|(^|/)Jenkinsfile$"
    r"|(^|/)(ci|pipeline)(/|$)",
    re.I,
)
_PLATFORM_RE = re.compile(
    r"(^|/)(terraform|helm|k8s|kubernetes|docker)(/|$)"
    r"|(^|/)Dockerfile$"
    r"|\.tf$",
    re.I,
)
_DATA_RE = re.compile(r"(^|/)(migrations|schema|seed)(/|$)|\.sql$", re.I)
_OBS_RE = re.compile(r"(^|/)(monitoring|metrics|tracing|dashboard|logging)(/|$)", re.I)
_FRONT_RE = re.compile(
    r"(^|/)(components|pages|ui)(/|$)"
    r"|\.(tsx|jsx|vue|svelte|astro)$",
    re.I,
)
_BACK_RE = re.compile(
    r"(^|/)(api|routes|controllers|services|workers)(/|$)"
    r"|\.(py|go|rs|java|kt|rb|php|cs|scala|c|h|cpp|hpp|swift)$",
    re.I,
)
_CONFIG_RE = re.compile(
    r"\.(ya?ml|toml|json|ini|cfg|conf)$"
    r"|(^|/)(package\.json|pyproject\.toml|Cargo\.toml|go\.mod|Gemfile|"
    r"pom\.xml|composer\.json|Makefile)$",
    re.I,
)

_MATCHERS: tuple[tuple[str, re.Pattern[str] | None], ...] = (
    ("test", None),
    ("docs", _DOCS_RE),
    ("ci_cd", _CI_RE),
    ("platform", _PLATFORM_RE),
    ("data", _DATA_RE),
    ("observability", _OBS_RE),
    ("frontend", _FRONT_RE),
    ("backend", _BACK_RE),
    ("config", _CONFIG_RE),
    ("generated_vendor", None),
)


def _norm(path: str) -> str:
    # Do not strip leading '.' — `.github` would become `github`.
    return path.replace("\\", "/").lstrip("/")


def matching_surfaces(path: str) -> tuple[str, ...]:
    lowered = _norm(path)
    hits: list[str] = []
    for name, pattern in _MATCHERS:
        if name == "test" and TEST_PATH_RE.search(lowered):
            hits.append(name)
        elif name == "generated_vendor" and is_vendor_path(lowered):
            hits.append(name)
        elif pattern is not None and pattern.search(lowered):
            hits.append(name)
    return tuple(hits)


def classify_surface(path: str) -> str:
    hits = matching_surfaces(path)
    if not hits:
        return "other"
    for surface in SURFACES:
        if surface in hits:
            return surface
    return "other"


def surface_flags(path: str) -> tuple[str, bool, bool]:
    """Return (surface, ambiguous, unclassified)."""
    hits = matching_surfaces(path)
    if not hits:
        return "other", False, True
    chosen = classify_surface(path)
    return chosen, len(hits) > 1, False
