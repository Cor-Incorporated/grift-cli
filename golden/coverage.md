# Golden coverage matrix — 観測フィールド x golden repo（v2 wave 1）

自動生成: `scripts/gen_coverage_table.py`（`tests/coverage_matrix.py` が計算ロジックの単一実装）。
**手書き編集禁止** — テスト `tests/test_coverage.py` がこの表と expected ファイルの突合を行う。

記号: `o` = observed（励起。0 も合法な観測値）/ `x` = not_observed / `-` = 期待値に未ピン。
要件: `excited` = o>=1 / `both` = o>=1 かつ x>=1（新観測は both を満たすこと — golden-v2 指示 1-1）。
HOLE 行は機械検出された穴。**穴は静かに放置しない** — 表の HOLE と issue 番号の対応を
tests/test_coverage.py の KNOWN_HOLES が強制する。

波2/3行（context v2 / experience）はプレースホルダ: 該当実装の PR で expected に追記し
both 要件の機械検証を有効化するまで `-` が並ぶ。


| field | wave | req | G1-click | G2-gitignore | G3-spoon-knife | G4-express | G5-typer | G6-claude-code | G7-axios | G8-co | G9-pyscript | G10-scvi-tools | G11-kilo | G12-httpx | G13-voicevox | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| origin: tenant_unique | 1 | excited | o | o | o | o | o | o | o | o | o | o | o | o | o | ok |  |
| origin: tenant_merge_or_sync | 1 | excited | o | o | x | o | o | o | o | o | o | o | o | o | o | ok |  |
| origin: upstream_sync | 1 | excited | x | x | o | x | x | x | x | x | x | x | x | x | x | ok |  |
| origin: inherited_upstream | 1 | excited | o | o | o | o | o | o | o | o | o | o | o | o | o | ok |  |
| origin: generated_or_vendor | 1 | excited | o | o | o | o | o | o | o | o | o | o | o | o | o | ok | --vendor-scan ピンなし（全 pin で observed 0） |
| origin: template_inherited | 1 | excited | x | x | x | x | x | x | x | x | x | x | x | x | x | HOLE | --template ピンなし（全 pin not_observed） |
| origin: tenant_derivative | 1 | info | x | x | x | x | x | x | x | x | x | x | x | x | x | ok | --parent-repo ピンなし（設計上 not_observed） |
| origin: external_upstream_contribution | 1 | info | x | x | x | x | x | x | x | x | x | x | x | x | x | ok | --parent-repo ピンなし（設計上 not_observed） |
| origin: ambiguous_origin | 1 | info | o | o | o | o | o | o | o | o | o | o | o | o | o | ok | 空メール fixture のみで励起（golden では observed 0） |
| origin: unresolved | 1 | excited | o | o | o | o | o | o | o | o | o | o | o | o | o | ok |  |
| origin: bot | 1 | excited | - | - | - | - | - | o | o | o | o | o | o | o | o | ok |  |
| attribution: bot | 1 | excited | o | o | o | o | o | o | o | o | o | o | o | o | o | ok |  |
| activity: active_days | 1 | excited | o | - | - | - | - | o | o | o | o | o | o | o | o | ok |  |
| activity: cpad median | 1 | excited | o | - | - | - | - | x | x | x | x | x | x | x | x | ok |  |
| activity: active_days_13w | 1 | excited | - | - | - | - | - | o | o | o | o | o | o | o | o | ok |  |
| core_activity_period | 1 | excited | o | x | - | - | x | x | x | x | x | x | x | x | x | ok |  |
| test_frameworks | 1 | both | o | x | x | o | o | x | o | o | x | o | x | o | o | ok |  |
| test_cochange | 1 | both | o | x | x | x | x | x | x | x | x | x | x | x | x | ok |  |
| rework: corrective_rework_rate | 1 | both | o | x | x | x | x | x | x | x | x | x | x | x | x | ok |  |
| rework: path_retouch_rate | 1 | both | o | x | x | x | x | x | x | x | x | x | x | x | x | ok |  |
| rework: revert_rate | 1 | excited | o | x | x | x | x | x | x | x | x | x | x | x | x | ok | G1 expected は subset（revert_rate 未ピン）→ 再生成必要 |
| survival | 1 | info | x | x | x | x | x | x | x | x | x | x | x | x | x | ok | opt-in（--survival）。golden では恒常 not_observed。corpus runs で実測 |
| interpretation | 1 | info | - | - | - | - | - | - | - | - | - | - | - | - | - | ok | repo スコープ専用。golden は tenant スコープ（scope_is_tenant）。corpus v2026.09 で励起 |
| context v2: lifecycle_stage | 2 | both | - | - | - | - | - | - | - | - | - | - | - | - | - | future | G8 (dormant) / G7,G13 (active) で両側を予定期 |
| context v2: language_composition | 2 | both | - | - | - | - | - | - | - | - | - | - | - | - | - | future | G9 polyglot で励起予定期 |
| experience: declared_ai_assist_share | 3 | both | - | - | - | - | - | - | - | - | - | - | - | - | - | future | G6 (AI 共著トレーラー実在) で励起・G1〜G5,G11 で not_observed 予定期 |
| experience: cross_author_modification_share | 3 | both | - | - | - | - | - | - | - | - | - | - | - | - | - | future | G7 (handoff 多数) で励起・G11 (solo) で not_observed/低位 予定期 |
| experience: founder 時期性 | 3 | both | - | - | - | - | - | - | - | - | - | - | - | - | - | future | G12 (Tom Christie) で励起予定期 |

