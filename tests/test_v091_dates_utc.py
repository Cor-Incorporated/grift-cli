"""v0.9.1: one clock for dates at the day boundary (UTC), and no dropped commits.

0.9.0 (#90) took the observation date from HEAD's UTC day. Three places still
read a different day, or lost a commit:

- M4: the event window of a bound forge / tracker export was its timestamp cut
  to `[:10]`, the day on the export's own clock. The binding check compares the
  UTC day, so an export written west of UTC could not be given any
  `--event-window`, and its window never lined up with the Git window.
- L7: the v2 report carried the v1 context profile, which reads the author's
  local day; and a subject holding 0x1f made `git log` parsing drop the commit.

M3 (an ancestor authored after HEAD falls outside the range) moved to 0.9.2:
ending at the latest author day let one future-dated commit, a bot's included,
move the whole window. The guards below keep the end at HEAD's UTC day.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
from dataclasses import astuple
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from git_fixture import git, init_repo

from tep_cli.__main__ import main
from tep_core.gitutil import GitError, _parse_log, read_commits

_ORIGIN = "https://github.com/acme/source-bound.git"


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _commit(
    repo: Path,
    when: str,
    index: int,
    *,
    subject: str | None = None,
    who: tuple[str, str] = ("Alice", "alice@example.com"),
    path: str = "src/api/svc.py",
) -> None:
    name, email = who
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(old + f"# {index}\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": when,
    }
    git(repo, "add", path, env=env)
    git(repo, "commit", "-q", "-m", subject or f"feat: svc {index}", env=env)


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


# --- M4: the event window is read in UTC days ---------------------------------

# 2026-02-02 00:00 UTC to 2026-08-01 00:00 UTC, written on New York's clock.
# On that clock the days are 2026-02-01 and 2026-07-31.
_WEST_WINDOW = {"start": "2026-02-01T19:00:00-05:00", "end": "2026-07-31T20:00:00-04:00"}
_UTC_DAYS = ("2026-02-02", "2026-08-01")


def _bound_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    _commit(repo, "2026-07-01T12:00:00+00:00", 0)
    # HEAD's UTC day is 2026-08-01, so the Git window is 2026-02-02..2026-08-01:
    # the same UTC days as the export's window.
    _commit(repo, "2026-08-01T12:00:00+00:00", 1)
    git(repo, "remote", "add", "origin", _ORIGIN)
    return repo


def _binding(repo: Path) -> dict[str, Any]:
    return {
        "provider": "github",
        "host": "github.com",
        "project_id": "R_source_bound_1",
        "project_path": "acme/source-bound",
        "target_oid": {"algorithm": "sha1", "value": _head(repo)},
        "window": dict(_WEST_WINDOW),
        "coverage": {
            "status": "complete",
            "observed": 180,
            "expected": 180,
            "missing": 0,
            "unit": "days",
        },
    }


def _event(repo: Path, kind: str) -> dict[str, Any]:
    common = {
        "event_id": f"{kind}-1",
        "timestamp": "2026-07-10T00:00:00Z",
        "actor_canonical_id": "alice",
        "project_id": "R_source_bound_1",
        "project_path": "acme/source-bound",
        "commit_sha": _head(repo),
    }
    if kind == "forge":
        return {**common, "kind": "pull_request_opened", "pr_number": 7}
    return {
        **common,
        "kind": "issue_opened",
        "record_type": "issue",
        "record_id": "issue-7",
        "state": "open",
        "previous_state": None,
        "previous_event_id": None,
        "linked_event_id": None,
        "duration_seconds": None,
        "issue_number": 7,
    }


def _export(tmp_path: Path, repo: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": f"tep-{kind}-export-v2",
                "binding": _binding(repo),
                "events": [_event(repo, kind)],
            }
        ),
        encoding="utf-8",
    )
    return path


def _days(window: dict[str, Any]) -> tuple[Any, Any]:
    return window.get("start"), window.get("end")


def test_a_forge_window_written_west_of_utc_is_read_in_utc_days(tmp_path: Path) -> None:
    repo = _bound_repo(tmp_path)
    export = _export(tmp_path, repo, "forge")
    code, out, err = _run(["repo", str(repo), "--forge-export", str(export), "--format", "json"])
    assert code == 0, err
    coverage = json.loads(out)["input_coverage"]
    facts = {
        "event_window": _days(coverage["event_window"]),
        "git_window": _days(coverage["git_window"]),
        "alignment": coverage["window_alignment"].get("kind"),
    }
    assert facts["event_window"] == _UTC_DAYS, facts
    assert facts["git_window"] == _UTC_DAYS, facts
    assert facts["alignment"] == "observed", facts


def test_the_utc_days_the_binding_check_accepts_are_accepted_as_the_event_window(
    tmp_path: Path,
) -> None:
    """The binding check compares UTC days; the window block compared the export's own days.

    No --event-window satisfied both: the UTC days failed the window block, and
    the export's own days failed the binding check.
    """
    repo = _bound_repo(tmp_path)
    export = _export(tmp_path, repo, "forge")
    argv = ["repo", str(repo), "--forge-export", str(export), "--format", "json"]
    code, out, err = _run([*argv, "--event-window", *_UTC_DAYS])
    assert code == 0, err
    assert _days(json.loads(out)["input_coverage"]["event_window"]) == _UTC_DAYS
    code, _out, err = _run([*argv, "--event-window", "2026-02-01", "2026-07-31"])
    assert code == 2 and "window" in err, err


def test_a_tracker_window_written_west_of_utc_is_read_in_utc_days(tmp_path: Path) -> None:
    repo = _bound_repo(tmp_path)
    export = _export(tmp_path, repo, "tracker")
    code, out, err = _run(["repo", str(repo), "--tracker-export", str(export), "--format", "json"])
    assert code == 0, err
    coverage = json.loads(out)["input_coverage"]
    facts = {
        "tracker_window": _days(coverage["tracker_window"]),
        "tracker_unit": coverage["tracker_window"].get("unit"),
        "event_window": _days(coverage["event_window"]),
    }
    assert facts["tracker_window"] == _UTC_DAYS, facts
    assert facts["tracker_unit"] == "utc_date_range", facts
    assert facts["event_window"] == _UTC_DAYS, facts


# --- M3 is 0.9.2: a later-dated commit does not move the range ---------------


def _later_ancestor_repo(
    tmp_path: Path, ancestor: str, who: tuple[str, str] = ("Alice", "alice@example.com")
) -> Path:
    repo = init_repo(tmp_path / "later")
    for index in range(22):
        _commit(repo, f"2026-08-{index + 1:02d}T12:00:00+00:00", index)
    _commit(repo, ancestor, 22, who=who)  # reachable from HEAD, authored after it
    _commit(repo, "2026-09-01T12:00:00+00:00", 23)  # HEAD keeps an older author date
    return repo


def _range_facts(report: dict[str, Any]) -> dict[str, Any]:
    context = report["context_profile"]
    return {
        "observation_date": report["provenance"]["observation_date"],
        "git_window_end": report["input_coverage"]["git_window"]["end"],
        "rhythm_in_window": report["change_rhythm"].get("sample_size"),
        "repo_age_days": context["repo_age_days"]["value"],
        "lifecycle_stage": context["lifecycle_stage"]["value"],
    }


_HEAD_RANGE = {
    "observation_date": "2026-09-01",
    "git_window_end": "2026-09-01",
    "rhythm_in_window": 23,
    "repo_age_days": 31,
    "lifecycle_stage": "active",
}


def test_a_far_future_ancestor_does_not_move_the_observation_date(tmp_path: Path) -> None:
    repo = _later_ancestor_repo(tmp_path, "2031-01-01T00:00:00+00:00")
    code, out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 0, err
    facts = _range_facts(json.loads(out))
    assert facts == _HEAD_RANGE, facts


def test_a_future_dated_bot_commit_does_not_move_the_observation_date(tmp_path: Path) -> None:
    bot = ("ci-runner[bot]", "ci-runner[bot]@example.com")
    repo = _later_ancestor_repo(tmp_path, "2031-01-01T00:00:00+00:00", who=bot)
    code, out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 0, err
    facts = _range_facts(json.loads(out))
    assert facts == _HEAD_RANGE, facts


def test_an_explicit_as_of_still_cuts_the_later_commit(tmp_path: Path) -> None:
    repo = _later_ancestor_repo(tmp_path, "2026-09-10T12:00:00+00:00")
    code, out, err = _run(["repo", str(repo), "--as-of", "2026-09-01", "--format", "json"])
    assert code == 0, err
    report = json.loads(out)
    facts = {
        "surface": report["surface_profile"].get("sample_size"),
        "observation_date": report["provenance"]["observation_date"],
        "window_basis": report["provenance"]["window_basis"],
    }
    assert facts == {
        "surface": 23,
        "observation_date": "2026-09-01",
        "window_basis": "explicit_as_of",
    }, facts


# --- L7: the v2 context profile, the label, and 0x1f in `git log` ----------------


def _west_evening_head(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "west")
    for index in range(3):
        _commit(repo, f"2026-08-{index + 1:02d}T12:00:00+00:00", index)
    _commit(repo, "2026-08-28T20:00:00-08:00", 3)  # HEAD: 2026-08-29 04:00 UTC
    return repo


def test_the_v2_context_profile_reads_the_same_utc_day_as_the_observation_date(
    tmp_path: Path,
) -> None:
    repo = _west_evening_head(tmp_path)
    code, out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 0, err
    report = json.loads(out)
    context = report["context_profile"]
    facts = {
        "observation_date": report["provenance"]["observation_date"],
        "last_commit": context["scale"]["last_commit"]["value"],
        "first_commit": context["scale"]["first_commit"]["value"],
        "repo_age_days": context["repo_age_days"]["value"],
    }
    assert facts == {
        "observation_date": "2026-08-29",
        "last_commit": "2026-08-29",
        "first_commit": "2026-08-01",
        "repo_age_days": 28,
    }, facts


def test_report_v1_keeps_the_author_local_day(tmp_path: Path) -> None:
    """report-v1 counts activity on the author's local day; its context profile stays with it."""
    repo = _west_evening_head(tmp_path)
    code, out, err = _run(["analyze", str(repo), "--format", "json"])
    assert code == 0, err
    context = json.loads(out)["context_profile"]
    assert context["scale"]["last_commit"]["value"] == "2026-08-28"


