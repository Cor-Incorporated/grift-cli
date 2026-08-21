"""Synthetic git repositories for falsification tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.com")
    git(path, "config", "commit.gpgsign", "false")
    return path


def commit(
    repo: Path,
    *,
    email: str,
    date: str,
    message: str,
    filename: str = "file.txt",
    content: str | None = None,
    name: str = "Author",
) -> None:
    target = repo / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        content = message + "\n"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(existing + content, encoding="utf-8")
    git(repo, "add", filename)
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": f"{date}T12:00:00",
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": f"{date}T12:00:00",
    }
    git(repo, "commit", "-m", message, env=env)


def merge_commit(
    repo: Path,
    *,
    email: str,
    date: str,
    message: str = "merge",
    name: str = "Author",
) -> None:
    git(repo, "checkout", "-b", "feature")
    commit(repo, email=email, date=date, message="on-feature", filename="feature.txt", name=name)
    git(repo, "checkout", "main")
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": f"{date}T13:00:00",
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": f"{date}T13:00:00",
    }
    git(repo, "merge", "--no-ff", "-m", message, "feature", env=env)
