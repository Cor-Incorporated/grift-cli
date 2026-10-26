# TEP alignment レポート

## このレポートは誰・何を対象にしたか
- attribution_state=claimed と記録された identity に基づく本人向けactor観測（actor `candidate-b`）と案件宣言（project `storefront-redesign`）の軸ごとの並びです。
- actor repo SHA: `5ec556e67c818522a743d06a20b8ac5bb03d1079`
- project repo SHA: `869513e7bc91eab9b2d96788e687655e5af95769`
- 案件側の宣言と観測証拠の重なりを軸ごとに表示しています。全体の点数や順位は計算していません。

## 何を入力として見たか
- actor observed は actor レポートの観測です。project observed は対象リポジトリの運用観測です。
- declared は project TOML です。観測と混ぜません。

## 何を見ていないか
- 総合点、順位、適合率、採用推奨は計算していません。
- Git-only では review / issue triage / stakeholder 活動は未観測です。

## 案件側の宣言
- surfaces: frontend, docs surface-names
- verification: e2e verification-types
- inputs: git input-kinds

## 観測された数値 / 軸ごとの並び
- change_rhythm.active_days_180d: 案件側に要求がない（不足ではない）。actor観測=21 days（母数 n=39） / project実測=52 days（母数 n=52） / 宣言=未宣言（not_declared。案件側が書いていない。不足ではない）理由: requirement_not_provided。actor_n=39 project_n=52 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.change_rhythm.active_days_180d, project.declared.requirements.change_rhythm.active_days_180d_min
- change_rhythm.median_gap_days: 案件側に要求がない（不足ではない）。actor観測=0.7417 days（母数 n=38） / project実測=1.0465 days（母数 n=51） / 宣言=未宣言（not_declared。案件側が書いていない。不足ではない）理由: requirement_not_provided。actor_n=38 project_n=51 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.change_rhythm.median_gap_days, project.declared.requirements.change_rhythm.median_gap_days_max
- change_rhythm.p90_gap_days: 宣言範囲の外（能力の否定ではない）。actor観測=18.572 days（母数 n=38） / project実測=12.0465 days（母数 n=51） / 宣言=14 days。actor_n=38 project_n=51 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.change_rhythm.p90_gap_days, project.declared.requirements.change_rhythm.p90_gap_days_max
- surfaces.frontend: 重なり（観測が宣言範囲・要求と重なる）。actor観測=0.551 commit_share / project実測=57 commits / 宣言=0.3 commit_share。actor_n=49 project_n=113 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=partial。比較不能=unit_mismatch。根拠=actor.surface_profile.surface_commit_counts.frontend, project.declared.requirements.surfaces
- surfaces.docs: 重なり（観測が宣言範囲・要求と重なる）。actor観測=10 commits / project実測=23 commits / 宣言=docs surface。actor_n=49 project_n=113 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.surface_profile.surface_commit_counts.docs, project.declared.requirements.surfaces
- verification.e2e: 重なり（観測が宣言範囲・要求と重なる）。actor観測=9 commits / project実測=22 commits / 宣言=e2e surface。actor_n=49 project_n=113 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.verification_profile.test_type_distribution.e2e, project.declared.requirements.verification
- inputs.git: 重なり（観測が宣言範囲・要求と重なる）。actor観測=True boolean / project実測=True boolean / 宣言=git input。actor_n=49 project_n=113 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=present。比較不能=なし。根拠=actor.input_coverage.git, project.declared.requirements.inputs
- role_lens: 案件側に要求がない（不足ではない）。actor観測=未観測（not_observed。測定できなかった。実績がないことではない）理由: role_lens_not_set / project実測=未観測（not_observed。測定できなかった。実績がないことではない）理由: axis_not_in_project_observed / 宣言=未宣言（not_declared。案件側が書いていない。不足ではない）理由: requirement_not_provided。actor_n=49 project_n=113 actor_denominator=None project_denominator=None actor_source=['git:path', 'git:author_timestamp'] project_source=['git:path', 'git:author_timestamp'] actor_window=2026-04-23〜2026-10-20 project_window=2026-04-23〜2026-10-20 coverage=partial。比較不能=observed_unavailable。根拠=actor.role_lens, project.declared.requirements.role_lens

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
- relationship change_rhythm.active_days_180d: different_direction（similar_direction は採用・適合ではない）
- actor change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
- project change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
- relationship change_rhythm.median_gap_days: similar_direction（similar_direction は採用・適合ではない）
- actor change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
- project change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
- relationship change_rhythm.p90_gap_days: similar_direction（similar_direction は採用・適合ではない）
- actor surfaces.frontend: frontend系surfaceが相対的に多い傾向
- project surfaces.frontend: frontend系surfaceが相対的に多い傾向
- relationship surfaces.frontend: not_comparable（similar_direction は採用・適合ではない）
- actor surfaces.docs: frontend系surfaceが相対的に多い傾向
- project surfaces.docs: frontend系surfaceが相対的に多い傾向
- relationship surfaces.docs: different_direction（similar_direction は採用・適合ではない）
- actor verification.e2e: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project verification.e2e: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship verification.e2e: different_direction（similar_direction は採用・適合ではない）
- actor inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship inputs.git: mixed（similar_direction は採用・適合ではない）
- actor role_lens: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project role_lens: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship role_lens: not_comparable（similar_direction は採用・適合ではない）

