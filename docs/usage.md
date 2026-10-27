# grift コマンドの使い方

[README](../README.md) の「試す」の続きです。grift は TEP（Technical Evidence Pipeline）という手法を実装したコマンドで、ここには各コマンドの詳しい使い方と、出力の形式、ネットワークに接続する操作をまとめています。英語版は [docs/en/usage.md](en/usage.md) です。

出力の数値の読み方は [metrics-guide.md](metrics-guide.md)、report-v2 の構成は [report-v2.md](report-v2.md) にあります。

## 1 人の記録と案件の要求を並べる

```bash
pipx install grift-cli
cd your-repo
grift repo                  # このリポジトリの記録（report-v2）
grift actor candidate_001 --identity .tep/identity.toml --format both --out actor-report.json
grift project --requirements .tep/project.toml --format both --out project-out
grift align \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --format both --out alignment-out
```

互換経路 `grift align --repo --identity --actor --project` は残しています。この経路は project observed を含まないため、Markdown に「project observedは未提供のため、actorとprojectの実測比較は行っていません。」と出ます。

saved-report の alignment は次で verify します。

```bash
grift verify alignment-out/alignment.json \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --reference-manifest benchmarks/v060/sources.json
```

互換経路で作った alignment は、作ったときと同じ repo・identity・project TOML で verify します。どちらの経路で確かめるかは渡した入力で決まります。`--project` があって `--actor-report` と `--project-report` の 2 つがそろっていなければ repo の経路、2 つがそろっていて `--project` が無ければ保存した report の経路です。両方の入力がそろっているとき、またはどちらもそろっていないときは、JSON の `subject.mode` が `saved_reports` なら保存した report の経路、そうでなければ repo の経路で確かめます。保存した report から作った alignment を repo の経路で確かめると、MISMATCH の最初に `note: subject.mode is 'saved_reports'` と出ます。

```bash
grift verify alignment.json --repo . \
  --identity .tep/identity.toml --project .tep/project.toml
```

どちらの経路も `subject`（同意の記録 `actor_consent` と `project_id` を含む）を保存した JSON から写さず、入力から作り直して比べます。repo の経路は provenance と limitations も作り直し、保存した JSON からは作り直しの入力（`--as-of`・`--role-lens`・`--vendor-scan`・`--survival`・`--reference` の指定）だけを読みます。`--event-window` を付けて作った alignment は、まだ repo の経路で VERIFIED になりません（0.9.2 で直します）。保存した 2 つの report の経路は、渡した actor の report を信じて作り直します。actor の report が書き換えられていないかは、`grift verify actor-report.json --repo REPO --identity IDENTITY` で別に確かめてください。

`grift report alignment-out/alignment.json` は保存した JSON から Markdown を描き直すだけで、検算はしません。面談の問いを出すかどうかは、JSON に書かれた actor の選び方・ID の種類・同意の記録（`subject.actor_selection`・`subject.actor_attribution_state`・`subject.actor_consent`）をそのまま使います（actor の report を描き直すときの本人向けの文も同じです）。JSON が書き換えられていないかを確かめるのは `grift verify` です（保存した report から作った照らし合わせでは、上のとおり actor の report も確かめます）。Markdown の「数字の読み方と限界」にも同じことを書いています。

## 複数人の記録をまとめて書き出す

```bash
# repo全体と選択Actor cardを分離した閉じた集合
grift repo . --actors --format both --out actor-collection
grift verify actor-collection --repo .

# 1 Actorだけを選ぶstrict collection（consent-gated experience/roleもcardへ保持）
grift actor candidate_001 . --identity .tep/identity.toml \
  --format both --out actor-explicit-collection
grift verify actor-explicit-collection --repo . \
  --identity .tep/identity.toml
```

`--top N` は、commit 数の多い N 人を取り出す「量による抽出」です。選ぶ基準は commit 数であり、品質や順位ではありません。取り出した N 人を含め、`actor-index` の行、selected card の列挙、report-v2 の `actor_directory` は actor id 順（identity があれば canonical_id、無ければ `actor_<hash>`）に並べ、commit 数の多い順には並べません（0.8.0 から）。

collection を alignment へ渡すとき、card が複数あれば `--actor-id`（別名 `--actor`）が必須です。

```bash
grift align --actor-dir actor-collection --actor-id ACTOR_ID \
  --project-report project-out/project.json --format both --out alignment-from-card
```

## コマンドの一覧

