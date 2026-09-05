# Grift CLI v0.6.0 発見済み欠陥・完了監査台帳

最終更新: 2026-09-01

## 判定と適用範囲

現判定は **NO-GO** である。本台帳は、2026-08-31 時点の合意済み v0.6.0
契約について、公開 Forge、Actor/experience、contribution/研究データ、
attest/portfolio、schema/golden/package/CI、実 repo scenario、PR/Issue 連携を
横断監査し、2026-09-01 までに**発見・再現できた欠陥**を重複排除して固定する。
この36件は承認計画の全原子要件数ではない。承認計画を原子要件へ分解した
一対一トレーサビリティは現在再監査中であり、未割当要件が0になるまで本台帳だけを
根拠にPR-readyまたは網羅完了を主張しない。

- 発見済みの技術・契約・証跡欠陥: **36 件**
- 人間ゲート: **6 件**
- 現在値: **LOCALLY_VERIFIED 12 / IN_PROGRESS 6 / OPEN 18 / 回帰 3**
- 監査時 source: `893168c9ddde344ad33db32ad3a3253db7c7c16a`
- 監査時 dirty 差分: 8 files、`+809/-47`
- Forge focused test の既知状態: 33 passed / 4 failed
- blind pilot: ready 0 / blocked 14

本台帳を固定するまで実装差分は凍結した。以後、新しい観測はまず既存 ID へ
分類する。定義済み範囲で既存 ID に分類できない再現可能な欠陥だけを新規行として
追加し、件数と理由を同じ変更で明示する。単なる追加提案、未再現の懸念、
v0.6.0 外の機能拡張は本台帳へ追加しない。

状態語は `OPEN` / `IN_PROGRESS` / `LOCALLY_VERIFIED` / `REMOTE_VERIFIED` /
`HUMAN_GATE` とする。`LOCALLY_VERIFIED` は merge、release、live、Issue close を
意味しない。

## A. Forge・partial bundle・公開証跡（10件）

| ID | 深刻度 | 閉鎖対象 | 反証可能な受入条件 | 状態 |
|---|---|---|---|---|
| SEC-01 | P0 | private bundle の root/source/target/backup/remove が検査後に Path 操作へ戻り、verify/load/prior-digest が検査済み manifest/body と消費 byte を束縛しない TOCTOU | root fd を全 lifecycle で保持し、`O_NOFOLLOW`・`fstat`・fd-relative 操作だけで copy/read/chmod/replace/remove。verify/load/prior-digest は同一 FD byte/digest を最後まで消費し、root/file/source/target/backup/remove と manifest/body の swap/ABA race で外部 content/inode/mode が不変かつ未検証 byte を返さない | OPEN |
| SEC-02 | P0 | summary/ledger/registry の予測可能な `.tmp`、validate→replace→backup/remove、staging directory 差替え後の Path member write の競合 | `O_EXCL`・`O_NOFOLLOW`・保持 dirfd からの member write・fd-relative atomic rename。tmp/output/backup/staging symlink・swap で外部 victim 不変 | OPEN |
| SEC-03 | P0 | Actions の private resume bundle が job/run 終了で消え、次 run が fresh に戻る | controlled persistent store を用いる2-run E2E、または product contract を明示的に local-only へ変更。前者なら run 2 が `collection_mode=resume` と prior digest 一致で完了し、公開 artifact の raw/token は0 | OPEN |
| SEC-04 | P0 | provider subprocess が非選択 provider の token も継承し、scanner は選択 token だけを見る | child env を provider ごとに最小化し、両 token canary を全出力で検査。非選択 token 注入負例が red | OPEN |
| SEC-05 | P0 | shared scenario-v1 schema は新 field を任意扱い、public runtime は必須扱い | local v1 を壊さない public scenario v2 を閉じた schema として追加し、fresh/resume field deletion が stdlib/jsonschema/runtime 全て red。D4 migration を付与 | OPEN |
| SEC-06 | P1 | resume 失敗 summary が `fresh`・prior null と誤記する | FAIL/PARTIAL/PASS の全経路で実際の mode と prior manifest/payload digest を保持し、tamper test で一致 | OPEN |
| SEC-07 | P1 | `abspath` 前に明示 `..` を拒否せず、入力上の traversal を正規化して受理する | raw path component の `..` を正規化前に拒否し、absolute/relative/encoded 境界を固定 | OPEN |
| SEC-08 | P1 | token の多段 percent encoding 境界が十分反証されていない | 1〜16段の漏洩 canary を検出し、17段以上を excessive encoding として拒否 | OPEN |
| SEC-09 | P1 | Vite forced-partial を保存・resumeしない契約の2-run実証がない | 同一 P02 を2回実行し、各回が1 page/100、prior bundleなし、件数累積なし | OPEN |
| SEC-10 | P0 | 現 Forge dirty 差分の fixture/contract が不一致で focused suite が4件 red | public registry fixture、fresh/resume argv、receipt、schema mutation、tamper を更新し、対象 suite 0 failed | OPEN |

