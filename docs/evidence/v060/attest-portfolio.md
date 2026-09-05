# v0.6 attest / portfolio CLI evidence

- observed_at: `2026-08-31T03:43:13+0900`
- command: focused portfolio/attest CLI, core, and Draft 2020-12 mutation cases
- result: `24 passed / 0 failed / 1 skipped` (25 collected)
- SSH implementation: `/usr/bin/ssh-keygen`; `OpenSSH_10.3p1, LibreSSL 3.3.6`

Reproduction: run both `tests/test_v060_portfolio_core.py` and
`tests/test_v060_attest_portfolio_cli.py`, plus the five portfolio-specific
nodes in `tests/test_v060_schema_contracts.py` (canonical portfolio/manifest,
attested evidence mutation, mixed manifest binding, and runtime arithmetic
invariants).

## Attestation falsification

All cases used a newly generated, permission-restricted Ed25519 test key and the
actual `grift attest` / `grift verify` CLI parsers.

| Case | CLI exit | Signature | Report hash | Repository recomputation |
|---|---:|---|---|---|
| Untampered bundle | 0 | VERIFIED | VERIFIED | VERIFIED |
| One byte appended to report JSON | 1 | VERIFIED | MISMATCH | VERIFIED |
| One signature byte changed | 1 | INVALID | CANNOT_VERIFY | CANNOT_VERIFY |
| Recipient principal changed | 1 | MISMATCH | VERIFIED | VERIFIED |
| A different repository supplied | 2 | VERIFIED | VERIFIED | CANNOT_VERIFY |

An additional CLI case placed `identity.toml` outside the repository and passed
it explicitly to both `attest` and `verify`. The recomputation result was
`VERIFIED`; the explicit identity option is therefore part of the verified
bundle CLI path, not only the signing preflight.

The generated statement omitted `repo_hint` by default and did not contain the
local repository path. The verification response also retained the warning
that signature validity is not evidence of metric correctness or superiority.

## Portfolio binding falsification

The compatibility path retained two independently analyzed tenant-scope
report-v1 files under `subject_binding = "self_declared"`. Its JSON/Markdown
now explicitly records `not_verified_self_declared`; the signature metadata is
evidence inventory, not a recipient trust decision.

The attested path used two independent fixed-repository actor report-v2 files,
each with `subject.kind = "actor"` and the same explicit canonical subject ID.
Both reports were signed with real OpenSSH Ed25519 detached signatures. The
portfolio succeeded only with a recipient-owned `allowed_signers` file and the
exact principal. JSON and Markdown record `recipient_trust_verified` and the
subject ID read from each signed report.

- declared eligible repositories: 3
- included repositories: 2
- disclosure: 2 / 3 (`0.666666666667 ratio`)
- implicit repository hints, source remotes, and local paths in output: 0
- forbidden aggregate keys (`score`, `rank`, `average`, `weight`, `percentile`): 0
- duplicate report path: rejected with exit 2 before output creation
- mismatched declared subject: rejected with exit 2 before output creation
- attested binding without trust policy: rejected with exit 2, output files 0
- wrong recipient principal/key: rejected with exit 2, output files 0
- self-declared/attested method mixture: rejected before evidence use
- signed report subject mismatch: rejected
- output trust-file/private-key absolute paths: 0
- implicit repository hints: 0; manifest opt-in hint remains supported
- Draft 2020-12 portfolio/manifest schemas: 2/2 valid; status/subject mutations rejected

## Cosign status

The host had no persistent `cosign` installation in the final focused run, so
the keyful cosign portfolio extension remained skipped there. An earlier test downloaded the
official Sigstore `v3.1.3` macOS arm64 release into a temporary directory and
verified `cosign-darwin-arm64` against the release checksum:
`5cf948c2f4dfe59687bdd0b8523709067383e03982cc543475c8a7dc70e92a76`.
The real keyful `generate-key-pair` / `sign-blob --bundle` / verification CLI
path then passed. No system installation was performed. Keyless OIDC remains a
separate human gate and is **NOT_PROVEN**.

The temporary pytest workspace containing test-only private keys was moved to
Trash after the run. No user key, tracked key, or signing credential was read.
