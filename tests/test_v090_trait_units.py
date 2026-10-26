"""v0.9.0 (b): the decision-table branches, one boundary at a time.

tests/test_v090_trait_profile.py runs the CLI on real git; these cases pin the
rows a small fixture never reaches (ties, the 7-day and half boundaries, 20
gaps, merges and tags, a declared share floor, 10,000 gaps).
"""

from __future__ import annotations

import pytest

from tep_core import trait_tables as tables
from tep_core.trait_alignment import alignment_section
from tep_core.trait_profile import (
    actor_questions,
    count_from_share,
    not_shown_reason,
    place_sentences,
    rhythm_lead,
    rhythm_sentences,
    verify_sentences,
    work_sentences,
)
from tep_core.trait_sections import declared_lines, project_section
from tep_core.v2_constants import SURFACES


def _observed(value: float, n: int = 40) -> dict:
    return {"kind": "observed", "value": value, "sample_size": n}


def _rhythm(
    *, n: int = 40, median: float = 2.0, p90: float = 5.0, burst: float = 0.3, long: float = 0.0
) -> dict:
    return {
        "kind": "observed",
        "interval_sample_size": {"kind": "observed", "value": n, "unit": "gaps"},
        "median_gap_days": _observed(median, n),
        "p90_gap_days": _observed(p90, n),
        "burst_share_le_2d": _observed(burst, n),
        "long_gap_share_ge_30d": _observed(long, n),
    }


@pytest.mark.parametrize(
    ("p90", "long", "burst", "lead"),
    [
        (7.0, 0.0, 0.1, "rhythm_steady"),  # 10 回に 9 回が 7 日以内、長い空きなし
        (7.0001, 0.0, 0.9, None),  # 7 日を超えた、長い空きなし: 先頭の文は出さない
        (40.0, 0.025, 0.5, "rhythm_bursty"),  # 30 日以上が 1 回、2 日以内がちょうど半分
        (40.0, 0.025, 0.4999, None),  # 半分に届かない
        (6.0, 0.025, 0.2, None),  # 長い空きがあれば「間をあまり空けずに」ではない
    ],
)
def test_rhythm_lead_uses_only_the_published_boundaries(p90, long, burst, lead) -> None:
    assert rhythm_lead(_rhythm(p90=p90, long=long, burst=burst)) == lead


def test_rhythm_needs_twenty_gaps() -> None:
    assert rhythm_sentences(_rhythm(n=19)) == [tables.SENTENCES["rhythm_few"].format(n=19)]
    lines = rhythm_sentences(_rhythm(n=20, median=2.05, p90=4.01, burst=0.25, long=0.0))
    assert lines == [
        tables.SENTENCES["rhythm_steady"],
        tables.SENTENCES["rhythm_detail"].format(median="2.1", p90="4.0", n=20, burst=5, long=0),
    ]


def test_counts_from_rounded_shares_say_about_when_they_cannot_be_exact() -> None:
    assert count_from_share(_observed(0.3333), 9999) == "3333"
    assert count_from_share(_observed(0.3333), 10000) == "約 3333"


def _surface(counts: dict[str, int], n: int) -> dict:
    values = {name: counts.get(name, 0) for name in SURFACES}
    return {
        "kind": "observed",
        "population": n,
        "surface_commit_counts": {"kind": "observed", "values": values},
    }


def test_place_sentences_skip_test_list_ties_and_cap_the_rest() -> None:
    counts = {
        "test": 40,
        "backend": 12,
        "frontend": 12,
        "docs": 5,
        "data": 4,
        "config": 3,
        "platform": 2,
        "other": 1,
    }
    lines, top = place_sentences(_surface(counts, 40), scope="自分の変更")
    assert top == "画面、サーバー側の処理"  # SURFACES order: frontend before backend
    assert lines[0] == tables.SENTENCES["place_lead_tie"].format(
        places="画面、サーバー側の処理", scope="自分の変更", n=40, c=12
    )
    assert lines[1] == tables.SENTENCES["place_following"].format(
        items="文書（5 件）、データベースの定義（4 件）、設定ファイル（3 件）、実行環境の設定（2 件）"
    )


def test_place_sentences_need_twenty_changes() -> None:
    lines, top = place_sentences(_surface({"backend": 10}, 19), scope="変更")
    assert lines == [tables.SENTENCES["place_few"].format(scope="変更", n=19)]
    assert top is None


def test_verify_sentences_cover_pairing_and_not_observed() -> None:
    profile = {
        "kind": "observed",
        "test_touch_share": {"kind": "observed", "value": 0.5, "sample_size": 40, "test_touch": 20},
        "test_type_distribution": {"kind": "observed", "values": {"unit": 15, "e2e": 6}},
        "fix_with_test_pairing": {
            "kind": "observed",
            "value": 0.8,
            "sample_size": 25,
            "with_test": 20,
        },
    }
    assert verify_sentences(profile) == [
        tables.SENTENCES["verify_lead"].format(n=40, c=20),
        tables.SENTENCES["verify_types"].format(
            types="部品ごとに確かめる単体テスト（15 件）と、画面から通しで動かす E2E テスト（6 件）"
        ),
        tables.SENTENCES["verify_fix_paired"].format(s=25, w=20),
    ]
    missing = {"kind": "not_observed", "reason": "insufficient_population"}
    assert verify_sentences(missing) == [
        tables.SENTENCES["verify_not_observed"].format(
            reason=tables.PLAIN_REASONS["insufficient_population"]
        )
    ]


