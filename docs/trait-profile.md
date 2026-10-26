# 進め方の文と面談の問いの決定表

[English](en/trait-profile.md) | **日本語**

`grift actor`・`grift project`・`grift align` の Markdown の先頭に出す「この記録から見える進め方」の文と、「面談で確かめたいこと」の問いは、この表で JSON の数字から機械的に選びます。LLM は使いません。文と問いは Markdown にだけ出し、JSON には入れません（[ADR-0002](adr/ADR-0002-trait-profile.md) T4・T6）。

この表と `src/tep_core/trait_tables.py` の定数は `tests/test_v090_trait_tables.py` で結んであり、片方だけ変えると、テストが両方の値を挙げて落ちます。表を変えるときは、release の commit で `DEFINITION_VERSION` を上げます。

## 文を出す相手

| 出力 | 文を出す条件 | 出さないとき |
|---|---|---|
| `grift actor`（1 人） | `attribution_state = "claimed"` で、identity の行に `consent = "recorded-explicit-consent"` があり、リポジトリが浅い clone でない | 節の見出しの下に、出していない理由を 1 文で書く（下の `NOT_SHOWN`） |
| `grift actor --all` / `--top` | 出さない | collection の Markdown と JSON には、文の節も理由の文も作らない |
| `grift project` | 案件のリポジトリの記録を渡したとき。人ごとの数字は出しません | 記録を渡していないと書く |
| `grift align` | 重なっている点の表は、いつも出す。面談の問いは、本人が名乗った ID（claimed）で同意の記録があるとき。`grift align` が actor report の同意の記録を `subject.actor_consent` に写し、actor の文と同じ関数で確かめる | 管理者が登録した ID・公開 inferred・同意なし・不明の actor には問いを出さず、理由を書く（`questions_not_shown`）。間隔の問いは本人の進め方の文に合わせない（本人の進め方の文は actor の Markdown にだけ出す）。actor の記録が浅い clone のときは、表も問いも出さず `NOT_SHOWN_SHALLOW_TEMPLATE` の文だけを出す |

出さないときの文は次のとおりです（`NOT_SHOWN_TEMPLATE`）。`{reason}` に下の `NOT_SHOWN` の 1 行が入ります。

> この節の文は出していません。{reason}です。本人が名乗った ID（attribution_state = "claimed"）と、同意の記録（consent = "recorded-explicit-consent"）があるときだけ出します。

浅い clone（履歴が途中までしか無い記録）には、同意の記録があっても節の文を出さず、次の文を出します（`NOT_SHOWN_SHALLOW_TEMPLATE`）。浅い clone では、取得できたいちばん古い変更がすべてのファイルを足したように数えられ、場所の件数も間隔も全履歴と変わるためです。

> この節の文は出していません。{reason}です。浅い clone では、いちばん古い変更がすべてのファイルを足したように数えられ、場所や間隔の数が全履歴と変わります。`git fetch --unshallow` で全履歴を取ってから実行すると出します。

部分 clone（promisor）は commit がすべてそろうので節を出します。ただし role_profile は集めないので、「関わり方」だけを理由つきで外します（`work_not_observed`）。時間の上限で集められなかったときも同じです。role_profile は、`--as-of` を指定したときは観測日で切り、指定しないときは HEAD までのすべての commit を数えます。その母数がこの節の変更の数と違うときは、この観点を外して両方の数を書きます。role_profile が観測日のあとの変更も数えているときは `work_scope_later`、そうでないときは `work_scope_differs` です。取り込み（merge）の回数は、role_profile が観測日のあとの変更を数えていないときだけ書きます。リリースの印（タグ）の回数は `--as-of` を指定していないときだけ書きます（タグを付けた日は JSON に入っていないため）。0 回はどちらもいつでも書きます。

測れなかった理由は `PLAIN_REASONS` の平易な文で書きます。表に無い理由は、内部名だけを出さずに次の文に入れます（`PLAIN_REASON_FALLBACK`）。

> この記録の数え方では測れないため（記録の上の理由は `{reason}`）

## 数字の書き方

