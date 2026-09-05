# Grift CLI v0.6.0 要求・反証・証跡台帳

最終更新: 2026-08-31（第4回・横断完了監査）。これは v0.6.0 の release 判定 SSOT である。
旧 `HANDOVER-v060-completion-20260830.md` と
`HANDOVER-v060-public-actor-integrity-20260830.md` のGO/受入表現はsupersededとし、
コードの存在や過去の成功ログだけでは本台帳をPASSにしない。現在の閉鎖項目、
優先順位、受入条件は `docs/V060-CLOSURE-LEDGER-20260831.md` を正とする。

現判定は **NO-GO**。第2回時点の「PR_READY 相当」と、第3回時点の
「ローカル実装・反証・実repo行列・package・golden・既存CIは緑」という表現を撤回する。
横断監査で発見済みの技術・契約・証跡欠陥36件と人間ゲート6件を固定し、監査時点のForge focused
testは33 passed / 4 failed、blind pilotはready 0 / blocked 14である。既存scenario、
package hash、exact-head note、live provider結果は旧sourceの履歴であり、final sourceの
証拠ではない。全原子要件と36件の発見済み欠陥の閉鎖、final clean SHAの全gate、
remote exact-head、必要な人間ゲート
が揃うまで`PR_READY`、`RELEASED`、`LIVE_EVIDENCE`、`ISSUE_CLOSEABLE`へ進めない。

> **2026-09-01 訂正:** 上記36件は全原子要件ではなく、発見済み欠陥の件数である。
> 承認計画の全項目を原子要件へ分解する独立網羅監査で未割当候補が見つかったため、
> 「要求を全て洗い出し済み」という主張を撤回する。未割当0・弱い受入条件0の
> 一対一表を確定するまで、欠陥修正の進行数を要求網羅率として扱わない。

以下の第3回レビュー表と要求表は「実装箇所と過去の検査」を残す追跡表である。
現在状態は各行の `REOPENED` / `FINAL_VERIFICATION_PENDING` と閉鎖台帳を優先する。

## レビュー指摘（2026-08-31）と対応

| # | 深刻度 | 指摘 | 対応 | 状態 |
|---|---|---|---|---|
| R1 | CRITICAL | intake validator が score/hire/verdict・偽 digest・任意 measurement を受理 | digest完全一致・allowlist閉包・判断語彙全面拒否・生数値拒否・poison負例固定（tep-contributions PR #5）。本体と受理側のimmutable SHAをsibling checkoutし、8ケースをsocket deny下で実行 | IMPLEMENTED / sender最終SHA・built-wheel・process egressはREOPENED（REL-06） |
| R2 | HIGH | 公開inferred actor を「本人証拠ビュー」と誤表示・alignment が無条件で同意identity注意 | 5状態（public inferred / self-claimed / admin-authorized / explicit nonconsent / fail-closed unknown）をJSON・Markdown・stderrで分離。本人向け文言はclaimedだけ、CLIは同意・本人性を証明しない | IMPLEMENTED / final focused・full再計測待ち |
| R3 | HIGH | SSOT 自身が NO-GO なのに報告が PR_READY と矛盾 | 本ヘッダで撤回。blind pilot は pre-release gate のまま（post-release への変更はプロダクトオーナー判断） | ADDRESSED |
| R4 | MEDIUM | 通常CIはmerge refのみで、PR headそのものの実行証跡がなかった。sdist hashはrun-specific | 独立`exact-pr-head` jobがPR head SHAを明示checkoutし、actual=expectedを検査して同じ非golden suiteを実行する。さらに同SHAを`repo --actors --rev`で自己観測し、`verify`往復とdigest付きartifactをupload。通常jobのmerge-ref検査とは分離。hash確定はPyPI再取得のみ | REOPENED: golden/action/packageまで同一exact headへ束縛（REL-04） |
| R5 | MEDIUM | action-dogfood がcomposite actionを実際に呼んでいなかった | read-only jobが`uses: ./`、`install-source: checkout`、`comment: false`で実呼出しし、report/shared-blockとguard ledgerを検査・uploadする。PR write tokenを使う`comment: true`とPyPI pin canaryは別のtrusted/post-publish gate | REOPENED: report/Markdown/shared block artifact不足（REL-05） |
| R6 | LOW | PR 全差分の whitespace 検査が失敗（3件） | 修正済み。`git diff --check merge-base..HEAD` が exit 0 | FIXED |

