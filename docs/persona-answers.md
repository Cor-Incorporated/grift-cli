# ペルソナ回答実演集 — golden 実数値による回答例（wave 1）

出典: BD `tep-adversarial-review-20260822.md`（9ペルソナ・◎7/△12/✗3）。master 指示 §3-2。
本ファイルは**公開リポに置く実演集**であり、各問いに「使う観測 → golden repo の実数値による回答例 → 宿題/限界」を1エントリずつ載せる。

規則（機械検証される）:

1. **手書き数値禁止** — 数値はすべて `転記:` 行で `golden/expected/<id>.json#<field.path> = <value>` の形で書き、`tests/test_persona_answers.py` が golden 期待値と突合する（golden 更新で数値が変われば CI が落ちる）
2. ✗3問（Q3-2 / E1 / E4）は「答えられない」を明記し、限界文を norms（P1g で正式化予定）に基づいて引く — 正直さも実演の一部
3. 各波の完了時点で「実数値つきで答えられない問い」が残っていたら観測の欠落として起票する（検出器: 本ファイルの `宿題:` 行 + issue リンク）
4. 問い数について: master 指示は「22問」と数えるが、敵対レビュー正本の実問いは **21問**（P1×4 + P2×3 + P3×3 + P4×2 + E1×1 + E2×1 + E3×3 + E4×1 + E5×3）。数え方の確認を提唱者に依頼中（確認まで本ファイルは正本の21問構成に従う）

wave 1 = 既存 report-v1 フィールドで答えられる問い。wave 2 = context_profile v2（Q8・E2）。wave 3 = experience（Q2〜Q7・E1〜E6 の残り）。

---

## 採用側ペルソナ

### P1: スタートアップCTO

#### Q1-1「90分の面接に対して、これは何を足してくれる？」 — wave 1 回答例

- 使う観測: test co-change・活動日・コア期間（既存フィールド）
- 転記: golden/expected/G1-click.json#test_cochange.all_time.value = 0.2664
- 転記: golden/expected/G1-click.json#test_cochange.all_time.cochanged = 73
- 転記: golden/expected/G1-click.json#test_cochange.all_time.population = 274
- 回答例: 面接は「語れるか」を測り、本ツールは「語りの裏に痕跡があるか」を出す。click の本人スコープでは本番変更 274 コミットのうち 73 コミットがテストを伴い（co-change 0.2664 ratio）、これは経歴書からは作れない解像度の面接質問（「2023年の corrective 集中期間に何が？」）を10分で作れる。摩擦は `pipx install grift-cli && grift analyze .` の1回。

#### Q1-2「game できるのでは（テストを形だけ触る）」 — wave 1 回答例

- 使う観測: test_frameworks（テスト基盤の実在）× test co-change
- 転記: golden/expected/G6-claude-code.json#test_frameworks.reason = no_test_framework_or_directory
- 転記: golden/expected/G13-voicevox.json#test_frameworks.names = ['vitest', 'playwright']
- 回答例: co-change を上げる最短経路はテストを書くこと（game すると本物になる指標選定）。また母集団には実在するテスト基盤が前提になる — テスト基盤の無い repo（G6 claude-code: not_observed）は率自体が出ない。対して G13 voicevox は vitest/playwright が観測される。形骸テストの観測は v0.6 行レベルの宿題。
- 宿題: 形骸テスト（assert なし diff）の検出 — v0.6

#### Q1-3「decile 8 と言われて、で？」 — wave 1 は限界文

- 使う観測: interpretation（参照分布位置）— **golden は tenant スコープで固定しているため励起されない**（`scope_is_tenant`）。repo スコープの十分位は corpus v2026.09 由来
- 転記: golden/expected/G1-click.json#interpretation.test_cochange.reason = scope_is_tenant
- 限界文: golden 実数値つきの十分位実演には repo スコープの golden 期待値ピンが必要（観測ではなく golden ピン構成の欠落）→ 起票した
- 起票: https://github.com/Cor-Incorporated/grift-cli-dev/issues/12

#### Q1-4「偽陰性のコストは誰が持つか」 — △（規範で対応）

- 使う観測: なし（方法論規範の領域）
- 限界文: TEP 単独での足切りは方法論非準拠（norms 2条予定）。not_observed ≠ 実績なし。誤用を技術で防げないことは認め、規範+読み方ガイド+教育の3層で緩和する
- 宿題: norms.md 公開（P1g・v0.5.2 同乗）

### P2: 受託開発の発注責任者

