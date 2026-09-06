# grift — evidence that does not inflate in the AI era

[日本語](README.md) | **English**

Method = **TEP** / Tool = **grift** (two-layer naming, CodeScene-style: the methodology stays TEP; the command is `grift`).
Named after the Grift product line.

Anyone can produce volume. This tool measures what remains, and which changes came with verification. It is not a skill score.

## Usage norms

The conditions for calling a use "TEP-compliant" are defined in [docs/norms.md](docs/norms.md) (seven articles, JA/EN: do not read absence as negative; no single-metric cutoffs; do not read AI declaration as negative; no third-party profiling without consent; surveillance use is non-compliant; disclose selectivity; no weighting or conversion). **Compliance with these norms is a condition of using the TEP name.**

Commit counts, line counts, and “activity” inflate easily once agents and generated code are in the loop. grift reads git only and emits TEP provenance (whose work) and a verification layer (test co-change and related metrics) **deterministically**. No LLM. No composite score. No skill-rank labels.

## Why grift does not produce a score

grift preserves evidence whose conditions and limits a recipient can inspect and,
when the source is available, recompute. It does not reduce a person to one number.

| Design choice | Practical value | Boundary |
|---|---|---|
| No LLM | Model, provider, and prompt updates do not change the measurement | A new definition version or input revision can change it, so provenance remains part of every result |
| Fixed OID, versioned definitions, deterministic recomputation | A recipient can rerun the same input and detect differences or tampering | Reproducibility is not proof of correctness, quality, or superiority |
| Local/offline by default | History, identity, and results stay on the machine except on an explicit network path | Public fetch, `update --check`, `contribute --open`, and cosign keyless are explicit network paths |
| No composite score, rank, or weighting | Units, populations, windows, and limits remain visible instead of becoming a hidden hiring cutoff | Human context review, interviews, and code review are not replaced |
| `not_observed` and suppression below population 20 | Missing history and small samples are not converted into negative evidence | Private history and outcomes outside git are not filled in or inferred |
| Attestation and portfolio selectivity disclosure | A recipient can inspect who measured under which conditions and which repositories were selected | A signature proves an execution fact; a portfolio is a selected evidence ledger, not a person judgment |

## Start in five minutes (subject first)

```bash
pipx install grift-cli
cd your-repo
grift repo
grift actor candidate_001 --identity .tep/identity.toml --format both --out actor-report.json
grift project --requirements .tep/project.toml --format both --out project-out
grift align \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --format both --out alignment-out

# closed collection: full repository population plus selected Actor cards
grift repo . --actors --format both --out actor-collection
grift verify actor-collection --repo .

# strict collection selecting one Actor (consent-gated experience/role stays on the card)
grift actor candidate_001 . --identity .tep/identity.toml \
  --format both --out actor-explicit-collection
grift verify actor-explicit-collection --repo . \
  --identity .tep/identity.toml
```

`--top` selects by commit count, not quality. When a collection is passed to
alignment, `--actor-id` (alias `--actor`) is required if it contains multiple
cards; there is no implicit first-card selection.

```bash
grift align --actor-dir actor-collection --actor-id ACTOR_ID \
  --project-report project-out/project.json --format both --out alignment-from-card
```

`--repo --identity --actor --project` remains a compatibility path. If project observed is not provided, Markdown states that actor vs project observed comparison was not performed.

```bash
grift verify alignment-out/alignment.json \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --reference-manifest benchmarks/v060/sources.json
```

v0.6 entry points name the **subject**. `--out` is required to save; `.grift/` is not created by default. Default `--format` is `md`.

| Command | Action |
|---|---|
| `grift repo` | Observe a git working tree (`report-v2`, repo scope) |
| `grift actor ID` | stdout / `--out FILE.json|FILE.md` is a basis-aware observation for one `canonical_id` (`report-v2`); `--out DIR` is an explicit strict collection. No pattern guessing, no `--export` |
| `grift project` | Observed operating signature and/or declared requirements (`project-v1`). Git-only does not observe review/issue operations |
| `grift align` | Axis-by-axis declared vs observed view (`alignment-v1`). No overall score |

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