- 件数は JSON の値をそのまま書きます。割合は件数に戻して「{n} 件のうち {c} 件」と書きます。母数が 20 に届かないときは、文も根拠の行も出さず、照らし合わせの表には件数だけを書きます。
- 間隔の真ん中の値と、短い順に並べて 9 割のところの間隔（p90）は、小数 1 桁に四捨五入します。p90 は前後の 2 つの値のあいだを按分した値なので、「10 回に 9 回がこれ以内」とは言い切れません。照らし合わせの節では、間隔をすべて切り上げます。案件の上限と並べた値が判定と食い違わないようにし、同じ値を 1 つの節の中で 2 通りに書かないためです。
- 2 日以内と 30 日以上の回数は、JSON の割合に間隔の回数を掛けて四捨五入します。間隔が 10000 回以上のときは、割合が小数 4 桁に丸めてあるので「約」を付け、先頭の文も出しません。
- 割合の下限（`min_share`）は百分率で書きます（0.3 は 30%）。
- 本人のレポートの範囲は「{end} までの全履歴」と書きます（浅い clone には節を出さないため）。案件のリポジトリの記録は project-v1 に浅い clone かどうかが入らないので「{end} までの履歴」と書き、限界の注記（`shallow_repo`）を付けます。
- 保存した alignment だけを渡し、actor の数が JSON に無いときは、割合の下限を宣言した項目を割合で書き（`record_own_share`）、ほかの項目は件数だけを書きます。
- 場所の並びと、同じ件数のときの順は `SURFACES`（`src/tep_core/v2_constants.py`）の順です。並びは何も意味しません。

## 境目（`THRESHOLDS`）

| id | 意味 | 値 |
|---|---|---|
| `min_population` | 分母（変更の件数、間隔の回数、直しの変更の件数）がこれに届かないと、その観点の文と根拠の行を出さない | 20 |
| `steady_p90_max_days` | 短い順に並べて 9 割のところの間隔の上限。30 日以上の間隔が 0 回で、これ以内なら「間をあまり空けずに」 | 7 |
| `burst_share_min` | 2 日以内の間隔の割合の下限。30 日以上の間隔が 1 回以上で、これ以上なら「続けて出す時期と、長く空く時期」 | 0.5 |
| `max_following_places` | 「次いで」と根拠の表に並べる場所の数 | 4 |
| `max_questions` | 本人のレポートの面談の問いの数 | 4 |

## 呼び名

### 場所（`PLACE_NAMES`）

| id | 呼び名 |
|---|---|
| `test` | テスト |
| `docs` | 文書 |
| `ci_cd` | 自動テストと配布の設定 |
| `platform` | 実行環境の設定 |
| `data` | データベースの定義 |
| `observability` | 監視とログ |
| `frontend` | 画面 |
| `backend` | サーバー側の処理 |
| `config` | 設定ファイル |
| `generated_vendor` | 自動生成・外部から取り込んだコード |
| `other` | 種類を分けられなかったファイル |

### テストの種類（文の中）（`TEST_TYPE_NAMES`）

| id | 呼び名 |
|---|---|
| `unit` | 部品ごとに確かめる単体テスト |
| `integration` | 組み合わせて動かす結合テスト |
| `e2e` | 画面から通しで動かす E2E テスト |
| `contract` | 外部との約束事を確かめる契約テスト |
| `unspecified` | 種類を判別できないテスト |

### テストの種類（表と問いの中）（`TEST_TYPE_SHORT_NAMES`）

| id | 呼び名 |
|---|---|
| `unit` | 単体テスト |
| `integration` | 結合テスト |
| `e2e` | E2E テスト |
| `contract` | 契約テスト |
| `unspecified` | 種類を判別できないテスト |

### 共有する記録（`INPUT_NAMES`）

| id | 呼び名 |
|---|---|
| `git` | git の記録 |
| `forge` | レビューの記録（forge） |
| `tracker` | 課題管理の記録（tracker） |

### 間隔の項目（`RHYTHM_ITEM_NAMES`）

| id | 呼び名 |
|---|---|
| `active_days_180d` | 変更を出した日の数 |
| `median_gap_days` | 変更の間隔の真ん中の値 |
| `p90_gap_days` | 間隔を短い順に並べて 9 割のところ |

## 文（`SENTENCES`）

