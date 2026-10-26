# 特性プロフィール設計の材料（2026-10-26）

[設計書](../trait-profile-20261026.md) が行番号で参照する 0.8.0 の実出力と、見本の数字の出どころを置いています。名前・メール・日付はすべて合成です（メールは example.com）。

## 置いてあるもの

| 場所 | 中身 |
|---|---|
| `tools/make_synth.py` | 合成リポジトリ 4 本を作るスクリプト。日付と変更の並びは固定で、乱数は使いません |
| `tools/run_080.sh` | 4 本を作り直し、grift 0.8.0 の `actor` / `project` / `align` / `verify` を実行します |
| `inputs/` | 候補者 2 人の identity-v2（本人申告と同意の記録あり）と、案件 2 件の `tep-project-v1` |
| `outputs-080/` | 0.8.0 が出した Markdown 8 本。設計書 §1.3 の行番号はこのファイルの行です |
| `samples/` | 推奨案で出す予定の Markdown の見本 8 本。CLI はまだこの形を出しません |
| `inputs/brief-*.toml` | 段階 2 で提案するエンジニア側の宣言（`tep-actor-brief-v1`）の書き方の案。0.8.0 は読めません |

## 合成リポジトリ

| リポジトリ | 役 | commit | HEAD |
|---|---|---|---|
| ledger-api | 候補者 A（`candidate-a`）。サーバー側とテストの変更を、数日おきに出す | 108 | `b2c5f307116c97ed2f12b737a6ff3df942d703df` |
| shop-front | 候補者 B（`candidate-b`）。画面と文書の変更を、まとめて出して間が空く | 57 | `5ec556e67c818522a743d06a20b8ac5bb03d1079` |
| payments-api | 案件 P1「決済 API の保守と機能追加」の案件側リポジトリ（3 人） | 227 | `005ce05ea3cafff383fdd35745e9de0c8fc0d20f` |
| storefront | 案件 P2「EC サイトの画面刷新」の案件側リポジトリ（2 人） | 113 | `869513e7bc91eab9b2d96788e687655e5af95769` |

## 作り直し方

```bash
GRIFT=grift bash docs/design/trait-profile-20261026/tools/run_080.sh /tmp/trait-profile-work
```

2026-10-26 に grift 0.8.0（dev `main` `87076c8`、定義版 `tep-v0.8.0-2026-10-25`）で実行し、16 本すべて rc 0、`verify` は 2 本とも `VERIFIED` でした。作り直した Markdown を `outputs-080/` と比べると、align の 4 本の「actor report digest」「project report digest」の 2 行だけが変わります。保存した JSON に実行時刻（`provenance.analyzed_at`）が入るためです。ほかの行は同じです。

shop-front は最初、`package.json` を JSON として読めない中身で作っていたため、テストの仕組みが見つからず「検証の観測」が未観測になりました。実在のフロントエンドのリポジトリに近づけるため、`devDependencies` に `@playwright/test` と `vitest` を書いた形に直してから実行しています。