## B. Actor・identity・experience（7件）

| ID | 深刻度 | 閉鎖対象 | 反証可能な受入条件 | 状態 |
|---|---|---|---|---|
| ACT-01 | P0 | `coauthor_shas()` と `read_numstat()` が40桁 OID 固定 | SHA-256 repo の通常＋coauthor commitで `coauthored_count=1`、numstat observed、SHA-1 fixtureと同値 | LOCALLY_VERIFIED (`7f55a1b`) |
| ACT-02 | P0 | actor選択時に full identity を1行へ縮退し、別行の明示 bot を human populationへ混入 | full identity をpopulation/bot分類に保持。非regex botがactor/adoption/founder等の分母から除外され、CLI→verifyが一致 | LOCALLY_VERIFIED (`7f55a1b`) |
| ACT-03 | P1 | 30日未満で削除された file も adoption 分母に残る | day29 delete は分母外、day30境界、day30 M/R後delete、delete/re-add別incarnationを exact equality | LOCALLY_VERIFIED (`7f55a1b`) |
| ACT-04 | P1 | AI申告あり・production path 0件でも理由が `no_declared_ai_commits` | docs/test-only AI申告では production-path母数なしを表示し、申告そのもの0件だけ旧理由を許可 | LOCALLY_VERIFIED (`7f55a1b`) |
| ACT-05 | P1 | `.mailmap` のGit公式4形式、casefold、precedence、malformed UTF-8の差分検証不足 | fixed-tree fixtureを `git check-mailmap` と exact比較。working-tree/global config影響0も維持 | LOCALLY_VERIFIED (`7f55a1b`) |
| ACT-06 | P1 | `renovate*` 等の名前prefixだけでhumanをbotにする偽陽性 | known bot正例、類似名human負例、identity明示bot正例を固定し、曖昧prefixだけではhuman除外しない | LOCALLY_VERIFIED (`7f55a1b`) |
| ACT-07 | P0 | identity-v2 の experience/role consent に authority が不要 | consent有・authority無/未知authorityを拒否または `consenting_actor_required`。許可authority正例をCLI生成とverify再計算で確認。v1読み取り互換は本人観測を自動解禁しない | LOCALLY_VERIFIED (`e79fc20`; contribution/identity focused 230/230) |

## C. Contribution・研究データ・attest・portfolio（8件）

| ID | 深刻度 | 閉鎖対象 | 反証可能な受入条件 | 状態 |
|---|---|---|---|---|
| DATA-01 | P0 | masked/raw payload全文を `--yes` を含め常に stdout へ出す | controlled profile は既定でdigest付き要約のみ。raw email canaryがstdout/stderr 0、0600 payloadだけに存在。全文表示を残すならTTY限定の明示opt-in | LOCALLY_VERIFIED (`e79fc20`; terminal canary 0、0600 4/4、digest 2/2) |
| DATA-02 | P0 | controlled sidecar が PID→source actor、source report、key reference を持たず再現不能 | report+key/key-id+sidecarから全PID・measurementを再生成しpayloadとexact一致。PID/report/key/mapping各1-byte mutationがred | IN_PROGRESS (`d4f0433`; root focused 427/427、final clean SHA parity待ち) |
| DATA-03 | P0 | reportなしsidecar検証でnested token/header/private-key/userinfo URLを許す | sidecar sourceをclosed/sanitized schema化し、report有無によらずrecursive credential guardを強制 | LOCALLY_VERIFIED (`e79fc20`; focused 230/230) |
| DATA-04 | P0 | masked変換がtimeline、暦年、period/category配列等を落とす、または直接/文中/source-sidecar の actor ID を再混入できる | 直接識別子以外の experience/role numerator/denominator/window/period/category をfield-for-field保持し、全 actor identifier のcasefold文中出現をpayload/sidecar pairから排除してclosed schemaで検証 | IN_PROGRESS (`d4f0433`; root focused 427/427、final clean SHA parity待ち) |
| DATA-05 | P0 | raw研究経路が安全な pagination/ref query URL まで一律拒否する一方、mapping key/value の多段encodingでcredential guardを迂回できる | GitHub/GitLabのsanitized page/ref queryを16段まで許可し、token/access_token/signature/userinfoをkey/value/pathで拒否、17段残存はfail-closed | IN_PROGRESS (`d4f0433`; root focused 427/427、final clean SHA parity待ち) |
| DATA-06 | P0 | aggregate が exact `n` / `denominator` をbucketへ置換する | 識別子なしでexact n/denominatorを保持し、sender/receiver schema・変換digest・fixtureを同時更新 | LOCALLY_VERIFIED (`e79fc20` ↔ `33bff78`; clean exact-SHA parity 8/8 VERIFIED) |
| DATA-07 | P0 | report-v1 portfolio entryを同一repo・別report/OIDとして水増し可能 | 全entryへopaque repo binding必須。report-v1はrepo_hint/repo_subject_id必須、同repo別OID・hintなしを拒否 | LOCALLY_VERIFIED (`079d43a`; focused 70/70) |
| DATA-08 | P1 | attest libraryがschema-invalid reportを署名・hash VERIFIEDにできる | sign前とbinding検証時にreport-v2/report-v1互換validatorを適用し、未知key/壊れたmetricsを拒否 | LOCALLY_VERIFIED (`079d43a`; focused 70/70) |

