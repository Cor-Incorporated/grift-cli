# grift — AI時代に痩せない証拠

**日本語** | [English](README.en.md)

Method = **TEP** / Tool = **grift**（CodeScene 型の二層。方法論名は TEP、コマンドは `grift`）。
Named after the Grift product line.

量は誰でも作れる。残るものと、検証が伴った変更を測る。技量スコアではない。

コミット数・行数・「活動量」は、エージェントと生成コードの時代に簡単に膨らむ。grift は git だけから、TEP の帰属（誰の仕事か）と検証層（test co-change ほか）を**決定論的に**出す。LLM は使わない。合成スコアも等級語彙も出さない。

## 5分で始める

```bash
pipx install grift-cli
grift analyze ./my-repo --scope repo
```

- `--scope tenant`（既定）: `.tep/identity.toml` に載った人の仕事 = **証拠用**
- `--scope repo`: bot 以外の全人間コミット = **プロセス観測・参照分布用**

参照分布 v2026.09 は **repo スコープ同士**でのみ照合する。tenant の値を repo 分布に載せない（混ぜたら分布が嘘になる）。

## 実レポート例

自リポで `grift analyze . --format md` を実行する。各数値に単位と provenance（method=TEP・tool=grift・定義版・分析 SHA・`analysis_scope`）が付く。

## 終了コードと stdout / stderr 規約

| 終了コード | 意味 |
|---|---|
| 0 | 成功 |
| 2 | 使用法エラー、または指定パスが git リポジトリでない |
| 1 | その他の予期しない失敗（詳細は stderr） |

`--format json` の stdout は **JSON 1 件のみ**（機械消費向けの純度保証）。`--format md` は markdown のみ、`--format both` は markdown → 空行 → JSON の順。診断とエラーは常に stderr。`--out DIR` を使っても stdout 規約は変わらない（`report.md` / `report.json` の追記のみ）。

report.json の全フィールド定義は [docs/report-schema.md](docs/report-schema.md)（schema `report-v1`・凍結済み・追加互換）。

## 機械取込用 export（opt-in）

`grift analyze <repo> --export <dir>` で commits.ndjson（1行=1コミット・origin/actor/cochange）・actors.json（canonical_id ごとの帰属と活動）・export-meta.json（`config_digest` つき）を書く。**生メールアドレス・生 author 文字列は一切出力しない**。顧客向け叙述に載る数値は report.json の集計値が正。詳細は [docs/export-schema.md](docs/export-schema.md)。

例（click、tenant スコープ。ゴールデン G1）:

- test co-change: 0.2664 ratio（73 of 274）
- corrective rework: 0.0109 ratio（3 of 274）— 観測値。証拠主張ではない
- path retouch: 0.573 ratio — 観測のみ

母数 20 未満では率も分布位置も出さない（`insufficient_population`。件数の生表示のみ）。

## 指標と限界

| 指標 | 何の証拠か | 限界 |
|---|---|---|
| origin / 帰属 | 誰の仕事か | identity 未設定は unresolved。Cor 実メールは同梱しない |
| test co-change | 本番変更にテストが伴うか | テスト基盤なしは not_observed。母数<20 は率も十分位も出さない（`insufficient_population`） |
| corrective rework | 件名が fix/revert の直近パス回帰（観測） | **証拠主張から降格**。件名規約依存の交絡あり。バグ件数ではない。再挑戦は v0.6 行レベル |
| path retouch | 同一ファイル再接触 | 観測のみ。証拠主張に使わない |
| survival (τ=180d) | 行の残り方 | `--survival` のみ。参照分布は **v2027 予定**。今回の公開分布には含めない |

参照位置は「第N十分位」の1行だけ。n<30 の指標は位置を出さない（`reference_too_small`）。v2026.09 の観測 n: test co-change 33 / corrective rework 42（観測）/ survival 0。

## 判別力の現況（repo スコープ・基準 `5f2665e`）

出典: `corpus/DISCRIMINANT-v2026.09.md` Run 2。verdict はファイルから逐語。

- `test_cochange A vs C` → `separated`（median_A 0.2379, median_other 0.0306, gap 0.2073, Cliff δ 0.7143, n 18/7）
- `test_cochange A vs D` → `inconclusive_small_n`（n 18/1。D の narratable 観測が 1）
- `corrective_rework A vs C` → `fail_tier2`（median_A 0.0522, median_other 0.1063, gap -0.0541, Cliff δ -0.7083, n 18/8）。観測診断のみ。証拠主張には使わない
- survival: 本コーパスでは未計測。参照分布は v2027 予定

WP4 Run 1 の記録（`separated` / `inconclusive_small_n` / `fail_tier2`）は同ファイルに履歴として残してある。

## 倫理

- 実在個人のスコアカード・順位表は公開も内部共有も禁止
- 等級語彙（シニア/ジュニア/素晴らしい）を出さない
- コーパスの manifest（リポ名+SHA）は再現用に公開してよい。**個別リポ値のリーグテーブルは公開しない**
- 対照群 E（私的 ground truth）はこのリポに入れない

## 公開状態

- 公開リポ: https://github.com/Cor-Incorporated/grift-cli
- コマンド名: **`grift`**（方法論名 TEP はレポートに残す）
- PyPI: 配布名 **`grift-cli`**。本公開は別ゲート（未了ならソースから `pipx install .`）

## License

MIT. See [LICENSE](LICENSE).