def _metric(numerator: int | None, denominator: int) -> dict:
    if numerator is None:
        return {
            "kind": "not_observed",
            "reason": "insufficient_population",
            "denominator": denominator,
        }
    return {"kind": "observed", "numerator": numerator, "denominator": denominator}


def _role(create, modify, merges=0, releases=0, n=40) -> dict:
    return {
        "kind": "observed",
        "consent_basis": "identity_file_explicit_consent:recorded-explicit-consent",
        "window": {"start": "2026-01-02T00:00:00Z", "end": "2026-06-30T00:00:00Z"},
        "dimensions": {
            "work_type": {"create": _metric(create, n), "modify": _metric(modify, n)},
            "process_position": {"integrator": _metric(merges, n), "release": _metric(releases, n)},
        },
    }


def _work(role: dict, total: int | None = 40) -> dict:
    """The fields work_sentences reads: the role, the own total and the observation date."""
    verification = {"kind": "observed", "sample_size": total} if total is not None else {}
    return {
        "role_profile": role,
        "verification_profile": verification,
        "provenance": {"observation_date": "2026-08-31"},
    }


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (_role(10, 10), [tables.SENTENCES["work_equal"].format(c=10)]),
        (
            _role(25, 15, merges=3),
            [
                tables.SENTENCES["work_create_more"].format(m=15, c=25),
                tables.SENTENCES["work_merge_only"].format(i=3),
            ],
        ),
        (
            _role(15, 25, releases=2),
            [
                tables.SENTENCES["work_modify_more"].format(m=25, c=15),
                tables.SENTENCES["work_release_only"].format(r=2),
            ],
        ),
        (
            _role(15, 25, merges=1, releases=2),
            [
                tables.SENTENCES["work_modify_more"].format(m=25, c=15),
                tables.SENTENCES["work_process"].format(i=1, r=2),
            ],
        ),
        (_role(None, None, n=12), [tables.SENTENCES["work_few"].format(n=12)]),
    ],
)
def test_work_sentences_follow_the_table(role, expected) -> None:
    denominator = role["dimensions"]["work_type"]["create"]["denominator"]
    assert work_sentences(_work(role, total=denominator)) == expected


def test_questions_are_capped_and_follow_the_order() -> None:
    report = {
        "surface_profile": _surface({"backend": 30, "other": 3}, 40),
        "change_rhythm": _rhythm(p90=40.0, long=0.05, burst=0.7),
        "verification_profile": {
            "kind": "observed",
            "sample_size": 40,  # the own total role_profile is checked against (R11)
            "fix_with_test_pairing": {"kind": "observed", "sample_size": 25, "with_test": 20},
        },
        "role_profile": _role(10, 30, releases=2),
    }
    assert actor_questions(report) == [
        tables.QUESTIONS["ask_outside"].format(place="サーバー側の処理"),
        tables.QUESTIONS["ask_rhythm_bursty"],
        tables.QUESTIONS["ask_fix_without_test"].format(s=25, u=5),
        tables.QUESTIONS["ask_release"].format(r=2),
    ]  # the fifth row (unclassified files) is past max_questions


@pytest.mark.parametrize(
    ("subject", "consent", "reason"),
    [
        ({"selection": "explicit_actor", "attribution_state": "claimed"}, True, None),
        ({"selection": "explicit_actor", "attribution_state": "claimed"}, False, "no_consent"),
        ({"selection": "explicit_actor", "attribution_state": "verified"}, True, "admin_verified"),
        (
            {"selection": "explicit_actor", "attribution_state": "inferred"},
            False,
            "explicit_nonconsent",
        ),
        ({"selection": "inferred_actor", "attribution_state": None}, False, "public_inferred"),
        ({"selection": None, "attribution_state": "claimed"}, True, "unknown"),
    ],
)
def test_person_facing_text_needs_claimed_and_consent(subject, consent, reason) -> None:
    role = (
        _role(10, 10)
        if consent
        else {"kind": "not_observed", "reason": "consenting_actor_required"}
    )
    assert not_shown_reason({"subject": subject, "role_profile": role}) == reason
    if reason is not None:
        assert reason in tables.NOT_SHOWN


def test_project_without_a_repository_says_so() -> None:
    report = {
        "declared": {"title": {"kind": "declared", "value": "画面の刷新"}},
        "observed": {"kind": "not_observed"},
    }
    lines = project_section(report)
    assert lines[0] == tables.HEADINGS["project_title"].format(title="画面の刷新")
    assert tables.SECTION_TEXTS["project_no_repository"] in lines


def test_declared_share_floor_is_written_as_a_percentage() -> None:
    declared = {
        "surfaces": {
            "kind": "declared",
            "value": ["frontend", "docs"],
            "min_share": {"frontend": 0.3},
        },
        "verification": {"kind": "not_declared"},
        "inputs": {"kind": "declared", "value": ["git"]},
    }
    lines = declared_lines(declared)
    assert lines[0] == tables.DECLARED_TEXTS["surfaces"].format(
        items="画面（変更の 30% 以上）、文書"
    )
    assert lines[-1].startswith(
        f"- 書いていないこと: {tables.DECLARED_ITEM_NAMES['verification']}、変更を出した日の数"
    )