v0.6 からの基本の入口は **対象** を名前にしたコマンドです。保存したいときだけ `--out` を付けます（既定では `.grift/` を作りません）。`--format` の既定は `md` です。

| コマンド | 動作 |
|---|---|
| `grift repo` | Git working tree を観測（report-v2, repo scope） |
| `grift actor ID` | stdout / `--out FILE.json|FILE.md` は1つの canonical_id のbasis-aware actor観測（report-v2）。`--out DIR` はexplicit strict collection。pattern 推測と `--export` はしない |
| `grift project` | 観測した運用の形、または `--requirements` の宣言（project-v1）。混ぜない。Git-only では review/issue 運用は未観測 |
| `grift align` | 宣言と観測を軸ごとに並べる（alignment-v1）。総合点は出さない |

0.5 系からある動詞は「**analyze = 表示（stdout）**・**report = 記録（`.grift/`）**」の意味のままです。

| 2語コマンド | 動作 |
|---|---|
| `grift analyze` | カレントリポジトリを**stdout に表示**（report-v1・repo スコープ・`.grift/` は作らない） |
| `grift report` | 分析して `.grift/report.{json,md}` に**記録**（常に現在の HEAD を再分析・既定 repo スコープ・`--scope tenant` 可） |
| `grift verify` | `.grift/report.json` を同条件で再計算し改ざんを検出（VERIFIED / MISMATCH / CANNOT_VERIFY） |
| `grift contribute` | `.grift/report.json` からprofile別payloadを組む。既定はlocal書込のみ。**`--open`** は明示network経路として本人のforkへpushし、PR作成ページを開く（最終ボタンは本人） |
| `grift update` | grift-cli 自身を明示的に更新。`--check` は最新版の表示だけを行う唯一の update-check 経路 |

- `.grift/` は出力専用のディレクトリです（無ければ自動で作ります）。リポジトリの `.gitignore` に `.grift/` を足しておくことを勧めます
- 対象パス・スコープ・出力先を明示する書き方は従来どおりです: `grift analyze path --scope tenant --identity .tep/identity.toml --out dir`
- 明示パス付きの `grift analyze REPO` では `--scope tenant`（既定）: `.tep/identity.toml` に載った人の仕事が対象／`--scope repo`: bot 以外の全人間コミット = プロセス観測・参照分布用

repo スコープの `grift analyze` / `grift report` が書く report-v1 には、公開リポジトリの参照分布の中での参照用の位置（「第N十分位」）が 1 行付きます。tenant スコープでは出しません（`not_observed(scope_is_tenant)`）。リポジトリ同士の位置であり、人の順位ではありません。参照分布 v2026.09 は **repo スコープ同士**でのみ照合します。tenant の値を repo の分布に載せません（混ぜると分布が嘘になります）。位置の定義は [metrics-guide.md](metrics-guide.md) の十分位の表記規約、分布の母数は [validation.md](validation.md) にあります。

## Actor の表示根拠

Actorの表示根拠は `subject.selection` と `subject.attribution_state` で区別します。
identityなしの `inferred_actor` は公開Git上のcluster、explicitの `claimed` だけが
本人向け表示、`verified` は管理権限に基づく非本人向け表示です。explicitの
`inferred|external|unresolved|bot` は非同意表示、state欠落・矛盾はunknownとして
fail closedします。CLIはclaimedを含め、申告者・本人同意・本人性を証明しません。
actor reportのmachine scopeは、explicit `verified|claimed`だけが`tenant`、公開inferred
またはexplicit非同意basisは`actor_cluster`です。`actor_cluster`はrepo-local Git
primary-author clusterであり、表示根拠・本人同意・本人性の証明ではありません。

## チームの充足ギャップ（`grift align --team`）

宣言された要求をチームが覆えているかを **人数のみ** で出します。個人の測定値は匿名の最大値としても出ません。3 名未満では `not_observed`（`reason: insufficient_team_size`）を返し、個人を特定しうる数を出しません。入力は **report-v2 のみ**で、`grift actor ID REPO --out DIR` が書く `actor-card-v1` は拒否します（card は surface 観測を持たず、読ませると全要求が `not_observed` になり「チームを測った」ように見えるため）。

```bash
# メンバーごとに report-v2 を作る（--format json の stdout が report-v2）
grift actor alice . --identity .tep/identity.toml --format json > team/alice.json
grift actor bob   . --identity .tep/identity.toml --format json > team/bob.json
grift actor carol . --identity .tep/identity.toml --format json > team/carol.json
grift align --team --actor-dir team --project-report project-out/project.json
```

