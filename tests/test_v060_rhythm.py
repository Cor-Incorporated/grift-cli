"""Change-rhythm calculations from author timestamps."""

from __future__ import annotations

from tep_core.gitutil import GitCommit
from tep_core.rhythm import change_rhythm, ordered_commits
from tep_core.v2_constants import RHYTHM_LIMITATION


def _c(sha: str, iso: str) -> GitCommit:
    day = iso[:10]
    return GitCommit(
        sha=sha,
        author_email="a@example.com",
        parents=("p",),
        date=day,
        subject="feat",
        author_iso=iso,
    )


def test_gap_median_p90_burst_long_gap() -> None:
    # 21 commits, 1 day apart except one 40-day gap and a 1-day burst cluster
    commits = []
    for index in range(20):
        if index < 15:
            iso = f"2026-01-{1 + index:02d}T12:00:00Z"
        elif index == 15:
            iso = "2026-02-20T12:00:00Z"  # >= 30d after Jan 15
        else:
            iso = f"2026-02-{20 + (index - 15):02d}T12:00:00Z"
        commits.append(_c(f"{index:040d}", iso))
    profile = change_rhythm(commits, observation_date="2026-02-28", empty_reason="no_human_commits")
    assert profile["kind"] == "observed"
    assert profile["timestamp_basis"] == "git_author_timestamp"
    assert profile["median_gap_days"]["kind"] == "observed"
    assert profile["p90_gap_days"]["kind"] == "observed"
    assert profile["burst_share_le_2d"]["kind"] == "observed"
    assert profile["long_gap_share_ge_30d"]["kind"] == "observed"
    assert profile["long_gap_share_ge_30d"]["value"] > 0
    assert RHYTHM_LIMITATION in profile["limitations"]


def test_as_of_window_active_days() -> None:
    commits = [_c(f"{i:040d}", f"2026-01-{(i % 28) + 1:02d}T12:00:00Z") for i in range(21)]
    inside = change_rhythm(commits, observation_date="2026-01-31", empty_reason="x")
    outside = change_rhythm(commits, observation_date="2026-08-29", empty_reason="x")
    assert inside["active_days_180d"]["value"] >= outside["active_days_180d"]["value"]
    assert outside["active_days_180d"]["value"] == 0


def test_insufficient_population_suppresses_rates() -> None:
    commits = [_c(f"{i:040d}", f"2026-01-{i + 1:02d}T12:00:00Z") for i in range(5)]
    profile = change_rhythm(commits, observation_date="2026-01-31", empty_reason="x")
    assert profile["median_gap_days"]["kind"] == "not_observed"
    assert profile["median_gap_days"]["reason"] == "insufficient_population"
    assert profile["active_days_180d"]["kind"] == "observed"


def test_sha_tie_break_same_timestamp() -> None:
    a = _c("b" * 40, "2026-01-01T12:00:00Z")
    b = _c("a" * 40, "2026-01-01T12:00:00Z")
    ordered = ordered_commits([a, b])
    assert ordered[0].sha < ordered[1].sha


def test_gaps_ignore_history_outside_180d_window() -> None:
    old = [_c(f"a{i:039d}", f"2025-01-{(i % 28) + 1:02d}T12:00:00Z") for i in range(25)]
    new = [_c(f"b{i:039d}", f"2026-08-{(i % 28) + 1:02d}T12:00:00Z") for i in range(25)]
    mixed = change_rhythm(old + new, observation_date="2026-08-29", empty_reason="x")
    only_new = change_rhythm(new, observation_date="2026-08-29", empty_reason="x")
    assert mixed["window_population"] == only_new["window_population"]
    assert mixed["median_gap_days"] == only_new["median_gap_days"]
    assert mixed["p90_gap_days"] == only_new["p90_gap_days"]
    assert mixed["history_outside_window_commit_count"]["value"] == 25
    assert only_new["history_outside_window_commit_count"]["value"] == 0


def test_as_of_moves_window_population() -> None:
    commits = [_c(f"{i:040d}", f"2026-01-{(i % 28) + 1:02d}T12:00:00Z") for i in range(25)]
    january = change_rhythm(commits, observation_date="2026-01-31", empty_reason="x")
    august = change_rhythm(commits, observation_date="2026-08-29", empty_reason="x")
    assert january["window_population"] == 25
    assert august["window_population"] == 0
    assert august["median_gap_days"]["reason"] == "no_commits_in_window"


def test_limitation_mentions_not_labor() -> None:
    profile = change_rhythm(
        [_c(f"{i:040d}", "2026-01-01T12:00:00Z") for i in range(21)],
        observation_date="2026-01-31",
        empty_reason="x",
    )
    joined = " ".join(profile["limitations"])
    assert "労働" in joined
    assert RHYTHM_LIMITATION in joined