def _axis(name, verdict, *, declared=None, observed=None) -> dict:
    return {
        "axis": name,
        "comparison": verdict,
        "declared": declared or {},
        "observed": observed or {},
    }


def _bob_alignment(axes: list) -> dict:
    return {
        "subject": {
            "actor_canonical_id": "bob",
            "actor_selection": "explicit_actor",
            "actor_attribution_state": "claimed",
            "actor_consent": "recorded-explicit-consent",
        },
        "declared": {"title": {"kind": "declared", "value": "画面の刷新"}},
        "actor_observed": {
            "surface_profile": _surface({"frontend": 9, "docs": 4}, 40),
            "verification_profile": {
                "test_type_share": {"population": 12},
                "test_type_distribution": {"values": {"e2e": 2}},
            },
        },
        "axes": axes,
    }


def test_alignment_rows_and_questions_for_share_floors_and_presence() -> None:
    axes = [
        _axis(
            "surfaces.frontend",
            "outside_declared_range",
            declared={"kind": "declared", "value": 0.3, "unit": "commit_share"},
            observed={"kind": "observed", "value": 0.225, "unit": "commit_share"},
        ),
        _axis(
            "surfaces.docs",
            "overlap",
            declared={"value": "docs", "unit": "surface"},
            observed={"kind": "observed", "value": 4},
        ),
    ]
    text = "\n".join(alignment_section(_bob_alignment(axes)))
    assert "| 文書 | 記録の変更 40 件のうち 4 件 |" in text
    floor = tables.ALIGNMENT_TEXTS["floor_own"].format(pct="30%")
    record = tables.ALIGNMENT_TEXTS["record_own"].format(n=40, c=9)
    assert (
        tables.ALIGNMENT_TEXTS["ask_below_share"].format(item="画面", floor=floor, record=record)
        in text
    )
    assert "この記録では記録の" not in text  # LOW: the record is not named twice


def test_alignment_questions_for_gaps_and_unobserved_inputs() -> None:
    axes = [
        _axis(
            "change_rhythm.p90_gap_days",
            "outside_declared_range",
            declared={"kind": "declared", "value": 14},
            observed={"kind": "observed", "value": 18.572},
        ),
        _axis(
            "inputs.tracker",
            "not_observed",
            declared={"value": "tracker"},
            observed={"kind": "not_observed", "reason": "tracker_export_not_provided"},
        ),
    ]
    text = "\n".join(alignment_section(_bob_alignment(axes)))
    gap = tables.ALIGNMENT_TEXTS["ask_outside_gap"].format(
        item=tables.RHYTHM_ITEM_NAMES["p90_gap_days"], declared=14, observed="18.6"
    )
    assert gap in text
    tracker = tables.ALIGNMENT_TEXTS["ask_not_observed"].format(
        item="課題管理の記録（tracker）", reason=tables.PLAIN_REASONS["tracker_export_not_provided"]
    )
    assert tracker in text


def test_alignment_says_plainly_when_nothing_overlaps_or_needs_asking() -> None:
    report = {
        "subject": {
            "actor_canonical_id": "bob",
            "actor_selection": "explicit_actor",
            "actor_attribution_state": "claimed",
            "actor_consent": "recorded-explicit-consent",
        },
        "declared": {},
        "actor_observed": {},
        "axes": [],
    }
    text = "\n".join(alignment_section(report))
    assert tables.HEADINGS["alignment_title_untitled"].format(cid="bob") in text
    assert tables.ALIGNMENT_TEXTS["no_overlap"] in text
    assert tables.ALIGNMENT_TEXTS["no_questions"] in text


# --- review round 1 (H1-H2, M1-M8, L2-L9): one test per finding ---------------

CONSENT = "identity_file_explicit_consent:recorded-explicit-consent"


def _actor_report(*, role: dict, total: int = 40, n: int = 40) -> dict:
    """A claimed, consented actor report-v2 with the blocks the section reads."""
    return {
        "subject": {
            "kind": "actor",
            "selection": "explicit_actor",
            "canonical_id": "alice",
            "attribution_state": "claimed",
        },
        "provenance": {
            "observation_date": "2026-08-31",
            "git_window": {"start": "2026-03-04", "end": "2026-08-31", "days": 180},
            "revision_completeness": {"shallow": False, "promisor": False, "complete": True},
        },
        "activity": {"tenant_commits": {"kind": "observed", "value": total + 30}},  # not as-of cut
        "surface_profile": _surface({"backend": 25, "docs": 6}, n),
        "change_rhythm": {**_rhythm(n=30), "window_population": 31},
        "verification_profile": {
            "kind": "observed",
            "sample_size": total,
            "test_touch_share": {
                "kind": "observed",
                "value": 0.25,
                "sample_size": total,
                "test_touch": 10,
            },
            "test_type_distribution": {"kind": "observed", "values": {"unit": 10}},
            "fix_with_test_pairing": {"kind": "not_observed", "reason": "no_fix_or_revert_commits"},
        },
        "role_profile": role,
        "input_coverage": {"forge": {"kind": "not_observed"}, "tracker": {"kind": "not_observed"}},
    }


def _section_text(report: dict) -> str:
    from tep_core.trait_sections import actor_section

    return "\n".join(actor_section(report))