def test_the_markdown_says_the_observation_date_is_a_utc_day(tmp_path: Path) -> None:
    repo = _west_evening_head(tmp_path)
    code, out, err = _run(["repo", str(repo), "--format", "md"])
    assert code == 0, err
    line = next(item for item in out.splitlines() if item.startswith("- 観測日:"))
    assert line.startswith("- 観測日: 2026-08-29（UTC の日付。窓の基準=legacy_head_date。"), line


def _context_end(report: dict[str, Any]) -> str:
    context = report["context_profile"]
    first = date.fromisoformat(context["scale"]["first_commit"]["value"])
    return (first + timedelta(days=context["repo_age_days"]["value"])).isoformat()


def test_the_v2_context_ends_on_the_day_the_report_range_ends(tmp_path: Path) -> None:
    """M1: the context takes the report's end day; it does not work out one of its own."""
    ends = {}
    for name, repo in (
        ("west_evening_head", _west_evening_head(tmp_path / "a")),
        ("far_future_ancestor", _later_ancestor_repo(tmp_path / "b", "2031-01-01T00:00:00Z")),
    ):
        code, out, err = _run(["repo", str(repo), "--format", "json"])
        assert code == 0, err
        report = json.loads(out)
        ends[name] = (report["provenance"]["observation_date"], _context_end(report))
    assert all(left == right for left, right in ends.values()), ends