| id | 観点 | 条件 | 文 |
|---|---|---|---|
| `place_lead` | 変えた部分の区分（作業領域） | 分母（path が取れた変更）が 20 件以上。test を除いて件数がいちばん多い場所が 1 つ | いちばん多いのは{place}で、{scope} {n} 件のうち {c} 件です。 |
| `place_lead_tie` | 変えた部分の区分（作業領域） | 件数がいちばん多い場所が 2 つ以上。SURFACES の順に「、」でつなぐ | いちばん多いのは次の場所で、{scope} {n} 件のうち、それぞれ {c} 件です（{places}）。 |
| `place_following` | 変えた部分の区分（作業領域） | 0 件より多いほかの場所。件数の多い順（同じ件数は SURFACES の順）に 4 つまで | 次いで、{items}にも触れています。 |
| `place_few` | 変えた部分の区分（作業領域） | 分母が 20 件未満 | {scope}が 20 件に届かないため、この観点の文は出していません（{n} 件）。 |
| `place_not_observed` | 変えた部分の区分（作業領域） | surface の観測が not_observed | 触った場所は、この記録からは測れませんでした（理由: {reason}）。 |
| `place_tests_only` | 変えた部分の区分（作業領域） | 分母が 20 件以上で、触った場所がテストだけ | {scope} {n} 件はどれもテストのファイルの変更でした。テストは「テストの付け方」で数えています。 |
| `rhythm_steady` | 変更のペース（変更リズム） | 間隔が 20 回以上 1 万回未満。30 日以上の間隔が 0 回で、9 割のところが 7 日以内 | 間をあまり空けずに出す進め方です。 |
| `rhythm_bursty` | 変更のペース（変更リズム） | 間隔が 20 回以上 1 万回未満。30 日以上の間隔が 1 回以上で、2 日以内の間隔が半分以上 | 続けて出す時期と、長く空く時期がある進め方です。 |
| `rhythm_detail` | 変更のペース（変更リズム） | 間隔が 20 回以上（先頭の文が無いときも出す） | 変更と変更の間隔は、真ん中の値が {median} 日、短い順に並べて 9 割のところが {p90} 日でした。間隔 {n} 回のうち、2 日以内が {burst} 回、30 日以上が {long} 回です。 |
| `rhythm_few` | 変更のペース（変更リズム） | 間隔が 20 回未満 | 変更と変更の間隔が 20 回に届かないため、この観点の文は出していません（{n} 回）。 |
| `rhythm_not_observed` | 変更のペース（変更リズム） | 間隔の観測が not_observed | 変更の間隔は、この記録からは測れませんでした（理由: {reason}）。 |
| `verify_lead` | テストの付け方（検証の形） | テストのファイルを変えた変更の割合が observed（変更が 20 件以上） | テストのファイルも一緒に変えた変更が、{n} 件のうち {c} 件あります。 |
| `verify_types` | テストの付け方（検証の形） | 0 件より多いテストの種類（VERIFICATION_TYPES の順） | テストの種類は{types}です。 |
| `verify_fix_paired` | テストの付け方（検証の形） | 直し（fix・revert）の変更が 20 件以上 | 直し（fix）の変更 {s} 件のうち {w} 件で、テストも一緒に変えています。 |
| `verify_fix_few` | テストの付け方（検証の形） | 直しの変更が 1 件以上 20 件未満 | 直し（fix）の変更は {s} 件で、20 件に届かないため、テストとの組み合わせは数えていません。 |
| `verify_not_observed` | テストの付け方（検証の形） | verification_profile が not_observed | テストの記録は、この記録からは測れませんでした（理由: {reason}）。テストを書いていないという意味ではありません。 |
| `work_modify_more` | 関わり方 | 手を入れる変更のほうが多い（role_profile。本人のレポートだけ） | すでにあるファイルに手を入れる変更（{m} 件）のほうが、新しいファイルを作る変更（{c} 件）より多い進め方です。 |
| `work_create_more` | 関わり方 | 作る変更のほうが多い | 新しいファイルを作る変更（{c} 件）のほうが、すでにあるファイルに手を入れる変更（{m} 件）より多い進め方です。 |
| `work_equal` | 関わり方 | 同じ数 | 新しいファイルを作る変更と、すでにあるファイルに手を入れる変更が、どちらも {c} 件です。 |
| `work_process` | 関わり方 | 取り込み（merge）とリリースの印（タグ）がどちらも 1 回以上。取り込みは role_profile が観測日のあとの変更を数えていないとき、リリースの印は `--as-of` を指定していないときだけ数える | ほかの作業の取り込み（merge）を {i} 回、リリースの印（タグ）付けを {r} 回しています。 |
| `work_merge_only` | 関わり方 | 数えた取り込みだけが 1 回以上 | ほかの作業の取り込み（merge）を {i} 回しています。 |
| `work_release_only` | 関わり方 | 数えたリリースの印だけが 1 回以上 | リリースの印（タグ）付けを {r} 回しています。 |
| `work_few` | 関わり方 | role_profile がこの節と同じ変更を数えていて、自分の変更が 20 件未満 | 自分の変更が 20 件に届かないため、この観点の文は出していません（{n} 件）。 |
| `work_not_observed` | 関わり方 | 同意の記録はあるが、role_profile を集められなかった（部分 clone、時間の上限） | 関わり方は、この記録からは数えていません（理由: {reason}）。 |
| `work_scope_differs` | 関わり方 | role_profile の母数がこの節の変更の数と違い、観測日のあとの変更は数えていない | 関わり方の数は、この節のほかの観点と数えた変更が違うため、この観点の文は出していません（この数え方では {n} 件、ほかの観点では {total} 件）。 |
| `work_scope_later` | 関わり方 | role_profile の母数がこの節の変更の数と違い、観測日のあとの変更も数えている | 関わり方の数は、観測日のあとの変更も含めて数えていて、この節のほかの観点と数えた変更が違うため、この観点の文は出していません（この数え方では {n} 件、観測日までは {total} 件）。 |

