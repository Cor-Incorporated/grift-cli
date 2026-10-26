# Decision tables for the working-pattern sentences and interview questions

**English** | [日本語](../trait-profile.md)

The sentences under "この記録から見える進め方" (what this record shows about how the work was done) and the questions under "面談で確かめたいこと" (what to confirm in the interview), printed at the top of the `grift actor`, `grift project` and `grift align` Markdown, are picked mechanically from the JSON numbers by these tables. No LLM is used. The text exists only in Markdown, never in JSON ([ADR-0002](../adr/ADR-0002-trait-profile.md) T4 and T6). The CLI prints Japanese, so the last column of every table is the exact Japanese text; the other columns explain it in English.

These tables and the constants in `src/tep_core/trait_tables.py` are tied by `tests/test_v090_trait_tables.py`: if one side changes alone, the test fails and names both values. A change to a table raises `DEFINITION_VERSION` in the release commit.

## Who gets the sentences

| Output | Sentences are printed when | Otherwise |
|---|---|---|
| `grift actor` (one person) | `attribution_state = "claimed"` and the identity row records `consent = "recorded-explicit-consent"`, and the repository is not a shallow clone | The section says in one sentence why it is not shown (`NOT_SHOWN` below) |
| `grift actor --all` / `--top` | Never | Collection Markdown and JSON get no sentence section and no reason |
| `grift project` | The project repository was observed. No per-person numbers | The section says that no repository was given |
| `grift align` | The overlap table, always. Interview questions for an identity the person claimed, with the consent record. `grift align` copies the actor report's consent record into `subject.actor_consent`, checked by the same function as the actor sentences | Administrator-registered, public inferred, unconsented and unknown actors get no questions and the reason (`questions_not_shown`). The gap question never follows the person's rhythm sentence (that sentence appears only in the actor Markdown). When the actor record is a shallow clone, neither the table nor the questions are shown, only the `NOT_SHOWN_SHALLOW_TEMPLATE` text |

When the section is not shown, it prints this text (`NOT_SHOWN_TEMPLATE`), with one `NOT_SHOWN` row as `{reason}`:

> この節の文は出していません。{reason}です。本人が名乗った ID（attribution_state = "claimed"）と、同意の記録（consent = "recorded-explicit-consent"）があるときだけ出します。

A shallow clone (a record whose history stops partway) gets no sentences even with a recorded consent; it prints this text instead (`NOT_SHOWN_SHALLOW_TEMPLATE`). In a shallow clone the oldest fetched commit reads as adding every file, so the place counts and the gaps differ from the full history.

> この節の文は出していません。{reason}です。浅い clone では、いちばん古い変更がすべてのファイルを足したように数えられ、場所や間隔の数が全履歴と変わります。`git fetch --unshallow` で全履歴を取ってから実行すると出します。

A partial (promisor) clone has every commit, so the section is shown. role_profile is not collected there, so only "関わり方" (how they take part) is left out with the reason (`work_not_observed`), as it is when the time budget runs out. role_profile is cut at an explicit `--as-of`, and without one it counts every commit up to HEAD. When its denominator still differs from the section's own commits, that aspect is left out and both counts are named: `work_scope_later` when role_profile also counted work after the observation date, `work_scope_differs` otherwise. A merge count is stated only when role_profile counted nothing after the observation date, and a release-tag count only without an explicit `--as-of` (tag dates are not in the JSON). A count of zero is always stated.

A reason that could not be measured is written with a `PLAIN_REASONS` row. A reason with no row never prints as a bare internal name; it goes into this sentence (`PLAIN_REASON_FALLBACK`):

> この記録の数え方では測れないため（記録の上の理由は `{reason}`）

## How numbers are written

- Counts are the JSON values. Shares are turned back into counts, "{c} of {n}". Below a denominator of 20 there is no sentence and no evidence row, and the alignment table shows the count alone.
- The median gap and the 90th-percentile gap are rounded half up to one decimal. The 90th percentile is interpolated between two neighbouring gaps, so "9 of 10 gaps are within it" cannot be claimed. In the alignment sections every gap is rounded up, so a value next to a declared upper bound never contradicts the verdict and one value never prints two ways in one section.
- The counts of gaps within 2 days and of 30 days or more are the JSON share times the number of gaps, rounded half up. With 10,000 gaps or more the share's four decimals cannot give an exact count, so the count is marked 約 (about) and no lead sentence is picked.
- A declared minimum share (`min_share`) is written as a percentage (0.3 is 30%).
- The actor report calls its range "{end} までの全履歴" (the whole history up to the date), because a shallow clone gets no section. The project repository's record is "{end} までの履歴" (the history up to the date) with a limit note (`shallow_repo`), because project-v1 does not record whether the clone was shallow.
- When only a saved alignment is given and the JSON has no actor counts, an item with a declared minimum share is written as a share (`record_own_share`) and any other item as a count alone.
- Places, and ties between them, follow the `SURFACES` order in `src/tep_core/v2_constants.py`. The order carries no meaning.

