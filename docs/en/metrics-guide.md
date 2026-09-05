# How to read grift reports — a plain-language metric guide (v3, 2026-08-31)

Japanese original: [metrics-guide.md](../metrics-guide.md).

**Audience**: non-engineers. **Principle restated**: every number is a record
of observed fact, not a grade. Standalone pass/fail decisions and
person-to-person comparisons are non-compliant with the TEP norms
([en/norms.md](norms.md)). What is not written (= not observed) did not
"not happen." Reference values come from a 117-repository public corpus
(v2026.11, repo scope) and field measurements (requests / flask / GitHub CLI
/ chalk).

---

## Decile notation (the one definition used throughout)

**Decile N = the band containing the top (100−10N)% of values.** Formally,
with corpus boundaries d₁…d₁₀: **band N = (d(N−1), dN]** (left-open,
right-closed). Decile 5 = the middle band (50–60% from the bottom); decile
10 = the top 10% band.

- Example: click's test co-change 0.3178 falls in 0.2894 < 0.3178 ≤ 0.4871,
  hence **decile 9** (the top-20% band)
- Every band mention in this guide carries a plain-language translation
  (e.g. "decile 7 (the top 30–40% band)")

---

## Full observation inventory (what appears in a report)

grift reports consist of three layers. **A layer is a promise about how the
number may be used.**

### Attribution layer (origin, 11 classes) — "whose/what work is this commit?"

| Class | One-line definition |
|---|---|
| tenant_unique | Original (non-merge) commits by identity-matched workers |
| tenant_merge_or_sync | Tenant merge commits (PR flow; repos without upstream lineage) |
| upstream_sync | Tenant merges that pull upstream (fork-lineage repos) |
| inherited_upstream | Other people's (upstream-side) commits under fork lineage |
| tenant_derivative | Judged only with a parent repo provided: work derived from it |
| external_upstream_contribution | Judged only with a parent repo: work flowing back upstream |
| template_inherited | Judged only with a template provided: template-derived parts |
| generated_or_vendor | Commits touching only generated/vendored files |
| bot | Automation-account commits |
| ambiguous_origin | Author information missing — cannot be judged |
| unresolved | Human commits not matching the identity (no names shown) |

### Evidence layer — "changes accompanied by verification"

| Observation | One-line definition |
|---|---|
| test co-change | Share of production changes whose same commit also changed tests |
| survival | Share of lines still present after 180 days (`--survival` only) |

### Observational layer — "tendency records (not evidence claims)"

| Observation | One-line definition |
|---|---|
| corrective rework | Share of commits quickly redoing recently touched paths with fix/revert subjects |
| path retouch | Share of commits re-touching the same files within 21 days |
| revert_rate | Share of revert commits |

### Context layer (context profile) — "what kind of repo is this"

| Observation | One-line definition |
|---|---|
| collaboration_class | solo / small_team / community |
| lifecycle_stage (+ active_days_180d / days_since_last_human_commit) | Activity density (the class is always printed with the two raw observations) |
| resolved_human_actors / top_actor_share | Contributor count (upstream/bot excluded) and top-author share (no names) |
| pr_flow_share | Share of merge (PR) commits |
| scale / repo_age_days | Size (commits, span, top dirs, tags) and repo age |
| actor_turnover | Yearly join/leave counts |
| release_cadence | Tag frequency (releases/year) |
| conventional_commit_share / issue_link_density | Conventional subjects (`feat:` etc.) / `#N` references |
| language_composition / dependency_manifests / monorepo_markers | Language mix / dependency files / monorepo signs |
| test_file_ratio / docs_share | Test/docs path touches |

### Consenting-subject experience and role

This layer is emitted only for one explicit Actor selected by the fixed tree's
`.tep/identity.toml` or an explicit `--identity FILE`, and only when that row
contains both `attribution_state=verified|claimed` and
`consent=recorded-explicit-consent`. State or `authority` alone does not unlock
the layer; the CLI validates the record, not real-world consent. `inferred`,
`external`, `unresolved`, `bot`, public third-party Actors, identities without
the marker, and repositories without identity remain
`not_observed(consenting_actor_required)`. A caller CWD
identity and checkout-only identity edits are not consent for another repo.

