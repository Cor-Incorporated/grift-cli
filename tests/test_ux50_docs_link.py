"""report-schema.md, metrics-guide.md and the code say the same about two keys (#50).

PR #112 rewrote the metrics-guide entries for `actor_turnover` and
`release_cadence` (`joined` / `last_active`, `tags/year`, `タグ数 /
active_span_days × 365.25`) and left docs/report-schema.md saying `年別
joined/left` and `releases/year`. docs/en/report-schema.md defers to the
Japanese file for its per-field tables, so the Japanese schema is the one tied
here: to the guide in both languages, and to the units, keys and Markdown rows
the code produces. A comment saying "keep in sync" is not a control; these
tests are, and each failure names both sides.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tep_core.context_profile import build_context_profile
from tep_core.gitutil import GitCommit
from tep_core.origin import OriginResult
from tep_core.report import _fmt_tag_frequency

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs" / "report-schema.md"
GUIDES = {
    "docs/metrics-guide.md": ROOT / "docs" / "metrics-guide.md",
    "docs/en/metrics-guide.md": ROOT / "docs" / "en" / "metrics-guide.md",
}
FIELDS = ("actor_turnover", "release_cadence")


def _schema_row(field: str) -> tuple[str, str]:
    """(unit, meaning) of a row in the context_profile table."""
    text = SCHEMA.read_text(encoding="utf-8")
    section = text.split("### context_profile", 1)[1].split("\n### ", 1)[0]
    match = re.search(rf"^\| `{field}` \| ([^|]+?) \| (.+?) \|$", section, re.MULTILINE)
    assert match, f"docs/report-schema.md has no context_profile row for `{field}`"
    return match[1].strip(), match[2].strip()


def _guide_entry(name: str, field: str) -> str:
    """The `- **field**:` entry of a metrics guide, unwrapped to one line."""
    text = GUIDES[name].read_text(encoding="utf-8")
    pattern = rf"^- \*\*{field}\*\*: (.+?)(?=\n- |\n\n|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    assert match, f"{name} has no `- **{field}**:` entry"
    return " ".join(match[1].split())


def _formula(text: str) -> str:
    found = re.findall(r"`([^`]*active_span_days[^`]*)`", text)
    assert found, f"no backticked active_span_days formula in: {text}"
    return found[0]


@pytest.fixture
def profile(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    commits = [
        GitCommit(
            sha=f"{index:040x}",
            author_email=f"dev{index}@example.com",
            parents=(),
            date=day,
            subject="work",
            files=("src/a.py",),
        )
        for index, day in enumerate(("2025-12-01", "2026-03-01"))
    ]
    monkeypatch.setattr("tep_core.context_profile._tags", lambda repo: ["v1", "v2"])
    return build_context_profile(
        Path("."),
        list(reversed(commits)),
        OriginResult(classes_by_sha={c.sha: "tenant_unique" for c in commits}),
    )


def test_schema_units_are_the_units_the_code_emits(profile: dict[str, Any]) -> None:
    for field in FIELDS:
        unit, _meaning = _schema_row(field)
        emitted = profile[field]["unit"]
        assert unit == emitted, (
            f"docs/report-schema.md gives `{field}` the unit {unit!r}; the code emits {emitted!r}"
        )


def test_turnover_keys_are_named_alike(profile: dict[str, Any]) -> None:
    keys = sorted({key for row in profile["actor_turnover"]["value"].values() for key in row})
    assert keys == ["joined", "last_active"], keys
    _unit, meaning = _schema_row("actor_turnover")
    for key in keys:
        assert f"`{key}`" in meaning, (
            f"the code emits turnover key `{key}`; docs/report-schema.md says: {meaning}"
        )
        for name in GUIDES:
            entry = _guide_entry(name, "actor_turnover")
            assert f"`{key}`" in entry, f"the code emits turnover key `{key}`; {name} says: {entry}"


def test_cadence_formula_and_unit_are_stated_alike() -> None:
    unit, meaning = _schema_row("release_cadence")
    japanese = _guide_entry("docs/metrics-guide.md", "release_cadence")
    english = _guide_entry("docs/en/metrics-guide.md", "release_cadence")
    formula = _formula(japanese)
    assert f"`{formula}`" in meaning, (
        f"docs/metrics-guide.md defines release_cadence as `{formula}`; "
        f"docs/report-schema.md says: {meaning}"
    )
    denominator = formula.split("/", 1)[1].strip()
    assert _formula(english).split("/", 1)[1].strip() == denominator, (
        f"docs/metrics-guide.md divides by `{denominator}`; "
        f"docs/en/metrics-guide.md defines `{_formula(english)}`"
    )
    for name, entry in (("docs/metrics-guide.md", japanese), ("docs/en/metrics-guide.md", english)):
        assert f"`{unit}`" in entry, (
            f"docs/report-schema.md gives release_cadence the unit {unit!r}; {name} says: {entry}"
        )


@pytest.mark.parametrize(
    ("tags", "days", "value"),
    [
        pytest.param(3, 1, 1095.75, id="short-span"),
        pytest.param(3, 0, None, id="zero-span"),
    ],
)
def test_guides_show_the_rows_the_renderer_prints(tags: int, days: int, value: Any) -> None:
    rendered = _fmt_tag_frequency(
        {
            "release_cadence": {"kind": "observed", "value": value, "unit": "tags/year"},
            "scale": {
                "tags": {"kind": "observed", "value": tags, "unit": "tags"},
                "active_span_days": {"kind": "observed", "value": days, "unit": "days"},
            },
        }
    )
    for name in GUIDES:
        entry = _guide_entry(name, "release_cadence")
        assert f"`{rendered}`" in entry, (
            f"report.md prints `{rendered}` for {tags} tags over {days} days; {name} says: {entry}"
        )
