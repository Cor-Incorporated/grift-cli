"""Decision tables for the plain trait sentences and interview questions.

ADR-0002 T6: the sentences and questions are picked from report numbers by
these tables, never by an LLM. The same tables are published in
docs/trait-profile.md and docs/en/trait-profile.md, and
tests/test_v090_trait_tables.py reads both documents and compares them with the
constants here, both ways. Changing a table means changing both documents and
raising DEFINITION_VERSION in the release commit.

Nothing here reaches JSON (T4): the text exists only in Markdown and can be
rebuilt from the JSON numbers with these tables.
"""

from __future__ import annotations

from tep_core.v2_constants import MIN_POPULATION_FOR_RATES

# The rhythm lead sentence is the only place a boundary picks the wording.
# 7 days and a half are reading aids, not validated values (design §7).
THRESHOLDS: dict[str, float] = {
    "min_population": MIN_POPULATION_FOR_RATES,
    "steady_p90_max_days": 7,
    "burst_share_min": 0.5,
    "max_following_places": 4,
    "max_questions": 4,
}

# Plain names, in SURFACES and VERIFICATION_TYPES order (design §5).
PLACE_NAMES: dict[str, str] = {
    "test": "テスト",
    "docs": "文書",
    "ci_cd": "自動テストと配布の設定",
    "platform": "実行環境の設定",
    "data": "データベースの定義",
    "observability": "監視とログ",
    "frontend": "画面",
    "backend": "サーバー側の処理",
    "config": "設定ファイル",
    "generated_vendor": "自動生成・外部から取り込んだコード",
    "other": "種類を分けられなかったファイル",
}
TEST_TYPE_NAMES: dict[str, str] = {
    "unit": "部品ごとに確かめる単体テスト",
    "integration": "組み合わせて動かす結合テスト",
    "e2e": "画面から通しで動かす E2E テスト",
    "contract": "外部との約束事を確かめる契約テスト",
    "unspecified": "種類を判別できないテスト",
}
TEST_TYPE_SHORT_NAMES: dict[str, str] = {
    "unit": "単体テスト",
    "integration": "結合テスト",
    "e2e": "E2E テスト",
    "contract": "契約テスト",
    "unspecified": "種類を判別できないテスト",
}
INPUT_NAMES: dict[str, str] = {
    "git": "git の記録",
    "forge": "レビューの記録（forge）",
    "tracker": "課題管理の記録（tracker）",
}
RHYTHM_ITEM_NAMES: dict[str, str] = {
    "active_days_180d": "変更を出した日の数",
    "median_gap_days": "変更の間隔の真ん中の値",
    "p90_gap_days": "間隔を短い順に並べて 9 割のところ",
}

