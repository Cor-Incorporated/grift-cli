"""The 「根拠」 table under the trait sections: the numbers each sentence used.

The rows follow the same gates as the sentences (ADR-0002 T3): a block that says
it is not shown below 20 shows no row either, and the make rows appear only when
role_profile counts the same commits as the rest of the section.
"""

from __future__ import annotations

from typing import Any

from tep_core.trait_profile import (
    as_decimal,
    as_int,
    days_text,
    place_counts,
    process_counts,
    ranked_places,
    role_in_scope,
    share_count,
)
from tep_core.trait_tables import (
    EVIDENCE_ROWS,
    HEADINGS,
    PLACE_NAMES,
    SECTION_TEXTS,
    TEST_TYPE_SHORT_NAMES,
    THRESHOLDS,
)
from tep_core.v2_constants import VERIFICATION_TYPES

_MIN = int(THRESHOLDS["min_population"])
_SAME = SECTION_TEXTS["same_period"]
_UNKNOWN_PERIOD = "—"


def _aspect(key: str) -> str:
    return HEADINGS[key].lstrip("# ")


def _row(aspect: str, counted: str, value: str, period: str) -> str:
    return f"| {aspect} | {counted} | {value} | {period} |"


def _units(counts: list[int]) -> str:
    return " / ".join(SECTION_TEXTS["count_unit"].format(c=count) for count in counts)


def recorded_shallow(prov: dict[str, Any]) -> bool | None:
    """`provenance.revision_completeness.shallow`, or None when it is not recorded
    (a project-v1 saved before 0.9.1 J3): unknown, never read as complete."""
    completeness = prov.get("revision_completeness")
    shallow = completeness.get("shallow") if isinstance(completeness, dict) else None
    return shallow if isinstance(shallow, bool) else None


def history_text(prov: dict[str, Any], *, person: bool = True) -> str:
    """The counted range: 全履歴 only where a shallow clone is ruled out. The actor
    section is not shown for one; project-v1 records it since 0.9.1 (J3)."""
    end = prov.get("observation_date")
    whole = person or recorded_shallow(prov) is False
    key = "history" if whole else "history_repo"
    return SECTION_TEXTS[key].format(end=end) if end else _UNKNOWN_PERIOD


def window_text(prov: dict[str, Any]) -> str:
    window = prov.get("git_window") or {}
    if window.get("start") and window.get("end"):
        return SECTION_TEXTS["window"].format(start=window["start"], end=window["end"])
    return _UNKNOWN_PERIOD


def _place_rows(source: dict[str, Any], period: str) -> list[str]:
    n, counts = place_counts(source.get("surface_profile") or {})
    ranked = ranked_places(counts)
    if n is None or n < _MIN or not ranked:
        return []
    aspect = _aspect("places")
    limit = int(THRESHOLDS["max_following_places"])
    (top, top_count), rest = ranked[0], ranked[1 : 1 + limit]
    counted = EVIDENCE_ROWS["place_top"].format(place=PLACE_NAMES[top])
    rows = [_row(aspect, counted, SECTION_TEXTS["count_of"].format(n=n, c=top_count), period)]
    if rest:
        names = " / ".join(PLACE_NAMES[name] for name, _ in rest)
        values = SECTION_TEXTS["count_list"].format(n=n, values=_units([c for _, c in rest]))
        rows.append(_row(aspect, EVIDENCE_ROWS["place_rest"].format(places=names), values, _SAME))
    return rows


