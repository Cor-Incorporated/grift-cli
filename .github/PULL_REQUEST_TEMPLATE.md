<!--
1 PR = 1 意図。ブランチ名と PR タイトルの type（feat / fix / docs / refactor / chore / ci / test / perf）を一致させてください。
作法と禁止事項は CONTRIBUTING.md §6 / §7。英語版は CONTRIBUTING.en.md。
One PR, one intent. Branch name and PR title share a type. Etiquette and prohibitions: CONTRIBUTING.en.md §6 / §7.
-->

## 目的 / Purpose

<!-- この PR が変える 1 つのこと。関連 Issue があれば `Closes #N`。The one thing this PR changes. `Closes #N` if there is an issue. -->

## 変更の種類 / Kind of change

- [ ] docs（文書のみ。`src/` に触れない / documentation only, no `src/`）
- [ ] fix
- [ ] feat（テストを含む / ships with tests）
- [ ] refactor / chore / ci / test / perf

## 変更内容 / What changed

<!-- 箇条書きで。ファイルと理由。Bullets: file and why. -->

## 実行したテスト / Tests you ran

```text
python -m pytest tests -m "not golden" -q
# → passed / failed の件数をここに貼る。Paste the passed / failed counts here.
```

## H5-E2E

<!--
実際に実行したコマンドと、その生出力の要約（20 文字以上）または安定したログ path。
実行環境を持たない変更（docs のみ）は `H5-E2E: none` の 1 行。
The command you actually ran and a summary of its raw output (20+ characters) or a stable log path.
For changes with no runtime (docs only), the single line `H5-E2E: none`.
-->

```text
H5-E2E: <command>
H5-E2E-OUT: <raw output summary or log path>
```

## ADR-0001 の確認 G / R / B（`src/`・schema・norms に触れた PR は必須）/ ADR-0001 check (required when `src/`, a schema or the norms change)

<!-- 定義は CONTRIBUTING.md §6。該当しない欄は「該当なし」と書く。Definitions in CONTRIBUTING.en.md §6. Write "not applicable" where nothing qualifies. -->

- **G（Green）** 受入条件を満たすテストが通った / the acceptance test passes:
- **R（Red）** 片側だけ変えると落ちることを実測した（何を壊して何が落ちたか）/ one-sided change fails (what you broke, what failed):
- **B（Binding）** 宣言と実体を 1 つのテストで結んだ / declaration and enforcement tied by one test:

## 証跡ゲート / Evidence gates（`src/` に触れた PR のみ / only when `src/` changed）

<!-- CONTRIBUTING.md §5 の 4 本。赤になったものと、意図した出力変更かどうか。The four gates in CONTRIBUTING.en.md §5: which went red, and whether the output change is intended. -->

- [ ] #1 `evidence/v060/scenarios` — 緑 / 再生成した / 赤のまま（理由: ）
- [ ] #2 `evidence/v060/scenarios-public` — 赤でも可。release で再束縛 / may stay red; re-bound at release
- [ ] #3 `evidence/v070/benchmark.json` — 緑 / 再生成した
- [ ] #4 `benchmarks/v060/golden` + `DEFINITION_VERSION` — 緑 / 上げた

## チェック / Checklist

- [ ] 合成スコア・順位・推奨・合否を出す出力やキーを足していない（`FORBIDDEN_VERDICT_KEYS`、`check_forbidden_vocab`）/ No score, rank, recommendation or pass/fail output or key
- [ ] 新しい network 経路は無い。あるなら opt-in フラグ付き / No new network path, or only behind an opt-in flag
- [ ] 生メールアドレス・個人を特定する値を出力・テスト fixture・文書に載せていない / No raw email or identifying value in output, fixtures or docs
- [ ] 文書を変えたなら日英両方（`README.md` ↔ `README.en.md`、`docs/*` ↔ `docs/en/*`）/ Docs changed in both languages
- [ ] 利用者に見える変更は `CHANGELOG.md` の `[Unreleased]` に 1 行 / One line under `[Unreleased]` for anything a user can see