# Sentences for one scope's own work: the actor report (claimed with a consent
# record) and the project repository.
SENTENCES: dict[str, str] = {
    "place_lead": "いちばん多いのは{place}で、{scope} {n} 件のうち {c} 件です。",
    "place_lead_tie": "いちばん多いのは次の場所で、{scope} {n} 件のうち、それぞれ {c} 件です（{places}）。",
    "place_following": "次いで、{items}にも触れています。",
    "place_few": "{scope}が 20 件に届かないため、この観点の文は出していません（{n} 件）。",
    "place_not_observed": "触った場所は、この記録からは測れませんでした（理由: {reason}）。",
    "place_tests_only": "{scope} {n} 件はどれもテストのファイルの変更でした。テストは「テストの付け方」で数えています。",
    "rhythm_steady": "間をあまり空けずに出す進め方です。",
    "rhythm_bursty": "続けて出す時期と、長く空く時期がある進め方です。",
    "rhythm_detail": (
        "変更と変更の間隔は、真ん中の値が {median} 日、短い順に並べて 9 割のところが {p90} 日でした。"
        "間隔 {n} 回のうち、2 日以内が {burst} 回、30 日以上が {long} 回です。"
    ),
    "rhythm_few": "変更と変更の間隔が 20 回に届かないため、この観点の文は出していません（{n} 回）。",
    "rhythm_not_observed": "変更の間隔は、この記録からは測れませんでした（理由: {reason}）。",
    "verify_lead": "テストのファイルも一緒に変えた変更が、{n} 件のうち {c} 件あります。",
    "verify_types": "テストの種類は{types}です。",
    "verify_fix_paired": "直し（fix）の変更 {s} 件のうち {w} 件で、テストも一緒に変えています。",
    "verify_fix_few": (
        "直し（fix）の変更は {s} 件で、20 件に届かないため、テストとの組み合わせは数えていません。"
    ),
    "verify_not_observed": (
        "テストの記録は、この記録からは測れませんでした（理由: {reason}）。"
        "テストを書いていないという意味ではありません。"
    ),
    "work_modify_more": (
        "すでにあるファイルに手を入れる変更（{m} 件）のほうが、"
        "新しいファイルを作る変更（{c} 件）より多い進め方です。"
    ),
    "work_create_more": (
        "新しいファイルを作る変更（{c} 件）のほうが、"
        "すでにあるファイルに手を入れる変更（{m} 件）より多い進め方です。"
    ),
    "work_equal": (
        "新しいファイルを作る変更と、すでにあるファイルに手を入れる変更が、どちらも {c} 件です。"
    ),
    "work_process": "ほかの作業の取り込み（merge）を {i} 回、リリースの印（タグ）付けを {r} 回しています。",
    "work_merge_only": "ほかの作業の取り込み（merge）を {i} 回しています。",
    "work_release_only": "リリースの印（タグ）付けを {r} 回しています。",
    "work_few": "自分の変更が 20 件に届かないため、この観点の文は出していません（{n} 件）。",
    "work_not_observed": "関わり方は、この記録からは数えていません（理由: {reason}）。",
    "work_scope_differs": (
        "関わり方の数は、この節のほかの観点と数えた変更が違うため、この観点の文は出していません"
        "（この数え方では {n} 件、ほかの観点では {total} 件）。"
    ),
    "work_scope_later": (
        "関わり方の数は、観測日のあとの変更も含めて数えていて、この節のほかの観点と数えた変更が"
        "違うため、この観点の文は出していません（この数え方では {n} 件、観測日までは {total} 件）。"
    ),
}

# Interview questions in the actor report: in table order, at most
# max_questions; rows that share an order are exclusive.
QUESTIONS: dict[str, str] = {
    "ask_outside": (
        "{place}のほかに、この記録の外でしている仕事はありますか"
        "（別のリポジトリ、非公開の仕事、設計や運用など）。"
    ),
    "ask_outside_plain": (
        "この記録の外でしている仕事はありますか（別のリポジトリ、非公開の仕事、設計や運用など）。"
    ),
    "ask_rhythm_steady": "細かく分けて変更を出すのは、チームの決まりですか。自分のやり方ですか。",
    "ask_rhythm_bursty": "続けて出す時期と、長く空く時期は、それぞれどんな仕事の区切りでしたか。",
    "ask_fix_without_test": "直しの変更 {s} 件のうち、テストを変えなかった {u} 件はどんな場面でしたか。",
    "ask_test_type": "{type}（{c} 件）はどんな場面で書いていますか。",
    "ask_release": "リリースの印付け（{r} 回）はどこまで任されていましたか。",
    "ask_unclassified": (
        "「種類を分けられなかったファイル」に触れた変更（{k} 件）は、何のファイルでしたか"
        "（決まりに入っていない拡張子のことがあります）。"
    ),
}

