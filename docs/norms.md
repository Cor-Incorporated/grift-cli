# TEP（Technical Evidence Pipeline）利用規範（norms）— 「TEP 準拠」を名乗る条件 / TEP Usage Norms

**正式版（v1・2026-08-22実装・P1g）。「TEP 準拠（TEP-compliant）」を名乗る利用の条件を定める。**
**Norms v1 (2026-08-22, shipped as part of WP-P1g). Defines the conditions for calling a use "TEP-compliant."**

TEP は検証可能な証拠を出す方法論であり、判定機ではない。本規範は「TEP 準拠（TEP-compliant）」を名乗る利用の条件を定める。**本規範への適合を「TEP」の名の使用条件とする**（DORA ガイドライン型の規範的強制）。非準拠の利用は TEP と呼んでならない。

---

## 規範（ja）

### 1. 不在を負に読まない

TEP レポートの不在・private 経歴・低活動期間（gap）を、能力・実績の否定として扱う利用は非準拠である。
理由: not_observed ≠ 実績なし。育児・傷病・非公開業務の経歴は git に写らない。

### 2. 単独足切りの禁止

TEP の数値・分布位置を単独の合否基準にする利用は非準拠である。
理由: TEP は問いに答える証拠であり、判定機ではない。

### 3. 申告を負に読まない

declared_ai_assist の申告あり/なしのいずれも、それ自体を負の証拠として扱う利用は非準拠である。
理由: 透明性への罰は隠蔽を生む。申告なし ≠ AI 不使用。

### 4. 同意なき第三者プロファイリング禁止

本人の同意なく identity を構成して tenant 分析する利用は非準拠である。
理由: 個人化の入口は本人の意思でなければならない。

ただし**公開Git上のactor clusterを名前付きで観測・表示すること（`grift actor` の
inferred 選択、actor card、actor index）はこの限りではない**。actor cluster は
repo-local の Git primary-author 分類であり、実在人物との同一性は証明しない。
したがって:

- 公開actor表示には「実在人物との同一性は証明していません」を常時併記する
- 公開actor観測を identity・本人証拠・tenant 分析の入力に使わない
- `attribution_state=claimed` は申告が記録されたことだけを表し、このbasisだけを
  本人向け表示に使う。CLIは申告者・本人同意・本人性を証明しない
- `attribution_state=verified` は管理対象リポジトリの管理権限に基づく
  admin-authorized identityであり、本人同意または本人向け表示を意味しない
- experience/roleを観測できるのは、`verified|claimed`に加えてidentity行が
  `consent=recorded-explicit-consent`を明示した場合だけである。CLIが検証するのは
  この記録の存在であり、現実の同意・申告者・本人性ではない。`authority`だけでは
  experience/roleを解放しない
- 公開inferred・explicit非同意basisのmachine scopeは`actor_cluster`とし、`tenant`へ
  昇格させない。どちらのscope名も第三者を個人化する権限または同意の証拠ではない

### 5. 監視転用の非準拠

組織構成員の常時比較・個人評価表化への利用は非準拠である（公開も内部も）。
理由: 個人を対象にした継続的な比較表は、この方法論が拒否する使われ方そのものである。

### 6. 選択性の明示

複数 repo の提示は「提供者が選択したものである」ことを明示して読む・示す。
理由: 選択的開示は禁止しないが、隠さない。閉じた経歴書と違い、選択が見えることが前進である。
単体の actor report-v2 と alignment-v1 の `notices` には固定文「This report covers one repository that the provider chose to share. It does not show whether other repositories exist or what they would show.」を常に載せる（v0.8.0）。
日本語の Markdown には、同じ意味の文「このレポートは、提供した人が選んで共有した 1 つのリポジトリだけを対象にしています。ほかのリポジトリがあるかどうかも、そこで何が見えるかも示しません。」を載せる（v0.9.0）。JSON の `notices` は英語の固定文のまま。

### 7. 重み付け・換算の禁止

文脈・難易度による数値の補正は非準拠である。
理由: 補正は必ず仮説を含み、検証可能な一次記録を歪める。

