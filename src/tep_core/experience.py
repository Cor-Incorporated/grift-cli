"""Pure, consent-gated experience observations for one declared actor.

This module intentionally does not read a repository or infer a person.  A
caller supplies normalized commit/change events, the repo-local actor id and
an explicit :class:`TenantConsent`.  That keeps Git collection, identity
resolution and the observational definitions independently testable.

File history uses rename detection at Git's ``-M50%`` boundary:

* ``R`` inherits the original file creator;
* ``C`` and ``A`` start a new creation (including a delete/re-add);
* ``D`` ends the active incarnation and is never adoption;
* merge diffs update lineage only and never count as actor metric events.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from statistics import median
from typing import Iterable, Mapping, Sequence

from tep_core.identity import email_identity_sha256, normalize_email
from tep_core.paths import is_prod_path
from tep_core.rework import is_corrective_subject

EXPERIENCE_DEFINITION_VERSION = "experience-v1"
DEFAULT_MIN_POPULATION = 20
ADOPTION_DAYS = 30
RETURN_DAYS = 180
POST_RELEASE_DAYS = 30

_CHANGE_STATUSES = frozenset({"A", "M", "D", "R", "C"})
_AI_TRAILERS = frozenset({"ai-assisted-by", "ai-generated-by", "agent-lane"})
_TRAILER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):\s*(.*?)\s*$")
_COAUTHOR_EMAIL_RE = re.compile(r"<([^<>]+)>\s*$")

_DEPENDENCY_BASENAMES = frozenset(
    {
        "cargo.lock",
        "cargo.toml",
        "composer.json",
        "composer.lock",
        "gemfile",
        "gemfile.lock",
        "go.mod",
        "go.sum",
        "package-lock.json",
        "package.json",
        "pipfile",
        "pipfile.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "uv.lock",
        "yarn.lock",
    }
)
_DOC_BASENAMES = frozenset({"readme", "changelog", "changes", "contributing", "license"})
_DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".adoc", ".txt"})
_CORE_PREFIXES = frozenset({"app", "cmd", "crates", "lib", "pkg", "src"})
_CORE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".ex",
        ".exs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".swift",
        ".ts",
        ".tsx",
        ".vue",
    }
)
_INFRA_PREFIXES = frozenset(
    {".github", ".gitlab", "ci", "deploy", "docker", "helm", "infra", "k8s", "terraform"}
)
_INFRA_BASENAMES = frozenset(
    {
        ".gitlab-ci.yml",
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
        "dockerfile",
        "makefile",
    }
)
_LANGUAGE_SUFFIXES = {
    ".c": "c_cpp",
    ".cc": "c_cpp",
    ".cpp": "c_cpp",
    ".h": "c_cpp",
    ".hpp": "c_cpp",
    ".cs": "csharp",
    ".css": "css",
    ".ex": "elixir",
    ".exs": "elixir",
    ".go": "go",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "configuration",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rst": "documentation",
    ".rs": "rust",
    ".scala": "scala",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".toml": "configuration",
    ".vue": "vue",
    ".yaml": "configuration",
    ".yml": "configuration",
    ".md": "markdown",
    ".mdx": "markdown",
}

__all__ = [
    "ADOPTION_DAYS",
    "DEFAULT_MIN_POPULATION",
    "EXPERIENCE_DEFINITION_VERSION",
    "ExperienceCommit",
    "ExperienceInputError",
    "FileChange",
    "POST_RELEASE_DAYS",
    "RETURN_DAYS",
    "ReleaseTag",
    "TenantConsent",
    "build_experience",
    "classify_domain",
    "classify_language",
    "is_dependency_path",
    "is_production_path",
    "is_test_path",
    "ordered_commits",
    "trailer_observations",
]


class ExperienceInputError(ValueError):
    """Raised when normalized experience events are internally inconsistent."""


@dataclass(frozen=True)
class FileChange:
    """One normalized file change.

    ``path`` is the destination for R/C and the affected path otherwise.
    ``old_path`` is mandatory for R/C.  An R similarity below 50 is rejected:
    the collector must represent that Git result as D+A instead.
    """

    status: str
    path: str
    old_path: str | None = None
    similarity: int | None = None

    def __post_init__(self) -> None:
        status = self.status.upper()
        object.__setattr__(self, "status", status)
        if status not in _CHANGE_STATUSES:
            raise ExperienceInputError(f"unknown file change status: {self.status!r}")
        path = _normalize_path(self.path)
        object.__setattr__(self, "path", path)
        if status in {"R", "C"}:
            if self.old_path is None:
                raise ExperienceInputError(f"{status} change requires old_path")
            object.__setattr__(self, "old_path", _normalize_path(self.old_path))
        elif self.old_path is not None:
            raise ExperienceInputError(f"{status} change must not carry old_path")
        if self.similarity is not None and not 0 <= self.similarity <= 100:
            raise ExperienceInputError("similarity must be between 0 and 100")
        if status == "R" and self.similarity is not None and self.similarity < 50:
            raise ExperienceInputError("R similarity below 50 must be represented as D+A")


@dataclass(frozen=True)
class ExperienceCommit:
    """Provider-neutral commit event consumed by experience/role metrics."""

    oid: str
    actor_id: str | None
    authored_at: datetime | str
    message: str
    changes: tuple[FileChange, ...] = ()
    parents: tuple[str, ...] = ()
    is_bot: bool = False
    sequence: int | None = None
    repository_commit_count_after: int | None = None
    repository_file_count_after: int | None = None
    repository_line_count_after: int | None = None

    def __post_init__(self) -> None:
        if self.sequence is not None and self.sequence < 0:
            raise ExperienceInputError("commit sequence must be non-negative")
        for name in (
            "repository_commit_count_after",
            "repository_file_count_after",
            "repository_line_count_after",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ExperienceInputError(f"{name} must be non-negative")

    @property
    def subject(self) -> str:
        return self.message.splitlines()[0] if self.message else ""

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


@dataclass(frozen=True)
class ReleaseTag:
    """A reachable release tag normalized by the collection layer."""

    name: str
    target_oid: str
    tagged_at: datetime | str
    annotated: bool = True
    tagger_actor_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.target_oid.strip():
            raise ExperienceInputError("release tag name and target_oid must not be empty")
        as_utc(self.tagged_at)


@dataclass(frozen=True)
class TenantConsent:
    """Explicit authorization to compute one tenant actor's observations."""

    actor_id: str
    basis: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ExperienceInputError("consent actor_id must not be empty")
        if not self.basis.strip():
            raise ExperienceInputError("consent basis must not be empty")


