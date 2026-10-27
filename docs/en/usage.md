# Using grift

This page continues from "Try it" in the [README](../../README.en.md). grift is the command-line implementation of TEP (Technical Evidence Pipeline). This page covers each command in detail, the output formats, and every operation that touches the network. Japanese version: [docs/usage.md](../usage.md).

How to read the numbers: [metrics-guide.md](metrics-guide.md). The report-v2 layout: [report-v2.md](../report-v2.md) (Japanese).

## One person's record next to a project's requirements

```bash
pipx install grift-cli
cd your-repo
grift repo                  # this repository's record (report-v2)
grift actor candidate_001 --identity .tep/identity.toml --format both --out actor-report.json
grift project --requirements .tep/project.toml --format both --out project-out
grift align \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --format both --out alignment-out
```

`--repo --identity --actor --project` remains a compatibility path. If project observed is not provided, Markdown states that actor vs project observed comparison was not performed.

Verify a saved alignment with:

```bash
grift verify alignment-out/alignment.json \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --reference-manifest benchmarks/v060/sources.json
```

Verify an alignment made on the compatibility path with the same repository, identity and project TOML it was made from. The inputs you pass pick the path: `--project` without both of `--actor-report` and `--project-report` means the repository path; both of those without `--project` mean the saved-report path. When both input sets are complete, or neither is, the file's `subject.mode` decides: `saved_reports` means the saved-report path, anything else the repository path. A saved-report alignment checked on the repository path starts its MISMATCH with `note: subject.mode is 'saved_reports'`.

```bash
grift verify alignment.json --repo . \
  --identity .tep/identity.toml --project .tep/project.toml
```

On both paths the `subject` (including the consent record `actor_consent` and `project_id`) is rebuilt from the inputs and compared, never copied from the saved JSON. The repository path also rebuilds the provenance and limitations, and reads from the saved JSON only the recompute inputs (what `--as-of`, `--role-lens`, `--vendor-scan`, `--survival` and `--reference` were). An alignment made with `--event-window` does not yet verify on the repository path (to be fixed in 0.9.2). The saved-report path trusts the actor report it is handed and rebuilds from it; check that actor report separately with `grift verify actor-report.json --repo REPO --identity IDENTITY`.

`grift report alignment-out/alignment.json` only re-renders the Markdown from the saved JSON; it checks nothing. Whether the interview questions are shown comes straight from the actor selection, identity kind and consent record written in the JSON (`subject.actor_selection`, `subject.actor_attribution_state` and `subject.actor_consent`); re-rendering an actor report treats its person-facing sentences the same way. `grift verify` is what checks that the JSON was not changed (for an alignment made from saved reports, check the actor report too, as above). The Markdown says the same under "数字の読み方と限界" (how to read the numbers and their limits).

## Writing out several people at once

```bash
# closed collection: full repository population plus selected Actor cards
grift repo . --actors --format both --out actor-collection
grift verify actor-collection --repo .

# strict collection selecting one Actor (consent-gated experience/role stays on the card)
grift actor candidate_001 . --identity .tep/identity.toml \
  --format both --out actor-explicit-collection
grift verify actor-explicit-collection --repo . \
  --identity .tep/identity.toml
```

`--top N` is a volume-based selection: it picks the N actors with the most commits. The criterion is commit count, not quality or rank. Index rows, selected cards (including those N) and the report-v2 `actor_directory` are listed in actor-id order (canonical_id when an identity exists, otherwise `actor_<hash>`), never by commit count (since 0.8.0).

When a collection is passed to alignment, `--actor-id` (alias `--actor`) is required if it contains multiple cards; there is no implicit first-card selection.

```bash
grift align --actor-dir actor-collection --actor-id ACTOR_ID \
  --project-report project-out/project.json --format both --out alignment-from-card
```

## Command reference

Since v0.6 the main entry points name the **subject**. `--out` is required to save; `.grift/` is not created by default. Default `--format` is `md`.