## 納品結果の申告（`--outcome-declaration`）

`grift repo` と `grift actor` にだけ付きます。渡した内容は必ず `kind: "declared"` として記録され、観測にはなりません。**`grift verify` はこのブロックを比較しません**。宣言を書き換えても verify は検知しません。`grift project` / `grift align` に渡すと `unrecognized arguments` になります。

```bash
grift repo . --outcome-declaration .tep/outcome.toml --format json
```

## 導入ライブラリの普及率（`library_context`・actor scope）

その Actor が導入したライブラリが参照コーパスでどれだけ普及しているかを出します。**ライブラリを記述するのであって、人を記述しません。** actor scope の出力にだけ現れます。

```bash
grift actor candidate_001 . --identity .tep/identity.toml --format json
```

## 公開 Forge 取得（`--fetch-public`・opt-in）

`grift repo REPO --rev REV --fetch-public --public-evidence-out DIR` は、固定OID時点のGitHubまたはGitLab commits APIをprovider-neutral adapterで全paginationし、response bodyをcontent-addressed bundleとしてmode 0600で保存します。`--public-evidence DIR`はnetworkなしで再生し、`--resume-public-evidence DIR`は安全なpartialだけを再開します。既定では**一切接続しません**。

- Actor partitionは固定Git履歴と固定treeの`.mailmap`だけで先に確定します。GitHubはtop-level `author.id`を持つcommit SHAだけをaccount linkageに使います。GitLab commits APIにはdocumented account linkageがないため`unsupported/not_proven`のままです。provider loginや名前類似でActorを統合しません。
- pagination がrate limit等で途中停止するとbundleとresume cursorを残してexit 3（PARTIAL）にします。`verify --public-evidence DIR --repo REPO`はmanifest/body digest、再parse、固定OIDの`git rev-list`とのmissing/extra/duplicateをofflineで検査します。
- providerは`--forge-provider auto|github|gitlab`、API endpointは
  `--forge-api-base URL`、tokenの値を置く環境変数名は`--auth-token-env NAME`、
  安全なpage上限は`--max-public-pages N`で明示します。token値自体は引数や証跡に
  書きません。
- REST API経路にはcrawler向けrobots.txtを適用しません。provider API termsとrate-limit responseを記録し、licenseは固定Git treeから別証跡として扱います。
- GitHub/GitLab/self-managedの判定はhost完全一致と明示provider/API baseで行い、SSH/SCP/HTTPS/port/IPv6をcredential除去後に正規化します。
- token・Authorization header・raw email・ローカル絶対 path は成果物に出しません。

## Target-bound forge / tracker export

`--forge-export` / `--tracker-export` をv0.6 subjectへ渡す場合は、provider、host、
stable project ID/path、target OID、UTC window、coverageを持つv2だけを受理します。
GitHub/GitLab固有の名前ではなく正規化eventを集計し、repoは全event、actorは
`actor_canonical_id`完全一致だけを対象にします。partial入力は含まれる件数を
下限として残し、absence/cadence/shareを`not_proven`にします。

tracker v2はissue/milestoneの閉じたstate chain、predecessor/link、timestamp差と
一致する非負durationを検査します。出力durationは労働時間・速度・能力ではありません。
詳細とJSON例は[ローカルexport契約](input-export-schema.md)を参照してください。

## Actor collection と strict schema

`repo --actors`、`actor --all`、`actor --top N`、`actor ACTOR_ID --out DIR`は、
次の閉じた集合を新規ディレクトリへ出力します。単一Actorの詳細report-v2を
保存する互換経路は`--out FILE.json|FILE.md`です。

```text
repo-report.json / repo-report.md       # full population
actor-index.json / actor-index.md       # full一覧とselected一覧
actors/<actor-id>.json / .md            # selected card
collection-manifest.json                # 全memberのpath/bytes/SHA-256
```