## 面談の問い（本人のレポート、`QUESTIONS`）

| id | 順 | 条件 | 問い |
|---|---|---|---|
| `ask_outside` | 1 | 場所の先頭の文がある（同点なら同点の場所を「、」でつなぐ） | {place}のほかに、この記録の外でしている仕事はありますか（別のリポジトリ、非公開の仕事、設計や運用など）。 |
| `ask_outside_plain` | 1 | 場所の先頭の文が無い | この記録の外でしている仕事はありますか（別のリポジトリ、非公開の仕事、設計や運用など）。 |
| `ask_rhythm_steady` | 2 | 間隔の先頭の文が `rhythm_steady` | 細かく分けて変更を出すのは、チームの決まりですか。自分のやり方ですか。 |
| `ask_rhythm_bursty` | 2 | 間隔の先頭の文が `rhythm_bursty` | 続けて出す時期と、長く空く時期は、それぞれどんな仕事の区切りでしたか。 |
| `ask_fix_without_test` | 3 | 直しの変更が 20 件以上で、テストを変えなかったものが 1 件以上 | 直しの変更 {s} 件のうち、テストを変えなかった {u} 件はどんな場面でしたか。 |
| `ask_test_type` | 3 | 直しの変更が 20 件未満で、テストの種類が 1 つ以上（件数がいちばん多い種類。同じ件数は VERIFICATION_TYPES の順） | {type}（{c} 件）はどんな場面で書いていますか。 |
| `ask_release` | 4 | 数えたリリースの印が 1 回以上（role_profile がこの節と同じ変更を数えていて、`--as-of` を指定していないとき） | リリースの印付け（{r} 回）はどこまで任されていましたか。 |
| `ask_unclassified` | 5 | 種類を分けられなかったファイルに触れた変更が 1 件以上 | 「種類を分けられなかったファイル」に触れた変更（{k} 件）は、何のファイルでしたか（決まりに入っていない拡張子のことがあります）。 |

## 照らし合わせの節（`ALIGNMENT_TEXTS`）

