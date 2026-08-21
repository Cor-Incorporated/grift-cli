# Changelog

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)。バージョンは SemVer。

タグ・PyPI・リポ public 化は本ファイルの記載対象外（人間ゲート）。

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