| Observation | Definition |
|---|---|
| cross_author_modification_share | M/R commits with a known creator that touch a file created by another Actor |
| adopted_creations | Own files with at least 30 observable days that another human Actor M/Rs after day 30 |
| self_maintenance_returns | M/R returns to an own file at least 180 days after the previous touch |
| dependency_update_share | Actor non-merge commits touching manifests or lockfiles |
| post_release_fixes | Existing corrective-classifier fix/revert commits that descend from the tag target and fall within the inclusive 30-day tag-time window |
| declared_ai_assist_share | Commits with versioned AI-assistance trailers or an AI co-author identity |
| human co-authored share | Commits with a human `Co-authored-by` trailer |

The AI co-author SSOT is the fixed tree's `.tep/ai-identities.toml`
(`ai-identity-v1`, exact `emails` and/or domain-separated `email_sha256`).
Checkout-only edits, names, handles, and similarity are ignored.
`AI-Assisted-By`, `AI-Generated-By`, and `Agent-Lane` retain their existing
declaration semantics; an undeclared `Co-authored-by` remains human.
Only the final trailer block separated from the body by a blank line is parsed,
matching the supported `git interpret-trailers --parse` shape; examples inside
prose are not declarations. Declared-AI test co-change reuses the existing
test-cochange production-path taxonomy, excluding README, docs, and LICENSE
paths from its denominator.

Every observation carries kind, numerator, denominator, unit, window,
definition version, and limitations. Below denominator 20, the rate and
numerator are suppressed; only the denominator and
`insufficient_population` remain. After that population gate, zero declarations
produce `no_declared_ai_commits`; they do not establish no AI use, ability, or
rank.

Descriptive observations retain an auditable numerator too. Cadence uses the
number of adjacent commit intervals; the language/domain timeline uses target
commits with at least one path touch; repository-size points use the number of
distinct commit snapshots actually referenced by first/median/last. Their
denominator is the target human non-merge commit population, while cadence's
`unit=days` applies to its median/longest descriptors. Tag time alone never
establishes post-release ancestry: the fixed-OID parent DAG must prove that the
tag target is an ancestor of the corrective commit. A missing target or parent
path, or a cycle, suppresses the value as `not_observed`; a sibling branch is a
proven zero. Annotated and lightweight tags can mark a release boundary, but a
lightweight tag still has no tagger attribution.
Shallow, promisor-backed, or missing-object histories suppress all experience
and role values as `not_observed(history_incomplete)`. File lineage follows
parent state in the commit DAG: an existing merge path follows the first
parent, a path added from one unambiguous secondary lineage inherits that
creator, and a conflict remains unresolved. Annotated taggers match both
plaintext identity emails and identity-v2 `email_sha256` aliases.

`role_profile-v1` is not one occupation or a score. Its only top-level
dimensions are `domain`, `work_type`, `time`, and `process_position`. The
`time` dimension contains both `phase` (early/middle/recent) and
`calendar_year`; calendar year is not a fifth dimension. Process position is
creator/maintainer/integrator/release. Alignment may turn differences into
questions for a person to confirm, never fit/hire/rank.

---

## Evidence: test co-change

**Unit**: ratio (0.0–1.0). **Population**: commits that changed production code.

**What it measures**: of the commits that changed production code, the share
that changed tests in the same commit — read from git history, not
self-reports. Docs-only changes are excluded from the population.

**How to read it**:

- **High (≥ 0.233 = above the top edge of decile 7, i.e. the top-30% band)**:
  the habit of accompanying production changes with tests is established
- **Middle (0.109–0.161 = decile 5, the middle band)**: where most public
  repositories sit
- **Low / 0**: no test substrate, or tests not synchronized. **Not "bad"** —
  docs-centric repos, design phases, and tooling legitimately land low
- **not observed**: no test framework or directory detected. Cannot be
  measured ≠ zero

**Corpus bands (v2026.11, n=68, repo scope)**: decile 5 = (0.1089, 0.1613] ·
decile 7 = (0.1613, 0.233] · decile 10 = (0.4871, 0.6948]. Field examples:
GitHub CLI 0.37 · flask 0.20 · chalk 0.18 · requests 0.12 (2026-08).

---

## Observational: corrective rework & path retouch

