# grift — evidence that does not inflate in the AI era

[日本語](README.md) | **English**

Method = **TEP** / Tool = **grift** (two-layer naming, CodeScene-style: the methodology stays TEP; the command is `grift`).
Named after the Grift product line.

Anyone can produce volume. This tool measures what remains, and which changes came with verification. It is not a skill score.

## Usage norms

The conditions for calling a use "TEP-compliant" are defined in [docs/norms.md](docs/norms.md) (seven articles, JA/EN: do not read absence as negative; no single-metric cutoffs; do not read AI declaration as negative; no third-party profiling without consent; surveillance use is non-compliant; disclose selectivity; no weighting or conversion). **Compliance with these norms is a condition of using the TEP name.**

Commit counts, line counts, and “activity” inflate easily once agents and generated code are in the loop. grift reads git only and emits TEP provenance (whose work) and a verification layer (test co-change and related metrics) **deterministically**. No LLM. No composite score. No skill-rank labels.

## Start in five minutes

```bash
pipx install grift-cli
grift analyze ./my-repo --scope repo
```

If the package is not on PyPI yet: `pipx install .`

- `--scope tenant` (default): work matched in `.tep/identity.toml` = **evidence**
- `--scope repo`: all non-bot human commits = **process observation and reference distributions**

Reference distribution v2026.09 is compared **only at repo scope**. Do not plot tenant values on the repo distribution (mixing scopes makes the distribution a lie).

## Example report

Run `grift analyze . --format md` on your own repository. Every number carries a unit and provenance (method=TEP, tool=grift, definition version, analyzed SHA, `analysis_scope`).

Example (click, tenant scope, golden G1):

- test co-change: 0.2664 ratio (73 of 274)
- corrective rework: 0.0109 ratio (3 of 274) — observational; not an evidence claim
- path retouch: 0.573 ratio — observational only

Below population 20, neither the rate nor a distribution position is shown (`insufficient_population`; raw counts only).

## Exit codes and stdout / stderr contract

| Exit code | Meaning |
|---|---|
| 0 | success |
| 2 | usage error, or the given path is not a git repository |
| 1 | any other unexpected failure (details on stderr) |

With `--format json`, stdout is **exactly one JSON document** (purity guarantee for machine consumption). `--format md` writes markdown only; `--format both` writes markdown, a blank line, then JSON. Diagnostics and errors always go to stderr. `--out DIR` does not change the stdout contract (it additionally writes `report.md` / `report.json`).

The full field-by-field definition of report.json lives in [docs/report-schema.md](docs/report-schema.md) (schema `report-v1`, frozen, additive-only).

## Machine ingestion export (opt-in)

`grift analyze <repo> --export <dir>` writes commits.ndjson (one row per commit: origin / actor / cochange), actors.json (attribution and engagement per canonical_id), and export-meta.json (with `config_digest`). **No raw emails or author strings are ever exported.** Aggregates in report.json remain authoritative for narrative. Details: [docs/export-schema.md](docs/export-schema.md).

## Metrics and limits

| Metric | What it is evidence of | Limit |
|---|---|---|
| origin / attribution | whose work | unset identity → unresolved. Real tenant emails are not shipped |
| test co-change | whether production changes came with tests | no test substrate → `not_observed`. population &lt; 20 → no rate and no decile (`insufficient_population`) |
| corrective rework | recent-path return with a fix/revert subject (observational) | **demoted from evidence claim**. confounded by subject conventions. not a bug count. line-level retry is v0.6 |
| path retouch | same-file re-touch | observational only. not an evidence claim |
| survival (τ=180d) | whether lines remain | `--survival` only. reference distribution planned for **v2027**. not in this public distribution |

Reference position is a single “decile N” line. Metrics with n&lt;30 omit position (`reference_too_small`). Current v2026.11 measured n: test co-change 68 / corrective rework 101 (observational) / survival 0 (planned for v2027). The older v2026.09 stays immutable and selectable via `--reference-version`.

## Discriminatory power (repo scope, criteria `5f2665e`)

Source: `corpus/DISCRIMINANT-v2026.11.md` (n=117: all v2026.09 rows + 70 v2026.11 admissions). Verdicts copied **verbatim** from the file.

- `test_cochange A vs D` → `separated` (median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18) — **first separation with a standing n**; the first strong evidence for the "anyone can produce volume" thesis
- `test_cochange A vs C` → `fail_tier2` (median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21) — was `separated` in v2026.09 (δ 0.7143), but the grown C pool (AI-driven repos WITH tests) reduced the separation. **The registered criteria were not lowered; the reversal is published as-is**
- `corrective_rework A vs C / A vs D` → no required direction (observational only, unchanged since v0.5.0). A vs C δ -0.8333 / A vs D δ 0.0139
- Honest population note: C narratable = 14 (short of the 30 target, corrected by machine-verified admission) / D total 29 (target 20 met)
- survival: reference distribution planned for v2027

The v2026.09 record (Run 2: A vs C `separated` etc.) remains as history in `corpus/DISCRIMINANT-v2026.09.md`.

## GitHub Action (observation only)

```yaml
uses: Cor-Incorporated/grift-cli@v0.5.3
with:
  scope: repo
```

- Runs `grift analyze`, prints the **shared block to $GITHUB_STEP_SUMMARY**, and uploads report.md / report.json as artifacts
- **No pass/fail, no thresholds, no failure exit — observation only, permanently**
- PR comment requires explicit opt-in (`comment: true`, default off)
- Minimal permissions recommended (`contents: read`; `pull-requests: write` only when `comment: true`)

## Ethics

- Named-person scorecards and league tables are forbidden, publicly and internally
- Do not emit skill-rank labels (senior / junior / “excellent”)
- Corpus manifests (repo name + SHA) may be published for reproduction. **Per-repo value league tables are not published**
- Control group E (private ground truth) is not in this repository

## Status

- Public repository: https://github.com/Cor-Incorporated/grift-cli
- Command name: **`grift`** (methodology name TEP remains on reports)
- PyPI: distribution name **`grift-cli`**. Publishing is a separate human gate (until then, `pipx install .`)

## License

MIT. See [LICENSE](LICENSE).