def test_counted_range_is_the_observation_date_history_not_role_window() -> None:
    """H1: role_profile.window spans every author and ignores --as-of; never quoted."""
    role = _role(10, 30, n=40)
    role["window"] = {"start": "2025-01-01T00:00:00Z", "end": "2026-10-04T00:00:00Z"}
    text = _section_text(_actor_report(role=role))
    assert tables.SECTION_TEXTS["record_scope"].format(end="2026-08-31", total=40) in text
    assert "2025-01-01" not in text and "2026-10-04" not in text


def test_make_block_is_left_out_when_role_profile_counts_other_commits() -> None:
    """H1: 70 role commits (later work included) against 40 counted to the observation date."""
    role = _role(32, 38, releases=2, n=70)
    role["window"]["end"] = "2026-10-04T00:00:00Z"
    text = _section_text(_actor_report(role=role, total=40))
    assert tables.SENTENCES["work_scope_later"].format(n=70, total=40) in text
    assert tables.QUESTIONS["ask_release"].format(r=2) not in text
    assert "手を入れる変更 / 新しく作る変更" not in text  # no evidence row for that block
    assert tables.SECTION_TEXTS["unseen_no_release"] not in text


def test_a_shallow_history_gets_the_reason_instead_of_the_section() -> None:
    """R7: a shallow clone counts its oldest change as adding every file; nothing is described."""
    report = _actor_report(role={"kind": "not_observed", "reason": "history_incomplete"})
    report["provenance"]["revision_completeness"] = {
        "shallow": True,
        "promisor": False,
        "complete": False,
    }
    assert not_shown_reason(report) == "shallow_history"
    text = _section_text(report)
    reason = tables.NOT_SHOWN["shallow_history"]
    assert tables.NOT_SHOWN_SHALLOW_TEMPLATE.format(reason=reason) in text
    for fragment in ("いちばん多いのは", tables.HEADINGS["questions"], "数えた範囲"):
        assert fragment not in text, fragment
    report["role_profile"] = {"kind": "not_observed", "reason": "consenting_actor_required"}
    assert not_shown_reason(report) == "no_consent"  # the consent gate comes first


def test_a_partial_clone_keeps_the_section_and_names_the_missing_role_numbers() -> None:
    """M1: a promisor clone has every commit; role_profile refuses it after the consent check."""
    report = _actor_report(role={"kind": "not_observed", "reason": "history_incomplete"})
    report["provenance"]["revision_completeness"] = {
        "shallow": False,
        "promisor": True,
        "complete": False,
    }
    assert not_shown_reason(report) is None
    text = _section_text(report)
    reason = tables.PLAIN_REASONS["history_incomplete"]
    assert tables.SENTENCES["work_not_observed"].format(reason=reason) in text
    no_consent = _actor_report(role={"kind": "not_observed", "reason": "consenting_actor_required"})
    assert not_shown_reason(no_consent) == "no_consent"


def test_no_release_note_needs_releases_counted_as_zero() -> None:
    """M2: an uncounted release total is not 'no release'."""
    counted_zero = _section_text(_actor_report(role=_role(10, 30, releases=0)))
    assert tables.SECTION_TEXTS["unseen_no_release"] in counted_zero
    role = _role(10, 30)
    role["dimensions"]["process_position"]["release"] = _metric(None, 12)
    assert tables.SECTION_TEXTS["unseen_no_release"] not in _section_text(_actor_report(role=role))


def test_evidence_rows_follow_the_twenty_gate() -> None:
    """M6: a block below 20 shows no number in the evidence table either."""
    report = _actor_report(role=_role(None, None, n=12), total=12, n=12)
    report["change_rhythm"] = {**_rhythm(n=11), "window_population": 12}
    report["verification_profile"]["test_touch_share"] = {
        "kind": "not_observed",
        "reason": "insufficient_population",
        "population": 12,
        "test_touch": 6,
    }
    text = _section_text(report)
    evidence = (
        text.split(tables.HEADINGS["evidence"], 1)[-1]
        if tables.HEADINGS["evidence"] in text
        else ""
    )
    for fragment in (
        "に触れた変更",
        tables.EVIDENCE_ROWS["rhythm_median"],
        tables.EVIDENCE_ROWS["verify_touch"],
    ):
        assert fragment not in evidence, fragment
    assert "12 件中 6 件" not in text
    assert "12 件のうち 6 件" not in text  # the sentence form of the same share (MM)


def test_rhythm_with_ten_thousand_gaps_picks_no_lead() -> None:
    """L6: four decimals cannot rule out one 30-day gap among 10,000 or more."""
    assert rhythm_lead(_rhythm(n=10_000, p90=3.0, long=0.0, burst=0.6)) is None
    assert rhythm_lead(_rhythm(n=9_999, p90=3.0, long=0.0, burst=0.6)) == "rhythm_steady"


def test_a_tests_only_actor_keeps_the_places_heading() -> None:
    """L3: every change touched tests only; the block says so instead of vanishing."""
    lines, top = place_sentences(_surface({"test": 30}, 30), scope="自分の変更")
    assert lines == [tables.SENTENCES["place_tests_only"].format(scope="自分の変更", n=30)]
    assert top is None


