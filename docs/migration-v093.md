# v0.9.3 移行

## v0.9.3 の差分

v0.9.3 は identity ファイルの生成を楽にする feature release です。測定のしかた（定義）は、
`DEFINITION_VERSION` の採番以外は変わっていません。

### 追加: `grift identity --init` / `--list`（公開リポジトリ issue #26）

メールアドレスの SHA-256 を手で計算せずに identity-v2 ファイルを作れます。生のメールは
ファイルに書かれず、`email_sha256` だけが記録されます。詳細は [usage.md](usage.md) の
「identity ファイルの生成」と [identity-schema.md](identity-schema.md) を見てください。

```bash
grift identity --list .                                            # author email を件数つきで一覧
grift identity --init --out .tep/identity.toml --email you@example.com
```

- 既存の identity ファイル（v1 / v2、手書きのもの）の読み込み規約は変わっていません
- `attribution_state` は `claimed` で書かれます。`consent` / `authority` は書かれないため、
  experience / role は従来どおり `not_observed(consenting_actor_required)` です
- 既存ファイルの上書きはしません（exit 2）

### 追加: console script `grift-cli`（公開リポジトリ issue #28 の一部）

パッケージ名と同じ名前の実行ファイルを足しました。`uvx grift-cli repo` が `--from` なしで
動きます（0.9.2 では `uvx grift-cli --version` が「実行ファイル grift-cli は無い」で
失敗することを 2026-11-20 に実測）。`grift` コマンドも従来どおり使えます。

### 変更: 導入案内を uv 主体に

README と docs の導入手順を `uv tool install grift-cli` に変えました（pipx と venv + pip も
併記）。`pip install grift` は別のライブラリであることの注意を足しました。Python 3.13 /
3.14 での動作を実測して classifiers に足しています。

### 照らし合わせ（verify）: 0.9.2 で保存した report は CANNOT_VERIFY になる

`DEFINITION_VERSION` を `tep-v0.9.2-2026-10-30` から `tep-v0.9.3-2026-11-21` に上げました。
これは測定のしかたが変わったことではなく、版の採番規約（版を上げたら定義版も上げる）に
従ったものです。そのため、0.9.2 で保存した report を 0.9.3 で `grift verify` すると
CANNOT_VERIFY（rc=2）になります。2026-11-21 実測:

```bash
# 合成 repo（alice 3 commit / bob 1 commit、2026-11-01〜04）。2026-11-21 実測
# 0.9.2 = PyPI の grift-cli 0.9.2（uvx --from grift-cli で導入）、0.9.3 = 本 release の src
$ grift verify mig093/report.json --repo id-fixture
CANNOT_VERIFY:
  - definition version 'tep-v0.9.2-2026-10-30' is not the current 'tep-v0.9.3-2026-11-21'
# rc=2。repo report-v2 も同じ理由で CANNOT_VERIFY rc=2
```

0.9.2 と 0.9.3 で同じ repo・同じ定義版の組み合わせに戻すには、同じ版で計算し直すか、
レポートを作り直してください。

## 既存機能と互換性

v0.9.2 までに公開した機能は引き続き利用できます。v0.9.2 のコマンド・フラグ・enum 値・JSON の形と分析値の互換性、以前の版からの移行内容は [v0.9.2 移行ガイド](migration-v092.md) にあります。v0.9.3 では既存コマンドの測定方法は変わりませんが、定義版数が変わるため、0.9.2 で保存した report は上記のとおり `CANNOT_VERIFY` になります。

report-v2 の `library_context` と `outcome`、チーム単位の `align --team`、contribution の `--purpose` は従来どおりです。shallow clone（例: Actions の `fetch-depth: 1`）では履歴に依存する値が `not_observed(history_incomplete)` になります。各入力・出力条件は [usage.md](usage.md)、[report-v2.md](report-v2.md)、[alignment-schema.md](alignment-schema.md) を参照してください。