@dataclass(frozen=True)
class _FileIncarnation:
    creation_id: str
    creator_actor_id: str | None
    creator_is_bot: bool
    created_at: datetime
    last_target_touch: datetime | None


@dataclass
class _LineageSnapshot:
    """Persistent first-parent file state for one commit in the fixed DAG.

    Overrides store both live incarnations and explicit tombstones.  Looking up
    a path therefore follows commit parents, never the incidental order in
    which sibling commits appeared in ``rev-list``.
    """

    parent: _LineageSnapshot | None
    overrides: dict[str, _FileIncarnation | None] = field(default_factory=dict)
    cache: dict[str, _FileIncarnation | None] = field(default_factory=dict)

    def get(self, path: str) -> _FileIncarnation | None:
        pending: list[_LineageSnapshot] = []
        current: _LineageSnapshot | None = self
        value: _FileIncarnation | None = None
        while current is not None:
            if path in current.overrides:
                value = current.overrides[path]
                break
            if path in current.cache:
                value = current.cache[path]
                break
            pending.append(current)
            current = current.parent
        for snapshot in pending:
            snapshot.cache[path] = value
        return value

    def set(self, path: str, value: _FileIncarnation | None) -> None:
        self.overrides[path] = value
        self.cache.pop(path, None)


def _normalize_path(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    path = PurePosixPath(text)
    if not text or text.startswith("/") or ".." in path.parts:
        raise ExperienceInputError(f"file path must be relative and normalized: {value!r}")
    return path.as_posix()


def as_utc(value: datetime | str) -> datetime:
    """Normalize an ISO timestamp or datetime to aware UTC."""

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ExperienceInputError(f"invalid timestamp: {value!r}") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ExperienceInputError(f"timestamp must be datetime or ISO string: {value!r}")
    if parsed.tzinfo is None:
        raise ExperienceInputError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def observation_window(
    commits: Sequence[ExperienceCommit], observation_end: datetime | str | None = None
) -> tuple[datetime | None, datetime | None, dict[str, str | None]]:
    timestamps = [as_utc(commit.authored_at) for commit in commits]
    start = min(timestamps) if timestamps else None
    last_commit = max(timestamps) if timestamps else None
    end = as_utc(observation_end) if observation_end is not None else last_commit
    if last_commit is not None and end is not None and end < last_commit:
        raise ExperienceInputError("observation_end cannot precede the latest commit")
    return (
        start,
        end,
        {
            "start": iso_utc(start) if start is not None else None,
            "end": iso_utc(end) if end is not None else None,
        },
    )


def ordered_commits(commits: Iterable[ExperienceCommit]) -> list[ExperienceCommit]:
    """Return deterministic collector order.

    When a collector supplies ``sequence`` it must do so for every event and
    the values must be unique.  This is the preferred fixed-OID/topological
    order for file history.  Timestamp order is a compatibility fallback.
    """

    rows = list(commits)
    oids = [row.oid for row in rows]
    if any(not oid.strip() for oid in oids):
        raise ExperienceInputError("commit oid must not be empty")
    if len(oids) != len(set(oids)):
        raise ExperienceInputError("duplicate commit oid")
    sequences = [row.sequence for row in rows]
    if any(value is not None for value in sequences):
        if any(value is None for value in sequences):
            raise ExperienceInputError("commit sequence must be supplied for every event")
        materialized = [int(value) for value in sequences if value is not None]
        if len(materialized) != len(set(materialized)):
            raise ExperienceInputError("duplicate commit sequence")
        return sorted(rows, key=lambda row: int(row.sequence or 0))
    return sorted(rows, key=lambda row: (as_utc(row.authored_at), row.oid))


def _trailers(message: str) -> list[tuple[str, str]]:
    """Parse only Git's final, blank-line-delimited trailer paragraph.

    A key-shaped line in prose or an example is not a declaration.  This is the
    default ``git interpret-trailers --parse`` shape used by the supported
    trailers: a subject/body, a blank separator, then a final block consisting
    only of trailers, continuations, and comment lines.
    """

    lines = message.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []

    block_start = len(lines) - 1
    while block_start > 0 and lines[block_start - 1].strip():
        block_start -= 1
    if block_start == 0 or lines[block_start - 1].strip():
        return []

    result: list[tuple[str, str]] = []
    for raw_line in lines[block_start:]:
        if raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1].isspace():
            if not result:
                return []
            key, value = result[-1]
            result[-1] = (key, " ".join((value, raw_line.strip())).strip())
            continue
        match = _TRAILER_RE.fullmatch(raw_line.strip())
        if match is None:
            return []
        result.append((match.group(1).lower(), match.group(2).strip()))
    return result


