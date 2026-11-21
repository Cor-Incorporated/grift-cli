# Migrating to v0.9.3

Japanese original: [migration-v093.md](../migration-v093.md). For the earlier public migration
and compatibility notes, see [migration-v092.md](migration-v092.md).

The existing `analyze` / `report` / `verify` / `contribute` commands still produce report-v1. Every
command from v0.6.0 to v0.9.2 is still there.

## What changes in 0.9.3

**One new command pair and one new executable name. 0.9.3 makes the first actor report easier:
`grift identity --init` generates an identity-v2 file from emails you pass on the command line, and
a second console script named `grift-cli` makes `uvx grift-cli` work without `--from`.** Analysis
values and measurement definitions do not change, except for the version stamp: `DEFINITION_VERSION`
moves from `tep-v0.9.2-2026-10-30` to `tep-v0.9.3-2026-11-21` following the release numbering
convention (a new tool version takes a new definition stamp even when no definition changes).

### `grift identity --init` / `--list` (public issue #26)

- Emails are passed on the command line; the written file records `email_sha256` digests only and
  never the raw addresses. The normalisation and the domain-separated digest are the loader's own,
  so the generated file loads through `--identity` as is
- `canonical_id` defaults to the local part of the first `--email`; when that does not fit the
  pattern, or has the reserved hash-id shape, pass `--id`. `attribution_state` is written as
  `claimed`; `consent` / `authority` are not written, so experience / role observations stay
  `not_observed(consenting_actor_required)` exactly as before
- Existing identity files (v1 / v2, hand-written) load exactly as before. An existing file is never
  overwritten (exit 2)

### Console script `grift-cli` (public issue #28, part)

On 0.9.2, `uvx grift-cli --version` failed with "An executable named `grift-cli` is not provided by
package `grift-cli`" (measured 2026-11-20). The package now declares a second script with the
package name, so `uvx grift-cli repo` works without `--from`. The `grift` command stays.

### Installer guidance leads with uv

The README and the docs now lead with `uv tool install grift-cli` (pipx and venv + `pip` remain
documented alternatives; plain `pip` needs a local Python 3.11+, and macOS's default 3.9.6 fails
resolution — measured 2026-11-20). The README also warns that `pip install grift` installs a
different library. Python 3.13 / 3.14 classifiers were added after running the built wheel on both.

### Verify: reports saved with 0.9.2 become CANNOT_VERIFY

Because `DEFINITION_VERSION` moved, a report saved with 0.9.2 verifies as CANNOT_VERIFY (rc=2)
under 0.9.3. Measured 2026-11-21 on a synthetic repository (3 commits by alice, 1 by bob):

```bash
$ grift verify mig093/report.json --repo id-fixture
CANNOT_VERIFY:
  - definition version 'tep-v0.9.2-2026-10-30' is not the current 'tep-v0.9.3-2026-11-21'
# rc=2
```

Recompute under one version, or regenerate the report, to compare again.

## Existing features and compatibility

The public features from v0.6.0 through v0.9.2 remain available. The v0.9.2 migration guide records the earlier command, flag, enum, JSON-shape, and analysis-value compatibility details. v0.9.3 does not change the existing measurement methods; it advances the definition stamp, so reports created with 0.9.2 return `CANNOT_VERIFY` under 0.9.3.

The existing report-v2 `library_context` and `outcome` fields, `align --team`, and contribution `--purpose` continue to work. Shallow clones such as an Actions checkout with `fetch-depth: 1` mark history-dependent values as `not_observed(history_incomplete)`. See the [usage guide](usage.md), [report-v2 guide](../report-v2.md), and [alignment schema](../alignment-schema.md).

## Fixed revisions and public Forge evidence

`repo` and `actor` resolve `--rev REV` to a fixed SHA-1 or SHA-256 OID and are offline by default. `--fetch-public`, `--public-evidence DIR`, and `--resume-public-evidence DIR` are mutually exclusive. Acquisition can explicitly set `--forge-provider auto|github|gitlab`, `--forge-api-base URL`, `--auth-token-env NAME`, `--public-evidence-out DIR`, and `--max-public-pages N`. Self-managed GitLab needs an explicit provider and API base. GitHub and GitLab use a provider-neutral contract; when the GitLab commits API has no documented account linkage, the result remains `unsupported/not_proven`.

A safe stop during public acquisition returns exit 3 (`PARTIAL`). `verify` on a saved bundle does not reconnect to the network; it checks the schema, manifest and body digests, parsed content, Git OID set, SHA/account mapping, and report/collection binding. Exit codes are `0=VERIFIED`, `1=MISMATCH`, `2=CANNOT_VERIFY`, and `3=PARTIAL` for a safe stop during public acquisition.

## contribution-v2

| Profile | Allowed doors | Boundary |
|---|---|---|
| `aggregate` | `local` / `public-pr` | No actor rows, remote/OID, exact timestamps, or source digests; public by default |
| `named-public` | `local` / `public-pr` | Only provider-neutral accounts/projects with explicit authority |
| `masked` | `local` / `controlled` | High-precision observations with HMAC pseudonyms; controlled sidecar required |
| `raw` | `local` / `controlled` | Raw source for research; controlled sidecar required |

`masked` and `raw` cannot use `public-pr`. There is no automatic upload because no authorized controlled destination is configured.

## attest / portfolio

`grift attest REPORT --repo REPO --out DIR --sign ssh|cosign` recomputes the report before signing a canonical statement. The statement includes the report hash and input digests. `grift verify` separates signature verification, report-hash verification, and repository recomputation. SSH uses the recipient's `--allowed-signers` / `--principal`; cosign uses a public key or a recipient-selected certificate identity/issuer.

`grift portfolio --manifest portfolio.toml --format both --out DIR` creates an evidence ledger from explicit self-declaration or attestations. It does not infer identities across repositories from email/handle and does not compute averages, weights, score, or rank.
