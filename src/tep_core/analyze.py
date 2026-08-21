"""Assemble a provenance-bearing TEP report."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tep_core.activity import activity_metrics
from tep_core.cochange import test_cochange
from tep_core.core_period import compute_core_activity_period
from tep_core.gitutil import GitError, read_commits, repository_identity, rev_parse
from tep_core.identity import IdentityConfig
from tep_core.lineage import Lineage
from tep_core.observation import Observed
from tep_core.origin import classify_commits
from tep_core.reference import interpret_metric
from tep_core.rework import rework_metrics
from tep_core.scope import DEFAULT_SCOPE
from tep_core.survival import survival_metrics
from tep_core.tests_observed import observe_test_frameworks
from tep_core.version import (
    ACTIVITY_DEFINITION_VERSION,
    DEFINITION_VERSION,
    ORIGIN_DEFINITION_VERSION,
    __version__,
)


def analyze_repository(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    template_provided: bool = False,
    parent_repo_provided: bool = False,
    include_files: bool = False,
    include_local_path: bool = False,
    survival: bool = False,
    scope: str = DEFAULT_SCOPE,
) -> dict[str, Any]:
    repo = repo.resolve()
    commits = read_commits(repo, include_files=False)
    if include_files:
        try:
            named = read_commits(repo, include_files=True)
            files_by_sha = {item.sha: item.files for item in named}
            for commit in commits:
                commit.files = files_by_sha.get(commit.sha, ())
        except GitError:
            pass
    origin = classify_commits(commits, identity, lineage)
    tests = observe_test_frameworks(repo)
    tests_observed = tests.get("kind") == "observed"
    need_paths = include_files or scope == "repo" or origin.counts["tenant_unique"] > 0
    if not include_files and need_paths:
        try:
            named = read_commits(repo, include_files=True)
            files_by_sha = {item.sha: item.files for item in named}
            for commit in commits:
                commit.files = files_by_sha.get(commit.sha, ())
        except GitError:
            pass
    head_sha = rev_parse(repo)
    head_date = commits[0].date if commits else None
    activity = activity_metrics(origin.tenant_dates, origin.tenant_day_counts, head_date=head_date)
    cochange = test_cochange(
        commits,
        origin,
        tests_observed=tests_observed,
        pending_attribution=identity.pending_attribution,
        head_date=head_date,
        scope=scope,
    )
    rework = rework_metrics(
        commits,
        origin,
        pending_attribution=identity.pending_attribution,
        scope=scope,
    )
    corr = rework.get("corrective_rework_rate") if rework.get("kind") == "observed" else rework
    return {
        "schema_version": "tep-report-v1",
        "provenance": {
            "tool_name": "grift",
            "method_name": "TEP",
            "tool_version": __version__,
            "definition_version": DEFINITION_VERSION,
            "origin_definition_version": ORIGIN_DEFINITION_VERSION,
            "activity_definition_version": ACTIVITY_DEFINITION_VERSION,
            "analysis_scope": scope,
            "analyzed_commit_sha": head_sha,
            "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "repository": repository_identity(repo, include_local_path=include_local_path),
        "identity": {
            "pending_attribution": identity.pending_attribution,
            "actor_count": identity.actor_count,
        },
        "lineage": lineage.to_dict(),
        "origin": origin.origin_observations(
            template_provided=template_provided,
            parent_repo_provided=parent_repo_provided,
            has_upstream_lineage=lineage.has_upstream_lineage,
        ),
        "attribution": {
            "bot": Observed(origin.bot_commits, "commits").to_dict(),
        },
        "activity": activity,
        "core_activity_period": compute_core_activity_period(origin.tenant_dates),
        "test_frameworks": tests,
        "test_cochange": cochange,
        "rework": rework,
        "survival": survival_metrics(repo, enabled=survival),
        "interpretation": {
            "test_cochange": interpret_metric(
                report_scope=scope, metric_id="test_cochange", observation=cochange
            ),
            "corrective_rework": interpret_metric(
                report_scope=scope, metric_id="corrective_rework", observation=corr
            ),
        },
    }
