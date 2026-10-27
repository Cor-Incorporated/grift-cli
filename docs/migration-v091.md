# v0.9.1 移行

既存の `analyze` / `report` / `verify` / `contribute` は report-v1 のまま動く。
v0.6.0〜v0.9.0 の面はすべて残る。本書は v0.9.0 移行の内容を引き継いだ上に v0.9.1 の
差分を加えたものである。英語版（0.9.1 の差分だけ）は [en/migration-v091.md](en/migration-v091.md) にある。


## v0.9.1 の差分

**面は増えない。0.9.0 の在庫（`docs/PLAN-v080-20261025.md` §6）にあった、人や案件について事実と違う数や読みが
出うるところを直す。** CLI フラグと enum 値は変わらない。schema key は project-v1 と collection の provenance に
任意の 1 つずつ増える。JSON の値が変わる場面は次のとおりで、どれも直したもの。

### `--as-of` のとき、experience・test_cochange・rework も観測日で切る（PR #106、**過去の report と collection に影響する**）

0.9.0 は `--as-of` を指定しても、experience・test_cochange・rework を全部の履歴で数え、test_cochange の 13 週の窓も
HEAD の日から数えていた。0.9.1 は、どれも観測日（UTC）の終わりまでの commit とタグで数え、13 週の窓は観測日から
数える。足した依存（`dependency_introduction`、`library_context`）も観測日までの commit の分だけを数える。
`--as-of` のときの activity の日は、範囲を切るのと同じ UTC の日で数える。

- 変わる key: `test_cochange.*`（`last_13w` を含む）、`rework.*`、`experience.*`（`window.end` は観測日の
  `T23:59:59Z`）、`library_context`、`activity.active_days`・`commits_per_active_day`・`active_days_13w`、
  `core_activity_period`、collection の card の `experience`
- `--as-of` を指定しないときは変わらない
- `--as-of` を付けずに作った report の activity は、今までどおり作者の現地の日付で日を数える（report-v1 の
  互換のため）。同じ report の `context_profile`（下）と `change_rhythm` は UTC の日付で数えるので、日の数え方が
  そろわない場合がある（0.9.2 の在庫）

### v2 レポートの `context_profile` を UTC の日付で数える（PR #104、**ふつうのリポジトリでも変わる**）

0.9.0 は、範囲を UTC の日付で切るのに、v2 レポート（repo・actor・project・align）の `context_profile` は作者の
現地の日付で日を数えていた。同じレポートの中で `context_profile.active_days_180d` と
`change_rhythm.active_days_180d` が食い違うことがあった（この repo の固定 revision `fa9bc31` では 7 と 6）。
0.9.1 は UTC の日付で数える。

- 作者の現地の日付と UTC の日付が違う commit（日本なら 0:00〜8:59、UTC より西なら夕方〜夜）が 1 件でもあると、
  `context_profile.scale.first_commit` / `last_commit` / `active_span_days`、`repo_age_days`、
  `days_since_last_human_commit`、`active_days_180d`、`lifecycle_stage`、`actor_turnover`、`release_cadence` が
  変わりうる
- report-v1（`grift analyze`）の `context_profile` は変えていない
- `--fork` で `--vendor-scan` を付けないとき、v2 の `context_profile` は v1 と同じ（ファイルを見ない）分類で作る

### forge / tracker の export の窓を UTC の日付で読む（PR #104）

export の窓の時刻を `[:10]` で読んでいたので、UTC 以外の offset で書いた窓の日付が UTC の日付とずれていた。
UTC の日付で読む。UTC より西で書いた窓に `--event-window` を合わせられるようになる。逆に、UTC より東の offset で
書かれ、`[:10]` がたまたま Git の窓と合っていた export は `windows_not_equivalent` になる。

### 件名に区切りに似た文字を含む commit を読み落とさない（PR #104）

`git log` の読み取りで、件名に 0x1f や U+2028 などを含む commit を落としたり、欄がずれたりしていた。欄を NUL で
区切って位置で読む。ふつうの履歴では結果は変わらない（5 つの repo の 26,032 commit で同じことを確かめた）。
git の設定 `log.showSignature=true` の人の環境で、署名された commit の署名の確認の行がファイルの一覧に
混ざっていたのも直した（grift が呼ぶ git には `log.showSignature=false` を付ける）。

### 浅い clone の扱いを JSON に正しく書く（PR #103、**過去の浅い clone の report に影響する**）

- `grift project REPO` の JSON（project-v1）に `provenance.revision_completeness`（`{shallow, promisor, complete}`、
  report-v2 と同じ形）を書く（任意。リポジトリを渡したときだけ）。浅い clone でないと分かれば、project の
  Markdown の範囲を「全履歴」と書く。0.9.0 までの project-v1 は key が無いまま読め、`grift verify` も通る
- 浅い clone の report-v2 の `limitations` の 1 文を、`not_observed` にした値と、取得できた commit だけで数えた
  節を名前で並べる文にする（0.9.0 は「actor の合計は not_observed」と書きながら、surface・change_rhythm を
  observed で出していた）。完全な clone のレポートは変わらない
- 照らし合わせの JSON の `project_provenance` も、0.9.1 の project report から作れば
  `revision_completeness` を持つ

### identity の id と、名前で作る cluster id の取り違えを止める（PR #105、**identity の書き直しが要る場合がある**）

- identity の `canonical_id` に、grift が付ける hash id の形（`^actor_[a-f0-9]{12,32}$`）を書けなくした
  （exit 2。どの行の何が理由かをメッセージに出す）。この形の id を使っている identity は、読める id
  （`alice` など）に書き直す。リポジトリに commit した `.tep/identity.toml` を固定 revision（`--rev`）で読むとき
  など、ファイルを直せない場合は、直した identity を `--identity FILE` で渡す
- 作者名がこの形の人は、名前の slug ではなく自分の hash id で数える（0.9.0 までは別の人の hash id と重なると
  exit 2 で止まった）。そういう作者がいる repo の collection の actor id・`partition_digest`・card の名前が変わる
- identity を使って書いた collection の `repo-report.json` に `provenance.identity_digest` を足した。
  `grift verify` に別の identity を渡すと、分け方が同じでも `identity` の違いとして MISMATCH を名指しする。
  0.9.0 までの collection には無いので、作ったときと同じ identity を渡す（違うと note で知らせる）
- identity を読めない collection の verify は、MISMATCH ではなく CANNOT_VERIFY（exit 2）になる

### 照らし合わせの検算を、保存した JSON から写さずに作り直す（PR #102）

`grift verify <alignment.json> --repo REPO --identity IDENTITY --project PROJECT` は、subject・provenance・
limitations を `grift align --repo` と同じ作り方で作り直して比べる（0.9.0 は `project_id`・`mode`・provenance の
多くを保存した JSON から写していた）。`--survival` や `--vendor-scan` で作った照らし合わせが必ず MISMATCH に
なっていたのも直った。照らし合わせの JSON は変わらない。

保存した report から作った照らし合わせ（`--actor-report` / `--project-report`）では、同意の記録を actor report
から作り直すので、actor report も `grift verify actor-report.json --repo REPO --identity IDENTITY` で確かめる。
`grift report <alignment.json>` での描き直しは同意の記録を確かめない（照らし合わせの Markdown の「数字の
読み方と限界」に書いた）。

### Markdown の直し（PR #100・#101）

- `--as-of` を指定した actor の Markdown に、観測日までに付けたリリースの印（注釈付きタグ）の回数と、
  それについての面談の問いが出る（role_profile の窓が観測日の終わりで切られているとき）
- 「傾向」の行で、変更のペースの名前が 2 回続いていたのを直した（「変更のペース（変更リズム）: 変更の間隔が
  観測される」）

### 0.9.1 に入れなかったもの（0.9.2 の在庫）

- `--as-of` なしで、HEAD より後の作者日付を持つ祖先（rebase・cherry-pick のあと）がレポートから外れる（M3）。
  直し方を試したが、未来の日付の commit が 1 件あるとレポート全体がその日付までずれた（bot の commit でも
  起きる）ので外した。観測日は 0.9.0 と同じく HEAD の作者日付の UTC の日付

### 収集をやり直す必要があるか