## D. Golden・package・CI・scenario・remote evidence（11件）

| ID | 深刻度 | 閉鎖対象 | 反証可能な受入条件 | 状態 |
|---|---|---|---|---|
| REL-01 | P0 | local/public scenario が旧 `0e44efe`・旧source digestに束縛され、local既定実行は登録6件中R07/R08を黙って省く | final clean SHAで既定local 6件を再生成・6/6 verifyし、全登録IDと既定選択がexact一致。P01〜P03を同SHAで再取得しcurrent binding/digest一致。CIもchecked-in stale registryのverifyだけでなくexact-head再生成を実行 | OPEN |
| REL-02 | P0 | dev merge→sanitized public snapshot→package の機械的chainがなく、内部docs・機密情報・mode欠落を含むsnapshotを公開し得る | canonical dev workflow/repository/run/head/artifact digestを外部receiptに束縛。tracked file単位のclosed public allowlistからmode/hidden fileを保持するdeterministic tarを生成し、禁止path/symlink/credential（PyPI token形式を含む）0、manifest自身もblob/100644、公開側でbody・inventory・digestを独立再検査。dev merge SHA→snapshot commit/tree→package smokeを連鎖 | OPEN |
| REL-03 | P1 | D4 manifestがfixture/expectedだけでCLI/shared core/schema/definition/acquisitionの実行実体と不可改の承認履歴を束縛しない | CLI wiring、shared core、schema、definition registry、experience/role/contribution/attest/portfolio/public acquisitionのclosed source inventoryをdigest化。base branch lockとappend-only比較し、1-byte mutationが `MIGRATION_REQUIRED`。未承認は `PENDING_HUMAN_APPROVAL` でfail-closed、CODEOWNERS reviewまたは署名receiptを実検証した場合だけPASS | OPEN |
| REL-04 | P0 | golden/action/packageがmerge-refで、exact PR head・exact tag commitの統合証拠がない。workflow内のmain判定だけではbranch改変を防げず、devはtestpypi environmentだけ、public repoはenvironment 0 | exact head SHAでnon-golden、v0.5/v0.6 golden、public registry、action dogfood、package smokeを実行しartifact source binding一致。publishはexact tag commitのCI workflow path/runとaction/intake必須job、current-run package artifactのGitHub API digest・REST ZIP byte/inventoryを独立照合し、secret-bearing actionをimmutable commitへpin、token mint/publishを外部protected release environmentのtag policy・reviewerへ束縛 | OPEN |
| REL-05 | P1 | action-dogfood artifactがguard ledgerだけでreport JSON/MD/shared blockを含まず、canned JSONで通過し得る | report JSON/MD、shared block、closed digest manifestをuploadし、artifact内reportに対しtrusted readback側でも実 `grift verify --repo .` を実行。exact SHA/OID/schema/算術/Markdown・shared block対応/digestをreadback | OPEN |
| REL-06 | P1 | intake network denialがPython socket patchのみで、source checkoutがinstalled wheelをshadowし、IPv6・workload後のdenyも未証明 | ambient `PYTHONPATH`/user-siteを無効化し、import originがisolated venv内wheelであることを検査。sudo不可のworkload境界でIPv4/IPv6の事前・実行中・事後deny/probe/readbackを取り、両rule activeがtrueの場合だけVERIFIED | OPEN |
| REL-07 | P0 | `REQUIREMENTS-v060.md` と旧exact-head evidenceにstaleなgreen/final/LIVE_EVIDENCE主張 | current事実へ修正し、過去証跡をhistorical/non-finalとして機械可読に区別。final exact-headは自己参照しないCI artifactとする | IN_PROGRESS (`6f9e4c3`; final docs gate待ち) |
| REL-08 | P0 | blind pilot ready 0/14。artifact検証失敗を成功扱いでき、final timeoutでmachine-readable receiptが消え、既存timer復元とroot FD ownershipにも不整合がある | 人間回答後に14 repoを固定OIDで一括実行するdeterministic producerを実装。全artifact/timeout callsiteはclosed failure rowとatomic `FAILED` receiptへ収束し、timer/FDを正しく復元。crash 0、verify成功、比較可能cell80%以上、分類100%、説明不能0、時間条件を満たす | IN_PROGRESS（producer再反証中、HUM-01待ち） |
| REL-09 | P1 | R01は同意/authority未記録、R03はshallowなのに本人観測・小標本実repo証拠と読める | R01をrepo/actor証拠と本人観測human gateへ分離。R03をshallow fail-closedへ訂正し、小標本n19/20はsynthetic exact証拠へ限定 | IN_PROGRESS (`6f9e4c3`; final docs gate待ち) |
| REL-10 | P0 | final sourceでfull suite、golden、P0、schema、package、local/public scenario未実行。通常PR CIはP0 resolver testだけで43本体を走らせない。OUT-01再監査ではcard/manifest/path/symlink改ざん8件をverifyは拒否したがalignが8/8受理 | final clean SHAで全gateを再実行し、生のpassed/failed/skipped、duration、artifact SHA-256を記録。PR exact-head CIでもP0 43/43とlocal 6件再生成を強制。align/Actor verifierは同一FD byteへdigest→parse→consumeを束縛し、8改ざん、検証後swap、ABA restoreを全拒否。旧数値を流用しない | OPEN |
| REL-11 | P0 | PR #64、#65、Grift #2055が旧head・旧数値・過大な完成表現 | FF push後のexact head CIを確認し、PR本文と既存commentだけを正確な段階へ更新・即readback。新規commentを増やさない | OPEN |

