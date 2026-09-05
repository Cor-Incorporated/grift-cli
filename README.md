# grift — AI時代に痩せない証拠

**日本語** | [English](README.en.md)

Method = **TEP** / Tool = **grift**（CodeScene 型の二層。方法論名は TEP、コマンドは `grift`）。
Named after the Grift product line.

量は誰でも作れる。残るものと、検証が伴った変更を測る。技量スコアではない。

## 利用規範（norms）

「TEP 準拠」を名乗る利用の条件を [docs/norms.md](docs/norms.md) に定める（不在を負に読まない・単独足切り禁止・申告を負に読まない・同意なき第三者プロファイリング禁止・監視転用非準拠・選択性の明示・重み付け禁止の7条・日英併記）。**本規範への適合を「TEP」の名の使用条件とする。**

コミット数・行数・「活動量」は、エージェントと生成コードの時代に簡単に膨らむ。grift は git だけから、TEP の帰属（誰の仕事か）と検証層（test co-change ほか）を**決定論的に**出す。LLM は使わない。合成スコアも等級語彙も出さない。

## なぜスコアを出さないか

grift の目的は人を1つの数値へ縮約することではなく、第三者が条件と限界を確認し、
必要なら再計算できる証拠を残すことです。

| 設計上の選択 | 利用者にとっての価値 | 境界 |
|---|---|---|
| LLMを使わない | モデル、provider、promptの更新で測定結果が変わらない | 定義版や入力revisionが変われば結果も変わるため、provenanceを併記する |
| 固定OID・版管理された定義・決定論的再計算 | 同じ入力を再実行し、差分や改ざんを確認できる | 再現できることは、数値の正しさ・品質・優秀さの証明ではない |
| 既定local/offline | 明示したnetwork経路を除き、履歴・identity・結果を端末外へ送らない | public fetch、`update --check`、`contribute --open`、cosign keylessは明示network経路 |
| 合成score・rank・重み付けを生成しない | 単位、母数、観測窓、限界を隠さず、採用閾値へ自動変換しない | 読み手による文脈確認と面接・レビューは置き換えない |
| `not_observed` と母数20未満の抑制 | 見えない履歴や小標本を、低実績・低能力へ誤変換しない | private履歴やgit外の成果を補完・推測しない |
| attest とportfolioの選択性開示 | 誰がどの条件で測ったか、どのrepoを選んだかを受領者が確認できる | 署名は実行事実、portfolioは選択された証拠台帳であり、人物評価ではない |

## 5分で始める（対象を先に選ぶ）

```bash
pipx install grift-cli
cd your-repo
grift repo                  # このリポジトリの証拠（report-v2）
grift actor candidate_001 --identity .tep/identity.toml --format both --out actor-report.json
grift project --requirements .tep/project.toml --format both --out project-out
grift align \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --format both --out alignment-out

# repo全体と選択Actor cardを分離した閉じた集合
grift repo . --actors --format both --out actor-collection
grift verify actor-collection --repo .

# 1 Actorだけを選ぶstrict collection（consent-gated experience/roleもcardへ保持）
grift actor candidate_001 . --identity .tep/identity.toml \
  --format both --out actor-explicit-collection
grift verify actor-explicit-collection --repo . \
  --identity .tep/identity.toml
```

`--top` はcommit数による抽出であり、品質ランキングではありません。collectionを
alignmentへ渡す場合、複数cardでは`--actor-id`（別名`--actor`）が必須です。

```bash
grift align --actor-dir actor-collection --actor-id ACTOR_ID \
  --project-report project-out/project.json --format both --out alignment-from-card
```

互換経路 `grift align --repo --identity --actor --project` は残しています。この経路は project observed を含まないため、Markdown に「project observedは未提供のため、actorとprojectの実測比較は行っていません。」と出ます。

saved-report の alignment は次で verify します。

```bash
grift verify alignment-out/alignment.json \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --reference-manifest benchmarks/v060/sources.json
```

v0.6 の基本入口は **対象** である。保存したいときだけ `--out` を付ける（既定では `.grift/` を作らない）。`--format` の既定は `md`。

| コマンド | 動作 |
|---|---|
| `grift repo` | Git working tree を観測（report-v2, repo scope） |
| `grift actor ID` | stdout / `--out FILE.json|FILE.md` は1つの canonical_id のbasis-aware actor観測（report-v2）。`--out DIR` はexplicit strict collection。pattern 推測と `--export` はしない |
| `grift project` | 観測した運用の形、または `--requirements` の宣言（project-v1）。混ぜない。Git-only では review/issue 運用は未観測 |
| `grift align` | 宣言と観測を軸ごとに並べる（alignment-v1）。総合点は出さない |