# The alignment sections. Verdicts come from alignment-v1 (ADR-0001 R5); a
# question never repeats a trait sentence. Questions follow T7 like the actor
# report: a claimed identity with the consent record (subject.actor_consent).
ALIGNMENT_TEXTS: dict[str, str] = {
    "zero_note": (
        "0 件はこの記録に無いという意味です。その仕事をしたことがないという意味ではありません。"
    ),
    "ask_zero_places": (
        "{places}は、案件が求めていますが、この記録では 0 件です。"
        "このリポジトリの外（別のリポジトリ、非公開の仕事）でしていたかを聞いてください。"
    ),
    "ask_zero_tests": (
        "{types}はこの記録では 0 件です。"
        "書いたり直したりしたことがあるか、どの道具を使ったかを聞いてください。"
    ),
    "ask_below_share": (
        "{item}は、案件が{floor}を求めていて、この記録では{record}です（要望の範囲の外）。"
        "この記録の外での仕事と、案件での分担を聞いてください。"
    ),
    "ask_outside_gap": (
        "{item}は、案件が {declared} 日以内を求めていて、この記録では {observed} 日です（要望の範囲の外）。"
        "どんな事情でその間隔になったかと、案件の進め方に合わせるときに何が必要かを聞いてください。"
    ),
    "ask_outside_days": (
        "変更を出した日の数は、案件が 180 日のうち {declared} 日以上を求めていて、"
        "この記録では {observed} 日です（要望の範囲の外）。日数はまとめて出すか分けて出すかで変わります。"
        "どんな単位で変更を出してきたかを聞いてください。"
    ),
    "ask_forge": (
        "レビューの記録（forge）はこの記録に入っていないため測れていません。"
        "レビューをどんな流れで受けてきたか（誰に、どのくらいの単位で）を聞いてください。"
    ),
    "ask_not_observed": (
        "{item}は、この記録からは測れませんでした（理由: {reason}）。直接聞いてください。"
    ),
    "ask_other": "{item}はこの記録では「{state}」でした。直接聞いてください。",
    "questions_not_shown": (
        "面談の問いは出していません。{reason}です。"
        '本人が名乗った ID（attribution_state = "claimed"）と、'
        '同意の記録（consent = "recorded-explicit-consent"）があるときだけ出します。'
    ),
    "no_questions": "要望の範囲の外になった項目と、測れなかった項目はありません。",
    "no_overlap": "要望と記録が重なっている項目はありません。",
    "not_declared_gap": "{item}は、案件が書いていません。この記録では {observed} 日です。",
    "not_declared_days": "変更を出した日の数は、案件が書いていません。この記録では 180 日のうち {observed} 日です。",
    "header_request": "案件の要望",
    "header_record": "`{cid}` の記録",
    "cell_own_count": "記録の変更 {n} 件のうち {c} 件",
    "cell_count": "{c} 件",
    "cell_place_floor": "{place}（その人の変更の {pct} 以上）",
    "cell_test_floor": "{type}（テストのファイルを変えた変更の {pct} 以上）",
    "cell_days_min": "変更を出した日の数が 180 日のうち {d} 日以上",
    "cell_days": "{v} 日",
    "cell_median_max": "変更の間隔の真ん中の値が {d} 日以内",
    "cell_p90_max": "間隔を短い順に並べて 9 割のところが {d} 日以内",
    "cell_input": "{input}を共有する",
    "cell_shared": "共有されている",
    "floor_own": "その人の変更の {pct} 以上",
    "floor_tests": "テストのファイルを変えた変更の {pct} 以上",
    "record_own": "変更 {n} 件のうち {c} 件",
    "record_tests": "テストのファイルを変えた変更 {n} 件のうち {c} 件",
    "record_own_count": "変更のうち {c} 件",
    "record_tests_count": "テストのファイルを変えた変更のうち {c} 件",
    "record_own_share": "変更の {pct}",
    "record_tests_share": "テストのファイルを変えた変更の {pct}",
}

