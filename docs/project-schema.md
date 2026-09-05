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

Git-only の observed は運用の形（surface / rhythm / verification）であり、review / issue 運用は含みません。
project 側でそれらを見る場合は `--forge-export` / `--tracker-export` を明示します。付けない限り `not_observed` です。
`align` の観測値は actor 側の入力です。project の運用実態を actor の export 有無だけで代表しません。
