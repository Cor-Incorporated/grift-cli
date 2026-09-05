# 実装エージェント向け：Grift v0.6 benchmark pack 実証・反証指示

## 目的

このパックを使って、Grift v0.6が「リポジトリ」「actor」「project」「要求と観測のalignment」を、出典・母数・欠損とともに分離して出力できるかを検証する。

この作業で職種や適合性の正解モデルを実装してはいけない。実証対象は、観測値を正しく計算し、外部参照値と混同せず、判定不能を明示できることです。

## 実装要求

### 1. Benchmark catalog

`benchmarks/v060/sources.json`を読み込むローカル専用の参照カタログを追加する。

最低限、各referenceに以下を保持する。

- `id`
- `kind`
- `source_url`
- `source_version`または取得時点
- `window`
- `n`
- `sha256`または再取得不能理由
- `use_for`
- `do_not_use_for`
- `quality_notes`

外部ネットワークが利用できない場合でも、既存のローカルfixtureだけで同じ結果を出す。分析本体から外部APIを呼ばない。

### 2. Forge event normalization

`data/gharchive_events_2024-01-15_to_21.ndjson`を読み込み、以下を計算できるようにする。

- リポジトリ別イベント数
- 日別イベント数
- Push、Issue、Issue comment、PR、Review、Releaseの内訳
- active UTC days
- first／last observed event
- event typeごとの欠損・未知値

actor login、actor ID、生Payloadを復元・出力してはいけない。

### 3. Project rhythm

イベント時系列から、少なくとも以下を別々に出す。

- `active_day_share`
- `inter_event_gap_median_hours`
- `inter_event_gap_iqr_hours`
- `same_day_event_share`
- `burst_day_share`
- `release_interval_days`（Releaseが2件未満なら`not_proven`）

`constant`／`burst`は観測上の説明ラベルに留める。「速度」「生産性」「優秀」と表現してはいけない。

### 4. Surface profile

既存のpath surface計算を維持し、少なくとも次を出す。

- changed files by surface
- changed lines by surface（取得できる場合のみ）
- frontend／backend／test／docs／ci_cd等の分母付き割合
- unknown／otherの割合
- path heuristicの定義と限界

職種名ではなく、`observed_surface_profile`として出力する。

### 5. External role validation

`data/role_ground_truth_sample.csv`は分類器の評価専用とする。

- accuracy
- macro／weighted precision
- macro／weighted recall
- macro／weighted F1
- confusion matrix
- class support

40行の小型サンプルだけでモデル性能を主張してはいけない。`sample_size_warning`を出す。

出力文は「Frontend Engineerです」ではなく、「Frontendラベルに対する分類器の検証結果」とする。

### 6. Tracker／Forge lifecycle

`data/tracker_lifecycle_fixture.csv`を用いて、次を計算する。

- issue created -> in_progress
- issue created -> closed
- PR created -> first review
- PR created -> merged
- release interval
- linked issue／PR割合

`fixture_kind=synthetic_contract`をレポートに表示し、外部観測値として扱わない。

### 7. Alignment

`data/alignment_cases.jsonl`を用いて、要求軸と観測軸を同じ行に並べる。

必須列は、`axis`、`requirement`、`observed`、`unit`、`source`、`n`、`coverage`、`limitations`です。

総合点、ランキング、採用推奨は出してはいけません。

## 必ず通す反証ケース

1. GH Archive行の`event_type`を未知値に変えると、黙って集計せず、Schemaエラーまたは`unknown_event_type`になること。
2. `occurred_at`を日付範囲外に変えると、fixture外として拒否または警告されること。
3. `event_id`を重複させると、重複件数と影響率が表示されること。
4. ReleaseEventだけのリポジトリを「高速開発」と解釈しないこと。
5. Pushイベントの時刻だけからDORAのChange Lead Timeを算出しないこと。
6. actorのidentityがない状態で職種名を確定しないこと。
7. role validation sampleをGrift actorの本人証拠として出力しないこと。
8. Tracker fixtureの`synthetic_contract`を実データと表示しないこと。
9. `n < 30`の外部分布に分位点・合否を付けないこと。
10. Issue・PR・Reviewの観測だけでPM適合性を確定しないこと。
11. Forge入力が無いprojectでは、Issue／Review未観測を0件と表示せず、`not_observed`と表示すること。
12. 片方の軸だけが欠けたalignmentでは、総合判定をせず、欠損軸を明示すること。