def test_the_v2_context_classifies_a_fork_like_report_v1(tmp_path: Path) -> None:
    """M2: without --vendor-scan v1 classifies before reading paths; so does the v2 context.

    With paths, a vendor-only commit of a fork became `generated_or_vendor` (a
    human commit) in the context, against `inherited_upstream` in the origin
    block of the same report.
    """
    repo = init_repo(tmp_path / "fork")
    _commit(repo, "2026-08-01T12:00:00+00:00", 0)
    for index in range(1, 4):
        _commit(repo, f"2026-08-0{index + 1}T12:00:00+00:00", index, path="vendor/lib.js")
    contexts = {}
    for command in ("analyze", "repo"):
        code, out, err = _run([command, str(repo), "--fork", "--format", "json"])
        assert code == 0, (command, err)
        context = json.loads(out)["context_profile"]
        human = ((context.get("scale") or {}).get("human_commits") or {}).get("value")
        contexts[command] = (context.get("kind"), context.get("reason"), human)
    assert contexts["repo"] == contexts["analyze"], contexts


def test_the_v2_context_counts_days_and_years_on_the_utc_day(tmp_path: Path) -> None:
    """Active days and the per-year turnover read the UTC day in v2, the local day in v1."""
    repo = init_repo(tmp_path / "days")
    bob = ("Bob", "bob@example.com")
    _commit(repo, "2026-01-01T08:00:00+09:00", 0, who=bob)  # 2025-12-31 23:00 UTC
    _commit(repo, "2026-08-01T12:00:00+00:00", 1)
    _commit(repo, "2026-08-02T08:00:00+09:00", 2)  # HEAD: 2026-08-01 23:00 UTC
    facts = {}
    for command in ("analyze", "repo"):
        code, out, err = _run([command, str(repo), "--format", "json"])
        assert code == 0, (command, err)
        context = json.loads(out)["context_profile"]
        facts[command] = {
            "active_days_180d": context["active_days_180d"]["value"],
            "actor_turnover": context["actor_turnover"]["value"],
        }
    assert facts["repo"] == {
        "active_days_180d": 1,
        "actor_turnover": {
            "2025": {"joined": 1, "last_active": 1},
            "2026": {"joined": 1, "last_active": 1},
        },
    }, facts
    assert facts["analyze"] == {
        "active_days_180d": 2,
        "actor_turnover": {"2026": {"joined": 2, "last_active": 2}},
    }, facts