| Command | Action |
|---|---|
| `grift repo` | Observe a git working tree (`report-v2`, repo scope) |
| `grift actor ID` | stdout / `--out FILE.json|FILE.md` is a basis-aware observation for one `canonical_id` (`report-v2`); `--out DIR` is an explicit strict collection. No pattern guessing, no `--export` |
| `grift project` | Observed operating signature and/or declared requirements (`project-v1`). Git-only does not observe review/issue operations |
| `grift align` | Axis-by-axis declared vs observed view (`alignment-v1`). No overall score |

The verbs from the 0.5 series keep their meaning: **analyze = display (stdout)** · **report = record (`.grift/`)**.

| Verb | Action |
|---|---|
| `grift analyze` | Analyze the current repository and **print to stdout** (report-v1; repo scope; does not create `.grift/`) |
| `grift report` | Analyze and **record into `.grift/report.{json,md}`** (always re-analyzes the current HEAD; repo scope by default, `--scope tenant` available) |
| `grift verify` | Recompute `.grift/report.json` under recorded provenance (VERIFIED / MISMATCH / CANNOT_VERIFY) |
| `grift contribute` | Build an opt-in payload from `.grift/report.json` (**never auto-sends to us**; after consent writes `.grift/contribution.json` and prints steps). **`--open`** pushes a branch with the payload and meta file committed to your fork and opens the PR creation page in the browser (uses your own gh credentials and your own fork; the final button is yours) |
| `grift update` | Explicitly upgrade grift-cli. `--check` is the only update-check path and only displays the latest version |

- `.grift/` is the dedicated output directory (auto-created). Adding `.grift/` to your `.gitignore` is recommended
- Custom invocations keep the explicit form: `grift analyze path --scope tenant --identity .tep/identity.toml --out dir`
- With an explicit path, `grift analyze REPO` uses `--scope tenant` (default): work matched in `.tep/identity.toml`; `--scope repo` observes all non-bot human commits for process observation and reference distributions. Bare `grift analyze` and `grift report` use repo scope.

At repo scope, the report-v1 written by `grift analyze` / `grift report` includes one reference position line ("decile N"): where the repository's value falls in the distribution of public repositories at repo scope. At tenant scope it is `not_observed(scope_is_tenant)`. It locates a repository among repositories; it does not rank people. Reference distribution v2026.09 is compared **only at repo scope**. Do not plot tenant values on the repo distribution (mixing scopes makes the distribution a lie). The band definition is in [metrics-guide.md](metrics-guide.md); distribution sizes are in [validation.md](validation.md).

## Actor presentation basis

Actor presentation is classified from `subject.selection` and
`subject.attribution_state`. `inferred_actor` without an identity is a public
Git cluster. Only explicit `claimed` gets personal-view wording; `verified` is
an admin-authorized, non-personal view. Explicit `inferred|external|unresolved|bot`
is nonconsenting, and a missing or contradictory state fails closed as unknown.
The CLI does not prove the declarer, consent, or personhood, including for
`claimed`. The legacy `provenance.analysis_scope=tenant` machine field in an
Actor report is now limited to explicit `verified|claimed`; public inferred and
explicit nonconsenting bases use `actor_cluster`. `actor_cluster` is a repo-local
Git primary-author cluster, not a presentation basis or evidence of consent or
personhood.

## Team coverage gaps (`grift align --team`)

Reports whether a team covers the declared requirements, **as counts of people only**.
No individual measurement is emitted, not even as an anonymous maximum. Below three
members it returns `not_observed` (`reason: insufficient_team_size`) rather than a count
that could identify one person. The input is **report-v2 only**: the `actor-card-v1`
written by `grift actor ID REPO --out DIR` is refused, because a card carries no surface
observations, so reading it would turn every requirement into `not_observed` while still
looking like a measurement of the team.

```bash
# one report-v2 per member (--format json writes report-v2 to stdout)
grift actor alice . --identity .tep/identity.toml --format json > team/alice.json
grift actor bob   . --identity .tep/identity.toml --format json > team/bob.json
grift actor carol . --identity .tep/identity.toml --format json > team/carol.json
grift align --team --actor-dir team --project-report project-out/project.json
```

