"""Plain sentences about one scope's own work, and interview questions (ADR-0002).

Pure functions from report-v2 / project-v1 numbers to Markdown lines. Every
sentence is a row of tep_core.trait_tables formatted with JSON values only, so
the text can be rebuilt from the JSON (T3, T6). Nothing is written back to the
report (T4). The person-facing section needs a claimed identity with a consent
record (T7); every other actor basis gets the reason instead.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from tep_core.actor_basis import (
    CONSENT_CHECKED_REASONS,
    ActorBasis,
    classify_actor_basis,
    consent_recorded,
)
from tep_core.trait_tables import (
    HEADINGS,
    NOT_SHOWN,
    NOT_SHOWN_SHALLOW_TEMPLATE,
    NOT_SHOWN_TEMPLATE,
    PLACE_NAMES,
    PLAIN_REASON_FALLBACK,
    PLAIN_REASONS,
    QUESTIONS,
    SENTENCES,
    TEST_TYPE_NAMES,
    TEST_TYPE_SHORT_NAMES,
    THRESHOLDS,
)
from tep_core.v2_constants import SURFACES, VERIFICATION_TYPES

# Shares carry four decimals, so share × n is an exact count below this n.
_EXACT_COUNT_LIMIT = 10_000
_MIN = int(THRESHOLDS["min_population"])
# CONSENT_CHECKED_REASONS (actor_basis): a role_profile with one of them belongs to
# a consented actor whose role numbers could not be collected. A shallow clone
# also ends there, but not_shown_reason stops it first (R7): its other numbers
# come from the truncated history too.


def as_int(node: Any) -> int | None:
    """An integer, or the integer `value` of an observed node."""
    if isinstance(node, dict):
        node = node.get("value")
    if isinstance(node, bool) or not isinstance(node, int):
        return None
    return node


def as_decimal(node: Any) -> Decimal | None:
    """A number, or the `value` of an observed node, as an exact decimal."""
    if isinstance(node, dict):
        if node.get("kind") not in (None, "observed"):
            return None
        node = node.get("value")
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return Decimal(str(node))


def days_text(value: Decimal, *, ceiling: bool = False) -> str:
    """One decimal: half up, or ceiling next to a declared upper bound."""
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_CEILING if ceiling else ROUND_HALF_UP))


def share_count(share: Any, n: int) -> Decimal:
    """share × n, rounded half up: the count a rounded share stands for."""
    value = as_decimal(share) or Decimal(0)
    return (value * n).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def count_from_share(share: Any, n: int) -> str:
    count = share_count(share, n)
    return f"約 {count}" if n >= _EXACT_COUNT_LIMIT else str(count)


def plain_reason(reason: Any) -> str:
    """A plain reason; an unknown one keeps the recorded name inside a plain sentence."""
    text = PLAIN_REASONS.get(str(reason))
    return text if text is not None else PLAIN_REASON_FALLBACK.format(reason=reason)


def join_long(items: list[str]) -> str:
    """「A、B と、C」 for items that already carry counts."""
    if len(items) <= 1:
        return "".join(items)
    return "、".join(items[:-1]) + "と、" + items[-1]


def place_counts(profile: dict[str, Any]) -> tuple[int | None, dict[str, int]]:
    """(denominator, counts per surface) for the surface sentences."""
    if profile.get("kind") != "observed":
        return None, {}
    values = (profile.get("surface_commit_counts") or {}).get("values") or {}
    counts = {name: as_int(values.get(name)) or 0 for name in SURFACES}
    return as_int(profile.get("population")), counts


def ranked_places(counts: dict[str, int]) -> list[tuple[str, int]]:
    """Places above zero by count, test excluded; SURFACES order breaks ties."""
    return sorted(
        ((name, count) for name, count in counts.items() if name != "test" and count > 0),
        key=lambda item: -item[1],
    )


def place_sentences(profile: dict[str, Any], *, scope: str) -> tuple[list[str], str | None]:
    """Lead and following sentences, and the lead place (or tied places) for the questions."""
    n, counts = place_counts(profile)
    if n is None:
        return [], None
    if n < _MIN:
        return [SENTENCES["place_few"].format(scope=scope, n=n)], None
    ranked = ranked_places(counts)
    if not ranked:
        return [SENTENCES["place_tests_only"].format(scope=scope, n=n)], None
    top = ranked[0][1]
    leaders = [name for name, count in ranked if count == top]
    if len(leaders) == 1:
        lead = SENTENCES["place_lead"].format(
            place=PLACE_NAMES[leaders[0]], scope=scope, n=n, c=top
        )
    else:
        places = "、".join(PLACE_NAMES[name] for name in leaders)
        lead = SENTENCES["place_lead_tie"].format(places=places, scope=scope, n=n, c=top)
    lines = [lead]
    rest = [(name, count) for name, count in ranked if count != top]
    if rest:
        limit = int(THRESHOLDS["max_following_places"])
        items = "、".join(f"{PLACE_NAMES[name]}（{count} 件）" for name, count in rest[:limit])
        lines.append(SENTENCES["place_following"].format(items=items))
    return lines, "、".join(PLACE_NAMES[name] for name in leaders)


def rhythm_lead(rhythm: dict[str, Any]) -> str | None:
    """`rhythm_steady`, `rhythm_bursty` or None. The only boundary-picked sentence."""
    n = as_int(rhythm.get("interval_sample_size"))
    p90 = as_decimal(rhythm.get("p90_gap_days"))
    burst = as_decimal(rhythm.get("burst_share_le_2d"))
    if rhythm.get("kind") != "observed" or n is None or n < _MIN or p90 is None or burst is None:
        return None
    if n >= _EXACT_COUNT_LIMIT:
        return None  # a four-decimal share cannot prove there was no 30-day gap
    long_gaps = share_count(rhythm.get("long_gap_share_ge_30d"), n)
    if long_gaps == 0 and p90 <= Decimal(str(THRESHOLDS["steady_p90_max_days"])):
        return "rhythm_steady"
    if long_gaps >= 1 and burst >= Decimal(str(THRESHOLDS["burst_share_min"])):
        return "rhythm_bursty"
    return None


def rhythm_sentences(rhythm: dict[str, Any]) -> list[str]:
    if rhythm.get("kind") != "observed":
        return []
    n = as_int(rhythm.get("interval_sample_size"))
    median = as_decimal(rhythm.get("median_gap_days"))
    p90 = as_decimal(rhythm.get("p90_gap_days"))
    if n is None:
        return []
    if n < _MIN or median is None or p90 is None:
        return [SENTENCES["rhythm_few"].format(n=n)]
    lead = rhythm_lead(rhythm)
    detail = SENTENCES["rhythm_detail"].format(
        median=days_text(median),
        p90=days_text(p90),
        n=n,
        burst=count_from_share(rhythm.get("burst_share_le_2d"), n),
        long=count_from_share(rhythm.get("long_gap_share_ge_30d"), n),
    )
    return [SENTENCES[lead], detail] if lead else [detail]


def verify_sentences(profile: dict[str, Any]) -> list[str]:
    if profile.get("kind") != "observed":
        if profile.get("kind") == "not_observed":
            return [
                SENTENCES["verify_not_observed"].format(reason=plain_reason(profile.get("reason")))
            ]
        return []
    lines = []
    touch = profile.get("test_touch_share") or {}
    n, c = as_int(touch.get("sample_size")), as_int(touch.get("test_touch"))
    if touch.get("kind") == "observed" and n is not None and c is not None:
        lines.append(SENTENCES["verify_lead"].format(n=n, c=c))
    types = (profile.get("test_type_distribution") or {}).get("values") or {}
    shown = [
        f"{TEST_TYPE_NAMES[name]}（{as_int(types.get(name))} 件）"
        for name in VERIFICATION_TYPES
        if (as_int(types.get(name)) or 0) > 0
    ]
    if shown:
        lines.append(SENTENCES["verify_types"].format(types=join_long(shown)))
    fix = profile.get("fix_with_test_pairing") or {}
    if fix.get("kind") == "observed":
        lines.append(
            SENTENCES["verify_fix_paired"].format(s=fix.get("sample_size"), w=fix.get("with_test"))
        )
    elif as_int(fix.get("population")) is not None:
        lines.append(SENTENCES["verify_fix_few"].format(s=fix.get("population")))
    return lines


def _numerator(dimension: dict[str, Any], key: str) -> int | None:
    node = dimension.get(key) or {}
    return as_int(node.get("numerator")) if node.get("kind") == "observed" else None


def _process_sentence(merges: int | None, releases: int | None) -> list[str]:
    if merges and releases:
        return [SENTENCES["work_process"].format(i=merges, r=releases)]
    if merges:
        return [SENTENCES["work_merge_only"].format(i=merges)]
    if releases:
        return [SENTENCES["work_release_only"].format(r=releases)]
    return []


def _role_denominator(role: dict[str, Any]) -> int | None:
    work = (role.get("dimensions") or {}).get("work_type") or {}
    return as_int((work.get("create") or {}).get("denominator"))


def work_sentences(report: dict[str, Any]) -> list[str]:
    """「関わり方」 from role_profile, when it counts the same commits.

    Without --as-of, role_profile counts every commit up to HEAD, so its counts can
    differ from the section's; the block is then left out with both totals named (T3). The range
    is checked before anything else, and an unknown own total leaves the block
    out (R2, R11).
    """
    role = report.get("role_profile") or {}
    if role.get("kind") != "observed":
        if role.get("reason") in CONSENT_CHECKED_REASONS:
            return [SENTENCES["work_not_observed"].format(reason=plain_reason(role.get("reason")))]
        return []
    total, denominator = own_total(report), _role_denominator(role)
    if total is None or denominator is None:
        return []
    if denominator != total:
        later = _role_window_after_the_date(report) is True
        key = "work_scope_later" if later else "work_scope_differs"
        return [SENTENCES[key].format(n=denominator, total=total)]
    work = (role.get("dimensions") or {}).get("work_type") or {}
    create, modify = _numerator(work, "create"), _numerator(work, "modify")
    if create is None or modify is None:
        return [SENTENCES["work_few"].format(n=denominator)]
    if modify > create:
        lines = [SENTENCES["work_modify_more"].format(m=modify, c=create)]
    elif create > modify:
        lines = [SENTENCES["work_create_more"].format(m=modify, c=create)]
    else:
        lines = [SENTENCES["work_equal"].format(c=create)]
    return lines + _process_sentence(*process_counts(report))


def _role_window_after_the_date(report: dict[str, Any]) -> bool | None:
    """Whether role_profile saw a commit after the observation date (None: unknown).

    Its window spans every author's commits, merges included. With an explicit
    --as-of it ends at that date; otherwise at the latest commit it counted.
    """
    end = str(((report.get("role_profile") or {}).get("window") or {}).get("end") or "")[:10]
    date = str((report.get("provenance") or {}).get("observation_date") or "")
    if not end or not date:
        return None
    return end > date


def process_counts(report: dict[str, Any]) -> tuple[int | None, int | None]:
    """(merges, release tags) the section may state; None when not proven to be in range.

    A zero is always in range. A merge count is in range when role_profile saw no
    commit after the observation date. Tag dates are not in the JSON, so a release
    count is stated only without an explicit --as-of (R1).
    """
    if not role_in_scope(report):
        return None, None
    role = report.get("role_profile") or {}
    process = (role.get("dimensions") or {}).get("process_position") or {}
    merges, releases = _numerator(process, "integrator"), _numerator(process, "release")
    if merges and _role_window_after_the_date(report) is not False:
        merges = None
    if releases and (report.get("provenance") or {}).get("window_basis") == "explicit_as_of":
        releases = None
    return merges, releases


def role_in_scope(report: dict[str, Any]) -> bool:
    """role_profile counts the same own commits as the rest of the section."""
    role = report.get("role_profile") or {}
    if role.get("kind") != "observed":
        return False
    denominator, total = _role_denominator(role), own_total(report)
    return denominator is not None and total is not None and denominator == total


def own_total(report: dict[str, Any]) -> int | None:
    """The actor's own non-merge commits up to the observation date.

    verification_profile and surface_profile honour --as-of; `activity` and
    role_profile do not (0.8.0), so they are never the section's total. The
    surface `population` counts only commits that changed a path, so it is not
    the total either: an empty commit is still a change (R3).
    """
    for value in (
        (report.get("verification_profile") or {}).get("sample_size"),
        (report.get("surface_profile") or {}).get("sample_size"),
    ):
        number = as_int(value)
        if number is not None:
            return number
    return None


def _fix_question(profile: dict[str, Any]) -> str | None:
    fix = profile.get("fix_with_test_pairing") or {}
    if fix.get("kind") == "observed":
        s, w = as_int(fix.get("sample_size")) or 0, as_int(fix.get("with_test")) or 0
        return QUESTIONS["ask_fix_without_test"].format(s=s, u=s - w) if s - w >= 1 else None
    types = (profile.get("test_type_distribution") or {}).get("values") or {}
    present = [(name, as_int(types.get(name)) or 0) for name in VERIFICATION_TYPES]
    present = [item for item in present if item[1] > 0]
    if not present:
        return None
    name, count = max(present, key=lambda item: item[1])  # first maximum in table order
    return QUESTIONS["ask_test_type"].format(type=TEST_TYPE_SHORT_NAMES[name], c=count)


def actor_questions(report: dict[str, Any]) -> list[str]:
    """In table order, at most max_questions; rows that share an order are exclusive."""
    _, top = place_sentences(report.get("surface_profile") or {}, scope="自分の変更")
    asks = [QUESTIONS["ask_outside"].format(place=top) if top else QUESTIONS["ask_outside_plain"]]
    lead = rhythm_lead(report.get("change_rhythm") or {})
    if lead == "rhythm_steady":
        asks.append(QUESTIONS["ask_rhythm_steady"])
    elif lead == "rhythm_bursty":
        asks.append(QUESTIONS["ask_rhythm_bursty"])
    fix = _fix_question(report.get("verification_profile") or {})
    if fix:
        asks.append(fix)
    releases = process_counts(report)[1]
    if releases:
        asks.append(QUESTIONS["ask_release"].format(r=releases))
    _, counts = place_counts(report.get("surface_profile") or {})
    if counts.get("other"):
        asks.append(QUESTIONS["ask_unclassified"].format(k=counts["other"]))
    return asks[: int(THRESHOLDS["max_questions"])]


def not_shown_reason(report: dict[str, Any]) -> str | None:
    """None when the person-facing section may be shown (T7), else a NOT_SHOWN key."""
    subject = report.get("subject") or {}
    basis = classify_actor_basis(subject.get("selection"), subject.get("attribution_state"))
    if basis is not ActorBasis.SELF_CLAIMED:
        return basis.value
    if not consent_recorded(report):
        return "no_consent"
    completeness = (report.get("provenance") or {}).get("revision_completeness") or {}
    if completeness.get("shallow") is True:
        return "shallow_history"
    return None


def not_shown_lines(report: dict[str, Any]) -> list[str]:
    cid = (report.get("subject") or {}).get("canonical_id")
    reason = not_shown_reason(report) or "unknown"
    template = NOT_SHOWN_SHALLOW_TEMPLATE if reason == "shallow_history" else NOT_SHOWN_TEMPLATE
    return [
        HEADINGS["actor_title"].format(cid=cid),
        "",
        template.format(reason=NOT_SHOWN[reason]),
        "",
    ]
