# TEP (Technical Evidence Pipeline) Usage Norms — Conditions for calling a use "TEP-compliant"

**Norms v1 (2026-08-23, shipped as part of WP-P1g).** Japanese original:
[norms.md](../norms.md).

TEP is a methodology that produces verifiable evidence; it is not a decision
engine. These norms define what may be called "TEP-compliant." **Compliance
with this document is a condition of using the TEP name** (DORA-guideline-style
normative enforcement). Non-compliant use must not be called TEP.

### 1. Do not read absence as negative

Treating a missing TEP report, a private career, or a low-activity period
(gap) as evidence of lack of ability or accomplishment is non-compliant.
Reason: not_observed ≠ no achievement. Parental leave, illness, and
non-public work do not appear in git.

### 2. No single-metric cutoff

Using any TEP number or distribution position as a standalone pass/fail
criterion is non-compliant.
Reason: TEP answers questions with evidence; it does not make decisions.

### 3. Do not read declaration as negative

Treating either the presence or absence of declared AI assistance as negative
evidence is non-compliant.
Reason: Punishing transparency breeds concealment. No declaration ≠ no AI use.

### 4. No third-party profiling without consent

Constructing an identity to run tenant analysis on someone without their
consent is non-compliant.
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

Using TEP for continuous comparison or personal-evaluation tables of
organization members — public or internal — is non-compliant.
Reason: A persistent per-person comparison table is exactly the use this
methodology rejects.

### 6. Disclose selectivity

Presenting multiple repositories must be read, and shown, as "selected by
the provider."
Reason: Selective disclosure is not forbidden; hiding the selection is.
A single-repo actor report-v2 and an alignment-v1 always carry the fixed notice "This report covers one repository that the provider chose to share. It does not show whether other repositories exist or what they would show." in `notices` (v0.8.0).
The Japanese Markdown shows the same notice in Japanese, 「このレポートは、提供した人が選んで共有した 1 つのリポジトリだけを対象にしています。ほかのリポジトリがあるかどうかも、そこで何が見えるかも示しません。」 (v0.9.0); JSON `notices` keep the English sentence.
Unlike a closed résumé, visible selection is progress.

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

`grift align --team` reads several consenting actors at once and reports, **as counts only**, whether a team covers what a project declared. No individual measurement leaves the report, not even anonymously as a maximum; no vocabulary of rank or strength appears; below three actors the aggregation itself is refused because "one of two" names a person by elimination. A requirement that could not be observed is reported as not observed, never as not covered (article 1). Enforced by `src/tep_core/complementarity.py` (`MIN_TEAM_SIZE`) and `report_complementarity` in `v060-contracts.schema.json` (`additionalProperties: false`). The ban on ordering vocabulary is enforced over every string value in the output by `tests/test_v070_complementarity.py::test_no_ordering_vocabulary_appears_in_any_value`.

### Alignment has no verdict (v0.6)

`grift align` places declared requirements next to observed evidence axis by axis. Computing an overall score, rank, pass/fail, or recommendation is non-compliant (same intent as articles 2 and 7).

### Trait sentences and interview questions (v0.9)

The `grift actor` and `grift project` Markdown opens with plain sentences on how the work shows in the record, and the `grift actor` and `grift align` Markdown lists questions to confirm in an interview. The [decision tables](trait-profile.md) pick them mechanically from the JSON numbers, under these rules ([ADR-0002](../adr/ADR-0002-trait-profile.md) T1-T7):

1. A sentence is chosen by the shares and shape of the person's own work, never by volume (T1)
2. The only comparison is with the person's other work; no word that compares with other people or a reference distribution (T2)
3. Every sentence keeps its numerator, denominator and period; a share over fewer than 20 is not turned into a sentence (T3)
4. No type names: JSON carries no sentence, sentence id or type key (T4)
5. An alignment is never totalled; the number of overlapping items is not printed (T5)
6. Sentences and questions come from the published tables; no LLM (T6)
7. Person-facing sentences appear only with `attribution_state=claimed` and `consent=recorded-explicit-consent`. Actor reports for verified identities and public inferred actors get none, and the output says why; collections get no sentence section; alignment questions follow the same rule, a claimed identity with the consent record that `grift align` copies into `subject.actor_consent` (T7)

Folding the sentences into one name to rank or select people is non-compliant, as under articles 2 and 7. Enforcement: `src/tep_core/trait_tables.py` (the tables), `tests/test_v090_trait_tables.py` (docs-to-constants link and vocabulary gates), `tests/test_v090_trait_profile.py` (consent condition, no sentence in JSON, no change with volume).

### 7. No weighting or conversion

Adjusting numbers by context or difficulty is non-compliant.
Reason: Adjustment always embeds hypotheses and distorts verifiable primary
records.

## Retention, withdrawal, and reuse ban (explicit submissions via `grift contribute`)

1. **Purpose restriction (amended in v0.7)**: explicitly submitted data is used
   solely for **the purpose the submitter chose at submission time and which is
   recorded in the payload** — **never for anything else, including reuse for
   channel 4 (Grift SaaS, organization contracts, sales, or estimation)**

   The selectable purposes are a closed set. Adding one is an amendment to these
   norms: `docs/norms.md` and the implementation's `PURPOSES` must change with
   it, or `test_v070_norms_link` fails.

   | id | recorded purpose |
   |---|---|
   | `reference-distributions` | `TEP Report 集計と参照分布 vNext` |
   | `outcome-linkage` | `提出者が選択した成果連携の検証` |

   Through v0.6 the purpose was fixed to one value, which meant the project --
   not the person submitting -- decided what their data was for. This amendment
   does not widen the use; it moves the choice to the submitter and records the
   binding per submission. A submission that chooses nothing is treated as
   `reference-distributions` and means exactly what it meant in v0.6.
2. **Retention**: until the next annual Report
3. **Withdrawal**: (a) a PR deleting your own payload, or (b) a request to
   the intake repository's contact address. A proxy-PR submitter's identity
   stays private, but complete withdrawal from existing Git history, clones,
   and forks cannot be guaranteed
4. **Inference-risk disclosure**: aggregate payloads omit repo names, OIDs,
   and source digests, but the risk of re-identification from feature
   combinations is not zero — this limit is shown on every submission
   confirmation
5. **Profile-specific access**: only aggregate and named-public may use
   public-pr. Masked and raw are local/controlled only and require purpose,
   authority/consent, retention, withdrawal, and access-class governance in a
   separate controlled sidecar
