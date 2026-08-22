# export-v1 スキーマ — 機械取込用 opt-in 出力（凍結 2026-08-22）

`grift analyze <repo> --export <dir>` が書く3ファイルの契約。Grift 本体統合（WP-G1）の取込対象。
report-v1（`docs/report-schema.md`）と同じ追加互換規約: **export-v1 の間は追加のみ**（改名・削除・意味変更は v2）。

- 定数: `tep_core.export.EXPORT_SCHEMA_VERSION = "tep-export-v1"`
- report と export は同一の `prepare_inputs()`（commits 読み込み + origin 分類）を共有する。**単一実装**であり、二つの出力が乖離する余地は構造的にない

## 境界（裁定 2026-08-22 二層契約）

- 顧客向け叙述に載る数値は **report.json の集計値が正**（消費者は明細から独自集計した別の数を narrate しない）
- 参照分布の位置は repo スコープ実行の出力のみ
- 母数<20 非表示・`not_observed` ≠ 0 の上書き禁止 — 従来どおり
- **per-actor の品質指標（actor別 co-change 等）は export-v2 でも解禁しない**（個人を評価対象にする出力の禁止レール）

## ファイル構成

| ファイル | 内容 |
|---|---|
| `commits.ndjson` | 1行 = 1コミット（NDJSON）。**git log 順（新しいコミットが先頭）** |
| `actors.json` | canonical_id ごとの帰属と活動（engagement）。JSON 配列 |
| `export-meta.json` | スキーマ版・provenance・`config_digest` |

## commits.ndjson（1行のフィールド）

| フィールド | 型 | 意味 |
|---|---|---|
| `sha` | string (40 hex) | コミット SHA |
| `ts` | string `YYYY-MM-DD` | author date（日精度。他の全指標と同じ `--date=short` 由来） |
| `origin` | string | 11分類のいずれか（report-v1 origin と同一語彙） |
| `actor` | string \| null | 解決できたら `canonical_id`、できなければ null。**生メール・生 author 文字列は出ない** |
| `bot` | bool | origin == `bot` と同値 |
| `is_merge` | bool | 親コミット複数 |
| `prod_paths_touched` | int >= 0 | 本番パス変更数（report と同一の path 分類） |
| `test_paths_touched` | int >= 0 | テストパス変更数 |
| `cochange` | bool \| null | **本番変更コミットのみ値を持つ**（prod_paths_touched > 0）。そのコミットがテストも変更したか。それ以外は null |
| `subject_class` | string | `fix` \| `revert` \| `other`（report の rework 定義と同一正規表現） |

merge コミットは `git log --name-only` の仕様上ファイル一覧が空になるため `prod_paths_touched = 0`・`cochange = null` になる。

## actors.json（1要素のフィールド）

| フィールド | 型 | 意味 |
|---|---|---|
| `canonical_id` | string | identity の安定 ID（**`@` を含めてはならない**） |
| `attribution_state` | string | identity の当該 actor の状態 |
| `commits` | int >= 1 | この actor の `tenant_unique` コミット数 |
| `active_days` | int >= 1 | 一意な活動日数 |
| `first_ts` / `last_ts` | string `YYYY-MM-DD` | 最初・最後の tenant_unique コミット日 |
| `core_period` | object | report-v1 の `core_activity_period` と同一構造（この actor の日付で計算） |

actor 行を持つのは **tenant_unique コミットが1以上の canonical_id のみ**。pattern 推論（actor 行なし）・bot・unresolved は行を持たない（commits.ndjson の `actor` が null で表現）。actor 順は canonical_id 辞書順（決定論的）。

## export-meta.json

| フィールド | 型 | 意味 |
|---|---|---|
| `schema` | string | 常に `"tep-export-v1"` |
| `tool_name` / `tool_version` | string | `"grift"` / SEMVER |
| `definition_version` / `origin_definition_version` / `activity_definition_version` | string | report-v1 provenance と同一 |
| `analysis_scope` | string | `tenant` \| `repo` |
| `analyzed_commit_sha` | string (40 hex) | |
| `analyzed_at` | string UTC | |
| `config_digest` | string (64 hex) | 下記 |
| `commit_count` | int | commits.ndjson の行数 |

## config_digest の正規化（Grift 側再計算用の完全仕様)

`sha256( json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") )` の hexdigest。

`payload` の内容:

```json
{
  "schema": "tep-export-v1",
  "definition_version": "<DEFINITION_VERSION>",
  "origin_definition_version": "<ORIGIN_DEFINITION_VERSION>",
  "activity_definition_version": "<ACTIVITY_DEFINITION_VERSION>",
  "analysis_scope": "<tenant|repo>",
  "lineage": {"is_fork": <bool>, "parent": <string|null>},
  "template_provided": <bool>,
  "parent_repo_provided": <bool>,
  "vendor_scan": <bool>,
  "identity": {
    "actors": [
      {"canonical_id": "<id>", "attribution_state": "<state>",
       "emails": [<sorted strings>], "github_login": <string|null>}
    ],
    "email_patterns": [<sorted raw pattern strings>]
  }
}
```

- actors は canonical_id 辞書順、emails と email_patterns は辞書順ソート
- 生メールは digest 計算には入るが**ディスクには出力されない**。identity.toml を生成した側（Grift）は同じ正規化でローカル再計算・照合できる
- digest は設定のみから計算（analyzed_at / SHA を含まない）。同一設定なら再実行しても不変

## 取込パリティ（消費者の義務 — 裁定3）

取込側は commits.ndjson から origin 別行数合計（および test co-change）を再計算し、report.json の集計値と**一致しない場合は取込を中止**すること。CLI 側テスト（`tests/test_export.py`）がこの再計算を tenant / repo 両スコープで自動検証している。

### パリティ検算レシピ（取込側はこの式を逐語実行する — F-P10-1）

行 `r` は commits.ndjson の1行（JSON object）。以下の式は Python 式としてそのまま実行可能であること（`tests/test_export_recipe.py` が本節の式を文字列どおり取り出して実行し、doc と実装の乖離を検出する）。

**origin パリティ（スコープ共通）**:

- 各クラス c の行数: `sum(1 for r in rows if r["origin"] == c)`
- 突合先: `report["origin"][c]`。`kind == "observed"` なら `value` と一致すること。`kind == "not_observed"` なら行数 0 であること

**test co-change パリティ — tenant スコープ**:

- 母集団フィルタ（tenant）: `r["origin"] == "tenant_unique" and r["cochange"] is not None`
- cochanged フィルタ（tenant）: `r["origin"] == "tenant_unique" and r["cochange"] is True`
- 突合先: `report["test_cochange"]["all_time"]` の `population` / `cochanged`（`test_cochange.kind == "not_observed"` のときは検算対象なし）

**test co-change パリティ — repo スコープ**:

- 母集団フィルタ（repo）: `r["bot"] is False and r["is_merge"] is False and r["cochange"] is not None`
- cochanged フィルタ（repo）: `r["bot"] is False and r["is_merge"] is False and r["cochange"] is True`
- 突合先: 同上

**既知の誤実装（検収 追記9 の実例）**: tenant スコープで `cochange is not None` を忘れると、テスト専用コミットや merge まで母集団に混入し、誤った率（click で 73/274=0.2664 が正しいのに 444/1537=0.2889 を出す）を「パリティ不一致」として誤検知する。`cochange is not None`（= 本番変更コミット）の絞り込みは省略禁止。

## 終了コードと stdout

`--export` は stdout 規約を変えない（`--format json` の stdout は JSON 1 件のまま）。export は常にファイルのみに書く。