pins: 13 / 上限 13（master §3-1）

## 機検出された HOLE（issue トラック必須）
- origin.template_inherited

## 実行時間証跡（受入⑥・週次 CI 予算）

- 2026-08-22 wave 1: 13 repos, warm cache: 14.6s wall (`TEP_GOLDEN=1 pytest -m golden`; clone 済み .golden-cache)。コールド clone 込みは pins 追加時の `gen_golden_expected.py` 実行で別計上

| pin | collaboration | lifecycle | era | ecosystem | questions | reason(抜粋) |
|---|---|---|---|---|---|---|
| G1-click | - | - | - | - | - |  |
| G2-gitignore | - | - | - | - | - |  |
| G3-spoon-knife | - | - | - | - | - |  |
| G4-express | - | - | - | - | - |  |
| G5-typer | - | - | - | - | - |  |
| G6-claude-code | ai-coauthored | active | 2024+ | typescript | Q5,E4 | AI co-author trailers actually present (67 commits with Claude trailers; e.g. 1f |
| G7-axios | community-handoff | active | pre-2024 | javascript | Q3,E1,E3 | 443 contributors; lib/axios.js modified by 22 distinct authors over time incl. o |
| G8-co | small-community | dormant-since-2016 | pre-2024 | javascript | Q6 | Famous dormant repo: last master commit 2016-10-17 after active 2011-2016; 11.8k |
| G9-pyscript | community | active | 2022+ | polyglot-python-js-ts | Q2 | Polyglot monorepo: pyproject.toml + core/package.json + bridge/package.json; Pyt |
| G10-scvi-tools | community | active | 2024+ | python | Q2,D-class | Template-derived: root .cruft.json names cookiecutter-scverse template URL + che |
| G11-kilo | solo | dormant | pre-2024 | c | E2 | Solo personal project: antirez 14/20 commits, single-drive-by others; <1k LOC ed |
| G12-httpx | founder-led | active | 2019+ | python | Q7,E6 | Clear founder: oldest commit 'Initial commit' by Tom Christie 2019-04-04, remain |
| G13-voicevox | community | active | 2024+ | typescript-japanese-oss | Q2,robustness | Japanese-origin OSS: README.md Japanese-first ('VOICEVOX のエディタです。'), Japanese co |
