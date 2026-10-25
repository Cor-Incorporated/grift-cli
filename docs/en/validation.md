# Metric validation and limits

This page records whether grift's metrics actually differ between groups of public repositories. It is a check on the metrics themselves, against criteria written down before measuring; it is not a way to rank people or repositories. The protocol is in [corpus-protocol.md](corpus-protocol.md) and the source record is `corpus/DISCRIMINANT-v2026.11.md`. Japanese version: [docs/validation.md](../validation.md).

## Design choices and their boundaries

grift preserves evidence whose conditions and limits a recipient can inspect and,
when the source is available, recompute. It does not reduce a person to one number.

| Design choice | Practical value | Boundary |
|---|---|---|
| No LLM | Model, provider, and prompt updates do not change the measurement | A new definition version or input revision can change it, so provenance remains part of every result |
| Fixed OID, versioned definitions, deterministic recomputation | A recipient can rerun the same input and detect differences or tampering | Reproducibility is not proof of correctness, quality, or superiority |
| Local/offline by default | History, identity, and results stay on the machine except on an explicit network path | Public fetch, `update` (including `--check`), `contribute --open`, and cosign keyless are explicit network paths |
| No composite score, rank, or weighting | Units, populations, windows, and limits remain visible instead of becoming a hidden hiring cutoff | Human context review, interviews, and code review are not replaced |
| `not_observed` and suppression below population 20 | Missing history and small samples are not converted into negative evidence | Private history and outcomes outside git are not filled in or inferred |
| Attestation and portfolio selectivity disclosure | A recipient can inspect who measured under which conditions and which repositories were selected | A signature proves an execution fact; a portfolio is a selected evidence ledger, not a person judgment |

## Limits of each metric

| Metric | What it records | Limit |
|---|---|---|
| origin / attribution | whose work | unset identity → unresolved. Real tenant emails are not shipped |
| test co-change | whether production changes came with tests | no test substrate → `not_observed`. population &lt; 20 → no rate and no decile (`insufficient_population`) |
| corrective rework | recent-path return with a fix/revert subject (observational) | not used as an evidence claim (demoted). confounded by subject conventions. not a bug count. line-level retry is v0.6 |
| path retouch | same-file re-touch | observational only. not an evidence claim |
| survival (τ=180d) | whether lines remain | `--survival` only. reference distribution planned for **v2027**. not in this public distribution |

## Reference position

The reference position in report-v1 is a single "decile N" line: the band in which the repository's value falls among public repositories at repo scope. There is no tenant-scope distribution, so tenant-scope reports show `not_observed(scope_is_tenant)` instead. Metrics with n&lt;30 omit the position (`reference_too_small`). Current v2026.11 measured n: test co-change 68 / corrective rework 101 (observational) / survival 0 (planned for v2027). The older v2026.09 stays immutable and selectable via `--reference-version`. Band definitions are in [metrics-guide.md](metrics-guide.md).

## Differences between groups (repo scope, criteria `5f2665e`)

The groups of public repositories are fixed before measuring: A has a strong verification culture, C is AI-heavy, and D is templates, forks, or repositories without tests (definitions in [corpus-protocol.md](corpus-protocol.md)). The check asks whether a metric's values differ between groups.

Source: `corpus/DISCRIMINANT-v2026.11.md` (n=117: all v2026.09 rows + 70 v2026.11 admissions). Verdicts copied **verbatim** from the file.

- `test_cochange A vs D` → `separated` (median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18). The first separation with enough repositories on both sides, and the first strong result for grift's premise that anyone can inflate volume such as commit counts, but not changes that come with tests
- `test_cochange A vs C` → `fail_tier2` (median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21). It was `separated` in v2026.09 (δ 0.7143), but the grown C pool (AI-driven repos WITH tests) reduced the separation. The registered criteria were not lowered; the reversal is published as-is
- `corrective_rework A vs C / A vs D` → no required direction (observational only, unchanged since v0.5.0). A vs C δ -0.8333 / A vs D δ 0.0139
- Population: C narratable = 14 (short of the 30 target, corrected by machine-verified admission) / D total 29 (target 20 met)
- survival: reference distribution planned for v2027

The v2026.09 record (Run 2: A vs C `separated` etc.) remains as history in `corpus/DISCRIMINANT-v2026.09.md`.

## Publication rules

- Named-person scorecards and league tables are forbidden, publicly and internally
- Do not emit skill-rank labels (senior / junior / “excellent”)
- Corpus manifests (repo name + SHA) may be published for reproduction. **Per-repo value league tables are not published**
- Control group E (private ground truth) is not in this repository
