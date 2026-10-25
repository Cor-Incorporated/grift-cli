# ADR-0001: 0.8 系の受入条件 — 観測量で人を並べない・選ばない、宣言と観測の分離を両方向に保つ

- ステータス: 採択（2026-10-25、release/v0.8.0 統合方針と golden 承認移行のユーザー承認をもって。R1 / R2 / R4 は 0.8.0 で実装、R3 / R5 は在庫）
- 日付: 2026-10-25
- 関連: [ギャップ表](../GAP-site-vs-cli-v08-20261025.md)、[0.8.x 計画](../PLAN-v080-20261025.md)、[利用規範](../norms.md) §2・§5・§6・§7、[alignment-v1](../alignment-schema.md)
- 位置づけ: grift-cli 最初の ADR。旧 Grift（BenevolentDirector）の ADR-0057〜0076 は
  `grift-match/reference/grift-v2/docs/v2/` に凍結されており、本番号はそれらを継がない。
  形式は旧 ADR-0061（合成 quality_score の停止）に合わせた
- 先行する判断: 旧 ADR-0061「較正されていない合成を産出しない」、norms §2「単独足切り禁止」、
  norms「`--top N` の順序を品質 rank へ変換する利用は非準拠」

---

## 文脈

公開面（griftai.org・cor-jp.com）は「点数や順位はつけない」「量は誰でも作れる。だから
残るものを測る」と約束している。CLI は合成スコア・rank・fit・推奨のキーを schema と
`forbidden_key_hits` で禁じ、等級語彙を `check_forbidden_vocab` で止めている。

それでも 2026-10-25 の突合で、**人を観測量で並べる既定出力が 1 つ残っていた**。

| 場所 | 実体 | 読み手に見えるもの |
|---|---|---|
| `src/tep_core/actor_artifacts.py:261` `_actor_summaries` | `sorted(index.actors, key=lambda item: (-len(item.commit_shas), item.actor_id))` | `actor-index.json` / `actor-index.md` の行が commit 数の多い順に並ぶ |
| 同 `_selection(mode="top")` | 上の順の先頭 N 件 | `--top N` = 最も commit の多い N 名 |

`actor-index.md` の注記「Commit-count extraction only; this is not a quality ranking.」は
宣言であり、表の並び順という実体は commit 数で決まっていた。**宣言と実体の二重管理**の
片側だけが norms に追随していた形である。

同じ突合で、両側判断に関わる欠けも見つかった。`grift align` は案件側の宣言
（`tep-project-v1`）を actor 観測に当てる向きしか持たず、エンジニア側が案件に求めることを
宣言する入口が無い。

---

## 決定

0.8 系の全変更に、次の 5 つの受入条件を課す。

### R1. 既定の成果物は人を観測量で並べない

actor を列挙する成果物（`actor-index`、`actors/*` の列挙順、`--team` の requirement 列）の
既定の並び順は **canonical_id の辞書順**とし、commit 数・行数・日数などの観測量に依存させない。
観測量そのものは分母付きの事実として残す（消すのは順序であって値ではない）。

### R2. 観測量による選別は、量であることを名前と注記で明示する

`--top N` は 0.8.0 では残すが、help・Markdown・norms に「選別基準は観測 commit 数であり、
品質・順位ではない」を保つ。廃止または量を名に含む改名（例 `--most-commits N`）は破壊的
変更なので 0.9 でユーザーが判断する（計画 §2.3 #9）。新しい選別フラグを観測量で作らない。

### R3. 参照分布上の位置は明示要求時のみ出す

report-v1 の `interpretation.decile` は `--reference-version` を明示したときだけ出し、既定は
`not_observed(reference_not_requested)` とする（report-v1 の `reason` は開放集合で追加互換）。
実施は 0.8.1 で、golden expected と P0 baseline への影響を先に実測する（計画 §3）。

### R4. 各観測に「膨らませ方」を開示し、補正はしない