| 成果物 | 0.9.0 で作ったものの 0.9.1 verify | 作り直し |
|---|---|---|
| report-v1（`analyze` / `report`） | CANNOT_VERIFY（定義版数） | 要（verify を使うなら） |
| actor / repo report-v2（collection 外） | CANNOT_VERIFY（定義版数） | 要 |
| project report（project-v1） | リポジトリを観測したもの（`grift project REPO`）は MISMATCH（`definition_version` の欄）。要求だけを書いたもの（`grift project --requirements` だけ）は VERIFIED | 前者は要 |
| 照らし合わせ（alignment-v1、`align --team`） | CANNOT_VERIFY（定義版数） | 要 |
| actor collection（`repo --actors`、`actor --all/--top`、`actor ID --out DIR`） | 定義版数は見ない。`--as-of` を付けて作ったものは MISMATCH（`experience recomputation`）。作者名が hash id の形の人がいる repo のものも MISMATCH。それ以外は VERIFIED | MISMATCH になるものは要 |
| attest / portfolio | 入力 report の digest が変われば再署名 | 入力に依存 |

identity を使って書いた 0.9.0 の collection を verify すると、MISMATCH のときに「collection に identity_digest が
無い。identity が原因かもしれない」という note が出る。`--as-of` 付きの collection の MISMATCH の原因は上の
experience の切り方で、identity ではない（note は「かもしれない」の言い方で出る）。

0.9.0 のとき浅い clone で作った repo / actor report は、`limitations` の文が変わったので、定義版数をそろえても
一致しない。

```
# 合成 repo（作者 Alice の 30 commit、2026-07-01〜28、注釈付きタグ 1 つ）、identity は alice（claimed、同意あり）
# 0.9.0 = release/v0.9.1 の起点（36e0877）の src、0.9.1 = 本 release の src（a63bf03）。2026-10-27T16:27Z 実測
$ grift verify --report report-v1.json --repo repo    # grift analyze の出力
CANNOT_VERIFY:
  - definition version 'tep-v0.9.0-2026-10-26' is not the current 'tep-v0.9.1-2026-10-28' — historical versions cannot be reproduced yet (compatibility table: docs/report-schema.md)
# rc=2。repo report-v2（grift repo）、actor report-v2（--as-of 付きとなし）も同じ理由で CANNOT_VERIFY rc=2

$ grift verify project-out/project.json --repo team --project requirements.toml    # grift project --as-of 2026-08-31
MISMATCH: 1 field(s) differ
  - definition_version: report='tep-v0.9.0-2026-10-26' recomputed='tep-v0.9.1-2026-10-28'
# rc=1

$ grift verify alignment.json --actor-report actor-asof.json --project-report project-out/project.json
CANNOT_VERIFY:
  - definition version is not current
# rc=2

$ grift verify coll-asof --repo repo --identity identity.toml    # grift actor alice --as-of 2026-08-31 --out coll-asof
MISMATCH: experience recomputation:alice
  note: the collection records no identity_digest (written without an identity, or by grift 0.9.0 or earlier) but this verify uses identity_digest 26a8…242e; the identity may be the cause, since it changes the actor partition
# rc=1

$ grift verify coll-now --repo repo --identity identity.toml    # --as-of なしで書いた collection
VERIFIED: actor collection 6 member(s), full=1, selected=1
# rc=0

$ grift verify p-decl/project.json --project requirements.toml    # 0.9.0 の grift project --requirements（リポジトリなし）
VERIFIED: all fields match recomputation under recorded provenance
# rc=0
```

同じ 8 つを 0.9.1 で作り直すと、0.9.1 の verify ですべて VERIFIED（rc=0）になる。

## 定義版数

`DEFINITION_VERSION` を `tep-v0.9.0-2026-10-26` → `tep-v0.9.1-2026-10-28` に上げた（REL-091）。上の JSON の値の
変化（`--as-of` の切り方、`context_profile` の日付、export の窓、浅い clone の `limitations`、hash id の形の作者名）に
合わせたもの。版数だけを上げて定義版数を据え置くこともできない（golden の runner が `provenance.tool_version` の差を
D3 として FAIL にし、承認には D4（定義版数の差）が要る。版数だけを上げた tree で `scripts/v060_golden.py` が rc=1 FAIL、
D3 ×1 を実測）。

## CI

`v060-provider-live.yml` の仮の FAIL 要約を checkout の後に書くようにした（#99。成功した run の成果物は変わらない）。
src が変わったので、証跡 4 件を 0.9.1 の source で作り直した。

- `evidence/v060/scenarios` は release 束の source（a63bf03）で再生成した（`--replace`、6 / 6 PASS、
  source_drift 0、2026-10-27T16:23Z、`--verify-registry` PASS）。source は 0.9.0 と同じ。全 6 シナリオで
  `partition_digest` は 0.9.0 の登録値と一致し、変わったのは版数の文字列とそれに伴う digest、runner binding の
  commit と file_count だけである
- `evidence/v060/scenarios-public` は PR tier を実走して再生成した（verdict PASS、3 / 3、2026-10-27T16:23Z〜16:25Z、
  `--verify-registry --digest-only` PASS）。token は `V060_GITHUB_TOKEN` にプロセス環境でだけ渡し、成果物に
  含まれないことを grep で確認した
- `evidence/v070/benchmark.json` は `scripts/v070_benchmark.py --write` で再束縛した（self-contained 6 / 6 hold、
  2026-10-27T16:25Z）。`determinism.report_sha256` は `5a63b782…` → `4774f965…`。#104 で
  `context_profile.active_days_180d` が 7 → 6 になったこと（JST の朝の commit 8 件が UTC では前の日）と、版数の
  文字列による
- `benchmarks/v060/golden` の承認移行は人間ゲート。dry-run（`scripts/v060_golden.py`、2026-10-27T16:26Z）の drift は
  **D3 ×1 / D4 ×2、D0-D2 = 0**。D3 = `repo-report.json` の `provenance.tool_version`、D4 =
  `provenance.definition_version` と `metrics.human_nonmerge_commit_share.definition_version`。観測値の drift は 0。
  承認は `scripts/v060_golden_baseline.py --case actor-partition --approve --requirement REL-091 --migration-id
  gold-actor-partition-0007 --approved-by human:<承認者> --approved-at <RFC3339>` を人間が実行する。それまで
  `tests/test_v060_golden_runner.py::test_runner_executes_repo_and_verify_cli` は red

## v0.9.0 の差分

**面は増えない。Markdown の先頭に文と問いが出て、JSON は 4 つの場面で値が変わり、照らし合わせの
JSON に同意の記録の key が 1 つ増える。** CLI フラグと enum 値は変わらない。JSON の値が変わる場面は、どれも人や案件について事実と違う数や
読みが出うるところを直したものである。

### Markdown の先頭に、記録から見える進め方の文と面談の問いが出る（PR #86）

actor・project・alignment の Markdown の先頭に、JSON の数字から決定表
（`docs/trait-profile.md`、英語は `docs/en/trait-profile.md`）で選んだ平易な文と、面談で確かめたい
ことの問いが出る。0.8.0 の詳しい数字の節はその後ろに残る。

- 本人向けの文は、本人が名乗った ID（`attribution_state=claimed`）と同意の記録
  （`consent=recorded-explicit-consent`）があるときだけ出す。管理者が登録した ID（verified）、
  公開リポジトリから推定したまとまり、同意の記録が無い ID、浅い clone の記録には、出していない
  理由を 1 文で書く
- collection（`--all` / `--top`）には文を出さない
- 数が確かめられないときは文にしない（`role_profile` の母数がほかの観点と違うとき、浅い clone の
  とき、`--as-of` を指定していてタグを付けた日が分からないときなど）。外した理由は書く
- 文・文の id・型のキーは JSON に入らない。JSON はこの変更では変わらない

### 「傾向の強さ」と `relationship` を Markdown から外す（PR #88）

見出し「傾向の強さと確からしさ」は「傾向の確からしさ」になり、傾向の行の「傾向の強さ」と、
alignment の `relationship` の行が消える。2 つのレポートを並べると、強い人・弱い人、合う人・
合わない人に読めるため。JSON は変わらない。alignment-v1 の
`axes[].actor_tendency.strength` / `axes[].project_tendency.strength` は**非推奨**で、次の schema 版で
消す。

### 4 つの観点の呼び名を griftai.org にそろえる（PR #95）