# Plain reasons for not_observed nodes, one row for every reason the producers
# emit (tests/test_v090_trait_tables.py scans them). An unknown reason prints
# PLAIN_REASON_FALLBACK, never the bare internal name.
PLAIN_REASONS: dict[str, str] = {
    "insufficient_population": "数が 20 に届かないため",
    "no_commits_in_window": "数えた 180 日のあいだに変更が無いため",
    "no_gaps": "変更と変更の間隔が無いため",
    "no_human_commits": "人の変更が無いため",
    "no_actor_commits": "この人の変更が無いため",
    "commit_paths_unavailable": "変更したファイルの置き場所が取れなかったため",
    "numstat_unavailable": "変更した行の数が取れなかったため",
    "no_test_framework_or_directory": "テストの仕組みやテストの置き場所が見つからなかったため",
    "no_test_touching_commits": "テストのファイルを変えた変更が無いため",
    "no_fix_or_revert_commits": "直し（fix・revert）の変更が無いため",
    "no_production_commits": "本番のコードを変えた変更が無いため",
    "consenting_actor_required": "同意の記録が無いため",
    "history_incomplete": "履歴か Git のデータの一部が手元に無いため（浅い clone、部分 clone など）",
    "experience_collection_timeout": "履歴を読む時間の上限を超えたため",
    "pending_attribution": "誰の変更かがまだ決まっていないため",
    "head_date_unavailable": "最後の変更の日付が取れなかったため",
    "forge_export_not_provided": "レビューの記録のファイルを渡していないため",
    "tracker_export_not_provided": "課題管理の記録のファイルを渡していないため",
    "bound_export_not_provided": "書き出した記録のファイルを渡していないため",
    "event_window_not_provided": "イベントを数える期間を渡していないため",
    "public_evidence_not_provided": "公開の記録を取りに行っていないため",
    "provider_api_terms_not_recorded": "公開の記録の利用条件が記録されていないため",
    "tracker_timestamps_missing": "課題管理の記録に時刻が無いため",
    "archive_events_have_no_actor_identity": "公開イベントの記録に、人との対応が無いため",
    "synthetic_contract_not_actor_evidence": "試験用の合成データで、人の記録ではないため",
    "dependency_scan_not_provided": "依存の読み取りをしていないため",
    "repository_not_provided": "リポジトリを渡していないため",
    "project_report_not_provided": "案件のレポートを渡していないため",
    "project_observed_not_provided": "案件のリポジトリの記録を渡していないため",
    "axis_not_in_project_observed": "案件のリポジトリの記録にこの項目が無いため",
    "requirement_not_provided": "案件側が書いていないため",
    "not_declared": "案件側が書いていないため",
    "role_lens_not_set": "表示の型を指定していないため",
    "share_not_observed": "割合が出ていないため",
    "observed_unavailable": "比べる値が出ていないため",
    "not_observed": "測れなかったため",
    "n_missing": "母数が無いため",
    "unit_mismatch": "単位が違うため",
    "non_scalar_observed": "1 つの数で表せない値のため",
    "windows_not_equivalent": "数えた期間が違うため",
    "window_too_short_for_shape": "数えた期間が短いため",
    "no_surface_share": "場所の割合が無いため",
    "tied_top_share": "割合がいちばん大きい場所が 2 つ以上あるため",
    "no_tendency_for_axis": "この項目には傾向を出さないため",
}
PLAIN_REASON_FALLBACK = "この記録の数え方では測れないため（記録の上の理由は `{reason}`）"

# Why the person-facing section is not shown (T7), by actor basis.
NOT_SHOWN: dict[str, str] = {
    "admin_verified": '管理者が登録した ID（attribution_state = "verified"）の記録のため',
    "public_inferred": "公開リポジトリの記録から、名前とメールで同じ人と推定したまとまりのため",
    "explicit_nonconsent": "同意の記録が無い ID の記録のため",
    "unknown": "表示の根拠（selection と attribution_state）を確かめられないため",
    "no_consent": "本人が名乗った ID ですが、同意の記録（consent）が無いため",
    "shallow_history": "履歴が途中までしか無い記録（浅い clone）のため",
}
NOT_SHOWN_TEMPLATE = (
    "この節の文は出していません。{reason}です。"
    '本人が名乗った ID（attribution_state = "claimed"）と、'
    '同意の記録（consent = "recorded-explicit-consent"）があるときだけ出します。'
)
# A shallow clone is not a consent question: its oldest fetched commit reads
# as adding every file, so the places and the gaps are not the person's.
NOT_SHOWN_SHALLOW_TEMPLATE = (
    "この節の文は出していません。{reason}です。"
    "浅い clone では、いちばん古い変更がすべてのファイルを足したように数えられ、"
    "場所や間隔の数が全履歴と変わります。`git fetch --unshallow` で全履歴を取ってから実行すると出します。"
)