Actorの表示根拠は `subject.selection` と `subject.attribution_state` で区別します。
identityなしの `inferred_actor` は公開Git上のcluster、explicitの `claimed` だけが
本人向け表示、`verified` は管理権限に基づく非本人向け表示です。explicitの
`inferred|external|unresolved|bot` は非同意表示、state欠落・矛盾はunknownとして
fail closedします。CLIはclaimedを含め、申告者・本人同意・本人性を証明しません。
actor reportのmachine scopeは、explicit `verified|claimed`だけが`tenant`、公開inferred
またはexplicit非同意basisは`actor_cluster`です。`actor_cluster`はrepo-local Git
primary-author clusterであり、表示根拠・本人同意・本人性の証明ではありません。

legacy 動詞の意味は「**analyze = 表示（stdout）**・**report = 記録（`.grift/`）**」のままです:

| 2語コマンド | 動作 |
|---|---|
| `grift analyze` | カレントリポジトリを**stdout に表示**（report-v1・repo スコープ・`.grift/` は作らない） |
| `grift report` | 分析して `.grift/report.{json,md}` に**記録**（常に現在の HEAD を再分析・既定 repo スコープ・`--scope tenant` 可） |
| `grift verify` | `.grift/report.json` を同条件で再計算し改ざんを検出（VERIFIED / MISMATCH / CANNOT_VERIFY） |
| `grift contribute` | `.grift/report.json` からprofile別payloadを組む。既定はlocal書込のみ。**`--open`** は明示network経路として本人のforkへpushし、PR作成ページを開く（最終ボタンは本人） |
| `grift update` | grift-cli 自身を明示的に更新。`--check` は最新版の表示だけを行う唯一の update-check 経路 |

- **`.grift/` は出力専用ディレクトリ**です（無ければ自動作成）。リポジトリの `.gitignore` に `.grift/` を追加することを推奨します
- カスタム指定（対象パス・スコープ・出力先を明示）は従来どおり引数・オプションで: `grift analyze path --scope tenant --identity .tep/identity.toml --out dir`
- 明示パス付きの `grift analyze REPO` では `--scope tenant`（既定）: `.tep/identity.toml` に載った人の仕事 = **証拠用**／`--scope repo`: bot 以外の全人間コミット = **プロセス観測・参照分布用**

参照分布 v2026.09 は **repo スコープ同士**でのみ照合する。tenant の値を repo 分布に載せない（混ぜたら分布が嘘になる）。

## v0.7.0 で加わったもの

v0.6.0 の面はすべて残ります。詳細と移行時の注意は [docs/migration-v070.md](docs/migration-v070.md) を参照してください。

### チームの充足ギャップ（`grift align --team`）

宣言された要求をチームが覆えているかを **人数のみ** で出します。個人の測定値は匿名の最大値としても出ません。3 名未満では `not_observed`（`reason: insufficient_team_size`）を返し、個人を特定しうる数を出しません。入力は **report-v2 のみ**で、`grift actor ID REPO --out DIR` が書く `actor-card-v1` は拒否します（card は surface 観測を持たず、読ませると全要求が `not_observed` になり「チームを測った」ように見えるため）。

```bash
# メンバーごとに report-v2 を作る（--format json の stdout が report-v2）
grift actor alice . --identity .tep/identity.toml --format json > team/alice.json
grift actor bob   . --identity .tep/identity.toml --format json > team/bob.json
grift actor carol . --identity .tep/identity.toml --format json > team/carol.json
grift align --team --actor-dir team --project-report project-out/project.json
```

### 納品結果の申告（`--outcome-declaration`）

`grift repo` と `grift actor` にだけ付きます。渡した内容は必ず `kind: "declared"` として記録され、観測にはなりません。**`grift verify` はこのブロックを比較しません**。宣言を書き換えても verify は検知しません。`grift project` / `grift align` に渡すと `unrecognized arguments` になります。

```bash
grift repo . --outcome-declaration .tep/outcome.toml --format json
```

### 導入ライブラリの普及率（`library_context`・actor scope）

その Actor が導入したライブラリが参照コーパスでどれだけ普及しているかを出します。**ライブラリを記述するのであって、人を記述しません。** actor scope の出力にだけ現れます。

```bash
grift actor candidate_001 . --identity .tep/identity.toml --format json
```

### 提出目的の選択（`grift contribute --purpose`）

提出データの目的を提出者が選びます。`reference-distributions`（無指定時の既定・v0.6.0 と同じ意味）と `outcome-linkage` の 2 つです。`outcome-linkage` は `--door public-pr` では使えません（公開受け口の schema がまだ v0.6.0 の値だけを受けるため、組み立てた後に受け口で弾かれる前に断ります）。

