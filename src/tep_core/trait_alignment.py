"""The alignment sections: overlap table, questions, what was not declared.

Built from the alignment-v1 verdicts (overlap / outside_declared_range /
observed_zero / not_observed / not_declared, ADR-0001 R5). Overlaps are listed,
never counted (ADR-0002 T5). A question never repeats a trait sentence.
Questions follow T7 like the actor report: an identity the person claimed, with
the consent record `grift align` copies into `subject.actor_consent`. Any other
actor (administrator-registered, public, unconsented) gets the overlap table and
the reason instead.
"""

from __future__ import annotations

from typing import Any

from tep_core.actor_basis import ActorBasis, classify_actor_basis
from tep_core.identity import RECORDED_EXPLICIT_CONSENT
from tep_core.trait_profile import as_decimal, as_int, days_text, place_counts, plain_reason
from tep_core.trait_sections import percent_text, title_value
from tep_core.trait_tables import (
    ALIGNMENT_TEXTS,
    HEADINGS,
    INPUT_NAMES,
    LIMIT_NOTES,
    NOT_SHOWN,
    NOT_SHOWN_SHALLOW_TEMPLATE,
    PLACE_NAMES,
    RHYTHM_ITEM_NAMES,
    SECTION_TEXTS,
    TEST_TYPE_SHORT_NAMES,
    THRESHOLDS,
    VERDICT_NAMES,
)
from tep_core.v2_constants import SELECTIVITY_NOTICE_JA

_T = ALIGNMENT_TEXTS
_MIN = int(THRESHOLDS["min_population"])


def _floor(axis: dict[str, Any]) -> Any:
    declared = axis.get("declared") or {}
    return declared.get("value") if declared.get("unit") == "commit_share" else None


def _item_name(group: str, item: str) -> str:
    names = {"surfaces": PLACE_NAMES, "verification": TEST_TYPE_SHORT_NAMES, "inputs": INPUT_NAMES}
    return names.get(group, RHYTHM_ITEM_NAMES).get(item, item)


def _gap_days(value: Any) -> str:
    """Every gap in this section is rounded up: next to an upper bound it never reads
    as inside it, and one value never prints two ways in one section (R10)."""
    number = as_decimal(value)
    return days_text(number, ceiling=True) if number is not None else str(value)


def _observed(axis: dict[str, Any]) -> dict[str, Any]:
    return axis.get("observed") or axis.get("actor_observed") or {}


