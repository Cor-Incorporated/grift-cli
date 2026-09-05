# v0.6.0 移行

既存の `analyze` / `report` / `verify` / `contribute` は report-v1 のまま動く。

| 旧操作 | v0.6 の扱い |
|---|---|
| `grift analyze` | report-v1。裸実行は repo scope |
| `grift analyze PATH` | report-v1。明示パスの tenant default を維持 |
| `grift report` | `.grift/report.{json,md}` を現在 HEAD から再生成 |
| `grift verify` | schema を自動判別（report-v1 / report-v2 / alignment-v1） |
| `grift contribute` | report-v1は既存`tep-contribution-v1`、report-v2はprofile別`tep-contribution-v2`。alignment-v1は拒否 |
| `--scope actor` | 許可しない。`grift actor ACTOR_ID` を使う |
| `grift actor ID --export DIR` | 許可しない |

新しい入口:

```text
このリポジトリを観測したい       → grift repo
この repo-local Actor の本人証拠を見たい → grift actor
この案件の要求と運用条件を記録したい → grift project
この本人証拠と案件要求を並べたい     → grift align
```

v0.6.0 の正式な cross-repo 経路:

```bash
grift actor ACTOR_ID ACTOR_REPO --identity ACTOR_IDENTITY --format both --out actor-report.json
grift project PROJECT_REPO --requirements PROJECT_TOML --format both --out PROJECT_REPORT_DIR
grift align \
  --actor-report actor-report.json \
  --project-report PROJECT_REPORT_DIR/project.json \
  --format both --out ALIGNMENT_DIR
grift verify ALIGNMENT_DIR/alignment.json \
  --actor-report actor-report.json \
  --project-report PROJECT_REPORT_DIR/project.json \
  --reference-manifest benchmarks/v060/sources.json
```

`grift repo REPO --actors --out DIR`、`grift actor --all REPO --out DIR`、
`grift actor --top N REPO --out DIR`、`grift actor ACTOR_ID REPO --out DIR` は、
次の閉じたActor collectionを新規ディレクトリへ書きます。既存ディレクトリは
置換しません。単一Actorの詳細report-v2はstdoutまたは
`--out FILE.json|FILE.md`で維持します。

```text
DIR/repo-report.json
DIR/repo-report.md
DIR/actor-index.json
DIR/actor-index.md
DIR/actors/<actor-id>.json
DIR/actors/<actor-id>.md
DIR/collection-manifest.json
```

`repo-report.*` はfull population、`actor-index.*`はfull/selectedの両集合、
`actors/*`はselected cardです。`actors/*.json`のschemaは`actor-card-v1`です。
集合自体は次でGit partitionまでoffline再検証します。

```bash
grift verify DIR --repo REPO
```

alignment は次で接続します。

```bash
grift align --actor-dir DIR --actor-id ACTOR_ID --project-report PROJECT/project.json
```

複数 card では `--actor-id`（別名 `--actor`）必須です。先頭ファイルの暗黙選択はしません。
Actor ID、`--all`、`--top`は排他です。IDのdirectory出力は
`actor-index-v1.selection.mode=explicit`を使います。explicit cardのoptional
`experience` / `role_profile`は固定OIDとidentityから再計算されるため、cardと
manifestを同時に書き換えてもverifyはMISMATCHにします。同意済みdetailを持つ
collectionは、生成時と同じ`--identity FILE`をverifyにも指定します。

v0.6 subject（repo/actor/project/align/verify）の暗黙identity探索は対象repoへ閉じます。
固定OID treeの`.tep/identity.toml`または明示`--identity FILE`だけを使い、別repoを
観測するプロセスのCWD identityとworking-treeだけの変更は無視します。legacy
`analyze` / `report`のhistorical discoveryは互換helperへ隔離されています。
experience/roleをobservedにできる明示Actor行は`attribution_state=verified|claimed`に
加えて`consent=recorded-explicit-consent`を必要とします。stateや`authority`だけでは
解放せず、consent basisには明示マーカーを記録します。マーカーのない既存identityと
`inferred|external|unresolved|bot`は
`not_observed(consenting_actor_required)`です。

AI coauthor identityは固定OID treeの`.tep/ai-identities.toml`へ移します。closed
`ai-identity-v1`はtop-level `schema_version`、`emails`、`email_sha256`以外を拒否し、
少なくとも1つのexact identityを要求します。working-treeだけの宣言は無視します。
既存の`AI-Assisted-By` / `AI-Generated-By` / `Agent-Lane`は挙動を変えず、未宣言の
`Co-authored-by`はhuman coauthorのままです。

`grift align --repo --identity --actor --project` は互換経路です。project observed が無い場合、Markdown は次を明記します。

```text
project observedは未提供のため、actorとprojectの実測比較は行っていません。
```

alignment の各軸は actor observed / project observed / project declared を分け、n・denominator・source・window を混ぜません。relationship は `similar_direction` / `different_direction` / `mixed` / `not_comparable` であり、採用・能力・適合ではありません。

`--reference-manifest` の digest は provenance に残し、verify 時に再指定します。異なる manifest は `MISMATCH` または `CANNOT_VERIFY: benchmark manifest is unavailable or different` です。

dirty worktree では `checkout --force` を使いません。unreachable SHA は `not reachable`、reachable かつ dirty は破壊的 checkout を拒否します。

`grift analyze PATH --actor ACTOR_ID --identity FILE` は互換 alias。stderr に deprecation を出し、出力は report-v2、`.grift/report.json` は上書きしない。

v0.6 の `change_rhythm` は 180 日窓内の author timestamp だけを gap 母集団にします。窓の外側は別カウントです。

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

## schema と互換性

- report-v1 / export-v1は追加互換です。既存キー・値・意味を変更しません
- report-v2、actor card/index、project、alignment、public evidence、
  contribution-v2、attest、portfolio、scenario、forge/tracker export-v2は
  Draft 2020-12の閉じたschemaで未知キーを拒否します
- legacy commandはexport-v1の読取互換を維持します。v0.6 subject commandは
  provider/host/project/target OID/window/coverageへboundされたexport-v2だけを
  受けるのがrelease契約です。`EXT-01`がPASSになるまではこの経路を完了扱いしません
- experience/roleはreport-v1の同意済みtenant reportへの追加fieldだけです。
  export-v1へはconsumer sign-offまで追加しません

## network経路

測定コマンドの暗黙update checkはありません。明示network経路はpublic fetch /
resume、`grift update --check`、`grift contribute --open`、cosign keylessだけです。
public evidence replay、report/collection/attestation verifyはnetworkへ再接続しません。
