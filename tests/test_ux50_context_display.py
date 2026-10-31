"""Context-v3 values and their readable denominators (#50)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tep_core.context_profile import CONTEXT_DEFINITION_VERSION, build_context_profile
from tep_core.gitutil import GitCommit
from tep_core.origin import OriginResult
from tep_core.report import _fmt_context_lines


def _profile(monkeypatch, *, same_day=False, history_complete=True):
    commits = [
        GitCommit(
            sha="a" * 40,
            author_email="a@example.com",
            parents=(),
            date="2026-01-01",
            subject="initial",
            files=("src/a.py", "src/b.py", "README.md"),
        ),
        GitCommit(
            sha="b" * 40,
            author_email="a@example.com",
            parents=("a" * 40,),
            date="2026-01-01" if same_day else "2026-03-12",
            subject="follow-up",
            files=("src/a.py", "src/web.ts"),
        ),
    ]
    monkeypatch.setattr("tep_core.context_profile._tags", lambda repo: [f"v{i}" for i in range(43)])
    return build_context_profile(
        Path("."),
        list(reversed(commits)),
        OriginResult(classes_by_sha={c.sha: "tenant_unique" for c in commits}),
        history_complete=history_complete,
    )


def test_mixed_language_touches_are_shares_not_counts(monkeypatch):
    profile = _profile(monkeypatch)
    assert profile["definition_version"] == CONTEXT_DEFINITION_VERSION == "context-v3-2026-08-25"
    assert profile["language_composition"] == {
        "kind": "observed", "value": {"py": 0.75, "ts": 0.25}, "unit": "touch-share"
    }
    markdown = "\n".join(_fmt_context_lines(profile))
    assert "languages (touch-share): py 75%, ts 25%" in markdown


def test_last_active_is_not_a_departure_and_is_explained(monkeypatch):
    profile = _profile(monkeypatch)
    assert profile["actor_turnover"]["value"] == {"2026": {"joined": 1, "last_active": 1}}
    markdown = "\n".join(_fmt_context_lines(profile))
    assert "2026: joined 1, last_active 1" in markdown
    assert "最終活動年" in markdown
    assert "not departures" in markdown
    assert "left" not in markdown


def test_annualized_tag_frequency_shows_real_count_and_span(monkeypatch):
    profile = _profile(monkeypatch)
    before = deepcopy(profile)
    assert profile["release_cadence"] == {
        "kind": "observed", "value": 224.37, "unit": "tags/year"
    }
    markdown = "\n".join(_fmt_context_lines(profile))
    assert "224.37 tags/year" in markdown
    assert "43 tags / 70 days × 365.25" in markdown
    assert "not published releases" in markdown
    assert profile == before, "rendering must preserve the measured report"


def test_existing_context_v2_turnover_can_still_be_rendered(monkeypatch):
    profile = _profile(monkeypatch)
    profile["definition_version"] = "context-v2-2026-08-22"
    profile["actor_turnover"]["value"] = {"2025": {"joined": 3, "left": 2}}
    before = deepcopy(profile)
    markdown = "\n".join(_fmt_context_lines(profile))
    assert "2025: joined 3, last_active 2" in markdown
    assert "last_active None" not in markdown
    assert profile == before


@pytest.mark.parametrize("same_day,history_complete,reason", [
    (True, True, "zero_activity_span"),
    (False, False, "history_incomplete"),
])
def test_unmeasurable_cadence_is_not_rendered_as_a_rate(
    monkeypatch, same_day, history_complete, reason
):
    markdown = "\n".join(_fmt_context_lines(_profile(
        monkeypatch, same_day=same_day, history_complete=history_complete
    )))
    line = next(line for line in markdown.splitlines() if "release_cadence" in line)
    assert f"not observed ({reason})" in line
    assert "None" not in line
    assert "224.37" not in line
