"""lifecycle-v2 (density-based) tests — addendum16 §2.

Falsifiable centerpiece: a bulk-housekeeping-shaped fixture (180 days of
silence + commits on only the last 1 day) must stay dormant. Primary outputs
are the two raw observations, and the class band always sits next to them.
"""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.context_profile import (
    CONTEXT_DEFINITION_VERSION,
    LIFECYCLE_ACTIVE_MIN_DAYS_180D,
    LIFECYCLE_MAINTAINED_MIN_DAYS_180D,
)
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo


def _analyze(repo: Path):
    return analyze_repository(repo, empty_identity(), Lineage(), scope="repo")["context_profile"]


def test_version_is_v2_and_bands_disclosed() -> None:
    assert CONTEXT_DEFINITION_VERSION == "context-v2-2026-08-23"
    assert (LIFECYCLE_MAINTAINED_MIN_DAYS_180D, LIFECYCLE_ACTIVE_MIN_DAYS_180D) == (3, 12)


def test_bulk_housekeeping_fixture_stays_dormant(tmp_path: Path) -> None:
    """addendum16 §2-5 falsification: 180-day silence + 1 day of touches."""
    repo = init_repo(tmp_path / "repo")
    # long-ago active history (outside the 180d window)
    for index in range(10):
        commit(
            repo,
            email="a@example.com",
            date=f"2024-0{index % 9 + 1}-1{index % 9}",
            message=f"old {index}",
        )
    # then silence, and exactly ONE recent active day (bulk housekeeping shape)
    commit(repo, email="a@example.com", date="2026-08-01", message="chore: bulk housekeeping")
    ctx = _analyze(repo)
    assert ctx["active_days_180d"]["value"] == 1
    assert ctx["days_since_last_human_commit"]["value"] == 0
    assert ctx["lifecycle_stage"]["value"] == "dormant", (
        "a single recent day after 180 days of silence must not flip the class"
    )


def test_band_boundaries(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    # 12 distinct active days inside the window → active (>= 12)
    for index in range(12):
        commit(repo, email="a@example.com", date=f"2026-07-{index + 1:02d}", message=f"d{index}")
    ctx = _analyze(repo)
    assert ctx["active_days_180d"]["value"] == 12
    assert ctx["lifecycle_stage"]["value"] == "active"

    repo2 = init_repo(tmp_path / "repo2")
    for index in range(3):  # 3 days → maintained band (3..11)
        commit(repo2, email="a@example.com", date=f"2026-07-{index + 1:02d}", message=f"m{index}")
    ctx2 = _analyze(repo2)
    assert ctx2["active_days_180d"]["value"] == 3
    assert ctx2["lifecycle_stage"]["value"] == "maintained"

    repo3 = init_repo(tmp_path / "repo3")
    for index in range(2):  # 2 days → dormant (<= 2)
        commit(repo3, email="a@example.com", date=f"2026-07-{index + 1:02d}", message=f"x{index}")
    ctx3 = _analyze(repo3)
    assert ctx3["active_days_180d"]["value"] == 2
    assert ctx3["lifecycle_stage"]["value"] == "dormant"


def test_primary_outputs_always_present(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="one")
    ctx = _analyze(repo)
    for key in ("days_since_last_human_commit", "active_days_180d"):
        assert ctx[key]["kind"] == "observed"
        assert ctx[key]["unit"] == "days"
    # markdown renders the raw values next to the class
    from tep_core.report import render_markdown

    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    md = render_markdown(report)
    assert "active_days_180d" in md and "days_since_last_human_commit" in md


def test_definition_document_discloses_informed_by_pilot() -> None:
    text = (Path(__file__).resolve().parents[1] / "docs" / "report-schema.md").read_text(
        encoding="utf-8"
    )
    assert "lifecycle-v2" in text
    assert "informed-by-pilot-1" in text or "pilot" in text.lower()
    assert "bulk housekeeping" in text
