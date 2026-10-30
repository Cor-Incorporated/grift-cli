# grift レポートの読み方 — 指標ごとの平易な解説（v3・2026-08-31）

**対象**: grift 0.5.4 以降。report-v1 の既存定義は0.5.x互換、v0.6のexperience / roleは別のversion付き定義です。非エンジニアの方向け。v0.6 の subject コマンド（repo / actor / project / align）の数値も同じ原則です。
**原則の再掲**: すべての数値は**観測された事実の記録**であって、優劣の評価ではありません。単独の数値での合否判断・人と人の比較は TEP（Technical Evidence Pipeline）非準拠です（[docs/norms.md](norms.md)）。書かれていないこと（= not observed）は「無かったこと」を意味しません。
**v0.9.0 の文と問い**: `grift actor`・`grift project`・`grift align` の Markdown の先頭に出る「この記録から見える進め方」の文と「面談で確かめたいこと」の問いは、[決定表](trait-profile.md)で本書の数値から選んでいます。
**参考値の出典**: 特に断らない限り、公開リポジトリ 117 件のコーパス（v2026.11・repo スコープ）と v0.5.2 実地調査（requests / flask / GitHub CLI / chalk ほか）に基づきます。参考値は「だいたいの目安」であり、分布は成長とともに新版として出ます。

---

## 十分位（decile）の表記規約（本文書で唯一の定義）

**第N十分位 = 値が上位 (100−10N)% に入る「帯」**。形式的には、コーパスの値を小さい順に並べた境界 d₁…d₁₀ に対して **第N帯 = (d(N−1), dN]**（左開・右閉）。第5十分位 = 下から 50〜60% の帯（いわゆる中央の帯）、第10十分位 = 上位 10% の帯です。

- 実例: click の test co-change 0.3178 は境界 0.2894 < 0.3178 ≤ 0.4871 に落ちるため **第9十分位**（上位 20% の帯に相当）
- 本書の帯表記には必ず日本語訳を併記します（例: 「第7十分位（上位 30〜40% の帯）」）
- 「上位N割」という目安訳は補助として併用します

---

## サイトの訳語と CLI の語の対応表

公開サイト（griftai.org・cor-jp.com）は非エンジニア向けの訳語で観測を呼び、CLI の出力と本書は英語の語と JSON キーで呼びます。対応は 1 対 1 で、**この表だけ**に置きます（他の文書は表を複製せず、ここへリンクします）。JSON キーは report-v1（`grift analyze` / `grift report`）の経路で、`.value` は `kind: "observed"` のときだけ存在します。

