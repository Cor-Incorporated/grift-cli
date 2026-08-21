"""Git subprocess helpers. Standard library only."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 120


class GitError(RuntimeError):
    pass


@dataclass
class GitCommit:
    sha: str
    author_email: str
    parents: tuple[str, ...]
    date: str  # YYYY-MM-DD
    subject: str
    files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


def _run_git(repo: Path, args: list[str], timeout: int = _GIT_TIMEOUT_SECONDS) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out") from exc
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def rev_parse(repo: Path, rev: str = "HEAD") -> str:
    return _run_git(repo, ["rev-parse", rev]).strip()


def remote_url(repo: Path, name: str = "origin") -> str | None:
    try:
        url = _run_git(repo, ["remote", "get-url", name]).strip()
    except GitError:
        return None
    return url or None


def repository_identity(repo: Path, *, include_local_path: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": repo.name,
        "remote": remote_url(repo),
    }
    if include_local_path:
        payload["path"] = str(repo.resolve())
    return payload


def read_commits(repo: Path, *, include_files: bool = False) -> list[GitCommit]:
    """Read commit metadata. File names are optional (vendor heuristic)."""
    fmt = "%H%x1f%ae%x1f%P%x1f%ad%x1f%s"
    args = ["log", f"--format={fmt}", "--date=short"]
    if include_files:
        args.append("--name-only")
    raw = _run_git(repo, args)
    return _parse_log(raw, include_files=include_files)


def _parse_log(raw: str, *, include_files: bool) -> list[GitCommit]:
    commits: list[GitCommit] = []
    current: GitCommit | None = None
    files: list[str] = []

    def flush() -> None:
        nonlocal current, files
        if current is None:
            return
        current.files = tuple(files)
        commits.append(current)
        current = None
        files = []

    for line in raw.splitlines():
        if "\x1f" in line:
            flush()
            parts = line.split("\x1f")
            if len(parts) != 5:
                continue
            sha, email, parents, date, subject = parts
            current = GitCommit(
                sha=sha,
                author_email=email,
                parents=tuple(p for p in parents.split() if p),
                date=date,
                subject=subject,
            )
            files = []
            continue
        if include_files and current is not None and line.strip():
            files.append(line.strip())
    flush()
    return commits