| id | 並び | 項目 | 文 |
|---|---|---|---|
| `zero_note` | observed_zero | 節の頭に 1 回 | 0 件はこの記録に無いという意味です。その仕事をしたことがないという意味ではありません。 |
| `ask_zero_places` | observed_zero | 場所（0 件の場所を SURFACES の順にまとめる） | {places}は、案件が求めていますが、この記録では 0 件です。このリポジトリの外（別のリポジトリ、非公開の仕事）でしていたかを聞いてください。 |
| `ask_zero_tests` | observed_zero | テストの付け方（0 件の種類をまとめる） | {types}はこの記録では 0 件です。書いたり直したりしたことがあるか、どの道具を使ったかを聞いてください。 |
| `ask_below_share` | outside_declared_range | 場所とテストの付け方（割合の下限を宣言したとき） | {item}は、案件が{floor}を求めていて、この記録では{record}です（要望の範囲の外）。この記録の外での仕事と、案件での分担を聞いてください。 |
| `ask_outside_gap` | outside_declared_range | 間隔（真ん中の値、9 割のところ。上限と並べるので切り上げる） | {item}は、案件が {declared} 日以内を求めていて、この記録では {observed} 日です（要望の範囲の外）。どんな事情でその間隔になったかと、案件の進め方に合わせるときに何が必要かを聞いてください。 |
| `ask_outside_days` | outside_declared_range / observed_zero | 変更を出した日の数（0 日も） | 変更を出した日の数は、案件が 180 日のうち {declared} 日以上を求めていて、この記録では {observed} 日です（要望の範囲の外）。日数はまとめて出すか分けて出すかで変わります。どんな単位で変更を出してきたかを聞いてください。 |
| `ask_forge` | not_observed | レビューの記録（forge） | レビューの記録（forge）はこの記録に入っていないため測れていません。レビューをどんな流れで受けてきたか（誰に、どのくらいの単位で）を聞いてください。 |
| `ask_not_observed` | not_observed | そのほか（role_lens は表示の型なので問いにしない） | {item}は、この記録からは測れませんでした（理由: {reason}）。直接聞いてください。 |
| `ask_other` | どれでも | この表に行の無い並びと項目（落とさずに問いにする） | {item}はこの記録では「{state}」でした。直接聞いてください。 |
| `questions_not_shown` | — | actor basis が claimed でない（verified、公開 inferred、同意なし、不明）か、claimed でも `subject.actor_consent` が無い | 面談の問いは出していません。{reason}です。本人が名乗った ID（attribution_state = "claimed"）と、同意の記録（consent = "recorded-explicit-consent"）があるときだけ出します。 |
| `no_questions` | — | 問いが 1 つも無いとき | 要望の範囲の外になった項目と、測れなかった項目はありません。 |
| `no_overlap` | overlap | 重なっている項目が無いとき | 要望と記録が重なっている項目はありません。 |
| `not_declared_gap` | not_declared | 間隔（記録の値を切り上げて並べる。問いは出さない） | {item}は、案件が書いていません。この記録では {observed} 日です。 |
| `not_declared_days` | not_declared | 変更を出した日の数 | 変更を出した日の数は、案件が書いていません。この記録では 180 日のうち {observed} 日です。 |
| `header_request` | 表 | 重なっている点の表の左の見出し | 案件の要望 |
| `header_record` | 表 | 重なっている点の表の右の見出し | `{cid}` の記録 |
| `cell_own_count` | overlap | 場所の記録の欄（母数が 20 未満なら `cell_count`） | 記録の変更 {n} 件のうち {c} 件 |
| `cell_count` | overlap | 件数だけの欄（母数が 20 未満か、分からないとき） | {c} 件 |
| `cell_place_floor` | overlap | 割合の下限を宣言した場所の要望の欄 | {place}（その人の変更の {pct} 以上） |
| `cell_test_floor` | overlap | 割合の下限を宣言したテストの付け方の要望の欄 | {type}（テストのファイルを変えた変更の {pct} 以上） |
| `cell_days_min` | overlap | 変更を出した日の数の要望の欄 | 変更を出した日の数が 180 日のうち {d} 日以上 |
| `cell_days` | overlap | 日数と間隔の記録の欄（間隔は切り上げ） | {v} 日 |
| `cell_median_max` | overlap | 真ん中の値の要望の欄 | 変更の間隔の真ん中の値が {d} 日以内 |
| `cell_p90_max` | overlap | 9 割のところの要望の欄 | 間隔を短い順に並べて 9 割のところが {d} 日以内 |
| `cell_input` | overlap | 共有する記録の要望の欄 | {input}を共有する |
| `cell_shared` | overlap | 共有する記録の記録の欄 | 共有されている |
| `floor_own` | outside_declared_range | 場所の下限（`ask_below_share` の中） | その人の変更の {pct} 以上 |
| `floor_tests` | outside_declared_range | テストの付け方の下限（`ask_below_share` の中） | テストのファイルを変えた変更の {pct} 以上 |
| `record_own` | outside_declared_range | 場所の記録（`ask_below_share` の中。母数が 20 以上） | 変更 {n} 件のうち {c} 件 |
| `record_tests` | overlap / outside_declared_range | テストの付け方の記録（母数が 20 以上） | テストのファイルを変えた変更 {n} 件のうち {c} 件 |
| `record_own_count` | outside_declared_range | 場所の記録（母数が 20 未満か、分からないとき） | 変更のうち {c} 件 |
| `record_tests_count` | outside_declared_range | テストの付け方の記録（母数が 20 未満か、分からないとき） | テストのファイルを変えた変更のうち {c} 件 |
| `record_own_share` | overlap / outside_declared_range | 保存した alignment に actor の数が無いときの、割合の下限を宣言した場所の記録 | 変更の {pct} |
| `record_tests_share` | overlap / outside_declared_range | 同じく、割合の下限を宣言したテストの付け方の記録 | テストのファイルを変えた変更の {pct} |

