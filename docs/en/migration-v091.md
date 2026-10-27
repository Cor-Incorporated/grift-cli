# Migrating to v0.9.1

Japanese original: [migration-v091.md](../migration-v091.md). That page also keeps the notes for
0.9.0 and earlier (in Japanese). This page covers what changed in 0.9.1. For 0.9.0, see
[migration-v090.md](migration-v090.md).

The existing `analyze` / `report` / `verify` / `contribute` commands still produce report-v1. Every
command from v0.6.0 to v0.9.0 is still there.

## What changes in 0.9.1

**No new commands. 0.9.1 fixes places, listed after the 0.9.0 release, where numbers or wording
about a person or a project could be wrong.** CLI flags and enum values do not change. Two optional
keys are added: one to project-v1 and one to the collection's provenance. JSON values change in the
cases below.

### With `--as-of`, experience, test_cochange and rework are cut at the observation date too (PR #106, **affects saved reports and collections**)

0.9.0 counted experience, test_cochange and rework over the whole history even with `--as-of`, and
counted the 13-week window of test_cochange back from HEAD's date. 0.9.1 counts all of them up to the
end of the observation date (UTC), commits and tags alike, and counts the 13-week window back from
the observation date. Introduced dependencies (`dependency_introduction`, `library_context`) count
only the commits up to that date. With `--as-of`, activity days are counted on the same UTC days the
range is cut on.

- Keys that change: `test_cochange.*` (including `last_13w`), `rework.*`, `experience.*`
  (`window.end` becomes `<date>T23:59:59Z`), `library_context`, `activity.active_days`,
  `commits_per_active_day`, `active_days_13w`, `core_activity_period`, and the collection cards'
  `experience`
- Without `--as-of`, nothing changes
- Without `--as-of`, actor activity still counts days by the author's local date (for report-v1
  compatibility), while `context_profile` (below) and `change_rhythm` count UTC days. The two can
  differ in one report (listed for 0.9.2)

### v2 reports count `context_profile` days in UTC (PR #104, **changes ordinary repositories too**)

