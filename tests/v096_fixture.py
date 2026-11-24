"""A repository whose commit objects carry hand-written signature headers.

The header content is not a valid signature. The 0.9.6 observation counts header
presence only, so a fixture needs the header and nothing else; building the
objects directly keeps the tests free of ssh/gpg tooling and keyrings.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from git_fixture import commit, init_repo

AS_OF = "2026-03-31"
AS_OF_JUNE = "2026-07-01"  # after the alice_bob_repo commits
_SIG = "gpgsig -----BEGIN SSH SIGNATURE-----\n U1NIU0lHAAAAAQ==\n -----END SSH SIGNATURE-----\n"


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
    )
    return done.stdout.strip()


def signed_pattern_repo(
    path: Path, *, total: int = 24, signed_every: int | None = 3
) -> tuple[Path, int]:
    """`total` commits, every `signed_every`-th one carrying a signature header
    (`None`: none of them).

    Returns the repo and the number of signed commits.
    """

    repo = init_repo(path)
    parent: str | None = None
    signed = 0
    for index in range(total):
        (repo / f"mod{index % 4}.py").write_text(f"value = {index}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        tree = _git(repo, "write-tree")
        stamp = f"{1767225600 + index * 86400} +0000"
        lines = [f"tree {tree}"]
        if parent:
            lines.append(f"parent {parent}")
        lines.append(f"author Fixture <fixture@example.com> {stamp}")
        lines.append(f"committer Fixture <fixture@example.com> {stamp}")
        body = "\n".join(lines) + "\n"
        if signed_every is not None and index % signed_every == 0:
            body += _SIG
            signed += 1
        body += f"\nchange {index}\n"
        parent = _git(repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=body)
        _git(repo, "update-ref", "refs/heads/main", parent)
    _git(repo, "reset", "--hard", "-q", "main")
    return repo, signed


def alice_bob_repo(path: Path, *, commits: int = 30) -> Path:
    """Alice and Bob alternate, so an actor report for alice has own commits."""
    repo = init_repo(path)
    for index in range(commits):
        who = "alice" if index % 2 == 0 else "bob"
        commit(
            repo,
            email=f"{who}@example.com",
            date=f"2026-06-{index + 1:02d}",
            message=f"feat: change {index}",
            filename="tests/test_svc.py" if index % 3 == 0 else "src/api/svc.py",
            name=who.title(),
            content=f"line {index}\nline {index} again\n",
        )
    return repo


def consenting_identity(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                'schema_version = "identity-v2"',
                "",
                "[[actors]]",
                'canonical_id = "alice"',
                'emails = ["alice@example.com"]',
                'attribution_state = "claimed"',
                'consent = "recorded-explicit-consent"',
                'authority = "subject-authorization"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def bind_forge_reviews(
    repo: Path, export: Path, *, reviews: int, coverage: str = "complete"
) -> Path:
    """Point `repo` at a public GitHub URL and write a bound export of alice's reviews."""
    _git(repo, "remote", "add", "origin", "https://github.com/acme/v096-fixture.git")
    head = _git(repo, "rev-parse", "HEAD")
    binding = {
        "provider": "github",
        "host": "github.com",
        "project_id": "R_v096_fixture_1",
        "project_path": "acme/v096-fixture",
        "target_oid": {"algorithm": "sha1", "value": head},
        "window": {"start": "2026-06-01T00:00:00Z", "end": "2026-07-01T00:00:00Z"},
        "coverage": {
            "status": coverage,
            "observed": 30 if coverage == "complete" else 20,
            "expected": 30,
            "missing": 0 if coverage == "complete" else 10,
            "unit": "days",
        },
    }
    events = [
        {
            "event_id": f"review-{index}",
            "kind": "pull_request_review",
            "timestamp": f"2026-06-{index + 10:02d}T00:00:00Z",
            "actor_canonical_id": "alice",
            "project_id": binding["project_id"],
            "project_path": binding["project_path"],
            "pr_number": index + 1,
            "commit_sha": head,
        }
        for index in range(reviews)
    ]
    export.write_text(
        json.dumps({"schema_version": "tep-forge-export-v2", "binding": binding, "events": events}),
        encoding="utf-8",
    )
    return export
