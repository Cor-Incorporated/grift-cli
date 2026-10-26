# Migrating to v0.9.0

Japanese original: [migration-v090.md](../migration-v090.md). That page also keeps the notes for
0.8.0 and earlier (in Japanese). This page covers what changed in 0.9.0.

The existing `analyze` / `report` / `verify` / `contribute` commands still produce report-v1. Every
command from v0.6.0 to v0.8.0 is still there. The reasons are in `docs/adr/ADR-0002-trait-profile.md`
(stage 1) and `docs/adr/ADR-0001-v08-no-volume-ordering.md`.

## What changes in 0.9.0

**No new commands. The Markdown opens with plain sentences and interview questions, JSON values
change in four situations, and the alignment JSON gains one optional key.** CLI flags and enum
values do not change. Each JSON change fixes a place where a number or a reading about a person or a
project could be wrong.

### The Markdown opens with how the work shows in the record, and interview questions (PR #86)

The `grift actor`, `grift project` and `grift align` Markdown now opens with plain Japanese sentences
picked from the JSON numbers by the [decision tables](trait-profile.md), and with questions to confirm
in an interview. The detailed number sections from 0.8.0 follow them.

- Person-facing sentences appear only for an identity the person claimed
  (`attribution_state=claimed`) with a consent record (`consent=recorded-explicit-consent`). An
  identity registered by an administrator (verified), a cluster inferred from a public repository, an
  identity without a consent record, and a shallow clone get one sentence that says why nothing is
  shown
- Collections (`--all` / `--top`) get no sentences
- When a number cannot be confirmed, no sentence is written from it (for example when `role_profile`
  counts a different set of changes, in a shallow clone, or when `--as-of` is set and the tag dates
  are unknown). The reason is written instead
- The sentences, their ids and type keys never enter the JSON. The JSON does not change with this

### "Strength" and `relationship` leave the Markdown (PR #88)

The heading 「傾向の強さと確からしさ」 becomes 「傾向の確からしさ」, and the "strength" line of each
tendency and the alignment `relationship` line are gone. Side by side, two reports read as a stronger
and a weaker person, or as a good and a bad fit. The JSON does not change. In alignment-v1,
`axes[].actor_tendency.strength` / `axes[].project_tendency.strength` are **deprecated** and will be
removed in the next schema version.

### The four viewpoints use griftai.org's names (PR #95)

The `grift actor`, `grift repo`, `grift project` and `grift align` Markdown names the four viewpoints
the way griftai.org does, as plain words followed by the site term: 変えた部分の区分（作業領域）
(parts changed), 変更のペース（変更リズム） (pace of change), テストの付け方（検証の形） (how tests
are added), and 関わり方 (how they take part; griftai.org uses the same word as plain words and as the
site term, so that heading has no second name). The headings and sentences of the opening section,
the viewpoint column of the evidence table, the headings of the detailed sections, the tendency names
and the names of the project's requirement items change. JSON keys and the fixed texts inside the
JSON (such as `limitations`) do not change, so those texts keep their older wording. The names are
listed in [the metrics guide](metrics-guide.md).

The site term for survival changes from 定着率 (retention rate) to コードの新しさ (Code recency). The
value is not the share of lines that stayed: it is the mean of how recently the lines in the current
code were written, weighted with 180 days as the scale, and a value near 1 means most lines were
written recently. How the value is computed does not change.

### Alignment interview questions need a claimed identity and the consent record (PR #96)

The alignment-v1 subject gains an optional `actor_consent` (its only value is
`recorded-explicit-consent`). `grift align` copies the actor report's consent record into it, checked
by the same function as the actor's person-facing sentences (`actor_basis.consent_recorded`). A
cluster inferred from a public repository never carries it.

The alignment's interview questions appear only for an identity the person claimed (claimed) that
carries `actor_consent`. An identity registered by an administrator (verified), an identity without a
consent record, and a cluster inferred from a public repository get one sentence that says why no
questions are shown. `grift verify` does not trust a saved `actor_consent`: it rebuilds it from the
actor report, so an alignment with the value added or removed by hand is MISMATCH.

### Alignment fixes (PR #85, **affects saved alignments**)

These fix discrepancies found while reading real 0.8.0 output (design document §1.4). The alignment
JSON (`align`, `align --team`) and the actor, project and alignment Markdown change. The actor and
project report JSON does not change with this.

- **How the direction (`relationship`) is decided** (a breaking change in meaning). 0.8.0 compared one
  person's count with the whole team's count, so the person's side came out small in any repository
  with many people. 0.9.0 compares shares within each side (the share of the person's commits that
  touched that place, and the same share for the whole repository), and records
  `"compared": "commit_share"` with the two shares (`actor_share` / `project_share`). When either share
  has fewer than 20 in its denominator, the two are not compared (`not_comparable`). The change rhythm
  axes (`change_rhythm.*`) count different things for one person and for a repository, so they are
  never compared
- **The window of the place and test axes**. Both count the history up to the observation date, but
  they carried a 180-day window. The window is now
  `{"end": <observation date>, "basis": "history_to_observation_date"}`, and the Markdown says
  "the history up to …"
- **The rhythm tendency**. It was called a regular cadence whatever the values were. Its `value` is now
  `rhythm_observed`; read the shape from the numbers (`basis`)
- **How the place tendency is chosen**. It uses the same commit share as the list
  (`surface_commit_share`). When the share is unknown, or two or more places share the largest share
  (a commit that changes code and tests counts for both), it is `not_proven`