# Fixed notes under 「数字の読み方と限界」. Not selected by numbers, but the
# vocabulary gates read them like every template.
LIMIT_NOTES: dict[str, str] = {
    "places": (
        "場所はファイルの置き場所と拡張子の決まりで分けています。中身は読んでいません。"
        "1 件の変更が 2 つ以上の場所に入ることがあります。"
    ),
    "rhythm": "間隔は小さく分けて毎日出せば短くなり、まとめて出せば長くなります。補正はしていません。",
    "tests": (
        "テストはテストのファイルに 1 行足すだけでも「一緒に変えた」に数えます。"
        "変えた行の中身は見ていません。"
    ),
    "own_work": (
        "「多い」はこの記録の変更の中で多いという意味です。ほかの人やほかのリポジトリとは比べていません。"
    ),
    "overlap": (
        "「重なっている」は、要望の場所や種類の変更が記録に 1 件以上あるという意味です。"
        "どれだけ慣れているかは示しません。"
    ),
    "days": (
        "変更を出した日の数は小さく分けて毎日出せば増え、まとめて出せば減ります。"
        "要望の日数は量の線で、補正はしていません。"
    ),
    "scales": (
        "1 人の記録と案件のリポジトリの件数は、同じ物差しではありません。"
        "件数どうしを割り算した比べ方はしていません。"
    ),
    "verify": "数字は JSON の値から作っています。JSON は `grift verify` で検算できます。この Markdown は検算の対象外です。",
    # Alignment only: `grift report <alignment.json>` re-renders the saved file
    # and checks nothing, so the consent behind the questions is the file's word.
    "consent": (
        "面談の問いを出すかどうかは、JSON に書かれた actor の選び方・ID の種類・同意の記録"
        "（`subject.actor_selection`・`subject.actor_attribution_state`・`subject.actor_consent`）"
        "で決めています。保存した JSON から描き直したとき（`grift report`）は、これを確かめていません。"
        "照らし合わせの JSON は `grift verify` で確かめます。保存した actor の report から作った"
        "照らし合わせでは、`grift verify` は渡した actor の report を信じて作り直すので、actor の report も"
        " `grift verify actor-report.json --repo REPO --identity IDENTITY` で確かめます。"
    ),
    "p90": (
        "間隔を短い順に並べたときの 9 割の位置の値を「9 割のところ」と書いています"
        "（前後の 2 つの値のあいだを按分します）。"
    ),
    "gap_rounding": (
        "この節の間隔の日数は上限と並べたときに判定と食い違わないよう、すべて小数 1 桁に切り上げています。"
    ),
    "shallow_repo": (
        "浅い clone のリポジトリでは、取得できた変更だけを数えます。いちばん古い変更は"
        "すべてのファイルを足したように数えられます。project の JSON には浅い clone かどうかが入っていません。"
    ),
    # 0.9.1 J3: project-v1 records `provenance.revision_completeness`. `shallow_repo`
    # stays for a project report saved before it (no key, so unknown).
    "shallow_repo_recorded": (
        "このリポジトリは浅い clone なので、取得できた変更だけを数えます。いちばん古い変更は"
        "すべてのファイルを足したように数えられます。`git fetch --unshallow` で残りの履歴を取ると、"
        "取得できなかった変更も数えます。"
    ),
}