## 状態語

`NOT_STARTED` / `IN_PROGRESS` / `IMPLEMENTED` / `LOCALLY_VERIFIED` /
`NOT_PROVEN` / `PR_READY` /
`MERGED` / `RELEASED` / `LIVE_EVIDENCE` / `ISSUE_CLOSEABLE` を区別する。
人間ゲートが残る項目は、ローカル成功後も `NOT_PROVEN` と併記する。

## 要求トレーサビリティ

| ID | 要求 | 実装・schema | 反証 scenario | 状態 |
|---|---|---|---|---|
| ACT-01 | 固定 OID の repo-local primary-author partition。provider は partition を変更しない | `attribution.py`; actor index/card schemas | 同一email異名、同名異email、partial/full digest一致 | REOPENED（ACT-02、SEC-09、REL-01/10） |
| ACT-02 | fixed tree の `.mailmap` と明示 alias だけで複数emailを統合 | `attribution.py`; `identity.py` | mailmap統合/分離、working-tree mailmap無視 | REOPENED（ACT-05） |
| ACT-03 | SHA-1/SHA-256 generic OID と credential-free repo scope digest | provenance + schemas | SHA-256合成repo、userinfo remote | REOPENED（ACT-01） |
| FORGE-01 | provider-neutral GitHub/GitLab adapter、固定OID、全pagination | `forge.py`; `public_fetch.py` | GitHub/GitLab fixture、5/62 pages | REOPENED（SEC-03/04/09、REL-01/10） |
| FORGE-02 | public bundle CAS、sanitized request/body digest/rate/coverage、0600 | public-evidence schema | token/header/cross-origin Link、1-byte tamper | REOPENED（SEC-01/02/04/07/08） |
| FORGE-03 | replay/verifyはsocketなし。0/1/2、partial=3 | `verify.py`; CLI | offline socket refusal、missing/body/manifest tamper | REOPENED（SEC-03/05/06/10） |
| OUT-01 | `repo-report.*`、`actor-index.*`、`actors/*`の全数/選択数/digest一致 | actor collection schemas; ID directory output=`explicit`; consent-gated detail再計算 | all/top/id排他、path/symlink/unregistered file、自己整合detail改ざん | REOPENED（REL-10）: verifyは8/8拒否したがalignが同じ8改ざんを8/8受理。入力時full collection検証の修正中 |
| ID-01 | identity-v2 email hash、XOR、actor間重複・未知key拒否、v1 read互換 | `identity.py`; identity-v2 schema | plaintext/hash混在、不正hex、重複 | REOPENED（ACT-07） |
| ID-02 | v0.6 subjectのidentityは明示fileまたは固定repo treeだけ。CWD/working-tree混入なし | `identity.py`; subject/verify loaders | 別repo+CWD負例、fixed repo/explicit正例、checkout改ざん | REOPENED（ACT-02/07） |
| EXP-01 | rename/copy/re-add/delete、30/180日、tag、AI/human coauthorを固定定義で計測 | `experience.py`; fixed-tree `ai-identity-v1` | 境界時刻、email/hash AI正例、未宣言human、working-tree AI無視 | REOPENED（ACT-02/03/04） |
| EXP-02 | denominator<20抑制、explicit `verified|claimed` + `consent=recorded-explicit-consent` 以外 not_observed（CLIは記録を検証し、現実の同意・本人性を証明しない） | identity/experience/role schemas | n=19/20、state/authorityのみ、inferred/external/unresolved、identityなし/public actor | REOPENED（ACT-07、REL-08/09） |
| ROLE-01 | domain/work-type/time/process の4次元だけ。score/fit/rankなし | `role_profile.py` | 禁止語彙・算術・期間三等分 | IMPLEMENTED / FINAL_VERIFICATION_PENDING（REL-08/10） |
| ATT-01 | canonical statement + detached SSH/cosign、受領者trust必須 | `attest.py`; attest schema | statement/report/signature/policy/repo改ざん | REOPENED（DATA-08）。keyless OIDCはHUM-03 |
| PORT-01 | context×role×period×evidence台帳。宣言/attestだけで主体結合 | `portfolio.py`; portfolio schema | 2repo、digest/duplicate/subject改ざん | REOPENED（DATA-07） |
| CON-01 | aggregate/named-public/masked/raw と door allowlist | `contribute.py`; contribution-v2 schema | public masked/raw、raw email、unknown key | REOPENED（DATA-01/04/05/06、REL-06） |
| CON-02 | masked HMAC key file/FD、32 bytes、permission、controlled sidecar | `contribute.py` | arg/env漏洩、cross-repo linkage、sidecar欠落 | REOPENED（DATA-01/02/03） |
| EXT-01 | forge/tracker export-v2はprovider/host/project/OID/window/coverage bound。repo/actorはprovider-neutral eventを集計し、actorはcanonical ID完全一致だけ。trackerは閉じたstate/link/duration遷移 | `forge.py`; `tracker.py`; `analyze_v2.py`; export/report schemas | v1・別repo・混合source、duplicate/missing/nonfinite/broken link/negative・不一致duration/out-of-order拒否、nonempty repo/actor/project/align | IMPLEMENTED / FINAL_VERIFICATION_PENDING（REL-10） |
| SCH-01 | 新規v0.6 schemaはclosed Draft 2020-12、stdlibとjsonschema cross-check | `schemas/*.json`; `schema.py` | unknown key/mutation corpus | REOPENED（SEC-05、REL-03/10） |
| GOLD-01 | v0.5 report-v1 19件凍結、新runnerはCLI実行、全fixture hash登録 | golden runner/manifest | missing/unregistered/hash mismatch、D0-D4 | REOPENED（REL-03/04/10） |
| PKG-01 | version.py SSOT、sdist/wheel allowlist、runtime assets resources読込 | `pyproject.toml`; package smoke | dirty sentinel、member/secret scan、clean venv | REOPENED（REL-02/04/10）。確定hashはtag→PyPI再取得後のみ |
| NET-01 | 測定時の暗黙update checkなし | CLI | urlopenを例外化したanalyze | IMPLEMENTED / FINAL_VERIFICATION_PENDING（REL-10） |
| DOC-01 | README日英/norms/guideに境界と価値翻訳 | docs | claim/schema/version consistency | REOPENED（REL-07/09）。公開collection許可と単一Actor限定のnorms矛盾は `7564d1d` で修正、final全claim parity待ち |
| REL-070 | v0.7.0 のリリース版数と定義版数を上げる。`__version__` = 0.7.0 / `DEFINITION_VERSION` = tep-v0.7.0-2026-09-03。golden baseline の drift は版数文字列 3 行のみで、観測値は 1 つも変わらない | `version.py`; CHANGELOG; `docs/migration-v070.md` | golden runner の drift 分類（D3×1 tool_version / D4×2 definition_version、D0-D2 = 0） | LOCALLY_VERIFIED（`test_v060_release_consistency.py` green、`scripts/v070_benchmark.py` self-contained 6/6 hold、監査 13 件対応済み（BLOCKS 4 / SHOULD 5 / NOTE 4）、統合 branch `feat/v070-integrated`） |
| GRIFT-01 | 0.5.1 chainと0.6利用契約を#65/#2055へ一件ずつreadback | issue comments | URL/body/readback | REOPENED（REL-11）。既存comment bodyは旧状態のため最終SHA後に同じcommentを更新 |

