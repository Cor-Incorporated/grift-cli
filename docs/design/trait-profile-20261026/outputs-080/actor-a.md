# TEP 証拠レポート

## このレポートは誰・何を対象にしたか
- attribution_state=claimed と記録された identity に基づく本人向けactor観測。対象 canonical_id は `candidate-a`。CLI はその申告者、本人同意または本人性を証明しません。
- 観測日: 2026-10-20（窓の基準=explicit_as_of。explicit_as_of は --as-of、legacy_head_date は履歴 HEAD 日）

## 何を入力として見たか
- Git 履歴を入力として使った
- forge export は未提供（未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided）
- tracker export は未提供（未観測（not_observed。測定できなかった。実績がないことではない）理由: tracker_export_not_provided）
- GitHub / GitLab / tracker API には接続していません。
- 固定Git treeのルートlicense証跡: status=not_observed files=0 target=sha1:b2c5f307116c97ed2f12b737a6ff3df942d703df
- License証跡digest: `584e5d95b0e56d70e377d910814dd4921b30cafd8d21ee90b79bd4169957582d`（API termsとは別）

## 何を見ていないか
- 非公開の経歴、会議、レビューの質、労働時間は見えません。
- forge export が提供されていないため、review は観測できません。Git の merge commit 比率を pull request review とは呼びません。
- tracker export が提供されていないため、issue triage / milestone coordination は観測できません。これは活動が無かったことを意味しません。

## 観測された数値
- 表示プリセット未指定。下記の観測項目をすべて表示します。
### 作業領域プロファイル（surface）
- 分類根拠: path_pattern_and_extension_heuristic（意味理解ではない）
- 曖昧 path 数: 57 件（複数パターンに当たった path）
- 未分類 path 数: 7 件（other）
- 分母: non-merge human commits that touched at least one path。母数=97
- test: 43 commits（その surface を1つ以上触った commit 数。入力=Git path）
- test files: 50 file-changes / unique=16 files
- docs: 8 commits（その surface を1つ以上触った commit 数。入力=Git path）
- docs files: 8 file-changes / unique=2 files
- ci_cd: 7 commits（その surface を1つ以上触った commit 数。入力=Git path）
- ci_cd files: 7 file-changes / unique=1 files
- platform: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- platform files: 0 file-changes / unique=0 files
- data: 8 commits（その surface を1つ以上触った commit 数。入力=Git path）
- data files: 8 file-changes / unique=8 files
- observability: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- observability files: 0 file-changes / unique=0 files
- frontend: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- frontend files: 0 file-changes / unique=0 files
- backend: 61 commits（その surface を1つ以上触った commit 数。入力=Git path）
- backend files: 70 file-changes / unique=20 files
- config: 1 commits（その surface を1つ以上触った commit 数。入力=Git path）
- config files: 1 file-changes / unique=1 files
- generated_vendor: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- generated_vendor files: 0 file-changes / unique=0 files
- other: 7 commits（その surface を1つ以上触った commit 数。入力=Git path）
- other files: 7 file-changes / unique=1 files
- ファイル比率: 観測あり（単位 ratio、n=49）（commit 比率とは別）
- 変更行: 観測あり（単位 lines、n=151）
- 比率: 観測あり（単位 ratio、n=97）。合計は 1 を超えてよい（1 commit が複数 surface）
- トップレベル module 数: 6 modules（母数 n=97）（名前は出さない）
### 変更提出の間隔（change rhythm）
- 時刻の根拠: git_author_timestamp
- 窓: observation_date=2026-10-20 から 180 日
- 窓内の commit 数: 70 commits（分母）
- 窓の外の履歴: 27 commits（統計に混ぜない）
- 180 日の活動日数: 69 days（母数 n=70）
- 間隔の中央値: 2.0465 days（母数 n=69）
- 間隔の p90: 4.0661 days（母数 n=69）
- 2 日以内の間隔の割合: 0.2609 ratio（母数 n=69）
- 30 日以上の間隔の割合: 0.0 ratio（母数 n=69）
- 間隔の標本数: 69 gaps
### 検証の観測（test path heuristic。QA 適性ではない）
- test だけを触った commit: 15 commits（母数 n=97）
- test を含む commit の割合: 0.4433 ratio（母数 n=97）
- fix/revert と test の同時変更: 0.7083 ratio（母数 n=24）
- test 種別 unit: 35 commits（path heuristic）
- test 種別 integration: 15 commits（path heuristic）
- test 種別 e2e: 0 commits（path heuristic）
- test 種別 contract: 0 commits（path heuristic）
- test 種別 unspecified: 0 commits（path heuristic）
### 調整の観測（Git / ローカル export。能力判定ではない）
- merge commit 数: 3 commits（PR review ではない）
- merge commit 割合: 0.03 ratio（母数 n=100）
- commit 件名の issue link: 0 commits（heuristic）
- review: 未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided
- tracker: 未観測（not_observed。測定できなかった。実績がないことではない）理由: tracker_export_not_provided
### イベント観測（bound forge / GH Archive。能力判定ではない）
- 未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided
### イベント間隔（観測ラベル。速度・生産性ではない）
- 未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided
### Tracker lifecycle
- 未観測（not_observed。測定できなかった。実績がないことではない）理由: tracker_export_not_provided