class _Sections:
    def __init__(self, report: dict[str, Any]) -> None:
        actor = report.get("actor_observed") or {}
        self.n, self.counts = place_counts(actor.get("surface_profile") or {})
        profile = actor.get("verification_profile") or {}
        self.tests_n = as_int((profile.get("test_type_share") or {}).get("population"))
        self.tests = (profile.get("test_type_distribution") or {}).get("values") or {}
        self.rows: list[tuple[str, str]] = []
        self.zero_places: list[str] = []
        self.zero_tests: list[str] = []
        self.asks: list[str] = []
        self.not_declared: list[str] = []
        self.gaps = False

    def gap(self, value: Any) -> str:
        self.gaps = True
        return _gap_days(value)

    def record(self, axis: dict[str, Any], group: str, item: str, *, ask: bool) -> str:
        """The record side of a place or test-type row (T3: no denominator below 20).

        A saved alignment without actor_observed falls back to the axis's own
        value, which is a share for a declared floor and a count otherwise (R4).
        """
        own = group == "surfaces"
        source, n = (self.counts, self.n) if own else (self.tests, self.tests_n)
        count = as_int(source.get(item))
        if count is None:
            observed = _observed(axis)
            if observed.get("unit") == "commit_share":
                key = "record_own_share" if own else "record_tests_share"
                return _T[key].format(pct=percent_text(observed.get("value")))
            count, n = as_int(observed.get("value")) or 0, None
        if n is not None and n >= _MIN:
            key = ("record_own" if ask else "cell_own_count") if own else "record_tests"
            return _T[key].format(n=n, c=count)
        key = ("record_own_count" if own else "record_tests_count") if ask else "cell_count"
        return _T[key].format(c=count)

    def overlap(self, axis: dict[str, Any], group: str, item: str) -> None:
        name, declared = str(axis.get("axis")), (axis.get("declared") or {}).get("value")
        observed = _observed(axis).get("value")
        if group in ("surfaces", "verification"):
            label, floor = _item_name(group, item), _floor(axis)
            if floor is not None:
                key = "cell_place_floor" if group == "surfaces" else "cell_test_floor"
                label = _T[key].format(place=label, type=label, pct=percent_text(floor))
            self.rows.append((label, self.record(axis, group, item, ask=False)))
        elif name == "change_rhythm.active_days_180d":
            self.rows.append(
                (_T["cell_days_min"].format(d=declared), _T["cell_days"].format(v=observed))
            )
        elif name.startswith("change_rhythm."):
            key = "cell_p90_max" if name.endswith("p90_gap_days") else "cell_median_max"
            value = _T["cell_days"].format(v=self.gap(observed))
            self.rows.append((_T[key].format(d=declared), value))
        elif group == "inputs":
            self.rows.append(
                (_T["cell_input"].format(input=_item_name(group, item)), _T["cell_shared"])
            )
        else:
            self.other(axis, group, item)

    def outside(self, axis: dict[str, Any], group: str, item: str) -> None:
        name, declared = str(axis.get("axis")), (axis.get("declared") or {}).get("value")
        observed = _observed(axis).get("value")
        if group in ("surfaces", "verification"):
            floor_key = "floor_own" if group == "surfaces" else "floor_tests"
            floor_text = _T[floor_key].format(pct=percent_text(_floor(axis)))
            record = self.record(axis, group, item, ask=True)
            text = _T["ask_below_share"].format(
                item=_item_name(group, item), floor=floor_text, record=record
            )
            self.asks.append(text)
        elif name == "change_rhythm.active_days_180d":
            self.asks.append(_T["ask_outside_days"].format(declared=declared, observed=observed))
        elif name.startswith("change_rhythm."):
            text = _T["ask_outside_gap"].format(
                item=_item_name(group, item), declared=declared, observed=self.gap(observed)
            )
            self.asks.append(text)
        else:
            self.other(axis, group, item)

    def zero(self, axis: dict[str, Any], group: str, item: str) -> None:
        if group == "surfaces":
            self.zero_places.append(_item_name(group, item))
        elif group == "verification":
            self.zero_tests.append(_item_name(group, item))
        elif str(axis.get("axis")) == "change_rhythm.active_days_180d":
            # No day with a change in the 180-day window: below a minimum, like any shortfall.
            declared = (axis.get("declared") or {}).get("value")
            self.asks.append(_T["ask_outside_days"].format(declared=declared, observed=0))
        else:
            self.other(axis, group, item)

    def unobserved(self, axis: dict[str, Any], group: str, item: str) -> None:
        if str(axis.get("axis")) == "inputs.forge":
            self.asks.append(_T["ask_forge"])
            return
        reason = plain_reason(_observed(axis).get("reason"))
        self.asks.append(_T["ask_not_observed"].format(item=_item_name(group, item), reason=reason))

    def undeclared(self, axis: dict[str, Any], group: str, item: str) -> None:
        name, observed = str(axis.get("axis")), _observed(axis)
        if observed.get("kind") != "observed" or not name.startswith("change_rhythm."):
            return  # nothing was asked for, and nothing countable to list
        if name == "change_rhythm.active_days_180d":
            self.not_declared.append(_T["not_declared_days"].format(observed=observed.get("value")))
            return
        days = self.gap(observed.get("value"))
        self.not_declared.append(
            _T["not_declared_gap"].format(item=_item_name(group, item), observed=days)
        )

    def other(self, axis: dict[str, Any], group: str, item: str) -> None:
        """A verdict and axis this table has no row for: asked about, never dropped."""
        state = VERDICT_NAMES.get(str(axis.get("comparison")), str(axis.get("comparison")))
        self.asks.append(_T["ask_other"].format(item=_item_name(group, item), state=state))

    def read(self, axes: list[dict[str, Any]]) -> None:
        order = {"surfaces": 0, "verification": 1, "change_rhythm": 2, "inputs": 3}
        handlers = {
            "overlap": self.overlap,
            "outside_declared_range": self.outside,
            "observed_zero": self.zero,
            "not_observed": self.unobserved,
            "not_declared": self.undeclared,
        }
        for axis in sorted(
            axes, key=lambda axis: order.get(str(axis.get("axis")).split(".")[0], 4)
        ):
            name = str(axis.get("axis") or "")
            if name == "role_lens":
                continue  # a display preset, not an observation: no row, no question
            group, _, item = name.partition(".")
            handlers.get(str(axis.get("comparison")), self.other)(axis, group, item)