```bash
grift contribute --purpose outcome-linkage --door local
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
詳細とJSON例は[ローカルexport契約](docs/input-export-schema.md)を参照してください。

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

report-v1とexport-v1は既存キー・値の追加互換を維持します。report-v2と新規v0.6
成果物はDraft 2020-12の閉じたschemaで未知キーを拒否します。詳細は
[docs/report-v2.md](docs/report-v2.md)を参照してください。

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
は、context×role×period×evidenceの複数repo台帳を作ります。同一主体の結合は
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

## 実レポート例

自リポで `grift analyze . --format md` を実行する。各数値に単位と provenance（method=TEP・tool=grift・定義版・分析 SHA・`analysis_scope`）が付く。

## 終了コードと stdout / stderr 規約

| 終了コード | 意味 |
|---|---|
| 0 | `VERIFIED` またはコマンド成功 |
| 1 | `MISMATCH`（検証対象の不一致） |
| 2 | `CANNOT_VERIFY`、使用法エラー、または入力契約違反 |
| 3 | 再開可能な公開取得の安全な途中停止（PARTIAL） |

`--format json` の stdout は **JSON 1 件のみ**（機械消費向けの純度保証）。`--format md` は markdown のみ、`--format both` は markdown → 空行 → JSON の順。診断とエラーは常に stderr。`--out DIR` を使っても stdout 規約は変わりません。単一reportはコマンド固有の固定名、Actor collectionは上記の閉じた構成で追記します。

report-v1の全フィールド定義は[docs/report-schema.md](docs/report-schema.md)
（凍結済み・追加互換）、report-v2とActor collectionは
[docs/report-v2.md](docs/report-v2.md)（閉じたschema）です。

## 機械取込用 export（opt-in）

`grift analyze <repo> --export <dir>` で commits.ndjson（1行=1コミット・origin/actor/cochange）・actors.json（canonical_id ごとの帰属と活動）・export-meta.json（`config_digest` つき）を書く。**生メールアドレス・生 author 文字列は一切出力しない**。顧客向け叙述に載る数値は report.json の集計値が正。詳細は [docs/export-schema.md](docs/export-schema.md)。

## データ提出（grift contribute・明示的 opt-in）

**TEP Report 集計と参照分布 vNext** への提出は、profile と door を先に固定します:

```bash
grift report                                  # ① repo スコープの report を作る
grift contribute --privacy aggregate --door public-pr --out .grift/contribution.json
# ③ payload を [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions) に PR で提出
```

- `analyze` / `report` はofflineです。`repo` / `actor` は既定offlineで、`--fetch-public` または `--resume-public-evidence` を明示したときだけForge APIへ接続します。`verify`は保存bundleを再生し再接続しません。ほかの明示network経路は `update --check`、`contribute --open`、cosign keylessだけです。暗黙update checkはありません
- CLIから当社への自動送信は恒久にありません。`contribute --open`の明示経路も本人のforkまでで、PR作成の最終ボタンは本人が押します
- `report-v1` は既存 `tep-contribution-v1` を維持します。`report-v2` の既定 `aggregate` はActor行、repo/remote/OID、正確な時刻、source digestを落としたbucket集計です。`named-public` は本人の明示authorityがあるprovider-neutral project/accountだけを保持します
- `masked` は32 byte以上のHMAC鍵をpermission検査済みfile/FDから読み、`raw` とともに `local` / `controlled` 専用です。研究用のsource対応はpermission 0600のcontrolled sidecarへ分離され、`public-pr` はhard errorです。認可済みcontrolled destinationがないため自動uploadは実装していません
- `--open` は明示的に本人の GitHub 権限でforkへpushし、最終ボタンは本人が押します。代理PR経路は提出者identityを非公開にしてもpayload自体は公開されます。公開後は既存clone/forkを含むGit履歴から完全撤回できません
- 受け口リポの CI はlegacy v1とpublic-safeなv2 `aggregate` / `named-public`だけをmode別allowlistで受理し、masked/raw、メール、内部Actor ID、credential形状を拒否します
- 用途は「TEP Report 集計と参照分布 vNext」に限定。保持期間は次回年次 Report まで・撤回は issue で受け付けます（`docs/norms.md` 保持・削除条項）

例（click、tenant スコープ。ゴールデン G1）:

- test co-change: 0.2664 ratio（73 of 274）
- corrective rework: 0.0109 ratio（3 of 274）— 観測値。証拠主張ではない
- path retouch: 0.573 ratio — 観測のみ

母数 20 未満では率も分布位置も出さない（`insufficient_population`。件数の生表示のみ）。

## Shared block の扱い（仕様）

Shared block（レポート冒頭 3-5 行のコピペ要約）には **gloss（説明）を付けない**。経歴書や issue にそのまま貼ったとき自己説明的な長文になるより、簡潔さ・貼りやすさを優先するため。各数値の意味は本文の行末 gloss と [docs/metrics-guide.md](metrics-guide.md) が担う。

## 指標の読み方（非エンジニア向け）

すべての指標について「何を測っているか・高い/低いで何がわかるか・公開リポジトリ117件の分布上の目安」を [docs/metrics-guide.md](docs/metrics-guide.md) に平易にまとめています。初めてレポートを見る方はまずこちらを。誤読しやすい点（例: corrective rework はバグ件数ではない、dormant は放置ではない）も表にしてあります。

## 指標と限界

| 指標 | 何の証拠か | 限界 |
|---|---|---|
| origin / 帰属 | 誰の仕事か | identity 未設定は unresolved。Cor 実メールは同梱しない |
| test co-change | 本番変更にテストが伴うか | テスト基盤なしは not_observed。母数<20 は率も十分位も出さない（`insufficient_population`） |
| corrective rework | 件名が fix/revert の直近パス回帰（観測） | **証拠主張から降格**。件名規約依存の交絡あり。バグ件数ではない。再挑戦は v0.6 行レベル |
| path retouch | 同一ファイル再接触 | 観測のみ。証拠主張に使わない |
| survival (τ=180d) | 行の残り方 | `--survival` のみ。参照分布は **v2027 予定**。今回の公開分布には含めない |

参照位置は「第N十分位」の1行だけ。n<30 の指標は位置を出さない（`reference_too_small`）。現行 v2026.11 の観測 n: test co-change 68 / corrective rework 101（観測）/ survival 0（v2027 予定）。旧 v2026.09 は不変のまま `--reference-version` で選択可能。

## 判別力の現況（repo スコープ・基準 `5f2665e`）

出典: `corpus/DISCRIMINANT-v2026.11.md`（n=117・v2026.09 全行 + v2026.11 admission 70 件）。verdict はファイルから逐語。

- `test_cochange A vs D` → `separated`（median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18）— **初めて n が立った分離**。「量は誰でも作れる」テーゼの最初の強い実証
- `test_cochange A vs C` → `fail_tier2`（median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21）— v2026.09 では `separated`（δ 0.7143）だったが、C 群が「tests を持つ AI 駆動 repo」に広がり分離が低下。**登録済み基準は下げず転回をそのまま公開する**
- `corrective_rework A vs C / A vs D` → 方向要件なし（観測専用・v0.5.0 から不変）。A vs C δ -0.8333 / A vs D δ 0.0139
- 母数の正直な記録: C narratable = 14（目標 30 に不足・admission 実測で訂正）/ D total 29（目標 20 達成）
- survival: 参照分布は v2027 予定

v2026.09 の記録（Run 2: A vs C `separated` ほか）は `corpus/DISCRIMINANT-v2026.09.md` に履歴として残してある。

## GitHub Action（観測のみ）

```yaml
permissions:
  contents: read
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
      persist-credentials: false
  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
  - uses: Cor-Incorporated/grift-cli@v0.7.0
    with:
      scope: repo
      comment: false
