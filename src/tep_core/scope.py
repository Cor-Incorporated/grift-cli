"""Analysis population scopes used by report-v2 internals.

``actor_cluster`` is deliberately distinct from ``tenant``: it represents one
repo-local Git primary-author cluster without asserting consent or personhood.
"""

from __future__ import annotations

from tep_core.gitutil import GitCommit
from tep_core.origin import OriginResult

SCOPES = ("tenant", "repo", "actor_cluster")
DEFAULT_SCOPE = "tenant"
TENANT_ORIGIN = frozenset({"tenant_unique"})


class ScopeMismatchError(ValueError):
    """Comparing values computed under different analysis scopes is forbidden."""


def require_same_scope(left: str, right: str) -> None:
    if left != right:
        raise ScopeMismatchError(
            f"scope mismatch: {left!r} vs {right!r} — reference lookup is same-scope only"
        )


def population_shas(
    commits: list[GitCommit],
    origin: OriginResult,
    scope: str,
) -> set[str]:
    """SHAs eligible for co-change/rework. Merge and bot are always excluded."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope: {scope}")
    if scope == "tenant":
        return {sha for sha, klass in origin.classes_by_sha.items() if klass in TENANT_ORIGIN}
    if scope == "actor_cluster":
        return {
            commit.sha
            for commit in commits
            if commit.sha in origin.actor_cluster_shas
            and origin.classes_by_sha.get(commit.sha) != "bot"
            and not commit.is_merge
        }
    return {
        commit.sha
        for commit in commits
        if origin.classes_by_sha.get(commit.sha) != "bot" and not commit.is_merge
    }
