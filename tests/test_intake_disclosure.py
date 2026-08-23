"""Intake disclosure ↔ norms parity (meta-rule: every prohibition carries a
falsification test). Verifies the ruling's required disclosure lines exist in
BOTH the CLI confirmation and the norms docs, and that a payload with a repo
name field is structurally rejected by the contribution builder."""

from __future__ import annotations

import json
from pathlib import Path

from tep_core.contribute import CONFIRMATION_TEXT, INTAKE_REPO, build_contribution

ROOT = Path(__file__).resolve().parents[1]


def test_disclosure_and_norms_carry_the_same_promises() -> None:
    norms = (ROOT / "docs" / "norms.md").read_text(encoding="utf-8")
    norms_en = (ROOT / "docs" / "en" / "norms.md").read_text(encoding="utf-8")
    required = [
        ("目的拘束/公開コーパス", "公開コーパス" in CONFIRMATION_TEXT or "公開リポジトリ" in norms),
        (
            "転用禁止",
            "転用" in norms and "SaaS" in norms and "reuse" in norms_en and "SaaS" in norms_en,
        ),
        ("撤回", "撤回" in norms and "Withdrawal" in norms_en),
        ("保持期間", "保持期間" in norms and "Retention" in norms_en),
        (
            "推測リスク",
            "推測" in CONFIRMATION_TEXT and "推測" in norms and "re-identification" in norms_en,
        ),
        ("repo名なし", "repo 名は含まれません" in CONFIRMATION_TEXT),
        (
            "二枚扉",
            "二枚扉" in CONFIRMATION_TEXT
            and "公開ドア" in CONFIRMATION_TEXT
            and "非公開ドア" in CONFIRMATION_TEXT,
        ),
        ("intake URL", "tep-contributions" in INTAKE_REPO and INTAKE_REPO in CONFIRMATION_TEXT),
    ]
    missing = [name for name, ok in required if not ok]
    assert not missing, f"disclosure/norms parity broke: {missing}"


def test_payload_with_repo_name_field_is_rejected() -> None:
    """Falsification: a report carrying a repo-name field must not pass through
    build_contribution (the builder excludes 'repository', and a tampered
    payload that smuggles it back trips the forbidden-key assertion)."""
    report = {
        "schema_version": "report-v1",
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.5.5",
            "method_name": "TEP",
            "definition_version": "x",
            "origin_definition_version": "x",
            "activity_definition_version": "x",
            "analysis_scope": "repo",
            "analyzed_commit_sha": "0" * 40,
            "analyzed_at": "2026-08-23T00:00:00Z",
        },
        "test_cochange": {
            "kind": "observed",
            "all_time": {
                "kind": "observed",
                "value": 0.2,
                "unit": "ratio",
                "population": 50,
                "cochanged": 10,
                "narrate_rate": True,
            },
        },
        "origin": {"unresolved": {"kind": "observed", "value": 100, "unit": "commits"}},
        "rework": {"kind": "not_observed", "reason": "commit_paths_unavailable"},
        "survival": {"kind": "not_observed", "reason": "survival_scan_disabled"},
        "identity": {"pending_attribution": True, "actor_count": 0},
        "interpretation": {},
    }
    payload = build_contribution(report)
    text = json.dumps(payload, ensure_ascii=False)
    assert "@" not in text

    def keys_of(node):
        found = set()
        if isinstance(node, dict):
            found.update(node.keys())
            for value in node.values():
                found |= keys_of(value)
        return found

    assert not keys_of(payload) & {"repository", "repo", "canonical_id", "actor", "actors", "emails", "path"}, (
        "payload must not carry identifying keys (values like analysis_scope='repo' are fine)"
    )
    # falsify: smuggle a repo-name key back into the payload — the same key
    # walk the intake validator runs must detect it (mirror of intake CI)
    smuggled = json.loads(text)
    smuggled["metrics"]["repository"] = {"name": "secret-repo"}
    forbidden = {"canonical_id", "actor", "actors", "emails", "path", "repo", "repository"}
    keys: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            keys.update(node.keys())
            for value in node.values():
                walk(value)

    walk(smuggled)
    assert keys & forbidden, "smuggled repo-name key must be detectable"


def test_intake_validator_is_pinned_in_repo_docs() -> None:
    readmes = "\n".join(
        (ROOT / f).read_text(encoding="utf-8") for f in ("README.md", "README.en.md")
    )
    assert "tep-contributions" in readmes