Markdown は 4 つの観点を、griftai.org と同じ「平易な言い方（サイトの用語）」で呼ぶ。変えた部分の区分
（作業領域）、変更のペース（変更リズム）、テストの付け方（検証の形）、関わり方（griftai.org は平易な
言い方とサイトの用語に同じ語を使うので、見出しは「関わり方」だけ）。先頭の節の見出しと文、根拠の表の
観点、詳しい数字の節の見出し、傾向の名前、案件の要望の項目名が変わる（`grift repo` の Markdown
も含む）。JSON のキーと、JSON に入る固定文（`limitations` など）は変わらない（その文には元の
言い方が残る）。呼び名は `docs/metrics-guide.md` の
「Markdown の観点の呼び名」の表にある。

survival のサイトの訳語は「定着率」から「コードの新しさ」（Code recency）に改めた。値は残った行の
割合ではなく、いまのコードにある行が書かれてからどれだけ経っているかを 180 日を目安に重みを付けて
平均した値で、1 に近いほど最近書かれた行が多い。値の計算は変わらない。

### 照らし合わせの面談の問いは、本人が名乗った ID と同意の記録があるときだけ出す（PR #96）

alignment-v1 の subject に、任意の `actor_consent`（値は `recorded-explicit-consent` だけ）が増える。
`grift align` は actor report の同意の記録を、actor の本人向けの文と同じ関数
（`actor_basis.consent_recorded`）で確かめて写す。公開リポジトリから推定したまとまりには付けない。

照らし合わせの「面談で確かめたい点」は、本人が名乗った ID（claimed）かつ `actor_consent` があるとき
だけ問いを出す。管理者が登録した ID（verified）、同意の記録が無い ID、公開リポジトリから推定した
まとまりには、出していない理由を 1 文で書く。`grift verify` は保存した `actor_consent` を信じず、
actor report から作り直して比べるので、値を足したり消したりした alignment は MISMATCH になる。

### 照らし合わせの食い違いを直す（PR #85、**過去の alignment に影響する**）

0.8.0 の実際の出力を読んでいて見つけた食い違い（設計書 §1.4）を直した。変わるのは照らし合わせ
（`align`、`align --team`）の JSON と、actor・project・alignment の Markdown。actor report と
project report の JSON は、この変更では変わらない。

- **向き（`relationship`）の決め方**（値の意味が変わる破壊的変更）。0.8.0 は「1 人の件数」と
  「チーム全体の件数」をそのまま比べていたので、人の多いリポジトリほど 1 人の側が小さく出た。
  0.9.0 は、それぞれの中の割合（その人の commit のうちその場所に触れたものの割合と、リポジトリ
  全体での同じ割合）どうしで比べ、`"compared": "commit_share"` と比べた割合（`actor_share` /
  `project_share`）を残す。割合の母数が 20 に届かない側があれば比べない（`not_comparable`）。
  変更の間隔（`change_rhythm.*`）は、1 人とリポジトリで数える相手が違うので、常に比べない
- **場所と確かめ方の軸の窓**。どちらも観測日までの履歴を数えているのに 180 日の窓が付いていた。
  窓を `{"end": 観測日, "basis": "history_to_observation_date"}` にし、Markdown では「〜までの履歴」と
  書く
- **変更の間隔の傾向**。値にかかわらず「定期的な変更提出」と呼んでいた。`value` を
  `rhythm_observed` にし、形は数字（`basis`）で読む
- **場所の傾向の選び方**。一覧と同じ commit の割合（`surface_commit_share`）で選ぶ。割合が分から
  ないときと、いちばん大きい割合が 2 つ以上あるとき（本体とテストを同じ commit で変えると両方に
  入る）は `not_proven` にする
- **確かめ方の宣言の単位**を `verification-type` にした（`align --team` の
  `requirements[].declared.unit` も同じ）
- Markdown に案件の題名を出し、種類を表すだけの単位名を値に付けない。日本語の Markdown の
  選択性の注記を日本語にした（JSON の `notices` は英語の固定文のまま）
- `docs/metrics-guide.md` の survival の説明を、実装どおり「いまある行が HEAD から見てどれだけ
  最近書かれたか」の平均（τ=180 日、最大 40 ファイル）に直した。0.8.0 の説明（「180 日後も残って
  いる行の割合」）は逆の読みだった。docs だけの変更で、出力は変わらない

### 詳しい数字の節の窓を「全履歴」と書かない（PR #89）

場所と確かめ方の窓は「{観測日} までの履歴」と書く。浅い clone なら取得できた範囲だけを数えて
いて、project report にはそれが記録されないため。JSON は変わらない。

### `--as-of` なしの観測日を UTC の日付で取る（PR #90、**過去の report に影響する**）

`--as-of` を指定しないとき、0.8.0 は観測日を HEAD の作者の現地の日付で取り、数える範囲は各
commit の UTC の日付で切っていた。UTC より西（アメリカなど）の夕方に作った HEAD は、現地では
同じ日でも UTC では翌日なので、HEAD 自身が自分のレポートから外れていた。0.9.0 は観測日も UTC の
日付で取る。

変わるのは、HEAD の現地の日付と UTC の日付が違うときだけである。そのとき actor・repo report と
project report の `observation_date`・`git_window`・`change_rhythm` が変わる。西の夕方は 1 日あとに
なり、HEAD の UTC の日の commit がすべて数えに入る。東の朝（日本の 0 時〜9 時など）は 1 日まえに
なる。

### `--as-of` のとき、activity と role_profile も観測日で切る（PR #91、**過去の report と collection に影響する**）

`--as-of` を指定すると、場所・確かめ方・間隔の節はその日で切っていたが、`activity`（活動日数など）と
`role_profile`（関わり方）は観測日のあとの commit・merge・タグまで数えていて、同じ
レポートの中で数が食い違っていた。0.9.0 は、activity を観測日（UTC）までの自分の commit で、
role_profile を観測日の終わり（23:59:59 UTC）までの commit とタグで数え、role_profile の窓の終わりを
観測日にする。activity には `core_activity_period` も入り、`--identity` を付けた repo report の
activity も変わる。`--as-of` で書き出した collection の検算（`grift verify DIR`）も、同じ日付で
数え直す。

`--as-of` を指定しないときは今までどおり。`experience`（依存の経験）は、依存ファイルの読み取りに
日付が無いので、まだ観測日で切っていない。

### 名前で作る cluster id に、宣言した identity の id を使わせない（PR #92、**過去の report と collection に影響する**）

identity に書いた人（例: `alice`、`alice@example.com`）に commit が 1 件も無いと、別のメールで同じ
作者名「Alice」の人の commit のまとまりが、名前から作る id として `alice` を名乗れた。同意の記録が
ある `alice` の role_profile は id で commit を数えるので、別人の commit を alice の数として数えて
いた。0.9.0 は、宣言した identity の id を commit の有無にかかわらず予約する。そのとき別人の
まとまりは、名前ではなく hash の id（`actor_<hash>`）になる。JSON は、その人の role_profile と
experience の数、repo report-v2 の `actor_directory` の id、`partition_digest`、collection の card の
id とファイル名が変わる。

```
# 合成 repo: 作者「Alice」<alice.other@example.org> の 25 commit。identity は alice@example.com の alice だけを宣言
# 0.8.0 で書いた collection の index: [{"actor_id":"alice","commit_count":25}]
# 0.9.0 で書いた collection の index: [{"actor_id":"actor_764e6d7e62373f8135d186bf29dd3b91","commit_count":25}]
$ grift verify coll-080 --repo repo --identity identity.toml
MISMATCH: partition digest, actor membership/counts, card actor membership:alice.json
# rc=1（2026-10-26 実測）。0.9.0 で書き直した collection は VERIFIED
```

### 収集をやり直す必要があるか

| 成果物 | 0.8.0 で作ったものの 0.9.0 verify | 作り直し |
|---|---|---|
| report-v1（`analyze` / `report`） | CANNOT_VERIFY（定義版数） | 要（verify を使うなら） |
| actor / repo report-v2（collection 外） | CANNOT_VERIFY（定義版数） | 要 |
| project report（project-v1） | MISMATCH（`definition_version` の欄） | 要 |
| 照らし合わせ（alignment-v1、`align --team`） | CANNOT_VERIFY（定義版数）。`relationship` の意味も変わる | 要 |
| actor collection（`repo --actors`、`actor --all/--top`、`actor ID --out DIR`） | 定義版数は見ない。`--as-of` を付けて作ったものと、identity に書いた人に commit が無く同じ作者名の別人がいるものは MISMATCH。それ以外は VERIFIED | MISMATCH になるものは要 |
| attest / portfolio | 入力 report の digest が変われば再署名 | 入力に依存 |

## 定義版数