既存ディレクトリは上書きしません。full/selected件数、partition/population/
selection digest、cardのn/denominatorを全形式で一致させ、path traversal、symlink、
未登録file、改ざんを`grift verify DIR --repo REPO`で拒否します。公開accountを含む
集合の独立検証では`--public-evidence EVIDENCE_DIR`も指定します。
explicit cardはclosed schema内のoptional `experience` / `role_profile`に、現在の
consent gateで生成した観測または`not_observed(consenting_actor_required)`を保持します。
この機械field名や生成可否は同意の証明ではありません。verifyは
manifestの自己整合だけでなく固定OIDとidentityから両fieldを再計算します。
identityを使って書いたcollectionは、0.9.1から`repo-report.json`の`provenance.identity_digest`に
そのdigestを記録します。verifyは生成時と違うidentityを、MISMATCHの先頭の
`identity (recorded identity_digest …, observed …)`（記録したdigestといま使ったdigest）と、
生成時と同じ`--identity FILE`を求める`note:`の行で示します。identityなしで書いたcollectionと
0.9.0までのcollectionにはこのkeyが無く、食い違ったときは`note:`の行だけを添えます（原因が
identityとは限りません）。読み込めないidentityを渡したときは`CANNOT_VERIFY`（exit 2）です。

report-v1とexport-v1は既存キー・値の追加互換を維持します。report-v2と新規v0.6
成果物はDraft 2020-12の閉じたschemaで未知キーを拒否します。詳細は
[report-v2.md](report-v2.md)を参照してください。

## identity と AI identity の読み込み

v0.6 subjectコマンドが暗黙に読むidentityは、対象の固定OID treeに記録された
`.tep/identity.toml`だけです。別repoを観測するときにカレントディレクトリのidentityや
working-treeだけの変更を混入させません。外部ファイルを使う場合は`--identity FILE`で
明示します。experience/roleを生成するには、1 Actorを明示した行に
`attribution_state=verified|claimed`と
`consent=recorded-explicit-consent`の両方が必要です。stateや`authority`だけでは
解放しません。CLIが検証するのは明示マーカーの記録であり、現実の本人同意・申告者・
本人性ではありません。マーカーのない既存identityや`inferred`、`external`、
`unresolved`、`bot`は
`not_observed(consenting_actor_required)`のままです。

AIの`Co-authored-by`を申告として分類するidentityも、固定OID treeの
`.tep/ai-identities.toml`だけから読みます。閉じた最小契約は次の形で、emailまたは
identity-v2と同じdomain-separated `email_sha256`を1件以上記録します。

```toml
schema_version = "ai-identity-v1"
emails = ["agent@example.invalid"]
# email_sha256 = ["<64 lowercase hex>"]
```

working-treeだけの追加・変更、名前、handle、類似性ではAI identityを推測しません。
既存の`AI-Assisted-By`、`AI-Generated-By`、`Agent-Lane` trailerの判定は不変で、
宣言されていない`Co-authored-by`はhuman coauthorとして扱います。

identity ファイルの形式は [identity-schema.md](identity-schema.md) にあります。

## Attestation と portfolio（opt-in）

検証済みreportは、外部のOpenSSHまたはcosignでcanonical statementへ署名できます。
署名・report hash・リポジトリ再計算は別判定であり、署名成功を数値の正しさ、
品質、優秀さへ読み替えません。

```bash
grift attest actor-report.json --repo REPO --identity IDENTITY \
  --out actor-attest --sign ssh --ssh-key KEY --principal SUBJECT
grift verify actor-report.json --repo REPO --identity IDENTITY \
  --bundle actor-attest --allowed-signers ALLOWED_SIGNERS --principal SUBJECT
```

reportがpublic evidence、forge/tracker export、reference manifestを入力にした場合は、
`attest`と`verify`の両方へ同じ`--public-evidence`、`--forge-export`、
`--tracker-export`、`--reference-manifest`を渡します。statementは各入力digestと
aggregate、定義版集合、reachable tagsetを束縛し、入力が欠けたreportを署名しません。
taggerのname/emailはstatementへ出力しません。

`grift portfolio --manifest portfolio.toml --format both --out portfolio-out`
は、context×role×period×evidenceの複数repoの一覧を作ります。同一主体の結合は
提出者の明示宣言またはattestationだけで行い、email・handleの類似から推論しません。
eligible/included件数と開示率を常に示し、平均・重み・score・rankは生成しません。

manifestの`subject_binding = "self_declared"`は提出者による明示申告です。
`subject_binding = "attested"`は、全entryのreport-v2に同じ明示`subject_id`があり、
全detached signatureが同じ受領者trust policyで検証できる場合だけ成立します。
SSHでは`--allowed-signers FILE --principal ID`、cosignでは
`--cosign-public-key FILE`または`--certificate-identity ID`と
`--certificate-oidc-issuer URL`を指定します。bundle内の自己申告鍵はtrust anchorにせず、
trust未指定、異なるsigner、binding方式の混在、subject不一致はfail closedです。
trust fileの絶対pathとrepository hintは既定出力へ含めません。repository hintはmanifestで
entryごとに明示した場合だけ出力します。JSON/Markdownは各entryを
`not_verified_self_declared`または`recipient_trust_verified`として区別します。

