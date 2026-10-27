"""v0.9.1: with --as-of, experience, test_cochange and rework stop at the date too.

0.9.0 (#91) cut activity and role_profile at the end of the --as-of day (UTC),
but `experience` (its dependency scan carries no date), `test_cochange` and
`rework` still counted every reachable commit, and the 13-week window of
`test_cochange` was based on HEAD's day. A person who kept working after the
date had that later work in a report that says it describes the work up to it.

The fixture pins the cut itself (M1): the last second of the day is in and the
first second of the next day is out, the day is the UTC day (two commits made
on the morning of 1 September at +09:00 are 31 August in UTC; one made on the
evening of 31 August at -07:00 is 1 September in UTC), the 13-week window
counts back from the observation date and starts on a UTC day too (a commit
made on the morning of 1 June at +09:00 is 31 May in UTC, outside it), and an
actor_cluster subject is cut like an explicit one. Activity names its days on
the same UTC clock (L8).
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

# Own commits up to the end of 2026-08-31 UTC, and after it.
BEFORE, AFTER = 26, 10


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


def _env(when: str) -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_COMMITTER_DATE": when,
    }


def _tag(repo: Path, name: str, when: str) -> None:
    git(repo, "tag", "-a", name, "-m", f"release {name}", env=_env(when))


def _commit(repo: Path, when: str, message: str, *paths: str, text: str | None = None) -> None:
    for name in paths:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(text if text is not None else old + when + "\n", encoding="utf-8")
    env = _env(when)
    git(repo, "add", *paths, env=env)
    git(repo, "commit", "-q", "-m", message, env=env)


def _repo(tmp: Path) -> Path:
    repo = init_repo(tmp / "rest")
    _commit(repo, "2026-05-04T12:00:00+00:00", "feat: start", "requirements.txt", text="requests\n")
    _commit(repo, "2026-05-04T13:00:00+00:00", "feat: app", "src/api/app.py", "tests/test_app.py")
    for day in range(11, 14):  # before the 13-week window counted back from the date
        _commit(repo, f"2026-05-{day}T12:00:00+00:00", f"feat: m{day}", f"src/api/m{day}.py")
    # 2026-06-01 is the window's first day; this is 31 May in UTC.
    _commit(repo, "2026-06-01T08:00:00+09:00", "feat: window edge", "src/api/w.py")
    for day in range(10, 15):  # inside that window, outside one counted back from HEAD
        _commit(repo, f"2026-06-{day}T12:00:00+00:00", f"feat: n{day}", f"src/api/n{day}.py")
    for day in range(1, 13):
        paths = ["src/api/core.py", *(["tests/test_core.py"] if day % 3 == 0 else [])]
        verb = "fix" if day % 4 == 0 else "feat"
        _commit(repo, f"2026-07-{day:02d}T12:00:00+00:00", f"{verb}: core {day}", *paths)
    _tag(repo, "v1.0.0", "2026-07-15T12:00:00+00:00")  # an annotated tag before the date
    # 31 August in UTC, 1 September where they were made.
    _commit(repo, "2026-09-01T07:00:00+09:00", "feat: east one", "src/api/east.py")
    _commit(repo, "2026-09-01T08:00:00+09:00", "feat: east two", "src/api/east.py")
    _commit(repo, "2026-08-31T23:59:59+00:00", "feat: last second", "src/api/edge.py")
    # After the date: the next UTC day, and 31 August where it was made.
    _commit(repo, "2026-09-01T00:00:00+00:00", "feat: next day", "src/api/edge.py")
    _commit(repo, "2026-08-31T18:00:00-07:00", "feat: west evening", "src/api/west.py")
    _commit(repo, "2026-09-02T12:00:00+00:00", "feat: flask", "requirements.txt", text="flask\n")
    for day in range(3, 9):
        paths = ["src/api/core.py", *(["tests/test_core.py"] if day % 2 else [])]
        _commit(repo, f"2026-09-{day:02d}T12:00:00+00:00", f"fix: core late {day}", *paths)
    _commit(repo, "2026-09-20T12:00:00+00:00", 'Revert "feat: core 1"', "src/api/core.py")
    _tag(repo, "v2.0.0", "2026-09-21T12:00:00+00:00")  # and one after it
    return repo


def _identity(tmp: Path) -> Path:
    path = tmp / "identity.toml"
    path.write_text(IDENTITY, encoding="utf-8")
    return path


def _actor(repo: Path, actor: str, *extra: str) -> dict:
    return json.loads(_cli(["actor", actor, str(repo), *extra, "--format", "json"]))


def _facts(report: dict) -> dict:
    activity = report["activity"]
    own = "actor_cluster_commits" if activity["scope"] == "actor_cluster" else "tenant_commits"
    cochange, rework = report["test_cochange"], report["rework"]
    return {
        "range": report["surface_profile"]["sample_size"],
        "activity": activity[own]["value"],
        "active_days": activity["active_days"]["value"],
        "active_days_13w": activity["active_days_13w"]["value"],
        "cochange": cochange["all_time"]["population"],
        "cochange_13w": cochange["last_13w"]["population"],
        "rework": rework["path_retouch_rate"]["population"],
        "reverts": [rework["revert_rate"]["reverts"], rework["revert_rate"]["population"]],
    }


def _experience(report: dict) -> dict:
    metrics = report["experience"]["metrics"]
    introduced = metrics["dependency_introduction"]
    sizes = metrics["repository_size_at_contribution_points"]
    return {
        "cadence": metrics["cadence"]["denominator"],
        "introduced": introduced["values"],
        "manifest_commits": introduced["manifest_commits"],
        "end": report["experience"]["window"]["end"],
        # The size snapshots are taken at the last contribution up to the date.
        "last_size_point": (sizes.get("points") or {}).get("last", {}).get("observed_at"),
        "tags": metrics["annotated_tag_creation"]["numerator"],
        "role": report["role_profile"]["dimensions"]["work_type"]["create"]["denominator"],
    }


# With the cut: 26 own commits up to the date, on 23 UTC days (both east-morning
# commits fall on 31 August UTC, like the last second). The 13-week window starts
# 2026-06-01: the June, July and 31 August commits, 5 + 12 + 3 on 18 days.
CUT = {
    "range": BEFORE,
    "activity": BEFORE,
    "active_days": 1 + 3 + 1 + 5 + 12 + 1,
    "active_days_13w": 5 + 12 + 1,
    "cochange": BEFORE,
    "cochange_13w": 5 + 12 + 3,
    "rework": BEFORE,
    "reverts": [0, BEFORE],
}


def test_experience_cochange_and_rework_stop_at_the_as_of_date(tmp_path: Path) -> None:
    identity = str(_identity(tmp_path))
    report = _actor(_repo(tmp_path), "alice", "--identity", identity, "--as-of", AS_OF)
    assert _facts(report) == CUT, _facts(report)
    assert _experience(report) == {
        "cadence": BEFORE,
        "introduced": ["requests"],  # flask was introduced after the date
        "manifest_commits": 1,
        "end": f"{AS_OF}T23:59:59Z",
        "last_size_point": f"{AS_OF}T23:59:59Z",  # the last-second commit
        "tags": 1,  # v2.0.0 was tagged after the date
        "role": BEFORE,
    }, _experience(report)


def test_experience_ends_at_the_date_even_without_a_commit_at_its_last_second(
    tmp_path: Path,
) -> None:
    """Review M2: the window ends at the date, not at the last commit kept before it."""
    identity = str(_identity(tmp_path))
    report = _actor(_repo(tmp_path), "alice", "--identity", identity, "--as-of", "2026-08-30")
    ends = {
        "experience": report["experience"]["window"]["end"],
        "role_profile": report["role_profile"]["window"]["end"],
        "cadence": report["experience"]["metrics"]["cadence"]["denominator"],
    }
    # The last commit kept is 12 July; the three 31 August (UTC) commits are after it.
    assert ends == {
        "experience": "2026-08-30T23:59:59Z",
        "role_profile": "2026-08-30T23:59:59Z",
        "cadence": BEFORE - 3,
    }, ends


def test_an_actor_cluster_is_cut_like_an_explicit_actor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    directory = json.loads(_cli(["repo", str(repo), "--format", "json"]))["actor_directory"]
    (cluster,) = [row["actor_id"] for row in directory["actors"]]
    report = _actor(repo, cluster, "--as-of", AS_OF)
    assert report["test_cochange"]["analysis_scope"] == "actor_cluster"
    assert _facts(report) == CUT, _facts(report)


def test_without_as_of_the_whole_history_is_counted_as_before(tmp_path: Path) -> None:
    """No --as-of: every reachable commit, local author days, 13 weeks back from HEAD's day."""
    report = _actor(_repo(tmp_path), "alice", "--identity", str(_identity(tmp_path)))
    total = BEFORE + AFTER
    # Local days: 4 May, 11-13 May, 1 June, 10-14 June, 1-12 July, 31 August (last
    # second, west evening), 1 September (east ×2, next day), 2-8 and 20 September.
    # HEAD's day is 20 September, so the 13-week window starts 21 June.
    assert _facts(report) == {
        "range": total,
        "activity": total,
        "active_days": 1 + 3 + 1 + 5 + 12 + 2 + 7 + 1,
        "active_days_13w": 12 + 2 + 7 + 1,
        "cochange": total,
        "cochange_13w": 12 + 3 + 2 + 1 + 6 + 1,
        "rework": total,
        "reverts": [1, total],
    }, _facts(report)
    assert _experience(report) == {
        "cadence": total,
        "introduced": ["flask", "requests"],
        "manifest_commits": 2,
        "end": "2026-09-20T12:00:00Z",
        "last_size_point": "2026-09-20T12:00:00Z",
        "tags": 2,
        "role": total,
    }, _experience(report)


def test_an_as_of_report_and_collection_verify(tmp_path: Path) -> None:
    """verify recomputes experience, test_cochange and rework with the same date."""
    repo, identity = _repo(tmp_path), _identity(tmp_path)
    argv = ["actor", "alice", str(repo), "--identity", str(identity), "--as-of", AS_OF]
    report = tmp_path / "alice.json"
    report.write_text(_cli([*argv, "--format", "json"]), encoding="utf-8")
    verdict = _cli(["verify", str(report), "--repo", str(repo), "--identity", str(identity)])
    assert verdict.startswith("VERIFIED"), verdict
    out = tmp_path / "collection"
    _cli([*argv, "--format", "json", "--out", str(out)])
    card = json.loads((out / "actors" / "alice.json").read_text(encoding="utf-8"))
    assert card["experience"]["metrics"]["cadence"]["denominator"] == BEFORE
    verdict = _cli(["verify", str(out), "--repo", str(repo), "--identity", str(identity)])
    assert verdict.startswith("VERIFIED"), verdict