`DEFINITION_VERSION` を `tep-v0.8.0-2026-10-25` → `tep-v0.9.0-2026-10-26` に上げた（REL-090）。
上の JSON の値の変化（照らし合わせ、観測日、`--as-of` の切り方、cluster id）と Markdown の変化に
合わせたもの。

```
# 合成 repo（作者 Alice の 30 commit、2026-07-01〜28、HEAD は 2026-07-02 12:00 UTC）、identity は alice（claimed、同意あり）
# 0.8.0 = main abb7872 の src（src の最後の変更は d4b9bb8）、0.9.0 = 本 release の src。2026-10-26T08:27Z〜08:33Z 実測
$ grift verify --report report-v1-080.json --repo repo --identity identity.toml    # grift analyze の出力
CANNOT_VERIFY:
  - definition version 'tep-v0.8.0-2026-10-25' is not the current 'tep-v0.9.0-2026-10-26' — historical versions cannot be reproduced yet (compatibility table: docs/report-schema.md)
# rc=2。repo report-v2（grift repo の出力）も同じ理由で CANNOT_VERIFY rc=2

$ grift verify actor-080.json --repo repo --identity identity.toml    # grift actor alice --as-of 2026-08-31
CANNOT_VERIFY:
  - definition version 'tep-v0.8.0-2026-10-25' is not the current 'tep-v0.9.0-2026-10-26'
# rc=2

$ grift verify project-080.json --repo repo --identity identity.toml    # grift project --as-of 2026-08-31
MISMATCH: 1 field(s) differ
  - definition_version: report='tep-v0.8.0-2026-10-25' recomputed='tep-v0.9.0-2026-10-26'
# rc=1

$ grift verify align-080.json --repo repo --identity identity.toml    # 上の 2 つから grift align
CANNOT_VERIFY:
  - definition version is not current
# rc=2

$ grift verify coll-080 --repo repo --identity identity.toml    # grift actor alice --as-of 2026-08-31 --out coll-080
MISMATCH: role profile recomputation:alice
# rc=1。role_profile の窓の終わりが 2026-07-28T12:00:00Z（最後の commit）から 2026-08-31T23:59:59Z（観測日の終わり）に変わる

$ grift verify coll-080-now --repo repo --identity identity.toml    # --as-of なしで書いた collection
VERIFIED: actor collection 6 member(s), full=1, selected=1
# rc=0
```

## CI

workflow は変えていない。src が変わったので、証跡 4 件を 0.9.0 の source で作り直した。

- `benchmarks/v060/golden` は `gold-actor-partition-0006` として承認移行した（承認者
  human:teradakousuke、approved_at 2026-10-26T12:14:18Z、要求 REL-090。ユーザーの承認は親セッション
  経由で、`--approve` のコマンドはユーザーが実行した）。承認後の `scripts/v060_golden.py` は overall PASS
  （D0-D4 = 0）。dry-run（`scripts/v060_golden.py` と、`--approve` なしの
  `scripts/v060_golden_baseline.py --case actor-partition`、2026-10-26T08:47Z〜08:56Z。#95・#96 を入れた
  あとの 13:42Z も同じ）の drift は
  **D3 ×1 / D4 ×2、D0-D2 = 0**。D3 = `repo-report.json` の `provenance.tool_version`、D4 =
  `provenance.definition_version` と `metrics.human_nonmerge_commit_share.definition_version`。観測値の
  drift は 0
- `evidence/v060/scenarios` は release 束の source（c573792。#95・#96 を入れたあと）で再生成した
  （`--replace`、6 / 6 PASS、source_drift 0、2026-10-26T13:42Z、`--verify-registry` PASS）。source は 0.8.0 と同じ
  （BenevolentDirector / grift-landing-blueprint を 2026-09-27 の bundle から復元したもの、grift-cli の
  clone、`~/Developer/oss/voicevox` と `~/Developer/oss/kilo` の元 checkout）。全 6 シナリオで
  `partition_digest` と件数は 0.8.0 の登録値と一致し、変わったのは版数の文字列とそれに伴う digest、
  `runner-tool-version` assertion（0.8.0 → 0.9.0）、R01 の窓（2026-03-03〜2026-08-30 →
  2026-03-02〜2026-08-29）だけである。R01 の target（a650ffa）は 2026-08-30 00:51 JST
  （2026-08-29 15:51 UTC）に書かれた commit で、上の「`--as-of` なしの観測日を UTC の日付で取る」の
  東の朝に当たる。scenario runner が期待する窓も UTC の日付で作るように直した（PR #93。直す前は
  R01 の window-start / window-end が 1 日ずれて FAIL した）
- `evidence/v060/scenarios-public` は PR tier（`scripts/v060_provider_live_gate.py --tier pr
  --registry-output evidence/v060/scenarios-public --replace-registry`）を実走して再生成した
  （verdict PASS、3 / 3、2026-10-26T13:44Z、`--verify-registry --digest-only` PASS）。token は
  `V060_GITHUB_TOKEN` にプロセス環境でだけ渡し、成果物に含まれないことを grep で確認した
- `evidence/v070/benchmark.json` は `scripts/v070_benchmark.py --write` で再束縛した
  （self-contained 6 / 6 hold、2026-10-26T08:53Z）。`determinism.report_sha256` は pinned revision
  `fa9bc31` の `grift repo` report の digest で、`10d903ff…` → `5a63b782…` に変わった。同じ revision の
  report を 0.8.0 と 0.9.0 で比べると、違うのは `tool_version` と `definition_version`（2 か所）だけ
  だった。#95・#96 は `grift repo` の JSON を変えないので、そのあとは作り直していない
  （`tests/test_v070_benchmark.py` 18 passed、13:42Z）。corpus-dependent 4 件は記録のまま再実行していない

## v0.8.0 の差分

**面は増えない。既定の出力の形が 2 箇所で変わる。** v0.8.0 は、公開面が約束する
「点数や順位はつけない」「選んで出したことも受け取る側に分かる」を既定出力に揃える
release である。CLI フラグ・schema key・enum 値は変わらない。

### actor-index の行が canonical_id 順になる（**過去の collection に影響する**）

v0.7.2 までは `actor-index.json` / `actor-index.md` の行と selected card の列挙が
観測 commit 数の多い順だった。注記「not a quality ranking」は宣言のまま、表の並びという
実体は量で決まっていた。v0.8.0 は行を canonical_id 順にし、`commit_count` の値は分母付きの
事実としてそのまま残す。`--top N` が選ぶ N 名は変わらない（選択だけが commit 数順で、返す
id 列は index の行順）。

`grift verify DIR --repo REPO` は、行が canonical_id 順でない index を digest 比較の前に
拒否する。**v0.7.x で生成した collection は v0.8.0 の verify で MISMATCH になる。**

```
# 0.7.2（main cd13d12 の src）で作った collection（合成 repo、zed 5 / mid 3 / abe 1 commit）を 0.8.0 で verify
$ grift verify collection-072 --repo repo
MISMATCH: actor collection verification failed: actor index rows must be ordered by actor id, not by any observed count; observed 'zed' before 'mid' at row 1
# rc=1（2026-10-25 実測）

# 同じ 0.7.2 で保存した report-v2 / report-v1 を 0.8.0 で verify
$ grift verify --report report-v2-072.json --repo repo
CANNOT_VERIFY:
  - definition version 'tep-v0.7.2-2026-09-07' is not the current 'tep-v0.8.0-2026-10-25'
# rc=2。report-v1（grift analyze の出力）も同じ理由で CANNOT_VERIFY rc=2
```

該当する collection は v0.8.0 で作り直す。

### 選択性の固定注記（#2、PR #78）

単体の actor report-v2 と alignment-v1 の `notices` に、提供者が選んだ 1 repo であることを
示す固定文 `SELECTIVITY_NOTICE`（norms §6、公開面の流れ 02「選んで出したことも、受け取る側に
分かる形で残ります」）を常に載せる。Markdown の「言えること / 言えないこと」にも同じ文を出す。
文は英語で固定（collection の英語 limitation 文に揃えた）。collection の `repo-report.json`
（kind=repo）と actor-card-v1 は対象外。schema は `notices: array<string>` のため追加互換。

### TEP の展開と訳語対応表（#3、PR #75、main に先行マージ）

README / norms / metrics-guide に TEP の展開（Technical Evidence Pipeline）と公開面の訳語
（検査値 / テスト併修率 / 手戻り率 / 磨き直し / 定着率）の対応表を置き、parity テストで結んだ。
docs のみで出力は変わらない。