## 出力の形式と終了コード

| 終了コード | 意味 |
|---|---|
| 0 | `VERIFIED` またはコマンド成功 |
| 1 | `MISMATCH`（検証対象の不一致） |
| 2 | `CANNOT_VERIFY`、使用法エラー、または入力契約違反 |
| 3 | 再開可能な公開取得の安全な途中停止（PARTIAL） |

`--format json` の stdout は **JSON 1 件のみ**です（機械で読むときに混ざりものがないように）。`--format md` は markdown のみ、`--format both` は markdown → 空行 → JSON の順です。診断とエラーは常に stderr に出ます。`--out DIR` を使っても stdout の決まりは変わりません。単一reportはコマンド固有の固定名、Actor collectionは上記の閉じた構成で書きます。

report-v1の全フィールド定義は[report-schema.md](report-schema.md)
（凍結済み・追加互換）、report-v2とActor collectionは
[report-v2.md](report-v2.md)（閉じたschema）です。

各数値には単位と provenance（method=TEP・tool=grift・定義版・分析 SHA・`analysis_scope`）が付きます。自分のリポジトリで `grift analyze . --format md` を実行すると確かめられます。値の書き方は次のようになります（架空の例です）。

- test co-change: 0.30 ratio（12 of 40）
- corrective rework: 0.05 ratio（2 of 40）。観測値であり、証拠主張ではない
- path retouch: 0.45 ratio。観測のみ

母数 20 未満では率も分布位置も出しません（`insufficient_population`。件数だけを出します）。

レポート冒頭の 3〜5 行の要約（Shared block）には説明を付けません。経歴書や issue にそのまま貼ったときに長くならないよう、短さと貼りやすさを優先しています。各数値の意味は本文の行末の説明と [metrics-guide.md](metrics-guide.md) が担います。

## 機械取込用 export（opt-in）

`grift analyze <repo> --export <dir>` で commits.ndjson（1行=1コミット・origin/actor/cochange）・actors.json（canonical_id ごとの帰属と活動）・export-meta.json（`config_digest` つき）を書きます。**生メールアドレス・生 author 文字列は一切出力しません**。顧客向けの説明に載せる数値は report.json の集計値が正です。詳細は [export-schema.md](export-schema.md)。

## ネットワークに接続する操作

- `analyze` / `report` はofflineです。`repo` / `actor` は既定offlineで、`--fetch-public` または `--resume-public-evidence` を明示したときだけForge APIへ接続します。`verify`は保存bundleを再生し再接続しません。ほかの明示network経路は `update`（`--check` を含む）、`contribute --open`、cosign keylessだけです。暗黙update checkはありません
- この CLI には、当社へデータを自動で送る機能はありません。今後もこの CLI には入れません。当社が grift を組み込んだアプリケーションやサービスを別に提供する場合、そこでのデータの扱いはそのサービスの利用規約とプライバシーポリシーで定めます。`contribute --open`の明示経路も本人のforkまでで、PR作成の最終ボタンは本人が押します

## データ提出（`grift contribute`・明示的 opt-in）

**TEP Report 集計と参照分布 vNext** への提出は、profile と door を先に決めてから行います。

```bash
grift report                                  # ① repo スコープの report を作る
grift contribute --privacy aggregate --door public-pr --out .grift/contribution.json
# ③ payload を tep-contributions に PR で提出
```

提出先は [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions) です。

- `report-v1` は既存 `tep-contribution-v1` を維持します。`report-v2` の既定 `aggregate` はActor行、repo/remote/OID、正確な時刻、source digestを落としたbucket集計です。`named-public` は本人の明示authorityがあるprovider-neutral project/accountだけを保持します
- `masked` は32 byte以上のHMAC鍵をpermission検査済みfile/FDから読み、`raw` とともに `local` / `controlled` 専用です。研究用のsource対応はpermission 0600のcontrolled sidecarへ分離され、`public-pr` はhard errorです。認可済みcontrolled destinationがないため自動uploadは実装していません
- `--open` は明示的に本人の GitHub 権限でforkへpushし、最終ボタンは本人が押します。代理PR経路は提出者identityを非公開にしてもpayload自体は公開されます。公開後は既存clone/forkを含むGit履歴から完全撤回できません
- 受け口リポの CI はlegacy v1とpublic-safeなv2 `aggregate` / `named-public`だけをmode別allowlistで受理し、masked/raw、メール、内部Actor ID、credential形状を拒否します
- 用途は「TEP Report 集計と参照分布 vNext」に限ります。保持期間は次回年次 Report まで、撤回は issue で受け付けます（`docs/norms.md` 保持・削除条項）