## Boundaries (`THRESHOLDS`)

| id | Meaning | Value |
|---|---|---|
| `min_population` | Below this denominator (changes, gaps, fix changes) the aspect gets no sentence and no evidence row | 20 |
| `steady_p90_max_days` | Upper bound for the 90th-percentile gap; with no gap of 30 days or more, the steady lead sentence | 7 |
| `burst_share_min` | Lower bound for the share of gaps within 2 days; with at least one gap of 30 days or more, the bursty lead sentence | 0.5 |
| `max_following_places` | Places listed after the lead place, in the sentence and in the evidence table | 4 |
| `max_questions` | Interview questions in the actor report | 4 |

## Plain names

### Places (`PLACE_NAMES`)

| id | Printed name |
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

### Test types (in sentences) (`TEST_TYPE_NAMES`)

| id | Printed name |
|---|---|
| `unit` | 部品ごとに確かめる単体テスト |
| `integration` | 組み合わせて動かす結合テスト |
| `e2e` | 画面から通しで動かす E2E テスト |
| `contract` | 外部との約束事を確かめる契約テスト |
| `unspecified` | 種類を判別できないテスト |

### Test types (in tables and questions) (`TEST_TYPE_SHORT_NAMES`)

| id | Printed name |
|---|---|
| `unit` | 単体テスト |
| `integration` | 結合テスト |
| `e2e` | E2E テスト |
| `contract` | 契約テスト |
| `unspecified` | 種類を判別できないテスト |

### Shared records (`INPUT_NAMES`)

| id | Printed name |
|---|---|
| `git` | git の記録 |
| `forge` | レビューの記録（forge） |
| `tracker` | 課題管理の記録（tracker） |

### Rhythm items (`RHYTHM_ITEM_NAMES`)

| id | Printed name |
|---|---|
| `active_days_180d` | 変更を出した日の数 |
| `median_gap_days` | 変更の間隔の真ん中の値 |
| `p90_gap_days` | 間隔を短い順に並べて 9 割のところ |

## Sentences (`SENTENCES`)