#### Q2-1「有利な repo だけ開示してきたら」 — △

- 使う観測: なし（選択性の明示は規範）
- 限界文: 選択的開示は禁止できない。選択性の明示の強制（portfolio の「提供者が選択」常時表示・開示率）で対応
- 宿題: PR-C portfolio（v0.6b）で開示率実装

#### Q2-2「identity.toml は盛れるのでは」 — wave 1 回答例

- 使う観測: lineage 除外・attribution_state 出力・再実行検証（provenance）
- 転記: golden/expected/G3-spoon-knife.json#lineage.is_fork = true
- 転記: golden/expected/G3-spoon-knife.json#lineage.parent = octocat/Hello-World
- 転記: golden/expected/G3-spoon-knife.json#origin.tenant_unique.value = 0
- 回答例: 盛りの2方向は両方検出可能: ①他人の仕事を自分に付ける → provenance の analyzed_commit_sha 时点で再実行し author を突合（verify で1コマンド化・P1g）。②上流を自分に付ける → lineage 宣言は fork として記録され（G3 参照）、inherited_upstream に分類される
- 宿題: `grift verify`（P1g）

#### Q2-3「decile に意味はないと言われたら」 — △

- 使う観測: 判別実績は corpus 由来（golden の外）
- 限界文: 判別の現況は v2026.11 で **A vs D separated（Cliff δ=0.9198・n 18/18）** が主軸（テーゼ「量は誰でも作れる」の最初の強い実証）だが、**A vs C は fail_tier2 に転回**（δ=0.291・C 群の多様化で分離低下 — `corpus/DISCRIMINANT-v2026.11.md` 逐語）。交渉材料の本体は「第三者が再実行できる一次記録」であることは不変
- 宿題: P1c corpus v2026.11

### P3: メガベンチャーEM

#### Q3-1「git 履歴で差別されたと言われたら法務は守れるか」 — △

- 限界文: 再現可能性・contestability（本人が同じ道具で反論できる）・単独判断禁止規範の3点は擁護可能。法域ごとの適法性審査は TEP の外。導入企業の法務確認が前提
- 宿題: norms 3条（規範の再掲）

#### Q3-2「gap 系指標は人生の断絶を系統的に不利にしないか」 — ✗（恒久限界）

- 限界文: **構造的に否定できない。** git 履歴は育児離職・傷病・非OSS文化圏の経歴を可視化する。緩和はあるが可視化そのものが選別に使われる危険は TEP の内側からは消せない。できる最大: gap を負に読む叙述の恒久禁止（規範1条予定・語彙ゲート）と限界節への明記。「解決済み」と言ったら嘘になる
- 宿題: norms 1条 + 語彙ゲート（P1g）

#### Q3-3「コーディングテストと何が違う」 — wave 1 回答例

- 使う観測: 行動履歴（本ツール全体）vs 統制環境の瞬間値
- 転記: golden/expected/G12-httpx.json#origin.unresolved.value = 1376
- 転記: golden/expected/G8-co.json#origin.unresolved.value = 299
- 回答例: 統制テストは「その場で解けるか」、本ツールは「実環境で何をしてきたか」。G8 co は 2016 年に休止した著名 repo（299 コミット）で、G12 httpx は 2019 年以降も成長する repo（1,376 コミット）— 瞬間値では見えない履歴の違いが出る。成果予測は主張しない（補完）

### P4: 人事・採用オペレーション

#### Q4-1「report.json の改ざん保証は」 — △→◎化の道

- 使う観測: provenance（analyzed_commit_sha・定義版・スコープ）
- 転記: golden/expected/G1-click.json#provenance.analyzed_commit_sha = 2c8cd3ac958a7eb316d67f2d316c27086c4c0369
- 回答例: provenance に再実行に必要な全情報が入っている（G1 の SHA はクリック時点で固定）。現状は手作業が欠陥
- 宿題: `grift verify <report.json>`（SHA checkout → 同条件再計算 → VERIFIED/MISMATCH/CANNOT_VERIFY・P1g）

#### Q4-2「候補者データの保持・削除は」 — △

- 限界文: CLI はローカル実行・無送信・データを持たない。企業が report を保存した瞬間に個データ管理の話になる → 保持・削除の推奨を norms に書く
- 宿題: norms（P1g）

## エンジニア側ペルソナ

### E1: 転職活動中のシニア（private 経歴） — ✗（恒久限界）

