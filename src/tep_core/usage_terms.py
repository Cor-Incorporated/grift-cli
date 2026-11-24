"""Machine-readable usage terms and disclosure level for report-v2 evidence.

The terms restate docs/norms.md in a form a recipient's tooling can read and an
auditor can quote. They are a declaration recorded with the report: nothing here
stops a recipient from ignoring them, and the report says so in `limitations`.
What the level changes is only which observation groups the Markdown view shows;
the JSON keeps every observation because `grift verify` recomputes it.
"""

from __future__ import annotations

from typing import Any

from tep_core.version import USAGE_TERMS_DEFINITION_VERSION

DISCLOSURE_LEVELS = ("minimal", "standard", "full")
DEFAULT_DISCLOSURE_LEVEL = "full"

# Observation groups the Markdown shows at each level, by report key. `full` is
# the whole detail layer and is what grift printed before 0.9.6. `change_rhythm`
# and the event groups sit at `full` only: activity days and gaps are the part of
# the record that describes working habits.
_MINIMAL = ("surface_profile", "verification_profile")
_STANDARD = (*_MINIMAL, "coordination_profile", "event_observation")
_FULL = (*_STANDARD, "change_rhythm", "event_rhythm", "tracker_lifecycle")
LEVEL_SECTIONS: dict[str, tuple[str, ...]] = {
    "minimal": _MINIMAL,
    "standard": _STANDARD,
    "full": _FULL,
}

NORMS_REF = "docs/norms.md"
BINDING = "declaration_only"

# (id, norms.md article). The ids are the closed vocabulary of this field.
PROHIBITED_USES: tuple[tuple[str, int], ...] = (
    ("negative_reading_of_absence", 1),
    ("single_threshold_cutoff", 2),
    ("negative_reading_of_declaration", 3),
    ("profiling_without_consent", 4),
    ("continuous_monitoring", 5),
    ("weighting_or_conversion", 7),
)
PERMITTED_USES = (
    "self_review",
    "career_summary",
    "interview_questions",
    "recipient_verification",
)

USAGE_TERMS_LIMITATIONS = (
    "These terms are a declaration recorded with the report. They do not technically prevent "
    "reuse after sharing; they make the conditions the report was shared under visible and "
    "quotable.",
    "The disclosure level selects what the Markdown view shows. The JSON keeps every "
    "observation so that grift verify can recompute it; share the JSON only with someone "
    "who may read all of it.",
)


class DisclosureLevelError(ValueError):
    """The requested disclosure level is not one of the closed set."""


def validate_disclosure_level(level: str | None) -> str:
    chosen = DEFAULT_DISCLOSURE_LEVEL if level is None else level
    if chosen not in DISCLOSURE_LEVELS:
        raise DisclosureLevelError(
            f"unknown disclosure level {level!r}; choose one of {', '.join(DISCLOSURE_LEVELS)}"
        )
    return chosen


def shown_sections(level: str | None) -> tuple[str, ...]:
    return LEVEL_SECTIONS[validate_disclosure_level(level)]


def usage_terms_payload(level: str | None) -> dict[str, Any]:
    chosen = validate_disclosure_level(level)
    shown = LEVEL_SECTIONS[chosen]
    return {
        "definition_version": USAGE_TERMS_DEFINITION_VERSION,
        "disclosure_level": chosen,
        "markdown_sections": list(shown),
        "withheld_from_markdown": [name for name in _FULL if name not in shown],
        "json_retains_all_observations": True,
        "permitted_uses": list(PERMITTED_USES),
        "prohibited_uses": [
            {"id": use_id, "norms_article": article} for use_id, article in PROHIBITED_USES
        ],
        "norms_ref": NORMS_REF,
        "binding": BINDING,
        "limitations": list(USAGE_TERMS_LIMITATIONS),
    }


SECTION_NAMES_JA = {
    "surface_profile": "作業領域",
    "verification_profile": "テストの付け方",
    "coordination_profile": "調整の観測",
    "event_observation": "イベント観測",
    "change_rhythm": "変更リズム",
    "event_rhythm": "イベント間隔",
    "tracker_lifecycle": "tracker の流れ",
}
PERMITTED_USE_NAMES_JA = {
    "self_review": "本人の振り返り",
    "career_summary": "経歴の要約の材料",
    "interview_questions": "面談で確かめたいことの材料",
    "recipient_verification": "受け取った人による再計算（`grift verify`）",
}
PROHIBITED_USE_NAMES_JA = {
    "negative_reading_of_absence": "記録にないことを、実績がないことと読む",
    "single_threshold_cutoff": "1 つの数字だけで足切りする",
    "negative_reading_of_declaration": "AI 利用の申告の有無を、悪い材料として読む",
    "profiling_without_consent": "本人の同意なしに、人物像を作る",
    "continuous_monitoring": "組織の人を継続して比べる、監視に使う",
    "weighting_or_conversion": "数字に重みを付ける、点に換算する",
}


def _names(keys: Any, names: dict[str, str]) -> str:
    return "、".join(names.get(str(key), str(key)) for key in keys if isinstance(key, str))


def usage_terms_lines(report: dict[str, Any]) -> list[str]:
    """The 「共有するときの条件」 section, read from the report's own `usage_terms`."""
    terms = report.get("usage_terms")
    if not isinstance(terms, dict):
        return []
    level = terms.get("disclosure_level")
    shown = _names(terms.get("markdown_sections") or [], SECTION_NAMES_JA)
    withheld = _names(terms.get("withheld_from_markdown") or [], SECTION_NAMES_JA) or "なし"
    prohibited = "、".join(
        f"{PROHIBITED_USE_NAMES_JA.get(str(row.get('id')), str(row.get('id')))}"
        f"（利用規範 {row.get('norms_article')} 条）"
        for row in terms.get("prohibited_uses") or []
        if isinstance(row, dict)
    )
    return [
        "## 共有するときの条件",
        f"- 開示レベル: {level}（この Markdown に出した観測: {shown}。出していない観測: {withheld}）",
        "- JSON には、開示レベルにかかわらずすべての観測が残ります。`grift verify` が JSON を計算し直すためです。"
        "JSON を渡すのは、全部を読んでよい相手だけにしてください。",
        f"- 使ってよい使い方: {_names(terms.get('permitted_uses') or [], PERMITTED_USE_NAMES_JA)}",
        f"- 使ってはいけない使い方（{terms.get('norms_ref')}）: {prohibited}",
        "- この条件は、レポートに書いた宣言です。共有したあとの使い方を技術では止められません。"
        "JSON の `usage_terms` に残すのは、どの条件で渡したかを見える形にするためです。",
        "",
    ]