## 完了条件

以下をすべて満たした場合だけ、benchmark integrationを実装済みと扱う。

- 既存v0.6テストが通る
- benchmark packのSchema検査が通る
- 554件のGH Archive抽出行を読み込める
- repository summaryの合計が554件になる
- role sampleが40行、5クラス各8行になる
- tracker fixtureの計算値が決定論的に一致する
- source／window／n／denominator／coverage／limitationsがレポートに現れる
- 上記12反証ケースがすべて検出される
- ネットワークなしでfixtureテストを再実行できる

## 実装後に提出するもの

- 変更ファイル一覧
- 追加CLIの使用例
- 通常系テスト結果
- 反証ケース12件の結果表
- 出力サンプル（repo、actor、project、alignment）
- 未実証の項目一覧
- ベンチマークの出典とハッシュのreadback

## 追加指示：外部ベンチマークパック統合

### 目的

`benchmarks/v060/`に配置済みの実データ抽出、職種ラベル検証サンプル、契約fixture、出典manifestを、Grift v0.6のCLIとレポートから参照できるようにする。

この追加実装の北極星は、次の一文です。

> 観測値、外部参照値、宣言、判定不能を混ぜず、すべてに出典・期間・母数・分母・欠損理由を付けて表示する。

### 取得済みデータの固定値

実装エージェントは、外部ネットワークから再取得せず、まずローカルファイルで実装・テストする。

| ファイル | 内容 | 固定条件 |
|---|---|---|
| `data/gharchive_events_2024-01-15_to_21.ndjson` | GH Archive抽出イベント | 554行、8リポジトリ、7種別、actor／生Payloadなし |
| `data/gharchive_repository_summary.csv` | リポジトリ別集計 | event_count合計554 |
| `data/gharchive_daily_summary.csv` | 日別イベント集計 | 2024-01-15〜21 UTC |
| `data/role_ground_truth_sample.csv` | 技術職種ラベルサンプル | 40行、Backend／Frontend／Mobile／DevOps／DataScientist各8行 |
| `data/role_label_counts.csv` | 研究データ全体のラベル件数 | source-derived summary |
| `data/tracker_lifecycle_fixture.csv` | Issue／PR／Release契約fixture | `synthetic_contract`、外部実測値ではない |
| `data/alignment_cases.jsonl` | 要求軸と観測軸の契約fixture | 総合点を持たない |
| `data/metric_catalog.csv` | v0.6指標カタログ | 指標ごとに単位・分母・未観測条件を持つ |
| `sources.json` | 出典・ハッシュ・利用範囲 | 2026-08-29時点 |

### 実装対象ファイル

既存のv0.6変更を尊重し、最低限以下を確認・変更する。

- `src/tep_cli/options.py`: `benchmark`サブコマンド、`--reference`、projectの`--forge-export`／`--tracker-export`
- `src/tep_cli/subject.py`: repo／actor／project／alignからの参照読込と入力digest
- `src/tep_cli/__main__.py`: `benchmark list|inspect|validate`のdispatch
- `src/tep_core/benchmark.py`: manifest読込、参照定義、ローカルfixture検証、ハッシュ検証
- `src/tep_core/forge.py`: 正規化イベントの読込とイベント種別・欠損検査
- `src/tep_core/tracker.py`: Issue／PR／Release lifecycle計算
- `src/tep_core/project.py`: Forge／Tracker入力をproject observedへ渡す経路
- `src/tep_core/report_v2.py`: reference、coverage、limitations、not_observedの可読表示
- `src/tep_core/schema_v2.py`: reference-v1の任意ブロックと厳格なobservedノード検証
- `tests/`: benchmark integration、offline、negative、readabilityの追加テスト

