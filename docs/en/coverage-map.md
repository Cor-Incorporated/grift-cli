# Coverage map — questions → observations (v1, introduced with PR-A)

Japanese original: [coverage-map.md](../coverage-map.md). 21 questions
(adjudicated). ★ = not yet implemented. Every feature addition starts by
updating this table.

## Hirer/manager questions

| # | Question | Answering observations | Status |
|---|---|---|---|
| Q1 | Can they actually build? | test co-change · survival · activity days · core period (existing) | Implemented |
| Q2 | Which domains/technologies? | language timeline ★ · domain paths ★ · test_frameworks · language_composition / dependency_manifests / monorepo markers (PR-A) | Partial |
| Q3 | Can they work in a team? | cross_author ★ · co_authored_share ★ · pr_flow_share (PR-A) · collaboration_class (PR-A) | Partial |
| Q4 | Maintainer or fire-and-forget? | self_maintenance ★ · dependency_update_share ★ · post_release_fixes ★ · fix/revert authorship ★ | v0.6a |
| Q5 | Transparent about AI-era work? | declared_ai_assist ★ × its co-change · generated_or_vendor | v0.6a (PR-B) |
| Q6 | Do they persist? | tenure · cadence descriptors ★ · release_cadence / actor_turnover (PR-A, repo level) | Partial |
| Q7 | Founding experience? | founder timing ★ · scaffold ★ · release creation ★ · pr_flow_share (PR-A) | Partial |
| Q8 | What scale/state of repos? | context_profile v2 (PR-A) · contribution-time repo scale ★ | Partial |

## Engineer questions (same observations, self-attestation reading)

| # | Question | Status |
|---|---|---|
| E1 | Assets, not volume | survival (implemented) · adopted_creations ★ |
| E2 | Breadth and depth | language_composition (PR-A) · domain composition ★ · portfolio (v0.6b) |
| E3 | Can handle others' code | cross_author ★ (PR-B) |
| E4 | Uses AI with verification | declared_ai_assist × co-change ★ (PR-B) |
| E5 | Returns for maintenance | self_maintenance ★ · post_release_fixes ★ (PR-B) |
| E6 | Founded something | founder timing ★ · scaffold ★ · release ★ (PR-B) |

## Not answerable from git (boundary, stated explicitly)

Code-review quality · communication · requirements analysis (the first two
are Grift-side API/human evaluation territory; requirements is permanently
out). Repo significance/popularity **grades** (permanently excluded — a repo
grade joins with attribution into a personal grade in one JOIN). Absence of
private careers / gap contents (outside TEP; norms article 1). "No
declaration = no AI use" inference (permanently forbidden).
