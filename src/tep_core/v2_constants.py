"""v0.6 enums and notices. Display presets only — not classifiers."""

from __future__ import annotations

SURFACES = (
    "test",
    "docs",
    "ci_cd",
    "platform",
    "data",
    "observability",
    "frontend",
    "backend",
    "config",
    "generated_vendor",
    "other",
)

ROLE_LENSES = (
    "frontend",
    "backend",
    "data",
    "platform",
    "qa",
    "full-stack",
    "tech-lead",
    "pm",
)

VERIFICATION_TYPES = ("unit", "integration", "e2e", "contract", "unspecified")
INPUT_KINDS = ("git", "forge", "tracker")
WINDOW_BASIS = ("explicit_as_of", "legacy_head_date")
SUBJECT_KINDS = ("repo", "actor")
COMPARISONS = (
    "overlap",
    "outside_declared_range",
    "observed_zero",
    "not_observed",
    "not_declared",
)

FORBIDDEN_VERDICT_KEYS = frozenset(
    {
        "score",
        "rank",
        "percentile_for_actor",
        "fit",
        "compatibility_score",
        "recommendation",
        "hire",
        "pass",
        "fail",
        "overall",
        "fit_score",
    }
)

EVIDENCE_DISCLAIMER = (
    "この数値は、過去の Git / ローカル export に残った変更の形を示します。"
    "人の優劣、職種の確定、採用の合否、将来の成果を示すものではありません。"
)
ACTOR_CONSENT_NOTICE = (
    "本人同意のある identity を使ってください。CLI は同意そのものを証明しません。"
)
PUBLIC_ACTOR_NOTICE = "この表示は公開 Git / 公開 Forge の観測です。CLI は本人性を証明しません。"
ACTOR_ADMIN_NOTICE = (
    "この表示は管理対象リポジトリの管理権限に基づいて定義された identity "
    "（attribution_state=verified）による actor 観測です。CLI は本人同意または"
    "本人性を証明せず、本人向け証拠ビューとは呼びません。"
)
ACTOR_CLAIMED_NOTICE = (
    "この表示は attribution_state=claimed と記録された identity による actor 観測です。"
    "CLI はその申告者、本人同意または本人性を証明しません。"
)
ACTOR_NONCONSENT_NOTICE = (
    "この表示は明示 identity により選択された actor 観測ですが、"
    "本人同意または本人性を証明しません。experience / role は観測しません。"
)
ACTOR_UNKNOWN_NOTICE = (
    "actor の表示根拠を確認できません。selection または attribution_state が欠落・"
    "不整合のため、本人同意または本人性を証明せず、本人向け証拠ビューとは呼びません。"
)
ACTOR_CARD_SCHEMA_VERSION = "actor-card-v1"
ACTOR_VIEW_NOTICE = (
    "この表示は、指定された1つの canonical_id に帰属した履歴だけを対象にした"
    "本人向け証拠ビューです。未観測は、実績がないことを意味しません。"
)
ALIGNMENT_NOTICE = (
    "案件側の宣言と観測証拠の重なりを軸ごとに表示しています。全体の点数や順位は計算していません。"
)
RHYTHM_WINDOW_DAYS = 180
RHYTHM_LIMITATION = (
    "これは変更提出の時系列であり、実際の労働時間、勤怠、能力、納期遵守を測るものではありません。"
)
RHYTHM_WINDOW_NOTE = (
    "gap / median / p90 / burst / long-gap は observation_date から遡る "
    f"{RHYTHM_WINDOW_DAYS} 日窓内の Git author timestamp だけを母集団にする。"
    "窓の外側の履歴は混ぜない。"
)
RHYTHM_TIMESTAMP_LIMITATIONS = (
    "squash・rebase・author timestamp の書き換え・bot・timezone の違いで間隔は変わります。"
    "squash 前後の commit 数の差を速度の変化とは呼びません。"
)
SURFACE_LIMITATION = (
    "これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。"
)
COMPARISON_JA = {
    "overlap": "重なり（観測が宣言範囲・要求と重なる）",
    "outside_declared_range": "宣言範囲の外（能力の否定ではない）",
    "observed_zero": "この範囲では該当証拠が0件（未経験・能力不足ではない）",
    "not_observed": "比較不能・未観測（実績がないことではない）",
    "not_declared": "案件側に要求がない（不足ではない）",
}
TRACKER_NOT_OBSERVED_NOTE = (
    "tracker export が提供されていないため、issue triage / milestone "
    "coordination は観測できません。これは活動が無かったことを意味しません。"
)
FORGE_NOT_OBSERVED_NOTE = (
    "forge export が提供されていないため、review は観測できません。"
    "Git の merge commit 比率を pull request review とは呼びません。"
)

MIN_POPULATION_FOR_RATES = 20
MIN_EVENTS_FOR_SHAPE = 8
MIN_ACTIVE_DAYS_FOR_SHAPE = 5
MIN_WINDOW_DAYS_FOR_SHAPE = 30
TENDENCY_SHARE_MODERATE = 0.4
TENDENCY_SHARE_STRONG = 0.6
TENDENCY_RATIO_SIMILAR_LOW = 0.5
TENDENCY_RATIO_SIMILAR_HIGH = 2.0

CONFIDENCE_LEVELS = (
    "not_proven",
    "insufficient_data",
    "weak_signal",
    "directional",
    "directional_candidate",
    "stronger_signal",
    "reference_aligned",
)
STRENGTH_LEVELS = ("weak", "moderate", "strong")
RELATIONSHIPS = (
    "similar_direction",
    "different_direction",
    "mixed",
    "not_comparable",
    "not_proven",
)
MIN_N_NOT_PROVEN = 5
MIN_N_DIRECTIONAL = 20

TENDENCY_CHANGE_NOTE = (
    "追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。"
)
PROJECT_OBSERVED_MISSING_NOTE = (
    "project observedは未提供のため、actorとprojectの実測比較は行っていません。"
)
# Paired with SCALE_DENOMINATOR_NOTE in context_profile: the same report ships
# both populations, and each block states which one it counts.
ACTIVITY_DENOMINATOR_NOTE = "repo_human_nonmerge_commits excludes bot and merge commits"
FORBIDDEN_UNITS = frozenset({"score", "rank", "fit", "hire", "percentile", "recommendation"})
ARTIFACT_NAMES = {
    "repo": ("report.md", "report.json"),
    "actor": ("actor-report.md", "actor-report.json"),
    "project": ("project.md", "project.json"),
    "alignment": ("alignment.md", "alignment.json"),
}
