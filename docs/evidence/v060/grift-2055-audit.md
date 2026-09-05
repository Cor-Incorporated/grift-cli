# Grift #2055 統合コメントの一次資料監査

監査日時: 2026-08-31 JST
対象: `Cor-Incorporated/grift-cli-dev#65`、`Cor-Incorporated/Grift#2055`、
`Cor-Incorporated/Grift#2059`、公開 `Cor-Incorporated/grift-cli`、PyPI
用途: #2055 への**1件の統合コメントの下書き**。この文書自体は pin、
deploy、merge、Issue close、コメント投稿の証拠ではない。

## 結論

- `grift-cli==0.5.1` の private merge → public snapshot/tag → publish run
  → PyPI wheel SHA-256 は、下表の一次資料で追跡できる。
- Grift #2059 は `develop` へ merge 済みだが、変更は
  `docs/v2/methodology/CONTRACT-ACK-g1-20260822.md` 1ファイルだけである。
  production pin、runtime image、live Evidence Room はこの監査では確認できず、
  **NOT_PROVEN**である。
- 現在の WP-G1 artifact は `grift-cli==0.5.6` の CLI-side PASS だが、
  shallow 19 commits、package artifact digest `UNMET_OUT_OF_SCOPE`、
  legacy実行なしである。production parity や release pin の証拠ではない。
- v0.6.0 はこの監査時点で release chain が無い。最終PR SHA、exact-head CI、
  golden、wheel digest を投稿直前に readback するまで、#2055へは
  `NOT_RELEASED` とだけ記載する。

## 0.5.1 release chain

| 段階 | 一次資料で確認した値 | 判定 |
|---|---|---|
| private merge | `grift-cli-dev` commit `57d72e9848d7cb0a23d51971db26bd31a30be0a9`、subject `chore: v0.5.1 リリース確定（バージョン・CHANGELOG）` | 確認 |
| public snapshot | public `grift-cli` commit `7dca9be79456b7011eaa472de69497f0fb91f1b4` の message が上記private SHAを snapshot source と明記 | 確認 |
| annotated tag | `v0.5.1` ref → tag object `3f6772b2ab364e0e4b6675dd301daae9085137e2` → commit `70f92e8ca20f4f5033360be9bf655aba6afa70d6` | 確認 |
| publish | public repository Actions run `32573244841`、`head_sha=70f92e8…`、`event=push`、`conclusion=success` | 確認 |
| wheel | PyPI `grift_cli-0.5.1-py3-none-any.whl` SHA-256 `99691ea0f8ee642546e0c32825aa27ff5c7e275c7e50131387ce12819838ca5a`。PyPI JSONとwheel bytesのstreamed SHA-256が一致 | 確認 |

固定インストール指定:

```text
# requirements-grift-cli.lock
grift-cli==0.5.1 --hash=sha256:99691ea0f8ee642546e0c32825aa27ff5c7e275c7e50131387ce12819838ca5a
```

```sh
python -m pip install --require-hashes --only-binary=:all: --no-deps \
  -r requirements-grift-cli.lock
```

`#65` の本文はこの chain、wheel SHA-256、install specification と旧
`scripts/tep/` 相当の確認を依頼しており、監査時点の comments は 0 だった。

## Grift側の現在値と反証

| 項目 | 観測値 | この値が証明しないもの |
|---|---|---|
| #2059 | `develop`へmerged `true`、merge commit `8dd0038a505c8a9e9b7bb4ffb6849aed4a7c785f`。PR files API は CONTRACT-ACK 1ファイル追加（+284/-0）。default `main` はこの文書をまだ含まない | consumer実装、pin、deploy、live |
| 0.5.9 CONTRACT-ACK | 上記docs-only PRで merge。#2055本文にも `Implementation-Evidence: Draft PR #2059 ... docs-only` という古い表現が残るため、コメントでは「merge済みdocs-only」に訂正する | release chainやproduction adoption |
| 0.5.6 parity fixture | `cli_side_state=PASS`、PyPI source、`report-v1`、`repository_is_shallow=true`、reachable commits `19` | 完全履歴、39–51 repo shadow、legacyとの実測 parity |
| 0.5.6 artifact digest | `package_artifact_digest_verification=UNMET_OUT_OF_SCOPE`。保存report SHA-256 は `6874ea6d…` だが、これはwheel provenanceではない | package artifactのdigest attestation |
| old `scripts/tep` | 7本は tree に残る。production pathを対象にした `git grep` は0件で、唯一の非対象参照は parity README の「old scriptsをraw inputとして受けない」という説明 | 7本の削除、absence guard、個人品質consumer全消去 |
| production | #2055の `Live-Evidence: NOT_PROVEN`、この監査でも deployed revision/image、pinned runtime、live Evidence Room readbackなし | pin/deploy/live/close |

旧 scripts は production callsite 0であって、削除済みではない。今後置換として
許可するのは origin、Actor帰属・活動、cochange、survivalのみである。個人品質値、
fingerprint、select、coverage は意図的に継承しない。

## #2055 に固定する利用契約

1. 初期production ingestは release済みの凍結 `report-v1` / `export-v1` のみ。
   `report-v2`、project、alignmentは別consumer sign-offまで読まない。
2. Evidence Room は repository 観測を「何を観測したか・coverage・理由・次の質問」
   として表示し、必ず `n`、denominator、window、OID、tool/schema/definitionを併記する。
3. Actorはtenant隔離された帰属・活動の説明だけに使う。additions/deletions/churn/
   test-touch/fix-featを能力・品質・rankへ変換しない。
4. experience/roleは同意済みidentity本人だけ。project declarationとobserved dataを
   分離し、alignmentは確認質問のみでfit/hire/scoreを出さない。
5. CLI値から金額、工数、単価、契約条件を自動変更しない。
6. GitHub/GitLab等のpublic provider enrichmentは表示だけでActor partitionを変えない。
   account linkageがunsupportedなら`not_proven`を保持する。
7. contribution corpusをSaaS tenant dataへ直結せず、版管理されたaggregate/referenceを
   別契約で読む。version、wheel hash、schema、OID、partition、parity、provenance、
   missingness不一致はfail-closedでlegacy fallbackしない。
8. provider APIの取得責任はGrift側、Git履歴観測のoffline SSOTとbound exportはCLI側。
   GitHub/GitLabで同じ境界を守る。

## 再現コマンド

```sh
gh api repos/Cor-Incorporated/grift-cli-dev/issues/65
gh api repos/Cor-Incorporated/grift-cli/git/ref/tags/v0.5.1
gh api repos/Cor-Incorporated/grift-cli/git/tags/3f6772b2ab364e0e4b6675dd301daae9085137e2
gh api repos/Cor-Incorporated/grift-cli/actions/runs/32573244841
curl -fsSL https://pypi.org/pypi/grift-cli/0.5.1/json
gh api repos/Cor-Incorporated/Grift/pulls/2059
jq . scripts/wp-g1-parity-diff/artifacts/current/status.json
git grep -nE 'tep_(coverage|demo|evidence_v2|fingerprint|origin|select|survival)\\.py|scripts/tep' -- \
  ':!scripts/tep/**' ':!docs/**' ':!**/test*' ':!**/*test*' ':!**/fixtures/**' ':!**/artifacts/**'
```

Evidence: GitHub REST and PyPI JSON/readback commands above | release chain matched;
#2059 docs-only merge; 0.5.6 shallow/digest limits observed | 2026-08-31 JST