@pytest.mark.parametrize(
    ("build", "scaled"),
    [
        (lambda k: rhythm_sentences(_rhythm(n=30 * k, median=2.0, p90=5.0, burst=0.3)), "rhythm"),
        (
            lambda k: verify_sentences(
                {
                    "kind": "observed",
                    "test_touch_share": {
                        "kind": "observed",
                        "value": 0.25,
                        "sample_size": 40 * k,
                        "test_touch": 10 * k,
                    },
                    "test_type_distribution": {"kind": "observed", "values": {"unit": 10 * k}},
                    "fix_with_test_pairing": {
                        "kind": "observed",
                        "sample_size": 20 * k,
                        "with_test": 15 * k,
                    },
                }
            ),
            "verify",
        ),
        (
            lambda k: work_sentences(_work(_role(10 * k, 30 * k, merges=k, n=40 * k), 40 * k)),
            "work",
        ),
        # Baselines that pick no rhythm lead and "create more": a rule that keyed
        # on volume (n >= 100, create >= 100) would change them at 10x (V1, V2).
        (lambda k: rhythm_sentences(_rhythm(n=30 * k, p90=9.0, burst=0.3)), "rhythm-no-lead"),
        (lambda k: work_sentences(_work(_role(30 * k, 10 * k, n=40 * k), 40 * k)), "work-create"),
    ],
)
def test_every_block_picks_the_same_sentence_at_ten_times_the_volume(build, scaled) -> None:
    """T1: only the numbers change; the sentence chosen is the same at 1x and 10x."""
    import re

    skeletons = [re.sub(r"\d+(\.\d+)?", "N", "".join(build(k))) for k in (1, 10)]
    assert skeletons[0] == skeletons[1], (scaled, skeletons)


def _claimed_alignment(
    axes: list,
    *,
    actor_observed: dict | None = None,
    state: str | None = "claimed",
    consent: bool = True,
) -> dict:
    selection = "inferred_actor" if state is None else "explicit_actor"
    subject = {
        "actor_canonical_id": "bob",
        "actor_selection": selection,
        "actor_attribution_state": state,
    }
    if consent and state is not None:
        subject["actor_consent"] = "recorded-explicit-consent"
    return {
        "subject": subject,
        "declared": {},
        "actor_observed": actor_observed
        if actor_observed is not None
        else {"surface_profile": _surface({"backend": 25}, 40)},
        "axes": axes,
    }


def test_alignment_zero_active_days_becomes_a_question() -> None:
    """H2: observed_zero on a day minimum was dropped from the opening section."""
    axis = _axis(
        "change_rhythm.active_days_180d",
        "observed_zero",
        declared={"kind": "declared", "value": 20},
        observed={"kind": "observed", "value": 0},
    )
    text = "\n".join(alignment_section(_claimed_alignment([axis])))
    assert tables.ALIGNMENT_TEXTS["ask_outside_days"].format(declared=20, observed=0) in text
    assert tables.ALIGNMENT_TEXTS["no_questions"] not in text


def test_alignment_asks_about_a_verdict_it_has_no_row_for() -> None:
    """H2: an unhandled verdict and axis is asked about, never silently dropped."""
    axis = _axis(
        "surfaces.backend", "mixed_future_verdict", observed={"kind": "observed", "value": 3}
    )
    text = "\n".join(alignment_section(_claimed_alignment([axis])))
    assert (
        tables.ALIGNMENT_TEXTS["ask_other"].format(
            item="サーバー側の処理", state="mixed_future_verdict"
        )
        in text
    )


def test_alignment_rounds_gaps_up_next_to_an_upper_bound() -> None:
    """M3: 7.0417 against 'within 7' is outside, so it must not print as 7.0."""
    axis = _axis(
        "change_rhythm.median_gap_days",
        "outside_declared_range",
        declared={"kind": "declared", "value": 7},
        observed={"kind": "observed", "value": 7.0417},
    )
    text = "\n".join(alignment_section(_claimed_alignment([axis])))
    item = tables.RHYTHM_ITEM_NAMES["median_gap_days"]
    assert (
        tables.ALIGNMENT_TEXTS["ask_outside_gap"].format(item=item, declared=7, observed="7.1")
        in text
    )


def test_alignment_cells_drop_the_denominator_below_twenty_or_when_unknown() -> None:
    """M6 and M7: 12 commits, and a saved alignment without actor_observed."""
    axis = _axis(
        "surfaces.backend",
        "overlap",
        declared={"value": "backend"},
        observed={"kind": "observed", "value": 6},
    )
    small = _claimed_alignment(
        [axis], actor_observed={"surface_profile": _surface({"backend": 6}, 12)}
    )
    assert "| サーバー側の処理 | 6 件 |" in "\n".join(alignment_section(small))
    saved = _claimed_alignment([axis], actor_observed={})
    text = "\n".join(alignment_section(saved))
    assert "| サーバー側の処理 | 6 件 |" in text and "None" not in text


@pytest.mark.parametrize(
    ("state", "consent", "reason"),
    [
        ("claimed", True, None),
        ("claimed", False, "no_consent"),
        ("verified", True, "admin_verified"),
        (None, False, "public_inferred"),
    ],
)
def test_alignment_questions_follow_the_actor_basis(state, consent, reason) -> None:
    """T7: questions need a claimed identity and the consent record (user decision 2026-10-26)."""
    axis = _axis(
        "inputs.forge",
        "not_observed",
        observed={"kind": "not_observed", "reason": "forge_export_not_provided"},
    )
    report = _claimed_alignment([axis], state=state, consent=consent)
    text = "\n".join(alignment_section(report))
    assert (tables.ALIGNMENT_TEXTS["ask_forge"] in text) is (reason is None)
    if reason is not None:
        not_shown = tables.ALIGNMENT_TEXTS["questions_not_shown"].format(
            reason=tables.NOT_SHOWN[reason]
        )
        assert not_shown in text
    assert "が共有した" not in text and "自分の変更" not in text


