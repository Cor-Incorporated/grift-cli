# TEP alignment レポート

## このレポートは誰・何を対象にしたか
- attribution_state=claimed と記録された identity に基づく本人向けactor観測（actor `candidate-a`）と案件宣言（project `payments-api-maintenance`）の軸ごとの並びです。
- actor repo SHA: `b2c5f307116c97ed2f12b737a6ff3df942d703df`
- project repo SHA: `005ce05ea3cafff383fdd35745e9de0c8fc0d20f`
- 案件側の宣言と観測証拠の重なりを軸ごとに表示しています。全体の点数や順位は計算していません。

## 何を入力として見たか
- actor observed は actor レポートの観測です。project observed は対象リポジトリの運用観測です。
- declared は project TOML です。観測と混ぜません。

## 何を見ていないか
- 総合点、順位、適合率、採用推奨は計算していません。
- Git-only では review / issue triage / stakeholder 活動は未観測です。

## 案件側の宣言
- surfaces: backend, data, test surface-names
- verification: unit, integration verification-types
- inputs: git, forge input-kinds

## 観測された数値 / 軸ごとの並び
- change_rhythm.active_days_180d: 重なり（観測が宣言範囲・要求と重なる）。actor観測=69 days（母数 n=70） / project実測=106 days（母数 n=106） / 宣言=20 days。actor_n=70 project_n=106 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.change_rhythm.active_days_180d, project.declared.requirements.change_rhythm.active_days_180d_min
- change_rhythm.median_gap_days: 重なり（観測が宣言範囲・要求と重なる）。actor観測=2.0465 days（母数 n=69） / project実測=1.0465 days（母数 n=105） / 宣言=7 days。actor_n=69 project_n=105 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.change_rhythm.median_gap_days, project.declared.requirements.change_rhythm.median_gap_days_max
- change_rhythm.p90_gap_days: 案件側に要求がない（不足ではない）。actor観測=4.0661 days（母数 n=69） / project実測=3.0465 days（母数 n=105） / 宣言=未宣言（not_declared。案件側が書いていない。不足ではない）理由: requirement_not_provided。actor_n=69 project_n=105 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.change_rhythm.p90_gap_days, project.declared.requirements.change_rhythm.p90_gap_days_max
- surfaces.backend: 重なり（観測が宣言範囲・要求と重なる）。actor観測=61 commits / project実測=133 commits / 宣言=backend surface。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.surface_profile.surface_commit_counts.backend, project.declared.requirements.surfaces
- surfaces.data: 重なり（観測が宣言範囲・要求と重なる）。actor観測=8 commits / project実測=19 commits / 宣言=data surface。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.surface_profile.surface_commit_counts.data, project.declared.requirements.surfaces
- surfaces.test: 重なり（観測が宣言範囲・要求と重なる）。actor観測=43 commits / project実測=94 commits / 宣言=test surface。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.surface_profile.surface_commit_counts.test, project.declared.requirements.surfaces
- verification.unit: 重なり（観測が宣言範囲・要求と重なる）。actor観測=35 commits / project実測=75 commits / 宣言=unit surface。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.verification_profile.test_type_distribution.unit, project.declared.requirements.verification
- verification.integration: 重なり（観測が宣言範囲・要求と重なる）。actor観測=15 commits / project実測=37 commits / 宣言=integration surface。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.verification_profile.test_type_distribution.integration, project.declared.requirements.verification
- inputs.git: 重なり（観測が宣言範囲・要求と重なる）。actor観測=True boolean / project実測=True boolean / 宣言=git input。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.input_coverage.git, project.declared.requirements.inputs
- inputs.forge: 比較不能・未観測（実績がないことではない）。actor観測=未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided / project実測=未観測（not_observed。測定できなかった。実績がないことではない）理由: forge_export_not_provided / 宣言=forge input。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=partial。比較不能=observed_unavailable。根拠=actor.input_coverage.forge, project.declared.requirements.inputs
- role_lens: 案件側に要求がない（不足ではない）。actor観測=未観測（not_observed。測定できなかった。実績がないことではない）理由: role_lens_not_set / project実測=未観測（not_observed。測定できなかった。実績がないことではない）理由: axis_not_in_project_observed / 宣言=未宣言（not_declared。案件側が書いていない。不足ではない）理由: requirement_not_provided。actor_n=97 project_n=227 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=partial。比較不能=observed_unavailable。根拠=actor.role_lens, project.declared.requirements.role_lens

### 数値の読み方（単位・分母・母数）
- 件数の単位は commits / days / events です。比率は 0〜1 で、分母（n=）を併記します。
- 0 件は「この範囲で該当証拠が無かった」です。未観測（not_observed）は「測れなかった」です。
- surface の分母は、merge を除く人間 commit のうち path が取れたものです。
- rhythm の分母は observation_date から 180 日以内の Git author timestamp です。
- overlap は重なり、observed_zero は 0 件、not_observed は測れない、not_declared は要求なしです。
- actor と project の n・denominator・source・window は混ぜません。