0.9.0 cut ranges on UTC days but counted the days of `context_profile` in v2 reports (repo, actor,
project, align) by the author's local date. One report could show different values for
`context_profile.active_days_180d` and `change_rhythm.active_days_180d` (7 and 6 at this
repository's pinned revision `fa9bc31`). 0.9.1 counts UTC days.

- Any commit whose local date differs from its UTC date (in Japan, 0:00–8:59; west of UTC, the
  evening) can change `context_profile.scale.first_commit` / `last_commit` / `active_span_days`,
  `repo_age_days`, `days_since_last_human_commit`, `active_days_180d`, `lifecycle_stage`,
  `actor_turnover` and `release_cadence`
- report-v1 (`grift analyze`) does not change
- With `--fork` and without `--vendor-scan`, v2 `context_profile` uses the same file-blind
  classification as v1

### Forge and tracker export windows are read as UTC days (PR #104)

Export windows were read with `[:10]` of the timestamp, so a window written with a non-UTC offset
landed on a different day than its UTC day. They are now read as UTC days. A window written west of
UTC can now be matched with `--event-window`. An export written east of UTC whose `[:10]` matched the
Git window by coincidence now becomes `windows_not_equivalent`.

### Commits whose subject contains separator-like characters are no longer dropped (PR #104)

`git log` parsing dropped or misaligned commits whose subject contained 0x1f, U+2028 and the like.
Fields are now NUL-separated and read by position. Ordinary histories give the same result (checked
on 26,032 commits in 5 repositories). With the git setting `log.showSignature=true`, signature check
lines no longer end up in commit file lists (grift passes `log.showSignature=false` to git).

### Shallow clones are described accurately in the JSON (PR #103, **affects saved shallow-clone reports**)

- `grift project REPO` writes `provenance.revision_completeness` (`{shallow, promisor, complete}`,
  the same shape as report-v2) into project-v1 (optional; only when a repository is given). When the
  repository is shown not to be shallow, the project Markdown says "the whole history" for the range.
  Project reports from 0.9.0 without the key still load and still verify
- For a shallow clone, the report-v2 `limitations` sentence now names the values reported as
  `not_observed` and the blocks counted from the fetched commits only. (0.9.0 said "actor totals are
  reported as not_observed" while surface and change_rhythm came out observed.) Full-clone reports do
  not change
- Alignment JSON built from a 0.9.1 project report carries `revision_completeness` in
  `project_provenance`

### Declared identity ids and name-based cluster ids no longer mix (PR #105, **an identity file may need editing**)

- An identity `canonical_id` may no longer have the shape of a grift hash id
  (`^actor_[a-f0-9]{12,32}$`). Such a file exits 2, and the message names the row and the reason.
  Rename the id to a readable one such as `alice`. If the file cannot be edited (for example a
  `.tep/identity.toml` committed to the repository and read at a fixed `--rev`), pass a fixed copy
  with `--identity FILE`
- An author whose name has that shape is now counted under their own hash id instead of the name
  slug (0.9.0 stopped with exit 2 when it collided with another cluster's hash id). In such
  repositories, collection actor ids, `partition_digest` and card file names change
- A collection written with an identity records `provenance.identity_digest` in `repo-report.json`.
  `grift verify` with a different identity reports a MISMATCH that names `identity`, even when the
  partition is the same. Collections from 0.9.0 do not have the key; pass the same identity as when
  they were written (verify prints a note when it differs)
- When the identity cannot be loaded, collection verify now says CANNOT_VERIFY (exit 2) instead of
  MISMATCH

### Alignment verification rebuilds instead of copying the saved JSON (PR #102)

`grift verify <alignment.json> --repo REPO --identity IDENTITY --project PROJECT` rebuilds the
subject, provenance and limitations the same way `grift align --repo` does, and compares them.
(0.9.0 copied `project_id`, `mode` and most of the provenance from the saved JSON.) Alignments made
with `--survival`, `--vendor-scan` or `--reference` no longer always fail. The alignment JSON does not
change.

For an alignment built from saved reports (`--actor-report` / `--project-report`), the consent record
comes from the actor report, so verify the actor report too:
`grift verify actor-report.json --repo REPO --identity IDENTITY`. Re-rendering with
`grift report <alignment.json>` does not check the consent record; the alignment Markdown now says
so under its notes on reading the numbers.

### Markdown fixes (PRs #100, #101)

- With `--as-of`, the actor Markdown states the number of release tags (annotated tags) made up to
  the observation date, with an interview question about them, when role_profile's window was cut at
  the end of the observation date
- A tendency row no longer repeats the viewpoint name ("変更のペース（変更リズム）: 変更の間隔が観測される")

### Not in 0.9.1 (listed for 0.9.2)

- Without `--as-of`, an ancestor whose author date is after HEAD's (after a rebase or cherry-pick)
  still drops out of the report (M3). A fix was tried and taken out: with it, a single commit dated
  in the future (a bot's included) moved the whole report to that date. The observation date stays
  HEAD's author date as a UTC day, as in 0.9.0

### Do you need to re-collect?

| Artifact | 0.9.0 output under 0.9.1 `verify` | Re-collect |
|---|---|---|
| report-v1 (`analyze` / `report`) | CANNOT_VERIFY (definition version) | Yes, if you use verify |
| actor / repo report-v2 (outside a collection) | CANNOT_VERIFY (definition version) | Yes |
| project report (project-v1) | With an observed repository (`grift project REPO`): MISMATCH (`definition_version`). Requirements only: VERIFIED | The former |
| alignment (alignment-v1, `align --team`) | CANNOT_VERIFY (definition version) | Yes |
| actor collection | The definition version is not checked. Collections written with `--as-of` are MISMATCH (`experience recomputation`), as are those of repositories with an author named like a hash id. Others VERIFY | Those that MISMATCH |
| attest / portfolio | Re-sign when an input report's digest changes | Depends on input |

Measured on 2026-10-27 with a synthetic repository; the commands and outputs are in the Japanese
original. All 8 outputs regenerated with 0.9.1 verify under 0.9.1.

## Definition version

`DEFINITION_VERSION` goes from `tep-v0.9.0-2026-10-26` to `tep-v0.9.1-2026-10-28` (REL-091), to match
the value changes above. Keeping the definition version while raising only the package version is not
possible: the golden runner treats the `provenance.tool_version` change as D3 drift (FAIL), and a
baseline approval requires D4 (definition version) drift.

## CI

The provisional FAIL summary of `v060-provider-live.yml` is now written after checkout (#99), so a
failed release-tier run uploads it. The four evidence gates were regenerated from the 0.9.1 source;
the golden baseline approval is a human step (see the Japanese original for the dry-run drift: D3 ×1,
D4 ×2, D0–D2 = 0, no observed-value drift).
