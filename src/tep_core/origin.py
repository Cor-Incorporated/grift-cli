"""Origin classifier (revised taxonomy: SO2 8-class + unresolved/bot + P0-d-2)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from tep_core.gitutil import GitCommit
from tep_core.identity import IdentityConfig
from tep_core.lineage import Lineage
from tep_core.observation import NotObserved, Observed

# Grift migration 000073 + 000075 vocabulary.
ORIGIN_CLASSES = (
    "inherited_upstream",
    "upstream_sync",
    "tenant_unique",
    "tenant_merge_or_sync",
    "tenant_derivative",
    "external_upstream_contribution",
    "template_inherited",
    "generated_or_vendor",
    "ambiguous_origin",
    "unresolved",
    "bot",
)

ALWAYS_OBSERVED = frozenset(
    {
        "tenant_unique",
        "inherited_upstream",
        "generated_or_vendor",
        "ambiguous_origin",
        "unresolved",
        "bot",
    }
)

BOT_EMAIL_RE = re.compile(
    r"\[bot\]@|^action@github\.com$|^github-actions|^dependabot|^renovate",
    re.I,
)

_VENDOR_PREFIXES = (
    "vendor/",
    "node_modules/",
    "third_party/",
    "third-party/",
)
_VENDOR_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".pb.go",
)


def is_bot_email(email: str) -> bool:
    return BOT_EMAIL_RE.search(email) is not None


def is_undecidable_email(email: str) -> bool:
    """True when origin cannot be attributed even with more identity config."""
    return not email.strip()


def is_vendor_path(path: str) -> bool:
    lowered = path.replace("\\", "/").lstrip("./")
    if any(lowered.startswith(prefix) for prefix in _VENDOR_PREFIXES):
        return True
    return any(lowered.endswith(suffix) for suffix in _VENDOR_SUFFIXES)


def is_vendor_only(commit: GitCommit) -> bool:
    if not commit.files:
        return False
    return all(is_vendor_path(path) for path in commit.files)


@dataclass
class OriginResult:
    counts: Counter[str] = field(default_factory=Counter)
    bot_commits: int = 0
    tenant_dates: list[str] = field(default_factory=list)
    tenant_day_counts: Counter[str] = field(default_factory=Counter)
    classes_by_sha: dict[str, str] = field(default_factory=dict)

    def origin_observations(
        self,
        *,
        template_provided: bool,
        parent_repo_provided: bool,
        has_upstream_lineage: bool,
    ) -> dict[str, dict[str, object]]:
        payload: dict[str, dict[str, object]] = {}
        for name in ORIGIN_CLASSES:
            if name == "upstream_sync" and not has_upstream_lineage:
                payload[name] = NotObserved("no_upstream_lineage").to_dict()
            elif name == "tenant_merge_or_sync" and has_upstream_lineage:
                payload[name] = NotObserved("lineage_present").to_dict()
            elif name in ALWAYS_OBSERVED or name in {
                "upstream_sync",
                "tenant_merge_or_sync",
            }:
                payload[name] = Observed(self.counts[name], "commits").to_dict()
            elif name == "template_inherited" and not template_provided:
                payload[name] = NotObserved("template_not_provided").to_dict()
            elif (
                name
                in {
                    "tenant_derivative",
                    "external_upstream_contribution",
                }
                and not parent_repo_provided
            ):
                payload[name] = NotObserved("parent_repo_not_provided").to_dict()
            else:
                payload[name] = Observed(self.counts[name], "commits").to_dict()
        return payload


def classify_commits(
    commits: list[GitCommit],
    identity: IdentityConfig,
    lineage: Lineage,
) -> OriginResult:
    result = OriginResult()
    has_lineage = lineage.has_upstream_lineage

    for commit in commits:
        email = commit.author_email
        actor = identity.actor_for_email(email)
        if is_bot_email(email) or (actor is not None and actor.attribution_state == "bot"):
            result.bot_commits += 1
            result.counts["bot"] += 1
            result.classes_by_sha[commit.sha] = "bot"
            continue
        if is_vendor_only(commit):
            result.counts["generated_or_vendor"] += 1
            result.classes_by_sha[commit.sha] = "generated_or_vendor"
            continue
        tenant = identity.is_tenant_email(email)
        if tenant:
            if commit.is_merge:
                klass = "upstream_sync" if has_lineage else "tenant_merge_or_sync"
            else:
                klass = "tenant_unique"
                result.tenant_dates.append(commit.date)
                result.tenant_day_counts[commit.date] += 1
        elif has_lineage:
            klass = "inherited_upstream"
        elif is_undecidable_email(email):
            klass = "ambiguous_origin"
        else:
            klass = "unresolved"
        result.counts[klass] += 1
        result.classes_by_sha[commit.sha] = klass
    return result