## Declared delivery outcomes (`--outcome-declaration`)

Accepted by `grift repo` and `grift actor` only. What you pass is always recorded as
`kind: "declared"` and never becomes an observation. **`grift verify` does not compare
this block**, so a modified declaration is not detected by verify. Passing the flag to
`grift project` or `grift align` is an `unrecognized arguments` error.

```bash
grift repo . --outcome-declaration .tep/outcome.toml --format json
```

## Prevalence of introduced libraries (`library_context`, actor scope)

Reports how widespread, in the reference corpus, the libraries this Actor introduced are.
It **describes libraries, not the person**. It appears in actor-scope output only.

```bash
grift actor candidate_001 . --identity .tep/identity.toml --format json
```

## Public forge fetch (`--fetch-public`, opt-in)

`grift repo REPO --rev REV --fetch-public --public-evidence-out DIR` pins one
Git OID, collects every page of the GitHub or GitLab commits API through a
provider-neutral adapter, and stores response bodies in a mode-0600
content-addressed bundle. `--public-evidence DIR` replays that bundle without a
network connection; `--resume-public-evidence DIR` resumes only a safely
recorded partial collection. The default path makes no connection.

- The Actor partition is fixed first from the pinned Git history and the
  pinned tree's `.mailmap`. GitHub account linkage uses only a commit's
  top-level `author.id`. GitLab's documented commits API has no account-link
  field, so it remains `unsupported/not_proven`. Handles and similar names
  never merge Actors.
- A rate or page limit leaves a resumable bundle and returns exit 3
  (`PARTIAL`). `verify --public-evidence DIR --repo REPO` checks the manifest,
  every body digest, reparsed items, and missing/extra/duplicate OIDs against
  the pinned local `git rev-list`, without reconnecting.
- Select `--forge-provider auto|github|gitlab`, `--forge-api-base URL`, the
  environment-variable name `--auth-token-env NAME`, and a safe
  `--max-public-pages N` explicitly. The token value itself is never accepted
  as an argument or written to evidence.
- REST collection follows provider API terms and rate-limit responses; it does
  not apply crawler-oriented robots.txt. License evidence comes from the
  pinned Git tree and provider terms remain separate collection metadata.
- Provider detection uses exact hosts or an explicit provider/API base,
  including self-managed GitLab. SSH/SCP/HTTPS remotes, ports, IPv6, and
  userinfo are parsed and sanitized rather than matched by substring.
- Tokens, Authorization headers, raw emails, and local absolute paths are not
  written to artifacts.

## Target-bound forge / tracker exports

v0.6 subjects accept `--forge-export` / `--tracker-export` only when the v2
input binds a provider, host, stable project ID/path, target OID, UTC window,
and coverage. Normalized events remain provider-neutral. A repo view includes
all rows, while an Actor view uses exact `actor_canonical_id` equality only.
Rows present in a partial input remain observed lower bounds; absence, cadence,
and shares remain `not_proven`.

Tracker v2 validates a closed issue/milestone state chain, predecessor/link
integrity, and a finite non-negative duration equal to the timestamp
difference. That duration is not work time, speed, quality, or ability. See the
[local export contract](../input-export-schema.md) (Japanese) for the JSON contract.

## Actor collections and strict schemas

`repo --actors`, `actor --all`, `actor --top N`, and `actor ACTOR_ID --out DIR`
write a closed collection into a new directory. Use `--out FILE.json|FILE.md` for the
single-Actor detailed report-v2 compatibility path:

```text
repo-report.json / repo-report.md       # full population
actor-index.json / actor-index.md       # full and selected indexes
actors/<actor-id>.json / .md            # selected cards
collection-manifest.json                # path/bytes/SHA-256 for every member
```

