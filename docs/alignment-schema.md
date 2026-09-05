# alignment-v1

actor観測（report-v2 actor）と案件要求（project-v1）を **軸ごとに** 並べる。
actorの表示根拠は `subject.actor_selection` / `actor_attribution_state` で保持し、
欠落・矛盾時は本人同意を推測しない。総合点・順位・合否・推奨は計算しない。

禁止キー: `score`, `rank`, `percentile_for_actor`, `fit`, `compatibility_score`, `recommendation`, `hire`, `pass`, `fail`, `overall`, `fit_score`

## comparison

| comparison | 意味 |
|---|---|
| `overlap` | 観測値と宣言範囲・要求項目が重なる |
| `outside_declared_range` | 観測値が宣言範囲の外にある。能力否定ではない |
| `observed_zero` | 対象 scope では該当証拠が 0 件だった |
| `not_observed` | 入力不足、母数不足、対象履歴なし等で比較不能 |
| `not_declared` | project 側に要求がない |

```json
{
  "schema_version": "alignment-v1",
  "report_kind": "alignment",
  "subject": {
    "kind": "alignment",
    "actor_canonical_id": "candidate_001",
    "actor_selection": "explicit_actor",
    "actor_attribution_state": "claimed",
    "project_id": "checkout-api"
  },
  "actor_observed": {"kind": "observed", "unit": "profile"},
  "project_observed": {"kind": "observed", "unit": "profile"},
  "project_declared": {"kind": "declared", "value": ["backend"], "unit": "surface_list"},
  "actor_provenance": {
    "analysis_scope": "tenant",
    "analyzed_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "project_provenance": {"analyzed_commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
  "actor_report_digest": "sha256:actor",
  "project_report_digest": "sha256:project",
  "axes": [
    {
      "axis": "surfaces.backend",
      "declared": {"kind": "declared", "value": "backend", "unit": "surface"},
      "observed": {"kind": "observed", "value": 12, "unit": "commits"},
      "actor_observed": {"kind": "observed", "value": 12, "unit": "commits"},
      "project_observed": {"kind": "observed", "value": 10, "unit": "commits"},
      "project_declared": {"kind": "declared", "value": "backend", "unit": "surface"},
      "actor_n": 12,
      "project_n": 10,
      "actor_denominator": 31,
      "project_denominator": 20,
      "actor_source": ["git:path"],
      "project_source": ["git:path"],
      "actor_basis": {"unit": "commits", "n": 12, "window": "2026-02-01/2026-08-01"},
      "project_basis": {"unit": "commits", "n": 10, "window": "2026-02-01/2026-08-01"},
      "actor_tendency": {"kind": "directional", "confidence": "directional"},
      "project_tendency": {"kind": "directional", "confidence": "directional"},
      "relationship": {"kind": "similar_direction", "confidence": "directional"},
      "actor_window": {"start": "2026-02-01", "end": "2026-08-01"},
      "project_window": {"start": "2026-02-01", "end": "2026-08-01"},
      "definition_version": {"actor": "tep-v0.6.0", "project": "tep-v0.6.0"},
      "coverage": {"status": "present", "missing": []},
      "incomparable_reason": null,
      "comparison": "overlap",
      "evidence_paths": ["surface_profile.surface_commit_counts.backend"],
      "limitations": ["A zero here is evidence in this scope, not inexperience."]
    }
  ]
}
```

各軸は次を分けて持ちます。混ぜません。

```json
{
  "actor_observed": {},
  "project_observed": {},
  "project_declared": {},
  "actor_basis": {},
  "project_basis": {},
  "actor_n": 0,
  "project_n": 0,
  "actor_denominator": null,
  "project_denominator": null,
  "actor_source": ["git:path"],
  "project_source": ["git:path"],
  "actor_tendency": {"kind": "directional", "confidence": "directional"},
  "project_tendency": {"kind": "not_proven", "confidence": "not_proven"},
  "relationship": {"kind": "similar_direction", "confidence": "directional"},
  "coverage": {"status": "present", "missing": []},
  "incomparable_reason": null
}
```

`relationship.kind` は `similar_direction` / `different_direction` / `mixed` / `not_comparable` です。採用・能力・適合ではありません。window や単位が違う場合は `not_comparable` です。

トップレベルにも `actor_observed` / `project_observed` / `project_declared` / `actor_provenance` / `project_provenance` / `actor_report_digest` / `project_report_digest` が必須です。

`evidence_paths` は `actor.`（actor観測）と `project.declared.`（案件宣言）を分けて書きます。

Markdown は次の順です: 対象 → 入力 → 見ていないこと → 観測値 → 基準値 → 傾向 → 強さと確からしさ → 比較不能 → 言えること/言えないこと → 再現情報。

tracker export が無いときの説明:

> tracker export が提供されていないため、issue triage / milestone coordination は観測できません。これは活動が無かったことを意味しません。