# Headings and the fixed sentences around the tables. The vocabulary gates
# read them like the templates above.
HEADINGS: dict[str, str] = {
    "actor_title": "# `{cid}` の記録から見える進め方",
    "project_title": "# 案件「{title}」の要望と記録",
    "project_title_untitled": "# 案件の要望と記録",
    "alignment_title": "# `{cid}` の記録と、案件「{title}」の照らし合わせ",
    "alignment_title_untitled": "# `{cid}` の記録と、案件の照らし合わせ",
    "work": "## 進め方",
    "places": "### 変えた部分の区分（作業領域）",
    "rhythm": "### 変更のペース（変更リズム）",
    "verify": "### テストの付け方（検証の形）",
    "make": "### 関わり方",
    "unseen": "## この記録では見えないこと",
    "questions": "## 面談で確かめたいこと",
    "limits": "## 数字の読み方と限界",
    "evidence": "## 根拠",
    "declared": "## 案件側が書いた要望",
    "repository": "## 案件のリポジトリから見える進め方",
    "overlap": "## 要望と記録が重なっている点",
    "align_questions": "## 面談で確かめたい点",
    "not_declared": "## 案件側が書いていないこと（参考）",
}
SECTION_TEXTS: dict[str, str] = {
    "actor_intro": (
        "`{cid}` が共有した 1 つのリポジトリの git の記録を、仕事の言葉に直しました。"
        "本人が名乗った ID と同意の記録があるので、この節を出しています。点数・順位・合否は出しません。"
    ),
    "record_scope": "- 数えた範囲: {end} までの全履歴（自分の変更 {total} 件）",
    "record_scope_paths": (
        "- 数えた範囲: {end} までの全履歴（自分の変更 {total} 件。"
        "ファイルを変えた変更は {paths} 件で、変えた部分の区分はこの {paths} 件で数えています）"
    ),
    "rhythm_period": "- 間隔を数えた期間: {start}〜{end} の {days} 日（この間の変更 {n} 件）",
    "project_intro": (
        "案件側が書いた要望（宣言）と、案件側のリポジトリの git の記録を、別の節に分けて並べます。"
        "会社や案件の良し悪しは出しません。"
    ),
    "project_people": "人ごとの数字は出しません。",
    "project_no_repository": (
        "案件のリポジトリの記録を渡していないので、この節の文は出していません。"
        "`grift project REPO` で記録を足せます。"
    ),
    "declared_note": "書いていない項目は、要望が無いという意味です。不足として扱いません。",
    "alignment_intro": (
        "案件の要望と、`{cid}` の記録を項目ごとに並べました。点数と、重なった項目の数は出しません。"
    ),
    "unseen_both": "レビューのやり方と課題の管理は入っていません。レビューと課題管理の記録のファイルを渡していないためです。",
    "unseen_forge": "レビューのやり方は入っていません。レビューの記録のファイルを渡していないためです。",
    "unseen_tracker": "課題の管理は入っていません。課題管理の記録のファイルを渡していないためです。",
    "unseen_always": "設計や会議の進め方は、git の記録には残りません。",
    "unseen_zero_places": (
        "ここに出ていない場所（{places}）は 0 件でした。"
        "この記録に無いという意味で、その仕事をしたことがないという意味ではありません。"
    ),
    "unseen_zero_places_repo": (
        "このリポジトリに無い場所（{places}）は 0 件でした。"
        "案件にその仕事が無いという意味ではありません（別のリポジトリで扱っていることがあります）。"
    ),
    "unseen_no_release": (
        "リリースの印（タグ）を付けた記録はありません。リリースを誰が担当していたかは、この記録からは分かりません。"
    ),
    "unseen_other_repos": "案件で使っているほかのリポジトリがあるかは、この記録からは分かりません。",
    "history": "{end} までの全履歴",
    "history_repo": "{end} までの履歴",
    "window": "{start}〜{end}",
    "count_of": "{n} 件中 {c} 件",
    "gaps_of": "間隔 {n} 回中 {c} 回",
    "days_with_gaps": "{days} 日（間隔 {n} 回）",
    "count_list": "{n} 件中 {values}",
    "count_unit": "{c} 件",
    "count_times": "{c} 回",
    "overlapping_counts": "（1 件が両方に入ることがあります）",
    "same_period": "同上",
    "col_aspect": "観点",
    "col_counted": "数えたもの",
    "col_value": "件数",
    "col_period": "期間",
}
# Rows of the 「根拠」 table: (aspect, what was counted). The counts and the
# period are filled from the JSON values the sentences used.
EVIDENCE_ROWS: dict[str, str] = {
    "place_top": "{place}に触れた変更",
    "place_rest": "{places}に触れた変更",
    "rhythm_median": "変更と変更の間隔の真ん中の値",
    "rhythm_p90": "間隔を短い順に並べて 9 割のところ",
    "rhythm_long": "30 日以上空いた間隔",
    "verify_touch": "テストのファイルも変えた変更",
    "verify_types": "{types}のファイルを変えた変更",
    "verify_fix": "直し（fix・revert）の変更のうち、テストも変えたもの",
    "work_modify_create": "手を入れる変更 / 新しく作る変更",
    "work_merges": "取り込み（merge）",
    "work_releases": "リリースの印（タグ）",
}

# What the project side declared, in plain words (project-v1 `declared`).
DECLARED_TEXTS: dict[str, str] = {
    "surfaces": "- 変えた部分の区分（作業領域）: {items}",
    "verification": "- テストの付け方（検証の形）: {items}",
    "active_days_180d_min": "- 変更を出した日の数: 180 日のうち {n} 日以上",
    "median_gap_days_max": "- 変更の間隔の真ん中の値: {n} 日以内",
    "p90_gap_days_max": "- 間隔を短い順に並べて 9 割のところ: {n} 日以内",
    "inputs": "- 共有してほしい記録: {items}",
    "not_declared": "- 書いていないこと: {items}",
    "share_floor": "{name}（変更の {pct} 以上）",
}
DECLARED_ITEM_NAMES: dict[str, str] = {
    "surfaces": "変えた部分の区分（作業領域）",
    "verification": "テストの付け方（検証の形）",
    "active_days_180d_min": "変更を出した日の数",
    "median_gap_days_max": "変更の間隔の真ん中の値",
    "p90_gap_days_max": "間隔を短い順に並べて 9 割のところ",
    "inputs": "共有してほしい記録",
    "role_lens": "表示の型（role_lens）",
}

# Plain names for the alignment verdicts, used only by `ask_other`.
VERDICT_NAMES: dict[str, str] = {
    "overlap": "要望と重なる",
    "outside_declared_range": "要望の範囲の外",
    "observed_zero": "0 件",
    "not_observed": "測れない",
    "not_declared": "要望なし",
}
