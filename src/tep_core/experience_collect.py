"""Collect normalized experience inputs from an already-materialized Git HEAD.

The collection boundary is intentionally narrow: the caller resolves a fixed
revision (normally with :func:`tep_core.revision.fixed_revision_worktree`) and
supplies the repo-local commit-to-actor partition.  This module never fetches,
never infers identities, and never changes that partition.

Commit objects are read in one ``cat-file --batch`` pass.  File changes are
read in one ``diff-tree --stdin`` pass with Git's ``-M50%`` rename rule and
explicit copy detection.  Exact repository-size snapshots are only calculated
for the first, median, and last non-merge contributions of actor ids selected
by the caller.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

from tep_core.attribution import GitObjectId, parse_git_oid
from tep_core.experience import ExperienceCommit, FileChange, ReleaseTag
from tep_core.identity import email_identity_sha256

__all__ = [
    "DependencyIntroductions",
    "ExperienceCollection",
    "ExperienceCollectionError",
    "ExperienceHistoryIncomplete",
    "collect_dependency_introductions",
    "collect_experience_inputs",
]


# Wall-clock budget for one Git subprocess. `diff-tree --find-copies-harder`
# compares every changed path against the whole tree, so its cost grows with
# repository size; on an 11,982-commit repository it exceeds this budget.
# Exceeding it yields not_observed, never a traceback (R8).
_GIT_BUDGET_SECONDS = 180


class ExperienceCollectionError(RuntimeError):
    """Raised when Git cannot provide a complete, internally consistent view."""


class ExperienceHistoryIncomplete(ExperienceCollectionError):
    """Raised before metrics when the fixed-OID ancestor history is not complete."""


@dataclass(frozen=True)
class ExperienceCollection:
    """Normalized fixed-revision inputs for experience and role calculations."""

    target_oid: GitObjectId
    commits: tuple[ExperienceCommit, ...]
    release_tags: tuple[ReleaseTag, ...]


_HEX_OID_RE = re.compile(rb"^[0-9a-f]+$")
_DIFF_STATUS_RE = re.compile(rb"^([A-Z])([0-9]{1,3})?$")
_MISSING_OBJECT_MARKERS = (
    "bad object",
    "could not read",
    "failed to read object",
    "invalid object",
    "lazy fetching disabled",
    "missing blob",
    "missing commit",
    "missing tree",
    "not a valid object",
    "promisor remote",
    "unable to read",
)


def _git_environment() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _git_bytes(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
    allowed_returncodes: Sequence[int] = (0,),
) -> bytes:
    try:
        result = subprocess.run(  # noqa: S603
            [
                "git",
                "--no-replace-objects",
                "-c",
                "safe.directory=*",
                "-C",
                str(repo),
                *args,
            ],
            input=input_bytes,
            capture_output=True,
            env=_git_environment(),
            timeout=_GIT_BUDGET_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        # A budget overrun is a missing observation, not a crash. Callers map
        # this to not_observed/experience_collection_timeout; letting
        # TimeoutExpired escape printed a traceback instead (R8).
        raise ExperienceCollectionError(
            f"git subprocess timed out after {_GIT_BUDGET_SECONDS}s: git {' '.join(args)}"
        ) from exc
    if result.returncode not in allowed_returncodes:
        error = result.stderr.decode("utf-8", "replace").strip()
        lowered = error.casefold()
        if any(marker in lowered for marker in _MISSING_OBJECT_MARKERS):
            raise ExperienceHistoryIncomplete(
                f"history_incomplete: {error or 'required Git object is unavailable'}"
            )
        raise ExperienceCollectionError(error or f"git {' '.join(args)} failed")
    return result.stdout


def _git_text(repo: Path, *args: str) -> str:
    return _git_bytes(repo, *args).decode("utf-8", "replace").strip()


def _resolve_target(repo: Path, revision: str) -> GitObjectId:
    oid = _git_text(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
    object_format = _git_text(repo, "rev-parse", "--show-object-format")
    parsed = parse_git_oid(oid)
    if parsed.algorithm != object_format:
        raise ExperienceCollectionError(
            f"Git object format {object_format!r} disagrees with target OID {parsed.algorithm!r}"
        )
    return parsed


def _assert_complete_repository(repo: Path) -> None:
    """Reject repository shapes that cannot prove the full ancestor population."""

    shallow = _git_text(repo, "rev-parse", "--is-shallow-repository").casefold() == "true"
    promisor_output = _git_bytes(
        repo,
        "config",
        "--local",
        "--bool",
        "--get-regexp",
        r"^remote\..*\.promisor$",
        allowed_returncodes=(0, 1),
    ).decode("utf-8", "replace")
    promisor = any(
        line.rsplit(maxsplit=1)[-1].casefold() == "true"
        for line in promisor_output.splitlines()
        if line.strip()
    )
    if shallow:
        raise ExperienceHistoryIncomplete("history_incomplete: shallow repository")
    if promisor:
        raise ExperienceHistoryIncomplete("history_incomplete: promisor repository")


def _reachable_oids(repo: Path, target: GitObjectId) -> tuple[str, ...]:
    output = _git_bytes(repo, "rev-list", "--reverse", "--topo-order", target.value)
    rows = tuple(line.decode("ascii") for line in output.splitlines() if line)
    if not rows or rows[-1] != target.value:
        raise ExperienceCollectionError("fixed target was not the final topological revision")
    expected_length = len(target.value)
    if any(
        len(row) != expected_length or not _HEX_OID_RE.fullmatch(row.encode("ascii"))
        for row in rows
    ):
        raise ExperienceCollectionError("rev-list returned an invalid object id")
    if len(rows) != len(set(rows)):
        raise ExperienceCollectionError("rev-list returned duplicate commits")
    return rows


@dataclass(frozen=True)
class _CommitObject:
    oid: str
    parents: tuple[str, ...]
    authored_at: datetime
    message: str


def _parse_commit_object(oid: str, payload: bytes) -> _CommitObject:
    try:
        header_bytes, message_bytes = payload.split(b"\n\n", 1)
    except ValueError as exc:
        raise ExperienceCollectionError(f"commit {oid} has no header/body separator") from exc

    parents: list[str] = []
    author_epoch: int | None = None
    encoding = "utf-8"
    for line in header_bytes.splitlines():
        if line.startswith(b"parent "):
            parent = line[7:].decode("ascii")
            if not _HEX_OID_RE.fullmatch(parent.encode("ascii")):
                raise ExperienceCollectionError(f"commit {oid} has an invalid parent OID")
            parents.append(parent)
        elif line.startswith(b"author "):
            try:
                author_epoch = int(line.rsplit(b" ", 2)[-2])
            except (IndexError, ValueError) as exc:
                raise ExperienceCollectionError(
                    f"commit {oid} has an invalid author header"
                ) from exc
        elif line.startswith(b"encoding "):
            encoding = line[9:].decode("ascii", "strict")
    if author_epoch is None:
        raise ExperienceCollectionError(f"commit {oid} has no author timestamp")
    try:
        message = message_bytes.decode(encoding, "replace")
    except LookupError as exc:
        raise ExperienceCollectionError(
            f"commit {oid} declares unknown encoding {encoding!r}"
        ) from exc
    return _CommitObject(
        oid=oid,
        parents=tuple(parents),
        authored_at=datetime.fromtimestamp(author_epoch, timezone.utc),
        message=message,
    )


def _read_commit_objects(repo: Path, oids: Sequence[str]) -> tuple[_CommitObject, ...]:
    output = _git_bytes(
        repo,
        "cat-file",
        "--batch",
        input_bytes=("\n".join(oids) + "\n").encode("ascii"),
    )
    cursor = 0
    objects: list[_CommitObject] = []
    for expected_oid in oids:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise ExperienceCollectionError("truncated cat-file batch header")
        header = output[cursor:header_end].split()
        if len(header) == 2 and header[1] == b"missing":
            raise ExperienceHistoryIncomplete(
                f"history_incomplete: commit {expected_oid} is unavailable"
            )
        if len(header) != 3 or header[0].decode("ascii") != expected_oid:
            raise ExperienceCollectionError("cat-file returned commits out of order")
        if header[1] != b"commit":
            raise ExperienceCollectionError(f"{expected_oid} is not a commit object")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise ExperienceCollectionError("cat-file returned an invalid object size") from exc
        body_start = header_end + 1
        body_end = body_start + size
        if body_end >= len(output) or output[body_end : body_end + 1] != b"\n":
            raise ExperienceCollectionError("truncated cat-file commit object")
        objects.append(_parse_commit_object(expected_oid, output[body_start:body_end]))
        cursor = body_end + 1
    if output[cursor:]:
        raise ExperienceCollectionError("cat-file returned unregistered trailing data")
    return tuple(objects)


def _status_token(token: bytes) -> tuple[str, int | None]:
    match = _DIFF_STATUS_RE.fullmatch(token)
    if match is None:
        raise ExperienceCollectionError(f"unsupported diff status: {token!r}")
    raw_status = match.group(1).decode("ascii")
    similarity = int(match.group(2)) if match.group(2) is not None else None
    # A committed type change is a modification for the experience model.
    status = "M" if raw_status == "T" else raw_status
    if status not in {"A", "M", "D", "R", "C"}:
        raise ExperienceCollectionError(f"unsupported committed diff status: {raw_status}")
    if status in {"R", "C"} and similarity is None:
        raise ExperienceCollectionError(f"{status} status omitted its similarity")
    return status, similarity


def _path(token: bytes) -> str:
    # Git paths are arbitrary bytes except NUL.  surrogateescape preserves the
    # original bytes while FileChange performs the shared relative-path checks.
    return token.decode("utf-8", "surrogateescape")


def _read_changes(
    repo: Path,
    commits: Sequence[_CommitObject],
) -> dict[str, tuple[FileChange, ...]]:
    oids = [commit.oid for commit in commits]
    output = _git_bytes(
        repo,
        "diff-tree",
        "--stdin",
        "--always",
        "--root",
        "-r",
        "-M50%",
        "-C50%",
        # `--find-copies-harder` is deliberately absent. It only widens copy
        # detection to unmodified sources, turning some `A` rows into `C`; every
        # consumer treats `A` and `C` identically (experience.py:861,1001,1004 and
        # role_profile.py:150,171), so it cannot change a measured value. It cost
        # ~100x on large repositories and was the sole cause of the collection
        # timeout on an 11,982-commit repository (R8).
        "--diff-merges=first-parent",
        "--name-status",
        "-z",
        "--format=%H",
        input_bytes=("\n".join(oids) + "\n").encode("ascii"),
    )
    tokens = output.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    changes: dict[str, tuple[FileChange, ...]] = {}
    token_index = 0
    for commit_index, commit in enumerate(commits):
        if token_index >= len(tokens):
            raise ExperienceCollectionError("diff-tree omitted a commit boundary")
        expected = commit.oid.encode("ascii")
        boundary = tokens[token_index]
        if commit_index and boundary.startswith(b"\n"):
            boundary = boundary[1:]
        if boundary != expected:
            raise ExperienceCollectionError("diff-tree returned commits out of order")
        token_index += 1
        rows: list[FileChange] = []
        while token_index < len(tokens):
            token = tokens[token_index]
            next_oid = (
                commits[commit_index + 1].oid.encode("ascii")
                if commit_index + 1 < len(commits)
                else None
            )
            if next_oid is not None and token in {next_oid, b"\n" + next_oid}:
                break
            if not rows and token.startswith(b"\n"):
                token = token[1:]
            status, similarity = _status_token(token)
            token_index += 1
            required_paths = 2 if status in {"R", "C"} else 1
            if token_index + required_paths > len(tokens):
                raise ExperienceCollectionError("truncated diff-tree path record")
            paths = [_path(value) for value in tokens[token_index : token_index + required_paths]]
            token_index += required_paths
            if status in {"R", "C"}:
                rows.append(
                    FileChange(
                        status=status,
                        old_path=paths[0],
                        path=paths[1],
                        similarity=similarity,
                    )
                )
            else:
                rows.append(FileChange(status=status, path=paths[0]))
        changes[commit.oid] = tuple(rows)
    if token_index != len(tokens):
        raise ExperienceCollectionError("diff-tree returned unregistered trailing records")
    return changes


def _snapshot_oids(commits: Sequence[ExperienceCommit], actor_ids: Iterable[str]) -> set[str]:
    selected: set[str] = set()
    for actor_id in sorted({value for value in actor_ids if value}):
        rows = [row for row in commits if row.actor_id == actor_id and not row.is_merge]
        if not rows:
            continue
        for index in {0, (len(rows) - 1) // 2, len(rows) - 1}:
            selected.add(rows[index].oid)
    return selected


def _line_count(repo: Path, oid: str) -> int:
    output = _git_bytes(
        repo,
        "grep",
        "-I",
        "-z",
        "--count",
        "-e",
        "^",
        oid,
        "--",
        allowed_returncodes=(0, 1),
    )
    total = 0
    cursor = 0
    while cursor < len(output):
        separator = output.find(b"\0", cursor)
        if separator < 0:
            raise ExperienceCollectionError("git grep returned a path without a count")
        end = output.find(b"\n", separator + 1)
        if end < 0:
            raise ExperienceCollectionError("git grep returned a truncated count")
        try:
            total += int(output[separator + 1 : end])
        except ValueError as exc:
            raise ExperienceCollectionError("git grep returned a non-integer line count") from exc
        cursor = end + 1
    return total


def _repository_size(repo: Path, oid: str) -> tuple[int, int, int]:
    commit_count = int(_git_text(repo, "rev-list", "--count", oid))
    tree = _git_bytes(repo, "ls-tree", "-r", "-z", "--name-only", oid)
    file_count = tree.count(b"\0")
    return commit_count, file_count, _line_count(repo, oid)


def _collect_release_tags(
    repo: Path,
    target: GitObjectId,
    tagger_actor_by_email: Mapping[str, str],
    tagger_actor_by_email_sha256: Mapping[str, str],
) -> tuple[ReleaseTag, ...]:
    normalized_taggers = {
        email.strip().casefold(): actor_id for email, actor_id in tagger_actor_by_email.items()
    }
    normalized_tagger_digests = {
        digest.strip().casefold(): actor_id
        for digest, actor_id in tagger_actor_by_email_sha256.items()
    }
    fields = "%00".join(
        (
            "%(refname:strip=2)",
            "%(objecttype)",
            "%(objectname)",
            "%(*objectname)",
            "%(taggerdate:unix)",
            "%(taggeremail:trim)",
            "%(creatordate:unix)",
        )
    )
    output = _git_bytes(
        repo,
        "for-each-ref",
        f"--merged={target.value}",
        f"--format={fields}",
        "refs/tags",
    )
    tags: list[ReleaseTag] = []
    for raw_record in output.splitlines():
        if not raw_record:
            continue
        record = raw_record.split(b"\0")
        if len(record) != 7:
            raise ExperienceCollectionError("for-each-ref returned an invalid tag record")
        name, object_type, object_oid, peeled_oid, tagger_epoch, tagger_email, creator_epoch = (
            value.decode("utf-8", "replace") for value in record
        )
        annotated = object_type == "tag"
        if annotated:
            target_oid = _git_text(repo, "rev-parse", "--verify", f"refs/tags/{name}^{{commit}}")
            epoch_text = tagger_epoch
            if not epoch_text:
                raise ExperienceCollectionError(f"annotated tag {name!r} has no tagger date")
            normalized_tagger_email = tagger_email.strip().casefold()
            tagger_actor_id = normalized_taggers.get(normalized_tagger_email)
            if tagger_actor_id is None:
                tagger_actor_id = normalized_tagger_digests.get(
                    email_identity_sha256(normalized_tagger_email)
                )
        elif object_type == "commit":
            target_oid = object_oid
            epoch_text = creator_epoch
            tagger_actor_id = None
        else:
            # A tag whose reference cannot peel to a reachable commit is not a
            # release marker for commit-history observations.
            continue
        parsed_target = parse_git_oid(target_oid)
        if parsed_target.algorithm != target.algorithm:
            raise ExperienceCollectionError(f"tag {name!r} uses a different object format")
        try:
            tagged_at = datetime.fromtimestamp(int(epoch_text), timezone.utc)
        except ValueError as exc:
            raise ExperienceCollectionError(f"tag {name!r} has an invalid timestamp") from exc
        tags.append(
            ReleaseTag(
                name=name,
                target_oid=parsed_target.value,
                tagged_at=tagged_at,
                annotated=annotated,
                tagger_actor_id=tagger_actor_id,
            )
        )
    return tuple(sorted(tags, key=lambda row: (row.tagged_at, row.name)))



@dataclass(frozen=True)
class DependencyIntroductions:
    """Which commit first declared which dependency, and how much was readable.

    `introduced` and `removed` are keyed by commit OID and hold only commits
    that changed the declared set. `manifest_commits` and `unparseable` let a
    caller tell coverage from absence: a person with no introductions and a
    manifest that never parsed is not the same as one who introduced nothing.
    """

    introduced: dict[str, frozenset[str]]
    removed: dict[str, frozenset[str]]
    manifest_commits: int
    unparseable: int
    # library name -> the registries whose manifests declared it here. A name
    # found under two registries is recorded under both rather than resolved
    # by guesswork; prevalence lookup reports that as ambiguous instead of
    # picking one. Kept beside the names rather than folded into them so the
    # introduction observation keeps the shape its consumers already read.
    ecosystems: dict[str, frozenset[str]] = field(default_factory=dict)


def _declared_at(repo: Path, revision: str, path: str) -> set[str] | None:
    """Declared names at one revision, or None when the manifest is unreadable."""
    from tep_core.dependency_manifest import ManifestParseError, declared_dependencies

    try:
        body = _git_bytes(repo, "show", f"{revision}:{path}", allowed_returncodes=(0, 128))
    except ExperienceCollectionError:
        return None
    if not body:
        return set()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        return declared_dependencies(PurePosixPath(path).name, text)
    except ManifestParseError:
        return None


def collect_dependency_introductions(
    repo: Path,
    *,
    revision: str = "HEAD",
) -> DependencyIntroductions:
    """Diff each manifest-touching commit against its first parent.

    A dependency is *introduced* by the commit whose manifest names it while
    its first parent's does not. A version bump changes the constraint, not the
    set, so it never registers: choosing a library and maintaining one are
    different acts and only the first is domain evidence.
    """
    from tep_core.dependency_manifest import SUPPORTED_MANIFESTS, ecosystem_for

    repository = repo.resolve()
    pathspecs: list[str] = []
    for name in sorted(SUPPORTED_MANIFESTS):
        pathspecs.extend([f":(icase,glob)**/{name}", f":(icase){name}"])
    listing = _git_text(
        repository,
        "log",
        revision,
        "--no-merges",
        "--name-only",
        "--format=%x1e%H",
        "--",
        *pathspecs,
    )
    introduced: dict[str, frozenset[str]] = {}
    removed: dict[str, frozenset[str]] = {}
    ecosystems: dict[str, set[str]] = {}
    manifest_commits = 0
    unparseable = 0
    for block in listing.split("\x1e"):
        block = block.strip("\n")
        if not block:
            continue
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        oid, paths = lines[0].strip(), lines[1:]
        paths = [p for p in paths if PurePosixPath(p).name.casefold() in SUPPORTED_MANIFESTS]
        if not paths:
            continue
        manifest_commits += 1
        gained: set[str] = set()
        lost: set[str] = set()
        for path in paths:
            child = _declared_at(repository, oid, path)
            if child is None:
                unparseable += 1
                continue
            parent = _declared_at(repository, f"{oid}^", path)
            if parent is None:
                parent = set()
            registry = ecosystem_for(PurePosixPath(path).name)
            new_here = child - parent
            if registry is not None:
                for name in new_here:
                    ecosystems.setdefault(name, set()).add(registry)
            gained |= new_here
            lost |= parent - child
        if gained:
            introduced[oid] = frozenset(gained)
        if lost:
            removed[oid] = frozenset(lost)
    return DependencyIntroductions(
        introduced,
        removed,
        manifest_commits,
        unparseable,
        {name: frozenset(found) for name, found in sorted(ecosystems.items())},
    )

def collect_experience_inputs(
    repo: Path,
    *,
    revision: str = "HEAD",
    sha_to_actor: Mapping[str, str] | None = None,
    bot_actor_ids: Iterable[str] = (),
    tagger_actor_by_email: Mapping[str, str] | None = None,
    tagger_actor_by_email_sha256: Mapping[str, str] | None = None,
    snapshot_actor_ids: Iterable[str] = (),
) -> ExperienceCollection:
    """Collect fixed-revision events without network or identity inference.

    ``repo`` must already expose the intended revision locally.  The supplied
    ``sha_to_actor`` mapping is used verbatim after lowercase OID
    normalization; absent commits stay unresolved.  Repository-size snapshots
    are exact fixed-tree values and are only attached at first/median/last
    contributions for ``snapshot_actor_ids``.
    """

    repository = repo.resolve()
    _assert_complete_repository(repository)
    target = _resolve_target(repository, revision)
    oids = _reachable_oids(repository, target)
    objects = _read_commit_objects(repository, oids)
    changes = _read_changes(repository, objects)
    actor_map = {oid.lower(): actor_id for oid, actor_id in (sha_to_actor or {}).items()}
    bot_ids = set(bot_actor_ids)

    rows = tuple(
        ExperienceCommit(
            oid=commit.oid,
            actor_id=actor_map.get(commit.oid),
            authored_at=commit.authored_at,
            message=commit.message,
            changes=changes[commit.oid],
            parents=commit.parents,
            is_bot=actor_map.get(commit.oid) in bot_ids,
            sequence=sequence,
        )
        for sequence, commit in enumerate(objects)
    )
    snapshot_oids = _snapshot_oids(rows, snapshot_actor_ids)
    sizes = {oid: _repository_size(repository, oid) for oid in sorted(snapshot_oids)}
    if sizes:
        rows = tuple(
            replace(
                row,
                repository_commit_count_after=sizes[row.oid][0],
                repository_file_count_after=sizes[row.oid][1],
                repository_line_count_after=sizes[row.oid][2],
            )
            if row.oid in sizes
            else row
            for row in rows
        )
    tags = _collect_release_tags(
        repository,
        target,
        tagger_actor_by_email or {},
        tagger_actor_by_email_sha256 or {},
    )
    return ExperienceCollection(target_oid=target, commits=rows, release_tags=tags)