def test_titles_cannot_break_out_of_their_heading() -> None:
    """L9: a title with a line break stays on the heading line."""
    from tep_core.trait_sections import title_value

    assert (
        title_value({"title": {"kind": "declared", "value": "決済\n# 偽の見出し"}})
        == "決済 # 偽の見出し"
    )


def test_section_notes_follow_the_inputs_and_skip_non_work_places() -> None:
    """M10: the forge/tracker note matches what is missing; test/other/vendor are not work areas."""
    report = _actor_report(role=_role(10, 30))
    report["input_coverage"] = {"forge": {"kind": "not_observed"}, "tracker": {"kind": "observed"}}
    text = _section_text(report)
    assert tables.SECTION_TEXTS["unseen_forge"] in text
    assert tables.SECTION_TEXTS["unseen_tracker"] not in text
    zero_line = next(line for line in text.splitlines() if "ここに出ていない場所" in line)
    listed = zero_line.split("（", 1)[1].split("）", 1)[0].split("、")
    for name in ("test", "generated_vendor", "other"):
        assert tables.PLACE_NAMES[name] not in listed, (name, listed)
    for key in ("own_work", "p90", "verify"):
        assert tables.LIMIT_NOTES[key] in text, key


def test_fix_question_needs_an_unpaired_fix_and_unclassified_count_is_exact() -> None:
    """M10: no question about fixes without tests when every fix changed a test."""
    report = {
        "surface_profile": _surface({"backend": 30, "other": 3}, 40),
        "change_rhythm": _rhythm(p90=40.0, long=0.0, burst=0.1),
        "verification_profile": {
            "kind": "observed",
            "fix_with_test_pairing": {"kind": "observed", "sample_size": 25, "with_test": 25},
        },
        "role_profile": _role(10, 30),
    }
    asks = actor_questions(report)
    assert not any("テストを変えなかった" in ask for ask in asks), asks
    assert tables.QUESTIONS["ask_unclassified"].format(k=3) in asks


def test_alignment_rows_rebuild_counts_days_and_notes_from_the_axes() -> None:
    """M10: test-type counts, the day cell, the not-declared days and the days note."""
    actor = {
        "surface_profile": _surface({"backend": 25}, 40),
        "verification_profile": {
            "test_type_share": {"population": 24},
            "test_type_distribution": {"values": {"unit": 21}},
        },
    }
    axes = [
        _axis(
            "verification.unit",
            "overlap",
            declared={"value": "unit"},
            observed={"kind": "observed", "value": 21},
        ),
        _axis(
            "change_rhythm.active_days_180d",
            "overlap",
            declared={"kind": "declared", "value": 20},
            observed={"kind": "observed", "value": 33},
        ),
    ]
    declared_days = {"change_rhythm": {"active_days_180d_min": {"kind": "declared", "value": 20}}}
    text = "\n".join(
        alignment_section(
            {**_claimed_alignment(axes, actor_observed=actor), "declared": declared_days}
        )
    )
    assert "| 単体テスト | テストのファイルを変えた変更 24 件のうち 21 件 |" in text
    assert "| 変更を出した日の数が 180 日のうち 20 日以上 | 33 日 |" in text
    assert tables.LIMIT_NOTES["days"] in text
    undeclared = [
        _axis(
            "change_rhythm.active_days_180d",
            "not_declared",
            observed={"kind": "observed", "value": 33},
        )
    ]
    other = "\n".join(alignment_section(_claimed_alignment(undeclared, actor_observed=actor)))
    assert tables.ALIGNMENT_TEXTS["not_declared_days"].format(observed=33) in other
    assert tables.LIMIT_NOTES["days"] not in other


# --- review round 2 (R1-R11, M10 residual): one test per finding ---------------


def _evidence_text(text: str) -> str:
    heading = tables.HEADINGS["evidence"]
    return text.split(heading, 1)[1] if heading in text else ""


def _make_block(text: str) -> str:
    return text.split(tables.HEADINGS["make"], 1)[1].split("##", 1)[0]


def test_a_merge_after_the_observation_date_is_not_counted_in() -> None:
    """R1: role_profile.window ends after the date, so its merge may be later work."""
    role = _role(10, 30, merges=1)
    role["window"]["end"] = "2026-09-10T12:00:00Z"
    text = _section_text(_actor_report(role=role))
    assert tables.SENTENCES["work_modify_more"].format(m=30, c=10) in text  # 40 = 40: in range
    assert tables.SENTENCES["work_merge_only"].format(i=1) not in text
    assert tables.EVIDENCE_ROWS["work_merges"] not in _evidence_text(text)
    inside = _section_text(_actor_report(role=_role(10, 30, merges=1)))  # ends 2026-06-30
    assert tables.SENTENCES["work_merge_only"].format(i=1) in inside
    once = tables.SECTION_TEXTS["count_times"].format(c=1)
    assert f"| {tables.EVIDENCE_ROWS['work_merges']} | {once} |" in inside


def _release_text(releases: int, basis: str) -> str:
    report = _actor_report(role=_role(10, 30, releases=releases))
    report["provenance"]["window_basis"] = basis
    return _section_text(report)