| id | Aspect | Condition | Printed text |
|---|---|---|---|
| `place_lead` | Parts changed (work surface) | Denominator (changes with paths) of 20 or more; one place has the most changes, test excluded | いちばん多いのは{place}で、{scope} {n} 件のうち {c} 件です。 |
| `place_lead_tie` | Parts changed (work surface) | Two or more places share the most changes, joined with 「、」 in SURFACES order | いちばん多いのは次の場所で、{scope} {n} 件のうち、それぞれ {c} 件です（{places}）。 |
| `place_following` | Parts changed (work surface) | Other places above zero, by count (ties in SURFACES order), up to 4 | 次いで、{items}にも触れています。 |
| `place_few` | Parts changed (work surface) | Denominator below 20 | {scope}が 20 件に届かないため、この観点の文は出していません（{n} 件）。 |
| `place_not_observed` | Parts changed (work surface) | The surface profile is not_observed | 触った場所は、この記録からは測れませんでした（理由: {reason}）。 |
| `place_tests_only` | Parts changed (work surface) | Denominator of 20 or more and every change touched tests only | {scope} {n} 件はどれもテストのファイルの変更でした。テストは「テストの付け方」で数えています。 |
| `rhythm_steady` | Pace of change (change rhythm) | 20 to 9,999 gaps; no gap of 30 days or more and the 90th percentile within 7 days | 間をあまり空けずに出す進め方です。 |
| `rhythm_bursty` | Pace of change (change rhythm) | 20 to 9,999 gaps; at least one gap of 30 days or more and half or more of the gaps within 2 days | 続けて出す時期と、長く空く時期がある進め方です。 |
| `rhythm_detail` | Pace of change (change rhythm) | 20 gaps or more, with or without a lead sentence | 変更と変更の間隔は、真ん中の値が {median} 日、短い順に並べて 9 割のところが {p90} 日でした。間隔 {n} 回のうち、2 日以内が {burst} 回、30 日以上が {long} 回です。 |
| `rhythm_few` | Pace of change (change rhythm) | Fewer than 20 gaps | 変更と変更の間隔が 20 回に届かないため、この観点の文は出していません（{n} 回）。 |
| `rhythm_not_observed` | Pace of change (change rhythm) | The change rhythm is not_observed | 変更の間隔は、この記録からは測れませんでした（理由: {reason}）。 |
| `verify_lead` | How tests are added (verification profile) | The share of changes that touched a test file is observed (20 changes or more) | テストのファイルも一緒に変えた変更が、{n} 件のうち {c} 件あります。 |
| `verify_types` | How tests are added (verification profile) | Test types above zero, in VERIFICATION_TYPES order | テストの種類は{types}です。 |
| `verify_fix_paired` | How tests are added (verification profile) | 20 or more fix or revert changes | 直し（fix）の変更 {s} 件のうち {w} 件で、テストも一緒に変えています。 |
| `verify_fix_few` | How tests are added (verification profile) | 1 to 19 fix or revert changes | 直し（fix）の変更は {s} 件で、20 件に届かないため、テストとの組み合わせは数えていません。 |
| `verify_not_observed` | How tests are added (verification profile) | The verification profile is not_observed | テストの記録は、この記録からは測れませんでした（理由: {reason}）。テストを書いていないという意味ではありません。 |
| `work_modify_more` | How they take part | More modifying changes (role_profile, actor report only) | すでにあるファイルに手を入れる変更（{m} 件）のほうが、新しいファイルを作る変更（{c} 件）より多い進め方です。 |
| `work_create_more` | How they take part | More creating changes | 新しいファイルを作る変更（{c} 件）のほうが、すでにあるファイルに手を入れる変更（{m} 件）より多い進め方です。 |
| `work_equal` | How they take part | Equal counts | 新しいファイルを作る変更と、すでにあるファイルに手を入れる変更が、どちらも {c} 件です。 |
| `work_process` | How they take part | At least one merge and one release tag. Merges count only when role_profile counted nothing after the observation date, release tags only without an explicit `--as-of` | ほかの作業の取り込み（merge）を {i} 回、リリースの印（タグ）付けを {r} 回しています。 |
| `work_merge_only` | How they take part | Only counted merges | ほかの作業の取り込み（merge）を {i} 回しています。 |
| `work_release_only` | How they take part | Only counted release tags | リリースの印（タグ）付けを {r} 回しています。 |
| `work_few` | How they take part | role_profile counts the same commits, and fewer than 20 own changes | 自分の変更が 20 件に届かないため、この観点の文は出していません（{n} 件）。 |
| `work_not_observed` | How they take part | Consent recorded, but role_profile could not be collected (partial clone, time budget) | 関わり方は、この記録からは数えていません（理由: {reason}）。 |
| `work_scope_differs` | How they take part | role_profile counts a different set of commits, none after the observation date | 関わり方の数は、この節のほかの観点と数えた変更が違うため、この観点の文は出していません（この数え方では {n} 件、ほかの観点では {total} 件）。 |
| `work_scope_later` | How they take part | role_profile counts a different set of commits, including work after the observation date | 関わり方の数は、観測日のあとの変更も含めて数えていて、この節のほかの観点と数えた変更が違うため、この観点の文は出していません（この数え方では {n} 件、観測日までは {total} 件）。 |

## Interview questions in the actor report (`QUESTIONS`)

| id | Order | Condition | Printed text |
|---|---|---|---|
| `ask_outside` | 1 | The place lead sentence exists (tied places joined with 「、」) | {place}のほかに、この記録の外でしている仕事はありますか（別のリポジトリ、非公開の仕事、設計や運用など）。 |
| `ask_outside_plain` | 1 | No place lead sentence | この記録の外でしている仕事はありますか（別のリポジトリ、非公開の仕事、設計や運用など）。 |
| `ask_rhythm_steady` | 2 | The rhythm lead is `rhythm_steady` | 細かく分けて変更を出すのは、チームの決まりですか。自分のやり方ですか。 |
| `ask_rhythm_bursty` | 2 | The rhythm lead is `rhythm_bursty` | 続けて出す時期と、長く空く時期は、それぞれどんな仕事の区切りでしたか。 |
| `ask_fix_without_test` | 3 | 20 or more fix changes and at least one without a test change | 直しの変更 {s} 件のうち、テストを変えなかった {u} 件はどんな場面でしたか。 |
| `ask_test_type` | 3 | Fewer than 20 fix changes and at least one test type (the type with the most changes; ties in VERIFICATION_TYPES order) | {type}（{c} 件）はどんな場面で書いていますか。 |
| `ask_release` | 4 | At least one counted release tag (role_profile counts the same commits, and no explicit `--as-of`) | リリースの印付け（{r} 回）はどこまで任されていましたか。 |
| `ask_unclassified` | 5 | At least one change that touched an unclassified file | 「種類を分けられなかったファイル」に触れた変更（{k} 件）は、何のファイルでしたか（決まりに入っていない拡張子のことがあります）。 |

