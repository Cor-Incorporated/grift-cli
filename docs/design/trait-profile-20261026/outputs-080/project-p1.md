# TEP project レポート

## このレポートは誰・何を対象にしたか
- 案件の宣言（declared）と、Git から見た運用の形（observed）です。会社評価ではありません。
- project_id: payments-api-maintenance id

## 何を入力として見たか
- declared は案件所有者が書いた TOML です。CLI は空欄を埋めません。
- Git 履歴を観測した
- project の forge export は未提供（未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided）
- project の tracker export は未提供（未観測（not_observed。測定できなかった。実績がないことではない）理由: tracker_export_not_provided）

## 何を見ていないか
- 会社の良し悪し、採用判定、actor 個人の履歴はこのレポートの対象外です。
- forge/tracker を付けない限り、project の review / issue 運用は未観測です。

## 案件側の宣言
- 180 日活動日の下限: 20 days
- 間隔中央値の上限: 7 days
- 間隔 p90 の上限: 未宣言（not_declared。案件側が書いていない。不足ではない）理由: requirement_not_provided
- 必要な surface: backend, data, test surface-names
- 必要な verification: unit, integration verification-types
- 必要な入力: git, forge input-kinds

## 観測された数値
### 作業領域プロファイル（surface）
- 分類根拠: path_pattern_and_extension_heuristic（意味理解ではない）
- 曖昧 path 数: 131 件（複数パターンに当たった path）
- 未分類 path 数: 18 件（other）
- 分母: non-merge human commits that touched at least one path。母数=227
- test: 94 commits（その surface を1つ以上触った commit 数。入力=Git path）
- test files: 112 file-changes / unique=6 files
- docs: 20 commits（その surface を1つ以上触った commit 数。入力=Git path）
- docs files: 20 file-changes / unique=2 files
- ci_cd: 19 commits（その surface を1つ以上触った commit 数。入力=Git path）
- ci_cd files: 19 file-changes / unique=1 files
- platform: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- platform files: 0 file-changes / unique=0 files
- data: 19 commits（その surface を1つ以上触った commit 数。入力=Git path）
- data files: 19 file-changes / unique=19 files
- observability: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- observability files: 0 file-changes / unique=0 files
- frontend: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- frontend files: 0 file-changes / unique=0 files
- backend: 133 commits（その surface を1つ以上触った commit 数。入力=Git path）
- backend files: 152 file-changes / unique=7 files
- config: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- config files: 0 file-changes / unique=0 files
- generated_vendor: 0 commits（その surface を1つ以上触った commit 数。入力=Git path）
- generated_vendor files: 0 file-changes / unique=0 files
- other: 18 commits（その surface を1つ以上触った commit 数。入力=Git path）
- other files: 18 file-changes / unique=1 files
- ファイル比率: 観測あり（単位 ratio、n=36）（commit 比率とは別）
- 変更行: 観測あり（単位 lines、n=340）
- 比率: 観測あり（単位 ratio、n=227）。合計は 1 を超えてよい（1 commit が複数 surface）
- トップレベル module 数: 6 modules（母数 n=227）（名前は出さない）
### 変更提出の間隔（change rhythm）
- 時刻の根拠: git_author_timestamp
- 窓: observation_date=2026-10-20 から 180 日
- 窓内の commit 数: 106 commits（分母）
- 窓の外の履歴: 121 commits（統計に混ぜない）
- 180 日の活動日数: 106 days（母数 n=106）
- 間隔の中央値: 1.0465 days（母数 n=105）
- 間隔の p90: 3.0465 days（母数 n=105）
- 2 日以内の間隔の割合: 0.5905 ratio（母数 n=105）
- 30 日以上の間隔の割合: 0.0 ratio（母数 n=105）
- 間隔の標本数: 105 gaps
### 検証の観測（test path heuristic。QA 適性ではない）
- test だけを触った commit: 37 commits（母数 n=227）
- test を含む commit の割合: 0.4141 ratio（母数 n=227）
- fix/revert と test の同時変更: 0.6667 ratio（母数 n=57）
- test 種別 unit: 75 commits（path heuristic）
- test 種別 integration: 37 commits（path heuristic）
- test 種別 e2e: 0 commits（path heuristic）
- test 種別 contract: 0 commits（path heuristic）
- test 種別 unspecified: 0 commits（path heuristic）
### 調整の観測（Git / ローカル export。能力判定ではない）
- merge commit 数: 0 commits（PR review ではない）
- merge commit 割合: 0.0 ratio（母数 n=227）
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
- declared は要求です。observed は Git（と明示した local export）の観測です。混ぜません。

## 基準値・比較材料
- このレポートには外部基準値はありません。宣言を観測値で埋めません。

## 傾向
- 作業領域: data系surfaceが相対的に多い傾向
- 変更提出間隔: 定期的な変更提出の傾向が観測される

## 傾向の強さと確からしさ
- 作業領域: data系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.data observed=0.5278 n=340 denominator=distinct paths or file-changes in scoped commits window=2026-04-23〜2026-10-20 source=git:path
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- 変更提出間隔: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=106 denominator=180 window=2026-04-23〜2026-10-20 source=git:author_timestamp
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
- 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- このレポートだけで採用の合否を決めてはいけません。

## 再現情報
- 定義版: tep-v0.8.0-2026-10-25
- 入力ハッシュ: project=22174fa974bda5ce1fad753bb2f4cc251f3da72c8baef574b10f167c536752ac forge=None tracker=None
- Git window: 2026-04-23〜2026-10-20
