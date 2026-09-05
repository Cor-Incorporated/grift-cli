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

CONTEXT_DEFINITION_VERSION = "context-v3-2026-08-25"

# `scale` counts every non-bot commit, merges included; `activity` counts only
# non-merge ones. Both blocks ship in the same report, and on a merge-heavy
# repository they differ by thousands (pytest: 16,962 vs 12,396), so the scale
# block states its denominator instead of relying on the field name to imply it.
# No measured value changes with this note, so CONTEXT_DEFINITION_VERSION holds
# — only the collaboration_class thresholds below are versioned behaviour.
SCALE_DENOMINATOR_NOTE = "human_commits includes merge commits and excludes bot commits"

# Shared with analyze.py's actor-side degradation so a report never carries two
# spellings of the same limit. Repo-scope metrics reached this guard late: the
# actor path has degraded on truncated history since v0.6.0, while
# context_profile kept reporting the visible slice as if it were the repository.
HISTORY_INCOMPLETE_REASON = "history_incomplete"

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


def _language_composition(commits: list[GitCommit]) -> dict[str, float]:
    """Touch shares (0-1, context-v3): the unit has been "touch-share" since
    context-v1 but the value emitted raw counts until v3 — aligned here (#50)."""
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
    return {
        name: round(count / total, 4)
        for name, count in counts.most_common()
        if count / total >= 0.01
    }


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


# Reasons a context value cannot be measured. Coercing either case to 0 and
# labelling it `observed` is what norms §1 forbids: on a partial clone that
# reported `test_file_ratio = 0` for pytest and `docs_share = 0` for curl,
# which carries 1,090 documentation files (R9).
_NO_PATHS = "commit_paths_unavailable"
_NO_POPULATION = "no_nonmerge_commits"


def _has_commit_paths(commits: list[GitCommit]) -> bool:
    """Same predicate as surface_profile, so the two cannot disagree."""
    return any(commit.files for commit in commits)


def _measured(value: Any, unit: str, reason: str) -> dict[str, Any]:
    """None means the value could not be computed, never that it is zero."""
    if value is None:
        return NotObserved(reason).to_dict()
    return Observed(value, unit).to_dict()


def _path_measured(
    paths_available: bool,
    compute: Any,
    commits: list[GitCommit],
    unit: str,
) -> dict[str, Any]:
    """Path-derived values are unmeasurable, not empty, when no paths exist."""
    if not paths_available:
        return NotObserved(_NO_PATHS).to_dict()
    return Observed(compute(commits), unit).to_dict()


def _test_docs_shares(commits: list[GitCommit]) -> tuple[float | None, float | None]:
    from tep_core.paths import is_doc_or_config_path, is_test_path

    pop = [c for c in commits if not c.is_merge and c.files]
    if not pop:
        return None, None
    test_touch = sum(1 for c in pop if any(is_test_path(f) for f in c.files))
    docs_touch = sum(1 for c in pop if any(is_doc_or_config_path(f) for f in c.files))
    return round(test_touch / len(pop), 4), round(docs_touch / len(pop), 4)


def _actor_turnover(commits: list[GitCommit]) -> dict[str, dict[str, int]]:
    """Per-year actor movement (context-v3): `joined` = first-seen year count,
    `last_active` = last-seen year count. The old key `left` was misleading —
    an actor whose latest commit is this year is NOT gone (#50)."""
    first_year: dict[str, str] = {}
    last_year: dict[str, str] = {}
    for commit in commits:
        key = _author_key(commit)
        year = commit.date[:4]
        if key not in first_year or year < first_year[key]:
            first_year[key] = year
        if key not in last_year or year > last_year[key]:
            last_year[key] = year
    joined: Counter[str] = Counter(first_year.values())
    last_active: Counter[str] = Counter(last_year.values())
    years = sorted(set(first_year.values()) | set(last_year.values()))
    return {
        year: {"joined": joined.get(year, 0), "last_active": last_active.get(year, 0)}
        for year in years
    }


def _release_cadence(tags: list[str], span_days: int) -> float | None:
    if span_days <= 0:
        return None
    per_year = len(tags) / (span_days / 365.25)
    return round(per_year, 2)


