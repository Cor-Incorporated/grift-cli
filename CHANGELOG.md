# Changelog

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)。バージョンは SemVer。

タグ・PyPI・リポ public 化は本ファイルの記載対象外（人間ゲート）。

## [0.5.6] — 2026-08-23

公開後検収で発見の仕様記述↔実挙動の矛盾 3 件（D-1/D-2/D-3）を解消するホットフィックス。

### Fixed

- **動詞の意味を確定: `analyze` = 表示（stdout）・`report` = 記録（`.grift/`）**。README 日英の 2 語動詞表の analyze 行（「`.grift/` を生成」と誤記）を訂正
- **D-3b**: 裸 `grift analyze` の既定スコープを **repo** に統一（パス明示の従来モードは既定 tenant のまま不変）
- **D-3a**: `grift report --scope {repo,tenant}`（既定 repo）を追加
- D-2 文書: report の help「default: ./out」誤記を `.grift/` に訂正・docstring/examples を動詞意味確定版に更新
- **errata（0.5.5 の記載について）**: 0.5.5 の README/EVIDENCE に「裸 `grift analyze` が `.grift/` を自動生成する」との記述があったが、実挙動は stdout 出力のみ（`.grift/` は `grift report` が作る）。本版で文書をバイナリに合わせ、動詞意味を上記のとおり確定した
- CHANGELOG の受け口 URL 表記を tep-contributions に統一

### Added（報告規律・恒久）

- **「wheel 実測」節の各 claim には実行コマンドと生ログを添付する**（0.5.5 で裸 analyze の claim が公開 wheel で再現しなかった件の再発防止）

### テスト（反証）

- 裸 analyze が `.grift/` を作らず stdout へ出すピン / 裸 analyze の scope=repo ピン / パス明示の既定 tenant 維持ピン / 裸 report が `.grift/` を書き scope=repo のピン / `report --scope tenant` のピン / help 文言の golden（`./out` 残存なし）

## [0.5.5] — 2026-08-23

UX 統一（2語動詞 + `.grift/` 出力）+ contribute 受け口の実運用化 + 全ドキュメント日英対応。

### Changed

- **基本操作はすべて `grift <動詞>` の2語で完結**: `grift analyze`（対象=カレント・出力=`.grift/`）・`grift report`（常に HEAD を再分析）・`grift verify`（`.grift/report.json` をカレントリポで再計算）・`grift contribute`（`.grift/report.json` から payload 組立）。明示指定は従来どおり引数で
- **出力先を `.grift/` に統一**（旧 `./out`・`.grift-out` は読み取り互換のみ）。`.gitignore` への `.grift/` 追加を推奨・リポ標準 `.gitignore` に同梱
- Action の作業ディレクトリも `.grift/` へ・既定ピン 0.5.5

### Added