### 活動日数の膨らませ方を数値の隣に開示する（#4、PR #77）

`tep_core.v2_constants.ACTIVE_DAYS_INFLATION_LIMITATION` の 1 文（活動日数は author 日付の
一意な日数。毎日 1 件の小さな commit を置けば増え、同じ変更を 1 日にまとめると減る。量や
中身は見ておらず、補正もしない）を、report-v1 のトップレベル `limitations`（新 optional
key。`activity` の中には置かない: P0 反証 `P0-legacy-activity-parity` が同ブロックを
v0.5.9 と同一に保つ）、report-v2 `activity.limitations` と `change_rhythm.limitations`、
`align` の `change_rhythm.active_days_180d` 軸の `limitations`、およびそれぞれの Markdown に
固定で載せる。開示であって補正ではなく（norms §7）、値・比較結果・schema の必須項目は
変わらない。

`verify` は `limitations` も再計算して比べるので、v0.7.x で保存した report-v1 / report-v2 は
v0.8.0 の `verify` で本キーの分だけ MISMATCH になる（PR #77 本文の実測: report-v1 は
`limitations: report=None recomputed=[…]` の 1 field）。collection の digest 検証は影響を
受けない。

### 収集をやり直す必要があるか

| 成果物 | v0.7.x 生成物の v0.8.0 verify | 作り直し |
|---|---|---|
| actor collection（`repo --actors`、`actor --all/--top`、`actor ID --out DIR`） | MISMATCH（行順検査） | 要 |
| 単体 actor report-v2 / alignment | CANNOT_VERIFY（定義版数）。同じ定義版数の build 間では `notices` と `limitations` の差で MISMATCH | 要 |
| repo report-v2（collection 外） | CANNOT_VERIFY（定義版数）。`actor_directory` の行順と `activity` / `change_rhythm` の `limitations` が変わる | 要 |
| report-v1（`analyze` / `report`） | CANNOT_VERIFY（定義版数）。トップレベル `limitations` が加わる | 要（verify を使うなら） |
| attest / portfolio | 入力 report の digest が変われば再署名 | 入力に依存 |

## 定義版数

`DEFINITION_VERSION` を `tep-v0.8.0-2026-10-25` に上げた。版数への追随に加えて、
actor-index / `actor_directory` の形（行順）、actor report-v2 / alignment の `notices`、report-v1 / report-v2 の `limitations` の内容が変わるため。

## CI

- `benchmarks/v060/golden` は `gold-actor-partition-0005` として承認移行した（承認者
  human:teradakousuke、approved_at 2026-10-25T10:14:40Z、要求 REL-080。ユーザー承認は親セッション経由）。
  dry-run（`scripts/v060_golden.py`、2026-10-25）の drift は
  **D3 ×7 / D4 ×2、D0-D2 = 0**。D4 = `provenance.definition_version` と
  `metrics.human_nonmerge_commit_share.definition_version`。D3 = actor-index の `limitations[2]`
  追加、`actor-index.md` の size / sha256、`actor_index_digest`（collection-manifest と
  repo-report）、`tool_version`、`repo-report.md` の sha256。観測値の drift は 0
- `evidence/v060/scenarios` は release/v0.8.0 の source（d4b9bb8）で再生成した
  （`--replace`、6 / 6 PASS、source_drift 0、2026-10-25T10:00Z）。source は BenevolentDirector /
  grift-landing-blueprint を 2026-09-27 の bundle から復元したもの、grift-cli の clone、
  `~/Developer/oss/voicevox` と `~/Developer/oss/kilo` の元 checkout。全 6 シナリオで
  `partition_digest` と `population_digest` は 0.7.2 の登録値と一致し、変わったのは版数文字列と
  それに伴う digest、`runner-tool-version` assertion（0.7.2 → 0.8.0）だけである。
  **注意（再生成時の落とし穴）**: `actor_<hash>` の id は `canonical_origin`（remote URL）を含む
  repo scope digest で名前空間を分けるため、OSS repo を別 remote（ローカル path の clone）から
  読むと public inferred actor の id が変わり、partition digest が一致しなくなる（voicevox で
  実測: 118 actor のうち 26 が別 id）。source は元の remote URL を持つ checkout を使う
- `evidence/v060/scenarios-public` は PR tier（`scripts/v060_provider_live_gate.py --tier pr
  --registry-output evidence/v060/scenarios-public --replace-registry`）を実走して再生成した
  （verdict PASS、3 / 3、2026-10-25T09:56Z、`--verify-registry --digest-only` PASS）。token は
  `V060_GITHUB_TOKEN` にプロセス環境でだけ渡し、成果物に含まれないことを grep で確認した
- `evidence/v070/benchmark.json` は `scripts/v070_benchmark.py --write` で再束縛した
  （self-contained 6 / 6 hold、2026-10-25T09:52Z）。`determinism.report_sha256` は pinned revision
  `fa9bc31` の `grift repo` report の digest で、`actor_directory` の行順変更と `limitations` /
  `notices` の追加により `e780793a…` → `10d903ff…` に変わった。corpus-dependent 4 件は記録のまま
  再実行していない

## v0.7.2 の差分

**面は 1 つも増えない。** v0.7.2 は「commit がまだ 1 件も無い actor に対して report が
1 つも出ない」という v0.7.0 回帰を直す patch release である。CLI フラグ・出力スキーマ・
payload の形は変わらない。

### commit ゼロの actor でも report が出る

v0.7.0 / v0.7.1 は `grift actor <ID> REPO --identity <TOML>` を exit 2 で終わらせ、

```
report-v2 validation failed:
$.context_profile: must match exactly one allowed shape (matched 0)
```

だけを表示していた。`docs/norms.md` は「入力不足・履歴なしは理由付き `not_observed` で
あり能力否定ではない」と定めるので、report ごと消えるのは規範違反である。

v0.7.2 は rc=0 で report-v2 を書く。`change_rhythm` / `surface_profile` /
`verification_profile` / `coordination_profile` は v0.6.0 と同じく
`{kind: not_observed, reason: no_actor_commits}` を持つ。`context_profile` は
repository 自身の観測なので `kind: observed` のまま出る。

原因は独立に 2 つあった。

1. `analyze.prepare_inputs` が per-commit path の読み込みを
   `origin.counts["tenant_unique"] > 0` で門番していた。`context_profile` は
   `analysis_scope: "repo"` を宣言する repo スコープの層なのに、選ばれた actor に
   commit が無いというだけで repository 自身の `language_composition` が
   `not_observed(commit_paths_unavailable)` に落ちていた。
2. 契約カタログ `v060-contracts.schema.json` の
   `$defs.report_context_profile.language_composition` が `observed` 固定を宣言していた。
   builder は `not_observed` を出しうるのに、カタログはその形を禁じたままだった。

宣言（カタログ）と強制（builder）の片側だけが動いた状態が残っていた形である。
`tests/test_v072_empty_actor.py::test_catalog_accepts_every_language_composition_kind_the_builder_emits`
が両者を機械照合するので、片側だけを変えると両方の値を挙げて落ちる。

### 人のコミットが無い repo でも `grift repo` が通る

bot だけの repo は `context_profile` が `not_observed`（`reason: no_human_commits`）に
なる。v0.6.0 以降、その器へ `resolved_human_actors` を後付けしていたため、どの shape にも
当たらず report ごと拒否されていた。v0.7.2 は observed の profile にだけ被せる。

### `grift export --scope tenant` の path 数

上の (1) と同じ門番のため、**identity に載った人の commit が 0 件のとき**、
`grift export --scope tenant` は全 commit の `prod_paths_touched` /
`test_paths_touched` を 0 と書いていた。v0.7.2 は実測値を書く。

**該当する export をやり直すこと。** commit が 1 件でもある actor の出力は v0.7.1 と
同一である。

### 収集をやり直す必要があるか

| 条件 | v0.7.1 の出力 | 対応 |
|---|---|---|
| `grift actor` で対象 actor の commit が 1 件以上 | 正常 | 不要。出力は同一 |
| `grift actor` で対象 actor の commit が 0 件 | report なし（exit 2） | v0.7.2 で取り直す |
| `grift repo` で人の commit が 1 件以上 | 正常 | 不要。出力は同一 |
| `grift repo` で人の commit が 0 件（bot のみ） | report なし（exit 2） | v0.7.2 で取り直す |
| `grift export --scope tenant` で identity 上の commit が 0 件 | path 数が全て 0 | v0.7.2 で取り直す |