def test_git_log_output_that_does_not_split_into_commits_stops(tmp_path: Path) -> None:
    raw = "\x00" + "\x00".join(["a" * 40, "x@example.com", "", "2026-08-01", "s", "", "A", "\n"])
    assert len(_parse_log(raw, include_files=True)) == 1
    try:
        _parse_log(raw + "\x00stray", include_files=True)
    except GitError as exc:
        assert "observed 9 fields, 1 left over" in str(exc), str(exc)
    else:
        raise AssertionError("a stray field was read as part of a commit")


def _ssh_signed_repo(tmp_path: Path) -> Path:
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        pytest.skip("ssh-keygen is not available to sign a commit")
    key = tmp_path / "signing_key"
    subprocess.run(
        [keygen, "-q", "-t", "ed25519", "-N", "", "-C", "fixture@example.com", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    repo = init_repo(tmp_path / "signed")
    _commit(repo, "2026-08-01T12:00:00+00:00", 0)
    git(repo, "config", "gpg.format", "ssh")
    git(repo, "config", "user.signingkey", str(key))
    git(repo, "config", "commit.gpgsign", "true")
    # A signed commit in the middle: its check printed after HEAD's paths.
    _commit(repo, "2026-08-02T12:00:00+00:00", 1)
    _commit(repo, "2026-08-03T12:00:00+00:00", 2)  # a signed HEAD: printed first
    return repo


def test_a_shown_signature_is_not_read_as_a_commit_or_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`log.showSignature=true` prints each signature check into `git log` stdout.

    Before 0.9.1 those lines became file names of the previous commit; with the
    NUL-delimited reader they stopped the run. grift turns the setting off.
    """
    repo = _ssh_signed_repo(tmp_path)
    plain = [astuple(item) for item in read_commits(repo, include_files=True)]
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "log.showSignature")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    shown = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%H"], capture_output=True, text=True
    ).stdout.split("\n")
    assert len([line for line in shown if line.strip()]) > 3, shown  # the setting is live
    signed = [astuple(item) for item in read_commits(repo, include_files=True)]
    assert signed == plain, {"plain": plain, "with_show_signature": signed}
    code, _out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 0, err


def test_a_subject_holding_a_separator_byte_keeps_its_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "sep")
    _commit(repo, "2026-08-01T12:00:00+00:00", 0)
    _commit(repo, "2026-08-02T12:00:00+00:00", 1, subject="feat: unit\x1fsep")
    _commit(repo, "2026-08-03T12:00:00+00:00", 2, subject="feat: line sep")
    _commit(repo, "2026-08-04T12:00:00+00:00", 3)
    commits = read_commits(repo, include_files=True)
    facts = {
        "made": 4,
        "read": len(commits),
        "subjects": [item.subject for item in commits],
        "author_iso": [item.author_iso for item in commits],
        "names": [item.author_name for item in commits],
        "files": [item.files for item in commits],
    }
    assert facts["read"] == facts["made"], facts
    assert facts["subjects"][1:3] == ["feat: line sep", "feat: unit\x1fsep"], facts
    assert all(facts["author_iso"]), facts
    assert facts["names"] == ["Alice"] * 4, facts
    assert facts["files"] == [("src/api/svc.py",)] * 4, facts
