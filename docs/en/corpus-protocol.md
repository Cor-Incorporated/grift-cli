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