## 定義版数

`DEFINITION_VERSION` は `tep-v0.7.1-2026-09-06` から `tep-v0.7.2-2026-09-07` へ上がる。
根拠は 2 つある。

- 版数への追随
- commit ゼロの actor の `context_profile` の形が変わること。v0.7.1 ではそもそも
  report が出なかったので、この形は v0.7.2 が初めて出す

## CI

P0 反証スイート（`tests/fixtures/v060/run_p0_falsify.py`）はこれまで `publish.yml` でしか
走っていなかった。そのため上の回帰は v0.7.0 と v0.7.1 の両方に載ったまま出荷され、最初に
気づいたのは tag を打った後の release run（34069987423）である。

v0.7.2 は `ci.yml` に `p0-falsify` job を足し、publish.yml と同じ immutable pin
（公開 v0.5.9 = `6711a3cdcb71f2a2a84276ac5e7a5abd4a7bf79f`）を同じ env 名
`GRIFT_V059_ROOT` で checkout して走らせる。pin が 2 ファイルに散ったので、
`tests/test_publish_baseline_pin.py` が両者の一致を機械照合する。

## v0.7.1 の差分

**面は 1 つも増えない。** v0.7.1 は公開 Forge 取得の 2 つの欠陥を直す
patch release である。CLI フラグ・出力スキーマ・payload の形は変わらない。

### bot / app アカウントで `--fetch-public` が落ちなくなる

GitHub の commit author が Bot / app installation
（`Copilot`、`dependabot[bot]`、`renovate[bot]`、`github-actions[bot]`）の
場合、`html_url` は `https://github.com/apps/<slug>` を指し、handle は
角括弧を含む。v0.7.0 はこの行にも public account を付けようとして
`profile_url` が空の account を作り、actor 成果物の生成が
`account '<provider>|<host>|<id>' needs a handle and profile URL` で
落ちていた。fetch は成功しているのに report が 1 つも出ず exit 2 になる。

v0.7.1 はこれらの行を **public account にしない**。commit は
`unlinked_commit_count` に数える。人の account が handle と
canonical な profile URL を必ず持つ条件は変えていない。

**bot は v0.7.1 でも public account にはならない。** bot の commit を
「誰かの貢献」として数え直したのではなく、public account の欄を
空にしたまま unlinked として数える。git 側の bot 判定
（`report.bot`）は従来どおり別に動く。

### 切れた転送を検出し、有限回リトライする

GitHub の commits ページは 1 ページ約 400KB あり、転送が宣言した長さに
届かないまま終わることがある。実測で `Content-Length: 436443` に対し
受信 372299 バイト、次の `read()` は即 `b""`。v0.7.0 はこの切れた bytes を
そのまま JSON として読み、`Forge response body is not valid UTF-8 JSON`
という「Forge の応答が壊れている」形のエラーを出していた。実際は
転送が途中で終わっただけである。

v0.7.1 は受信バイト数を `Content-Length` と照合し、足りなければ
`ForgeTruncatedBodyError` として扱う。**切れた body を JSON デコーダに
渡さない。** そのうえで収集ループが同一 request を最大 3 回まで試す
（backoff 0.5s / 1.0s）。使い切った場合は従来どおり
`stop_reason: transport_error:ForgeTruncatedBodyError` で止まり、
coverage は `complete` にならない。`TimeoutError` など他の transport error も
同じ扱いである。`Content-Length` を宣言しない chunked 応答は従来どおり
EOF が唯一の終端で、そのまま受け取る。1 ページあたりのバイト上限は
hard stop として残る。

発生頻度は環境依存である。ある環境では同一 URL 25 回中 2〜3 回、
別の環境では 145 回中 0 回だった。「もう起きない」ではなく
「起きたら検出して数回やり直す」である。

リトライ回数は bundle manifest に記録しない。`public-evidence-v1` の
page（`$defs.public_page`）は `additionalProperties: false` の閉じた
オブジェクトで、キーの追加は patch release での契約変更に当たるためである。

### 手当てが要る場合

**bot commit を含む repo は、account linkage の観測値が v0.7.1 で変わる。**
bot / app アカウントを public account にしなくなったので、
`provider.sha-to-account` と `account.commit-linked` が減る
（実測: cloudflare 661 → 657、vite の 1 ページ収集 100 → 94）。
`actors.full` や `report.human_nonmerge` などの git 側の観測値は変わらない。
これらの数値を保存している場合は **v0.7.1 で収集をやり直す**。

v0.7.0 で `--fetch-public` が exit 2 または
`Forge response body is not valid UTF-8 JSON` で失敗した収集も、
証跡が残っていないので v0.7.1 でやり直す。

上記に当たらない、すでに完了した bundle の再取得は不要である。

## v0.7.0 の差分

### 出力が増える（既存フィールドの意味は変えていない）

| ブロック | scope | 内容 |
|---|---|---|
| `library_context` | actor | 導入したライブラリが参照コーパスでどれだけ普及しているか。ライブラリを記述するのであって人を記述しない |
| `outcome` | repo / actor | `--outcome-declaration` を渡したときだけ。必ず `kind: "declared"` で、観測にはならない |
| `verification_profile.test_type_share` | repo / actor | テスト種別ごとの commit 割合。下記「`test_type_share`」を読んでから使うこと |

report-v2 を strict に検証している消費側は、このキーの追加で落ちる可能性がある。

### `--outcome-declaration` が付く scope は `repo` と `actor` だけ

`grift project` と `grift align` には付いていない。渡すと argparse が拒否する。

```console
$ grift project . --outcome-declaration outcome.toml
grift: error: unrecognized arguments: --outcome-declaration outcome.toml
$ grift align --actor-report a.json --project-report p.json --outcome-declaration outcome.toml
grift: error: unrecognized arguments: --outcome-declaration outcome.toml
```

project report は宣言された要求を記述し、alignment report は保存済み 2 report
の上のビューであり、どちらも `report_outcome` を出さない。フラグをそこにも
提供すると、ファイルを受け取り、何も読まず、outcome の無い report を返す
ことになる。それは「何も宣言されなかった」と読める（norms §1）。
根拠は `src/tep_cli/options.py:123-143`（`add_outcome_declaration` の docstring と、
それを呼ぶのが `repo` / `actor` の 2 parser だけであること）。

### `outcome` は `grift verify` の検査対象ではない

`grift verify` は観測を再計算して突き合わせる。宣言された outcome には
再計算する元が無く、verifier には宣言ファイルが渡されないため、
**`grift verify` は `outcome` ブロックを比較しない**。diff から外してある。

```python
# src/tep_core/verify.py:45
NOT_RECOMPUTED_PATHS = {"outcome"}
```

したがって **宣言を書き換えても verify は MISMATCH にならない**。
report 自身がこの限界を毎回明記する（`src/tep_core/outcome.py:80-84`）:

```text
Declared outcomes are not observations. `grift verify` neither recomputes
nor compares them; a modified declaration is not detected by verify.
Their absence is not evidence that work did not ship (norms §1, §3).
```

「再計算しない」だけを読むと保護のように見えるが、逆である。ここでは
何も検査していないので、変更を検知するものが無い。outcome を根拠に
使う受領者は、verify の VERIFIED をこのブロックの保証と読んではならない。

### `verification_profile.test_type_share`

`verification_profile` に新設した。分母は **テストを触った commit 数**である
（`denominator_definition = "commits that touched at least one test path"`,
`src/tep_core/verification_profile.py:105-121`）。

**各 type の share は独立に割るので、合計は 1 にならない。** 1 commit が unit と
e2e の両方を触れば両方に 1 ずつ加算される（type ごとの集合を commit 単位で
取るため）。読み手は値を足してはならない。

これ以前は `test_type_distribution` が commit 数しか持たず、type に対して床を
宣言しても比較する share が無かった。`alignment._obs_share` は share を探して
見つけられず、**非ゼロの type すべてを `not_observed`、ゼロの type だけを
`below_declared`（`observed_zero` 由来）にしていた**。実際に手を動かした type が
「未測定」と読める逆転である。`test_type_share` の新設でこれを直した。

母集団が `MIN_POPULATION_FOR_RATES` 未満のときは
`not_observed(insufficient_population)`、テストを触った commit が 0 のときは
`not_observed(no_test_touching_commits)` であり、0.0 という値は出さない。

