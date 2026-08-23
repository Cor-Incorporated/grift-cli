# report.json schema (report-v1) — 凍結 2026-08-22

`grift analyze --format json` が stdout / `report.json` に出力する全体構造の定義。
Grift 本体統合（WP-G1）はこの文書を契約として `grift analyze --format json` の子プロセス呼び出しで利用する。

- 定数: `tep_core.version.REPORT_SCHEMA_VERSION = "report-v1"`（report の `schema_version` フィールドと同一値）
- 検証器: `tep_core.schema.validate_report(report, subset=False) -> list[str]`（純標準ライブラリ。空リスト = 合格）
- 歴史（F-P10-2）: v0.5.0 は `schema_version: "tep-report-v1"` を出力していた。凍結直前の変更として `report-v1` に改名した（既存フィールドの意味は不変・純粋な識別子変更）。**消費側検証器は v0.5.1 以降 `report-v1` 固定とすること**（`tep-report-v1` は受理しない）

## 安定性の約束（breaking change policy）

**report-v1 の間は追加のみ許される。** 既存フィールドの改名・削除・意味変更は report-v2 まで禁止。
具体的には:

- 新しいトップレールド・新しいサブフィールド・新しい `reason` コード・新しい `names` 要素 → **追加（可）**
- 既存フィールドの改名・削除・型変更・単位変更・意味の変更 → **破壊（不可。v2 が必要）**
- 検証器は未知のキーをエラーにしない（追加互換のため）。消費側も未知キーを無視して読むこと

## 観測値の符号化（全指標共通）

| kind | 形 | 意味 |
|---|---|---|
| `observed` | `{"kind": "observed", "value": <数値>, "unit": "<単位>", "sample_size": <int>=optional}` | 観測された。**0 は合法な観測値** |
| `not_observed` | `{"kind": "not_observed", "reason": "<snake_case>"}` | 観測できない。理由コードは開放集合（追加可）。初期コードは下表 |

`reason` 初期コード（網羅）:

| reason | 出現箇所 |
|---|---|
| `no_upstream_lineage` / `lineage_present` / `template_not_provided` / `parent_repo_not_provided` | origin 各クラス |
| `no_tenant_commits` / `no_tenant_active_days` / `head_date_unavailable` | activity, core_activity_period |
| `no_test_framework_or_directory` | test_frameworks, test_cochange |
| `pending_attribution` / `no_human_commits` / `commit_paths_unavailable` / `no_production_commits` | test_cochange, rework |
| `deferred_to_v0.6` | rework.line_rework |
| `survival_scan_disabled` / `git_unavailable` / `no_source_files` / `blame_unavailable` | survival |
| `scope_is_tenant` / `metric_not_observed` / `insufficient_population` / `reference_too_small` | interpretation 各エントリ |

`insufficient_population`（母数 20 未満）では率の叙述（`narrate_rate: false`）と十分位の出力を抑制する。件数の生表示は許される。

## トップレベル構造

| フィールド | 型 | 備考 |
|---|---|---|
| `schema_version` | string | 常に `"report-v1"` |
| `provenance` | object | 下表 |
| `repository` | object | `name`: string, `remote`: string\|null, `path`: string = opt-in（`--include-local-path` のみ。既定では同梱しない） |
| `identity` | object | `pending_attribution`: bool, `actor_count`: int>=0 |
| `lineage` | object | `is_fork`: bool, `parent`: string\|null, `has_upstream_lineage`: bool |
| `origin` | object | 11 クラス各々が観測値（unit=`commits`） |
| `attribution` | object | `bot`: 観測値（unit=`commits`） |
| `activity` | object | 下表 |
| `core_activity_period` | object | observed または not_observed |
| `test_frameworks` | object | observed: `value: true`, `names`: [string], `directories`: [string], unit=`boolean` |
| `test_cochange` | object | observed または not_observed |
| `rework` | object | observed または not_observed |
| `survival` | object | observed または not_observed（既定は `survival_scan_disabled`） |
| `interpretation` | object | `test_cochange` / `corrective_rework` 各エントリ |

### provenance

| フィールド | 型 | 備考 |
|---|---|---|
| `tool_name` | string | `"grift"` |
| `method_name` | string | `"TEP"` |
| `tool_version` | string | SEMVER |
| `definition_version` | string | 定義版（判別基準とセットで凍結） |
| `origin_definition_version` | string | |
| `activity_definition_version` | string | |
| `analysis_scope` | string | `"tenant"` \| `"repo"`（下記） |
| `analyzed_commit_sha` | string | 40 桁小文字 hex。この SHA 時点の履歴で計算 |
| `analyzed_at` | string | UTC `YYYY-MM-DDTHH:MM:SSZ` |

### analysis_scope の意味

- `tenant`: identity に一致した作業者の仕事（`tenant_unique`）= **証拠用**
- `repo`: bot と merge 以外の全人間コミット = **プロセス観測・参照分布用**

参照分布との照合は**同 scope 間のみ**（tenant の値を repo 分布に載せない）。`interpretation` は `analysis_scope: "tenant"` のとき常に `scope_is_tenant`。

### origin（11 クラス、各 unit=`commits`）

`inherited_upstream` / `upstream_sync` / `tenant_unique` / `tenant_merge_or_sync` / `tenant_derivative` / `external_upstream_contribution` / `template_inherited` / `generated_or_vendor` / `ambiguous_origin` / `unresolved` / `bot`

lineage・テンプレ・親リポ未指定のクラスは対応する `not_observed` reason になる。

