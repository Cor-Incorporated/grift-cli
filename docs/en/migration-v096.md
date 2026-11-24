# Migrating to 0.9.6

0.9.6 closes #7, #8, #23, #24, #25 and #27. To reproduce results from an older version, record the CLI version and the repository revision you used. [日本語](../migration-v096.md)

## The definition version changed

`DEFINITION_VERSION` moves from `tep-v0.9.5-2026-11-23` to `tep-v0.9.6-2026-11-24`. A report-v2 saved by 0.9.5 or earlier gives `CANNOT_VERIFY` (exit 2) under 0.9.6 `grift verify`. Regenerate it with 0.9.6, or verify it with the CLI version that produced it.

## New report-v2 fields

- `signature_observation`: the share of selected commits whose object has a signature header. `not_observed` below 20 commits. Signature validity is not checked, and it is not a score. Scope: [verify-guarantees.md](verify-guarantees.md)
- `usage_terms`: permitted uses, prohibited uses (articles of the [usage norms](norms.md)), the disclosure level, and `binding: declaration_only`
- `provenance.disclosure_level`: records `--disclosure-level minimal|standard|full`; verify rebuilds with the same level
- report-v1 `interpretation.survival`, only with `--survival`. The published references carry no survival block, so it is `reference_too_small` today

Without `--disclosure-level` the level is `full` and the Markdown shows the same observations as 0.9.5. The new fields use no verdict words such as score or rank.

## Personal view

The Markdown of `grift actor` with recorded consent gains a "how to use this record (for you)" section, and, when the forge or tracker export you pass holds that person's events, a sentence on review and issue records. It states counts and periods only, never quality.

## Pinned revision and public forge evidence

`--fetch-public` records GitHub and GitLab public history in a provider-neutral form. On PARTIAL (exit 3), resume with `--resume-public-evidence` and verify saved evidence with `--public-evidence`. When CI uses `fetch-depth: 1`, only the fetched history is measured; if the output shows `history_incomplete`, fetch the full history and compare again.

## contribution-v2

report-v1 accepts only the default `--purpose reference-distributions`; use report-v2 for other purposes. A report-v1 run with `outcome-linkage` exits 2 before writing a contribution or opening a pull request. contribution-v2 offers the information levels aggregate / named-public / masked / raw and the destinations local / controlled / public-pr. Review the output before sharing.

## attest / portfolio

`grift attest` signs with `ssh|cosign`. On receipt, check the signature, the report hash and the repository recomputation separately. `grift portfolio` prints eligible and included counts and never builds a score or rank from an individual's email/handle. See the [usage guide](usage.md) for `library_context`, `outcome` and `align --team`.

## Bootstrapping a reference distribution from public repositories

`scripts/corpus_bootstrap.py` builds a reference distribution from public repositories without `contribute` (`plan`, `observe`, `build`). The shipped `v2026.09` and `v2026.11` do not change. See [corpus-protocol.md](corpus-protocol.md).
