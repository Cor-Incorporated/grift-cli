# v0.9.5 移行

0.9.5の配布前検証用。旧版の結果を再現する場合は、使用したCLIの版とリポジトリのrevisionを記録してください。[English](en/migration-v095.md)

## actorで保存した結果を受け取る

`grift actor --out DIR` の生成物はディレクトリ一式で共有します。0.9.5候補では観測日と期間の基準を記録し、`grift verify DIR/repo-report.json --repo REPO` で全構成物を照合します。identityを指定して生成した場合は検証にも同じ `--identity FILE` を指定します。JSONだけを渡した場合の終了コードは2です。

0.9.3で生成したactor collectionも、元のディレクトリ一式と元のリポジトリを使って検証できます。単独reportは定義版が変わるため、旧版を保持して照合するか、新しい候補で作り直します。

## contribution-v2

report-v1に許される `--purpose` は既定の `reference-distributions` です。別用途にはreport-v2を使用します。report-v1で `outcome-linkage` を指定すると、投稿・ファイル出力の前に終了コード2を返します。contribution-v2で選べる情報量はaggregate / named-public / masked / raw、送付先はlocal / controlled / public-prです。共有前に出力を確認してください。

## 固定revisionと公開Forge証跡

GitHub・GitLabの公開履歴を取得する `--fetch-public` はprovider-neutral形式で記録します。PARTIAL（exit 3）の場合は `--resume-public-evidence` で再開し、保存済み証拠を `--public-evidence` で検証します。CIで `fetch-depth: 1` の場合、計測できる履歴は取得済みの範囲です。出力に `history_incomplete` があれば、全履歴を取り直して比較してください。

## attest / portfolio

`grift attest` の署名方式は `ssh|cosign` です。受領時はsignature・report hash・repository recomputationの結果を個別に確認します。`grift portfolio` はeligibleとincludedの件数を表示し、個人のemail/handleによるscoreやrankを作りません。`library_context`、`outcome`、`align --team` の利用条件は[使い方](usage.md)を参照してください。