### actor collection / selection（v0.6）

`grift actor --all` はrepo-local clusterの全件collection、`--top N` は観測commit数
による取得件数の限定、`grift actor ACTOR_ID` は1つのcanonical_idのcardを出す。
この3経路は排他である。collection/indexは固定OID時点の帰属インベントリであり、
品質・能力・人物の順位や継続評価表ではない。index と `actor_directory` の行は actor id 順であり、
観測 commit 数の多い順には並べない（行の位置は何も意味しない）。`--top N` の順序を品質rankへ変換する
利用は非準拠である。公開collectionからidentity、本人性、experience/roleの同意を
推論しない。`email_patterns` を一人へ割り当てる推測もしない。未観測は実績なしを
意味しない。表示basisは次の5状態を混同しない。

1. **public inferred**: identityなしの `inferred_actor`。公開Git上のrepo-local
   primary-author clusterであり、実在人物との同一性を証明しない
2. **self-claimed**: explicitの `attribution_state=claimed`。このbasisだけが本人向け
   表示を得るが、CLIは申告者・本人同意・本人性を証明しない
3. **admin-authorized**: explicitの `attribution_state=verified`。管理権限に基づく
   非本人向けactor観測であり、同意または本人性の証明ではない
4. **explicit nonconsent**: explicitの `inferred|external|unresolved|bot`。本人向け
   表示にせず、experience/roleを観測しない
5. **unknown**: selection/stateの欠落・矛盾。本人同意を推測せずfail closedする

`grift align --team` は同意済みの複数 actor を同時に読み、宣言された要求をチームが覆えているかを**人数のみ**で出す。個人の測定値は名前を伏せた最大値・代表値としても出さず、順序を示す語彙を含まず、3 名未満では「2 人中 1 人」が消去法で個人を名指すため集計そのものを拒否する。測れなかった要求は「覆えていない」ではなく「観測できていない」と出す（1条）。強制側: `src/tep_core/complementarity.py`（`MIN_TEAM_SIZE`）と `v060-contracts.schema.json` の `report_complementarity`（`additionalProperties: false`）。順序を示す語彙の禁止は `tests/test_v070_complementarity.py::test_no_ordering_vocabulary_appears_in_any_value` が出力の全文字列値に対して強制する。

### alignment no-verdict（v0.6）

`grift align` は宣言と観測を軸ごとに並べるだけである。全体点・順位・合否・推奨を出す利用は非準拠である（2条・7条と同旨）。

### 特性の文と面談の問い（v0.9）

`grift actor` と `grift project` の Markdown の先頭に、記録から見える進め方を平易な文で書き、`grift actor` と `grift align` には面談で確かめたいことを問いとして並べる。文と問いは[決定表](trait-profile.md)で JSON の数字から機械的に選び、次を守る（[ADR-0002](adr/ADR-0002-trait-profile.md) T1〜T7）。

1. 文は量ではなく、本人の仕事の割合と形で選ぶ（T1）
2. 比べる相手は本人のほかの仕事だけ。ほかの人や参照分布と比べた語を使わない（T2）
3. 文ごとに分子・分母・期間を置く。母数 20 未満の割合は文にしない（T3）
4. タイプ名を作らない。文・文の id・型のキーを JSON に置かない（T4）
5. 照らし合わせを合計しない。重なった項目の数を出さない（T5）
6. 文と問いは公開した決定表で選ぶ。LLM を使わない（T6）
7. 本人向けの文は `attribution_state=claimed` と `consent=recorded-explicit-consent` があるときだけ出す。verified・公開 inferred の actor レポートには出さず、出していない理由を書く。collection には文の節を作らない。照らし合わせの問いも、claimed で同意の記録があるときだけ出す（T7。`grift align` が同意の記録を `subject.actor_consent` に写す）