## 基準値・比較材料
- 基準は project declared と、提供された場合の project observed です。

## 傾向
- actor change_rhythm.active_days_180d: 定期的な変更提出の傾向が観測される
- project change_rhythm.active_days_180d: 定期的な変更提出の傾向が観測される
- relationship change_rhythm.active_days_180d: similar_direction（similar_direction は採用・適合ではない）
- actor change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
- project change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
- relationship change_rhythm.median_gap_days: similar_direction（similar_direction は採用・適合ではない）
- actor change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
- project change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
- relationship change_rhythm.p90_gap_days: similar_direction（similar_direction は採用・適合ではない）
- actor surfaces.backend: backend系surfaceが相対的に多い傾向
- project surfaces.backend: data系surfaceが相対的に多い傾向
- relationship surfaces.backend: different_direction（similar_direction は採用・適合ではない）
- actor surfaces.data: backend系surfaceが相対的に多い傾向
- project surfaces.data: data系surfaceが相対的に多い傾向
- relationship surfaces.data: different_direction（similar_direction は採用・適合ではない）
- actor surfaces.test: backend系surfaceが相対的に多い傾向
- project surfaces.test: data系surfaceが相対的に多い傾向
- relationship surfaces.test: different_direction（similar_direction は採用・適合ではない）
- actor verification.unit: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project verification.unit: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship verification.unit: different_direction（similar_direction は採用・適合ではない）
- actor verification.integration: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project verification.integration: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship verification.integration: different_direction（similar_direction は採用・適合ではない）
- actor inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship inputs.git: mixed（similar_direction は採用・適合ではない）
- actor inputs.forge: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project inputs.forge: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship inputs.forge: not_comparable（similar_direction は採用・適合ではない）
- actor role_lens: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project role_lens: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship role_lens: not_comparable（similar_direction は採用・適合ではない）

## 傾向の強さと確からしさ
- actor change_rhythm.active_days_180d: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=2.0465 n=70 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- project change_rhythm.active_days_180d: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=106 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- relationship change_rhythm.active_days_180d 確からしさ: directional_candidate
- actor change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=2.0465 n=70 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- project change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=106 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- relationship change_rhythm.median_gap_days 確からしさ: directional_candidate
- actor change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=2.0465 n=70 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- project change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=106 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- relationship change_rhythm.p90_gap_days 確からしさ: directional_candidate
- actor surfaces.backend: backend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.backend observed=0.4082 n=151 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- project surfaces.backend: data系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.data observed=0.5278 n=340 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- relationship surfaces.backend 確からしさ: directional_candidate
- actor surfaces.data: backend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.backend observed=0.4082 n=151 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- project surfaces.data: data系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.data observed=0.5278 n=340 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- relationship surfaces.data 確からしさ: directional_candidate
- actor surfaces.test: backend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.backend observed=0.4082 n=151 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- project surfaces.test: data系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.data observed=0.5278 n=340 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- relationship surfaces.test 確からしさ: directional_candidate
- actor verification.unit: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project verification.unit: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship verification.unit 確からしさ: directional_candidate
- actor verification.integration: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project verification.integration: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship verification.integration 確からしさ: directional_candidate
- actor inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship inputs.git 確からしさ: directional
- actor inputs.forge: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project inputs.forge: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship inputs.forge 確からしさ: not_proven
- actor role_lens: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project role_lens: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship role_lens 確からしさ: not_proven

## 比較不能・未観測・未証明
- この入力では、追加の比較不能項目は記録されていません。

## 言えること / 言えないこと
- 案件側の宣言と観測証拠の重なりを軸ごとに表示しています。全体の点数や順位は計算していません。
- This report covers one repository that the provider chose to share. It does not show whether other repositories exist or what they would show.
- この数値は、過去の Git / ローカル export に残った変更の形を示します。人の優劣、職種の確定、採用の合否、将来の成果を示すものではありません。
- 活動日数（active days）は author 日付の一意な日数です。毎日 1 件の小さな commit を置けば増え、同じ変更を 1 日にまとめると減ります。変更の量や中身は見ておらず、補正もしません。
- この表示は attribution_state=claimed と記録された identity による actor 観測です。CLI はその申告者、本人同意または本人性を証明しません。
- 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- この並びだけで採用の合否を決めてはいけません。

## 再現情報
- 分析 SHA: `b2c5f307116c97ed2f12b737a6ff3df942d703df`
- 定義版: tep-v0.8.0-2026-10-25
- identity の要約ハッシュ: 315ae3360c09fb5fd5f6ce635117320ad10d24774872156d2d46a2d0a015207d
- actor report digest: f15659dce6f38c911846bd3ee634c71716a19429483f3d338729f83841a2d902
- project report digest: 66825793a94dc7bfe147ec0521f03f225dc767a5fa23f02fd6e314265de9cf75
- 入力ハッシュ: forge=None tracker=None project=22174fa974bda5ce1fad753bb2f4cc251f3da72c8baef574b10f167c536752ac
- Git window: 2026-04-23〜2026-10-20
- event window: —