def test_release_tags_are_not_counted_in_under_an_explicit_as_of() -> None:
    """R1: tag dates are not in the JSON; under --as-of a tag may come after the date."""
    counted = _release_text(2, "explicit_as_of")
    for fragment in (
        tables.SENTENCES["work_release_only"].format(r=2),
        tables.QUESTIONS["ask_release"].format(r=2),
        tables.SECTION_TEXTS["unseen_no_release"],
    ):
        assert fragment not in counted, fragment
    assert tables.EVIDENCE_ROWS["work_releases"] not in _evidence_text(counted)
    zero = _release_text(0, "explicit_as_of")
    assert tables.SECTION_TEXTS["unseen_no_release"] in zero  # none at all is none before the date
    head = _release_text(2, "legacy_head_date")
    assert tables.SENTENCES["work_release_only"].format(r=2) in head
    assert tables.QUESTIONS["ask_release"].format(r=2) in head
    twice = tables.SECTION_TEXTS["count_times"].format(c=2)
    assert f"| {tables.EVIDENCE_ROWS['work_releases']} | {twice} |" in head


def test_process_rows_show_only_the_counts_that_were_taken() -> None:
    """N22: a release count that was not taken gets no row; the merge count keeps its row."""
    role = _role(10, 30, merges=3)
    role["dimensions"]["process_position"]["release"] = _metric(None, 12)
    evidence = _evidence_text(_section_text(_actor_report(role=role)))
    three = tables.SECTION_TEXTS["count_times"].format(c=3)
    assert f"| {tables.EVIDENCE_ROWS['work_merges']} | {three} |" in evidence
    assert tables.EVIDENCE_ROWS["work_releases"] not in evidence


def test_the_range_is_checked_before_the_few_changes_sentence() -> None:
    """R2: 10 changes up to the date and 8 after: both totals, not '18 changes, too few'."""
    role = _role(None, None, n=18)
    role["window"]["end"] = "2026-09-20T00:00:00Z"
    text = _section_text(_actor_report(role=role, total=10, n=10))
    assert tables.SENTENCES["work_scope_later"].format(n=18, total=10) in text
    assert tables.SENTENCES["work_few"].format(n=18) not in text


def test_the_range_counts_every_own_commit_without_a_test_framework() -> None:
    """R3: no test framework; surface sample_size counts empty commits, population does not."""
    report = _actor_report(role=_role(10, 24, n=34), total=34, n=30)
    report["verification_profile"] = {
        "kind": "not_observed",
        "reason": "no_test_framework_or_directory",
    }
    report["surface_profile"]["sample_size"] = 34
    text = _section_text(report)
    scope = tables.SECTION_TEXTS["record_scope_paths"].format(end="2026-08-31", total=34, paths=30)
    assert scope in text
    assert tables.SENTENCES["work_modify_more"].format(m=24, c=10) in text


def test_scope_differs_names_later_work_only_when_the_role_window_ends_after_the_date() -> None:
    """R3: the role window ends before the date, so the counts differ for another reason."""
    text = _section_text(_actor_report(role=_role(32, 38, n=70), total=40))
    assert tables.SENTENCES["work_scope_differs"].format(n=70, total=40) in text
    assert "観測日のあと" not in _make_block(text)
    assert "role_profile" not in _make_block(text)  # LOW: no internal name in a plain sentence


def test_role_numbers_need_a_known_own_total() -> None:
    """R11: no own commit was counted, so role_profile cannot be checked: no make block."""
    report = _actor_report(role=_role(1, 24, n=25))
    report["verification_profile"] = {"kind": "not_observed", "reason": "no_actor_commits"}
    report["surface_profile"] = {"kind": "not_observed", "reason": "no_actor_commits"}
    text = _section_text(report)
    assert tables.HEADINGS["make"] not in text
    assert "24 件" not in text


def test_saved_alignment_share_floors_print_the_share_not_a_count() -> None:
    """R4: without actor_observed a floor axis carries a share; it never prints as 0 件."""
    floor = {"kind": "declared", "unit": "commit_share"}
    share = {"kind": "observed", "unit": "commit_share"}
    axes = [
        _axis(
            "surfaces.backend",
            "overlap",
            declared={**floor, "value": 0.3},
            observed={**share, "value": 0.5},
        ),
        _axis(
            "surfaces.docs",
            "outside_declared_range",
            declared={**floor, "value": 0.5},
            observed={**share, "value": 0.25},
        ),
        _axis(
            "verification.unit",
            "outside_declared_range",
            declared={**floor, "value": 0.5},
            observed={**share, "value": 0.2},
        ),
    ]
    text = "\n".join(alignment_section(_claimed_alignment(axes, actor_observed={})))
    own = tables.ALIGNMENT_TEXTS["record_own_share"]
    tests = tables.ALIGNMENT_TEXTS["record_tests_share"]
    assert f"| サーバー側の処理（その人の変更の 30% 以上） | {own.format(pct='50%')} |" in text
    below = tables.ALIGNMENT_TEXTS["ask_below_share"]
    docs_floor = tables.ALIGNMENT_TEXTS["floor_own"].format(pct="50%")
    unit_floor = tables.ALIGNMENT_TEXTS["floor_tests"].format(pct="50%")
    assert below.format(item="文書", floor=docs_floor, record=own.format(pct="25%")) in text
    assert below.format(item="単体テスト", floor=unit_floor, record=tests.format(pct="20%")) in text
    assert "0 件" not in text


