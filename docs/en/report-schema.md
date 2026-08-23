# report.json schema (report-v1) — frozen 2026-08-22

Japanese original: [report-schema.md](../report-schema.md). In case of any
discrepancy, the Japanese original is authoritative; field tables below are
mirrored verbatim.

- Constant: `tep_core.version.REPORT_SCHEMA_VERSION = "report-v1"`
- Validator: `tep_core.schema.validate_report(report, subset=False) -> list[str]`
  (pure standard library; empty list = valid)
- History (F-P10-2): v0.5.0 emitted `schema_version: "tep-report-v1"`; renamed
  to `report-v1` immediately before the freeze (identifier change only).
  **Consumers must accept only `report-v1` from v0.5.1 onward**

## Stability promise

While report-v1 lives, **additions only**. Renaming, removing, or changing the
meaning of an existing field requires report-v2. The validator does not reject
unknown keys (additive compatibility); consumers must ignore unknown keys.

## Observation encoding

| kind | Shape | Meaning |
|---|---|---|
| `observed` | `{"kind": "observed", "value": <num>, "unit": "<unit>", "sample_size": <int>=optional}` | Observed. **0 is a legal observed value** |
| `not_observed` | `{"kind": "not_observed", "reason": "<snake_case>"}` | Cannot be observed. Reason codes are an open set |

`insufficient_population` (population < 20) suppresses rate narration
(`narrate_rate: false`) and deciles; raw counts may be shown.

## Top-level structure

`schema_version` · `provenance` (tool/method/version/definition versions/
`analysis_scope`/`analyzed_commit_sha`/`analyzed_at`) · `repository` ·
`identity` · `lineage` · `origin` (11 classes) · `attribution` · `activity` ·
`core_activity_period` · `test_frameworks` · `test_cochange` · `rework` ·
`survival` · `context_profile` · `interpretation`.

`analysis_scope`: `tenant` (identity-matched evidence) or `repo` (all human
commits; the only scope that may consult reference distributions).
See the Japanese original for full per-field tables, the context_profile
(lifecycle-v2) section, and the exit-code/stdout contract.