Legacy verbs stay **analyze = display (stdout)** · **report = record (`.grift/`)**:

| Verb | Action |
|---|---|
| `grift analyze` | Analyze the current repository and **print to stdout** (report-v1; repo scope; does not create `.grift/`) |
| `grift report` | Analyze and **record into `.grift/report.{json,md}`** (always re-analyzes the current HEAD; repo scope by default, `--scope tenant` available) |
| `grift verify` | Recompute `.grift/report.json` under recorded provenance (VERIFIED / MISMATCH / CANNOT_VERIFY) |
| `grift contribute` | Build an opt-in payload from `.grift/report.json` (**never auto-sends to us**; after consent writes `.grift/contribution.json` and prints steps). **`--open`** pushes a branch with the payload and meta file committed to your fork and opens the PR creation page in the browser (the only remaining action is pressing "Create pull request"; uses your own gh credentials and your own fork; the final button is yours) |
| `grift update` | Explicitly upgrade grift-cli. `--check` is the only update-check path and only displays the latest version |

- **`.grift/` is the dedicated output directory** (auto-created). Adding `.grift/` to your `.gitignore` is recommended
- Custom invocations keep the explicit form: `grift analyze path --scope tenant --identity .tep/identity.toml --out dir`
- With an explicit path, `grift analyze REPO` uses `--scope tenant` (default): work matched in `.tep/identity.toml` = **evidence**; `--scope repo` observes all human commits for **process observation and reference distributions**. Bare `grift analyze` and `grift report` use repo scope.
- `--scope repo`: all non-bot human commits = **process observation and reference distributions**

Reference distribution v2026.09 is compared **only at repo scope**. Do not plot tenant values on the repo distribution (mixing scopes makes the distribution a lie).

## What v0.7.1 fixes

No new surface. A patch release for public forge fetch defects. For the details see
[docs/migration-v071.md](docs/migration-v071.md).

- **`--fetch-public` no longer aborts on bot / app accounts.** A Bot author such as
  `Copilot` or `dependabot[bot]` was given a public account it could not satisfy, and the
  run exited 2 without writing a single report. Those commits are now counted as unlinked
  instead. **Account linkage counts change for repositories with bot commits, so re-collect.**
- **A terminated transfer is detected and retried a bounded number of times.** A response
  that delivered fewer bytes than its `Content-Length` was read as JSON anyway. The length
  is now checked and the identical request is attempted at most three times.
- **The live gate records why a scenario failed.** `failure_detail` carries the exception
  class and the first 200 characters of its message, with tokens and local paths removed.

## What v0.7.0 adds

Every v0.6.0 surface remains. For the details and migration caveats see
[docs/migration-v070.md](docs/migration-v070.md).

### Team coverage gaps (`grift align --team`)

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

### Declared delivery outcomes (`--outcome-declaration`)

Accepted by `grift repo` and `grift actor` only. What you pass is always recorded as
`kind: "declared"` and never becomes an observation. **`grift verify` does not compare
this block**, so a modified declaration is not detected by verify. Passing the flag to
`grift project` or `grift align` is an `unrecognized arguments` error.

```bash
grift repo . --outcome-declaration .tep/outcome.toml --format json
```

### Prevalence of introduced libraries (`library_context`, actor scope)

Reports how widespread, in the reference corpus, the libraries this Actor introduced are.
It **describes libraries, not the person**. It appears in actor-scope output only.

```bash
grift actor candidate_001 . --identity .tep/identity.toml --format json
```

### Choosing a submission purpose (`grift contribute --purpose`)

The submitter selects what the submitted data is for: `reference-distributions`
(the default when unset, the same meaning as v0.6.0) or `outcome-linkage`.
`outcome-linkage` cannot use `--door public-pr`: the public intake schema still accepts
only the v0.6.0 value, so grift refuses up front instead of letting you build and
disclose a payload that the intake would then bounce.