## schema・互換性の不変条件

- report-v1 / export-v1は追加互換。既存キー・値・意味を変更しない
- v0.6新規成果物はDraft 2020-12のclosed schema。schemaが定義したmap slot以外の
  未知キーを拒否する
- strict Actor collectionは`repo-report.*`、`actor-index.*`、`actors/*`、
  `collection-manifest.json`を分離し、既存出力先を上書きしない
- `verify`は保存public evidenceまたはActor collectionをnetworkなしで検証し、
  `0=VERIFIED`、`1=MISMATCH`、`2=CANNOT_VERIFY`、安全な取得途中停止を`3=PARTIAL`
  とする
- GitHub/GitLabはprovider-neutralな固定OID/export契約で扱い、GitLabのdocumented
  account linkage欠落を検索推測で補わない
- 明示network経路はpublic fetch/resume、`update --check`、`contribute --open`、
  cosign keylessだけ。測定時の暗黙update checkを設けない

## 実repo scenario matrix

各リンク先の `scenario-result.json` に fixed OID、repo/actorの full/selected n、
merge basis、partition digest、window、coverage、所要時間、JSON/Markdown SHA-256、
verify結果を記録する。次表は判定と主要な反証値の要約である。
期待値との不一致は「ツール誤り」「旧期待値誤り」「source drift」のいずれかへ
一次証拠で分類し、期待値に合わせる実装はしない。