## 平易な理由（`PLAIN_REASONS`）

| id | 文 |
|---|---|
| `insufficient_population` | 数が 20 に届かないため |
| `no_commits_in_window` | 数えた 180 日のあいだに変更が無いため |
| `no_gaps` | 変更と変更の間隔が無いため |
| `no_human_commits` | 人の変更が無いため |
| `no_actor_commits` | この人の変更が無いため |
| `commit_paths_unavailable` | 変更したファイルの置き場所が取れなかったため |
| `numstat_unavailable` | 変更した行の数が取れなかったため |
| `no_test_framework_or_directory` | テストの仕組みやテストの置き場所が見つからなかったため |
| `no_test_touching_commits` | テストのファイルを変えた変更が無いため |
| `no_fix_or_revert_commits` | 直し（fix・revert）の変更が無いため |
| `no_production_commits` | 本番のコードを変えた変更が無いため |
| `consenting_actor_required` | 同意の記録が無いため |
| `history_incomplete` | 履歴か Git のデータの一部が手元に無いため（浅い clone、部分 clone など） |
| `experience_collection_timeout` | 履歴を読む時間の上限を超えたため |
| `pending_attribution` | 誰の変更かがまだ決まっていないため |
| `head_date_unavailable` | 最後の変更の日付が取れなかったため |
| `forge_export_not_provided` | レビューの記録のファイルを渡していないため |
| `tracker_export_not_provided` | 課題管理の記録のファイルを渡していないため |
| `bound_export_not_provided` | 書き出した記録のファイルを渡していないため |
| `event_window_not_provided` | イベントを数える期間を渡していないため |
| `public_evidence_not_provided` | 公開の記録を取りに行っていないため |
| `provider_api_terms_not_recorded` | 公開の記録の利用条件が記録されていないため |
| `tracker_timestamps_missing` | 課題管理の記録に時刻が無いため |
| `archive_events_have_no_actor_identity` | 公開イベントの記録に、人との対応が無いため |
| `synthetic_contract_not_actor_evidence` | 試験用の合成データで、人の記録ではないため |
| `dependency_scan_not_provided` | 依存の読み取りをしていないため |
| `repository_not_provided` | リポジトリを渡していないため |
| `project_report_not_provided` | 案件のレポートを渡していないため |
| `project_observed_not_provided` | 案件のリポジトリの記録を渡していないため |
| `axis_not_in_project_observed` | 案件のリポジトリの記録にこの項目が無いため |
| `requirement_not_provided` | 案件側が書いていないため |
| `not_declared` | 案件側が書いていないため |
| `role_lens_not_set` | 表示の型を指定していないため |
| `share_not_observed` | 割合が出ていないため |
| `observed_unavailable` | 比べる値が出ていないため |
| `not_observed` | 測れなかったため |
| `n_missing` | 母数が無いため |
| `unit_mismatch` | 単位が違うため |
| `non_scalar_observed` | 1 つの数で表せない値のため |
| `windows_not_equivalent` | 数えた期間が違うため |
| `window_too_short_for_shape` | 数えた期間が短いため |
| `no_surface_share` | 場所の割合が無いため |
| `tied_top_share` | 割合がいちばん大きい場所が 2 つ以上あるため |
| `no_tendency_for_axis` | この項目には傾向を出さないため |

## 文を出さない理由（`NOT_SHOWN`）

| id | 文 |
|---|---|
| `admin_verified` | 管理者が登録した ID（attribution_state = "verified"）の記録のため |
| `public_inferred` | 公開リポジトリの記録から、名前とメールで同じ人と推定したまとまりのため |
| `explicit_nonconsent` | 同意の記録が無い ID の記録のため |
| `unknown` | 表示の根拠（selection と attribution_state）を確かめられないため |
| `no_consent` | 本人が名乗った ID ですが、同意の記録（consent）が無いため |
| `shallow_history` | 履歴が途中までしか無い記録（浅い clone）のため |