## 傾向の強さと確からしさ
- actor change_rhythm.active_days_180d: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=0.7417 n=39 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- project change_rhythm.active_days_180d: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=52 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- relationship change_rhythm.active_days_180d 確からしさ: directional_candidate
- actor change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=0.7417 n=39 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- project change_rhythm.median_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=52 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- relationship change_rhythm.median_gap_days 確からしさ: directional_candidate
- actor change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=0.7417 n=39 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- project change_rhythm.p90_gap_days: 定期的な変更提出の傾向が観測される
  - 根拠: change_rhythm.median_gap_days observed=1.0465 n=52 denominator=180 window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: 間隔は提出の時系列であり、労働時間・速度・納期遵守ではない。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。
- relationship change_rhythm.p90_gap_days 確からしさ: directional_candidate
- actor surfaces.frontend: frontend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.frontend observed=0.617 n=69 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: strong
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- project surfaces.frontend: frontend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.frontend observed=0.5357 n=159 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- relationship surfaces.frontend 確からしさ: not_proven
- actor surfaces.docs: frontend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.frontend observed=0.617 n=69 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: strong
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- project surfaces.docs: frontend系surfaceが相対的に多い傾向
  - 根拠: surface_profile.surface_file_share.frontend observed=0.5357 n=159 denominator=distinct paths or file-changes in scoped commits window=2026-04-23/2026-10-20 source=git:path, git:author_timestamp
  - 傾向の強さ: moderate
  - 確からしさ: directional
  - 注意: これは path と拡張子による作業領域の観測です。職種・能力・適性の判定ではありません。; 追加の履歴、別window、別inputが加わると、この傾向の強さや表示は変わる可能性があります。; これは職種ラベルではない。能力・採用・将来成果を示さない。
- relationship surfaces.docs 確からしさ: directional_candidate
- actor verification.e2e: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project verification.e2e: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship verification.e2e 確からしさ: directional_candidate
- actor inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- project inputs.git: 未証明（not_proven。確認できない。0件ではない）理由: no_tendency_for_axis
- relationship inputs.git 確からしさ: directional
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
- 分析 SHA: `5ec556e67c818522a743d06a20b8ac5bb03d1079`
- 定義版: tep-v0.8.0-2026-10-25
- identity の要約ハッシュ: 7bfad97bd23d8b2744885e425e2a286e691995ac441f8da09c330d02e029db83
- actor report digest: 275cb87278c1607996a958e3d50cc9a63df4ff15507f911570601491bcdf10aa
- project report digest: 815991d257793af01c023b0f4ebcf5c3774f749e27cb3045fbd6c32c3e940515
- 入力ハッシュ: forge=None tracker=None project=57c3d4f2703646f0094f0822ec003e750e2f9a4f8d93290b4f72569e6ebea3e4
- Git window: 2026-04-23〜2026-10-20
- event window: —
