# grift — AI時代に痩せない証拠

**日本語** | [English](README.en.md)

Method = **TEP** / Tool = **grift**（CodeScene 型の二層。方法論名は TEP、コマンドは `grift`）。
Named after the Grift product line.

量は誰でも作れる。残るものと、検証が伴った変更を測る。技量スコアではない。

## 利用規範（norms）

「TEP 準拠」を名乗る利用の条件を [docs/norms.md](docs/norms.md) に定める（不在を負に読まない・単独足切り禁止・申告を負に読まない・同意なき第三者プロファイリング禁止・監視転用非準拠・選択性の明示・重み付け禁止の7条・日英併記）。**本規範への適合を「TEP」の名の使用条件とする。**

コミット数・行数・「活動量」は、エージェントと生成コードの時代に簡単に膨らむ。grift は git だけから、TEP の帰属（誰の仕事か）と検証層（test co-change ほか）を**決定論的に**出す。LLM は使わない。合成スコアも等級語彙も出さない。

## 5分で始める

```bash
pipx install grift-cli
grift analyze ./my-repo --scope repo --out ./out
```

- `--scope tenant`（既定）: `.tep/identity.toml` に載った人の仕事 = **証拠用**
- `--scope repo`: bot 以外の全人間コミット = **プロセス観測・参照分布用**

**初回の簡単導線**: リポジトリ内で `grift report` だけでも現在の HEAD を分析して `./out/report.md` と `report.json` を書き出します（既存の `./out/report.json` があっても常に再分析します）。**確実に指定条件で測りたいとき・CI では `grift analyze . --scope repo --out ./out` を使ってください**（`report` は repo スコープ固定の省略形です）。

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

## データ提出（grift contribute・明示的 opt-in）

`grift contribute <repo-scopeのreport.json> --out contribution.json` は **TEP Report 集計と参照分布 vNext** への提出 payload を組み立てる。**CLI は何も送信しない（自動送信は恒久禁止）** — payload 全文を表示し、「この提出は公開リポジトリに載る」ことを明示した上で、提出はあなた自身が PR で行う。payload は repo スコープ集計値 + context_profile（クラス級）+ 定義版のみで、canonical_id・メール・パス・repo 名・tenant スコープ値は含まない（`docs/norms.md` 保持・削除条項参照）。

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

参照位置は「第N十分位」の1行だけ。n<30 の指標は位置を出さない（`reference_too_small`）。現行 v2026.11 の観測 n: test co-change 68 / corrective rework 101（観測）/ survival 0（v2027 予定）。旧 v2026.09 は不変のまま `--reference-version` で選択可能。

## 判別力の現況（repo スコープ・基準 `5f2665e`）

出典: `corpus/DISCRIMINANT-v2026.11.md`（n=117・v2026.09 全行 + v2026.11 admission 70 件）。verdict はファイルから逐語。

- `test_cochange A vs D` → `separated`（median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18）— **初めて n が立った分離**。「量は誰でも作れる」テーゼの最初の強い実証
- `test_cochange A vs C` → `fail_tier2`（median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21）— v2026.09 では `separated`（δ 0.7143）だったが、C 群が「tests を持つ AI 駆動 repo」に広がり分離が低下。**登録済み基準は下げず転回をそのまま公開する**
- `corrective_rework A vs C / A vs D` → 方向要件なし（観測専用・v0.5.0 から不変）。A vs C δ -0.8333 / A vs D δ 0.0139
- 母数の正直な記録: C narratable = 14（目標 30 に不足・admission 実測で訂正）/ D total 29（目標 20 達成）
- survival: 参照分布は v2027 予定

v2026.09 の記録（Run 2: A vs C `separated` ほか）は `corpus/DISCRIMINANT-v2026.09.md` に履歴として残してある。

## GitHub Action（観測のみ）

```yaml
uses: Cor-Incorporated/grift-cli@v0.5.4
with:
  scope: repo
```

- `grift analyze` を実行し、**$GITHUB_STEP_SUMMARY に共有ブロック**を出力、report.md / report.json を artifact に upload
- **合否・閾値・fail は実装しない**（観測のみ・ゲート化は恒久にしない）
- PR コメント投稿は `comment: true` の明示オプトインのみ（既定 off）
- permissions は最小限（`contents: read` を推奨。`comment: true` のみ `pull-requests: write` が必要）

## 倫理

- 実在個人のスコアカード・順位表は公開も内部共有も禁止
- 等級語彙（シニア/ジュニア/素晴らしい）を出さない
- コーパスの manifest（リポ名+SHA）は再現用に公開してよい。**個別リポ値のリーグテーブルは公開しない**
- 対照群 E（私的 ground truth）はこのリポに入れない

## 公開状態

- 公開リポ: https://github.com/Cor-Incorporated/grift-cli
- コマンド名: **`grift`**（方法論名 TEP はレポートに残す）
- PyPI: 配布名 **`grift-cli`**（公開済み: `pipx install grift-cli`・最新版は [PyPI](https://pypi.org/project/grift-cli/) を参照）

## License

MIT. See [LICENSE](LICENSE).