提出データの目的は提出者が `--purpose` で選びます。`reference-distributions`（無指定時の既定・v0.6.0 と同じ意味）と `outcome-linkage` の 2 つです。`outcome-linkage` は `--door public-pr` では使えません（公開受け口の schema がまだ v0.6.0 の値だけを受けるため、組み立てた後に受け口で弾かれる前に断ります）。

```bash
grift contribute --purpose outcome-linkage --door local
```

## 0.9.0 からの更新

詳しくは [migration-v091.md](migration-v091.md) と [CHANGELOG](../CHANGELOG.md) にあります。作り直しが要るものは次のとおりです。

- 0.9.0 で保存した report（`analyze`・`actor`・`repo`）と照らし合わせ（`align`）は、0.9.1 の `grift verify` で CANNOT_VERIFY になります（`DEFINITION_VERSION` を上げたため）。リポジトリを観測した project report は MISMATCH になります。0.9.1 で作り直してください
- 0.9.0 で `--as-of` を付けて書き出した collection は、0.9.1 の `grift verify` で MISMATCH になります（experience・test_cochange・rework も観測日で切るようになったため）。作り直してください
- identity の `canonical_id` に `actor_` と 16 進数 12〜32 桁の形を書いていると、0.9.1 は exit 2 で止まります。読める id に書き直してください。リポジトリに commit した identity を固定 revision で読むときは、直したものを `--identity FILE` で渡してください
- v2 レポートの `context_profile` は UTC の日付で日を数えます。日本の 0 時〜9 時の commit がある repo では、0.9.0 と値が違うことがあります

## 0.8.0 からの更新

詳しくは [migration-v090.md](migration-v090.md) と [CHANGELOG](../CHANGELOG.md) にあります。作り直しが要るものは次のとおりです。

- 0.8.0 で保存した report（`analyze`・`actor`・`repo`）と照らし合わせ（`align`）は、0.9.0 の `grift verify` で CANNOT_VERIFY になります（`DEFINITION_VERSION` を上げたため）。project report は MISMATCH になります。0.9.0 で作り直してください
- 照らし合わせの向き（`relationship`）は、0.9.0 から、それぞれの中の割合どうしで決めます。0.8.0 の値とは意味が違うので、並べて比べないでください
- 0.8.0 で `--as-of` を付けて書き出した collection は、0.9.0 の `grift verify` で MISMATCH になります（`role_profile` を観測日で切るようになったため）。作り直してください
- identity に書いた人に commit が無く、同じ作者名の別人がいる repo では、0.8.0 の report と collection が別人の commit を本人の数に入れていました。0.9.0 で作り直してください
- `--as-of` を付けずに読んだ report で、HEAD の作者の現地の日付と UTC の日付が違う（UTC より西の夕方、日本の 0 時〜9 時など）ときは、観測日が 1 日ずれていました。0.9.0 で作り直してください

## 0.7.x からの更新

詳しくは [migration-v080.md](migration-v080.md) と [CHANGELOG](../CHANGELOG.md) にあります。作り直しが要るものは次のとおりです。

- 0.7.x で保存した report は、0.8.0 の `grift verify` で CANNOT_VERIFY になります（`DEFINITION_VERSION` を上げたため）。0.8.0 で作り直してください
- 0.7.x で作った collection は、0.8.0 の `grift verify` で MISMATCH になります（actor を列挙する行の順が actor id 順になったため）。作り直してください
- 0.7.0 / 0.7.1 で、identity に載った人の commit が 0 件の repo に `grift export --scope tenant` をかけた場合、全 commit の `prod_paths_touched` / `test_paths_touched` が 0 になっていました。0.7.2 以降でやり直してください
- 0.7.1 から、`--fetch-public` は bot commit に public account を付けず、unlinked commit として数えます。bot commit を含む repo は account linkage の観測値が変わるので、0.7.1 以降で集め直してください