## 固定revisionと公開Forge証跡

`repo` / `actor`は`--rev REV`をSHA-1/SHA-256の固定OIDへ解決します。既定はofflineで、
`--fetch-public`、`--public-evidence DIR`、`--resume-public-evidence DIR`は排他です。
取得時は`--forge-provider auto|github|gitlab`、`--forge-api-base URL`、
`--auth-token-env NAME`、`--public-evidence-out DIR`、`--max-public-pages N`を
明示できます。self-managed GitLabは明示providerとAPI baseが必要です。
GitHubとGitLabは同じprovider-neutral契約で扱いますが、GitLab commits APIに
documented account linkageがない場合は`unsupported/not_proven`のままです。
公開表示が加わってもActor partitionと全Git由来数値は変わりません。

公開取得の安全な途中停止はexit 3（PARTIAL）です。保存bundleを使う`verify`は
networkへ再接続せず、schema、manifest/body digest、再parse、Git OID集合、
SHA/account対応、report/collection bindingを検査します。

終了コードは`0=VERIFIED`、`1=MISMATCH`、`2=CANNOT_VERIFY`、公開取得の
安全な途中停止だけ`3=PARTIAL`です。

## contribution-v2

| profile | 許可door | 境界 |
|---|---|---|
| `aggregate` | `local` / `public-pr` | Actor行、remote/OID、正確な時刻、source digestなし。公開default |
| `named-public` | `local` / `public-pr` | 明示authorityのあるprovider-neutral account/projectだけ |
| `masked` | `local` / `controlled` | HMAC pseudonym付き高精度観測。controlled sidecar必須 |
| `raw` | `local` / `controlled` | 研究用raw source。controlled sidecar必須 |

masked/rawの`public-pr`はhard errorです。masked HMAC鍵は32 byte以上の
permission検査済みfile/FDからだけ読みます。CLI引数、環境変数、payload、logへ
鍵を出しません。認可済みcontrolled destinationがないため自動uploadは実装しません。

## attest / portfolio

`grift attest REPORT --repo REPO --out DIR --sign ssh|cosign`は、先にreportを
再計算してからcanonical statementへ外部署名します。reportが
`--public-evidence`、`--forge-export`、`--tracker-export`、
`--reference-manifest`を記録している場合、署名前preflightにも同じ保存入力を
明示してください。入力を省略・交換したreportは署名しません。alignmentでは
必要に応じ`--project` / `--actor`、または`--actor-report` /
`--project-report`も同様に渡します。このpreflightとverifyはnetworkへ接続しません。

statementはreport SHA-256とgeneric Git OIDに加え、全`input_digests`のmemberと
canonical aggregate digest、定義版集合digest、公開証跡digest、固定OIDから到達可能な
tag集合digest、analysis scope、実行時刻を署名対象にします。tag集合digestはtag refと
Git objectを結びますが、taggerのname/emailやtag本文をstatementへ出力しません。
`grift verify --report REPORT --bundle DIR --repo REPO`はsignature、report hash、
repository recomputationを別判定にします。SSHは受領者の
`--allowed-signers` / `--principal`、cosignはpublic keyまたは受領者が指定した
certificate identity/issuerをtrust anchorにし、bundle内の自己申告鍵を信頼しません。

`grift portfolio --manifest portfolio.toml --format both --out DIR`は、
明示self declarationまたはattestationで同じ主体を結んだ証拠台帳です。
email/handleからのcross-repo推論、平均、重み、score、rankは生成しません。
`subject_binding = "attested"`では、明示subjectを持つ各report-v2の署名を、受領者が
CLIで指定した単一のSSH allowed_signers/principalまたはcosign certificate/public key
により実検証します。bundle内の自己申告鍵、trust未指定、異なるsigner、方式混在、
subject不一致は受理しません。`self_declared`へtrust optionを混ぜることも拒否します。
repo hintはmanifestでentryごとに明示したときだけ成果物へ含めます。