def trailer_observations(
    message: str,
    *,
    ai_coauthor_emails: Iterable[str] = (),
    ai_coauthor_email_sha256: Iterable[str] = (),
) -> tuple[bool, bool]:
    """Return ``(declared_ai_assist, has_human_coauthor)``.

    ``Co-authored-by`` is considered AI only when its email is present in the
    caller-maintained AI identity set.  Names and fuzzy text are never used to
    infer an AI or a person.
    """

    ai_emails = {normalize_email(value) for value in ai_coauthor_emails}
    ai_email_digests = {value.lower() for value in ai_coauthor_email_sha256}
    declared_ai = False
    human_coauthor = False
    for key, value in _trailers(message):
        if key in _AI_TRAILERS and value:
            declared_ai = True
        if key != "co-authored-by":
            continue
        match = _COAUTHOR_EMAIL_RE.search(value)
        if match is None:
            continue
        email = normalize_email(match.group(1))
        if email in ai_emails or email_identity_sha256(email) in ai_email_digests:
            declared_ai = True
        else:
            human_coauthor = True
    return declared_ai, human_coauthor


def is_dependency_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    base = normalized.rsplit("/", 1)[-1]
    return (
        base in _DEPENDENCY_BASENAMES
        or base.startswith("requirements-")
        and base.endswith(".txt")
        or base.endswith(".gradle")
        or base.endswith(".gradle.kts")
    )


def classify_domain(path: str) -> str:
    """Classify one path into a provider-neutral descriptive domain."""

    normalized = path.replace("\\", "/").strip("/").lower()
    parts = PurePosixPath(normalized).parts
    base = parts[-1] if parts else ""
    suffix = PurePosixPath(base).suffix
    if is_dependency_path(normalized):
        return "deps"
    if is_test_path(normalized):
        return "test"
    if "docs" in parts[:-1] or base.split(".", 1)[0] in _DOC_BASENAMES or suffix in _DOC_SUFFIXES:
        return "docs"
    if (
        any(part in _INFRA_PREFIXES for part in parts[:-1])
        or base in _INFRA_BASENAMES
        or suffix == ".tf"
    ):
        return "infra"
    if any(part in _CORE_PREFIXES for part in parts[:-1]) or suffix in _CORE_SUFFIXES:
        return "core"
    return "unclassified"


def classify_language(path: str) -> str:
    """Return a stable language family from a path, without content guessing."""

    suffix = PurePosixPath(path.replace("\\", "/").lower()).suffix
    return _LANGUAGE_SUFFIXES.get(suffix, "other")


def is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    parts = PurePosixPath(normalized).parts
    base = parts[-1] if parts else ""
    stem = base.rsplit(".", 1)[0]
    return (
        any(part in {"test", "tests", "__tests__", "spec", "specs"} for part in parts[:-1])
        or stem.startswith("test_")
        or stem.endswith("_test")
        or ".test." in base
        or ".spec." in base
    )


def is_production_path(path: str) -> bool:
    """Use the report-v1 test-cochange path taxonomy as the production SSOT."""

    return is_prod_path(path)


def _metric(
    numerator: int,
    denominator: int,
    *,
    unit: str,
    window: dict[str, str | None],
    limitations: Sequence[str],
    min_population: int,
    count_value: bool = False,
    zero_reason: str | None = None,
) -> dict[str, object]:
    common: dict[str, object] = {
        "denominator": denominator,
        "unit": unit,
        "window": dict(window),
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
        "limitations": list(limitations),
    }
    if zero_reason is not None and denominator == 0:
        return {"kind": "not_observed", "reason": zero_reason, **common}
    if denominator < min_population:
        return {"kind": "not_observed", "reason": "insufficient_population", **common}
    value: int | float = numerator if count_value else round(numerator / denominator, 4)
    return {
        "kind": "observed",
        "value": value,
        "numerator": numerator,
        **common,
    }


def _not_consented(actor_id: str) -> dict[str, object]:
    return {
        "kind": "not_observed",
        "actor_id": actor_id,
        "reason": "consenting_actor_required",
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
        "limitations": [
            "Experience observations require an explicit, actor-matched tenant consent record.",
            "A public Git identity, provider handle, or name similarity is not consent.",
        ],
    }


def _suppressed_observation(
    reason: str,
    denominator: int,
    *,
    unit: str,
    window: dict[str, str | None],
    limitations: Sequence[str],
) -> dict[str, object]:
    return {
        "kind": "not_observed",
        "reason": reason,
        "denominator": denominator,
        "unit": unit,
        "window": dict(window),
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
        "limitations": list(limitations),
    }