```bash
grift contribute --purpose outcome-linkage --door local
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
[local export contract](docs/input-export-schema.md) for the JSON contract.

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

report-v1 and export-v1 keep their additive compatibility contract. report-v2
and new v0.6 artifacts use closed Draft 2020-12 schemas and reject unknown
keys. See [docs/report-v2.md](docs/report-v2.md).

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

## Example report

Run `grift analyze . --format md` on your own repository. Every number carries a unit and provenance (method=TEP, tool=grift, definition version, analyzed SHA, `analysis_scope`).

Example (click, tenant scope, golden G1):

- test co-change: 0.2664 ratio (73 of 274)
- corrective rework: 0.0109 ratio (3 of 274) — observational; not an evidence claim
- path retouch: 0.573 ratio — observational only

Below population 20, neither the rate nor a distribution position is shown (`insufficient_population`; raw counts only).

## Exit codes and stdout / stderr contract

| Exit code | Meaning |
|---|---|
| 0 | `VERIFIED` or command success |
| 1 | `MISMATCH` |
| 2 | `CANNOT_VERIFY`, usage error, or input-contract violation |
| 3 | safe, resumable partial public collection |

With `--format json`, stdout is **exactly one JSON document** (purity guarantee for machine consumption). `--format md` writes markdown only; `--format both` writes markdown, a blank line, then JSON. Diagnostics and errors always go to stderr. `--out DIR` does not change the stdout contract. Single reports use command-specific fixed names; Actor collections use the closed layout above.

The field-by-field report-v1 definition is
[docs/report-schema.md](docs/report-schema.md) (frozen, additive-only).
report-v2 and Actor collections are documented in
[docs/report-v2.md](docs/report-v2.md) (closed schemas).

## Machine ingestion export (opt-in)

`grift analyze <repo> --export <dir>` writes commits.ndjson (one row per commit: origin / actor / cochange), actors.json (attribution and engagement per canonical_id), and export-meta.json (with `config_digest`). **No raw emails or author strings are ever exported.** Aggregates in report.json remain authoritative for narrative. Details: [docs/export-schema.md](docs/export-schema.md).

## Opt-in data submission (grift contribute)

Submissions to the **TEP Report and the next reference distribution** start by fixing a privacy profile and door:

```bash
grift report                                      # 1) create a repo-scope report
grift contribute --privacy aggregate --door public-pr --out .grift/contribution.json
# 3) submit the payload as a PR to tep-contributions
#    https://github.com/Cor-Incorporated/tep-contributions
```

- `analyze` and `report` are offline. `repo` and `actor` are offline by default and use an **explicit network** path only with `--fetch-public` or `--resume-public-evidence`. `verify` replays saved bundles without reconnecting. The other explicit network paths are `update --check`, `contribute --open`, and cosign keyless; there is no implicit update check
- report-v1 retains the legacy `tep-contribution-v1` contract. For report-v2, the default `aggregate` profile drops actor rows, repo/remote/OIDs, exact timestamps, and source digests. `named-public` retains only explicitly authorized provider-neutral project/account evidence
- `masked` reads a 32-byte-or-longer HMAC key only from a permission-checked file or FD. It and `raw` are restricted to `local` / `controlled`; their 0600 sidecar carries research source/governance, and `public-pr` is a hard error. No automatic controlled upload exists before an authorized destination does
- `--open` explicitly uses the submitter's GitHub credentials to push a fork branch; the final button is yours. A proxy PR may hide submitter identity, but its payload still becomes public and cannot be fully withdrawn from existing Git history, clones, or forks
- Intake CI accepts legacy v1 plus public-safe v2 `aggregate` / `named-public` under mode-specific allowlists, rejecting masked/raw, raw email, internal actor IDs, and credential shapes
- Use is limited to "TEP Report aggregation and the next reference
  distribution"; retained until the next annual Report; withdrawal via issue

## Shared block policy (spec)

The Shared block (the 3-5 line copy-pasteable summary at the top of every
report) carries **no glosses**. Rationale: it is pasted into résumés and
issues, where compactness beats self-explanation — the per-line glosses in
the body and [docs/en/metrics-guide.md](en/metrics-guide.md) carry the
meanings.

## How to read the metrics (for non-engineers)

[docs/metrics-guide.md](docs/metrics-guide.md) explains every metric in plain
language: what it measures, what high/low values suggest, and rough ranges
from a 117-repository public corpus. Common misreadings (e.g. corrective
rework is not a bug count; dormant does not mean abandoned) are listed in a
table. Read this first if you are new to the reports.

## Metrics and limits

| Metric | What it is evidence of | Limit |
|---|---|---|
| origin / attribution | whose work | unset identity → unresolved. Real tenant emails are not shipped |
| test co-change | whether production changes came with tests | no test substrate → `not_observed`. population &lt; 20 → no rate and no decile (`insufficient_population`) |
| corrective rework | recent-path return with a fix/revert subject (observational) | **demoted from evidence claim**. confounded by subject conventions. not a bug count. line-level retry is v0.6 |
| path retouch | same-file re-touch | observational only. not an evidence claim |
| survival (τ=180d) | whether lines remain | `--survival` only. reference distribution planned for **v2027**. not in this public distribution |

Reference position is a single “decile N” line. Metrics with n&lt;30 omit position (`reference_too_small`). Current v2026.11 measured n: test co-change 68 / corrective rework 101 (observational) / survival 0 (planned for v2027). The older v2026.09 stays immutable and selectable via `--reference-version`.

## Discriminatory power (repo scope, criteria `5f2665e`)

Source: `corpus/DISCRIMINANT-v2026.11.md` (n=117: all v2026.09 rows + 70 v2026.11 admissions). Verdicts copied **verbatim** from the file.

- `test_cochange A vs D` → `separated` (median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18) — **first separation with a standing n**; the first strong evidence for the "anyone can produce volume" thesis
- `test_cochange A vs C` → `fail_tier2` (median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21) — was `separated` in v2026.09 (δ 0.7143), but the grown C pool (AI-driven repos WITH tests) reduced the separation. **The registered criteria were not lowered; the reversal is published as-is**
- `corrective_rework A vs C / A vs D` → no required direction (observational only, unchanged since v0.5.0). A vs C δ -0.8333 / A vs D δ 0.0139
- Honest population note: C narratable = 14 (short of the 30 target, corrected by machine-verified admission) / D total 29 (target 20 met)
- survival: reference distribution planned for v2027

The v2026.09 record (Run 2: A vs C `separated` etc.) remains as history in `corpus/DISCRIMINANT-v2026.09.md`.

## GitHub Action (observation only)

```yaml
permissions:
  contents: read
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
      persist-credentials: false
  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
  - uses: Cor-Incorporated/grift-cli@v0.7.1
    with:
      scope: repo
      comment: false