def test_alignment_records_below_twenty_keep_a_plain_count() -> None:
    """LOW: below 20 changes the record names the count only, and reads without a gap."""
    axis = _axis(
        "surfaces.backend",
        "outside_declared_range",
        declared={"kind": "declared", "value": 0.5, "unit": "commit_share"},
        observed={"kind": "observed", "value": 0.25, "unit": "commit_share"},
    )
    small = _claimed_alignment(
        [axis], actor_observed={"surface_profile": _surface({"backend": 3}, 12)}
    )
    text = "\n".join(alignment_section(small))
    record = tables.ALIGNMENT_TEXTS["record_own_count"].format(c=3)
    floor = tables.ALIGNMENT_TEXTS["floor_own"].format(pct="50%")
    ask = tables.ALIGNMENT_TEXTS["ask_below_share"].format(
        item="サーバー側の処理", floor=floor, record=record
    )
    assert ask in text
    assert "では3" not in text and "12 件" not in text


def test_alignment_rounds_every_gap_up_and_says_so() -> None:
    """R10: one value, 7.0417, read as p90 < median when only the bounded one was rounded up."""
    median = _axis(
        "change_rhythm.median_gap_days",
        "outside_declared_range",
        declared={"kind": "declared", "value": 7},
        observed={"kind": "observed", "value": 7.0417},
    )
    p90 = _axis(
        "change_rhythm.p90_gap_days", "not_declared", observed={"kind": "observed", "value": 7.0417}
    )
    text = "\n".join(alignment_section(_claimed_alignment([median, p90])))
    item = tables.RHYTHM_ITEM_NAMES["p90_gap_days"]
    assert tables.ALIGNMENT_TEXTS["not_declared_gap"].format(item=item, observed="7.1") in text
    assert "7.0 日" not in text
    assert tables.LIMIT_NOTES["gap_rounding"] in text
    assert tables.LIMIT_NOTES["p90"] in text


def test_alignment_notes_on_gaps_only_when_a_gap_is_shown() -> None:
    """N17: no gap in the section, no note about the 90th percentile or about rounding."""
    axis = _axis(
        "surfaces.backend",
        "overlap",
        declared={"value": "backend"},
        observed={"kind": "observed", "value": 25},
    )
    text = "\n".join(alignment_section(_claimed_alignment([axis])))
    assert tables.LIMIT_NOTES["p90"] not in text
    assert tables.LIMIT_NOTES["gap_rounding"] not in text


def test_evidence_gap_days_round_like_the_sentences() -> None:
    """MB: the evidence rows round half up, as the sentence does (7.04 is 7.0, 2.05 is 2.1)."""
    report = _actor_report(role=_role(10, 30))
    report["change_rhythm"] = {**_rhythm(n=30, median=2.05, p90=7.04), "window_population": 31}
    text = _section_text(report)
    days = tables.SECTION_TEXTS["days_with_gaps"]
    assert f"| {tables.EVIDENCE_ROWS['rhythm_p90']} | {days.format(days='7.0', n=30)} |" in text
    assert f"| {tables.EVIDENCE_ROWS['rhythm_median']} | {days.format(days='2.1', n=30)} |" in text
    assert "9 割のところが 7.0 日" in text


def test_project_evidence_does_not_claim_the_whole_history() -> None:
    """R7: project-v1 does not record a shallow clone, so its range is not called 全履歴."""
    observed = {
        "kind": "observed",
        "surface_profile": _surface({"backend": 25, "docs": 6}, 40),
        "change_rhythm": {**_rhythm(n=30), "window_population": 31},
        "verification_profile": {
            "kind": "not_observed",
            "reason": "no_test_framework_or_directory",
        },
        "input_coverage": {"forge": {"kind": "not_observed"}, "tracker": {"kind": "not_observed"}},
    }
    report = {
        "declared": {},
        "observed": observed,
        "provenance": {
            "observation_date": "2026-08-31",
            "git_window": {"start": "2026-03-04", "end": "2026-08-31", "days": 180},
        },
    }
    text = "\n".join(project_section(report))
    assert tables.SECTION_TEXTS["history_repo"].format(end="2026-08-31") in text
    assert "全履歴" not in text
    assert tables.LIMIT_NOTES["shallow_repo"] in text


def test_alignment_from_a_shallow_actor_record_gets_the_reason_only() -> None:
    """Round 3 A: the alignment verdicts come from the truncated history too (as R7)."""
    axis = _axis(
        "surfaces.frontend",
        "overlap",
        declared={"value": "frontend"},
        observed={"kind": "observed", "value": 1},
    )
    report = _claimed_alignment([axis])
    report["actor_provenance"] = {"revision_completeness": {"shallow": True, "complete": False}}
    text = "\n".join(alignment_section(report))
    reason = tables.NOT_SHOWN["shallow_history"]
    assert tables.NOT_SHOWN_SHALLOW_TEMPLATE.format(reason=reason) in text
    for fragment in (tables.HEADINGS["overlap"], tables.HEADINGS["align_questions"], "| 画面 |"):
        assert fragment not in text, fragment
    report["actor_provenance"] = {"revision_completeness": {"shallow": False, "complete": True}}
    assert "| 画面 |" in "\n".join(alignment_section(report))