## 数字の読み方と限界（`LIMIT_NOTES`）

| id | 文 |
|---|---|
| `places` | 場所はファイルの置き場所と拡張子の決まりで分けています。中身は読んでいません。1 件の変更が 2 つ以上の場所に入ることがあります。 |
| `rhythm` | 間隔は小さく分けて毎日出せば短くなり、まとめて出せば長くなります。補正はしていません。 |
| `tests` | テストはテストのファイルに 1 行足すだけでも「一緒に変えた」に数えます。変えた行の中身は見ていません。 |
| `own_work` | 「多い」はこの記録の変更の中で多いという意味です。ほかの人やほかのリポジトリとは比べていません。 |
| `overlap` | 「重なっている」は、要望の場所や種類の変更が記録に 1 件以上あるという意味です。どれだけ慣れているかは示しません。 |
| `days` | 変更を出した日の数は小さく分けて毎日出せば増え、まとめて出せば減ります。要望の日数は量の線で、補正はしていません。 |
| `scales` | 1 人の記録と案件のリポジトリの件数は、同じ物差しではありません。件数どうしを割り算した比べ方はしていません。 |
| `verify` | 数字は JSON の値から作っています。JSON は `grift verify` で検算できます。この Markdown は検算の対象外です。 |
| `p90` | 間隔を短い順に並べたときの 9 割の位置の値を「9 割のところ」と書いています（前後の 2 つの値のあいだを按分します）。 |
| `gap_rounding` | この節の間隔の日数は上限と並べたときに判定と食い違わないよう、すべて小数 1 桁に切り上げています。 |
| `shallow_repo` | 浅い clone のリポジトリでは、取得できた変更だけを数えます。いちばん古い変更はすべてのファイルを足したように数えられます。project の JSON には浅い clone かどうかが入っていません。 |

## 並びの呼び名（`ask_other` の中）（`VERDICT_NAMES`）

| id | 文 |
|---|---|
| `overlap` | 要望と重なる |
| `outside_declared_range` | 要望の範囲の外 |
| `observed_zero` | 0 件 |
| `not_observed` | 測れない |
| `not_declared` | 要望なし |

## 見出し（`HEADINGS`）

| id | 文 |
|---|---|
| `actor_title` | # `{cid}` の記録から見える進め方 |
| `project_title` | # 案件「{title}」の要望と記録 |
| `project_title_untitled` | # 案件の要望と記録 |
| `alignment_title` | # `{cid}` の記録と、案件「{title}」の照らし合わせ |
| `alignment_title_untitled` | # `{cid}` の記録と、案件の照らし合わせ |
| `work` | ## 進め方 |
| `places` | ### 変えた部分の区分（作業領域） |
| `rhythm` | ### 変更のペース（変更リズム） |
| `verify` | ### テストの付け方（検証の形） |
| `make` | ### 関わり方 |
| `unseen` | ## この記録では見えないこと |
| `questions` | ## 面談で確かめたいこと |
| `limits` | ## 数字の読み方と限界 |
| `evidence` | ## 根拠 |
| `declared` | ## 案件側が書いた要望 |
| `repository` | ## 案件のリポジトリから見える進め方 |
| `overlap` | ## 要望と記録が重なっている点 |
| `align_questions` | ## 面談で確かめたい点 |
| `not_declared` | ## 案件側が書いていないこと（参考） |

## 節の決まった文（`SECTION_TEXTS`）