def _path_distribution(counts: Counter[str]) -> dict[str, object]:
    denominator = sum(counts.values())
    return {
        "denominator": denominator,
        "unit": "path_touch_share",
        "values": {
            name: {"n": count, "share": round(count / denominator, 4)}
            for name, count in sorted(counts.items())
        }
        if denominator
        else {},
    }


def _parent_graph_index(
    parents_by_oid: dict[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, bool], str | None]:
    """Build a non-recursive DAG index and ancestry-completeness map."""

    children: dict[str, list[str]] = {oid: [] for oid in parents_by_oid}
    known_parent_count: dict[str, int] = {}
    for oid, parents in parents_by_oid.items():
        if len(parents) != len(set(parents)):
            return {}, {}, "duplicate_commit_parent"
        known = [parent for parent in parents if parent in parents_by_oid]
        known_parent_count[oid] = len(known)
        for parent in known:
            children[parent].append(oid)

    ready = deque(sorted(oid for oid, count in known_parent_count.items() if count == 0))
    topological: list[str] = []
    while ready:
        oid = ready.popleft()
        topological.append(oid)
        for child in sorted(children[oid]):
            known_parent_count[child] -= 1
            if known_parent_count[child] == 0:
                ready.append(child)
    if len(topological) != len(parents_by_oid):
        return {}, {}, "commit_parent_cycle"

    complete: dict[str, bool] = {}
    for oid in topological:
        complete[oid] = all(
            parent in parents_by_oid and complete[parent] for parent in parents_by_oid[oid]
        )
    return {oid: tuple(sorted(values)) for oid, values in children.items()}, complete, None


def _descendant_oids(
    target_oid: str,
    children_by_oid: dict[str, tuple[str, ...]],
) -> frozenset[str]:
    """Return target plus every descendant using only supplied commit edges."""

    seen = {target_oid}
    pending = deque([target_oid])
    while pending:
        oid = pending.popleft()
        for child in children_by_oid[oid]:
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return frozenset(seen)


def _post_release_fix_count(
    rows: Sequence[ExperienceCommit],
    target_nonmerge: Sequence[ExperienceCommit],
    tags: Sequence[ReleaseTag],
) -> tuple[int, str | None]:
    """Count corrective commits that descend from a temporally applicable tag.

    Returns ``(count, reason)``.  A non-``None`` reason means the count is not
    publishable because ancestry could not be proven from the supplied fixed
    OID history.  Sibling branches are a proven negative, not an unknown.
    """

    if not tags:
        return 0, None
    parents_by_oid = {commit.oid: tuple(commit.parents) for commit in rows}
    children_by_oid, ancestry_complete, graph_reason = _parent_graph_index(parents_by_oid)
    if graph_reason is not None:
        return 0, graph_reason
    if any(tag.target_oid not in parents_by_oid for tag in tags):
        return 0, "release_tag_target_missing"
    descendants = {
        target_oid: _descendant_oids(target_oid, children_by_oid)
        for target_oid in sorted({tag.target_oid for tag in tags})
    }

    count = 0
    incomplete = False
    for commit in target_nonmerge:
        if not is_corrective_subject(commit.subject):
            continue
        timestamp = as_utc(commit.authored_at)
        applicable = [
            tag
            for tag in tags
            if as_utc(tag.tagged_at)
            <= timestamp
            <= as_utc(tag.tagged_at) + timedelta(days=POST_RELEASE_DAYS)
        ]
        if not applicable:
            continue
        if any(commit.oid in descendants[tag.target_oid] for tag in applicable):
            count += 1
        elif not ancestry_complete[commit.oid]:
            incomplete = True
    if incomplete:
        return 0, "commit_ancestry_incomplete"
    return count, None


def _language_domain_timeline(
    target_nonmerge: Sequence[ExperienceCommit],
    *,
    window: dict[str, str | None],
    min_population: int,
) -> dict[str, object]:
    limitations = [
        "Languages are classified from file suffixes; contents are not guessed.",
        "Domain and language values are path-touch shares, not effort or proficiency.",
    ]
    if len(target_nonmerge) < min_population:
        return _suppressed_observation(
            "insufficient_population",
            len(target_nonmerge),
            unit="commits",
            window=window,
            limitations=limitations,
        )
    buckets: dict[str, dict[str, object]] = {}
    for commit in sorted(target_nonmerge, key=lambda row: (as_utc(row.authored_at), row.oid)):
        year = str(as_utc(commit.authored_at).year)
        bucket = buckets.setdefault(
            year,
            {
                "commit_n": 0,
                "path_touch_commit_n": 0,
                "languages": Counter[str](),
                "domains": Counter[str](),
            },
        )
        bucket["commit_n"] = int(bucket["commit_n"]) + 1
        if commit.changes:
            bucket["path_touch_commit_n"] = int(bucket["path_touch_commit_n"]) + 1
        languages = bucket["languages"]
        domains = bucket["domains"]
        assert isinstance(languages, Counter)
        assert isinstance(domains, Counter)
        for change in commit.changes:
            languages[classify_language(change.path)] += 1
            domains[classify_domain(change.path)] += 1
    periods = []
    for period, bucket in sorted(buckets.items()):
        languages = bucket["languages"]
        domains = bucket["domains"]
        assert isinstance(languages, Counter)
        assert isinstance(domains, Counter)
        periods.append(
            {
                "period": period,
                "commit_n": bucket["commit_n"],
                "path_touch_commit_n": bucket["path_touch_commit_n"],
                "languages": _path_distribution(languages),
                "domains": _path_distribution(domains),
            }
        )
    return {
        "kind": "observed",
        "numerator": sum(bool(commit.changes) for commit in target_nonmerge),
        "denominator": len(target_nonmerge),
        "unit": "commits",
        "window": dict(window),
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
        "periods": periods,
        "limitations": limitations,
    }