### CLIの必須形

既存の`repo`／`actor`／`project`／`align`と旧`analyze`互換aliasを壊さない。

```bash
grift benchmark list
grift benchmark inspect gharchive-2024-01-15-to-21-selected-repos
grift benchmark validate benchmarks/v060/sources.json

grift repo . --reference gharchive-2024-01-15-to-21-selected-repos
grift project . \
  --requirements .tep/project.toml \
  --forge-export benchmarks/v060/data/gharchive_events_2024-01-15_to_21.ndjson \
  --tracker-export benchmarks/v060/data/tracker_lifecycle_fixture.csv
grift actor candidate_001 --identity .tep/identity.toml
grift align --repo . --identity .tep/identity.toml --actor candidate_001 \
  --project .tep/project.toml --reference gharchive-2024-01-15-to-21-selected-repos
```

`--reference`は比較材料を指定するオプションであり、合否・ランキング・採用推奨を有効にするオプションではない。旧`--reference-version`は互換維持する。

### 出力契約

report-v2、project-v1、alignment-v1の既存構造を壊さず、任意の`reference`ブロックを追加する。各比較値は少なくとも次の形にする。

```json
{
  "metric_id": "rhythm.active_day_share",
  "observed": {"value": 0.42, "unit": "ratio", "n": 76, "denominator": 180},
  "reference": {"source_id": "numfocus-2022-to-2024", "n": 58, "summary": "distribution unavailable in local pack"},
  "coverage": {"status": "partial", "missing": ["production_deployments"]},
  "limitations": ["Git event time is not production delivery time"],
  "interpretation": "observed rhythm only"
}
```

実データが無い場合は0ではなく、次のいずれかを返す。

- `not_observed`: Forge／Tracker／Deploy入力が無い
- `not_proven`: 職種、PM成果、適合性などを確認できない
- `reference_too_small`: 参照母数が不足
- `partial`: 一部の入力だけ存在

### ProjectへのForge／Tracker統合

現在のproject経路がGit-onlyのままなら、追加実装は未達とする。

- `--forge-export`を渡した場合、Issue／PR／Review／Releaseをproject observedへ反映する
- `--tracker-export`を渡した場合、Issue状態、滞留、解決時間、リンクを反映する
- 入力が無い項目を0件と表示しない
- `synthetic_contract`を実測値として表示しない
- Gitのmerge commitをPull Request Reviewと呼ばない
- GitのCommit間隔をDORA Change Lead Timeと呼ばない

### Role／PMの禁止境界

- `role_ground_truth_sample.csv`は分類器の外部検証だけに使う
- actor reportに研究データのBackend／Frontendラベルを注入しない
- actor reportは`observed_surface_profile`を表示し、職種確定文を出さない
- Issue／PR／Review観測だけでPM適合度、PM成果、採用可否を出さない
- `role_lens`を分類器または適性判定器へ変更しない
- 複数actorの品質指標、ランキング、合否、総合fit scoreを出さない

### 追加の反証ケース

既存12ケースに加えて、次を必ず自動テストする。

1. `sources.json`のローカルハッシュを1文字変えると`benchmark validate`が失敗する。
2. manifestに未登録のfixture pathを指定すると読込を拒否する。
3. ネットワークを遮断してもbenchmark fixtureのテストが通る。
4. GH ArchiveのReleaseEventだけを含む入力で、速度・品質・成功率を出さない。
5. `--forge-export`なしのprojectで、review／issueを0件と表示しない。
6. `--tracker-export`の状態順を逆にしても、入力エラーまたは同じ決定論結果になる。
7. `role_ground_truth_sample.csv`のラベルをactor identityへ結合しようとした処理を拒否する。
8. 参照母数を29件以下にした場合、分位点・合否・ランキングを出さない。
9. 要求だけ存在し観測値が無いalignmentで、総合判定を出さない。
10. 観測値だけ存在し要求が無いalignmentで、適合判定を出さない。
11. `active_day_share`の分母を変更すると、出力の分母とdigestが変わる。
12. `occurred_at`のtimezoneを変更すると、正規化規則を表示し、黙って同一視しない。

