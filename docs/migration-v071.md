# v0.7.1 移行

既存の `analyze` / `report` / `verify` / `contribute` は report-v1 のまま動く。
v0.6.0 / v0.7.0 の面はすべて残る。本書は v0.7.0 移行の内容を引き継いだ上に v0.7.1 の差分を加えたものである。

## v0.7.1 の差分

**面は 1 つも増えない。** v0.7.1 は公開 Forge 取得の 2 つの欠陥を直す
patch release である。CLI フラグ・出力スキーマ・payload の形は変わらない。

### bot / app アカウントで `--fetch-public` が落ちなくなる

GitHub の commit author が Bot / app installation
（`Copilot`、`dependabot[bot]`、`renovate[bot]`、`github-actions[bot]`）の
場合、`html_url` は `https://github.com/apps/<slug>` を指し、handle は
角括弧を含む。v0.7.0 はこの行にも public account を付けようとして
`profile_url` が空の account を作り、actor 成果物の生成が
`account '<provider>|<host>|<id>' needs a handle and profile URL` で
落ちていた。fetch は成功しているのに report が 1 つも出ず exit 2 になる。

v0.7.1 はこれらの行を **public account にしない**。commit は
`unlinked_commit_count` に数える。人の account が handle と
canonical な profile URL を必ず持つ条件は変えていない。

**bot は v0.7.1 でも public account にはならない。** bot の commit を
「誰かの貢献」として数え直したのではなく、public account の欄を
空にしたまま unlinked として数える。git 側の bot 判定
（`report.bot`）は従来どおり別に動く。

### 切れた転送を検出し、有限回リトライする

GitHub の commits ページは 1 ページ約 400KB あり、転送が宣言した長さに
届かないまま終わることがある。実測で `Content-Length: 436443` に対し
受信 372299 バイト、次の `read()` は即 `b""`。v0.7.0 はこの切れた bytes を
そのまま JSON として読み、`Forge response body is not valid UTF-8 JSON`
という「Forge の応答が壊れている」形のエラーを出していた。実際は
転送が途中で終わっただけである。

v0.7.1 は受信バイト数を `Content-Length` と照合し、足りなければ
`ForgeTruncatedBodyError` として扱う。**切れた body を JSON デコーダに
渡さない。** そのうえで収集ループが同一 request を最大 3 回まで試す
（backoff 0.5s / 1.0s）。使い切った場合は従来どおり
`stop_reason: transport_error:ForgeTruncatedBodyError` で止まり、
coverage は `complete` にならない。`TimeoutError` など他の transport error も
同じ扱いである。`Content-Length` を宣言しない chunked 応答は従来どおり
EOF が唯一の終端で、そのまま受け取る。1 ページあたりのバイト上限は
hard stop として残る。

発生頻度は環境依存である。ある環境では同一 URL 25 回中 2〜3 回、
別の環境では 145 回中 0 回だった。「もう起きない」ではなく
「起きたら検出して数回やり直す」である。

リトライ回数は bundle manifest に記録しない。`public-evidence-v1` の
page（`$defs.public_page`）は `additionalProperties: false` の閉じた
オブジェクトで、キーの追加は patch release での契約変更に当たるためである。

### 手当てが要る場合

**bot commit を含む repo は、account linkage の観測値が v0.7.1 で変わる。**
bot / app アカウントを public account にしなくなったので、
`provider.sha-to-account` と `account.commit-linked` が減る
（実測: cloudflare 661 → 657、vite の 1 ページ収集 100 → 94）。
`actors.full` や `report.human_nonmerge` などの git 側の観測値は変わらない。
これらの数値を保存している場合は **v0.7.1 で収集をやり直す**。

v0.7.0 で `--fetch-public` が exit 2 または
`Forge response body is not valid UTF-8 JSON` で失敗した収集も、
証跡が残っていないので v0.7.1 でやり直す。

上記に当たらない、すでに完了した bundle の再取得は不要である。

## v0.7.0 の差分

### 出力が増える（既存フィールドの意味は変えていない）

| ブロック | scope | 内容 |
|---|---|---|
| `library_context` | actor | 導入したライブラリが参照コーパスでどれだけ普及しているか。ライブラリを記述するのであって人を記述しない |
| `outcome` | repo / actor | `--outcome-declaration` を渡したときだけ。必ず `kind: "declared"` で、観測にはならない |
| `verification_profile.test_type_share` | repo / actor | テスト種別ごとの commit 割合。下記「`test_type_share`」を読んでから使うこと |

report-v2 を strict に検証している消費側は、このキーの追加で落ちる可能性がある。

### `--outcome-declaration` が付く scope は `repo` と `actor` だけ

`grift project` と `grift align` には付いていない。渡すと argparse が拒否する。