def build_context_profile(
    repo: Path,
    commits: list[GitCommit],
    origin: OriginResult,
    *,
    history_complete: bool = True,
) -> dict[str, Any]:
    """repo-scope context layer. Appears in report-v1 as an additive section.

    `history_complete=False` (a shallow or promisor clone) suppresses every
    depth-dependent field. On a `--depth 50` clone of urllib3 the visible
    history claimed 38 commits from 2026-05-07 by 17 authors; the repository
    actually holds 4,269 commits from 2009-12-10 by 433. Those are artifacts of
    the truncation, not measurements of the repository, and reporting them as
    `observed` states as fact something the tool cannot see (norms §1).
    """
    humans = _human_commits(commits, origin)
    if not humans:
        return NotObserved("no_human_commits").to_dict()

    def depth_dependent(observation: dict[str, Any]) -> dict[str, Any]:
        """Emit the measurement, or say the history was too short to make it."""
        if history_complete:
            return observation
        return NotObserved(HISTORY_INCOMPLETE_REASON).to_dict()

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
    paths_available = _has_commit_paths(humans)
    test_share, docs_share = _test_docs_shares(humans)
    conventional = _conventional_share(humans)
    issue_share = _issue_link_share(humans)
    profile: dict[str, Any] = {
        "kind": "observed",
        "definition_version": CONTEXT_DEFINITION_VERSION,
        "analysis_scope": "repo",
        "resolved_human_actors": depth_dependent(
            Observed(resolved_human_actors, "actors").to_dict()
        ),
        "top_actor_share": depth_dependent(Observed(top_share, "ratio").to_dict()),
        "collaboration_class": depth_dependent(Observed(collaboration_class, "class").to_dict()),
        "pr_flow_share": Observed(pr_flow_share, "ratio").to_dict(),
        "scale": {
            "kind": "observed",
            # This block counts merges; `activity` does not. Both populations
            # appear in one report, so each states its own denominator rather
            # than leaving the reader to infer it from the field name.
            "denominator_note": SCALE_DENOMINATOR_NOTE,
            "human_commits": depth_dependent(Observed(len(humans), "commits").to_dict()),
            "first_commit": depth_dependent(Observed(first_date, "date").to_dict()),
            # HEAD is real whatever the depth, so the recent end survives.
            "last_commit": Observed(last_date, "date").to_dict(),
            "active_span_days": depth_dependent(Observed(span_days, "days").to_dict()),
            "top_level_dirs": depth_dependent(Observed(_top_level_dirs(humans), "dirs").to_dict()),
            "tags": depth_dependent(Observed(len(tags), "tags").to_dict()),
        },
        "repo_age_days": depth_dependent(
            Observed(
                _days_between(first_date, head_date) if first_date and head_date else 0, "days"
            ).to_dict()
        ),
        "days_since_last_human_commit": Observed(days_since_last, "days").to_dict(),
        # A truncated clone can cover fewer than 180 days, so the window itself
        # is unproven and the stage derived from it with it.
        "active_days_180d": depth_dependent(Observed(active_days_180d, "days").to_dict()),
        "lifecycle_stage": depth_dependent(Observed(lifecycle_stage, "class").to_dict()),
        "actor_turnover": depth_dependent(
            Observed(_actor_turnover(humans), "actors/year").to_dict()
        ),
        "release_cadence": depth_dependent(
            Observed(_release_cadence(tags, span_days), "tags/year").to_dict()
        ),
        "conventional_commit_share": _measured(conventional, "ratio", _NO_POPULATION),
        "language_composition": _path_measured(
            paths_available, _language_composition, humans, "touch-share"
        ),
        "test_file_ratio": _measured(test_share, "ratio", _NO_PATHS),
        "docs_share": _measured(docs_share, "ratio", _NO_PATHS),
        "dependency_manifests": _path_measured(paths_available, _manifest_set, humans, "manifests"),
        "monorepo_markers": _path_measured(paths_available, _monorepo_markers, humans, "markers"),
    }
    profile["issue_link_density"] = _measured(issue_share, "ratio", _NO_POPULATION)
    return profile
