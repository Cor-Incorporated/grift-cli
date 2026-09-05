# Coverage map — 問い → 観測（v0.6 実装状態）

出典: `docs/INSTRUCTION-p1f-v2-context-experience-20260822.md` §1（21問構成は addendum10 §3 で確定）。
以後の機能追加は**この表の更新から始める**（p1f-v2 §1）。ここでの「実装済」は
コード・closed schema・ローカル反証テストが存在することを示す。blind pilot は
ready 0 / blocked 14 のため、v0.6 の新観測の現実妥当性とrelease acceptanceは
**未証明**である。実装状態を PR-ready / released と読み替えない。

## v0.6 の検証経路（旧 Golden v2 指示からの差し替え）

`docs/INSTRUCTION-golden-v2-pilot-20260822.md` は、公開OSS goldenでも
experience / role_profileを非自明に励起するよう求めていた。これは現行SSOT
`docs/REQUIREMENTS-v060.md` のEXP-02、すなわち第三者public actor、identityなしrepo、
`inferred|external|unresolved`では両fieldを
`not_observed(consenting_actor_required)`にする契約により、v0.6では差し替えられる。

- 公開OSS goldenはreport-v1回帰とrepo-level detectorの固定に使う。actor単位の
  experience / role_profileを励起するためにidentityを推測せず、既存expectedを再生成しない
- actor単位の決定論・境界値・fail-closedはexact synthetic tests
  （`tests/test_v060_experience_role.py`、`tests/test_v060_experience_incomplete.py`、
  `tests/test_v060_experience_product_cli.py`）で固定する
- 実repoで持ち主の事前回答と一致するかはblind pilotで検証する。ready 0 / blocked 14の
  現状では現実妥当性を主張しない

したがって、`golden/coverage.md` のwave 2/3プレースホルダを「観測済み」に
読み替えない。synthetic greenもblind pilotの代替にはならない。

## 採用側・経営者の問い

| # | 問い | 答える観測 | 状態 |
|---|---|---|---|
| Q1 | 本当に作れる人か | test co-change・survival・活動日・コア期間（既存） | 実装済 |
| Q2 | どの領域・技術の経験か | language/domain timeline（期間つき）・4次元`role_profile`のdomain・test_frameworks・language_composition・dependency_manifests・monorepo_markers | 実装・exact synthetic済み / blind pilot未証明 |
| Q3 | チームで働ける人か | cross_author_modification_share・human_coauthored_share・pr_flow_share・collaboration_class | 実装・exact synthetic済み / blind pilot未証明 |
| Q4 | 保守する人か・作りっぱなしか | self_maintenance_returns・dependency_update_share・post_release_fixes・role_profile.work_type.corrective | 実装・exact synthetic済み / blind pilot未証明 |
| Q5 | AI 時代の働き方は透明か | declared_ai_assist_share × declared_ai_test_cochange・generated_or_vendor | 実装・exact synthetic済み / public G6でactor観測せず、blind pilot未証明 |
| Q6 | 続く人か | tenure・cadence（中央値/最長gap）・self_maintenance_returns・release_cadence・actor_turnover | 実装・exact synthetic済み / blind pilot未証明 |
| Q7 | 立ち上げ経験はあるか | founder_timing・initial_30d_scaffold_creation_share・annotated_tag_creation・pr_flow_share | 実装・exact synthetic済み / blind pilot未証明 |
| Q8 | どんな規模・状態の repo でやってきたか | context_profile v2・repository_size_at_contribution_points | 実装済 / repo-level golden acceptanceとblind pilotは未証明 |

## エンジニア側の問い（同じ観測の自己証明読み）

| # | 問い | 答える観測 | 状態 |
|---|---|---|---|
| E1 | 量産ではなく資産を作ったと示したい | survival・adopted_creations | 実装・exact synthetic済み / blind pilot未証明 |
| E2 | 幅と深さを示したい | language/domain timeline・role_profile・context×role×period×evidence portfolio | 実装・ローカル反証済み / blind pilot未証明 |
| E3 | 他人のコードを扱えると示したい | cross_author_modification_share | 実装・exact synthetic済み / blind pilot未証明 |
| E4 | AI を使いこなし且つ検証していると示したい | declared_ai_assist_share × declared_ai_test_cochange | 実装・exact synthetic済み / public G6でactor観測せず、blind pilot未証明 |
| E5 | 保守に戻る誠実さを示したい | self_maintenance_returns・post_release_fixes | 実装・exact synthetic済み / blind pilot未証明 |
| E6 | 立ち上げたと示したい | founder_timing・initial_30d_scaffold_creation_share・annotated_tag_creation | 実装・exact synthetic済み / blind pilot未証明 |

## git からは答えられない問い（境界・明記）

- コードレビューの質・コミュニケーション・要件定義力 — 前2者は Grift 側 API/人間評価の領域、要件定義は恒久に外
- repo の意義/人気/重要度の**等級** — 恒久に扱わない（context裁定 §2: 格付け×帰属=1 JOINで個人格付け。agent 代理変数は inflation 可能）
- private 経歴の不在・gap の中身 — TEP の外側（norms 1条で「不在を負に読まない」）
- 「申告なし = AI 不使用」の推定 — 恒久に禁止（非対称読み・p1f §3-2）
