# How to read grift reports — a plain-language metric guide (v2, 2026-08-23)

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
| **machuz/eis (Engineering Impact Signal)** | TEP's survival observation adopts EIS-style blame sampling as its lineage; the designs differ in fact: EIS reduces 7 axes with fixed weights to a 0-100 composite score with type labels and team side-by-sides; TEP forbids composite scores, weighting, and grade vocabulary by design (the six prohibitions / norms), and secures trust via discriminant validation, `grift verify`, and no-transmission |
| DORA | Four delivery-performance metrics and benchmarks; TEP's norm-style usage guidelines follow the DORA pattern |
| SPACE | A satisfaction/performance/activity/communication/efficiency/flow framework; agrees with TEP that productivity is not one number |
| GitClear | Commercial code-health (technical debt, rework) research and SaaS; overlapping observations, but TEP never emits person-comparison tables and the CLI transmits nothing |
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
`survival_scan_disabled` (`--survival` only).

---

*This is the plain-language companion of docs/report-schema.md (the
authoritative, machine-validated reference).*