The writer does not replace an existing directory. Full and selected counts,
partition/population/selection digests, and each card's n/denominator must agree
across JSON, Markdown, and the manifest. `grift verify DIR --repo REPO` rejects
path traversal, symlinks, unregistered files, and tampering. Add
`--public-evidence EVIDENCE_DIR` when independently verifying a collection that
contains provider-account evidence.
An explicit card may contain closed-schema `experience` / `role_profile`: an
observation produced by the explicit-consent gate or
`not_observed(consenting_actor_required)`. Neither the machine-field name nor
its presence proves consent. Verification recomputes both fields from the fixed
OID and identity instead of trusting a self-consistent card/manifest rewrite.
From 0.9.1 a collection written with an identity records its digest in
`repo-report.json` as `provenance.identity_digest`. Verify reports a different
identity as the first MISMATCH item,
`identity (recorded identity_digest …, observed …)` (the recorded and the
observed digest), with a `note:` line asking for the same `--identity FILE`. A
collection written without an identity, or by 0.9.0 or earlier, has no such key;
when it does not verify, only a `note:` line is added (the identity may not be the
cause). An identity that cannot be loaded gives `CANNOT_VERIFY` (exit 2).

report-v1 and export-v1 keep their additive compatibility contract. report-v2
and new v0.6 artifacts use closed Draft 2020-12 schemas and reject unknown
keys. See [report-v2.md](../report-v2.md) (Japanese).

## Identity and AI identity sources

The only implicit identity source for v0.6 subject commands is
`.tep/identity.toml` as recorded in the target's fixed Git tree. An identity in
the caller's current directory and checkout-only changes are ignored when a
different repository is observed. Pass `--identity FILE` for an explicit
external file. Experience/role requires one explicit Actor row containing both
`attribution_state=verified|claimed` and
`consent=recorded-explicit-consent`; attribution state or `authority` alone
does not unlock it. The CLI validates the recorded marker, not real-world
subject consent, declarer identity, or personhood. Existing identities without
the marker, plus `inferred`, `external`, `unresolved`, and `bot`, remain
`not_observed(consenting_actor_required)`.

AI `Co-authored-by` classification likewise reads only the fixed tree's closed
`.tep/ai-identities.toml` contract. Declare at least one exact email or the
same domain-separated `email_sha256` used by identity-v2:

```toml
schema_version = "ai-identity-v1"
emails = ["agent@example.invalid"]
# email_sha256 = ["<64 lowercase hex>"]
```

Checkout-only additions, names, handles, and similarity never infer an AI
identity. Existing `AI-Assisted-By`, `AI-Generated-By`, and `Agent-Lane`
trailers keep their behavior; an undeclared `Co-authored-by` remains human.

The identity file format: [identity-schema.md](identity-schema.md).

## Attestation and portfolio (opt-in)

A verified report can sign a canonical statement through external OpenSSH or
cosign. Signature validity, report hash, and repository recomputation remain
separate results. A valid signature is not presented as proof that a metric is
correct, that work is high quality, or that one person is superior.

```bash
grift attest actor-report.json --repo REPO --identity IDENTITY \
  --out actor-attest --sign ssh --ssh-key KEY --principal SUBJECT
grift verify actor-report.json --repo REPO --identity IDENTITY \
  --bundle actor-attest --allowed-signers ALLOWED_SIGNERS --principal SUBJECT
```

When a report used public evidence, forge/tracker exports, or a reference
manifest, pass the same `--public-evidence`, `--forge-export`,
`--tracker-export`, and `--reference-manifest` options to both `attest` and
`verify`. The statement binds every member digest and their aggregate, the
definition-version set, and the reachable tag set. Missing inputs prevent
signing; tagger names and emails are not copied into the statement.

`grift portfolio --manifest portfolio.toml --format both --out portfolio-out`
builds a context × role × period × evidence ledger across repositories. A
shared subject is linked only by an explicit submitter declaration or an
attestation, never by similar emails or handles. It always reports eligible and
included repository counts plus disclosure, and emits no averages, weights,
scores, or ranks.

