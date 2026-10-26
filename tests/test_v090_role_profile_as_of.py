"""v0.9.0: role_profile and activity are counted up to the --as-of date.

The report's other blocks (surface, verification, rhythm) are cut at the
observation date, but `activity` and `role_profile` were collected over every
reachable commit. A person who kept working after the date got their later
commits, merges and release tags counted into a report that says it describes
the work up to that date.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path

from git_fixture import git, init_repo

from tep_cli.__main__ import main

AS_OF = "2026-08-31"
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


def _env(name: str, email: str, when: str) -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": when,
    }


def _commit(repo: Path, filename: str, when: str, *, name: str = "Alice") -> None:
    email = f"{name.lower()}@example.com"
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((path.read_text(encoding="utf-8") if path.exists() else "") + when + "\n")
    env = _env(name, email, when)
    git(repo, "add", filename, env=env)
    git(repo, "commit", "-q", "-m", f"feat: {filename} {when}", env=env)


def _repo(tmp: Path) -> Path:
    """40 own commits up to the date, then 20 more, a merge and a release tag after it."""
    repo = init_repo(tmp / "later")
    for index in range(40):
        _commit(repo, f"src/api/m{index % 4}.py", f"2026-07-{index % 28 + 1:02d}T12:00:00+00:00")
    for index in range(20):
        _commit(repo, f"web/page{index}.tsx", f"2026-09-{index + 1:02d}T12:00:00+00:00")
    git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "src/bob.py", "2026-09-22T12:00:00+00:00", name="Bob")
    git(repo, "checkout", "-q", "main")
    merge = _env("Alice", "alice@example.com", "2026-09-23T12:00:00+00:00")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature", "feature", env=merge)
    tag = _env("Alice", "alice@example.com", "2026-09-24T12:00:00+00:00")
    git(repo, "tag", "-a", "v2.0.0", "-m", "release v2.0.0", env=tag)
    return repo


def _actor_json(repo: Path, tmp: Path, *extra: str) -> dict:
    identity = tmp / "identity.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    argv = ["actor", "alice", str(repo), "--identity", str(identity), *extra, "--format", "json"]
    return json.loads(_cli(argv))


def _facts(report: dict) -> dict:
    role = report["role_profile"]
    process = role["dimensions"]["process_position"]
    return {
        "range_total": report["surface_profile"]["sample_size"],
        "activity_commits": report["activity"]["tenant_commits"]["value"],
        "role_denominator": role["dimensions"]["work_type"]["create"]["denominator"],
        "merges": process["integrator"].get("numerator"),
        "releases": process["release"].get("numerator"),
        "role_window_end": str(role["window"]["end"])[:10],
    }


def test_role_profile_and_activity_stop_at_the_as_of_date(tmp_path: Path) -> None:
    facts = _facts(_actor_json(_repo(tmp_path), tmp_path, "--as-of", AS_OF))
    assert facts == {
        "range_total": 40,
        "activity_commits": 40,
        "role_denominator": 40,
        "merges": 0,
        "releases": 0,
        "role_window_end": AS_OF,
    }, facts


def test_without_as_of_the_whole_history_is_still_counted(tmp_path: Path) -> None:
    facts = _facts(_actor_json(_repo(tmp_path), tmp_path))
    assert (facts["activity_commits"], facts["role_denominator"]) == (60, 60), facts
    assert (facts["merges"], facts["releases"]) == (1, 1), facts


def test_a_collection_written_with_as_of_verifies(tmp_path: Path) -> None:
    """Review H1: verify recomputes the role profile with the date the card was cut at."""
    repo = _repo(tmp_path)
    identity = tmp_path / "identity.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    out = tmp_path / "collection"
    argv = ["actor", "alice", str(repo), "--identity", str(identity), "--as-of", AS_OF]
    _cli([*argv, "--format", "json", "--out", str(out)])
    card = json.loads((out / "actors" / "alice.json").read_text(encoding="utf-8"))
    assert str(card["role_profile"]["window"]["end"])[:10] == AS_OF
    verdict = _cli(["verify", str(out), "--repo", str(repo), "--identity", str(identity)])
    assert verdict.startswith("VERIFIED"), verdict
