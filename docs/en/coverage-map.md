# Coverage map — questions → observations (v0.6 implementation status)

Japanese original: [coverage-map.md](../coverage-map.md). 21 questions
(adjudicated). Every feature addition starts by updating this table.
“Implemented” below means code, a closed schema, and local falsification tests
exist. The blind pilot is still ready 0 / blocked 14, so real-world validity
and release acceptance for the new v0.6 observations are **not proven**. Do not
read implementation status as PR-ready or released.

## v0.6 validation path (superseding the old Golden v2 instruction)

`docs/INSTRUCTION-golden-v2-pilot-20260822.md` asked public-OSS golden cases to
excite `experience` and `role_profile`. For v0.6, current SSOT requirement
EXP-02 supersedes that actor-level path: a third-party public actor, an
identity-less repository, or an `inferred|external|unresolved` identity must
keep both fields at `not_observed(consenting_actor_required)`.

- Public-OSS golden cases pin report-v1 regressions and repo-level detectors.
  They do not infer an identity to excite actor experience/role, and existing
  expected files are not regenerated.
- Exact synthetic tests (`tests/test_v060_experience_role.py`,
  `tests/test_v060_experience_incomplete.py`, and
  `tests/test_v060_experience_product_cli.py`) pin actor-level determinism,
  boundaries, and fail-closed behavior.
- The blind pilot checks real repositories against owner answers recorded
  before results are shown. At ready 0 / blocked 14, it establishes no
  real-world validity yet.

Accordingly, the wave 2/3 placeholders in `golden/coverage.md` are not treated
as observed. Green synthetic tests do not substitute for the blind pilot.

## Hirer/manager questions

| # | Question | Answering observations | Status |
|---|---|---|---|
| Q1 | Can they actually build? | test co-change · survival · activity days · core period (existing) | Implemented |
| Q2 | Which domains/technologies? | language/domain timeline · four-dimensional `role_profile` domain · test_frameworks · language_composition / dependency_manifests / monorepo markers | Implemented and exact-synthetic tested / blind pilot not proven |
| Q3 | Can they work in a team? | cross_author_modification_share · human_coauthored_share · pr_flow_share · collaboration_class | Implemented and exact-synthetic tested / blind pilot not proven |
| Q4 | Maintainer or fire-and-forget? | self_maintenance_returns · dependency_update_share · post_release_fixes · role_profile.work_type.corrective | Implemented and exact-synthetic tested / blind pilot not proven |
| Q5 | Transparent about AI-era work? | declared_ai_assist_share × declared_ai_test_cochange · generated_or_vendor | Implemented and exact-synthetic tested / no actor observation in public G6; blind pilot not proven |
| Q6 | Do they persist? | tenure · cadence median/longest gap · self_maintenance_returns · release_cadence / actor_turnover | Implemented and exact-synthetic tested / blind pilot not proven |
| Q7 | Founding experience? | founder_timing · initial_30d_scaffold_creation_share · annotated_tag_creation · pr_flow_share | Implemented and exact-synthetic tested / blind pilot not proven |
| Q8 | What scale/state of repos? | context_profile v2 · repository_size_at_contribution_points | Implemented / repo-level golden acceptance and blind pilot not proven |

## Engineer questions (same observations, self-attestation reading)

| # | Question | Status |
|---|---|---|
| E1 | Assets, not volume | survival · adopted_creations — implemented and exact-synthetic tested; blind pilot not proven |
| E2 | Breadth and depth | language/domain timeline · role_profile · context × role × period × evidence portfolio — implemented and locally falsified; blind pilot not proven |
| E3 | Can handle others' code | cross_author_modification_share — implemented and exact-synthetic tested; blind pilot not proven |
| E4 | Uses AI with verification | declared_ai_assist_share × declared_ai_test_cochange — implemented and exact-synthetic tested; no actor observation in public G6; blind pilot not proven |
| E5 | Returns for maintenance | self_maintenance_returns · post_release_fixes — implemented and exact-synthetic tested; blind pilot not proven |
| E6 | Founded something | founder_timing · initial_30d_scaffold_creation_share · annotated_tag_creation — implemented and exact-synthetic tested; blind pilot not proven |

## Not answerable from git (boundary, stated explicitly)

Code-review quality · communication · requirements analysis (the first two
are Grift-side API/human evaluation territory; requirements is permanently
out). Repo significance/popularity **grades** (permanently excluded — a repo
grade joins with attribution into a personal grade in one JOIN). Absence of
private careers / gap contents (outside TEP; norms article 1). "No
declaration = no AI use" inference (permanently forbidden).