## Alignment sections (`ALIGNMENT_TEXTS`)

| id | Verdict | Item | Printed text |
|---|---|---|---|
| `zero_note` | observed_zero | Once, at the top of the section | 0 件はこの記録に無いという意味です。その仕事をしたことがないという意味ではありません。 |
| `ask_zero_places` | observed_zero | Places, grouped in SURFACES order | {places}は、案件が求めていますが、この記録では 0 件です。このリポジトリの外（別のリポジトリ、非公開の仕事）でしていたかを聞いてください。 |
| `ask_zero_tests` | observed_zero | Test types, grouped | {types}はこの記録では 0 件です。書いたり直したりしたことがあるか、どの道具を使ったかを聞いてください。 |
| `ask_below_share` | outside_declared_range | Places and test types with a declared minimum share | {item}は、案件が{floor}を求めていて、この記録では{record}です（要望の範囲の外）。この記録の外での仕事と、案件での分担を聞いてください。 |
| `ask_outside_gap` | outside_declared_range | Gaps (median, 90th percentile; rounded up next to the bound) | {item}は、案件が {declared} 日以内を求めていて、この記録では {observed} 日です（要望の範囲の外）。どんな事情でその間隔になったかと、案件の進め方に合わせるときに何が必要かを聞いてください。 |
| `ask_outside_days` | outside_declared_range / observed_zero | Days with a change (zero days too) | 変更を出した日の数は、案件が 180 日のうち {declared} 日以上を求めていて、この記録では {observed} 日です（要望の範囲の外）。日数はまとめて出すか分けて出すかで変わります。どんな単位で変更を出してきたかを聞いてください。 |
| `ask_forge` | not_observed | Review records (forge) | レビューの記録（forge）はこの記録に入っていないため測れていません。レビューをどんな流れで受けてきたか（誰に、どのくらいの単位で）を聞いてください。 |
| `ask_not_observed` | not_observed | Anything else (role_lens is a display preset, so it gets no question) | {item}は、この記録からは測れませんでした（理由: {reason}）。直接聞いてください。 |
| `ask_other` | any | A verdict and axis with no row here (asked about, never dropped) | {item}はこの記録では「{state}」でした。直接聞いてください。 |
| `questions_not_shown` | — | The actor basis is not claimed (verified, public inferred, unconsented, unknown), or it is claimed without `subject.actor_consent` | 面談の問いは出していません。{reason}です。本人が名乗った ID（attribution_state = "claimed"）と、同意の記録（consent = "recorded-explicit-consent"）があるときだけ出します。 |
| `no_questions` | — | No question at all | 要望の範囲の外になった項目と、測れなかった項目はありません。 |
| `no_overlap` | overlap | No overlapping item | 要望と記録が重なっている項目はありません。 |
| `not_declared_gap` | not_declared | Gaps (the record, rounded up; no question) | {item}は、案件が書いていません。この記録では {observed} 日です。 |
| `not_declared_days` | not_declared | Days with a change | 変更を出した日の数は、案件が書いていません。この記録では 180 日のうち {observed} 日です。 |
| `header_request` | table | Left column header of the overlap table | 案件の要望 |
| `header_record` | table | Right column header of the overlap table | `{cid}` の記録 |
| `cell_own_count` | overlap | Record cell for a place (`cell_count` below 20) | 記録の変更 {n} 件のうち {c} 件 |
| `cell_count` | overlap | Count-only cell (denominator below 20 or unknown) | {c} 件 |
| `cell_place_floor` | overlap | Request cell for a place with a minimum share | {place}（その人の変更の {pct} 以上） |
| `cell_test_floor` | overlap | Request cell for a test type with a minimum share | {type}（テストのファイルを変えた変更の {pct} 以上） |
| `cell_days_min` | overlap | Request cell for days with a change | 変更を出した日の数が 180 日のうち {d} 日以上 |
| `cell_days` | overlap | Record cell for days and gaps (gaps rounded up) | {v} 日 |
| `cell_median_max` | overlap | Request cell for the median gap | 変更の間隔の真ん中の値が {d} 日以内 |
| `cell_p90_max` | overlap | Request cell for the 90th-percentile gap | 間隔を短い順に並べて 9 割のところが {d} 日以内 |
| `cell_input` | overlap | Request cell for a shared record | {input}を共有する |
| `cell_shared` | overlap | Record cell for a shared record | 共有されている |
| `floor_own` | outside_declared_range | Place floor inside `ask_below_share` | その人の変更の {pct} 以上 |
| `floor_tests` | outside_declared_range | Test-type floor inside `ask_below_share` | テストのファイルを変えた変更の {pct} 以上 |
| `record_own` | outside_declared_range | Place record inside `ask_below_share` (denominator of 20 or more) | 変更 {n} 件のうち {c} 件 |
| `record_tests` | overlap / outside_declared_range | Test-type record (denominator of 20 or more) | テストのファイルを変えた変更 {n} 件のうち {c} 件 |
| `record_own_count` | outside_declared_range | Place record (denominator below 20 or unknown) | 変更のうち {c} 件 |
| `record_tests_count` | outside_declared_range | Test-type record (denominator below 20 or unknown) | テストのファイルを変えた変更のうち {c} 件 |
| `record_own_share` | overlap / outside_declared_range | Place record with a declared minimum share, from a saved alignment without the actor's counts | 変更の {pct} |
| `record_tests_share` | overlap / outside_declared_range | The same, for a test type with a declared minimum share | テストのファイルを変えた変更の {pct} |