> **再実行ゲート（2026-08-31・第4回監査）:** 下表の数値は旧sourceで取得した
> historical evidenceであり、現在のfinal証拠ではない。current sourceは監査時点で
> dirty、既存local/public scenarioは異なるsource treeへ束縛されているため、
> `REL-01` と `REL-10` が閉じるまで全行を `STALE_SOURCE` とする。raw provider bodyは
> 引き続きcommit対象外である。

| ID | repo / fixed OID | PR gate | 実測状態 |
|---|---|---|---|
| R01 | BenevolentDirector `a650ffa6b5921b93fcc32398ab01e0043ce962ec` | local | STALE_SOURCE: historical 3994=2607+1387、Actor 3。repo/actorだけの証拠で、tenant本人experience/roleはconsent/authority回答待ち（HUM-01） |
| R02 | grift-landing-blueprint `7efd09e22d06caa813149af891ae2001bebf6cb4` | local | STALE_SOURCE: historical 54=34+20、Actor 2 |
| R03 | grift-cli `fa9bc317cc0ac1953ed09cbab11d3de2232c2fb0` を depth 20 で shallow クローンした自己完結 fixture | local | LOCALLY_VERIFIED: PASS、33=20+13、Actor 1、`revision_completeness.shallow=true`。depth 依存 8 フィールドが `not_observed/history_incomplete` に degrade することを assert（`evidence/v060/scenarios/R03-shallow-history/scenario-result.json`）<br>旧版は外部 repo `claude-code-skills` の shallow 状態に依存しており、別作業でその repo が unshallow された時点で再現不能になった。OID と depth を pin した自前クローンに置き換えて外部依存を除去した |
| R04 | grift-cli baseline `fa9bc317cc0ac1953ed09cbab11d3de2232c2fb0` + exact PR head | local | baselineはSTALE_SOURCE。旧exact-head directoryはhistorical/non-final noteであり、final exact-headはCI artifactだけを正とする |
| R05 | cloudflare/cloudflare-os `4f42d625a994a7bff4a3091a6b06897ab2e4d79c` | GitHub full | STALE_SOURCE: historical API 667、human 663=438+225、bot 4、Actor 18。final sourceで再取得待ち |
| R06 | vite `e2b597de0ef14598901703f5aa52f8c962007d02` | forced partial | STALE_SOURCE: historical 1 page/100 of 9642。forced-partial 2-run負例とfinal source再取得待ち。provider fullはHUM-02 |
| R07 | VOICEVOX `c72a94cbcf501be054a239446c7eb8cf53be34b4` | release full | STALE_SOURCE: historical Git 1899=1810+89、Actor 118。provider fullはHUM-02 |
| R08 | kilo `323d93b29bd89a2cb446de90c4ed4fea1764176e` | local | STALE_SOURCE: historical 20=16+4、Actor 7 |
| R09 | GitLab release-cli `07d5e21c6610f781b65d7196c5d0e86e73bcc6be` | GitLab full | STALE_SOURCE: historical 453=290+163、Actor 47、account linkage=`unsupported`。final source再取得待ち |
| R10 | GitLab CLI `05e9a796977441dcede9d1cc691f55c5ff4cc07b` | release full | HUMAN_GATE（release tier は provider credential 必須） |

