# v0.6 benchmark pack quality report

## Summary

判定は `Share with caveats` 相当です。ファイル構造と抽出結果は再現可能ですが、外部データは母集団・期間・匿名化・イベント欠損の制約を持つため、Griftの合否基準や個人評価の正解値には使いません。

## Checks performed

- GH Archive NDJSONの全行をJSONとして読み込めること
- GH Archive各行に `event_id`、`event_type`、`occurred_at`、`repository` があること
- 対象イベント種別がmanifestの許可リスト内であること
- 日付が2024-01-15から2024-01-21の範囲にあること
- リポジトリ別集計の合計が554行になること
- 職種サンプルが40行で、5ラベルが各8行あること
- 職種ラベル全体件数が source-derived summary と一致すること
- Tracker契約fixtureの時間順序が計算可能であること
- manifestのartifactハッシュが現物と一致すること

## Findings and risks

### Medium: GH Archiveは7日間の各日00 UTCだけ

7日分の短時間スナップショットなので、日中全体の活動、週末差、長期のRelease周期は表しません。短期のイベント正規化・集計テストには使えますが、コンスタント型／バースト型の確定には不十分です。

### Medium: GitHub公開活動の母集団偏り

OSS、公開リポジトリ、GitHub上の活動に限られます。企業内の非公開リポジトリ、GitHub外のTracker、会議・顧客調整は含みません。

### Medium: Eventと成果は同じではない

ReleaseEventは自動化された成果物公開の場合もあります。PushやCommitの時刻は、作業開始、レビュー完了、本番Deploy、顧客価値の実現時刻ではありません。

### High: 外部職種データとGrift actorは結合しない

職種研究データは分類器検証用です。Griftのidentity.tomlと結合せず、分類精度・特徴量妥当性のテストだけに使います。

### High: PM成果は公開データから確定できない

Issue・PR・Reviewの観測値は、PM関連の作業面を示す補助証拠です。顧客成果、予算、優先順位、合意形成、実際の役割権限は `not_proven` とします。

## Required reporting behavior

レポートは、数値の横に必ず `source`、`window`、`n`、`denominator`、`coverage`、`limitations` を表示します。母数が小さい場合は分位点やベンチマーク判定を抑制します。

## Reproducibility

再取得元と派生ファイルのハッシュは `sources.json` に記録しています。イベントPayloadやactor情報を再配布せず、必要な場合はmanifestのURLから取得して同じ選択条件を適用します。
