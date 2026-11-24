"""Lines for the person-facing actor section that serve the person themself.

`grift actor` already writes plain sentences from the record (trait_sections).
This module adds two things to that section, under the same consent gate (T7):

* how the person can use the record before sharing it (review, career summary,
  interview preparation), so that the report is useful without anyone else;
* the forge and tracker evidence, when it was supplied, placed beside the other
  sentences instead of only in the detail layer (#24).

The wording uses counts and periods from the JSON only. It never compares the
person with anyone, never sums, and never turns a count into a verdict.
"""

from __future__ import annotations

from typing import Any

from tep_core.trait_profile import as_int, place_sentences

HEADING_USE = "## この記録の使い方（本人向け）"
HEADING_COORDINATION = "### レビューと課題の記録"

USE_REVIEW = (
    "- 振り返り: 「進め方」の文は、件数と期間がそろった事実だけです。自分の記憶と照らし、"
    "足りない仕事を書き足してください。"
)
USE_CAREER = (
    "- 経歴の要約: 「根拠」の表の行は、数えたもの・件数・期間がそろっています。"
    "職務経歴書や自己紹介の数字に、そのまま写せます。"
)
USE_INTERVIEW = "- 評価や昇進の面談の前: 「面談で確かめたいこと」を、自分への問いとして読めます。"
USE_SHARE = (
    "- 共有するとき: 見せる範囲は `--disclosure-level` で選びます。選んだ範囲と使い方の条件は、"
    "末尾の「共有するときの条件」と JSON の `usage_terms` に残ります。"
)
CAREER_DRAFT = "- 経歴の要約の下書き（事実だけ）: {end} までの記録について、{lead}"

REVIEW_SENTENCE = (
    "渡された forge の記録には、自分が書いたレビューのイベントが {events} 件あり、"
    "{prs} 件のプルリクエストに付いています{period}。"
)
TRACKER_SENTENCE = "渡された tracker の記録には、自分が関わった課題が {issues} 件あり、イベントは {events} 件です{period}。"
PARTIAL_NOTE = "記録の範囲が一部だけなので、件数は少なくとも、という意味です。"
COORDINATION_LIMIT = (
    "レビューの良し悪しや課題の扱い方は測っていません。他の人が自分の変更を承認した記録は、"
    "この版では数えていません。"
)


def _count(node: Any) -> int | None:
    if isinstance(node, dict) and node.get("kind") == "observed":
        return as_int(node.get("value"))
    return None


def _period(report: dict[str, Any]) -> str:
    window = (report.get("input_coverage") or {}).get("event_window") or {}
    if window.get("start") and window.get("end"):
        return f"（記録の期間: {window['start']}〜{window['end']}）"
    return ""


def self_use_lines(report: dict[str, Any]) -> list[str]:
    lines = [HEADING_USE, "", USE_REVIEW, USE_CAREER]
    end = (report.get("provenance") or {}).get("observation_date")
    sentences, top = place_sentences(report.get("surface_profile") or {}, scope="自分の変更")
    if end and top and sentences:
        lines.append(CAREER_DRAFT.format(end=end, lead=sentences[0]))
    lines += [USE_INTERVIEW, USE_SHARE, ""]
    return lines


def coordination_lines(report: dict[str, Any]) -> list[str]:
    """Review and issue records the person supplied; empty when none were supplied."""
    profile = report.get("coordination_profile") or {}
    period = _period(report)
    sentences: list[str] = []
    review = profile.get("review") or {}
    if review.get("kind") == "observed":
        events = _count(review.get("review_event_count"))
        prs = _count(review.get("reviewed_pr_count"))
        if events is not None and prs is not None:
            sentences.append(REVIEW_SENTENCE.format(events=events, prs=prs, period=period))
    tracker = profile.get("tracker") or {}
    if tracker.get("kind") == "observed":
        events = _count(tracker.get("event_count"))
        issues = _count(tracker.get("distinct_issue_count"))
        if events is not None and issues is not None:
            sentences.append(TRACKER_SENTENCE.format(issues=issues, events=events, period=period))
    if not sentences:
        return []
    partial = any(
        "partial" in str(note)
        for block in (review, tracker)
        for note in (block.get("limitations") or [])
    )
    text = "".join(sentences) + (PARTIAL_NOTE if partial else "") + COORDINATION_LIMIT
    return [HEADING_COORDINATION, "", text, ""]