| サイトの訳語 | CLI の語 | JSON キー（report-v1） | 本書の節 |
|---|---|---|---|
| 検査値 | observed | `kind: "observed"` を持つ観測ブロックの `value`（単位は `unit`） | [数値が出ない（not observed）とき](#数値が出ないnot-observedとき) |
| テスト併修率 | test co-change（テスト同期変更率） | `test_cochange.all_time.value` | [証拠系: test co-change](#証拠系-test-co-changeテスト同期変更率) |
| 手戻り率 | corrective rework | `rework.corrective_rework_rate.value` | [観測系: corrective rework と path retouch](#観測系-corrective-rework-と-path-retouch) |
| 磨き直し | path retouch | `rework.path_retouch_rate.value` | [観測系: corrective rework と path retouch](#観測系-corrective-rework-と-path-retouch) |
| コードの新しさ | survival | `survival.survival_index` | [survival（いまある行の新しさ）](#survivalいまある行の新しさ-任意指定) |

訳語は値の意味を変えません。「手戻り率」「磨き直し」は観測層（証拠主張ではない）、「コードの新しさ」は `--survival` 指定時のみ出ます。「コードの新しさ」は、いまのコードにある行が書かれてからどれだけ経っているかを、180 日を目安に重みを付けて平均した値で、1 に近いほど最近書かれた行が多いことを示します（リポジトリ全体の値で、一人ひとりの値ではありません）。各行の JSON キーと CLI の語が実在することは `tests/test_v060_docs_parity.py` が実レポートに対して検査します。

---

## Markdown の観点の呼び名

`grift actor`・`grift repo`・`grift project`・`grift align` の Markdown は、4 つの観点を griftai.org と同じ「平易な言い方（サイトの用語）」の形で呼びます（例: 見出し「変えた部分の区分（作業領域）」）。JSON のキーと、JSON に入る固定文（`limitations` など）は変えていません（その文には「作業領域の観測」「変更提出の時系列」のような元の言い方が残ります）。呼び名は**この表だけ**に置き、Markdown の見出し、「傾向」の節の名前、「観測された数値」の節の見出し、案件の要望の項目名（`DECLARED_TEXTS`・`DECLARED_ITEM_NAMES`）、文の中で観点の名前を引く決定表の文（`place_tests_only`・`work_not_observed`・`work_scope_differs`・`work_scope_later`・`record_scope_paths`）との一致は `tests/test_v090_site_names.py` が検査します。どれか 1 か所だけ呼び名が変わると、表の値とコードの値を並べて落ちます。観点の名前を引く文を決定表に足したときも、そのテストの一覧（`NAME_MENTIONS`）に足すまで落ちます。

| 平易な言い方 | サイトの用語 | JSON キー（report-v2） |
|---|---|---|
| 変えた部分の区分 | 作業領域 | `surface_profile` |
| 変更のペース | 変更リズム | `change_rhythm` |
| テストの付け方 | 検証の形 | `verification_profile` |
| 関わり方 | 関わり方 | `role_profile` |

griftai.org は「関わり方」を平易な言い方とサイトの用語の両方に使うので、この観点の見出しは「関わり方」だけです（cor-jp.com の事例ページは「役割の4次元」と書いています）。見出しには数字を入れません。

---

## 全観測インベントリ（何が出てくるか・1行1観測）

grift のレポートは3層の観測で構成されます。**層 = その数値の使い方の約束**です。

### 帰属層（origin 11分類）—「このコミットは誰の/何の仕事か」

| 分類 | 一言定義 |
|---|---|
| tenant_unique | identity に一致した作業者の独自コミット（merge 以外） |
| tenant_merge_or_sync | tenant の merge コミット（PR フロー。上流系譜が無い repo で付く） |
| upstream_sync | tenant の merge のうち上流取り込み（fork 系譜がある repo で付く） |
| inherited_upstream | fork 系譜にある他人（上流側）のコミット |
| tenant_derivative | 親リポ提供時のみ判定: 親リポ由来の改変作業 |
| external_upstream_contribution | 親リポ提供時のみ判定: 外部から上流へ還流した仕事 |
| template_inherited | テンプレート提供時のみ判定: テンプレート由来の部分 |
| generated_or_vendor | 生成・ベンダー成果物のみのコミット |
| bot | 自動化アカウントのコミット |
| ambiguous_origin | 作者情報が欠損して判定不能 |
| unresolved | identity に一致しない人間のコミット（名前は出ません） |

### 証拠層 —「検証を伴った変更の記録」

| 観測 | 一言定義 |
|---|---|
| test co-change | 本番変更と同一コミットでテストも変更した割合 |
| survival | いまある行が、HEAD から見てどれだけ最近書かれたか（`--survival` 指定時のみ） |

### 観測層 —「傾向の記録（証拠主張ではない）」

| 観測 | 一言定義 |
|---|---|
| corrective rework | 直近21日以内に触ったファイルを fix/revert でやり直した割合 |
| path retouch | 同じファイルを21日窓で再び触れた割合 |
| revert_rate | revert コミットの割合 |

### 文脈層（context profile）—「どんな repo か（分類であって序列ではない）」

| 観測 | 一言定義 |
|---|---|
| collaboration_class | solo / small_team / community の協働のかたち |
| lifecycle_stage（+ active_days_180d / days_since_last_human_commit） | 活動密度（クラスは一次観測2つの併記が本体） |
| resolved_human_actors / top_actor_share | 上流・bot 除外後の関与者数と最多作成者の比率（名前は出ない） |
| pr_flow_share | merge（PR）経由の割合 |
| scale / repo_age_days | 規模（コミット数・スパン・トップディレクトリ数・タグ数）と repo 年齢 |
| actor_turnover | 年別の初回活動人数（joined）・最終活動人数（last_active）。離脱人数ではない |
| release_cadence | ローカルの Git タグ数を人間活動スパンで年換算（tags/year） |
| conventional_commit_share / issue_link_density | 定型件名（`feat:` 等）の割合 / `#N` 参照を含む件名の割合 |
| language_composition / dependency_manifests / monorepo_markers | 言語構成・依存管理ファイル・monorepo 兆候 |
| test_file_ratio / docs_share | テスト/ドキュメントパスを触れたコミットの割合 |

### 同意済み本人のexperience / role —「どの文脈の観測か」

この層は、固定OID treeの`.tep/identity.toml`または明示`--identity FILE`で1 Actorを
選び、その行に`attribution_state=verified|claimed`と
`consent=recorded-explicit-consent`の両方がある場合だけ出ます。stateや`authority`だけ
では解放せず、CLIは記録の存在だけを検証します。`inferred`、`external`、
`unresolved`、`bot`、公開OSSの第三者Actor、identityなしrepo、マーカーのないidentityは
`not_observed(consenting_actor_required)`です。別repo観測時のCWD identityと
working-treeだけのidentity変更は同意根拠にしません。

| 観測 | 一言定義 |
|---|---|
| cross_author_modification_share | 作成者が既知のM/R対象commitのうち、別Actorが作成したfileを含む割合 |
| adopted_creations | 30日以上観測できる自作fileのうち、30日後以降に別human ActorがM/Rした数 |
| self_maintenance_returns | 自作fileへの前回接触から180日以上後に戻ったM/R event数 |
| dependency_update_share | manifest/lockfileを触ったactor非merge commitの割合 |
| post_release_fixes | tag targetを祖先に持ち、tag時刻から30日以内（境界を含む）の既存corrective classifierによるfix/revert commit |
| declared_ai_assist_share | version管理されたtrailer/AI identityで**申告された**AI支援commitの割合 |
| human co-authored share | human `Co-authored-by`を含むcommitの割合 |

AI coauthor identityのSSOTは固定OID treeの`.tep/ai-identities.toml`
（`ai-identity-v1`、exact `emails` / domain-separated `email_sha256`）です。
working-treeだけの変更、名前、handleでは推測しません。`AI-Assisted-By`、
`AI-Generated-By`、`Agent-Lane`は従来どおり申告として扱い、固定treeで未宣言の
`Co-authored-by`はhuman側へ残します。
いずれも`git interpret-trailers --parse`と同じ、本文から空行で分離された末尾trailer
blockだけを読み、本文中の例示行は申告に数えません。AI申告commitのtest co-changeは
既存test-cochangeと同じproduction path分類を使い、README/docs/LICENSE等を母数から
除外します。

全観測は `kind`、numerator、denominator、unit、window、definition version、limitations
を伴います。denominatorが20未満なら率とnumeratorを隠し、denominatorと
`insufficient_population`だけを示します。母数gate通過後にAI申告が0なら
`no_declared_ai_commits`であり、AI不使用・能力・優劣を意味しません。

特殊な記述観測でもnumeratorを省略しません。cadenceは隣接commit間隔の件数、
language/domain timelineはpath touchが1件以上あるtarget commit数、repo size pointは
first/median/lastで実際に参照した一意commit snapshot数です。各denominatorはtargetの
human non-merge commit数で、cadenceの`unit=days`はmedian/longest descriptorの単位です。
tag時刻だけではpost-releaseを判定せず、tag targetがfix commitのGit祖先であることを
固定OIDのparent DAGで検証します。tag target、parent pathが欠ける場合やcycleの場合は
数値を出さず`not_observed`にし、兄弟branchのfixは0件として扱います。annotated tagと
lightweight tagはrelease境界に使えますが、lightweight tagのtagger帰属は行いません。
shallow/promisor/missing-object履歴ではexperience/role全体を
`not_observed(history_incomplete)`にします。file lineageはcommit DAGのparent stateで
追跡し、mergeの既存pathはfirst parent、secondaryから一意に追加されたpathはそのcreatorを
継承し、衝突はunresolvedにします。annotated taggerはplaintext emailとidentity-v2の
`email_sha256`を同じ帰属規則で照合します。

`role_profile-v1`は単一職種やscoreではなく、top-levelを`domain`、`work_type`、
`time`、`process_position`の4次元だけに固定します。`time`の内側に`phase`
（early/middle/recent）と`calendar_year`を置き、暦年を第5の次元にはしません。
process positionはcreator/maintainer/integrator/releaseです。案件宣言と並べる場合も
fit/hire/rankへ変換せず、人間が確認する質問を作るために使います。

---

## まず全体の流れ（report.md の構成）

1. **Shared block**: 3-5 行の要約（コピペで共有できる形式・**gloss なし — 簡潔さ優先、意味は本文行末 gloss と本書が担う**）
2. **Provenance**: いつ・どのコミット・どの定義版で測ったか（再現に必要な情報）
3. **帰属（origin 11分類）**: この repo のコミットが誰の/何の仕事か（上のインベントリ参照）
4. **証拠系**: test co-change（検証を伴った変更の割合）
5. **観測系**: rework（手戻りの傾向）— 証拠主張ではない
6. **文脈**: context profile（どんな repo か）
7. **読み方の注意**（全レポート末尾に自動付与）

2種類のスコープがあります:
- **tenant スコープ**: identity.toml に載った特定の人の仕事（= 自己証明用）
- **repo スコープ**: bot 以外の全員のコミット（= repo 全体の姿・参考分布との比較はこちらのみ）

---

## 証拠系: test co-change（テスト同期変更率）

**単位**: ratio（0.0〜1.0）／**母数**: 本番コードを変えたコミット数

### 何を測っているか

「本番のコード（機能・ロジック）を変えたコミットのうち、**同じコミットでテストも変更した**割合」。テストを書く習慣が実際の変更に伴っているかを、申告ではなく git の記録から数えます。ドキュメントだけの変更は母数から除外されます。

### 読み方

- **高い（目安: 0.23 以上 = 第7十分位の上端を超える ≒ 上位 30% の帯に入る）**: 本番変更にテストが伴う習慣が定着している。変更の意図を後から検証できる状態が保たれやすい
- **中程度（0.11〜0.16 前後 = 第5十分位の帯＝中央の帯）**: 多くの公開リポジトリがここにいます
- **低い / 0**: テスト基盤が無い・あっても本番変更と同期していない。**ただし「テストを書いていない」=「悪い」ではありません** — ドキュメント中心のリポジトリ、設計のみの期間、ツール類など、テストが前提でない仕事は正当に低くなります
- **not observed**: テスト基盤そのものが検出できない（framework も tests ディレクトリも無い）場合。観測不能であって 0 ではありません
- **母数 20 未満**: Markdown は率を叙述せず件数だけを示しますが、report-v1 の JSON には `all_time.value` が `narrate_rate: false` を伴って残ります（report-v1 は凍結のため消しません）。report-v2 系（`grift repo` / `grift actor`）は `not_observed(insufficient_population)` で率そのものを出しません

### 分布の目安（v2026.11・n=68・repo スコープ）

| 帯 | 値の範囲（第N帯 = (d(N−1), dN]） | 目安訳 |
|---|---|---|
| 第5十分位（中央の帯） | 0.1089 を超え 0.1613 以下 | 下から 50〜60% |
| 第7十分位（上位 30〜40% の帯） | 0.1613 を超え 0.233 以下 | 上位 4割以内 |
| 第10十分位（最上位の帯） | 0.4871 を超え 0.6948 以下 | 上位 1割 |

実例: GitHub CLI 0.37（第8十分位相当）/ flask 0.20 / requests 0.12 / chalk 0.18（2026-08 実測）。検証文化で選んだ A クラス repo の中央値は 0.24。

---

## 観測系: corrective rework と path retouch

**単位**: ratio／**母数**: 本番変更コミット数／**注意**: **証拠主張ではありません**（観測専用）

### 何を測っているか

- **corrective rework**: 直近21日以内に触ったファイルを、`fix` / `revert` 等の件名で**すぐにやり直した**コミットの割合。「作った直後に手直しが必要になった頻度」の観測
- **path retouch**: 同じファイルを21日窓で再び触れた割合（手戻りというより「同じ場所を編集し続けている」傾向）

### 読み方（これは「数値が低い＝優秀」では読まない）

- commit メッセージの慣習（fix を書く文化か）で出方が変わるため、**人と人の比較・合否に使えません**（レポートにも明記されます）
- 高い値の読み方の例: 検証が無いまま進めて後から直している／活発に試しては直しているフェーズにある — の**いずれとも取れる**ので、面接などでの質問の種に使います（「この期間に何がありましたか?」）
- 低くても「バグが少ない」の証明にはなりません（バグ件数ではありません）

### 分布の目安（v2026.11・n=101・repo スコープ）

| 帯 | 値の範囲 | 目安訳 |
|---|---|---|
| 第5十分位（中央の帯） | 0.0683 を超え 0.0972 以下 | 下から 50〜60% |
| 第9-10十分位（上位 20% の帯） | 0.1904 を超え 0.4818 以下 | 上位 2割以内 |

A クラス（検証文化）の中央値は 0.05 と低めですが、因果の主張はできません。

---

## survival（いまある行の新しさ）— 任意指定

`--survival` を付けたときだけ計算します（τ=180日）。ソースのファイルから等間隔に最大 40 ファイルを抜き取り、HEAD にある行を `git blame` で調べます。行ごとに exp(-（HEAD の時刻 − その行を書いた時刻）÷ 180 日) を求め、その平均を出します。リポジトリ全体の値で、人ごとの値ではありません。
- 1 に近いほど、いまある行に最近書かれた行が多いことを示します。0 に近いほど、古くから残っている行が多いことを示します
- 180 日後に残っていた行の割合ではありません。消えた行は数えていません
- 実測例: 小規模運用中 repo で 0.94。いまある行の多くが、HEAD から見て最近書かれています
- 参照分布は **v2027 予定**（現時点で高低の判断基準は提供しません）

---

## 文脈: context profile（どんな repo か）

数値の意味は文脈で変わるため、repo の姿を並記します。**すべて分類であって序列ではありません。**

### collaboration_class（協働のかたち）

| クラス | 定義 | 読み方の例 |
|---|---|---|
| solo | 最多作成者の比率 90% 以上 | 個人プロジェクト。一貫性は保たれやすいが、バス係数（本人がいないと進まない度）は構造的に高い |
| small_team | 関与者 5 人以下 | 少人数で役割が重なる協働 |
| community | それ以上 | 多人数。審査プロセス（PR flow）や文書化が効いてきやすい |

実測例: requests 802人 / flask 870人 / GitHub CLI 722人は community。個人開発は solo。

### lifecycle_stage（活動密度）— 一次観測2つが本体

**クラスは便宜であり、必ず生の2数値と併せて読みます**:

- **active_days_180d**: 直近180日のうち、人がコミットした日が何日あったか（≥12 で active）
- **days_since_last_human_commit**: 最後のコミットから何日経ったか

| クラス | active_days_180d | 読み方の例 |
|---|---|---|
| active | 12日以上 | 現在も開発が続いている密度 |
| maintained | 3〜11日 | 維持運用は続いている（改修・追従） |
| dormant | 2日以下 | 180日窓ではほぼ静止している |

注意: **密度は「開発 vs 保守」の区別を測れません**（高密度の保守運用も active になります）。一斉ハウスキーピングで「新しそうに見える」のを防ぐため、新しさでなく密度を採っています。

**膨らませ方の開示（0.8〜）**: 活動日数は author 日付の一意な日数なので、毎日 1 件の小さな commit を置けば増え、同じ変更を 1 日にまとめると減ります。変更の量や中身は見ていません。この 1 文は report-v1 のトップレベル `limitations`、report-v2 `activity.limitations` と `change_rhythm.limitations`、`align` の `change_rhythm.active_days_180d` 軸の `limitations` と各 Markdown に固定で載ります。数値の補正・重み付けはしません（[norms](norms.md) §7）。

### その他の文脈観測（抜粋）

- **pr_flow_share**: merge コミット（PR マージ）の割合。高い = レビュー工程を経る文化
- **conventional_commit_share**: `feat:` `fix:` のような定型件名の割合。高い = 変更種別が機械可読な管理
- **language_composition**: 認識対象の言語拡張子を持つファイルへの接触が分母。同じパスでも別コミットで触れば再度数えます。`touch-share` の値は生カウントではなく 0〜1 の比率で、Markdown は百分率（上位3言語）です。認識されない拡張子は分母に含まず、1%未満の言語は省略するため表示合計が100%にならない場合があります。コード行数や現在のファイル構成の割合ではありません
- **actor_turnover**: `joined` は観測履歴で初めて活動した年、`last_active` は最後に活動した年に数えます。現在も活動している人も `last_active` に含まれるため、離脱や退職を示しません
- **release_cadence**: `タグ数 / active_span_days × 365.25` を小数第2位に丸めた年換算値（`tags/year`）です。`active_span_days` は最初から最後の人間コミットまでの日数差です。たとえば43タグ・70日なら224.37 tags/yearで、224回の公開リリースを観測した意味ではありません。ローカルに存在する全タグを数え、リリース用途の判定やタグ作成日時による絞り込みはしません。スパンが0日の場合は年換算できず、Markdownは `not observed (zero_activity_span)` と表示します。スパンが20日未満の場合も年換算せず（母数20未満の率は出さない）、Markdownはタグ数と日数だけを `3 tags over 1 days (not annualized: span < 20 days)` のように表示します。JSONの値は変わりません。浅い・部分cloneは `not_observed(history_incomplete)` です
- **dependency_manifests**: 依存管理ファイルの種類（複数 = polyglot / monorepo の兆候）
- **top_actor_share**: 最多作成者の比率（単独性の程度。名前は出ません）

これらのJSON契約は `context-v3-2026-08-25` です。以前の版では `language_composition` が `touch-share` 単位で生カウントを出し、`actor_turnover` に誤解を招く `left` キーを使っていました。現在の版では比率・`last_active`・`tags/year` を使います。

---

## 関連する指標・ツール（系譜と設計の違い）

| 名前 | 一言でいうと |
|---|---|
| **machuz/eis（Engineering Impact Signal）** | TEP の survival 観測は EIS 流の blame サンプリング（"EIS-style blame sampling"）を系譜として採り、設計上の差がある: EIS は 7 軸を固定比重で 0-100 の合成スコアに丸め、型ラベルとチーム横並び比較を出す。TEP は合成スコア・文脈による重み付け・等級語彙を設計で禁止し（6禁止・norms）、判別検証と `grift verify` で信頼を担保する。測定は既定offlineで、公開Forge取得だけが明示opt-inである |
| DORA | デリバリ性能の4指標（デプロイ頻度・リードタイム・MTTR・変更失敗率）とそのベンチマーク調査。TEP の norms 型の利用規範（ガイドラインで運用を律する）は DORA 方式を参考にしている |
| SPACE | 生産性を満足・パフォーマンス・活動・コミュニケーション・効率・時間フローで捉えるフレーム。「単一指標で生産性は測れない」TEP の立場と親和 |
| GitClear | コードの健全性（技術的負債・リワーク傾向）を商業データで追う調査・SaaS。重複する観測（rework 系）もあるが、TEP は個人の比較表を出さず、既定offline・明示opt-inの公開Forge取得を分離する点が異なる |
| MSR（Mining Software Repositories） | ソフトウェアリポジトリからの実証研究の学術分野。TEP の git 由来指標の多くはこの分野の蓄積の応用 |
| bus factor | 中心開発者の離脱でプロジェクトが止まる度合い。TEP の top_actor_share / collaboration_class はこの問いに観測で答える側面を持つ |

優劣の断言はここでは行いません。それぞれ目的が違う道具です。

---

## よくある誤読と、してはいけない読み方

| 誤読 | 正しくは |
|---|---|
| 「co-change が低い人はテストを書けない人」 | テストが前提でない仕事（docs・設計・ツール）は正当に低くなる。不在・低値を能力の否定として読むのは非準拠（norms 1条） |
| 「corrective rework が高い = バグが多い人」 | 件名慣習への依存が強く、バグ件数でも品質でもない（観測専用） |
| 「dormant = 捨てられた repo」 | 保守周期が長いだけの成熟 repo もある。復帰の履歴は gap として可視化されるが、gap を負に読むのは非準拠 |
| 「第9十分位の人は第5十分位の人より優秀」 | 十分位は同スコープ repo 間の位置（帯）のみ。単独足切り・比較表は非準拠（norms 2条） |
| 「decile が無い = 隠している」 | 母数 <20 か分布 n<30 では出力規則により非表示（insufficient_population / reference_too_small）です |

---

## 数値が出ない（not observed）とき

「0 だった」と「測れなかった」は別物です。主な理由コード:

| reason | 意味 |
|---|---|
| `no_test_framework_or_directory` | テスト基盤が検出できない |
| `insufficient_population` | 母数が 20 コミット未満（率を出さず件数のみ） |
| `pending_attribution` | identity（誰の仕事か）が未設定 |
| `scope_is_tenant` | 参照分布は repo スコープ専用のため tenant 実行では付かない |
| `survival_scan_disabled` | survival は `--survival` 指定時のみ |
| `no_actor_commits` | 指定 canonical_id の commit がこの履歴に無い（能力不足ではない） |
| `forge_export_not_provided` | ローカル forge export が無い。review は観測不能 |
| `tracker_export_not_provided` | ローカル tracker export が無い。活動が無かったことではない |
| `partial_source_coverage` | bound export の一部だけが提供された。含まれる件数は下限として観測するが、absence・cadence・割合は確定しない |
| `event_kind_not_collected` | tracker v2 契約がその event 種別を収集していない。0件とは扱わない |
| `requirement_not_provided` | 案件側が要求を書いていない（不足ではない） |

### v0.6 の数値 / 単位 / 入力 / 言えないこと

| 数値 | 単位 | 入力 | 言えないこと |
|---|---|---|---|
| surface_commit_counts | commits | git paths | 職種の確定 |
| active_days_180d | days | git author timestamp | 労働時間・勤怠・意欲 |
| median_gap_days | days | observation_date から 180 日以内の git author timestamp | 納期遵守・労働時間 |
| test_only_commit_count | commits | git + test paths | QA 適性 |
| merge_commit_share | ratio | git | PR review の質 |
| review_event_count | events | local forge export | 議論の良し悪し |
| event_observation.sample_size / active_utc_days | events / days | target-bound forge export-v2 | 未収集期間のabsence、速度、品質 |
| tracker_lifecycle issue transition | hours | target-bound tracker export-v2の検証済みtimestamp差 | 労働時間、工数、PM適性、納期遵守 |
| comparison=overlap 等 | enum | declared × observed | 採用の合否 |

v0.6 subject command はprovider名に依存せず、provider/host/stable project ID/path、
target OID、window、coverageで束縛したv2 exportだけを受理します。Actor別表示は
`actor_canonical_id`の完全一致だけで絞り、name/email/handleから人物を推測しません。
入力仕様と拒否条件は[ローカルexport契約](input-export-schema.md)を参照してください。

---

*本書は docs/report-schema.md（正本・機械検証付き）の平易版です。数値の厳密な定義・単位・符号化は正本を参照してください。参考値の更新は分布の新版（v2026.11 → vNext）とともに行われます。*