```

This reference becomes valid only after the annotated v0.6.0 tag is published.
A source implementation, PR, merge, tag, and PyPI publication are separate
states and human gates.

- Requires a complete checkout of the caller repository and Python 3.11 or newer. A fail-closed preflight rejects a missing checkout or shallow clone (exit 2) before measurement
- Runs `grift analyze`, prints the **shared block to $GITHUB_STEP_SUMMARY**, and uploads report.md / report.json as artifacts
- Never turns observed values into pass/fail or thresholds; input and history contract violations fail closed
- CI dogfood runs with `contents: read` and `comment: false`, so PR-controlled code receives no write token
- The `comment: true` path is implemented but not proven by read-only dogfood. Do not grant PR-controlled code write permission until a trusted post-workflow is designed

## Support

- Removal requests (e.g. for golden identity emails derived from public commit
  metadata): please open an issue on the public repository; see the
  tep-contributions README for the private contact channel.

## Ethics

- Named-person scorecards and league tables are forbidden, publicly and internally
- Do not emit skill-rank labels (senior / junior / “excellent”)
- Corpus manifests (repo name + SHA) may be published for reproduction. **Per-repo value league tables are not published**
- Control group E (private ground truth) is not in this repository

## Status

- Public repository: https://github.com/Cor-Incorporated/grift-cli
- Command name: **`grift`** (methodology name TEP remains on reports)
- PyPI: distribution name **`grift-cli`**. Publishing is a separate human gate (until then, `pipx install .`)

## License

MIT. See [LICENSE](LICENSE).
