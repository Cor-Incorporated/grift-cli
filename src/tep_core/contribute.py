"""`grift contribute` — explicit opt-in submission builder (data-collection
ruling §2-3, shipped ahead of schedule in v0.5.2).

The measurement commands never touch the network, and contribute never
auto-sends to anyone (7th prohibition: no automatic transmission to us, ever).
`--open` uses the user's own gh credentials to push to the user's own fork;
the final submit button is the user's. This module builds a payload and prints
it in full; the user reviews it and submits it themselves (PR-based intake
into the public contributions repository — therefore the payload WILL be
public, which the confirmation flow states explicitly).

Payload rules (ruling, unchangeable):
- repo-scope aggregate values + context_profile + definition versions ONLY
- canonical_id, actors, emails, paths, repo name (unless the submitter
  chooses to add it), and tenant-scope values are NEVER included
"""

from __future__ import annotations

import json
from typing import Any

CONTRIBUTE_PURPOSE = "TEP Report 集計と参照分布 vNext"

_EXCLUDE_TOP_LEVEL = {"identity", "interpretation", "repository", "context_profile", "activity"}
_CONTEXT_ALLOWED = {
    "kind",
    "definition_version",
    "analysis_scope",
    "resolved_human_actors",
    "top_actor_share",
    "collaboration_class",
    "pr_flow_share",
    "repo_age_days",
    "lifecycle_stage",
    "conventional_commit_share",
    "language_composition",
    "test_file_ratio",
    "docs_share",
    "dependency_manifests",
    "monorepo_markers",
    "issue_link_density",
    "release_cadence",
    "actor_turnover",
}


def build_contribution(report: dict[str, Any]) -> dict[str, Any]:
    """Build the contribution payload from a REPO-scope report.

    Raises ValueError when the report is not repo-scope (tenant values are
    structurally excluded — they are not ours to transmit).
    """
    scope = (report.get("provenance") or {}).get("analysis_scope")
    if scope != "repo":
        raise ValueError(
            "contribute requires a repo-scope report (tenant-scope values are "
            "private to the identity owner and are never included)"
        )
    provenance = report.get("provenance") or {}
    payload: dict[str, Any] = {
        "contribution_schema": "tep-contribution-v1",
        "purpose": CONTRIBUTE_PURPOSE,
        "provenance": {
            key: provenance.get(key)
            for key in (
                "tool_name",
                "tool_version",
                "definition_version",
                "origin_definition_version",
                "activity_definition_version",
                "analysis_scope",
            )
        },
        "metrics": {
            key: value
            for key, value in report.items()
            if key not in _EXCLUDE_TOP_LEVEL and key not in ("schema_version",)
        },
        "context_profile": _slim_context(report.get("context_profile")),
    }
    _assert_no_private_shape(payload)
    return payload


def _slim_context(ctx: Any) -> Any:
    if not isinstance(ctx, dict) or ctx.get("kind") != "observed":
        return ctx
    slim = {key: ctx[key] for key in _CONTEXT_ALLOWED if key in ctx}
    return slim


_FORBIDDEN_SUBSTRINGS = ("@",)  # emails must never appear


def _assert_no_private_shape(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    if "@" in text:
        raise ValueError("payload contains an email-shaped string — refuse to build")
    for key in ("canonical_id", "actor", "emails", "path"):
        if f'"{key}"' in text:
            raise ValueError(f"payload contains forbidden key {key!r}")


INTAKE_REPO = "https://github.com/Cor-Incorporated/tep-contributions"

CONFIRMATION_TEXT = """この提出について（必読）/ About this submission (read first):
1. 上記の payload 全文が提出内容のすべてです / The payload above is the entirety of the submission
2. この提出は公開コーパスに載ります（受け口は公開リポジトリのため、payload は公開になります）/ It will appear in the public corpus (the intake is a public repository)
3. repo 名は含まれません（付記は opt-in）。ただし特徴の組合せから推測されるリスクはゼロではありません / No repo name is included (opt-in aside); the risk of re-identification from feature combinations is not zero
4. 用途は「{purpose}」に限定され、それ以外（SaaS 等への転用を含む）には使われません（docs/norms.md 保持・削除条項）/ Use is restricted to "{purpose}" — nothing else, including SaaS reuse (see the norms retention section)
5. 測定コマンド（analyze/report/verify）はネットワークに触れません。contribute は自動送信しません — 提出はあなた自身が行います / The measurement commands never touch the network; contribute never auto-sends — submission is your action
6. 提出は二枚扉です / Two doors: 公開ドア（本人 PR・{intake}）/ 非公開ドア（フォーム・メール → 当社が代理 PR・身元は非公開）/ public door (your own PR) or private door (form/email; we open the PR; your identity stays private)
7. --open を使う場合 / If you use --open: **この方法は公開ドアです。あなたの GitHub アカウント名が PR に表示されます / this is the PUBLIC door; your GitHub account name will appear on the PR**。fork がまだ無い場合は自動作成されます / a fork under your account will be auto-created if you do not have one
""".format(purpose=CONTRIBUTE_PURPOSE, intake=INTAKE_REPO)


def render_confirmation(payload: dict[str, Any]) -> str:
    return (
        "=== contribution payload (full) ===\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n=== end payload ===\n\n"
        + CONFIRMATION_TEXT
    )


def validate_contribution_payload(payload: dict) -> list[str]:
    """Local pre-push check for --open (B-4): mirrors the intake validator's
    schema + needle rails. Returns violation list; non-empty = do not push."""
    violations: list[str] = []
    if payload.get("contribution_schema") != "tep-contribution-v1":
        violations.append("contribution_schema must be tep-contribution-v1")
    if payload.get("purpose") != CONTRIBUTE_PURPOSE:
        violations.append("unexpected purpose")
    prov = payload.get("provenance") or {}
    if prov.get("analysis_scope") != "repo":
        violations.append("only repo-scope contributions are accepted")
    import json as _json

    text = _json.dumps(payload, ensure_ascii=False)
    if "@" in text:
        violations.append("email-shaped string present")
    forbidden = {"canonical_id", "actor", "actors", "emails", "path", "repo", "repository"}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in forbidden:
                    violations.append(f"forbidden key {key!r}")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return violations