```

この参照はv0.6.0のannotated tag公開後に有効です。PR、merge、tag、PyPI公開は別の
人間ゲートであり、source treeに0.6.0実装があるだけではrelease済みを意味しません。

- 呼び出し元repoの完全履歴とPython 3.11以上が必須。未checkoutまたはshallow cloneは計測前にfail-closed（exit 2）
- `grift analyze` を実行し、**$GITHUB_STEP_SUMMARY に共有ブロック**を出力、report.md / report.json を artifact に upload
- 観測値を合否・閾値へ変換しない。入力・履歴契約違反はfail-closedする
- CI dogfoodは`contents: read`、`comment: false`で実行し、PR管理下コードへwrite tokenを渡さない
- `comment: true`経路は実装済みだがread-only dogfoodでは未実証。信頼済みpost-workflowを設計するまでPR管理下コードへwrite権限を付けない

## サポート / Support

- golden identity（再現検証用の公開コミットメタデータ由来メール）の削除依頼などはpublicリポのissueでお知らせください。代理連絡では提出者identityを非公開にできますが、公開corpus payload自体がprivateになるわけではありません
- Removal requests (e.g. for golden identity emails derived from public commit metadata): please open an issue on the public repository; see the tep-contributions README for the private contact channel.

## 倫理

- 実在個人のスコアカード・順位表は公開も内部共有も禁止
- 等級語彙（シニア/ジュニア/素晴らしい）を出さない
- コーパスの manifest（リポ名+SHA）は再現用に公開してよい。**個別リポ値のリーグテーブルは公開しない**
- 対照群 E（私的 ground truth）はこのリポに入れない

## 公開状態

- 公開リポ: https://github.com/Cor-Incorporated/grift-cli
- コマンド名: **`grift`**（方法論名 TEP はレポートに残す）
- PyPI: 配布名 **`grift-cli`**。本source treeのv0.6.0は未releaseであり、公開済み版は[PyPI](https://pypi.org/project/grift-cli/)で確認してください

## License

MIT. See [LICENSE](LICENSE).