## Blind pilot

数値を見せる前に、所有・利用権、identity、立上げ/引継ぎ、4次元role、
AI trailer記憶を一回の質問票で取得する。未回答を一致率の分母へ入れず、
回答前にrepo別数値を開示しない。crash 0、verify成功、比較可能cell一致率80%以上、
不一致分類100%、説明不能0、survivalを除き5分未満をPR-ready条件とする。

状態: `INVENTORIED / BLOCKED / NOT_PROVEN`。事前登録DRAWの12 pickedにmandatoryの
BenevolentDirector / corswebを加えた14 repoを全件固定OIDでinventory化したが、
統合質問票の必須回答はready 0、blocked 14。権限、identity同意、4次元role、AI trailer記憶を
推論で補っていない。測定結果のproducer実行はまだ行っていない。証跡は`evidence/v060/pilot/inventory-20260831.json`と
`evidence/v060/pilot/answer-gap-20260831.json`。回答取得前は`PR_READY`にしない。

## 人間ゲート

- blind pilot 統合質問票への回答（14 repo・ready 0 のまま）
- cosign keyless OIDC
- GitHub/GitLab大規模full fetch用credential（Vite full・GitLab CLI full・VOICEVOX provider full）
- PR #64 の merge、tag、PyPI publish
- Grift production pin/merge、production image readback、live Evidence Room
- companion intake PR（tep-contributions）の CI 確認と merge

未実施は `NOT_PROVEN`。別経路で迂回しない。

## この時点の検証コマンドと実測（2026-08-31 第4回・横断監査）

```bash
git rev-parse HEAD                                       # 893168c9...（監査開始時）
git status --short                                       # dirty 8 files、+809/-47
PYTHONPATH=src python -m pytest -q <Forge focused files>  # 33 passed / 4 failed
```

上記は監査開始snapshotであり、成功したfinal acceptanceではない。full suite、v0.5
golden 19件、v0.6 golden、P0 falsify、package smoke、local/public scenarioは、36件を
閉じたclean final SHAで再実行する。過去のpassed数、package hash、scenario durationを
current値としてコピーしない。

CI に関する正確な表現: 通常の`pull_request`チェックは**PR merge ref**上で走る。
既存`exact-pr-head` jobは非golden suiteと自己解析までで、v0.5/v0.6 golden、public
registry、action dogfood、package smokeを同じheadへ束縛していない。REL-04/05を閉じ、
remote artifactをreadbackするまでexact-head統合証拠は`NOT_PROVEN`である。

`intake-contract-parity` jobは、本体のPR head（push/workflow_dispatchは`github.sha`）と
companion SHA `173fac600f3ce64e6df1ca86565f427a391810cc`（受け口 main、v2 契約 + manifest artifact 化後。旧 `520a7f8` は 0.7.0 の digest を拒否する）を別々のsibling directoryへ
full-history checkoutする。aggregate/named-publicのacceptと2件、masked/raw public door・
digest・source replay・authority・GitLab account linkageのreject負例6件の計8件を実行する。
現在のsocket denyはPython process内に限られ、native/external processのegress denyを
証明しない。またinstalled wheelではなくsource tree上で実行するため、REL-06で閉じる。
負例probeとworkload中の接続試行数はresult/ledgerに残す。
両SHA一致、clean tree、8/8、workload接続試行0のいずれかを満たさなければfail closedする。

action-dogfoodはread-only、checkout install、`comment: false`でcomposite actionを呼ぶ。
現workflowのuploadはguard ledgerだけで、report JSON/Markdown/shared blockをremote reviewerが
再検証できない。REL-05を閉じ、remote job artifactをreadbackするまで未証明とする。
write権限を伴う`comment: true`とPyPI pin canaryはこのjobの証拠ではなく、別human gateのまま。