- 限界文: **否定できない。** 今日の TEP が証拠を出せるのは「見せられる git がある人」だけ。エンタープライズパス（会社許可の下・集計値のみ開示）は Phase 3 構想であり今日の答えにならない。唯一の誠実な対応: 「TEP レポートの不在・private 経歴を負に読むことは方法論非準拠」を規範の第1条に置く。証拠を出せない人の選別装置に転化した瞬間、この方法論は失敗である — と正本に書く
- 宿題: norms 1条（P1g）

### E2: 若手（solo 学習 repo 中心） — △

- 使う観測: （wave 2 の collaboration_class が本体。wave 1 は既存フィールドで「solo も記録は残る」ことを示す）
- 転記: golden/expected/G11-kilo.json#origin.unresolved.value = 20
- 限界文: solo の保護（solo は solo の分布とだけ比べる）は層別分布で実装予定。「期間は質を示さない」— 期間は必ず証拠と組で出す
- 宿題: context_profile v2（PR-A）と層別分布（v2026.11）

### E3: OSS メンテナ

#### Q3a「Goodhart の加害者になる自覚は」 — △

- 限界文: 自覚はある。game すると本物になる指標選定・社会的指標の不採用・ゲーミング分析の年次公開が設計上の対抗。生態系への影響がゼロではないことは認める
- 宿題: TEP Report での年次ゲーミング観測公開

#### Q3b「同意なしに public repo を analyze できる。opt-out は」 — wave 1 回答例

- 使う観測: repo スコープ = 公開情報（git log）の集計
- 転記: golden/expected/G2-gitignore.json#origin.unresolved.value = 4217
- 転記: golden/expected/G2-gitignore.json#attribution.bot.value = 0
- 回答例: repo スコープは git log という公開情報の集計で GitHub Insights と同じ範囲（G2 gitignore の全 4,217 コミットは誰でも `git log` で数えられる）。個人化（tenant スコープ）は identity.toml を要する。第三者が他人の identity.toml を書くことを技術的に防ぐ手段は無い — 防波堤は規範（同意なき第三者プロファイリング=非準拠）と個人ランキング機能の恒久不実装
- 宿題: norms 4条（P1g）

#### Q3c「全社員を毎週回す監視ツールになる」 — △

- 限界文: MIT で転用は止められない。止められるのは「それを TEP と呼ぶこと」— 個人比較表・全員スコアカードは非準拠（公開も内部も禁止）。実効性は年次レポートと共同体の目に依存（DORA 型）
- 宿題: norms 5条（P1g）

### E4: AI 駆動開発者 — ✗（現時点の限界 + データで動かす道）

- 限界文: **「申告ありを負に読む」採用者を止められない。保証は存在しない。** できるのは申告×検証の組を正の物語として確立することと、TEP Report 2026 で「透明な AI 利用者は検証も伴う」を実証すること。データが出るまで「先に正直者が損をする期間が存在しうる」を隠さない。なお申告なし≠AI不使用 — 低比率を負の証拠として叙述することを恒久禁止する
- 宿題: declared_ai_assist_share（PR-B・wave 3）+ 語彙ゲート

### E5: 懐古派（HN/Reddit）

#### Q5-a「n=47・判別1本で『基準』を名乗るのは誇大」 — ◎

- 限界文: 名乗っていない。許可主張は4つだけ（再現・帰属・透明性・独立性）で「基準」自称はその外。名乗る前提条件が敵対レビューの ✗ の解消（norms・guide・verify）

#### Q5-b「commit 指標は成果と相関しないと研究が示す」 — ◎

- 限界文: 成果予測を主張しない。「何が起きたか」の証拠であり「どうなるか」の予測ではない。判別検定も群分離のみ

#### Q5-c「名前が grift（詐取）って」 — ◎

- 限界文: 由来行で処理済み（Grift 製品ライン由来）。皮肉は買うが、中身の透明性で相殺する以外にない

---

## wave 1 完了時点の起票一覧（「測れるのに測っていない」検出器）

| 問い | 状態 | 起票 |
|---|---|---|
| Q1-3 | golden 実数値の十分位実演に repo スコープ期待値ピンが無い（観測は既存・ピン構成の欠落） | https://github.com/Cor-Incorporated/grift-cli-dev/issues/12 |
| Q3-2 / E1 / E4 | 恒久限界（✗）— 観測の欠落ではなく TEP の外側の世界。規範と限界文で対応 | なし（宿題は P1g） |

wave 2 / wave 3 の問い（context・experience 由来）は各波の完了時にこの表へ追記する。