## E. 人間ゲート（6件）

| ID | ゲート | 現状態 | 完了証拠 |
|---|---|---|---|
| HUM-01 | blind pilot 14 repoの権限・identity・role・AI trailer質問票回答、R01 consent/authority | HUMAN_GATE / ready 0 | 回答audit ready 14 / blocked 0。推論で補完しない |
| HUM-02 | Vite/VOICEVOX/GitLab CLI full用credentialとrelease-tier clone | HUMAN_GATE | 最終SHAのfull provider summary/ledger、OID集合差分0、秘密漏洩0 |
| HUM-03 | cosign keyless OIDC | HUMAN_GATE | 受領者指定identity/issuerで実署名・実検証 |
| HUM-04 | companion PR #5 と grift-cli-dev PR #64 のreview/merge | HUMAN_GATE | exact head CI後の人間merge。mainへの直接push・自動mergeなし |
| HUM-05 | protected release environmentのtag policy/reviewer/secret配置、annotated tag、PyPI publish、wheel再取得SHA-256 | HUMAN_GATE（devはtestpypiのみ、publicはenvironment 0） | environment API readback、tag object→commit、publish run、PyPI wheelのreadback hash |
| HUM-06 | Grift production pin/merge、image readback、live Evidence Room、#2055 close | HUMAN_GATE | version/hash/schema/OID/partition/parity/provenance一致とlive evidence。未達ならcloseしない |

## 閉鎖順序と進捗の数え方

依存順は次のとおりとし、並行作業は同じ段階の独立項目だけに限定する。

1. `SEC-*`、`ACT-*`、`DATA-*` の実装と各focused反証
2. `REL-02`〜`REL-06` のrelease/CI強制点
3. `REL-07`・`REL-09` のSSOT訂正
4. final clean SHAで `REL-10`、続いて `REL-01`
5. `REL-04`・`REL-05`・`REL-11` のremote exact-head/readback
6. `HUM-*` は人間が明示実施した場合だけ状態更新

進捗は「7段階中いくつ」だけでなく、**36件中の
LOCALLY_VERIFIED件数 / OPEN件数 / 回帰件数**を併記する。focused testが緑でも、
full suiteとfinal source bindingが未完なら当該release項目は閉じない。

## 停止条件

- 同一エラー3回
- 30分無進捗
- 権限・credential・同意・merge/tag/publish判断待ちで安全な次手がない

停止時は、該当ID、試行、最後の生出力、必要な人間操作を報告する。
