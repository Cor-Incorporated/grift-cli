"""v0.9.0: a name-based cluster never takes a declared identity's id.

An identity declared for alice@example.com with no commits of its own left its
canonical id `alice` free, so another person whose author name is also "Alice"
(a different email) got the name slug `alice` as their cluster id. The consented
role profile counts commits by actor id, so it counted that other person's 25
commits as alice's.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path

from git_fixture import git, init_repo

from tep_cli.__main__ import main

IDENTITY = """schema_version = "identity-v2"

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "claimed"
consent = "recorded-explicit-consent"
authority = "subject-authorization"
"""


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


def _commit(repo: Path, when: str, index: int) -> None:
    path = repo / "src" / "a.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((path.read_text(encoding="utf-8") if path.exists() else "") + f"{index}\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice.other@example.org",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice.other@example.org",
        "GIT_COMMITTER_DATE": when,
    }
    git(repo, "add", "src/a.py", env=env)
    git(repo, "commit", "-q", "-m", f"feat: a {index}", env=env)


def test_a_namesake_with_another_email_is_not_counted_as_the_declared_actor(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "namesake")
    for index in range(25):
        _commit(repo, f"2026-06-{index + 1:02d}T12:00:00+00:00", index)
    identity = tmp_path / "identity.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    argv = ["actor", "alice", str(repo), "--identity", str(identity), "--as-of", "2026-08-31"]
    report = json.loads(_cli([*argv, "--format", "json"]))
    work = ((report["role_profile"].get("dimensions") or {}).get("work_type") or {}).get("create")
    facts = {
        "own_commits": report["activity"]["tenant_commits"]["value"],
        "role_denominator": (work or {}).get("denominator"),
    }
    assert facts["own_commits"] == 0, facts
    assert facts["role_denominator"] in (None, 0), facts