```console
$ grift project . --outcome-declaration outcome.toml
grift: error: unrecognized arguments: --outcome-declaration outcome.toml
$ grift align --actor-report a.json --project-report p.json --outcome-declaration outcome.toml
grift: error: unrecognized arguments: --outcome-declaration outcome.toml
```

project report は宣言された要求を記述し、alignment report は保存済み 2 report
の上のビューであり、どちらも `report_outcome` を出さない。フラグをそこにも
提供すると、ファイルを受け取り、何も読まず、outcome の無い report を返す
ことになる。それは「何も宣言されなかった」と読める（norms §1）。
根拠は `src/tep_cli/options.py:123-143`（`add_outcome_declaration` の docstring と、
それを呼ぶのが `repo` / `actor` の 2 parser だけであること）。

### `outcome` は `grift verify` の検査対象ではない

`grift verify` は観測を再計算して突き合わせる。宣言された outcome には
再計算する元が無く、verifier には宣言ファイルが渡されないため、
**`grift verify` は `outcome` ブロックを比較しない**。diff から外してある。

```python
# src/tep_core/verify.py:45
NOT_RECOMPUTED_PATHS = {"outcome"}
```

したがって **宣言を書き換えても verify は MISMATCH にならない**。
report 自身がこの限界を毎回明記する（`src/tep_core/outcome.py:80-84`）:

```text
Declared outcomes are not observations. `grift verify` neither recomputes
nor compares them; a modified declaration is not detected by verify.
Their absence is not evidence that work did not ship (norms §1, §3).
```

「再計算しない」だけを読むと保護のように見えるが、逆である。ここでは
何も検査していないので、変更を検知するものが無い。outcome を根拠に
使う受領者は、verify の VERIFIED をこのブロックの保証と読んではならない。

### `verification_profile.test_type_share`

`verification_profile` に新設した。分母は **テストを触った commit 数**である
（`denominator_definition = "commits that touched at least one test path"`,
`src/tep_core/verification_profile.py:105-121`）。

**各 type の share は独立に割るので、合計は 1 にならない。** 1 commit が unit と
e2e の両方を触れば両方に 1 ずつ加算される（type ごとの集合を commit 単位で
取るため）。読み手は値を足してはならない。

これ以前は `test_type_distribution` が commit 数しか持たず、type に対して床を
宣言しても比較する share が無かった。`alignment._obs_share` は share を探して
見つけられず、**非ゼロの type すべてを `not_observed`、ゼロの type だけを
`below_declared`（`observed_zero` 由来）にしていた**。実際に手を動かした type が
「未測定」と読める逆転である。`test_type_share` の新設でこれを直した。

母集団が `MIN_POPULATION_FOR_RATES` 未満のときは
`not_observed(insufficient_population)`、テストを触った commit が 0 のときは
`not_observed(no_test_touching_commits)` であり、0.0 という値は出さない。

### 切り詰めた履歴の扱いが変わる（**過去の出力に影響する**）

shallow クローン（`actions/checkout` の既定 `fetch-depth: 1` を含む）では、
リポジトリ全体を主張する 8 フィールドが `not_observed / history_incomplete` に
degrade する。v0.6.0 では取得できた範囲の値を `observed` として出していた。

CI で生成した v0.6.0 の証跡がある場合は
`provenance.revision_completeness.shallow` を確認すること。`true` なら
`repo_age_days` / `first_commit` / `resolved_human_actors` などは誤っている。

### promisor clone では「完全」と「不完全」が同じ report に同居する

promisor（`--filter=blob:none` / `--filter=tree:0`）では、判定が 2 つ別々に走る。

| ブロック | promisor での状態 | 理由 |
|---|---|---|
| `context_profile.repo_age_days`、`scale.first_commit`、`activity.*` など commit 由来の値 | **observed のまま** | `revision.commit_history_complete` は promisor を不完全と数えない。commit graph は完全で、commit 数・日付・author は正確である（`src/tep_core/revision.py:46-64`） |
| `experience` / `role_profile` / `library_context` | **`not_observed(history_incomplete)`** | これらは blob を読む。`experience_collect` は promisor を明示的に拒否する（`src/tep_core/experience_collect.py:166-167`） |

**これは矛盾ではない。測っている対象が違う。** 「履歴は完全か」という問いは、
commit graph について訊けば promisor では yes、file 内容について訊けば no になる。
両方の判定がそれぞれ正しい結果を返しており、片方に合わせて他方を degrade させる
のは「測ったものを報告しない」という逆向きの誤りになる。

shallow clone では両方が不完全になるので、この同居は起きない。

### `grift align --team`

宣言された要求をチームが覆えているかを、人数のみで出す。個人の測定値は
匿名の最大値としても出ない。3 名未満（`complementarity.MIN_TEAM_SIZE = 3`）では
`not_observed`（`reason: insufficient_team_size`）を返し、個人を特定しうる数を
出さない。exit code は 0 である（hard error ではない）。

