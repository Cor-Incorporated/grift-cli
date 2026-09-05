"""Materialize one already-local Git revision without touching the caller's checkout."""

from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class RevisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FixedRevision:
    source_repo: Path
    worktree: Path
    oid: dict[str, str]
    shallow: bool
    promisor: bool

    @property
    def completeness_proven(self) -> bool:
        return not self.shallow and not self.promisor


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RevisionError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def commit_history_complete(repo: Path) -> bool:
    """Whether every reachable commit is present locally.

    False only for a shallow clone, which truncates the commit graph itself.
    A partial (promisor) clone is deliberately NOT counted as incomplete here:
    `--filter=blob:none` and `--filter=tree:0` both fetch every commit and omit
    only file content, so commit counts, dates and authors stay exact. Degrading
    those would be the opposite error — refusing to report what was measured.
    Missing blobs surface separately, as absent commit paths.

    A repository we cannot interrogate is treated as incomplete: the honest
    answer to "is anything missing?" when the question itself failed is
    "unproven", never "no".
    """
    try:
        shallow, _promisor = _repository_shape(repo)
    except RevisionError:
        return False
    return not shallow


def _repository_shape(repo: Path) -> tuple[bool, bool]:
    shallow = _git(repo, "rev-parse", "--is-shallow-repository").lower() == "true"
    result = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            "config",
            "--get-regexp",
            r"^remote\..*\.promisor$",
        ],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
        text=True,
    )
    promisor = any(
        line.rsplit(maxsplit=1)[-1].lower() == "true"
        for line in result.stdout.splitlines()
        if line.strip()
    )
    return shallow, promisor


def describe_revision(repo: Path, rev: str | None = None) -> FixedRevision:
    """Resolve an already-local commit and its repository completeness.

    This performs no checkout and every Git invocation inherits
    ``GIT_NO_LAZY_FETCH=1``.  Callers can therefore record the same generic OID
    and shallow/promisor state during both analysis and verification.
    """

    source = repo.resolve()
    target = rev or "HEAD"
    oid_value = _git(source, "rev-parse", "--verify", f"{target}^{{commit}}")
    algorithm = _git(source, "rev-parse", "--show-object-format")
    if algorithm not in {"sha1", "sha256"}:
        raise RevisionError(f"unsupported Git object format: {algorithm}")
    shallow, promisor = _repository_shape(source)
    return FixedRevision(
        source_repo=source,
        worktree=source,
        oid={"algorithm": algorithm, "value": oid_value},
        shallow=shallow,
        promisor=promisor,
    )


def _materialize_described_revision(described: FixedRevision) -> FixedRevision:
    """Create a detached checkout for one already-resolved commit."""

    source = described.source_repo
    oid_value = described.oid["value"]
    common = Path(_git(source, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    scratch = common / "grift-revisions"
    scratch.mkdir(parents=True, exist_ok=True)
    materialized = Path(tempfile.mkdtemp(prefix=f"{oid_value[:12]}-", dir=scratch))
    try:
        _git(source, "worktree", "add", "--detach", str(materialized), oid_value)
    except Exception:
        try:
            materialized.rmdir()
        except OSError:
            pass
        try:
            scratch.rmdir()
        except OSError:
            pass
        raise
    return FixedRevision(
        source_repo=source,
        worktree=materialized,
        oid=described.oid,
        shallow=described.shallow,
        promisor=described.promisor,
    )


def materialize_fixed_revision(repo: Path, rev: str) -> FixedRevision:
    """Materialize an explicit revision for callers with manual lifetimes.

    Unlike the compatibility behavior of :func:`fixed_revision_worktree`, this
    function never reuses the caller's checkout, including when ``rev`` is the
    current HEAD.  Verification uses this contract so dirty tracked files and
    untracked discovery inputs cannot affect recomputation of a recorded SHA.
    """

    return _materialize_described_revision(describe_revision(repo, rev))


def remove_fixed_revision_worktree(source_repo: Path, worktree: Path) -> None:
    """Remove a detached checkout created by this module, without fetching."""

    if source_repo.resolve() == worktree.resolve():
        return
    subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(source_repo),
            "worktree",
            "remove",
            "--force",
            str(worktree),
        ],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
        text=True,
    )
    try:
        worktree.rmdir()
    except OSError:
        pass
    try:
        worktree.parent.rmdir()
    except OSError:
        pass


@contextmanager
def fixed_revision_worktree(repo: Path, rev: str | None = None) -> Iterator[FixedRevision]:
    """Yield a checkout whose HEAD is the resolved commit.

    The commit must already exist locally. ``GIT_NO_LAZY_FETCH=1`` is set on
    every Git subprocess, so a promisor clone cannot silently fetch objects and
    then be reported as an offline-complete observation.
    """

    described = describe_revision(repo, rev)
    source = described.source_repo
    oid_value = described.oid["value"]
    shallow, promisor = described.shallow, described.promisor
    head = _git(source, "rev-parse", "--verify", "HEAD^{commit}")
    # Git itself reports ``sha1`` / ``sha256``.  Preserve those canonical
    # spellings across revision, attribution, forge evidence, and schemas so a
    # target OID never needs an ambiguous presentation-layer translation.
    fixed = described.oid
    # An explicit revision is a fixed-tree contract even when it happens to be
    # the checkout's current HEAD.  Reusing the caller's worktree in that case
    # would let tracked edits and untracked framework/test files affect a
    # supposedly immutable report.  The implicit (rev=None) compatibility path
    # may still use the current checkout.
    if rev is None and head == oid_value:
        yield FixedRevision(source, source, fixed, shallow, promisor)
        return

    materialized = _materialize_described_revision(described)
    try:
        yield FixedRevision(source, materialized.worktree, fixed, shallow, promisor)
    finally:
        remove_fixed_revision_worktree(source, materialized.worktree)
