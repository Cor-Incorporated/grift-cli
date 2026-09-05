"""Display presets. Role lens never classifies a person or assigns a job."""

from __future__ import annotations

from typing import Any

from tep_core.v2_constants import ROLE_LENSES

LENS_SECTIONS: dict[str, tuple[str, ...]] = {
    "frontend": ("surface_profile", "verification_profile", "change_rhythm"),
    "backend": ("surface_profile", "verification_profile", "change_rhythm"),
    "data": ("surface_profile", "verification_profile"),
    "platform": ("surface_profile", "coordination_profile"),
    "qa": ("verification_profile",),
    "full-stack": ("surface_profile", "change_rhythm"),
    "tech-lead": ("coordination_profile", "surface_profile"),
    "pm": ("coordination_profile",),
}

LENS_EMPHASIS: dict[str, tuple[str, ...]] = {
    "frontend": ("frontend", "cross_surface_cochange"),
    "backend": ("backend", "data"),
    "data": ("data", "backend"),
    "platform": ("platform", "ci_cd", "observability"),
    "qa": ("test_only_commit_count", "test_type_distribution", "fix_with_test_pairing"),
    "full-stack": ("frontend", "backend", "cross_surface_cochange"),
    "tech-lead": ("review", "module_breadth", "cross_surface_cochange"),
    "pm": ("tracker", "issue_link_count"),
}

LENS_INTRO: dict[str, str] = {
    "frontend": (
        "表示プリセット frontend: frontend surface と frontend↔backend の交差を強調します。"
        "backend プリセットと同じ節を出しますが、見る項目が違います。職種の確定ではありません。"
    ),
    "backend": (
        "表示プリセット backend: backend / data surface を強調します。"
        "frontend プリセットと同じ節を出しますが、見る項目が違います。職種の確定ではありません。"
    ),
    "data": "表示プリセット data: schema / migration / SQL の観測を強調します。職種の確定ではありません。",
    "platform": "表示プリセット platform: platform / CI/CD / observability を強調します。職種の確定ではありません。",
    "qa": (
        "表示プリセット qa: test-only と test type、fix-with-test を強調します。"
        "test co-change だけで QA とは呼びません。"
    ),
    "full-stack": (
        "表示プリセット full-stack: frontend↔backend の交差を強調します。"
        "言語が2つあるだけでは full-stack とは呼びません。"
    ),
    "tech-lead": (
        "表示プリセット tech-lead: review と surface breadth を強調します。"
        "forge export が無い場合、review は未観測です。Tech Lead 能力の判定ではありません。"
    ),
    "pm": (
        "表示プリセット pm: tracker / issue link を強調します。"
        "tracker export が無い場合、issue triage は未観測です。PM 能力の判定ではありません。"
    ),
}


def validate_role_lens(name: str | None) -> str | None:
    if name is None:
        return None
    if name not in ROLE_LENSES:
        raise ValueError(f"unknown role lens: {name}")
    return name


def role_lens_payload(name: str | None) -> dict[str, Any] | None:
    if name is None:
        return None
    return {
        "kind": "display_preset",
        "name": name,
        "unit": "lens",
        "classifies_role": False,
        "emphasized_sections": list(LENS_SECTIONS[name]),
        "emphasized_keys": list(LENS_EMPHASIS[name]),
        "intro": LENS_INTRO[name],
        "limitations": ["role_lens は表示する観測項目の切り替えです。職種分類器ではありません。"],
    }


def lens_intro(name: str | None) -> str | None:
    if name is None:
        return None
    return LENS_INTRO[name]


def emphasized_keys(name: str | None) -> tuple[str, ...]:
    if name is None:
        return ()
    return LENS_EMPHASIS[name]


def emphasized_sections(name: str | None) -> tuple[str, ...]:
    if name is None:
        return (
            "surface_profile",
            "change_rhythm",
            "verification_profile",
            "coordination_profile",
        )
    return LENS_SECTIONS[name]