### activity

| フィールド | unit | 型 |
|---|---|---|
| `tenant_commits` | commits | int>=0 |
| `active_days` | days | int>=0 |
| `commits_per_active_day` | commits/active-day | number>=0 |
| `commits_per_active_day_median` | commits/active-day | number>=0（`sample_size` = 観測日数） |
| `active_days_13w` | days | int>=0 |

### core_activity_period（observed の場合）

`start` / `end`: `YYYY-MM`（月）、`share`: 0..1（当該期間が覆う tenant_unique コミット比、>=80% を満たす最短連続月区間）、unit=`month-range`、`definition_version`。

### test_cochange（observed の場合）

`definition_version`、`analysis_scope`、`all_time`（率ブロック）、`last_13w`（率ブロック or `not_observed`）。

率ブロック: `value`: 0..1（unit=`ratio`）、`population` / `cochanged` / `test_only` / `docs_or_config_excluded`: int>=0、`narrate_rate`: bool（population>=20 で true）。

### rework（observed の場合）

`definition_version`、`analysis_scope`、`window_days`: int（21）、`evidence_claim`: null、および:

| ブロック | 特有フィールド | evidence_claim |
|---|---|---|
| `corrective_rework_rate` | `corrective_commits`, `narrate_rate` | `false`（観測専用。証拠主張ではない） |
| `path_retouch_rate` | `retouch_commits` | `false`（観測専用） |
| `revert_rate` | `reverts` | なし |
| `line_rework` | — | `not_observed`（`deferred_to_v0.6`） |

各率ブロックとも `value`: 0..1（unit=`ratio`）、`population`: int>=0。

### survival（observed の場合。`--survival` のみ）

`tau_days`: 180、`files_sampled` / `source_files` / `lines_sampled`: int>=1、`survival_index`: number（unit=`dimensionless`）、`definition_version`。

### context_profile（observed の場合・v0.5.2 追加）

repo スコープの文脈観測層（裁定: BD tep-context-profile-ruling §4-5・定義版 `context-v1`）。report-v1 への**追加セクション**。

| フィールド | unit | 意味 |
|---|---|---|
| `resolved_human_actors` | actors | bot・upstream系（inherited_upstream/upstream_sync）除外後のユニーク正規化著者数。**数のみ。誰かは出さない**（生 shortlog 数の叙述は禁止） |
| `top_actor_share` | ratio | 最多著者のコミット比率（canonical_id も名前も出さない） |
| `collaboration_class` | class | `solo`（top_share≥0.90）/ `small_team`（actors≤5）/ `community`（他）。閾値は定義版に含む |
| `pr_flow_share` | ratio | merge コミット比率 |
| `scale` | — | human_commits / first_commit / last_commit / active_span_days / top_level_dirs / tags |
| `repo_age_days` | days | first〜HEAD |
| `days_since_last_human_commit` | days | **lifecycle-v2 一次出力**: HEAD から最後の human（非bot）コミットまでの日数 |
| `active_days_180d` | days | **lifecycle-v2 一次出力**: 直近180日窓の human コミットユニーク日数（密度） |
| `lifecycle_stage` | class | **lifecycle-v2（密度基準）**: `dormant`（active_days_180d≤2）/ `maintained`（3〜11）/ `active`（≥12）。クラスは便宜であり一次観測値2つに常に併記される。**本閾値はパイロット第1round の観察から設計した（informed-by-pilot-1）** — 同一標本での「検証」は行わず、妥当性確認は将来の新標本（段2）で行う。**限界**: bulk housekeeping は「新しさ」を膨らませるため密度基準を採る／作業モード（開発 vs 保守）は測っていない — クラスは活動密度のみ |
| `actor_turnover` | actors/year | 年別 joined/left |
| `release_cadence` | releases/year | タグ頻度 |
| `conventional_commit_share` | ratio | `type(scope)?:` 形式の件名比率 |
| `language_composition` | touch-share | 拡張子別パス接触比率（1%未満は省略） |
| `test_file_ratio` / `docs_share` | ratio | テスト/ドキュメントパス接触コミット比率 |
| `dependency_manifests` | manifests | 検出された依存 manifest 名のリスト（polyglot 度） |
| `monorepo_markers` | markers | packages/ apps/ nx.json 等 |
| `issue_link_density` | ratio | `#N` 参照を含む非 merge 件名比率 |

**等級語・良し悪しの含意は持たせない**（community だから偉い、は書かない。分類は比較の条件であって賞ではない）。**重み付け禁止**: 文脈は比較母集団を選ぶためだけに使う。

### interpretation 各エントリ（observed の場合）

`reference_version`: string（例 `v2026.09`）、`analysis_scope`: `"repo"` 固定、`n`: int>=1、`decile`: 1..10、`value`: 0..1、`unit`、`metric_id`。参照分布 n<30 は `reference_too_small`。**十分位の 1 行以外の位置情報は出さない。**

## 終了コードと stdout/stderr 規約

| 終了コード | 意味 |
|---|---|
| 0 | 成功 |
| 2 | 使用法エラー（argparse）、または指定パスが git リポジトリでない |
| 1 | その他の予期しない失敗（詳細は stderr） |

- `--format json`: stdout は **JSON 1 件のみ**（純度保証。機械消費はこれを使う）
- `--format md`: stdout は markdown のみ
- `--format both`: markdown → 空行 → JSON の順
- 診断・エラーは常に stderr。`--out DIR` 指定時も stdout 規約は不変（`report.md` / `report.json` を追加で書く）
