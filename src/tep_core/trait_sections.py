"""The person-facing actor section and the project section, as Markdown lines.

Both open the Markdown, before the 0.8.0 detail that follows. The sentences come
from tep_core.trait_profile and the 「根拠」 rows from tep_core.trait_evidence;
this module places them under the headings of tep_core.trait_tables.
"""

from __future__ import annotations

from typing import Any

from tep_core.trait_evidence import evidence_table, recorded_shallow
from tep_core.trait_profile import (
    actor_questions,
    as_decimal,
    as_int,
    not_shown_lines,
    not_shown_reason,
    own_total,
    place_counts,
    place_sentences,
    plain_reason,
    process_counts,
    rhythm_sentences,
    verify_sentences,
    work_sentences,
)
from tep_core.trait_tables import (
    DECLARED_ITEM_NAMES,
    DECLARED_TEXTS,
    HEADINGS,
    INPUT_NAMES,
    LIMIT_NOTES,
    PLACE_NAMES,
    SECTION_TEXTS,
    SENTENCES,
    TEST_TYPE_SHORT_NAMES,
)
from tep_core.v2_constants import SELECTIVITY_NOTICE_JA, SURFACES

# Surfaces that are not areas of work: never listed as "0 件でした".
_NOT_WORK_AREAS = frozenset({"test", "generated_vendor", "other"})


def _block(heading: str, sentences: list[str], fallback: str | None) -> list[str]:
    body = "".join(sentences) or fallback
    return [HEADINGS[heading], "", body, ""] if body else []


def _not_observed(key: str, profile: dict[str, Any]) -> str | None:
    if profile.get("kind") == "not_observed":
        return SENTENCES[key].format(reason=plain_reason(profile.get("reason")))
    return None


def work_blocks(source: dict[str, Any], *, scope: str, person: bool) -> list[str]:
    """The 「進め方」 blocks; 「関わり方」 only for the consented actor."""
    surface = source.get("surface_profile") or {}
    rhythm = source.get("change_rhythm") or {}
    places = place_sentences(surface, scope=scope)[0]
    lines = _block("places", places, _not_observed("place_not_observed", surface))
    lines += _block(
        "rhythm", rhythm_sentences(rhythm), _not_observed("rhythm_not_observed", rhythm)
    )
    lines += _block("verify", verify_sentences(source.get("verification_profile") or {}), None)
    if person:
        lines += _block("make", work_sentences(source), None)
    return lines


def _input_notes(source: dict[str, Any]) -> list[str]:
    coverage = source.get("input_coverage") or {}
    forge = (coverage.get("forge") or {}).get("kind") == "not_observed"
    tracker = (coverage.get("tracker") or {}).get("kind") == "not_observed"
    if forge and tracker:
        return [SECTION_TEXTS["unseen_both"]]
    if forge:
        return [SECTION_TEXTS["unseen_forge"]]
    if tracker:
        return [SECTION_TEXTS["unseen_tracker"]]
    return []


def _unseen(source: dict[str, Any], *, person: bool) -> list[str]:
    notes = [*_input_notes(source), SECTION_TEXTS["unseen_always"]]
    n, counts = place_counts(source.get("surface_profile") or {})
    zero = [
        PLACE_NAMES[name]
        for name in SURFACES
        if name not in _NOT_WORK_AREAS and not counts.get(name)
    ]
    if n is not None and zero:
        key = "unseen_zero_places" if person else "unseen_zero_places_repo"
        notes.append(SECTION_TEXTS[key].format(places="、".join(zero)))
    if person and process_counts(source)[1] == 0:
        notes.append(SECTION_TEXTS["unseen_no_release"])
    notes.append(SELECTIVITY_NOTICE_JA if person else SECTION_TEXTS["unseen_other_repos"])
    return [HEADINGS["unseen"], "", *(f"- {note}" for note in notes), ""]


def _periods(report: dict[str, Any]) -> list[str]:
    """The counted range (as-of history) and the 180-day rhythm window, named apart."""
    prov = report.get("provenance") or {}
    lines = []
    end, total = prov.get("observation_date"), own_total(report)
    paths = as_int((report.get("surface_profile") or {}).get("population"))
    if end and total is not None:
        if paths is not None and paths != total:
            lines.append(
                SECTION_TEXTS["record_scope_paths"].format(end=end, total=total, paths=paths)
            )
        else:
            lines.append(SECTION_TEXTS["record_scope"].format(end=end, total=total))
    window = prov.get("git_window") or {}
    population = (report.get("change_rhythm") or {}).get("window_population")
    days = window.get("days")
    if (
        window.get("start")
        and window.get("end")
        and isinstance(population, int)
        and isinstance(days, int)
    ):
        lines.append(
            SECTION_TEXTS["rhythm_period"].format(
                start=window["start"], end=window["end"], days=days, n=population
            )
        )
    return lines


def _limits(keys: tuple[str, ...]) -> list[str]:
    return [HEADINGS["limits"], "", *(f"- {LIMIT_NOTES[key]}" for key in keys), ""]