**Not evidence claims.** Corrective rework = share of commits redoing paths
touched within 21 days with fix/revert subjects; path retouch = share
re-touching the same files in 21 days. Subject-convention dependent —
unsuitable for comparisons or pass/fail. Use high values as interview
questions ("what happened in this period?"), not verdicts. Low values do not
prove few bugs.

**Corpus bands (v2026.11, n=101)**: decile 5 = (0.0683, 0.0972] · deciles
9–10 = (0.1904, 0.4818].

---

## Survival (optional)

`--survival` only (τ=180d). 1.0-near values = lines mostly still present.
Reference distribution planned for v2027 — no high/low judgment provided yet.

---

## Context: collaboration & lifecycle

- **collaboration_class**: solo (top author ≥ 90%) / small_team (≤5 people) /
  community. Examples: requests 802 / flask 870 / GitHub CLI 722 → community
- **lifecycle_stage**: always read with the two raw observations.
  active = active_days_180d ≥ 12 / maintained = 3–11 / dormant = ≤ 2.
  Density does **not** distinguish development from maintenance (a
  high-density operational repo is legitimately active); density was chosen
  over recency so bulk housekeeping cannot fake freshness

---

## Related tools (lineage & design differences — no superiority claims)

| Name | In one line |
|---|---|
| **machuz/eis (Engineering Impact Signal)** | TEP's survival observation adopts EIS-style blame sampling as its lineage; the designs differ in fact: EIS reduces 7 axes with fixed weights to a 0-100 composite score with type labels and team side-by-sides; TEP forbids composite scores, weighting, and grade vocabulary by design, and secures trust via discriminant validation and `grift verify`. Measurement is offline by default; public Forge collection is an explicit opt-in path |
| DORA | Four delivery-performance metrics and benchmarks; TEP's norm-style usage guidelines follow the DORA pattern |
| SPACE | A satisfaction/performance/activity/communication/efficiency/flow framework; agrees with TEP that productivity is not one number |
| GitClear | Commercial code-health (technical debt, rework) research and SaaS; overlapping observations, but TEP never emits person-comparison tables and separates offline-by-default measurement from explicit public Forge collection |
| MSR | The academic field of mining software repositories; much of TEP's git-derived tooling applies its findings |
| bus factor | The degree to which a project stalls when key developers leave; top_actor_share / collaboration_class answer this question observationally |

---

## Common misreadings

| Misreading | Correct reading |
|---|---|
| "Low co-change = can't write tests" | Docs/design/tooling work lands low legitimately; reading absence as inability is non-compliant (norm 1) |
| "High corrective rework = buggy" | Subject-convention dependent; neither a bug count nor quality |
| "dormant = abandoned" | Mature repos with long maintenance cycles exist; reading gaps negatively is non-compliant |
| "Decile 9 > decile 5 person" | Deciles are positions (bands) among same-scope repos; standalone cutoffs and comparison tables are non-compliant (norm 2) |
| "No decile = hiding something" | Suppressed by rule when population <20 or corpus n<30 |

---

## When a number is absent (not observed)

`no_test_framework_or_directory` (no test substrate) ·
`insufficient_population` (<20 commits) · `pending_attribution` (identity
unset) · `scope_is_tenant` (distributions are repo-scope only) ·
`survival_scan_disabled` (`--survival` only) ·
`forge_export_not_provided` / `tracker_export_not_provided` (the local source
was not supplied; this is not zero activity) · `partial_source_coverage`
(present rows remain observed lower bounds, while absence, cadence, and shares
are not proven) · `event_kind_not_collected` (the tracker contract does not
collect that kind; this is not zero events).

v0.6 subject commands accept only target-bound v2 forge/tracker exports. The
provider, host, stable project ID/path, target OID, UTC window, and coverage
must identify one source. Forge summaries expose event count, kind, active UTC
days, window, and missing coverage. Tracker summaries use a validated closed
issue/milestone state chain; durations are timestamp differences, never work
hours or delivery speed. Actor views filter by exact `actor_canonical_id` only
and never infer a person from names, emails, or provider handles. See the
[local export contract](../input-export-schema.md).

---

*This is the plain-language companion of docs/report-schema.md (the
authoritative, machine-validated reference).*
