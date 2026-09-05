"""Git subprocess helpers. Standard library only."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_GIT_TIMEOUT_SECONDS = 120
_SCP_REMOTE_RE = re.compile(r"^(?:(?P<user>[^@/:]+)@)?(?P<host>\[[^]]+\]|[^/:]+):(?P<path>.+)$")
_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]", re.ASCII)
_FULL_GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


class GitError(RuntimeError):
    pass


@dataclass
class GitCommit:
    sha: str
    author_email: str
    parents: tuple[str, ...]
    date: str  # YYYY-MM-DD from %ad --date=short (v0.5.9 compatible)
    subject: str
    files: tuple[str, ...] = field(default_factory=tuple)
    author_iso: str = ""  # Git %aI; never overwrite `date`
    author_name: str = ""
    numstat: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


def _run_git(repo: Path, args: list[str], timeout: int = _GIT_TIMEOUT_SECONDS) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
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


def normalize_remote(url: str | None) -> str | None:
    """Return a credential-free remote identity, never a filesystem path.

    This compatibility helper keeps the historic ``host/path`` shape for
    ordinary HTTPS and SCP remotes.  Unlike the live Forge parser it is
    intentionally forgiving: query/fragment/userinfo are dropped so an
    offline report cannot disclose them.  Explicit public fetch remains
    fail-closed in ``parse_forge_locator``.
    """

    if not url:
        return None
    text = url.strip()
    if not text or text.startswith(("/", "./", "../", "~/", "\\")):
        return None
    if _WINDOWS_PATH_RE.match(text):
        return None

    host: str | None = None
    port: int | None = None
    path = ""
    if "://" in text:
        try:
            parsed = urlsplit(text)
            port = parsed.port
        except ValueError:
            return None
        if parsed.scheme.casefold() == "file" or not parsed.hostname:
            return None
        if parsed.scheme.casefold() not in {"http", "https", "ssh", "git", "git+ssh"}:
            return None
        host = parsed.hostname.casefold().rstrip(".")
        path = parsed.path
    else:
        # Remove components which must never become part of an offline
        # repository identity before parsing SCP-style syntax.
        without_suffix = text.split("#", 1)[0].split("?", 1)[0]
        authority = without_suffix.split("/", 1)[0]
        bare_port = re.fullmatch(r"(?:\[[^]]+\]|[^:]+):[0-9]+", authority)
        match = None
        if bare_port and "/" in without_suffix:
            try:
                parsed = urlsplit("//" + without_suffix)
                port = parsed.port
            except ValueError:
                return None
            if not parsed.hostname:
                return None
            host = parsed.hostname.casefold().rstrip(".")
            path = parsed.path
        else:
            match = _SCP_REMOTE_RE.fullmatch(without_suffix)
        if host is not None:
            pass
        elif match:
            raw_host = match.group("host")
            host = raw_host.strip("[]").casefold().rstrip(".")
            path = match.group("path")
        else:
            pieces = without_suffix.split("/", 1)
            if len(pieces) != 2 or "." not in pieces[0]:
                return None
            host = pieces[0].casefold().rstrip(".")
            path = pieces[1]

    if not host or any(character.isspace() for character in host):
        return None
    clean_path = path.strip("/")
    if clean_path.endswith(".git"):
        clean_path = clean_path[:-4]
    parts = clean_path.split("/") if clean_path else []
    if any(part in {"", ".", ".."} for part in parts):
        return None
    rendered_host = f"[{host}]" if ":" in host else host
    if port is not None:
        rendered_host = f"{rendered_host}:{port}"
    return "/".join((rendered_host, *parts))


def raw_remote_url(repo: Path, name: str = "origin") -> str | None:
    try:
        return _run_git(repo, ["remote", "get-url", name]).strip() or None
    except GitError:
        return None


def remote_url(repo: Path, name: str = "origin") -> str | None:
    return normalize_remote(raw_remote_url(repo, name))


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
    fmt = "%H%x1f%ae%x1f%P%x1f%ad%x1f%s%x1f%aI%x1f%an"
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
            if len(parts) not in {5, 6, 7}:
                continue
            sha, email, parents, date, subject = parts[:5]
            author_iso = parts[5] if len(parts) >= 6 else ""
            author_name = parts[6] if len(parts) >= 7 else ""
            current = GitCommit(
                sha=sha,
                author_email=email,
                parents=tuple(p for p in parents.split() if p),
                date=date,
                subject=subject,
                author_iso=author_iso,
                author_name=author_name,
            )
            files = []
            continue
        if include_files and current is not None and line.strip():
            files.append(line.strip())
    flush()
    return commits


def coauthor_shas(repo: Path) -> set[str]:
    try:
        raw = _run_git(repo, ["log", "--grep=Co-authored-by", "--format=%H", "-i"])
    except GitError:
        return set()
    return {
        line.strip()
        for line in raw.splitlines()
        if _FULL_GIT_OID_RE.fullmatch(line.strip()) is not None
    }


def read_numstat(repo: Path) -> dict[str, tuple[tuple[str, int, int], ...]]:
    raw = _run_git(repo, ["log", "--format=%H", "--numstat"])
    table: dict[str, tuple[tuple[str, int, int], ...]] = {}
    sha = ""
    rows: list[tuple[str, int, int]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if "\t" not in line and _FULL_GIT_OID_RE.fullmatch(line.strip()) is not None:
            if sha:
                table[sha] = tuple(rows)
            sha = line.strip()
            rows = []
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not sha:
            continue
        added, deleted, path = parts
        if added == "-" or deleted == "-":
            continue
        try:
            rows.append((path, int(added), int(deleted)))
        except ValueError:
            continue
    if sha:
        table[sha] = tuple(rows)
    return table


def apply_numstat(
    commits: list[GitCommit], table: dict[str, tuple[tuple[str, int, int], ...]]
) -> None:
    for commit in commits:
        commit.numstat = table.get(commit.sha, ())
