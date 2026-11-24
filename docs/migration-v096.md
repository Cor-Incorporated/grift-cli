# v0.9.6 移行

0.9.6 は #7・#8・#23・#24・#25・#27 を閉じる公開リポジトリ向けのリリースです。旧版の結果を再現する場合は、使用した CLI の版とリポジトリの revision を記録してください。[English](en/migration-v096.md)

## 定義版が変わります

`DEFINITION_VERSION` を `tep-v0.9.5-2026-11-23` から `tep-v0.9.6-2026-11-24` に上げました。0.9.5 までに保存した report-v2 は、0.9.6 の `grift verify` で `CANNOT_VERIFY`（終了コード 2）になります。0.9.6 で作り直すか、保存した版の CLI で照合してください。

## report-v2 に増えた項目

- `signature_observation`: 選んだ commit のうち、署名ヘッダを持つものの比率。母数が 20 に届かないときは `not_observed`。署名の有効性は見ません。点数ではありません。範囲は [verify-guarantees.md](verify-guarantees.md) にあります
- `usage_terms`: 許す使い方、使ってはいけない使い方（[利用規範](norms.md)の条文）、開示水準、`binding: declaration_only`
- `provenance.disclosure_level`: `--disclosure-level minimal|standard|full` の記録。verify が同じ水準で作り直します
- report-v1 の `interpretation.survival`（`--survival` を付けたときだけ）。公開の参照分布に survival が無いため、現行では `reference_too_small` です

`--disclosure-level` を省いたときは `full` で、Markdown は 0.9.5 までと同じ観測を出します。増えた項目に score・rank などの判定の語は使っていません。

## 本人向けの表示

本人の同意が記録された `grift actor` の Markdown に、「この記録の使い方（本人向け）」の節が付きます。渡した forge / tracker の export にその人のイベントがあれば、「レビューと課題の記録」の文も付きます。件数と期間だけで、良し悪しは書きません。

## 固定revisionと公開Forge証跡

GitHub・GitLabの公開履歴を取得する `--fetch-public` はprovider-neutral形式で記録します。PARTIAL（exit 3）の場合は `--resume-public-evidence` で再開し、保存済み証拠を `--public-evidence` で検証します。CIで `fetch-depth: 1` の場合、計測できる履歴は取得済みの範囲です。出力に `history_incomplete` があれば、全履歴を取り直して比較してください。

## contribution-v2

report-v1に許される `--purpose` は既定の `reference-distributions` です。別用途にはreport-v2を使用します。report-v1で `outcome-linkage` を指定すると、投稿・ファイル出力の前に終了コード2を返します。contribution-v2で選べる情報量はaggregate / named-public / masked / raw、送付先はlocal / controlled / public-prです。共有前に出力を確認してください。

## attest / portfolio

`grift attest` の署名方式は `ssh|cosign` です。受領時はsignature・report hash・repository recomputationの結果を個別に確認します。`grift portfolio` はeligibleとincludedの件数を表示し、個人のemail/handleによるscoreやrankを作りません。`library_context`、`outcome`、`align --team` の利用条件は[使い方](usage.md)を参照してください。

## 公開リポジトリからの基準分布づくり

`scripts/corpus_bootstrap.py` で、`contribute` に頼らず公開リポジトリから基準分布を作れます（`plan` → `observe` → `build`）。出荷済みの `v2026.09` と `v2026.11` は変わりません。手順は [corpus-protocol.md](corpus-protocol.md) にあります。