### 切り詰めた履歴の扱いが変わる（**過去の出力に影響する**）

shallow クローン（`actions/checkout` の既定 `fetch-depth: 1` を含む）では、
リポジトリ全体を主張する 8 フィールドが `not_observed / history_incomplete` に
degrade する。v0.6.0 では取得できた範囲の値を `observed` として出していた。

CI で生成した v0.6.0 の証跡がある場合は
`provenance.revision_completeness.shallow` を確認すること。`true` なら
`repo_age_days` / `first_commit` / `resolved_human_actors` などは誤っている。

### promisor clone では「完全」と「不完全」が同じ report に同居する

promisor（`--filter=blob:none` / `--filter=tree:0`）では、判定が 2 つ別々に走る。

| ブロック | promisor での状態 | 理由 |
|---|---|---|
| `context_profile.repo_age_days`、`scale.first_commit`、`activity.*` など commit 由来の値 | **observed のまま** | `revision.commit_history_complete` は promisor を不完全と数えない。commit graph は完全で、commit 数・日付・author は正確である（`src/tep_core/revision.py:46-64`） |
| `experience` / `role_profile` / `library_context` | **`not_observed(history_incomplete)`** | これらは blob を読む。`experience_collect` は promisor を明示的に拒否する（`src/tep_core/experience_collect.py:166-167`） |

**これは矛盾ではない。測っている対象が違う。** 「履歴は完全か」という問いは、
commit graph について訊けば promisor では yes、file 内容について訊けば no になる。
両方の判定がそれぞれ正しい結果を返しており、片方に合わせて他方を degrade させる
のは「測ったものを報告しない」という逆向きの誤りになる。

shallow clone では両方が不完全になるので、この同居は起きない。

### `grift align --team`

宣言された要求をチームが覆えているかを、人数のみで出す。個人の測定値は
匿名の最大値としても出ない。3 名未満（`complementarity.MIN_TEAM_SIZE = 3`）では
`not_observed`（`reason: insufficient_team_size`）を返し、個人を特定しうる数を
出さない。exit code は 0 である（hard error ではない）。

#### 入力は report-v2 であって actor card ではない

`--actor-dir` に渡すディレクトリの中身は、次のどちらかになる。**分岐を間違えると
拒否される。**

| 生成コマンド | 出力先 | schema | `--team` |
|---|---|---|---|
| `grift actor <ID> <repo> --identity <toml> --format json` | **stdout** | `report-v2` | 受理する |
| `grift actor <ID> <repo> --identity <toml> --out DIR` | `DIR/actors/<id>.json` | `actor-card-v1` | **拒否する** |

card を渡すと次で止まる（`src/tep_cli/subject.py:1097-1101`）:

```text
align --team requires report-v2 actor reports; actor-card-v1 carries no surface
observations. Produce one per member with: grift actor <ID> --identity <toml> --format json
```

card には `surface_profile` が無いため、読ませると宣言された要求がすべて
`not_observed` になる。読むことは拒否することより悪い ―― 出力が「チームを
測った結果」の形をしてしまうからである。

正しい作り方:

```bash
mkdir -p team
grift actor alice . --identity .tep/identity.toml --format json > team/alice.json
grift actor bob   . --identity .tep/identity.toml --format json > team/bob.json
grift actor carol . --identity .tep/identity.toml --format json > team/carol.json
grift align --team --actor-dir team --project-report project-out/project.json
```

#### identity は identity-v2 で consent と authority が要る

`experience` / `role_profile` を observed にできるのは、閉じた identity-v2 の
`consent` + `authority` の対を記録した行だけである
（`src/tep_core/identity.py:88-103` の `has_recorded_explicit_consent`）。
identity-v1 の行は読めるが、consent 証拠にはならない。

最小の `.tep/identity.toml`（identity-v2 は未知キーを拒否する。actor 行に
書けるのは `canonical_id` / `emails` / `email_sha256` / `github_login` /
`attribution_state` / `consent` / `authority` だけ）:

```toml
schema_version = "identity-v2"

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "claimed"          # verified か claimed のみ consent を持てる
consent = "recorded-explicit-consent"  # この文字列以外は拒否される
authority = "subject-authorization"    # または "repository-owner-authorization"
```

これはローカルの申告であって、申告者の身元・本人性・実世界の同意の証明ではない。

### `grift contribute --purpose`

提出データの目的を提出者が選ぶ。無指定時は v0.6.0 と同じ意味になる。

| purpose | 使える door |
|---|---|
| `reference-distributions`（既定） | `local` / `controlled` / `public-pr` |
| `outcome-linkage` | `local` / `controlled` |

`outcome-linkage` を `--door public-pr` に渡すと hard error である。公開受け口の
schema が v0.6.0 の単一値のまま pin されているためで、通せば payload を組み立て、
開示し、提出者が確認した後で受け口に弾かれる。ここで断るのは受領者ではなく
提出者の時間を使う選択である。norms の話ではなく、受け口の現状の話である
（`src/tep_core/contribution_v2.py:85-105`）。受け口の schema が受理する日に広げる。

### ベンチマーク主張の読み方

`evidence/v070/benchmark.json` の主張は、測った範囲までしか主張していない。
特に次の 2 件は、そのまま一般化すると誤読になる。

**`offline` は Python プロセス層のみ。** この項目が測っているのは、既定の解析経路が
Python プロセスから socket を開かないことだけである
（`measured.scope = "python_process_only"`、`watched_audit_events` は
`socket.connect` / `socket.getaddrinfo` / `socket.gethostbyname` / `urllib.Request`）。
**git subprocess の通信は測っていない**（`git_subprocess_network = "not_measured"`）。
git は `GIT_NO_LAZY_FETCH=1` の下で走るが、この項目はその効果を検証していない。
「grift はネットワークに触れない」という一般化された主張の根拠には使えない。

**δ = -0.7871 は v0.7.0 では再現できない。** `validity-person-signal` の
`cliffs_delta = -0.7871`（352 pair / 41 repository / 300 actor）は
`role-profile-v1` の上で、v0.7.0 の同意ゲートより前に測った値である。
`reproducibility` は `not_reproducible_on_this_version` であり、理由は次のとおり:

```text
v0.7.0 emits role_profile only for actors with a recorded explicit consent
(identity-v2 `consent` + `authority`). The study corpus is public OSS contributors
with no such record; re-measuring would require asserting consent on their behalf,
which the project refuses to do.
```

つまりこの数値は v0.7.0 の挙動の証拠ではなく、v0.7.0 で再測定する手段も無い。
現行版の主張として引用してはならない。

| 旧操作 | v0.6 の扱い |
|---|---|
| `grift analyze` | report-v1。裸実行は repo scope |
| `grift analyze PATH` | report-v1。明示パスの tenant default を維持 |
| `grift report` | `.grift/report.{json,md}` を現在 HEAD から再生成 |
| `grift verify` | schema を自動判別（report-v1 / report-v2 / alignment-v1） |
| `grift contribute` | report-v1は既存`tep-contribution-v1`、report-v2はprofile別`tep-contribution-v2`。alignment-v1は拒否 |
| `--scope actor` | 許可しない。`grift actor ACTOR_ID` を使う |
| `grift actor ID --export DIR` | 許可しない |

新しい入口:

```text
このリポジトリを観測したい       → grift repo
この repo-local Actor の本人証拠を見たい → grift actor
この案件の要求と運用条件を記録したい → grift project
この本人証拠と案件要求を並べたい     → grift align
```

v0.6.0 の正式な cross-repo 経路:

```bash
grift actor ACTOR_ID ACTOR_REPO --identity ACTOR_IDENTITY --format both --out actor-report.json
grift project PROJECT_REPO --requirements PROJECT_TOML --format both --out PROJECT_REPORT_DIR
grift align \
  --actor-report actor-report.json \
  --project-report PROJECT_REPORT_DIR/project.json \
  --format both --out ALIGNMENT_DIR
grift verify ALIGNMENT_DIR/alignment.json \
  --actor-report actor-report.json \
  --project-report PROJECT_REPORT_DIR/project.json \
  --reference-manifest benchmarks/v060/sources.json
```

`grift repo REPO --actors --out DIR`、`grift actor --all REPO --out DIR`、
`grift actor --top N REPO --out DIR`、`grift actor ACTOR_ID REPO --out DIR` は、
次の閉じたActor collectionを新規ディレクトリへ書きます。既存ディレクトリは
置換しません。単一Actorの詳細report-v2はstdoutまたは
`--out FILE.json|FILE.md`で維持します。