文を 1 つの名前に畳んで人を並べる・選ぶ利用は、2 条・7 条と同じく非準拠である。強制側: `src/tep_core/trait_tables.py`（決定表）、`tests/test_v090_trait_tables.py`（docs と定数の結び、語彙の検査）、`tests/test_v090_trait_profile.py`（同意の条件、JSON に文が無いこと、量で文が変わらないこと）。

---

## 保持・削除・転用禁止（提出データの扱い・`grift contribute` に関わる）

1. **目的拘束（v0.7 改訂）**: 明示的提出（`grift contribute`）で受け取ったデータは、**提出者が提出時に選択し payload に記録された目的にのみ**使用する。**それ以外（チャネル4: Grift SaaS・組織契約・営業・見積りへの転用を含む）には一切使わない**

   選択できる目的は次の閉じた集合に限る。集合への追加は本規範の改訂であり、`docs/en/norms.md` と実装の `PURPOSES` を同時に変えなければ `test_v070_norms_link` が落ちる。

   | id | 記録される目的 |
   |---|---|
   | `reference-distributions` | `TEP Report 集計と参照分布 vNext` |
   | `outcome-linkage` | `提出者が選択した成果連携の検証` |

   v0.6 までは目的が 1 つに固定されており、提出者ではなくプロジェクト側が用途を決めていた。本改訂は用途を広げるものではなく、**選択権を提出者へ移し、提出ごとに束縛を記録する**ものである。無選択時は `reference-distributions` として扱い、v0.6 と同じ意味になる。
2. **保持期間**: 次回年次 Report の発行まで
3. **撤回手続き**: (a) 提出者による自payload削除のPR (b) 受け口リポの連絡先への依頼。代理PR提出者のidentityは開示しない。ただし既存clone/forkを含むGit履歴からの完全撤回は保証できない
4. **推測リスクの開示**: aggregate payloadはrepo名/OID/source digestを含まないが特徴の組合せから推測されるリスクはゼロではない。named-publicは明示authorityの範囲でproject/accountを公開する
5. **profile別アクセス**: aggregate/named-publicだけがpublic-pr可能。masked/rawはlocal/controlled専用で、研究purpose・authority/consent・retention・withdrawal・access classをsidecarに必須化する

---

## Norms (en)

**TEP (Technical Evidence Pipeline) is a methodology that produces verifiable evidence; it is not a decision engine.** These norms define what may be called "TEP-compliant" use. Compliance with this document is a condition of using the TEP name (DORA-guideline-style normative enforcement). Non-compliant use must not be called TEP.

### 1. Do not read absence as negative

Treating a missing TEP report, a private career, or a low-activity period (gap) as evidence of lack of ability or accomplishment is non-compliant.
Reason: not_observed ≠ no achievement. Parental leave, illness, and non-public work do not appear in git.

### 2. No single-metric cutoff

Using any TEP number or distribution position as a standalone pass/fail criterion is non-compliant.
Reason: TEP answers questions with evidence; it does not make decisions.

### 3. Do not read declaration as negative

Treating either the presence or absence of declared AI assistance as negative evidence is non-compliant.
Reason: Punishing transparency breeds concealment. No declaration ≠ no AI use.

### 4. No third-party profiling without consent

Constructing an identity to run tenant analysis on someone without their consent is non-compliant.
Reason: The entry point to personalization must be the person's own choice.

Naming and displaying a public Git actor cluster (`inferred_actor`) is allowed
only as a repo-local primary-author cluster; it does not prove a real person's
identity. `claimed` records a claim and is the only basis that gets personal-view
wording, but the CLI does not prove the declarer, consent, or personhood.
`verified` is admin-authorized and non-personal; it does not imply subject
consent. Explicit `inferred|external|unresolved|bot` is nonconsenting, and a
missing or contradictory basis fails closed as unknown. Experience/role also
requires `consent=recorded-explicit-consent` on a `verified|claimed` row;
attribution state or `authority` alone never unlocks it. The CLI validates that
the marker is recorded, not real-world consent, declarer identity, or
personhood. Public inferred and explicitly nonconsenting bases use the machine scope
`actor_cluster`, never `tenant`. Neither scope name grants authority for
third-party personalization.