### 数値の読み方（単位・分母・母数）
- 件数の単位は commits / days / events です。比率は 0〜1 で、分母（n=）を併記します。
- 0 件は「この範囲で該当証拠が無かった」です。未観測（not_observed）は「測れなかった」です。
- surface の分母は、merge を除く人間 commit のうち path が取れたものです。
- rhythm の分母は observation_date から 180 日以内の Git author timestamp です。

## 基準値・比較材料
- このレポートには外部基準値はありません。観測値を基準値で置き換えていません。

## 傾向
- 作業領域: backend系surfaceが相対的に多い傾向
- 変更提出間隔: 定期的な変更提出の傾向が観測される

## 傾向の強さと確からしさ
- 作業領域: backend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.backend observed=0.4082 n=151 denominator=distinct paths or file-changes in scoped commits window=2026-04-23〜2026-10-20 source=git:path
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- 変更提出間隔: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=2.0465 n=70 denominator=180 window=2026-04-23〜2026-10-20 source=git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。

## 比較不能・未観測・未証明
- forge: 未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided
- tracker: 未観測（not_observed。測定できなかった。実績がないことではない）理由: tracker_export_not_provided
- window_alignment: 未観測（not_observed。測定できなかった。実績がないことではない）理由: event_window_not_provided
- event_window: 未観測（not_observed。測定できなかった。実績がないことではない）理由: bound_export_not_provided
- tracker_window: 未観測（not_observed。測定できなかった。実績がないことではない）理由: tracker_export_not_provided

## 言えること / 言えないこと
- この数値は、過去の Git / ローカル export に残った変更の形を示します。人の優劣、職種の確定、採用の合否、将来の成果を示すものではありません。
- これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。
- これは変更提出の時系列であり、実際の労働時間、勤怠、能力、納期遵守を測るものではありません。
- gap / median / p90 / burst / long-gap は observation_date から遡る 180 日窓内の Git author timestamp だけを母集団にする。窓の外側の履歴は混ぜない。
- squash・rebase・author timestamp の書き換え・bot・timezone の違いで間隔は変わります。squash 前後の commit 数の差を速度の変化とは呼びません。
- 活動日数（active days）は author 日付の一意な日数です。毎日 1 件の小さな commit を置けば増え、同じ変更を 1 日にまとめると減ります。変更の量や中身は見ておらず、補正もしません。
- 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- この表示は、指定された1つの canonical_id に帰属した履歴だけを対象にした本人向け証拠ビューです。未観測は、実績がないことを意味しません。
- この表示は attribution_state=claimed と記録された identity による actor 観測です。CLI はその申告者、本人同意または本人性を証明しません。
- This report covers one repository that the provider chose to share. It does not show whether other repositories exist or what they would show.
- forge export が提供されていないため、review は観測できません。Git の merge commit 比率を pull request review とは呼びません。
- tracker export が提供されていないため、issue triage / milestone coordination は観測できません。これは活動が無かったことを意味しません。

## 再現情報
- 分析 SHA: `b2c5f307116c97ed2f12b737a6ff3df942d703df`
- 定義版: tep-v0.8.0-2026-10-25
- 分析範囲(machine): tenant（tenant=verified/claimed identity、actor_cluster=repo-local Git cluster。どちらも表示basis・本人同意・本人性を単独では証明しません）
- identity の要約ハッシュ: 315ae3360c09fb5fd5f6ce635117320ad10d24774872156d2d46a2d0a015207d（生メールは含みません）
- 入力ハッシュ: forge=None tracker=None license=584e5d95b0e56d70e377d910814dd4921b30cafd8d21ee90b79bd4169957582d
- Git window: 2026-04-23〜2026-10-20
- Forge/Tracker window: 未観測（not_observed。測定できなかった。実績がないことではない）理由: bound_export_not_provided