```text
DIR/repo-report.json
DIR/repo-report.md
DIR/actor-index.json
DIR/actor-index.md
DIR/actors/<actor-id>.json
DIR/actors/<actor-id>.md
DIR/collection-manifest.json
```

`repo-report.*` はfull population、`actor-index.*`はfull/selectedの両集合、
`actors/*`はselected cardです。`actors/*.json`のschemaは`actor-card-v1`です。
集合自体は次でGit partitionまでoffline再検証します。

```bash
grift verify DIR --repo REPO
```

alignment は次で接続します。

```bash
grift align --actor-dir DIR --actor-id ACTOR_ID --project-report PROJECT/project.json
```

複数 card では `--actor-id`（別名 `--actor`）必須です。先頭ファイルの暗黙選択はしません。
Actor ID、`--all`、`--top`は排他です。IDのdirectory出力は
`actor-index-v1.selection.mode=explicit`を使います。explicit cardのoptional
`experience` / `role_profile`は固定OIDとidentityから再計算されるため、cardと
manifestを同時に書き換えてもverifyはMISMATCHにします。同意済みdetailを持つ
collectionは、生成時と同じ`--identity FILE`をverifyにも指定します。

v0.6 subject（repo/actor/project/align/verify）の暗黙identity探索は対象repoへ閉じます。
固定OID treeの`.tep/identity.toml`または明示`--identity FILE`だけを使い、別repoを
観測するプロセスのCWD identityとworking-treeだけの変更は無視します。legacy
`analyze` / `report`のhistorical discoveryは互換helperへ隔離されています。
experience/roleをobservedにできる明示Actor行は`attribution_state=verified|claimed`
だけで、consent basisにもstateを記録します。`inferred|external|unresolved|bot`は
`not_observed(consenting_actor_required)`です。

AI coauthor identityは固定OID treeの`.tep/ai-identities.toml`へ移します。closed
`ai-identity-v1`はtop-level `schema_version`、`emails`、`email_sha256`以外を拒否し、
少なくとも1つのexact identityを要求します。working-treeだけの宣言は無視します。
既存の`AI-Assisted-By` / `AI-Generated-By` / `Agent-Lane`は挙動を変えず、未宣言の
`Co-authored-by`はhuman coauthorのままです。

`grift align --repo --identity --actor --project` は互換経路です。project observed が無い場合、Markdown は次を明記します。

```text
project observedは未提供のため、actorとprojectの実測比較は行っていません。
```

alignment の各軸は actor observed / project observed / project declared を分け、n・denominator・source・window を混ぜません。relationship は `similar_direction` / `different_direction` / `mixed` / `not_comparable` であり、採用・能力・適合ではありません。

`--reference-manifest` の digest は provenance に残し、verify 時に再指定します。異なる manifest は `MISMATCH` または `CANNOT_VERIFY: benchmark manifest is unavailable or different` です。

dirty worktree では `checkout --force` を使いません。unreachable SHA は `not reachable`、reachable かつ dirty は破壊的 checkout を拒否します。

`grift analyze PATH --actor ACTOR_ID --identity FILE` は互換 alias。stderr に deprecation を出し、出力は report-v2、`.grift/report.json` は上書きしない。

v0.6 の `change_rhythm` は 180 日窓内の author timestamp だけを gap 母集団にします。窓の外側は別カウントです。

## 固定revisionと公開Forge証跡

`repo` / `actor`は`--rev REV`をSHA-1/SHA-256の固定OIDへ解決します。既定はofflineで、
`--fetch-public`、`--public-evidence DIR`、`--resume-public-evidence DIR`は排他です。
取得時は`--forge-provider auto|github|gitlab`、`--forge-api-base URL`、
`--auth-token-env NAME`、`--public-evidence-out DIR`、`--max-public-pages N`を
明示できます。self-managed GitLabは明示providerとAPI baseが必要です。
GitHubとGitLabは同じprovider-neutral契約で扱いますが、GitLab commits APIに
documented account linkageがない場合は`unsupported/not_proven`のままです。
公開表示が加わってもActor partitionと全Git由来数値は変わりません。

公開取得の安全な途中停止はexit 3（PARTIAL）です。保存bundleを使う`verify`は
networkへ再接続せず、schema、manifest/body digest、再parse、Git OID集合、
SHA/account対応、report/collection bindingを検査します。

終了コードは`0=VERIFIED`、`1=MISMATCH`、`2=CANNOT_VERIFY`、公開取得の
安全な途中停止だけ`3=PARTIAL`です。

## contribution-v2

| profile | 許可door | 境界 |
|---|---|---|
| `aggregate` | `local` / `public-pr` | Actor行、remote/OID、正確な時刻、source digestなし。公開default |
| `named-public` | `local` / `public-pr` | 明示authorityのあるprovider-neutral account/projectだけ |
| `masked` | `local` / `controlled` | HMAC pseudonym付き高精度観測。controlled sidecar必須 |
| `raw` | `local` / `controlled` | 研究用raw source。controlled sidecar必須 |

masked/rawの`public-pr`はhard errorです。masked HMAC鍵は32 byte以上の
permission検査済みfile/FDからだけ読みます。CLI引数、環境変数、payload、logへ
鍵を出しません。認可済みcontrolled destinationがないため自動uploadは実装しません。

## attest / portfolio

`grift attest REPORT --repo REPO --out DIR --sign ssh|cosign`は、先にreportを
再計算してからcanonical statementへ外部署名します。reportが
`--public-evidence`、`--forge-export`、`--tracker-export`、
`--reference-manifest`を記録している場合、署名前preflightにも同じ保存入力を
明示してください。入力を省略・交換したreportは署名しません。alignmentでは
必要に応じ`--project` / `--actor`、または`--actor-report` /
`--project-report`も同様に渡します。このpreflightとverifyはnetworkへ接続しません。

statementはreport SHA-256とgeneric Git OIDに加え、全`input_digests`のmemberと
canonical aggregate digest、定義版集合digest、公開証跡digest、固定OIDから到達可能な
tag集合digest、analysis scope、実行時刻を署名対象にします。tag集合digestはtag refと
Git objectを結びますが、taggerのname/emailやtag本文をstatementへ出力しません。
`grift verify --report REPORT --bundle DIR --repo REPO`はsignature、report hash、
repository recomputationを別判定にします。SSHは受領者の
`--allowed-signers` / `--principal`、cosignはpublic keyまたは受領者が指定した
certificate identity/issuerをtrust anchorにし、bundle内の自己申告鍵を信頼しません。

`grift portfolio --manifest portfolio.toml --format both --out DIR`は、
明示self declarationまたはattestationで同じ主体を結んだ証拠台帳です。
email/handleからのcross-repo推論、平均、重み、score、rankは生成しません。
`subject_binding = "attested"`では、明示subjectを持つ各report-v2の署名を、受領者が
CLIで指定した単一のSSH allowed_signers/principalまたはcosign certificate/public key
により実検証します。bundle内の自己申告鍵、trust未指定、異なるsigner、方式混在、
subject不一致は受理しません。`self_declared`へtrust optionを混ぜることも拒否します。
repo hintはmanifestでentryごとに明示したときだけ成果物へ含めます。

## schema と互換性

- report-v1 / export-v1は追加互換です。既存キー・値・意味を変更しません
- `report_context_profile.language_composition` は `observed` 固定から
  `observed | not_observed` の oneOf へ**緩和**しました。v0.7.1 が受理していた
  payload はすべて v0.7.2 でも受理されます
- report-v2、actor card/index、project、alignment、public evidence、
  contribution-v2、attest、portfolio、scenario、forge/tracker export-v2は
  Draft 2020-12の閉じたschemaで未知キーを拒否します
- legacy commandはexport-v1の読取互換を維持します。v0.6 subject commandは
  provider/host/project/target OID/window/coverageへboundされたexport-v2だけを
  受けるのがrelease契約です。`EXT-01`がPASSになるまではこの経路を完了扱いしません
- experience/roleはreport-v1の同意済みtenant reportへの追加fieldだけです。
  export-v1へはconsumer sign-offまで追加しません

## network経路

測定コマンドの暗黙update checkはありません。明示network経路はpublic fetch /
resume、`grift update --check`、`grift contribute --open`、cosign keylessだけです。
public evidence replay、report/collection/attestation verifyはnetworkへ再接続しません。