def _questions(parts: _Sections) -> list[str]:
    asks = []
    if parts.zero_places:
        asks.append(_T["ask_zero_places"].format(places="、".join(parts.zero_places)))
    if parts.zero_tests:
        asks.append(_T["ask_zero_tests"].format(types="、".join(parts.zero_tests)))
    return asks + parts.asks


def _question_lines(report: dict[str, Any], parts: _Sections) -> list[str]:
    subject = report.get("subject") or {}
    basis = classify_actor_basis(
        subject.get("actor_selection"), subject.get("actor_attribution_state")
    )
    if basis is not ActorBasis.SELF_CLAIMED:
        return [_T["questions_not_shown"].format(reason=NOT_SHOWN[basis.value])]
    if subject.get("actor_consent") != RECORDED_EXPLICIT_CONSENT:
        return [_T["questions_not_shown"].format(reason=NOT_SHOWN["no_consent"])]
    asks = _questions(parts)
    note = [_T["zero_note"], ""] if parts.zero_places or parts.zero_tests else []
    return note + ([f"{index}. {ask}" for index, ask in enumerate(asks, 1)] or [_T["no_questions"]])


def _limit_notes(declared: dict[str, Any], text: str, *, gaps: bool) -> list[str]:
    days = ((declared.get("change_rhythm") or {}).get("active_days_180d_min") or {}).get("kind")
    keys = ["overlap", *(["days"] if days == "declared" else [])]
    keys += ["p90"] if RHYTHM_ITEM_NAMES["p90_gap_days"] in text else []
    keys += ["gap_rounding"] if gaps else []
    keys.append("scales")
    return [*(LIMIT_NOTES[key] for key in keys), SELECTIVITY_NOTICE_JA, LIMIT_NOTES["verify"]]


def alignment_section(report: dict[str, Any]) -> list[str]:
    cid = (report.get("subject") or {}).get("actor_canonical_id")
    declared = report.get("declared") or {}
    title = title_value(declared)
    if title:
        heading = HEADINGS["alignment_title"].format(cid=cid, title=title)
    else:
        heading = HEADINGS["alignment_title_untitled"].format(cid=cid)
    completeness = (report.get("actor_provenance") or {}).get("revision_completeness") or {}
    if completeness.get("shallow") is True:
        # As in the actor section (R7): the verdicts were counted on the truncated history.
        reason = NOT_SHOWN["shallow_history"]
        return [heading, "", NOT_SHOWN_SHALLOW_TEMPLATE.format(reason=reason), ""]
    parts = _Sections(report)
    parts.read(report.get("axes") or [])
    lines = [
        heading,
        "",
        SECTION_TEXTS["alignment_intro"].format(cid=cid),
        "",
        HEADINGS["overlap"],
        "",
    ]
    if parts.rows:
        header = f"| {_T['header_request']} | {_T['header_record'].format(cid=cid)} |"
        lines += [header, "|---|---|", *(f"| {left} | {right} |" for left, right in parts.rows)]
    else:
        lines.append(_T["no_overlap"])
    lines += ["", HEADINGS["align_questions"], "", *_question_lines(report, parts)]
    if parts.not_declared:
        lines += ["", HEADINGS["not_declared"], "", *(f"- {text}" for text in parts.not_declared)]
    notes = _limit_notes(declared, "\n".join(lines), gaps=parts.gaps)
    return [*lines, "", HEADINGS["limits"], "", *(f"- {note}" for note in notes), ""]
