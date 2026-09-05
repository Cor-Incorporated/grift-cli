# Persona answer demonstrations — golden-measured answers (wave 1 + v0.6 status)

Japanese original: [persona-answers.md](../persona-answers.md). Transcribed
numbers are machine-checked against golden expected files by CI
(`tests/test_persona_answers.py`); the Japanese original carries the
`転記:` (transcription) lines that the tests parse.

Source: BD `tep-adversarial-review-20260822.md` (9 personas, ◎7/△12/✗3;
21 questions). Wave 1 answers with existing report-v1 fields; the three ✗
questions (Q3-2 / E1 / E4) carry limit statements citing the norms — honesty
is part of the demonstration. A question without a measured answer is marked
as an observation gap, a permanent limit, or implemented with release evidence
still outstanding.

## v0.6 P1 status addendum (2026-08-31)

| Surface | Current state | Not yet established |
|---|---|---|
| experience + four-dimensional role_profile | Code, closed schemas, and exact synthetic tests exist; third-party public / identity-less subjects stay not_observed | The blind pilot (ready 0 / blocked 14) is incomplete, so real-world validity and release acceptance are not proven |
| declared_ai_assist_share × declared_ai_test_cochange | Implemented from versioned trailers / AI identity in the fixed tree and excited in synthetic fixtures; zero declarations are not read as no AI use | Public G6 is not used to infer actor experience; pre-answered pilot comparison remains incomplete, and AI use or superiority is not inferred |
| role_profile | Implemented as domain / work type / time / process-position composition | It does not classify a job title, fit, rank, or a person's true role |
| portfolio | Implemented as context × role × period × evidence with selectivity and separate declaration/recipient-trust states | Local falsification does not establish market value, a complete career, or exhaustive coverage |

The wave-1 values below remain historical demonstrations. Public-OSS golden
cases pin repo-level detectors and legacy regressions; their actor
experience/role expected files are not regenerated. Numeric v0.6 P1 persona
examples must wait for the blind-pilot gate.

Highlights (see the Japanese original for the full 21 entries):

- **Q1-1 (what does this add to an interview?)**: click golden values —
  test co-change 0.2664 (73 of 274) — interview-question generation at
  a resolution résumés cannot provide
- **Q1-2 (can't you game it?)**: metrics where gaming produces the real
  thing; no substrate → not_observed (G6 claude-code) vs vitest/playwright
  observed (G13 voicevox)
- **Q2-2 (inflated identity?)**: lineage recorded (G3 fork); recomputation via
  `grift verify` is implemented, but it does not prove identity or consent
- **Q3-3 (vs coding tests?)**: instantaneous ability vs behavioral history
  (G8 co dormant 299 commits vs G12 httpx 1,376 and growing)
- **Q3b (consentless analysis?)**: repo scope aggregates public git log —
  the same range as GitHub Insights; personalization requires identity.toml;
  the norms forbid non-consensual third-party profiling
- **E2 (solo repositories)**: context classification exists, but the v2026.11
  solo stratum is n=9, below MIN_N 30; no solo decile is claimed
- **✗ Q3-2 / E1 / E4**: permanent limits remain explicit even though norms
  articles 1/3 and the declared-AI detector are implemented; the "honest ones
  lose first" period is not hidden

Wave-1 filed issue (dev repo): #8 (no repo-scope expected pin for the decile
demonstration). Exact synthetic tests do not substitute for the blind pilot.