- **The unit of declared test types** is `verification-type` (also `requirements[].declared.unit` of
  `align --team`)
- The Markdown shows the project's title and no longer appends unit names to values. In the Japanese
  Markdown, the selectivity notice is in Japanese (the JSON `notices` keep the fixed English text)
- The survival text in the metrics guide now matches the implementation: the mean of how recently the
  lines at HEAD were written (τ = 180 days, up to 40 files). The 0.8.0 text ("the share of lines still
  present after 180 days") read it backwards. Documentation only; the output does not change

### The detailed sections no longer say "the whole history" (PR #89)

The window of the place and test sections says "the history up to <observation date>". A shallow
clone counts only what was fetched, and the project report does not record whether it was shallow.
The JSON does not change.

### Without `--as-of`, the observation date is HEAD's UTC day (PR #90, **affects saved reports**)

Without `--as-of`, 0.8.0 took the observation date from HEAD's author-local day but cut the range by
each commit's UTC day. A HEAD made in the evening west of UTC (for example in the Americas) is already
the next day in UTC, so HEAD fell out of its own report. 0.9.0 takes the observation date in UTC too.

This changes only when HEAD's local day and UTC day differ. Then `observation_date`, `git_window` and
`change_rhythm` change in the actor, repo and project reports. An evening west of UTC moves one day
later, and every commit of HEAD's UTC day is counted. A morning east of UTC (0:00–9:00 in Japan, for
example) moves one day earlier.

### With `--as-of`, activity and role_profile are cut at the observation date too (PR #91, **affects saved reports and collections**)

With `--as-of`, the place, test and rhythm sections were cut at that date, but `activity` (active
days and so on) and `role_profile` (how they take part) still counted commits, merges and tags after
it, so numbers in one report disagreed. 0.9.0 counts activity from the person's own commits up to the
observation date (UTC), counts role_profile from commits and tags up to the end of that day
(23:59:59 UTC), and ends the role_profile window on the observation date. Activity includes
`core_activity_period`, and the activity of a repo report with `--identity` changes too. The check of
a collection written with `--as-of` (`grift verify DIR`) recounts with the same date.

Without `--as-of`, nothing changes. `experience` (dependency experience) is not cut at the
observation date yet, because the dependency reading has no dates.

### A name-based cluster id never takes a declared identity's id (PR #92, **affects saved reports and collections**)

When a person written in the identity file (for example `alice`, `alice@example.com`) had no commits,
the commits of another person with the same author name "Alice" and a different email could take
`alice` as their name-based id. The consented `alice`'s role_profile counts commits by id, so it
counted the other person's commits as alice's. 0.9.0 reserves every declared identity id, with or
without commits; the other person's cluster then gets a hash id (`actor_<hash>`). In the JSON, that
person's role_profile and experience numbers, the repo report-v2 `actor_directory` ids,
`partition_digest`, and the card ids and file names of collections change.

```
# Synthetic repo: 25 commits by author "Alice" <alice.other@example.org>; the identity declares only alice (alice@example.com)
# Collection index written by 0.8.0: [{"actor_id":"alice","commit_count":25}]
# Collection index written by 0.9.0: [{"actor_id":"actor_764e6d7e62373f8135d186bf29dd3b91","commit_count":25}]
$ grift verify coll-080 --repo repo --identity identity.toml
MISMATCH: partition digest, actor membership/counts, card actor membership:alice.json
# rc=1 (measured 2026-10-26). The collection rewritten by 0.9.0 is VERIFIED
```

### Do you need to re-collect?

| Output | `grift verify` 0.9.0 on what 0.8.0 wrote | Regenerate |
|---|---|---|
| report-v1 (`analyze` / `report`) | CANNOT_VERIFY (definition version) | Yes, if you use verify |
| actor / repo report-v2 (outside a collection) | CANNOT_VERIFY (definition version) | Yes |
| project report (project-v1) | MISMATCH (the `definition_version` field) | Yes |
| alignment (alignment-v1, `align --team`) | CANNOT_VERIFY (definition version); `relationship` also changes meaning | Yes |
| actor collection (`repo --actors`, `actor --all/--top`, `actor ID --out DIR`) | The definition version is not checked. MISMATCH if written with `--as-of`, or if an identity actor has no commits and someone else has the same author name; otherwise VERIFIED | Yes, for those that are MISMATCH |
| attest / portfolio | Re-sign if the input report's digest changes | Depends on the input |

## Definition version

`DEFINITION_VERSION` moves from `tep-v0.8.0-2026-10-25` to `tep-v0.9.0-2026-10-26` (REL-090), for the
JSON changes above (alignment, observation date, `--as-of` cut, cluster id) and the Markdown changes.
The measured `grift verify` results on outputs written by 0.8.0 are in the
[Japanese notes](../migration-v090.md) (definition version section).

## CI

The workflows do not change. Because the source changed, the four evidence sets were rebuilt from the
0.9.0 source: the golden baseline was migrated as `gold-actor-partition-0006` (approved by
human:teradakousuke at 2026-10-26T12:14:18Z, requirement REL-090; the drift was only the version
strings, with no change in observed values), the private scenario registry passed 6 / 6, the public
PR-tier registry passed 3 / 3, and the benchmark held 6 / 6 self-contained claims. Details are in the
[Japanese notes](../migration-v090.md) (CI section).