`subject_binding = "self_declared"` in the manifest is the submitter's explicit
declaration. `subject_binding = "attested"` succeeds only when every report-v2
contains the same explicit subject ID and every detached signature verifies
under one recipient trust policy. Supply `--allowed-signers FILE --principal ID`
for SSH, or `--cosign-public-key FILE` / `--certificate-identity ID` plus
`--certificate-oidc-issuer URL` for cosign. A bundle's self-declared key is never
a trust anchor. Missing trust, a wrong signer, mixed binding methods, or a
subject mismatch fails closed. Trust-file absolute paths stay out of output;
repository hints are omitted unless each entry explicitly opts in through the
manifest. JSON and Markdown distinguish every entry as
`not_verified_self_declared` or `recipient_trust_verified`.

## Output format and exit codes

| Exit code | Meaning |
|---|---|
| 0 | `VERIFIED` or command success |
| 1 | `MISMATCH` |
| 2 | `CANNOT_VERIFY`, usage error, or input-contract violation |
| 3 | safe, resumable partial public collection |

With `--format json`, stdout is **exactly one JSON document**, so a program can read it without filtering. `--format md` writes markdown only; `--format both` writes markdown, a blank line, then JSON. Diagnostics and errors always go to stderr. `--out DIR` does not change the stdout contract. Single reports use command-specific fixed names; Actor collections use the closed layout above.

The field-by-field report-v1 definition is
[report-schema.md](report-schema.md) (frozen, additive-only).
report-v2 and Actor collections are documented in
[report-v2.md](../report-v2.md) (closed schemas, Japanese).

Every number carries a unit and provenance (method=TEP, tool=grift, definition version, analyzed SHA, `analysis_scope`). Run `grift analyze . --format md` on your own repository to see them. The values are written like this (a made-up example):

- test co-change: 0.30 ratio (12 of 40)
- corrective rework: 0.05 ratio (2 of 40); observational, not an evidence claim
- path retouch: 0.45 ratio; observational only

Below population 20, neither the rate nor a distribution position is shown (`insufficient_population`; raw counts only).

The Shared block (the 3-5 line copy-pasteable summary at the top of every
report) carries no glosses. It is pasted into résumés and issues, where a short
block is easier to use; the per-line glosses in the body and
[metrics-guide.md](metrics-guide.md) carry the meanings.

## Machine ingestion export (opt-in)

`grift analyze <repo> --export <dir>` writes commits.ndjson (one row per commit: origin / actor / cochange), actors.json (attribution and engagement per canonical_id), and export-meta.json (with `config_digest`). **No raw emails or author strings are ever exported.** Aggregates in report.json remain authoritative for narrative. Details: [export-schema.md](export-schema.md).

## Operations that use the network

- `analyze` and `report` are offline. `repo` and `actor` are offline by default and use an **explicit network** path only with `--fetch-public` or `--resume-public-evidence`. `verify` replays saved bundles without reconnecting. The other explicit network paths are `update` (including `--check`), `contribute --open`, and cosign keyless; there is no implicit update check
- This CLI has no feature that sends data to us automatically, and we will not add one to this CLI. If Cor.Inc. offers a separate application or service built on grift, that service's terms of service and privacy policy will set out how it handles data. `contribute --open` stops at your own fork; the final button is yours

## Opt-in data submission (`grift contribute`)

Submissions to the **TEP Report and the next reference distribution** start by fixing a privacy profile and door:

```bash
grift report                                      # 1) create a repo-scope report
grift contribute --privacy aggregate --door public-pr --out .grift/contribution.json
# 3) submit the payload as a PR to tep-contributions
```

The intake repository is [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions).

- report-v1 retains the legacy `tep-contribution-v1` contract. For report-v2, the default `aggregate` profile drops actor rows, repo/remote/OIDs, exact timestamps, and source digests. `named-public` retains only explicitly authorized provider-neutral project/account evidence
- `masked` reads a 32-byte-or-longer HMAC key only from a permission-checked file or FD. It and `raw` are restricted to `local` / `controlled`; their 0600 sidecar carries research source/governance, and `public-pr` is a hard error. No automatic controlled upload exists before an authorized destination does
- `--open` explicitly uses the submitter's GitHub credentials to push a fork branch; the final button is yours. A proxy PR may hide submitter identity, but its payload still becomes public and cannot be fully withdrawn from existing Git history, clones, or forks
- Intake CI accepts legacy v1 plus public-safe v2 `aggregate` / `named-public` under mode-specific allowlists, rejecting masked/raw, raw email, internal actor IDs, and credential shapes
- Use is limited to "TEP Report aggregation and the next reference
  distribution"; retained until the next annual Report; withdrawal via issue