def _repository_size_points(
    target_nonmerge: Sequence[ExperienceCommit],
    *,
    window: dict[str, str | None],
    min_population: int,
) -> dict[str, object]:
    limitations = [
        "Snapshots are supplied by the fixed-OID collector after the selected commit.",
        "The median point is the nearest-rank 50th percentile target contribution.",
        "Repository size is context, not a measure of contribution quality.",
    ]
    denominator = len(target_nonmerge)
    if denominator < min_population:
        return _suppressed_observation(
            "insufficient_population",
            denominator,
            unit="target_commits",
            window=window,
            limitations=limitations,
        )
    indexes = (0, (denominator - 1) // 2, denominator - 1)
    selected = [target_nonmerge[index] for index in indexes]
    required = (
        "repository_commit_count_after",
        "repository_file_count_after",
        "repository_line_count_after",
    )
    if any(getattr(commit, name) is None for commit in selected for name in required):
        return _suppressed_observation(
            "repository_size_snapshots_missing",
            denominator,
            unit="target_commits",
            window=window,
            limitations=limitations,
        )
    labels = ("first", "median", "last")
    points: dict[str, object] = {}
    for label, index, commit in zip(labels, indexes, selected):
        points[label] = {
            "target_contribution_rank": index + 1,
            "commit_oid": commit.oid,
            "observed_at": iso_utc(as_utc(commit.authored_at)),
            "repository_commit_count": commit.repository_commit_count_after,
            "repository_file_count": commit.repository_file_count_after,
            "repository_line_count": commit.repository_line_count_after,
        }
    return {
        "kind": "observed",
        "numerator": len({commit.oid for commit in selected}),
        "denominator": denominator,
        "unit": "target_commits",
        "window": dict(window),
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
        "points": points,
        "limitations": limitations,
    }


def _dependency_introduction(
    target_nonmerge: Sequence[ExperienceCommit],
    introductions: Mapping[str, frozenset[str]] | None,
    manifest_commits: int | None,
    unparseable: int | None,
    *,
    window: dict[str, str | None],
    min_population: int,
) -> dict[str, object]:
    """Names this actor first declared, with the coverage behind the count.

    Without a scan the axis is not_observed: claiming zero introductions from a
    scan that never ran would read absence as evidence (norms §1).
    """
    common: dict[str, object] = {
        "unit": "packages",
        "window": dict(window),
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
    }
    if introductions is None:
        return {
            "kind": "not_observed",
            "reason": "dependency_scan_not_provided",
            "limitations": [
                "Dependency introductions require a manifest scan of the fixed revision."
            ],
            **common,
        }
    denominator = len(target_nonmerge)
    if denominator < min_population:
        return {
            "kind": "not_observed",
            "reason": "insufficient_population",
            "denominator": denominator,
            "limitations": ["Introductions are reported only above the population floor."],
            **common,
        }
    owned = {commit.oid for commit in target_nonmerge}
    names: set[str] = set()
    for oid, declared in introductions.items():
        if oid in owned:
            names.update(declared)
    limitations = [
        "A name counts once, for the commit that first declared it; version bumps do not count.",
        "Lock files are not read, so transitive updates are never recorded as a choice.",
    ]
    if unparseable:
        limitations.append(
            f"{unparseable} manifest revision(s) were unreadable and skipped; "
            "a zero here may reflect that parse failure, not an absence of choices."
        )
    return {
        "kind": "observed",
        "value": len(names),
        "values": sorted(names),
        "denominator": denominator,
        "manifest_commits": manifest_commits if manifest_commits is not None else 0,
        "unparseable_manifests": unparseable if unparseable is not None else 0,
        "limitations": limitations,
        **common,
    }


def build_experience(
    commits: Iterable[ExperienceCommit],
    *,
    actor_id: str,
    consent: TenantConsent | None,
    ai_coauthor_emails: Iterable[str] = (),
    ai_coauthor_email_sha256: Iterable[str] = (),
    release_tags: Iterable[ReleaseTag] = (),
    observation_end: datetime | str | None = None,
    min_population: int = DEFAULT_MIN_POPULATION,
    dependency_introductions: Mapping[str, frozenset[str]] | None = None,
    dependency_manifest_commits: int | None = None,
    dependency_unparseable: int | None = None,
) -> dict[str, object]:
    """Build consented actor observations from normalized commit events."""

    if min_population < 1:
        raise ExperienceInputError("min_population must be positive")
    if consent is None or consent.actor_id != actor_id:
        return _not_consented(actor_id)

    rows = ordered_commits(commits)
    start, end, window = observation_window(rows, observation_end)
    tags = list(release_tags)
    normalized_ai_coauthor_emails = tuple(ai_coauthor_emails)
    normalized_ai_coauthor_digests = tuple(ai_coauthor_email_sha256)

    snapshots: dict[str, _LineageSnapshot] = {}
    target_creations: list[_FileIncarnation] = []
    creation_ended_at: dict[str, datetime] = {}
    adopted_creation_ids: set[str] = set()
    cross_author_denominator = 0
    cross_author_numerator = 0
    self_maintenance_denominator = 0
    self_maintenance_returns = 0

    target_nonmerge = [
        commit
        for commit in rows
        if commit.actor_id == actor_id and not commit.is_bot and not commit.is_merge
    ]
    repo_human_nonmerge = [commit for commit in rows if not commit.is_bot and not commit.is_merge]
    known_oids = {commit.oid for commit in rows}
    previous_snapshot: _LineageSnapshot | None = None

    for commit in rows:
        parent_snapshots = tuple(
            snapshots[parent] for parent in commit.parents if parent in snapshots
        )
        primary_parent = snapshots.get(commit.parents[0]) if commit.parents else None
        if (
            primary_parent is None
            and commit.parents
            and all(parent not in known_oids for parent in commit.parents)
        ):
            # Compatibility for callers that supplied normalized linear events
            # before parent OIDs became part of the fixed-DAG contract.  Real
            # collection rejects missing ancestry before reaching this layer.
            primary_parent = previous_snapshot
        current = _LineageSnapshot(primary_parent)
        timestamp = as_utc(commit.authored_at)
        known_human_mr = False
        cross_author_mr = False
        for change in commit.changes:
            state: _FileIncarnation | None = None
            if change.status in {"M", "D"}:
                state = current.get(change.path)
            elif change.status == "R" and change.old_path is not None:
                state = current.get(change.old_path)

            if (
                not commit.is_merge
                and commit.actor_id == actor_id
                and not commit.is_bot
                and change.status in {"M", "R"}
                and state is not None
                and state.creator_actor_id is not None
                and not state.creator_is_bot
            ):
                known_human_mr = True
                if state.creator_actor_id != actor_id:
                    cross_author_mr = True

            if (
                not commit.is_merge
                and state is not None
                and state.creator_actor_id == actor_id
                and commit.actor_id == actor_id
                and not commit.is_bot
                and change.status in {"M", "R"}
            ):
                self_maintenance_denominator += 1
                previous = state.last_target_touch
                if previous is not None and timestamp - previous >= timedelta(days=RETURN_DAYS):
                    self_maintenance_returns += 1
                state = replace(state, last_target_touch=timestamp)

            if (
                not commit.is_merge
                and state is not None
                and state.creator_actor_id == actor_id
                and commit.actor_id not in {None, actor_id}
                and not commit.is_bot
                and change.status in {"M", "R"}
                and timestamp - state.created_at >= timedelta(days=ADOPTION_DAYS)
            ):
                adopted_creation_ids.add(state.creation_id)

            if change.status == "D":
                if state is not None:
                    creation_ended_at.setdefault(state.creation_id, timestamp)
                current.set(change.path, None)
                continue
            if change.status == "R" and change.old_path is not None:
                current.set(change.old_path, None)
                # The fixed first-parent lineage wins a merge conflict.  A
                # missing source remains unresolved instead of borrowing from
                # whichever sibling happened to be traversed last.
                current.set(change.path, state)
                continue
            if change.status == "M":
                if state is not None:
                    current.set(change.path, state)
                continue
            if change.status in {"A", "C"}:
                inherited: _FileIncarnation | None = None
                if commit.is_merge and change.status == "A":
                    candidates = [snapshot.get(change.path) for snapshot in parent_snapshots[1:]]
                    present = [candidate for candidate in candidates if candidate is not None]
                    creation_ids = {candidate.creation_id for candidate in present}
                    if len(creation_ids) == 1:
                        inherited = present[0]
                created = inherited or _FileIncarnation(
                    creation_id=(
                        f"{commit.oid}\0merge-unresolved\0{change.path}"
                        if commit.is_merge
                        else f"{commit.oid}\0{change.status}\0{change.path}"
                    ),
                    creator_actor_id=None if commit.is_merge else commit.actor_id,
                    creator_is_bot=False if commit.is_merge else commit.is_bot,
                    created_at=timestamp,
                    last_target_touch=(
                        timestamp if not commit.is_merge and commit.actor_id == actor_id else None
                    ),
                )
                current.set(change.path, created)
                if not commit.is_merge and commit.actor_id == actor_id and not commit.is_bot:
                    target_creations.append(created)

        snapshots[commit.oid] = current
        previous_snapshot = current
        if (
            not commit.is_merge
            and commit.actor_id == actor_id
            and not commit.is_bot
            and known_human_mr
        ):
            cross_author_denominator += 1
            if cross_author_mr:
                cross_author_numerator += 1

    eligible_creations = []
    if end is not None:
        eligible_creations = [
            creation
            for creation in target_creations
            if min(end, creation_ended_at.get(creation.creation_id, end)) - creation.created_at
            >= timedelta(days=ADOPTION_DAYS)
        ]
    adopted = sum(creation.creation_id in adopted_creation_ids for creation in eligible_creations)

    dependency_commits = sum(
        any(is_dependency_path(change.path) for change in commit.changes)
        for commit in target_nonmerge
    )
    declared_ai_commits = 0
    human_coauthored_commits = 0
    ai_production_commits = 0
    ai_production_with_tests = 0
    for commit in target_nonmerge:
        declared_ai, human_coauthor = trailer_observations(
            commit.message,
            ai_coauthor_emails=normalized_ai_coauthor_emails,
            ai_coauthor_email_sha256=normalized_ai_coauthor_digests,
        )
        declared_ai_commits += declared_ai
        human_coauthored_commits += human_coauthor
        if declared_ai and any(is_production_path(change.path) for change in commit.changes):
            ai_production_commits += 1
            if any(is_test_path(change.path) for change in commit.changes):
                ai_production_with_tests += 1

    post_release_fixes, post_release_reason = _post_release_fix_count(
        rows,
        target_nonmerge,
        tags,
    )

    target_dates = sorted(as_utc(commit.authored_at) for commit in target_nonmerge)
    gaps = [
        (current - previous).total_seconds() / 86400
        for previous, current in zip(target_dates, target_dates[1:])
    ]
    cadence: dict[str, object]
    if len(target_dates) < min_population:
        cadence = {
            "kind": "not_observed",
            "reason": "insufficient_population",
            "denominator": len(target_dates),
            "unit": "commits",
            "window": dict(window),
            "definition_version": EXPERIENCE_DEFINITION_VERSION,
            "limitations": ["Cadence describes observed commit dates, not work hours."],
        }
    else:
        cadence = {
            "kind": "observed",
            "numerator": len(gaps),
            "median_gap_days": round(float(median(gaps)), 4) if gaps else 0.0,
            "longest_gap_days": round(max(gaps), 4) if gaps else 0.0,
            "denominator": len(target_dates),
            "unit": "days",
            "window": dict(window),
            "definition_version": EXPERIENCE_DEFINITION_VERSION,
            "limitations": ["Cadence describes observed commit dates, not work hours."],
        }

    repo_population = len(repo_human_nonmerge)
    if not target_nonmerge:
        founder_timing = _suppressed_observation(
            "no_target_contributions",
            repo_population,
            unit="repository_commits",
            window=window,
            limitations=[
                "Timing describes the first observed target commit and does not establish founder status."
            ],
        )
    else:
        first_target = target_nonmerge[0]
        first_index = repo_human_nonmerge.index(first_target)
        founder_timing = _metric(
            first_index,
            repo_population,
            unit="repository_commit_share",
            window=window,
            limitations=[
                "Value is the share of observed human non-merge commits before the target's first commit.",
                "This timing observation does not establish legal or organizational founder status.",
            ],
            min_population=min_population,
        )
        repo_start = as_utc(repo_human_nonmerge[0].authored_at)
        elapsed_days = (as_utc(first_target.authored_at) - repo_start).total_seconds() / 86400
        if founder_timing["kind"] == "observed" and elapsed_days >= 0:
            founder_timing["days_after_repository_start"] = round(elapsed_days, 4)
            founder_timing["first_contribution_at"] = iso_utc(as_utc(first_target.authored_at))
        elif founder_timing["kind"] == "observed":
            founder_timing["timing_state"] = "author_timestamp_skew"

    scaffold_limitations = [
        "Scaffold is a period proxy: A/C file events in the repository's first 30 days.",
        "The share does not establish authorship of the idea, ownership, or founder status.",
    ]
    if not repo_human_nonmerge or end is None:
        initial_scaffold = _suppressed_observation(
            "no_repository_history",
            0,
            unit="file_creation_share",
            window=window,
            limitations=scaffold_limitations,
        )
    else:
        scaffold_start = as_utc(repo_human_nonmerge[0].authored_at)
        scaffold_end = scaffold_start + timedelta(days=ADOPTION_DAYS)
        scaffold_window = {"start": iso_utc(scaffold_start), "end": iso_utc(scaffold_end)}
        scaffold_rows = [
            commit
            for commit in repo_human_nonmerge
            if scaffold_start <= as_utc(commit.authored_at) < scaffold_end
        ]
        scaffold_denominator = sum(
            change.status in {"A", "C"} for commit in scaffold_rows for change in commit.changes
        )
        scaffold_numerator = sum(
            change.status in {"A", "C"}
            for commit in scaffold_rows
            if commit.actor_id == actor_id
            for change in commit.changes
        )
        if end < scaffold_end:
            initial_scaffold = _suppressed_observation(
                "incomplete_initial_30_day_window",
                scaffold_denominator,
                unit="file_creation_share",
                window=scaffold_window,
                limitations=scaffold_limitations,
            )
        else:
            initial_scaffold = _metric(
                scaffold_numerator,
                scaffold_denominator,
                unit="file_creation_share",
                window=scaffold_window,
                limitations=scaffold_limitations,
                min_population=min_population,
            )

    annotated_tag_creations = sum(tag.annotated and tag.tagger_actor_id == actor_id for tag in tags)
    lightweight_tags = sum(not tag.annotated for tag in tags)
    lightweight_reason = (
        "lightweight_tag_has_no_tagger" if lightweight_tags else "no_lightweight_tags"
    )

    metrics = {
        "cross_author_modification_share": _metric(
            cross_author_numerator,
            cross_author_denominator,
            unit="commit_share",
            window=window,
            limitations=[
                "Counts target commits with M/R changes to known human-created files; bot-created and unresolved lineages are excluded.",
                "File state follows the fixed commit DAG; the first parent wins an existing-path merge conflict, while a path added from one unambiguous secondary lineage inherits that creator.",
            ],
            min_population=min_population,
        ),
        "adopted_creations": _metric(
            adopted,
            len(eligible_creations),
            unit="file_share",
            window=window,
            limitations=[
                "Only files with at least 30 days of observation opportunity are eligible.",
                "Rename inherits creation; copy and delete/re-add create a new incarnation.",
                "Deletion is not adoption.",
                "Bot and unresolved actors do not count as human adopters.",
                "Merge conflicts use fixed first-parent lineage; ambiguous secondary additions remain unresolved.",
            ],
            min_population=min_population,
        ),
        "self_maintenance_returns": _metric(
            self_maintenance_returns,
            self_maintenance_denominator,
            unit="events",
            window=window,
            limitations=["A return is a target M/R event at least 180 days after its prior touch."],
            min_population=min_population,
            count_value=True,
        ),
        "dependency_introduction": _dependency_introduction(
            target_nonmerge,
            dependency_introductions,
            dependency_manifest_commits,
            dependency_unparseable,
            window=window,
            min_population=min_population,
        ),
        "dependency_update_share": _metric(
            dependency_commits,
            len(target_nonmerge),
            unit="commit_share",
            window=window,
            limitations=["Dependency files are identified by a versioned deterministic path list."],
            min_population=min_population,
        ),
        "post_release_fixes": (
            _metric(
                post_release_fixes,
                len(target_nonmerge),
                unit="commits",
                window=window,
                limitations=[
                    "Subject classification is convention-dependent.",
                    "A fix counts only when the supplied tag target is its Git ancestor and its author timestamp is within the inclusive 30-day release window.",
                    "Annotated and lightweight tags can mark a release; lightweight tagger attribution remains unavailable.",
                ],
                min_population=min_population,
                count_value=True,
            )
            if post_release_reason is None or len(target_nonmerge) < min_population
            else _suppressed_observation(
                post_release_reason,
                len(target_nonmerge),
                unit="commits",
                window=window,
                limitations=[
                    "Post-release ancestry could not be proven from the supplied fixed-OID commit graph.",
                    "No count is published when a tag target or parent path is missing, or the parent graph contains a cycle.",
                ],
            )
        ),
        "declared_ai_assist_share": _metric(
            declared_ai_commits,
            len(target_nonmerge),
            unit="commit_share",
            window=window,
            limitations=[
                "Measures declared trailers only; absence does not establish absence of AI use."
            ],
            min_population=min_population,
        ),
        "declared_ai_test_cochange": _metric(
            ai_production_with_tests,
            ai_production_commits,
            unit="commit_share",
            window=window,
            limitations=[
                "Measures test path co-change on declared-AI production commits, not test quality."
            ],
            min_population=min_population,
            zero_reason=("no_declared_ai_commits" if declared_ai_commits == 0 else None),
        ),
        "human_coauthored_share": _metric(
            human_coauthored_commits,
            len(target_nonmerge),
            unit="commit_share",
            window=window,
            limitations=[
                "Only syntactically valid Co-authored-by trailers are counted.",
                "AI coauthors require an explicit caller-maintained identity set.",
            ],
            min_population=min_population,
        ),
        "cadence": cadence,
        "language_domain_timeline": _language_domain_timeline(
            target_nonmerge,
            window=window,
            min_population=min_population,
        ),
        "repository_size_at_contribution_points": _repository_size_points(
            target_nonmerge,
            window=window,
            min_population=min_population,
        ),
        "founder_timing": founder_timing,
        "initial_30d_scaffold_creation_share": initial_scaffold,
        "annotated_tag_creation": _metric(
            annotated_tag_creations,
            len(target_nonmerge),
            unit="tag_events",
            window=window,
            limitations=[
                "Counts only supplied annotated tags whose explicit tagger actor matches the target.",
                "Tag creation is a process observation, not a release-quality judgment.",
            ],
            min_population=min_population,
            count_value=True,
        ),
        "lightweight_tag_attribution": _suppressed_observation(
            lightweight_reason,
            lightweight_tags,
            unit="tags",
            window=window,
            limitations=[
                "Lightweight tags have no tagger identity in the Git object and remain unattributed."
            ],
        ),
    }
    if declared_ai_commits == 0 and metrics["declared_ai_assist_share"]["kind"] == "observed":
        metrics["declared_ai_assist_share"]["observation_state"] = "no_declared_ai_commits"

    return {
        "kind": "observed",
        "actor_id": actor_id,
        "consent_basis": consent.basis,
        "definition_version": EXPERIENCE_DEFINITION_VERSION,
        "window": window,
        "metrics": metrics,
        "limitations": [
            "These are repository observations, not ability, quality, employment-role, or rank.",
            "File creation and modification depend on normalized Git diff events at a fixed OID.",
            "Merge file lineage is deterministic: existing paths follow the first parent and ambiguous secondary additions remain unresolved.",
        ],
    }