test co-change・active days・conventional commit share など、形式的な操作で上がる観測には、
その経路を `limitations` に固定文で併記する。数値を補正・重み付けしない（norms §7）。
開示は読み手が限界を知るためであり、ゲーミングを「検出」する機能ではない。

### R5. 両側判断は宣言と観測の分離を両方向に保つ

エンジニア側の宣言（`tep-actor-brief-v1`、計画 §2.3 #8）を受ける場合も、`declared` と
`observed` を混ぜず、`comparison` は alignment-v1 と同じ 5 値、`relationship` は同じ 4 値を
使う。両側の並びから総合点・順位・推奨を作らない（`FORBIDDEN_VERDICT_KEYS` を共有する）。

---

## なぜ並び順だけを先に直すのか

- 値を消すのは norms §1（不在を負に読まない）と衝突する。commit 数は分母付きの事実であり、
  受け手が母数を知るために要る
- 並び順は事実ではなく提示の選択である。「誰が多いか」を先頭に置くことは、受け手に順位として
  読ませる提示であり、サイトの約束と食い違う
- 並び順を id 順にしても、`--top N` の選択結果（どの N 名か）は変わらない。選別の是非は
  別の判断（R2）として切り分けられる

---

## 影響範囲

| レイヤ | 変更 |
|---|---|
| `tep_core.actor_artifacts` | `_actor_summaries` の並び順を canonical_id 順に。`_selection(mode="top")` は commit 数順に並べ直して N 件を選び、返す id 列は index の行順に揃える |
| `actor-index.md` | 注記に「rows are ordered by actor id, not by commit count」を加える |
| `verify` | 既存 collection（0.7.x 生成）は `actor_index_digest` が一致しなくなる。release PR で `DEFINITION_VERSION` を上げ、migration に実測を貼る |
| docs | README・norms・report-v2.md の `--top` / index の説明に並び順を明記。TEP の展開と訳語対応表（計画 #3） |
| schema | 変更なし（R1）。R3・R4 は `reason` / `limitations` への追加のみ。R5 は新 schema |

---

## 受入証跡（0.8.0 #1 の実装 PR に貼る）

| 基準 | 証跡タイプ | 項目 | 状態 |
|---|---|---|---|
| index の行順が canonical_id 順 | テスト出力 | commit 数の多い actor の id が辞書順で後ろになる fixture で、行順が id 順であること | 実装 PR |
| `--top N` の選択結果が 0.7.2 と同じ | テスト出力 | 既存 `test_v060_actor_artifacts.py` の top 選択テストが変更なしで通ること | 実装 PR |
| 片側変異で落ちる | 実行ログ | `_actor_summaries` のソートキーを `-len(commit_shas)` に戻すと新テストが落ちる | 実装 PR |
| verify が自分の出力を VERIFIED にする | テスト出力 | 実 git の合成 repo → `grift repo --actors --out DIR` → `grift verify DIR --repo REPO` が exit 0 | 実装 PR |
| 行順の改ざんを MISMATCH にする | テスト出力 | `actor-index.json` の行を入れ替えると verify が exit 1 | 実装 PR |
| 宣言と実体を結ぶ | テスト出力 | `actor-index.md` の注記文と並び順の両方を 1 つのテストで検査する | 実装 PR |

---

## 未対処として記録するもの

- `context_profile.top_actor_share`（最多著者の比率）は値であり並びではないので R1 の対象外。
  ただし「最多」という選別語を含む。名前の見直しは 0.8.x の在庫
- `tendency.strength: weak|moderate|strong` は序列語彙だが enum の破壊的変更になるため
  本 ADR では決めない（計画 §2.3 #6）
- `--team` の requirement 列は宣言順（project TOML の `required` 配列の順）であり観測量順では
  ない。R1 は満たしているが、明示的に id 順・宣言順と書いていない。docs 追記のみ