### 実装前スパイク回答欄

コード変更前に、実装エージェントは次の回答を指示書またはPR本文へ記録する。

- 現在のproject parserから`run_project`へForge／Trackerが渡っていない箇所はどこか
- reference定義を既存のrepo distributionとどう分離するか
- role validationをactor reportへ混入させない境界はどこか
- `not_observed`と0件をどのSchema／rendererで強制するか
- 外部ネットワークを呼ばずに同じテストを再実行する方法は何か
- 既存v0.5.9互換とv0.6 reference出力をどう同時に保つか

### 強制点の実測表

| 宣言 | 強制点 | 片側変異で反証する内容 |
|---|---|---|
| `sources.json`のhash固定 | `benchmark.py`のvalidate | hashを1文字変えてred |
| event schema | `event-observation.schema.json`＋forge loader | 未知event typeでred |
| project Forge／Tracker入力 | options parser＋`run_project` | parserだけ追加してrun_projectを変えない変異でred |
| observedの必須値 | `schema_v2.py` | kindだけのobservedでred |
| not_observed表示 | report renderer | 入力なしを0件にする変異でred |
| role-lens非分類 | role_lens＋report文言テスト | Backend適性点を出す変異でred |
| alignment軸比較のみ | alignment schema＋renderer | overall scoreを追加する変異でred |
| offline決定論 | fixture tests＋network拒否環境 | 外部API依存でred |

### 停止条件・報告・人間ゲート

- 最大6反復。同一エラー3回、30分無進捗、入力仕様の判断待ちで停止して報告する
- 着手時、最初の実行可能状態、通常系テスト完了時、反証完了時に進捗を報告する
- 有料API、認証済み外部データ、個人情報の再取得は行わない
- 現在のdirty worktreeをreset、clean、削除、上書きしない
- 新規データセットやMLモデルを勝手に追加提案しない
- commit、push、merge、PR作成はこの追加指示の完了条件に含めず、別途人間ゲートとする

### H8補助情報

- 一次資料：`sources.json`に記録したGH Archive、GitHub Events、Zenodo職種データ、NumFOCUS、TAWOS、Public Jira、SmartSHARK、DORA、SPACE、GitHub ESSP
- 要求インベントリ：event、surface、rhythm、issue、PR、review、release、role validation、alignment、offline、provenance
- 突合表：`quality-report.md`と`data/metric_catalog.csv`
- 標準質問：これは観測か、参照か、宣言か、未証明か。分母は何か。欠損は何か。時刻は何を表すか
- 北極星：出典・母数付きの観測を分離して読めること
- 反証軸：上記12ケース、既存12ケース、旧CLI互換、決定論、PII非漏洩
- 撤収：ライセンスまたは再配布条件が不明な生データは同梱せず、metadataと小型fixtureだけを残す

### 最終検査

```bash
PYTHONPATH=src pytest -q \
  tests/test_benchmark_pack_v060.py \
  tests/test_cli_v060.py \
  tests/test_v060_rhythm.py \
  tests/test_v060_schema.py \
  tests/test_v060_surfaces.py

PYTHONPATH=src python tests/fixtures/v060/run_p0_falsify.py
grift benchmark validate benchmarks/v060/sources.json
```

最終報告には、変更ファイル、CLI実行例、通常系テスト、既存12＋追加12反証結果、出典ハッシュ、未実証項目を含める。`implemented`、`PR-ready`、`merged`、`deployed`、`live evidence`、`issue-closeable`を混同しない。
