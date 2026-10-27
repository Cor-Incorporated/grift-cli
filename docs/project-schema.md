# project-v1

案件所有者が入力する **declared requirements** と、Git から観測した **operating signature** を分ける。会社評価ではない。空欄は `not_declared` であり、0 でも不足でもない。

TOML 入力の schema は `tep-project-v1`。JSON 出力は `project-v1`。

## 空 template

`grift project --init --out FILE` は値を推測せず、既存ファイルを上書きしない。

```toml
schema_version = "tep-project-v1"
project_id = "checkout-api"
title = "Checkout API"

[requirements.change_rhythm]
# 未記入の値は要求なし。単位は日。
active_days_180d_min = 20
median_gap_days_max = 14
p90_gap_days_max = 60

[requirements.surfaces]
required = ["backend", "data"]

[requirements.verification]
required = ["unit", "integration"]

[requirements.inputs]
required = ["git", "forge"]

[requirements.role_lens]
name = "backend"
```

## 許可値

- `project_id`: `^[a-z0-9][a-z0-9._-]{0,63}$`（identity の canonical_id と同じ）
- surface: `frontend`, `backend`, `data`, `platform`, `ci_cd`, `observability`, `test`, `docs`, `config`, `generated_vendor`, `other`
- verification: `unit`, `integration`, `e2e`, `contract`, `unspecified`
- inputs: `git`, `forge`, `tracker`
- role lens: `frontend`, `backend`, `data`, `platform`, `qa`, `full-stack`, `tech-lead`, `pm`

`grift project --requirements FILE` は declared view。
`grift project REPO --requirements FILE` は observed と declared を別セクションにする。

## provenance.revision_completeness

リポジトリを渡した（`observed.kind = "observed"`）ときだけ、`provenance.revision_completeness` に
そのリポジトリが浅い clone か部分 clone かを書きます（0.9.1 から）。形は report-v2 と同じです。

```json
"revision_completeness": {"shallow": false, "promisor": false, "complete": true}
```

- 3 つの key（`shallow`・`promisor`・`complete`）がそろい、値はどれも真偽値です。
  `complete` は `shallow` も `promisor` も `false` のときだけ `true` です。
- declared view（リポジトリを渡していない）には書きません。書いてあると schema の検査で止まります。
- 0.9.0 までに保存した project-v1 にはこの key がありません。そのまま読み込めて、浅い clone かどうかは
  「分からない」として扱います。
- `grift verify` は、記録したリポジトリから作り直した値と比べます。違えば `MISMATCH` です。
- Markdown の先頭の節は、`shallow` が `false` のときだけ範囲を「{観測日} までの全履歴」と書きます。
  `true` か key が無いときは「{観測日} までの履歴」と書き、限界の注記を付けます（[trait-profile](trait-profile.md)）。

Git-only の observed は運用の形（surface / rhythm / verification）であり、review / issue 運用は含みません。
project 側でそれらを見る場合は `--forge-export` / `--tracker-export` を明示します。付けない限り `not_observed` です。
`align` の観測値は actor 側の入力です。project の運用実態を actor の export 有無だけで代表しません。
