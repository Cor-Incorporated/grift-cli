"""G3 (較正) — a truncated clone must not be reported as the repository.

Found by the AI-comparison gate. `git clone --depth 50` of urllib3 produced a
report claiming, as `kind: "observed"`:

    first_commit          2026-05-07   (actually 2009-12-10)
    human_commits                 38   (actually 4,269)
    repo_age_days                117   (actually 6,109)
    resolved_human_actors         17   (actually 433)

`provenance.revision_completeness.complete` was already `false`, so the tool
knew. Nothing connected that knowledge to the values — the declaration and the
enforcement lived apart, and the values won.

This matters beyond tidiness: `actions/checkout` defaults to `fetch-depth: 1`,
so any CI-run report was of this shape. A sixteen-year-old project would be
presented to a reader as four months old with 17 contributors.

Depth-dependent fields now degrade to `not_observed / history_incomplete`.
HEAD-anchored facts survive, because HEAD is real whatever the depth.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tep_core.context_profile import HISTORY_INCOMPLETE_REASON, build_context_profile
from tep_core.gitutil import GitCommit
from tep_core.origin import OriginResult
from tep_core.revision import commit_history_complete

# Values that describe the whole repository, and so cannot survive truncation.
DEPTH_DEPENDENT = (
    "resolved_human_actors",
    "top_actor_share",
    "collaboration_class",
    "repo_age_days",
    "active_days_180d",
    "lifecycle_stage",
    "actor_turnover",
    "release_cadence",
)
DEPTH_DEPENDENT_SCALE = ("human_commits", "first_commit", "active_span_days", "tags")


def _commit(index: int) -> GitCommit:
    return GitCommit(
        sha=f"{index:040x}",
        author_email=f"dev{index % 4}@example.com",
        parents=(f"{index + 900:040x}",),
        date=f"2026-0{(index % 3) + 1}-{(index % 27) + 1:02d}",
        subject="feat: work",
        author_name="Dev",
        files=("src/app.py",),
    )


def _profile(*, history_complete: bool) -> dict:
    commits = [_commit(i) for i in range(40)]
    origin = OriginResult(classes_by_sha={c.sha: "tenant_unique" for c in commits})
    return build_context_profile(Path("."), commits, origin, history_complete=history_complete)


# --------------------------------------------------------------------------
# Truncated history: the depth-dependent claims must disappear
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", DEPTH_DEPENDENT)
def test_depth_dependent_fields_are_not_observed(field: str) -> None:
    node = _profile(history_complete=False)[field]
    assert node["kind"] == "not_observed", (
        f"{field} still claims a repository-wide value from a truncated clone: {node}"
    )
    assert node["reason"] == HISTORY_INCOMPLETE_REASON, node


@pytest.mark.parametrize("field", DEPTH_DEPENDENT_SCALE)
def test_depth_dependent_scale_fields_are_not_observed(field: str) -> None:
    node = _profile(history_complete=False)["scale"][field]
    assert node["kind"] == "not_observed", f"scale.{field}: {node}"
    assert node["reason"] == HISTORY_INCOMPLETE_REASON, node


def test_head_anchored_facts_survive_truncation() -> None:
    """Over-degrading is its own failure: HEAD is present at any depth."""
    profile = _profile(history_complete=False)
    assert profile["scale"]["last_commit"]["kind"] == "observed"
    assert profile["days_since_last_human_commit"]["kind"] == "observed"


# --------------------------------------------------------------------------
# Complete history: nothing changes
# --------------------------------------------------------------------------


def test_a_complete_clone_is_untouched() -> None:
    profile = _profile(history_complete=True)
    for field in DEPTH_DEPENDENT:
        assert profile[field]["kind"] == "observed", f"{field} degraded on a complete clone"
    for field in DEPTH_DEPENDENT_SCALE:
        assert profile["scale"][field]["kind"] == "observed", f"scale.{field} degraded"


# --------------------------------------------------------------------------
# Detection: the flag must come from the repository, not from a caller's guess
# --------------------------------------------------------------------------


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def origin_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    repo.mkdir()
    _git("init", "-q", "-b", "main", str(repo))
    _git("config", "user.email", "dev@example.com", cwd=repo)
    _git("config", "user.name", "Dev", cwd=repo)
    for i in range(6):
        (repo / "f.txt").write_text(f"{i}\n", encoding="utf-8")
        _git("add", "f.txt", cwd=repo)
        _git("commit", "-q", "-m", f"feat: change {i}", cwd=repo)
    return repo


def test_a_full_clone_reports_complete(origin_repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "full"
    _git("clone", "-q", f"file://{origin_repo}", str(dest))
    assert commit_history_complete(dest) is True


def test_a_shallow_clone_reports_incomplete(origin_repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "shallow"
    _git("clone", "-q", "--depth", "2", f"file://{origin_repo}", str(dest))
    assert dest.joinpath(".git", "shallow").exists(), "fixture did not produce a shallow clone"
    assert commit_history_complete(dest) is False


def test_a_blob_filtered_clone_stays_complete(origin_repo: Path, tmp_path: Path) -> None:
    """Over-correction guard.

    `--filter=blob:none` omits file content, never commits. Counts, dates and
    authors remain exact, so degrading them would refuse to report what was
    actually measured — the mirror image of the defect this module fixes.
    """
    dest = tmp_path / "partial"
    _git(
        "clone",
        "-q",
        "--filter=blob:none",
        "--no-local",
        f"file://{origin_repo}",
        str(dest),
    )
    promisor = subprocess.run(
        ["git", "-C", str(dest), "config", "--get-regexp", r"^remote\..*\.promisor$"],
        capture_output=True,
        text=True,
    ).stdout
    assert "true" in promisor, f"fixture did not produce a promisor clone: {promisor!r}"
    assert commit_history_complete(dest) is True, (
        "a blob-filtered clone has every commit; degrading it discards real measurements"
    )


def test_an_uninterrogable_path_is_incomplete(tmp_path: Path) -> None:
    """Unproven, never 'no'. A failed question is not a clean bill of health."""
    assert commit_history_complete(tmp_path / "does-not-exist") is False


# --------------------------------------------------------------------------
# End to end: the CLI on a real shallow clone
# --------------------------------------------------------------------------


def test_the_cli_degrades_on_a_shallow_clone(origin_repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "shallow-cli"
    _git("clone", "-q", "--depth", "2", f"file://{origin_repo}", str(dest))
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "tep_cli", "repo", str(dest), "--format", "json"],
        cwd=root,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[:500]
    report = json.loads(result.stdout)

    assert report["provenance"]["revision_completeness"]["complete"] is False
    context = report["context_profile"]
    assert context["repo_age_days"]["kind"] == "not_observed"
    assert context["resolved_human_actors"]["kind"] == "not_observed", (
        "analyze_v2 overrides resolved_human_actors from the actor directory; "
        "that directory is built from the same truncated history"
    )
    assert context["scale"]["first_commit"]["kind"] == "not_observed"
    assert report["activity"]["repo_human_nonmerge_commits"]["kind"] == "not_observed"


def test_the_actor_path_degrades_under_the_same_reason_name(
    origin_repo: Path, tmp_path: Path
) -> None:
    """Two modules refuse a truncated clone; they must refuse in one word.

    `context_profile` degrades its own fields to `HISTORY_INCOMPLETE_REASON`.
    `experience_collect` raises `ExperienceHistoryIncomplete`, which
    `analyze.py` maps to a reason of its own. Nothing linked the two strings,
    so one could be renamed and a report would carry two different names for
    the same refusal -- and a reader filtering on one would silently miss the
    other.
    """
    dest = tmp_path / "shallow-actor"
    _git("clone", "-q", "--depth", "2", f"file://{origin_repo}", str(dest))
    assert dest.joinpath(".git", "shallow").exists(), "fixture did not produce a shallow clone"
    identity = tmp_path / "identity.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        "[[actors]]\n"
        'canonical_id = "dev"\n'
        'emails = ["dev@example.com"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tep_cli",
            "actor",
            "dev",
            str(dest),
            "--identity",
            str(identity),
            "--format",
            "json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[:500]
    report = json.loads(result.stdout)

    assert report["provenance"]["revision_completeness"]["shallow"] is True
    for axis in ("experience", "role_profile", "library_context"):
        node = report[axis]
        assert node["kind"] == "not_observed", f"{axis} claimed a value: {node}"
        assert node["reason"] == HISTORY_INCOMPLETE_REASON, (
            f"{axis} refuses under {node['reason']!r} while context_profile uses "
            f"{HISTORY_INCOMPLETE_REASON!r}; one refusal needs one name"
        )
    assert report["context_profile"]["repo_age_days"]["reason"] == HISTORY_INCOMPLETE_REASON
