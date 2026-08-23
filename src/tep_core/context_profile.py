"""Context Profile v2 (repo-scope observation layer).

Ruling: BD tep-context-profile-ruling-20260822 §4-§5 + INSTRUCTION-p1f-v2 §2.
All values are observations (kind/unit/definition-versioned). No grade
vocabulary, no implication of quality. Collaboration class thresholds live
in the definition version — changing them bumps CONTEXT_DEFINITION_VERSION.

`resolved_human_actors` counts bot-excluded, upstream-lineage-excluded
unique normalized authors. Raw shortlog-style counts stay forbidden in
narratives (ruling §5) — output is counts and ratios only, never names.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from tep_core.gitutil import GitCommit, _run_git
from tep_core.observation import NotObserved, Observed
from tep_core.origin import OriginResult

CONTEXT_DEFINITION_VERSION = "context-v2-2026-08-23"

# collaboration_class thresholds (part of the definition version):
#   solo          top_actor_share >= 0.90
#   small_team    resolved_human_actors <= 5
#   community     otherwise
SOLO_TOP_SHARE = 0.90
SMALL_TEAM_MAX_ACTORS = 5

# lifecycle-v2 (density-based; addendum16 §2). Primary outputs are the two
# raw observations — days_since_last_human_commit and active_days_180d —
# and the class band is a convenience always printed alongside them.
# Bands: dormant = active_days_180d <= 2 / maintained = 3..11 / active = >= 12.
# These thresholds were designed FROM pilot round 1 observations
# (informed-by-pilot-1); they were not "verified" on the same sample, and
# validity will be checked on future samples (pilot round 2). Limits: bulk
# housekeeping can inflate recency (hence the density basis); work mode
# (development vs maintenance) is not measured — the class is activity
# density only.
LIFECYCLE_ACTIVE_MIN_DAYS_180D = 12
LIFECYCLE_MAINTAINED_MIN_DAYS_180D = 3
DENSITY_WINDOW_DAYS = 180

# lifecycle_stage (last-activity + cadence; thresholds in definition version):
#   active     last commit within 90 days of HEAD
#   maintained last commit within 365 days
#   dormant    otherwise
# legacy recency windows kept for reference only (superseded by lifecycle-v2
# density bands above); do not use in new code.
ACTIVE_WINDOW_DAYS = 90
MAINTAINED_WINDOW_DAYS = 365

# conventional-commit-ish subject: type(scope)?: / type:
_CONVENTIONAL_RE = re.compile(r"^[A-Za-z]+(\([^)]+\))?!?:\s")

# language composition: extension buckets over changed files (creation-weighted
# is v0.6 territory; here we count per-commit path touches).
_LANGUAGE_EXTENSIONS = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".swift",
    ".scala",
    ".sh",
    ".vue",
    ".svelte",
    ".astro",
    ".lua",
    ".r",
    ".m",
)
_DEPENDENCY_MANIFESTS = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "mix.exs",
    "deno.json",
)
_MONOREPO_MARKERS = (
    "packages/",
    "apps/",
    "services/",
    "libs/",
    "modules/",
    "workspace",
    "nx.json",
    "lerna.json",
    "turbo.json",
    "pnpm-workspace.yaml",
    "cargo-workspace",
    "go.work",
)


def _author_key(commit: GitCommit) -> str:
    return commit.author_email.lower().strip()


def _human_commits(commits: list[GitCommit], origin: OriginResult) -> list[GitCommit]:
    """Non-bot commits excluding upstream-inherited work (ruling §5).

    upstream_sync/inherited_upstream are excluded so a push-copy fork never
    counts upstream authors in resolved_human_actors (2026-08 fork incident).
    """
    excluded = {"bot", "upstream_sync", "inherited_upstream"}
    return [c for c in commits if origin.classes_by_sha.get(c.sha) not in excluded]


def _tags(repo: Path) -> list[str]:
    try:
        out = _run_git(repo, ["tag", "--sort=-creatordate"])
    except Exception:  # noqa: BLE001 — tags are optional context
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_dates(commits: list[GitCommit]) -> tuple[str | None, str | None]:
    if not commits:
        return None, None
    dates = sorted(c.date for c in commits)
    return dates[0], dates[-1]


def _days_between(first: str, last: str) -> int:
    from datetime import date

    def parse(value: str) -> date:
        year, month, day = (int(part) for part in value.split("-"))
        return date(year, month, day)

    return (parse(last) - parse(first)).days


def _active_days_in_window(commits: list[GitCommit], head_date: str | None) -> int:
    """Unique human-commit days within the trailing DENSITY_WINDOW (lifecycle-v2).

    Density, not recency: a single recent housekeeping day after 180 days of
    silence must NOT flip a dormant repo to active (falsifiable fixture in
    tests)."""
    if head_date is None:
        return 0
    from datetime import date, timedelta

    def parse(value: str) -> date:
        year, month, day = (int(part) for part in value.split("-"))
        return date(year, month, day)

    cut = parse(head_date) - timedelta(days=DENSITY_WINDOW_DAYS)
    days = {parse(c.date) for c in commits if parse(c.date) >= cut}
    return len(days)


def _top_level_dirs(commits: list[GitCommit]) -> list[str]:
    dirs: Counter[str] = Counter()
    for commit in commits:
        for path in commit.files:
            parts = path.replace("\\", "/").split("/")
            if len(parts) > 1:
                dirs[parts[0]] += 1
    return [name for name, _count in dirs.most_common(5)]


def _language_composition(commits: list[GitCommit]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    total = 0
    for commit in commits:
        for path in commit.files:
            lowered = path.lower()
            for ext in _LANGUAGE_EXTENSIONS:
                if lowered.endswith(ext):
                    counts[ext.lstrip(".")] += 1
                    total += 1
                    break
    if total == 0:
        return {}
    return {name: count for name, count in counts.most_common() if count / total >= 0.01}


def _manifest_set(commits: list[GitCommit]) -> list[str]:
    found: set[str] = set()
    for commit in commits:
        for path in commit.files:
            name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if name in _DEPENDENCY_MANIFESTS:
                found.add(name)
    return sorted(found)


def _monorepo_markers(commits: list[GitCommit]) -> list[str]:
    found: set[str] = set()
    for commit in commits:
        joined = " ".join(commit.files)
        lowered = joined.lower()
        for marker in _MONOREPO_MARKERS:
            if marker in lowered:
                found.add(marker.rstrip("/"))
    return sorted(found)


def _issue_link_share(commits: list[GitCommit]) -> float | None:
    pop = [c for c in commits if not c.is_merge]
    if not pop:
        return None
    linked = sum(1 for c in pop if re.search(r"(#\d+|fixes\s+#|close[sd]?\s+#)", c.subject, re.I))
    return round(linked / len(pop), 4)


def _conventional_share(commits: list[GitCommit]) -> float | None:
    pop = [c for c in commits if not c.is_merge]
    if not pop:
        return None
    matched = sum(1 for c in pop if _CONVENTIONAL_RE.match(c.subject))
    return round(matched / len(pop), 4)


def _test_docs_shares(commits: list[GitCommit]) -> tuple[float | None, float | None]:
    from tep_core.paths import is_doc_or_config_path, is_test_path

    pop = [c for c in commits if not c.is_merge and c.files]
    if not pop:
        return None, None
    test_touch = sum(1 for c in pop if any(is_test_path(f) for f in c.files))
    docs_touch = sum(1 for c in pop if any(is_doc_or_config_path(f) for f in c.files))
    return round(test_touch / len(pop), 4), round(docs_touch / len(pop), 4)


def _actor_turnover(commits: list[GitCommit]) -> dict[str, dict[str, int]]:
    first_year: dict[str, int] = {}
    last_year: dict[str, int] = {}
    for commit in commits:
        key = _author_key(commit)
        year = commit.date[:4]
        if key not in first_year or year < first_year[key]:
            first_year[key] = year
        if key not in last_year or year > last_year[key]:
            last_year[key] = year
    joined: Counter[str] = Counter(first_year.values())
    left: Counter[str] = Counter(last_year.values())
    years = sorted(set(first_year.values()) | set(last_year.values()))
    return {year: {"joined": joined.get(year, 0), "left": left.get(year, 0)} for year in years}


def _release_cadence(tags: list[str], span_days: int) -> float | None:
    if span_days <= 0:
        return None
    per_year = len(tags) / (span_days / 365.25)
    return round(per_year, 2)


def build_context_profile(
    repo: Path,
    commits: list[GitCommit],
    origin: OriginResult,
) -> dict[str, Any]:
    """repo-scope context layer. Appears in report-v1 as an additive section."""
    humans = _human_commits(commits, origin)
    if not humans:
        return NotObserved("no_human_commits").to_dict()

    author_counts: Counter[str] = Counter(_author_key(c) for c in humans)
    resolved_human_actors = len(author_counts)
    top_share = round(author_counts.most_common(1)[0][1] / len(humans), 4)

    if top_share >= SOLO_TOP_SHARE:
        collaboration_class = "solo"
    elif resolved_human_actors <= SMALL_TEAM_MAX_ACTORS:
        collaboration_class = "small_team"
    else:
        collaboration_class = "community"

    merges = sum(1 for c in humans if c.is_merge)
    pr_flow_share = round(merges / len(humans), 4)

    first_date, last_date = _commit_dates(humans)
    span_days = _days_between(first_date, last_date) if first_date and last_date else 0
    head_date = commits[0].date if commits else None
    # lifecycle-v2 primary observations (density-based, addendum16 §2)
    days_since_last = _days_between(last_date, head_date) if last_date and head_date else None
    active_days_180d = _active_days_in_window(humans, head_date)
    if active_days_180d >= LIFECYCLE_ACTIVE_MIN_DAYS_180D:
        lifecycle_stage = "active"
    elif active_days_180d >= LIFECYCLE_MAINTAINED_MIN_DAYS_180D:
        lifecycle_stage = "maintained"
    else:
        lifecycle_stage = "dormant"

    tags = _tags(repo)
    test_share, docs_share = _test_docs_shares(humans)
    conventional = _conventional_share(humans)
    issue_share = _issue_link_share(humans)
    profile: dict[str, Any] = {
        "kind": "observed",
        "definition_version": CONTEXT_DEFINITION_VERSION,
        "analysis_scope": "repo",
        "resolved_human_actors": Observed(resolved_human_actors, "actors").to_dict(),
        "top_actor_share": Observed(top_share, "ratio").to_dict(),
        "collaboration_class": Observed(collaboration_class, "class").to_dict(),
        "pr_flow_share": Observed(pr_flow_share, "ratio").to_dict(),
        "scale": {
            "kind": "observed",
            "human_commits": Observed(len(humans), "commits").to_dict(),
            "first_commit": Observed(first_date, "date").to_dict(),
            "last_commit": Observed(last_date, "date").to_dict(),
            "active_span_days": Observed(span_days, "days").to_dict(),
            "top_level_dirs": Observed(_top_level_dirs(humans), "dirs").to_dict(),
            "tags": Observed(len(tags), "tags").to_dict(),
        },
        "repo_age_days": Observed(
            _days_between(first_date, head_date) if first_date and head_date else 0, "days"
        ).to_dict(),
        "days_since_last_human_commit": Observed(days_since_last, "days").to_dict(),
        "active_days_180d": Observed(active_days_180d, "days").to_dict(),
        "lifecycle_stage": Observed(lifecycle_stage, "class").to_dict(),
        "actor_turnover": Observed(_actor_turnover(humans), "actors/year").to_dict(),
        "release_cadence": Observed(_release_cadence(tags, span_days), "releases/year").to_dict(),
        "conventional_commit_share": Observed(
            conventional if conventional is not None else 0, "ratio"
        ).to_dict(),
        "language_composition": Observed(_language_composition(humans), "touch-share").to_dict(),
        "test_file_ratio": Observed(test_share if test_share is not None else 0, "ratio").to_dict(),
        "docs_share": Observed(docs_share if docs_share is not None else 0, "ratio").to_dict(),
        "dependency_manifests": Observed(_manifest_set(humans), "manifests").to_dict(),
        "monorepo_markers": Observed(_monorepo_markers(humans), "markers").to_dict(),
    }
    issue_share_val = issue_share if issue_share is not None else 0
    profile["issue_link_density"] = Observed(issue_share_val, "ratio").to_dict()
    return profile