The submitter chooses what the data is for with `--purpose`: `reference-distributions`
(the default when unset, the same meaning as v0.6.0) or `outcome-linkage`.
`outcome-linkage` cannot use `--door public-pr`: the public intake schema still accepts
only the v0.6.0 value, so grift refuses up front instead of letting you build and
disclose a payload that the intake would then bounce.

```bash
grift contribute --purpose outcome-linkage --door local
```

## Upgrading from 0.9.0

The full notes are in [migration-v091.md](migration-v091.md) (the [Japanese original](../migration-v091.md) also keeps the notes for older versions) and the [changelog](../../CHANGELOG.md) (in Japanese). What needs regenerating:

- Reports saved by 0.9.0 (`analyze`, `actor`, `repo`) and alignments (`align`) are CANNOT_VERIFY under 0.9.1 `grift verify` (`DEFINITION_VERSION` changed). Project reports that observed a repository are MISMATCH. Regenerate them with 0.9.1
- Collections written by 0.9.0 with `--as-of` are MISMATCH under 0.9.1 `grift verify` (experience, test_cochange and rework are now cut at the observation date too). Regenerate them
- An identity file whose `canonical_id` has the shape `actor_` plus 12–32 hex digits makes 0.9.1 exit 2. Rename the id. If the identity is committed to the repository and read at a fixed revision, pass a fixed copy with `--identity FILE`
- v2 reports count `context_profile` days in UTC. In repositories with commits made between 0:00 and 9:00 in Japan, the values can differ from 0.9.0

## Upgrading from 0.8.0

The full notes are in [migration-v090.md](migration-v090.md) (the [Japanese original](../migration-v090.md) also keeps the notes for older versions) and the [changelog](../../CHANGELOG.md) (in Japanese). What needs regenerating:

- Reports saved by 0.8.0 (`analyze`, `actor`, `repo`) and alignments (`align`) are CANNOT_VERIFY under 0.9.0's `grift verify`, because `DEFINITION_VERSION` moved; project reports are MISMATCH. Regenerate them with 0.9.0
- From 0.9.0, the alignment direction (`relationship`) compares each side's own share instead of one person's count against the whole team's count. The values mean something different from 0.8.0's, so do not put them side by side
- Collections written by 0.8.0 with `--as-of` are MISMATCH under 0.9.0's `grift verify`, because `role_profile` is now cut at the observation date. Regenerate them
- In a repository where an identity actor has no commits and someone else has the same author name, 0.8.0 reports and collections counted the other person's commits as the actor's. Regenerate them with 0.9.0
- Without `--as-of`, a report whose HEAD has a different author-local date and UTC date (an evening west of UTC, or 0:00–9:00 in Japan) had its observation date off by one day. Regenerate it with 0.9.0

## Upgrading from 0.7.x

The full notes are in [migration-v080.md](../migration-v080.md) and the [changelog](../../CHANGELOG.md) (both in Japanese). What needs regenerating:

- Reports saved by 0.7.x are CANNOT_VERIFY under 0.8.0's `grift verify`, because `DEFINITION_VERSION` moved. Regenerate them with 0.8.0
- Collections written by 0.7.x fail `grift verify` under 0.8.0 (MISMATCH), because rows that list actors are now in actor-id order. Regenerate them
- With 0.7.0 or 0.7.1, `grift export --scope tenant` on a repository where no identity actor had any commits wrote `prod_paths_touched` and `test_paths_touched` as 0 for every commit. Re-run such exports with 0.7.2 or later
- Since 0.7.1, `--fetch-public` counts bot commits as unlinked instead of giving them a public account, so account linkage counts change for repositories with bot commits. Re-collect with 0.7.1 or later
