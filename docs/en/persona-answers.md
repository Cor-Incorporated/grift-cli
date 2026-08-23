# Persona answer demonstrations — golden-measured answers (wave 1)

Japanese original: [persona-answers.md](../persona-answers.md). Transcribed
numbers are machine-checked against golden expected files by CI
(`tests/test_persona_answers.py`); the Japanese original carries the
`転記:` (transcription) lines that the tests parse.

Source: BD `tep-adversarial-review-20260822.md` (9 personas, ◎7/△12/✗3;
21 questions). Wave 1 answers with existing report-v1 fields; the three ✗
questions (Q3-2 / E1 / E4) carry limit statements citing the norms — honesty
is part of the demonstration. Each wave files issues for questions that
cannot be answered with measured values.

Highlights (see the Japanese original for the full 21 entries):

- **Q1-1 (what does this add to an interview?)**: click golden values —
  test co-change 0.2664 (73 of 274) — interview-question generation at
  a resolution résumés cannot provide
- **Q1-2 (can't you game it?)**: metrics where gaming produces the real
  thing; no substrate → not_observed (G6 claude-code) vs vitest/playwright
  observed (G13 voicevox)
- **Q2-2 (inflated identity?)**: lineage recorded (G3 fork), recomputation
  via `grift verify`
- **Q3-3 (vs coding tests?)**: instantaneous ability vs behavioral history
  (G8 co dormant 299 commits vs G12 httpx 1,376 and growing)
- **Q3b (consentless analysis?)**: repo scope aggregates public git log —
  the same range as GitHub Insights; personalization requires identity.toml;
  the norms forbid non-consensual third-party profiling
- **✗ Q3-2 / E1 / E4**: permanent limits, stated as such (norms articles 1
  and 3; the "honest ones lose first" period is not hidden)

Wave-1 filed issues (dev repo): #11 (template_inherited unexcited),
#12 (no repo-scope expected pin for decile demonstration).
