# Grift v0.6 benchmark pack

このディレクトリは、Grift v0.6 の `repo` / `actor` / `project` / `align` を実証・反証するための、小型で再現可能な参照パックです。

## 重要な位置付け

このパックは「優秀な人」や「合う人」を決める正解表ではありません。外部データの分布、イベント構造、職種ラベル検証、欠損・匿名化の限界を、Griftの観測値と比較するための材料です。

次の区別を必ず維持します。

- `observed`: 実際に入力されたGit／Forge／Trackerから観測した値
- `reference`: 外部データの分布または研究データの比較材料
- `declared`: project.toml等で人間が宣言した要求
- `not_proven`: 公開データだけでは確認できない職種・成果・適合性

## ファイル構成

- `sources.json`: 出典、取得時点、ハッシュ、ライセンス注意、利用範囲
- `data/gharchive_events_2024-01-15_to_21.ndjson`: GH Archiveから抽出した実イベント554件。actor情報と生Payloadは除去済み
- `data/gharchive_repository_summary.csv`: 上記イベントのリポジトリ別集計
- `data/gharchive_daily_summary.csv`: 上記イベントの日別・イベント種別集計
- `data/role_ground_truth_sample.csv`: 技術職種研究データから抽出した5職種40行の匿名化サンプル
- `data/role_label_counts.csv`: 同研究データ全体のラベル件数
- `data/tracker_lifecycle_fixture.csv`: Tracker／Forge期間計算用の決定論的契約fixture。外部観測値ではない
- `data/alignment_cases.jsonl`: 要求軸と観測軸を並べるための決定論的契約fixture
- `schemas/`: NDJSON、職種サンプル、manifestの検証用Schema
- `quality-report.md`: 品質検査、比較可能性、既知の欠損
- `IMPLEMENTATION-AGENT-INSTRUCTIONS.md`: 実装・実証・反証を行うエージェント向け指示

## 実データの取得範囲

GH Archiveの抽出元は、2024-01-15から2024-01-21までの各日00:00 UTCの公開イベントアーカイブです。対象は代表的なOSSリポジトリ8個、イベント種別はPush、Issue、Issue comment、Pull Request、Pull Request review、Review comment、Releaseです。

この7日間fixtureは、イベントの正規化、日別集計、Releaseの扱い、Issue／PR／Reviewの結合テストには使えます。しかし、7日間だけで「速度」や長期的な職種傾向を断定してはいけません。

## 推奨する実行順

```bash
python -m pytest tests/test_cli_v060.py tests/test_v060_rhythm.py tests/test_v060_schema.py tests/test_v060_surfaces.py
PYTHONPATH=src python tests/fixtures/v060/run_p0_falsify.py
```

その後、実装エージェントはこのパックを読み込み、以下の結果を追加で出してください。

```text
repo observed -> reference distribution -> coverage / unknowns
actor observed -> role-lens evidence -> external label validation (separate)
project declared -> forge/tracker observed -> axis-by-axis alignment
```

ベンチマークの母数が少ない場合、分位点や合否を出さず、`reference_too_small` または `not_proven` と表示します。