| id | 文 |
|---|---|
| `actor_intro` | `{cid}` が共有した 1 つのリポジトリの git の記録を、仕事の言葉に直しました。本人が名乗った ID と同意の記録があるので、この節を出しています。点数・順位・合否は出しません。 |
| `record_scope` | - 数えた範囲: {end} までの全履歴（自分の変更 {total} 件） |
| `record_scope_paths` | - 数えた範囲: {end} までの全履歴（自分の変更 {total} 件。ファイルを変えた変更は {paths} 件で、変えた部分の区分はこの {paths} 件で数えています） |
| `rhythm_period` | - 間隔を数えた期間: {start}〜{end} の {days} 日（この間の変更 {n} 件） |
| `project_intro` | 案件側が書いた要望（宣言）と、案件側のリポジトリの git の記録を、別の節に分けて並べます。会社や案件の良し悪しは出しません。 |
| `project_people` | 人ごとの数字は出しません。 |
| `project_no_repository` | 案件のリポジトリの記録を渡していないので、この節の文は出していません。`grift project REPO` で記録を足せます。 |
| `declared_note` | 書いていない項目は、要望が無いという意味です。不足として扱いません。 |
| `alignment_intro` | 案件の要望と、`{cid}` の記録を項目ごとに並べました。点数と、重なった項目の数は出しません。 |
| `unseen_both` | レビューのやり方と課題の管理は入っていません。レビューと課題管理の記録のファイルを渡していないためです。 |
| `unseen_forge` | レビューのやり方は入っていません。レビューの記録のファイルを渡していないためです。 |
| `unseen_tracker` | 課題の管理は入っていません。課題管理の記録のファイルを渡していないためです。 |
| `unseen_always` | 設計や会議の進め方は、git の記録には残りません。 |
| `unseen_zero_places` | ここに出ていない場所（{places}）は 0 件でした。この記録に無いという意味で、その仕事をしたことがないという意味ではありません。 |
| `unseen_zero_places_repo` | このリポジトリに無い場所（{places}）は 0 件でした。案件にその仕事が無いという意味ではありません（別のリポジトリで扱っていることがあります）。 |
| `unseen_no_release` | リリースの印（タグ）を付けた記録はありません。リリースを誰が担当していたかは、この記録からは分かりません。 |
| `unseen_other_repos` | 案件で使っているほかのリポジトリがあるかは、この記録からは分かりません。 |
| `history` | {end} までの全履歴 |
| `history_repo` | {end} までの履歴 |
| `window` | {start}〜{end} |
| `count_of` | {n} 件中 {c} 件 |
| `gaps_of` | 間隔 {n} 回中 {c} 回 |
| `days_with_gaps` | {days} 日（間隔 {n} 回） |
| `count_list` | {n} 件中 {values} |
| `count_unit` | {c} 件 |
| `count_times` | {c} 回 |
| `overlapping_counts` | （1 件が両方に入ることがあります） |
| `same_period` | 同上 |
| `col_aspect` | 観点 |
| `col_counted` | 数えたもの |
| `col_value` | 件数 |
| `col_period` | 期間 |

## 根拠の表の「数えたもの」（`EVIDENCE_ROWS`）

| id | 文 |
|---|---|
| `place_top` | {place}に触れた変更 |
| `place_rest` | {places}に触れた変更 |
| `rhythm_median` | 変更と変更の間隔の真ん中の値 |
| `rhythm_p90` | 間隔を短い順に並べて 9 割のところ |
| `rhythm_long` | 30 日以上空いた間隔 |
| `verify_touch` | テストのファイルも変えた変更 |
| `verify_types` | {types}のファイルを変えた変更 |
| `verify_fix` | 直し（fix・revert）の変更のうち、テストも変えたもの |
| `work_modify_create` | 手を入れる変更 / 新しく作る変更 |
| `work_merges` | 取り込み（merge） |
| `work_releases` | リリースの印（タグ） |

## 案件側が書いた要望（`DECLARED_TEXTS`）

| id | 文 |
|---|---|
| `surfaces` | - 変えた部分の区分（作業領域）: {items} |
| `verification` | - テストの付け方（検証の形）: {items} |
| `active_days_180d_min` | - 変更を出した日の数: 180 日のうち {n} 日以上 |
| `median_gap_days_max` | - 変更の間隔の真ん中の値: {n} 日以内 |
| `p90_gap_days_max` | - 間隔を短い順に並べて 9 割のところ: {n} 日以内 |
| `inputs` | - 共有してほしい記録: {items} |
| `not_declared` | - 書いていないこと: {items} |
| `share_floor` | {name}（変更の {pct} 以上） |

## 要望の項目の呼び名（`DECLARED_ITEM_NAMES`）

| id | 文 |
|---|---|
| `surfaces` | 変えた部分の区分（作業領域） |
| `verification` | テストの付け方（検証の形） |
| `active_days_180d_min` | 変更を出した日の数 |
| `median_gap_days_max` | 変更の間隔の真ん中の値 |
| `p90_gap_days_max` | 間隔を短い順に並べて 9 割のところ |
| `inputs` | 共有してほしい記録 |
| `role_lens` | 表示の型（role_lens） |