def actor_section(report: dict[str, Any]) -> list[str]:
    """The person-facing section (T7), or the reason it is not shown."""
    if not_shown_reason(report) is not None:
        return not_shown_lines(report)
    cid = (report.get("subject") or {}).get("canonical_id")
    lines = [
        HEADINGS["actor_title"].format(cid=cid),
        "",
        SECTION_TEXTS["actor_intro"].format(cid=cid),
        "",
    ]
    lines += [*_periods(report), "", HEADINGS["work"], ""]
    lines += work_blocks(report, scope="自分の変更", person=True)
    lines += _unseen(report, person=True)
    asks = actor_questions(report)
    lines += [
        HEADINGS["questions"],
        "",
        *(f"{index}. {ask}" for index, ask in enumerate(asks, 1)),
        "",
    ]
    lines += _limits(("places", "rhythm", "p90", "tests", "own_work", "verify"))
    return lines + evidence_table(report, report.get("provenance") or {}, person=True)


def percent_text(value: Any) -> str:
    """0.3 -> 30%, 0.333 -> 33.3% (a declared share floor)."""
    number = as_decimal(value)
    if number is None:
        return str(value)
    shown = (number * 100).normalize()
    return f"{shown:f}%"


def _named(values: Any, names: dict[str, str]) -> list[str]:
    return [
        names.get(str(item), str(item)) for item in (values if isinstance(values, list) else [])
    ]


def _declared_items(node: dict[str, Any], names: dict[str, str]) -> str:
    floors = node.get("min_share") or {}
    items = []
    for item in node.get("value") or []:
        name = names.get(str(item), str(item))
        if item in floors:
            name = DECLARED_TEXTS["share_floor"].format(name=name, pct=percent_text(floors[item]))
        items.append(name)
    return "、".join(items)


def declared_lines(declared: dict[str, Any]) -> list[str]:
    """「案件側が書いた要望」: what was declared, and what was left unwritten."""
    lines, missing = [], []
    for key, names in (("surfaces", PLACE_NAMES), ("verification", TEST_TYPE_SHORT_NAMES)):
        node = declared.get(key) or {}
        if node.get("kind") == "declared":
            lines.append(DECLARED_TEXTS[key].format(items=_declared_items(node, names)))
        else:
            missing.append(DECLARED_ITEM_NAMES[key])
    rhythm = declared.get("change_rhythm") or {}
    for key in ("active_days_180d_min", "median_gap_days_max", "p90_gap_days_max"):
        node = rhythm.get(key) or {}
        if node.get("kind") == "declared":
            lines.append(DECLARED_TEXTS[key].format(n=node.get("value")))
        else:
            missing.append(DECLARED_ITEM_NAMES[key])
    inputs = declared.get("inputs") or {}
    if inputs.get("kind") == "declared":
        lines.append(
            DECLARED_TEXTS["inputs"].format(
                items="、".join(_named(inputs.get("value"), INPUT_NAMES))
            )
        )
    else:
        missing.append(DECLARED_ITEM_NAMES["inputs"])
    if (declared.get("role_lens") or {}).get("kind") != "declared":
        missing.append(DECLARED_ITEM_NAMES["role_lens"])
    if missing:
        lines.append(DECLARED_TEXTS["not_declared"].format(items="、".join(missing)))
    return lines


def title_value(declared: dict[str, Any]) -> str | None:
    """The declared title on one line: it goes into a heading, so no line breaks."""
    node = declared.get("title") or {}
    value = node.get("value") if node.get("kind") == "declared" else None
    text = " ".join(str(value).split()) if value else ""
    return text or None


def project_section(report: dict[str, Any]) -> list[str]:
    """The project's own declaration, then the repository's way of working (no people)."""
    declared = report.get("declared") or {}
    observed = report.get("observed") or {}
    title = title_value(declared)
    heading = (
        HEADINGS["project_title"].format(title=title)
        if title
        else HEADINGS["project_title_untitled"]
    )
    lines = [heading, "", SECTION_TEXTS["project_intro"], ""]
    lines += [
        HEADINGS["declared"],
        "",
        *declared_lines(declared),
        "",
        SECTION_TEXTS["declared_note"],
        "",
    ]
    lines += [HEADINGS["repository"], ""]
    if observed.get("kind") != "observed":
        return [*lines, SECTION_TEXTS["project_no_repository"], ""]
    lines += [SECTION_TEXTS["project_people"], ""]
    lines += work_blocks(observed, scope="変更", person=False)
    lines += _unseen(observed, person=False)
    prov = report.get("provenance") or {}
    lines += _limits(("days", "places", "p90", "scales", *_shallow_notes(prov), "verify"))
    return lines + evidence_table(observed, prov, person=False)


def _shallow_notes(prov: dict[str, Any]) -> tuple[str, ...]:
    """No note when project-v1 proves the clone is not shallow (the range is then
    全履歴); a recorded shallow clone, or a report saved before 0.9.1 that does not
    say (J3), keeps the range 「までの履歴」 and the note says which."""
    shallow = recorded_shallow(prov)
    if shallow is False:
        return ()
    return ("shallow_repo_recorded",) if shallow else ("shallow_repo",)