### 5. Surveillance use is non-compliant

Using TEP for continuous comparison or scorecards of organization members — public or internal — is non-compliant.
Reason: A persistent per-person comparison table is exactly the use this methodology rejects.

### 6. Disclose selectivity

Presenting multiple repositories must be read, and shown, as "selected by the provider."
Reason: Selective disclosure is not forbidden; hiding the selection is. Unlike a closed résumé, visible selection is progress.
A single-repo actor report-v2 and an alignment-v1 always carry the fixed notice "This report covers one repository that the provider chose to share. It does not show whether other repositories exist or what they would show." in `notices` (v0.8.0).
The Japanese Markdown shows the same notice in Japanese, 「このレポートは、提供した人が選んで共有した 1 つのリポジトリだけを対象にしています。ほかのリポジトリがあるかどうかも、そこで何が見えるかも示しません。」 (v0.9.0); JSON `notices` keep the English sentence.

### 7. No weighting or conversion

Adjusting numbers by context or difficulty is non-compliant.
Reason: Adjustment always embeds hypotheses and distorts verifiable primary records.

### Actor collection / selection (v0.6)

`grift actor --all` emits the full repo-local cluster collection, `--top N`
limits retrieval by observed commit count, and `grift actor ACTOR_ID` emits one
canonical-id card. These modes are mutually exclusive. A collection/index is
an attribution inventory at a fixed OID, not a quality, ability, person-ranking,
or continuous-evaluation table. Index and `actor_directory` rows are listed in actor-id
order, never by commit count; a row's position means nothing. Treating `--top N` order as a quality rank is
non-compliant. A public collection never supplies consent for identity or
experience/role. The five presentation bases are public inferred, self-claimed, admin-authorized,
explicit nonconsent, and fail-closed unknown. Only self-claimed receives
personal-view wording, and no basis is CLI proof of consent or personhood.
`email_patterns` are not assigned to one person. `not_observed` is not a lack
of achievement.

### Alignment has no verdict (v0.6)

`grift align` places declared requirements next to observed evidence axis by
axis. Computing an overall score, rank, pass/fail, or recommendation is
non-compliant (same intent as articles 2 and 7).

### Trait sentences and interview questions (v0.9)

The `grift actor` and `grift project` Markdown opens with plain sentences on how the work shows in the record, and the `grift actor` and `grift align` Markdown lists questions to confirm in an interview. The [decision tables](en/trait-profile.md) pick them mechanically from the JSON numbers, under these rules ([ADR-0002](adr/ADR-0002-trait-profile.md) T1-T7):

1. A sentence is chosen by the shares and shape of the person's own work, never by volume (T1)
2. The only comparison is with the person's other work; no word that compares with other people or a reference distribution (T2)
3. Every sentence keeps its numerator, denominator and period; a share over fewer than 20 is not turned into a sentence (T3)
4. No type names: JSON carries no sentence, sentence id or type key (T4)
5. An alignment is never totalled; the number of overlapping items is not printed (T5)
6. Sentences and questions come from the published tables; no LLM (T6)
7. Person-facing sentences appear only with `attribution_state=claimed` and `consent=recorded-explicit-consent`. Actor reports for verified identities and public inferred actors get none, and the output says why; collections get no sentence section; alignment questions follow the same rule, a claimed identity with the consent record that `grift align` copies into `subject.actor_consent` (T7)

Folding the sentences into one name to rank or select people is non-compliant, as under articles 2 and 7. Enforcement: `src/tep_core/trait_tables.py` (the tables), `tests/test_v090_trait_tables.py` (docs-to-constants link and vocabulary gates), `tests/test_v090_trait_profile.py` (consent condition, no sentence in JSON, no change with volume).

---

## Data retention (applies to explicit submissions via `grift contribute`)

Explicitly submitted data is used solely for "TEP Report aggregation and the next reference distribution," for no other purpose. It is retained until the next annual Report; withdrawal requests are honored via the contact channel the submitter chose to include in the payload (optional) or via the public repository's issue tracker.