def _rhythm_rows(rhythm: dict[str, Any], period: str) -> list[str]:
    n = as_int(rhythm.get("interval_sample_size"))
    median = as_decimal(rhythm.get("median_gap_days"))
    p90 = as_decimal(rhythm.get("p90_gap_days"))
    if rhythm.get("kind") != "observed" or n is None or n < _MIN or median is None or p90 is None:
        return []
    aspect, days = _aspect("rhythm"), SECTION_TEXTS["days_with_gaps"]
    long_gaps = share_count(rhythm.get("long_gap_share_ge_30d"), n)
    return [
        _row(
            aspect, EVIDENCE_ROWS["rhythm_median"], days.format(days=days_text(median), n=n), period
        ),
        _row(aspect, EVIDENCE_ROWS["rhythm_p90"], days.format(days=days_text(p90), n=n), _SAME),
        _row(
            aspect,
            EVIDENCE_ROWS["rhythm_long"],
            SECTION_TEXTS["gaps_of"].format(n=n, c=long_gaps),
            _SAME,
        ),
    ]


def _verify_rows(profile: dict[str, Any], period: str) -> list[str]:
    if profile.get("kind") != "observed":
        return []
    aspect, rows = _aspect("verify"), []
    touch = profile.get("test_touch_share") or {}
    n, c = as_int(touch.get("sample_size")), as_int(touch.get("test_touch"))
    if touch.get("kind") == "observed" and n is not None and c is not None:
        rows.append(
            _row(
                aspect,
                EVIDENCE_ROWS["verify_touch"],
                SECTION_TEXTS["count_of"].format(n=n, c=c),
                period,
            )
        )
    values = (profile.get("test_type_distribution") or {}).get("values") or {}
    present = [name for name in VERIFICATION_TYPES if (as_int(values.get(name)) or 0) > 0]
    if present:
        names = " / ".join(TEST_TYPE_SHORT_NAMES[name] for name in present)
        note = SECTION_TEXTS["overlapping_counts"] if len(present) > 1 else ""
        counts = _units([as_int(values.get(name)) or 0 for name in present]) + note
        rows.append(
            _row(
                aspect,
                EVIDENCE_ROWS["verify_types"].format(types=names),
                counts,
                _SAME if rows else period,
            )
        )
    fix = profile.get("fix_with_test_pairing") or {}
    if fix.get("kind") == "observed":
        value = SECTION_TEXTS["count_of"].format(n=fix.get("sample_size"), c=fix.get("with_test"))
        rows.append(_row(aspect, EVIDENCE_ROWS["verify_fix"], value, _SAME if rows else period))
    return rows


def _work_rows(report: dict[str, Any], period: str) -> list[str]:
    if not role_in_scope(report):
        return []
    dimensions = (report.get("role_profile") or {}).get("dimensions") or {}
    work = dimensions.get("work_type") or {}
    create, modify = work.get("create") or {}, work.get("modify") or {}
    if create.get("kind") != "observed" or modify.get("kind") != "observed":
        return []
    aspect = _aspect("make")
    counts = _units([as_int(modify.get("numerator")) or 0, as_int(create.get("numerator")) or 0])
    value = SECTION_TEXTS["count_list"].format(n=create.get("denominator"), values=counts)
    rows = [
        _row(
            aspect,
            EVIDENCE_ROWS["work_modify_create"],
            value + SECTION_TEXTS["overlapping_counts"],
            period,
        )
    ]
    # One row per count, and only for a count the sentences may state (R1).
    for key, count in zip(("work_merges", "work_releases"), process_counts(report), strict=True):
        if count is not None:
            times = SECTION_TEXTS["count_times"].format(c=count)
            rows.append(_row(aspect, EVIDENCE_ROWS[key], times, _SAME))
    return rows


def evidence_table(source: dict[str, Any], prov: dict[str, Any], *, person: bool) -> list[str]:
    """`source` is the actor report (person) or the project's observed block."""
    history, window = history_text(prov, person=person), window_text(prov)
    rows = _place_rows(source, history)
    rows += _rhythm_rows(source.get("change_rhythm") or {}, window)
    rows += _verify_rows(source.get("verification_profile") or {}, history)
    if person:
        rows += _work_rows(source, history)
    if not rows:
        return []
    columns = ("col_aspect", "col_counted", "col_value", "col_period")
    header = _row(*(SECTION_TEXTS[key] for key in columns))
    return [HEADINGS["evidence"], "", header, "|---|---|---|---|", *rows, ""]
