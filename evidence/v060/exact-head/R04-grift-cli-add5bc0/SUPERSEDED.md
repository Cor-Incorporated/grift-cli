# Historical exact-head evidence

Status: `HISTORICAL_NON_FINAL`

The authoritative machine-readable status is recorded in both
`exact-head-result.json` and `historical-evidence-manifest.json`. Consumers must
reject this bundle as final evidence when the status is historical or absent;
the closed contract is `../historical-exact-head-evidence.schema.json`.

This directory records a successful self-analysis of an earlier source snapshot.
It is not the final v0.6.0 PR head, package source, remote CI artifact, release, or
live evidence. The directory cannot prove the commit that later adds or changes
the evidence itself.

The final exact-head result must be generated outside the Git tree by CI after
checking out the exact pull-request head. Its artifact must bind the PR head SHA,
source inventory digest, report/Markdown/manifest digests, golden result, action
dogfood result, and package-smoke result. `docs/REQUIREMENTS-v060.md` and
`docs/V060-CLOSURE-LEDGER-20260831.md` define the current acceptance state.
