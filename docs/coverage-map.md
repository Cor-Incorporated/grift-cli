# Coverage map — 問い → 観測（v1・PR-A 導入）

出典: `docs/INSTRUCTION-p1f-v2-context-experience-20260822.md` §1（21問構成は addendum10 §3 で確定）。
以後の機能追加は**この表の更新から始める**（p1f-v2 §1）。観測名の `★` は未実装。

## 採用側・経営者の問い

| # | 問い | 答える観測 | 状態 |
|---|---|---|---|
| Q1 | 本当に作れる人か | test co-change・survival・活動日・コア期間（既存） | 実装済 |
| Q2 | どの領域・技術の経験か | 言語構成タイムライン（拡張子・manifest 由来、期間つき）★・domain path 構成★・test_frameworks（既存）・**language_composition・dependency_manifests・monorepo_markers（PR-A）** | 部分実装 |
| Q3 | チームで働ける人か | ★cross_author_modification_share・★co_authored_share・pr_flow_share（**PR-A**）・collaboration_class 横断ミックス（**PR-A**） | 部分実装 |
| Q4 | 保守する人か・作りっぱなしか | ★self_maintenance_returns・★dependency_update_share・★post_release_fixes・★fix/revert 作成比率（rework の corrective は repo 層で既存） | 未実装（PR-B/v0.6a） |
| Q5 | AI 時代の働き方は透明か | ★declared_ai_assist_share × その申告コミット群の test co-change・generated_or_vendor（既存） | 未実装（PR-B） |
| Q6 | 続く人か | tenure・★cadence 記述子・★最長ギャップと復帰（**release_cadence・actor_turnover は repo 層で PR-A**） | 部分実装 |
| Q7 | 立ち上げ経験はあるか | ★founder 時期性・★scaffold 作成・★release 作成（tagger）・merge 統合比率（pr_flow_share は **PR-A**） | 部分実装 |
| Q8 | どんな規模・状態の repo でやってきたか | **context_profile v2 全項目（PR-A）**・★貢献時点の repo 規模 | 部分実装 |

## エンジニア側の問い（同じ観測の自己証明読み）

| # | 問い | 答える観測 | 状態 |
|---|---|---|---|
| E1 | 量産ではなく資産を作ったと示したい | survival・★adopted_creations | 部分実装 |
| E2 | 幅と深さを示したい | 言語タイムライン（**language_composition PR-A**）・domain 構成★・文脈クラス×年数★（portfolio v0.6b） | 部分実装 |
| E3 | 他人のコードを扱えると示したい | ★cross_author_modification_share | 未実装（PR-B） |
| E4 | AI を使いこなし且つ検証していると示したい | ★declared_ai_assist_share × co-change | 未実装（PR-B） |
| E5 | 保守に戻る誠実さを示したい | ★self_maintenance_returns・★post_release_fixes | 未実装（PR-B） |
| E6 | 立ち上げたと示したい | ★founder 時期性・★scaffold・★release | 未実装（PR-B） |

## git からは答えられない問い（境界・明記）

- コードレビューの質・コミュニケーション・要件定義力 — 前2者は Grift 側 API/人間評価の領域、要件定義は恒久に外
- repo の意義/人気/重要度の**等級** — 恒久に扱わない（context裁定 §2: 格付け×帰属=1 JOINで個人格付け。agent 代理変数は inflation 可能）
- private 経歴の不在・gap の中身 — TEP の外側（norms 1条で「不在を負に読まない」）
- 「申告なし = AI 不使用」の推定 — 恒久に禁止（非対称読み・p1f §3-2）