#### 入力は report-v2 であって actor card ではない

`--actor-dir` に渡すディレクトリの中身は、次のどちらかになる。**分岐を間違えると
拒否される。**

| 生成コマンド | 出力先 | schema | `--team` |
|---|---|---|---|
| `grift actor <ID> <repo> --identity <toml> --format json` | **stdout** | `report-v2` | 受理する |
| `grift actor <ID> <repo> --identity <toml> --out DIR` | `DIR/actors/<id>.json` | `actor-card-v1` | **拒否する** |

card を渡すと次で止まる（`src/tep_cli/subject.py:1097-1101`）:

```text
align --team requires report-v2 actor reports; actor-card-v1 carries no surface
observations. Produce one per member with: grift actor <ID> --identity <toml> --format json
```

card には `surface_profile` が無いため、読ませると宣言された要求がすべて
`not_observed` になる。読むことは拒否することより悪い ―― 出力が「チームを
測った結果」の形をしてしまうからである。

正しい作り方:

```bash
mkdir -p team
grift actor alice . --identity .tep/identity.toml --format json > team/alice.json
grift actor bob   . --identity .tep/identity.toml --format json > team/bob.json
grift actor carol . --identity .tep/identity.toml --format json > team/carol.json
grift align --team --actor-dir team --project-report project-out/project.json
```

#### identity は identity-v2 で consent と authority が要る

`experience` / `role_profile` を observed にできるのは、閉じた identity-v2 の
`consent` + `authority` の対を記録した行だけである
（`src/tep_core/identity.py:88-103` の `has_recorded_explicit_consent`）。
identity-v1 の行は読めるが、consent 証拠にはならない。

最小の `.tep/identity.toml`（identity-v2 は未知キーを拒否する。actor 行に
書けるのは `canonical_id` / `emails` / `email_sha256` / `github_login` /
`attribution_state` / `consent` / `authority` だけ）:

```toml
schema_version = "identity-v2"

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "claimed"          # verified か claimed のみ consent を持てる
consent = "recorded-explicit-consent"  # この文字列以外は拒否される
authority = "subject-authorization"    # または "repository-owner-authorization"
```

これはローカルの申告であって、申告者の身元・本人性・実世界の同意の証明ではない。

### `grift contribute --purpose`

提出データの目的を提出者が選ぶ。無指定時は v0.6.0 と同じ意味になる。

| purpose | 使える door |
|---|---|
| `reference-distributions`（既定） | `local` / `controlled` / `public-pr` |
| `outcome-linkage` | `local` / `controlled` |

`outcome-linkage` を `--door public-pr` に渡すと hard error である。公開受け口の
schema が v0.6.0 の単一値のまま pin されているためで、通せば payload を組み立て、
開示し、提出者が確認した後で受け口に弾かれる。ここで断るのは受領者ではなく
提出者の時間を使う選択である。norms の話ではなく、受け口の現状の話である
（`src/tep_core/contribution_v2.py:85-105`）。受け口の schema が受理する日に広げる。

### ベンチマーク主張の読み方

`evidence/v070/benchmark.json` の主張は、測った範囲までしか主張していない。
特に次の 2 件は、そのまま一般化すると誤読になる。

**`offline` は Python プロセス層のみ。** この項目が測っているのは、既定の解析経路が
Python プロセスから socket を開かないことだけである
（`measured.scope = "python_process_only"`、`watched_audit_events` は
`socket.connect` / `socket.getaddrinfo` / `socket.gethostbyname` / `urllib.Request`）。
**git subprocess の通信は測っていない**（`git_subprocess_network = "not_measured"`）。
git は `GIT_NO_LAZY_FETCH=1` の下で走るが、この項目はその効果を検証していない。
「grift はネットワークに触れない」という一般化された主張の根拠には使えない。

**δ = -0.7871 は v0.7.0 では再現できない。** `validity-person-signal` の
`cliffs_delta = -0.7871`（352 pair / 41 repository / 300 actor）は
`role-profile-v1` の上で、v0.7.0 の同意ゲートより前に測った値である。
`reproducibility` は `not_reproducible_on_this_version` であり、理由は次のとおり:

```text
v0.7.0 emits role_profile only for actors with a recorded explicit consent
(identity-v2 `consent` + `authority`). The study corpus is public OSS contributors
with no such record; re-measuring would require asserting consent on their behalf,
which the project refuses to do.
```

つまりこの数値は v0.7.0 の挙動の証拠ではなく、v0.7.0 で再測定する手段も無い。
現行版の主張として引用してはならない。

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
experience/roleをobservedにできる明示Actor行は`attribution_state=verified|claimed`
だけで、consent basisにもstateを記録します。`inferred|external|unresolved|bot`は
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
