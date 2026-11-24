# Corpus protocol (v0.5) — write kill criteria before running

Japanese original: [corpus-protocol.md](../corpus-protocol.md).

Goal: test **discriminatory power** and **game resistance** — not whether
anyone is "senior." Named-person scorecards are forbidden.

## Groups

| Group | Represents |
|---|---|
| A | High verification culture |
| B | Notable individual works (repo URLs only in public docs) |
| C | AI-heavy / vibe-coding (2024+) |
| D | Template / fork / no-tests |
| E | Private ground truth (Grift-only; never copied here) |

## Kill criteria (registered before measurement)

- Test co-change is discarded if the A-vs-D medians differ by < 0.10 or the
  ranges fully overlap
- `corrective_rework_rate` is **observational only** (subject-convention
  confounding; demoted from evidence). `path_retouch_rate` likewise. Line-level
  retry is v0.6
- Survival is opt-in (`--survival`); killed if a repo exceeds 120s wall time
- If a metric is killed, keep origin/attribution as the floor. Never invent a
  composite score to replace it

## Tier definitions

Tier 1 (observation status): D expected `not_observed` or pending
attribution; identity-bearing A expected observed + narratable. Population
< 20 → no rate, no decile, raw counts only. Tier 2 (rates, only if both
groups have n ≥ 2 narratable): direction ≥ 0.10, ranges not fully contained,
Cliff's δ ≥ 0.33 — else `inconclusive_small_n`.

## Verbatim record

Verdicts (separated and fail alike) are recorded verbatim in
`corpus/DISCRIMINANT-*.md`. v2026.09 history: A vs C `separated` / A vs D
`inconclusive_small_n` / corrective A vs C `fail_tier2`. v2026.11: A vs D
`separated` (δ 0.9198, n 18/18) / A vs C `fail_tier2` (δ 0.291 — the grown C
pool reduced separation; criteria were not lowered).

## Bootstrapping from public repositories (0.9.6, `scripts/corpus_bootstrap.py`)

Builds a new reference version from public repositories alone, without `contribute`. The shipped `v2026.09` and `v2026.11` are immutable (the script refuses them); use a new version name such as `v2026.12`.

1. `plan` (offline): from candidates (TOML or JSON with `url`, optional `group` and `sha`) or existing pin files (`--from-pins`), drop non-public https URLs (credentials, ssh, other hosts), duplicates, heavy clones and anything over the limit, each with a reason.
2. `observe` (network): clone each planned repo and analyze with an empty identity at `scope=repo` (`--survival` also records survival). No person's identity enters. Per-repo values stay in the gitignored `corpus/runs-<version>/results.jsonl`; the public `corpus/pins-<version>.toml` holds url, sha and group only.
3. `build`: write `corpus/<version>/distributions.json`. Deciles are issued only for metrics with n ≥ 30; a short metric gets a note and no distribution (`reference_too_small`). Placing the file under `src/tep_core/data/<version>/` and switching `REFERENCE_VERSION` is a human step after the results are checked.

### Survival pre-registration

From 0.9.6 survival (line retention at τ=180d) can show a reference position as `interpretation.survival`, but the published distributions carry no survival block, so it is `reference_too_small` today. Before the first survival distribution is built, these criteria are fixed and are not lowered after seeing results; a change is recorded with its reason and date.

- Population: only repos with `lines_sampled ≥ 20` enter. Below n = 30, no deciles.
- A vs C: median gap ≥ 0.10, |Cliff's δ| ≥ 0.33, and the A and C ranges (min–max) must not contain one another. No direction is fixed in advance; the observed direction is recorded.
- Age confound: survival tends to read lower in older repos. If |Spearman ρ| against repo age is 0.5 or more, the metric is treated as an age proxy and not used to discriminate.

If any criterion fails, the result is published as-is, as with the failed A vs C test co-change comparison.
