# report-v2 / v0.6 strict artifacts

`report-v1` と `export-v1` は凍結した互換契約として残ります。既存キーの改名・
削除・意味変更は行わず、追加互換を維持します。v0.6 で新設する `report-v2`、
Actor collection、project、alignment、public evidence、contribution、attestation、
portfolio、scenario、bound export は Draft 2020-12 の閉じた契約です。未知キーは
拒否します。可変キーを持つ箇所は `metrics` や digest map など、schema が明示した
map slot だけです。

runtime の正本は
[`src/tep_core/schemas/v060-contracts.schema.json`](../src/tep_core/schemas/v060-contracts.schema.json)
です。stdlib validator と開発時の `jsonschema` を同じ mutation corpus で照合します。

## report-v2 の必須境界

`grift repo` と単一主体の `grift actor ACTOR_ID` は `report-v2` を出します。
トップレベルで必須なのは次の要素です。

- `subject`: repo は `repo_all_human`、Actor は `explicit_actor` または
  `inferred_actor`。Actor は実在人物の断定ではなく、固定OID時点の repo-local
  Git primary-author clusterです
- `target.oid`: `{algorithm: sha1|sha256, value: ...}`。OID文字列の長さとalgorithmを
  一致させます
- `provenance`: tool/schema/definition、固定target、入力digest、観測時刻、
  shallow/promisor/completeを分離します。`tagset_digest`と
  `input_digests.tagset`は、固定OIDから到達可能なtag ref集合を同じSHA-256で束縛します
- `population`: full Actor数、人間commit数、non-merge/merge、partition digest、
  population digestを保持し、算術整合を検査します
- `window`: start/end/unit/basisを固定します
- `metrics`: 各観測に `kind`、numerator、denominator、unit、window、
  definition version、limitationsを持たせます
- `limitations` / `notices`: 未観測、coverage不足、解釈上の限界を欠落不能にします

`score`、`rank`、`fit`、`recommendation`、`overall` と、それらの派生語彙は
成果物のどの階層でも禁止します。

次は必須境界を示す抜粋であり、完全なinstanceではありません。完全な有効例は
`tests/test_v060_schema_contracts.py`のmutation corpusを正本とします。

```json
{
  "schema_version": "report-v2",
  "report_kind": "evidence",
  "subject": {"kind": "repo", "selection": "repo_all_human"},
  "target": {
    "oid": {
      "algorithm": "sha1",
      "value": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  },
  "population": {
    "actor_count": 1,
    "human_commit_count": 2,
    "nonmerge_commit_count": 1,
    "merge_commit_count": 1,
    "basis": "git_primary_author_cluster"
  }
}
```

## Actor partition と公開account

Actor partitionは公開API取得より先に固定します。明示alias、固定treeの
`.mailmap`、正規化raw email、email欠落時だけname cluster、unresolvedの順で
構成し、provider loginや名前類似では統合しません。provider enrichmentは表示用で、
offline / partial / fullの間でActor数、partition digest、SHA→Actor対応、Git由来数値を
変更してはいけません。

GitHub account linkageはcommit responseのtop-level `author.id`とcommit OIDの対応を
根拠にします。GitLab commits APIにdocumented account linkageがない場合は
`unsupported/not_proven`のままです。同じActorに複数accountが対応すれば
`ambiguous`、同じaccountが複数Actorへ対応すれば`conflict`であり、自動統合しません。

## 閉じたActor collection

`grift repo REPO --actors --out DIR`、`grift actor --all REPO --out DIR`、
`grift actor --top N REPO --out DIR`、`grift actor ACTOR_ID REPO --out DIR` は、
既存パスを上書きしない新規ディレクトリに次を出力します。

```text
DIR/
├── repo-report.json
├── repo-report.md
├── actor-index.json
├── actor-index.md
├── actors/
│   ├── <actor-id>.json
│   └── <actor-id>.md
└── collection-manifest.json
```

- `repo-report.*` は常にfull population、`actor-index.*` はfull一覧とselected一覧、
  `actors/*` はselected cardだけです
- full/selected件数、partition/population/index/selection digest、cardの `n` と
  denominatorをJSON/Markdown/manifest間で一致させます
- manifestは全memberのpath、byte length、SHA-256を登録します。path traversal、
  symlink escape、未登録/欠落file、1-byte改ざんを拒否します
- `grift verify DIR --repo REPO` はcollection、固定OID、Git partitionを再計算します。
  public accountを含む場合は `--public-evidence EVIDENCE_DIR` も指定します

単一 `grift actor ACTOR_ID` のstdoutまたは`--out FILE.json|FILE.md`は、
`subject.selection` / `subject.attribution_state` を共通classifierへ渡し、次の5つの
表示basisを区別した詳細report-v2を出します。

- **inferred選択**（identityなし）: 公開Git上のactor cluster観測。
  「実在人物との同一性は証明していません」を常時表示し、本人証拠ビュー・
  同意identityの要求文は出しません（experience/role は not_observed）
- **explicit + claimed**: 申告が記録されたidentityに基づく本人向け表示。
  CLIは申告者・本人同意・本人性を証明しません
- **explicit + verified**: 管理対象リポジトリの管理権限に基づく
  admin-authorized観測。本人向け表示ではなく、同意または本人性を証明しません
- **explicit + inferred/external/unresolved/bot**: 非同意actor観測。
  本人向け表示にせず、experience/roleはnot_observedです
