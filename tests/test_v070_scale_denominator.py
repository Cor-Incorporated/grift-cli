"""The AI-comparison gate found two commit populations in one report.

`context_profile.scale.human_commits` counts merges. `activity.repo_human_
nonmerge_commits` does not. On pytest they read 16,962 and 12,396 — a 4,566
commit gap between two numbers a reader meets on the same page. `activity`
already carried a `denominator_note`; `scale` carried nothing, so the only
thing separating the two was a substring of the field name.

These tests pin the pair together: the populations really do differ, and each
one names its own denominator. A future change that quietly aligns or diverges
them fails here with both values shown.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_core.context_profile import SCALE_DENOMINATOR_NOTE, build_context_profile
from tep_core.gitutil import GitCommit
from tep_core.origin import OriginResult

SCHEMA = Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json"


def _commit(index: int, *, parents: int) -> GitCommit:
    return GitCommit(
        sha=f"{index:040x}",
        author_email="ada@example.com",
        parents=tuple(f"{index + 900 + p:040x}" for p in range(parents)),
        date=f"2026-01-{(index % 28) + 1:02d}",
        subject="feat: work",
        author_name="Ada",
        files=(f"src/module_{index}.py",),
    )


def _profile(nonmerge: int, merges: int) -> dict:
    commits = [_commit(i, parents=1) for i in range(nonmerge)]
    commits += [_commit(500 + i, parents=2) for i in range(merges)]
    origin = OriginResult(classes_by_sha={c.sha: "tenant_unique" for c in commits})
    return build_context_profile(Path("."), commits, origin)


# --------------------------------------------------------------------------
# The gap is real, not hypothetical
# --------------------------------------------------------------------------


def test_scale_counts_merges_that_activity_excludes() -> None:
    """If this ever stops holding, the note below becomes a lie."""
    scale = _profile(nonmerge=30, merges=12)["scale"]
    assert scale["human_commits"]["value"] == 42, (
        "scale stopped counting merges; the denominator note now misdescribes it: "
        f"{scale['human_commits']['value']} for 30 non-merge + 12 merge commits"
    )


def test_the_note_is_present_and_says_merges_are_included() -> None:
    scale = _profile(nonmerge=30, merges=12)["scale"]
    note = scale.get("denominator_note")
    assert note == SCALE_DENOMINATOR_NOTE, f"note drifted from the constant: {note!r}"
    assert "merge" in note.lower(), note


def test_the_two_notes_describe_opposite_populations() -> None:
    """One report, two denominators. Each must state which one it is."""
    from tep_core.analyze_v2 import ACTIVITY_DENOMINATOR_NOTE

    assert "excludes" in ACTIVITY_DENOMINATOR_NOTE and "merge" in ACTIVITY_DENOMINATOR_NOTE
    assert "includes" in SCALE_DENOMINATOR_NOTE and "merge" in SCALE_DENOMINATOR_NOTE
    assert ACTIVITY_DENOMINATOR_NOTE != SCALE_DENOMINATOR_NOTE


# --------------------------------------------------------------------------
# Declaration <-> enforcement
# --------------------------------------------------------------------------


def test_schema_requires_the_note() -> None:
    """additionalProperties is false, so an unlisted key fails every report."""
    scale = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]["report_context_scale"]
    assert "denominator_note" in scale["properties"], sorted(scale["properties"])
    assert "denominator_note" in scale["required"], scale["required"]


def test_an_emitted_profile_validates_against_the_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    scale = _profile(nonmerge=30, merges=12)["scale"]
    jsonschema.validate(
        scale, {**schema["$defs"]["report_context_scale"], "$defs": schema["$defs"]}
    )