## Plain reasons (`PLAIN_REASONS`)

| id | Printed text |
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

## Why the section is not shown (`NOT_SHOWN`)

| id | Printed text |
|---|---|
| `admin_verified` | 管理者が登録した ID（attribution_state = "verified"）の記録のため |
| `public_inferred` | 公開リポジトリの記録から、名前とメールで同じ人と推定したまとまりのため |
| `explicit_nonconsent` | 同意の記録が無い ID の記録のため |
| `unknown` | 表示の根拠（selection と attribution_state）を確かめられないため |
| `no_consent` | 本人が名乗った ID ですが、同意の記録（consent）が無いため |
| `shallow_history` | 履歴が途中までしか無い記録（浅い clone）のため |

## How to read the numbers (`LIMIT_NOTES`)

| id | Printed text |
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

## Verdict names (inside `ask_other`) (`VERDICT_NAMES`)

| id | Printed text |
|---|---|
| `overlap` | 要望と重なる |
| `outside_declared_range` | 要望の範囲の外 |
| `observed_zero` | 0 件 |
| `not_observed` | 測れない |
| `not_declared` | 要望なし |

## Headings (`HEADINGS`)

| id | Printed text |
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

## Fixed sentences of the sections (`SECTION_TEXTS`)

| id | Printed text |
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

## Evidence table, what was counted (`EVIDENCE_ROWS`)

| id | Printed text |
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

## What the project declared (`DECLARED_TEXTS`)

| id | Printed text |
|---|---|
| `surfaces` | - 変えた部分の区分（作業領域）: {items} |
| `verification` | - テストの付け方（検証の形）: {items} |
| `active_days_180d_min` | - 変更を出した日の数: 180 日のうち {n} 日以上 |
| `median_gap_days_max` | - 変更の間隔の真ん中の値: {n} 日以内 |
| `p90_gap_days_max` | - 間隔を短い順に並べて 9 割のところ: {n} 日以内 |
| `inputs` | - 共有してほしい記録: {items} |
| `not_declared` | - 書いていないこと: {items} |
| `share_floor` | {name}（変更の {pct} 以上） |

## Names of the declared items (`DECLARED_ITEM_NAMES`)

| id | Printed text |
|---|---|
| `surfaces` | 変えた部分の区分（作業領域） |
| `verification` | テストの付け方（検証の形） |
| `active_days_180d_min` | 変更を出した日の数 |
| `median_gap_days_max` | 変更の間隔の真ん中の値 |
| `p90_gap_days_max` | 間隔を短い順に並べて 9 割のところ |
| `inputs` | 共有してほしい記録 |
| `role_lens` | 表示の型（role_lens） |