- **unknown**: selection/stateの欠落・矛盾。本人同意を推測せずfail closedします

actor reportのmachine scopeは、explicit `verified|claimed`だけが`tenant`、公開inferred
またはexplicit非同意basisは`actor_cluster`です。`actor_cluster`はrepo-local Git
primary-author clusterであり、表示basis、本人同意、本人性の根拠には使いません。

`--out DIR`は
`actor-index-v1.selection.mode=explicit`のclosed collectionです。explicit cardの
optional `experience` / `role_profile`は明示consent gateで生成した観測、または
`not_observed(consenting_actor_required)`だけを保持し、verifyは固定OIDとidentityから
exact再計算します。この機械field名や生成可否は同意の証明ではありません。
detailを持つcollectionの検証には、生成時と同じ`--identity FILE`を指定します。
CLIはActor ID、`--all`、`--top`の同時指定を拒否します。

## experience / role

experienceと4次元role profileは、explicit identityに
`attribution_state=verified|claimed`と
`consent=recorded-explicit-consent`の両方がある場合だけ生成します。stateまたは
`authority`だけでは生成しません。CLIが検証するのはidentity内の記録であり、現実の
本人同意・申告者・本人性ではありません。第三者の公開Actor、identityなしrepo、
マーカーのない既存identity、その他のstateでは
`not_observed(consenting_actor_required)`です。4次元はtop-levelの`domain`、
`work_type`、`time`、`process_position`だけです。`time`内に`phase`と
`calendar_year`を保持し、単一職種やscoreを生成しません。denominatorが20未満の率は
値とnumeratorを非表示にし、denominatorと`insufficient_population`だけを残します。
cadence、language/domain timeline、repository-size pointsを含むobserved metricは
`kind/numerator/denominator/unit/window/definition_version/limitations`を必須とします。
`post_release_fixes`はtag時刻だけでなく、固定OIDのparent DAGでtag targetがfix commitの
祖先であることを確認し、欠落・cycle時は数値を出しません。

公開OSSのgoldenはrepo-level detectorとActor partitionを検証するものであり、
第三者個人のexperience/roleを生成する根拠にはしません。

## target-bound forge / tracker export

v0.6 subject commandは`tep-forge-export-v2` / `tep-tracker-export-v2`だけを
reportへ結合します。両形式はprovider/host/stable project ID/path、generic target
OID、UTC window、coverageを必須化し、別repo・混合source・unbound v1を拒否します。
v1の読み取り互換はlegacy loader/commandだけに残します。

forge v2は`event_observation`へevent総数、kind別件数、active UTC days、window、
input digest、credential-free binding、coverageのobserved/expected/missingを出します。
actor reportは`actor_canonical_id`完全一致だけを選択し、provider handle/name/emailで
補間しません。partial coverageでも含まれるeventは下限として観測しますが、
`event_rhythm`のabsence/cadenceは`not_proven(partial_source_coverage)`です。

tracker v2はissue/milestoneのstate、直前event、link、durationを閉じたschemaで表現し、
event ID重複、必須field欠落、nonfinite/negative/mismatched duration、timestamp逆順、
broken/cross-record/future link、state transition不整合を拒否します。
`tracker_lifecycle`は検証済みeventからkind/state件数、active UTC days、観測できた
issue transitionのtimestamp差を出します。これは労働時間、速度、品質、能力では
ありません。完全契約は[`input-export-schema.md`](input-export-schema.md)です。

## public evidence と検証

`--fetch-public`、`--public-evidence DIR`、`--resume-public-evidence DIR`は排他です。
取得には`--public-evidence-out DIR`を指定し、sanitized request、status、ETag、
Last-Modified、body SHA-256、item count、pagination、rate state、coverageを記録します。
raw bodyはmode 0600の`blobs/sha256/*`に置きます。

```bash
grift repo REPO --rev REV --fetch-public \
  --forge-provider github --public-evidence-out EVIDENCE_DIR
grift verify --public-evidence EVIDENCE_DIR --repo REPO
grift repo REPO --rev REV --public-evidence EVIDENCE_DIR
```

`verify`はnetworkへ再接続せず、schema→manifest→body digest→再parse→Git OID集合→
SHA/account対応→report/collection bindingの順で検査します。終了コードは
`0=VERIFIED`、`1=MISMATCH`、`2=CANNOT_VERIFY`、安全な途中停止は`3=PARTIAL`です。

## attestation の入力束縛

`grift attest`は署名前に`grift verify`と同じ保存入力でreportを再計算します。
reportが使用した`--public-evidence`、`--forge-export`、`--tracker-export`、
`--reference-manifest`を省略・交換すると署名を拒否します。canonical statementは
report digest、generic target OID、全input digestのmemberとaggregate、定義版集合digest、
public-evidence digest、reachable tagset digest、scope、実行時刻を署名対象にします。
taggerのname/emailやtag本文はstatementへ出力しません。署名、report hash、repo再計算は
独立判定のままです。

## Markdown

Markdownは「対象 → 入力/provenance → coverageと未観測 → 数値と母数 → 読み方 →
言えること/言えないこと → 再現情報」の順です。path heuristic、活動時刻、
declared AI trailer、attestationはいずれも職種・能力・品質の判定ではありません。

`analyzed_at`はprovenanceだけに使い、数値計算へ混ぜません。
