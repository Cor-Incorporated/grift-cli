# export-v1 — opt-in machine-ingestion output (frozen 2026-08-22)

Japanese original: [export-schema.md](../export-schema.md). Field tables are
mirrored; the Japanese original is authoritative.

- `grift analyze <repo> --export <dir>` writes three files:
  `commits.ndjson` (one row per commit: sha/ts/origin(11-class)/
  actor(canonical_id|null)/bot/is_merge/prod+test path counts/
  cochange(bool|null — only production-changing commits carry a value)/
  subject_class(fix|revert|other)), `actors.json` (canonical_id,
  attribution_state, commits, active_days, first_ts/last_ts, core_period —
  attribution and engagement only; per-actor quality metrics are permanently
  excluded), and `export-meta.json` (schema `tep-export-v1`,
  `config_digest`, definition versions, `analysis_scope`)
- `ts`, `first_ts` and `last_ts` are `YYYY-MM-DD` author dates in the author's
  own time zone (`--date=short`), the same days report-v1 uses. The
  `repo` / `actor` / `project` / `align` reports cut the range in UTC days
  (since v0.6) and take the observation date as a UTC day (since v0.9.0), so at
  a day boundary (an evening west of UTC, or
  0:00–9:00 in Japan) these values differ from them by one day
- **Raw emails and raw author strings are never exported.** The no-`@`
  property is enforced by tests
- report and export share `prepare_inputs()` — a single implementation
- Narrative numbers must come from report.json aggregates (ruling 5);
  consumers recompute from commits.ndjson and abort ingestion on mismatch
- `config_digest`: sha256 over the canonical JSON of the normalized identity
  + definition versions + flags (full spec in the Japanese original)
- `--export` never changes the stdout contract
