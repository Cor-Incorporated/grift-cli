# alignment-v1

actor観測（report-v2 actor）と案件要求（project-v1）を **軸ごとに** 並べる。
actorの表示根拠は `subject.actor_selection` / `actor_attribution_state` で保持し、
欠落・矛盾時は本人同意を推測しない。同意の記録は `subject.actor_consent`（任意、
値は `recorded-explicit-consent` だけ）で保持する。`grift align` は actor report に同意の
記録があるときだけ、actor の本人向けの文と同じ関数（`actor_basis.consent_recorded`）で
確かめて写し、公開 inferred には付けない。Markdown の面談の問いは、claimed かつ
`actor_consent` があるときだけ出す（T7）。`grift verify` は保存した値を信じず、actor report
から作り直して比べる。ただし保存した 2 つの report の経路では、渡した actor report そのものは
確かめないので、actor report は `grift verify actor-report.json --repo REPO --identity IDENTITY`
で別に確かめる。repo から作り直す経路（`--repo --identity --project`）は、subject・provenance・
limitations を `grift align --repo` と同じ関数（`alignment_repo.repo_alignment_payload`）で作り直す
（`project_id` は project TOML から、`mode` は付けない）。保存した JSON から読むのは作り直しの入力
（as_of・role_lens・vendor_scan・survival・reference_id）だけ。verify の経路は渡した入力で選び、両方の入力がそろっている（またはどちらもそろっていない）ときだけ保存した `mode` で選ぶ。
`grift report <alignment.json>` は保存した JSON を描き直すだけで、`actor_selection`・
`actor_attribution_state`・`actor_consent` を確かめない（Markdown の「数字の読み方と限界」にもそう書く）。
総合点・順位・合否・推奨は計算しない。

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
    "actor_consent": "recorded-explicit-consent",
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
      "actor_basis": {"unit": "commits", "n": 12, "window": {"end": "2026-08-01", "unit": "date-range", "basis": "history_to_observation_date"}},
      "project_basis": {"unit": "commits", "n": 10, "window": {"end": "2026-08-01", "unit": "date-range", "basis": "history_to_observation_date"}},
      "actor_tendency": {"kind": "directional", "confidence": "directional"},
      "project_tendency": {"kind": "directional", "confidence": "directional"},
      "relationship": {
        "kind": "similar_direction",
        "confidence": "directional_candidate",
        "compared": "commit_share",
        "actor_share": {"kind": "observed", "value": 0.3871, "unit": "commit_share", "sample_size": 31},
        "project_share": {"kind": "observed", "value": 0.5, "unit": "commit_share", "sample_size": 20}
      },
      "actor_window": {"end": "2026-08-01", "unit": "date-range", "basis": "history_to_observation_date"},
      "project_window": {"end": "2026-08-01", "unit": "date-range", "basis": "history_to_observation_date"},
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

`relationship.kind` は `similar_direction` / `different_direction` / `mixed` / `not_comparable` / `not_proven` です。採用・能力・適合ではありません。window や単位が違う場合は `not_comparable` です。比べた件数の小さいほうが 20 に届かないときは `not_proven` で、向きの候補は `direction` に残りますが、向きとしては扱いません（`confidence` は 5 未満なら `insufficient_data`、5 以上 20 未満なら `weak_signal`）。

v0.9.0 から、`relationship` と軸の窓は次のとおりです。

- `surfaces.*` と `verification.*` の `relationship` は、actor と project の件数ではなく、それぞれの範囲の中の割合（`surface_commit_share`、`test_type_share`）どうしで決めます。1 人の件数をチーム全体の件数で割ると、向きがチームの人数で決まってしまうためです。`"compared": "commit_share"` と、比べた割合（`actor_share` / `project_share`。`sample_size` は割合の母数）が付くので、向きを JSON から確かめられます。
- 割合の母数が 20 に届かない側があれば `not_comparable`（`observed_unavailable`）です。
- `change_rhythm.*` は、1 人の commit とリポジトリ全体の commit が別の母集団なので、常に `not_comparable`（`scope_not_equivalent`）です。
- `surfaces.*` と `verification.*` の `actor_window` / `project_window` は、観測日までの履歴（`"basis": "history_to_observation_date"`。浅い clone なら取得できた範囲）を表します。180 日窓（`provenance.git_window`）は `change_rhythm.*` の窓です。`inputs.*` と `role_lens` は数えた値ではないので、0.8.0 と同じく分析の窓（`provenance.git_window`）をそのまま載せています。
- 傾向（`actor_tendency` / `project_tendency`）の場所は commit の割合で選びます。割合がいちばん大きい場所が 2 つ以上あれば `not_proven`（`tied_top_share`）で、同じ割合の場所は `tied` に並びます。

v0.9.0 から、Markdown には `strength`（weak / moderate / strong）と `relationship` を出しません。2 つのレポートを並べると、強い人・弱い人、合う人・合わない人に読めるためです。JSON の `actor_tendency.strength` / `project_tendency.strength` は残しますが、`strength` は非推奨で、次の schema 版で消します。`relationship`（比べた割合を含む）は JSON に残します。

トップレベルにも `actor_observed` / `project_observed` / `project_declared` / `actor_provenance` / `project_provenance` / `actor_report_digest` / `project_report_digest` が必須です。

`evidence_paths` は `actor.`（actor観測）と `project.declared.`（案件宣言）を分けて書きます。

Markdown の見出し（`## `）は次の順です。

1. `要望と記録が重なっている点`
2. `面談で確かめたい点`
3. `案件側が書いていないこと（参考）`
4. `数字の読み方と限界`
5. `このレポートは誰・何を対象にしたか`
6. `何を入力として見たか`
7. `何を見ていないか`
8. `案件側の宣言`
9. `観測された数値 / 軸ごとの並び`
10. `基準値・比較材料`
11. `傾向`
12. `傾向の確からしさ`
13. `比較不能・未観測・未証明`
14. `言えること / 言えないこと`
15. `再現情報`

1〜4 は v0.9.0 からの先頭の節です（[決定表](trait-profile.md)）。判定（overlap など）を並べ直したもので、重なった項目の数は出しません。3 は案件側が書いていない項目があるときだけ出ます。浅い clone の記録では、1〜4 の代わりに出さない理由の 1 文だけが出ます。

tracker export が無いときの説明:

> tracker export が提供されていないため、issue triage / milestone coordination は観測できません。これは活動が無かったことを意味しません。