- **contribute 受け口リポ [grift-contributions](https://github.com/Cor-Incorporated/grift-contributions) を開設**: README（日英）・CONTRIBUTING・schema 検証 CI（`tep-contribution-v1`・メール形状拒否・禁止キー検査）。`grift contribute` の確認文が提出先と手順を明示
- **全公開ドキュメントの英語版を `docs/en/` に追加**: norms / metrics-guide（v2・帯規約・インベントリ・関連ツール節を含む完全英訳）/ report-schema / export-schema / identity-schema / corpus-protocol / coverage-map / persona-answers
- 読み方ガイド v2（帯規約の統一定義・全観測インベントリ・関連ツール節・表記確定）

### Removed

- publish-testpypi ワークフロー（TestPyPI シークレット不在による恒久失敗のため削除）

## [0.5.4] — 2026-08-23

`grift report` の stale 出力問題を解消 + 表示の版残存を一掃。

### Fixed

- **`grift report`（引数なし）は既存の `./out/report.json` があっても常に現在の HEAD を再分析**する（提唱者実測で検出: 旧仕様は既存 JSON を再表示し、2コミット目以降の SHA が古いまま残った — 自己証明の信頼性を損なう重大な問題として処理）。再分析なしの再レンダリングは引数指定時のみ
- README 日英: Action 使用例を `@v0.5.4` へ・**PyPI 欄を版に依存しない表記に変更**（「最新 0.5.2」等の古い版番号が残り続ける問題を構造的に解消）・`grift report` を「初回の簡単導線」として条件付きで説明（主 CTA は `grift analyze . --scope repo --out ./out` を維持）
- action.yml 既定ピンを 0.5.4 へ

## [0.5.3] — 2026-08-23

UX 改善（代表フィードバック）+ 公開 README の整合。

### Changed

- **`grift report`（引数なし）= そのディレクトリを分析して `./out/report.{json,md}` を自動作成**（`out/` がなければ作る）。引数を渡した場合は従来どおり既存 JSON からの再レンダリング（再分析なし）
- `grift contribute`（引数なし）は `./out/report.json` → `.grift-out/report.json` → `./report.json` を自動探索。無ければ「先に `grift report` を」と案内
- GitHub Action の使用例を `@v0.5.2` ぼ更新・「本公開は別ゲート」注記を公開済み表示に更新（README 日英）

### Fixed

- hygiene 除外リストに内部調査文書プレフィックス（SMOKE / REREVIEW / RELEASE-REHEARSAL / INTERNAL-PILOT）を追加

## [0.5.2] — 2026-08-23

基準の憲法（norms / reader's guide / verify）+ 文脈層（context_profile v2・lifecycle-v2）+ corpus v2026.11 + contribute。

### Added

- **norms.md v1**（7条 ja/en + 保持・削除条項）: 「TEP 準拠」の使用条件を定義。README 日英からリンク
- **reader's guide**: 全 report.md 末尾に「この数値でしてはいけない判断」節を自動同梱（テンプレート固定・LLM 不使用）
- **`grift verify`**: report.json を記録 provenance で再計算し全フィールド突合（VERIFIED / MISMATCH / CANNOT_VERIFY・exit 0/1/2）。改ざん検出の反証テストつき
- **context_profile v2**（裁定 §4/§5）: 16観測（collaboration_class / language_composition / dependency_manifests 等・定義版管理）。`resolved_human_actors` は bot・upstream 除外後の定義（push-copy fork 反証テストで上流混入排除を実証）
- **lifecycle-v2**（密度基準）: 一次出力 = `days_since_last_human_commit` + `active_days_180d`（クラスに常に併記）。帯 dormant≤2 / maintained 3-11 / active≥12。informed-by-pilot-1 を開示。180日沈黙+直近1日 fixture の反証テスト
- **共有ブロック**（`shared_block`）: report.md 冒頭に 3-5 行のコピペ要約（norms 1 行版つき）
- **`grift report`**: 既存 JSON から md を再レンダリング（再分析なし）
- **GitHub Action**（観測のみ）: `grift-cli` ピン install → STEP_SUMMARY に共有ブロック・artifact upload・PR コメントは明示 opt-in のみ。action-dogfood で自リポ動作保証
- **`grift contribute`**: 明示的 opt-in 提出 payload 組み立て（repo スコープ集計 + context クラス級 + 定義版のみ。canonical_id/メール/パス/repo 名/activity は構造的除外）。**CLI は何も送信しない（7禁止⑦）**。F-C1: 非 TTY + `--yes` なしは exit 2 で拒否・`--yes` でも開示文 + payload 全文表示（同意の痕跡）
- **corpus v2026.11**: admission 70 件（C33/D29/B8・narratable は機械実測で C=14/D=14 — 目標 30 に対する不足を逐語記録）。分布 test co-change n=68 / corrective n=101（deciles 収録・values 非同梱）。層別は active n=34 のみ発行・他は `context_stratum_too_small`
- `docs/coverage-map.md`（21問→観測の表）・`docs/persona-answers.md` 判別引用更新・`--reference-version`（旧 v2026.09 は不変で選択可能）

### Changed

- README 日英の判別節を v2026.11 逐語へ全面更新: **A vs D separated（δ=0.9198）を筆頭に、A vs C は fail_tier2 に転回**（基準 5f2665e 不変・転回をそのまま公開）。旧 separated 根拠の残存 0 を CI が機械強制
- CLI 既定の参照分布を v2026.11 に

## [0.5.1] — 2026-08-22

WP-P1e 二層契約 + Golden v2 第1波。Grift 本体統合（WP-G1）の unblock マイルストーン。

### Added

- export-v1（`--export <dir>`・opt-in）: commits.ndjson / actors.json / export-meta.json。生メール・生 author 文字列ゼロ出力。per-actor 品質指標は恒久禁止（`docs/export-schema.md`）
- `docs/report-schema.md`: report-v1 凍結（追加互換）・純stdlib検証器 `tep_core.schema.validate_report`
- golden G6〜G13 増設（計13本・上限内）: AI共著（claude-code）・引き継ぎ（axios）・dormant（co）・polyglot（pyscript）・テンプレ派生（scvi-tools）・solo（kilo）・founder（httpx）・日本語圏（voicevox）
- `golden/coverage.md` カバレッジ行列 + HOLE 機械検出（issue 紐付け強制）
- `docs/persona-answers.md`: 敵対レビュー21問の実数値実演集（転記数値は CI が golden 期待値と機械突合）
- パリティ検算レシピ（export-schema.md）+ 逐語実行テスト
- 終了コードと stdout 純度規約（README 日英）

### Fixed

- F-P10-3: identity loader が空・@含有・重複 canonical_id を受理し生メールが export に漏れる producer gap を修正。`CANONICAL_ID_PATTERN`（`^[a-z0-9][a-z0-9._-]{0,63}$`・版管理）で `IdentityValidationError`（CLI は exit 2・export 未書き出し）。schema 文書と実装は逐語一致テストで固定。性質テスト「exit 0 ⇒ export 内 `@` 0 バイト」

### Changed

- `schema_version` を `tep-report-v1` から `report-v1` へ改名（凍結前の最後の変更）

## [0.5.0] — 2026-08-22

定義Bの節目（`--scope`・参照分布 v2026.09・解釈層）。行レベル rework は v0.6 予約のまま。

### Added

- `--scope tenant|repo`。tenant は証拠、repo はプロセス観測と参照分布。混ぜると `ScopeMismatchError`
- 参照分布 v2026.09（repo スコープ）。n<30 の指標は位置を出さない
- survival（`--survival`、τ=180日）。参照分布は v2027 予定
- 公開コーパス pin（A/B/C/D、SHA 固定）。リーグテーブルは同梱しない

### Changed

- `corrective_rework_rate` を evidence_claim から観測専用へ降格（件名規約依存の交絡）
- git log の非 UTF-8 を `errors="replace"` で落とさない
- コマンド名を `grift` に確定（method=TEP / tool=grift）。旧 `tep` エントリは置かない
- PyPI 配布名を `grift-cli` に確定（公開操作は人間ゲート）
- H-5: 母数<20 では ratio と十分位を両方出さない（`insufficient_population`、件数の生表示のみ）

### Discriminant (verbatim from `corpus/DISCRIMINANT-v2026.09.md` Run 2)

- `test_cochange A vs D` → `inconclusive_small_n`
- `test_cochange A vs C` → `separated`
- `corrective_rework A vs C` → `fail_tier2`

## [0.1.1] — 2026-08-22

origin 語彙の P0 修正（検収合格 SHA `e954b16`）。ローカルタグ `v0.1.1` は未 push。v0.5.0 に一本化するかは代表判断。

## [0.1.0] — 2026-08-21

origin / activity の決定論的レポート。ゴールデン G1–G5。LLM なし。
