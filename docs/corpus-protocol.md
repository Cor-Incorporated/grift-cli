# Corpus protocol (v0.5) — write kill criteria before running

Goal: test **discriminatory power** and **game resistance**, not that anyone is
"senior". Public output is anonymous percentiles only. Named-person scorecards
are forbidden.

## Groups in this repository

| Group | What it represents | In this repo |
|---|---|---|
| A | High verification culture | golden click, express, typer |
| D | Template / fork / no tests | golden gitignore, Spoon-Knife |
| B | Notable individual works | not shipped (ethics: no personal ranking) |
| C | AI-heavy / vibe-coding | not shipped until a public pin is agreed |
| E | Private ground truth | Grift-only; never copied here |

## Kill criteria (written before measurement)

Compute group A vs group D on `test_cochange.all_time.value` among repos where
the metric is observed with `narrate_rate=true`.

- Discard test co-change if the two group medians differ by less than 0.10
  (absolute) **or** the ranges fully overlap.
- Rework: WP1b-1 裁定により `corrective_rework_rate` は **観測専用**
  （件名規約依存の交絡。evidence_claim から降格）。`path_retouch_rate`
  も観測専用。いずれもコーパスの証拠主張に使わない。行レベル再挑戦は v0.6。
- Do not load a corpus until H-4 (corrective definition + click sanity
  gate < 20%) is closed.
- Survival is opt-in (`--survival`). Kill it if wall time per repo exceeds
  120 seconds before any language rewrite is considered (git I/O first).
- Line-level rework is v0.6 opt-in (numstat/diff), same I/O caution as survival.

If a metric is killed, keep origin/attribution as the floor. Do not invent a
composite score to replace it.

## Narrative lock (corrective rework)

Registered before any corpus interpretation:

> Low `corrective_rework_rate` is **not** evidence of few bugs. The metric
> measures whether paths written recently needed an immediate fix/revert —
> **fresh-work stability**. Expanding it to “code quality” or “seniority”
> is forbidden (grade smell).

Markdown reports must carry this limit next to the number.

## A vs D pass criteria (registered 2026-08-22, before this pilot run)

Two tiers. A metric may pass Tier 1 and still be **inconclusive** on Tier 2.
Do not promote an inconclusive rate test into a pass by lowering the bar
after seeing numbers.

### Pins for this pilot

- **A**: golden `click` (identity present), `express`, `typer`
- **D**: golden `gitignore`, `Spoon-Knife` (already in `.golden-cache`)
- **C** (selected, not required for A/D): `https://github.com/mabene/vibe.git`
  — self-described 100% AI-generated product code. Reports use the **repo
  name only** (no person scorecard). SHA is pinned at first clone in
  `corpus/manifest.toml`. A/D does not wait on C.

### Tier 1 — observation status (A vs D)

Pre-specified direction: D is “no verification substrate / no tenant
population”, not “a low rate”.

- D: `test_cochange.kind == not_observed` with reason
  `no_test_framework_or_directory` **or** `pending_attribution`.
- A with an identity file: `test_cochange.kind == observed` and
  `all_time.narrate_rate == true`.
- Population below 20: do not narrate the ratio and do not attach a
  reference decile (`insufficient_population`). Raw counts only
  (e.g. `9コミット中2件`).
- A without identity: excluded from tenant-rate comparison. `test_frameworks`
  may still be observed (culture marker only).

**Pass**: every D pin matches D; every identity-bearing A pin matches A.
**Fail**: any D pin posts an observed narratable co-change rate, or click
fails to narrate.

### Tier 2 — rates (only if both groups have n ≥ 2 observed + narratable)

Metrics: `test_cochange.all_time.value`, `corrective_rework_rate.value`.
`path_retouch_rate` is excluded from the claim.

For each metric, **all** of:

1. Direction (co-change): median(A) − median(D) ≥ 0.10.
   Direction (corrective): **not** “A has fewer bugs”. Pre-specified only
   vs C later: median(C) − median(A) ≥ 0.10 would support “fresh work less
   stable”. A vs D has **no** required direction on corrective because D is
   expected not_observed.
2. Range: closed intervals [min, max] of A and D must not fully contain
   one another (complete overlap / inclusion → fail).
3. Effect size: Cliff’s δ, A vs D, |δ| ≥ 0.33 (medium). With n < 2 in
   either group, **do not compute δ**; mark `inconclusive_small_n`.

**Kill** the metric if Tier 2 runs and fails (1) or (2) or (3).
**Inconclusive** if n < 2 in a group — keep the floor (origin/attribution);
do not declare discriminatory power.

### C pin (public, for a later C vs A run)

Not executed in the A/D pilot. First public pin:

| id | url | why it is C (repo-level, not a person) |
|---|---|---|
| C1-vibe | https://github.com/mabene/vibe.git | README states the codebase was generated through AI dialogue with no human-authored source |

## Command

```bash
grift analyze <repo> --identity .tep/identity.toml
# survival is separate because blame is git-I/O bound
grift analyze <repo> --survival
```
