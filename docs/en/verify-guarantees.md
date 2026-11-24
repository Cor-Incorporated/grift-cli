# What `grift verify` guarantees, and what it does not

[日本語](../verify-guarantees.md)

`grift verify` checks that a saved report matches what you get by running the same steps again on the repository and inputs you hand it. This page describes the extent of that guarantee as an attack tree, so a reader of a report can decide how far to trust its numbers.

## In short

- verify guarantees **consistency between the report and the repository**: the JSON equals the result recomputed from the git history you pass in.
- verify does **not** guarantee that the repository's history is genuine. Commit author names, emails and dates are values the writer chose; git alone cannot show they are true.
- What supports authenticity sits next to verify: public forge records, the presence of signature headers, and signatures from `grift attest`. None of them makes forgery impossible. They raise its cost.

## Attack tree

The attacker's goal is a report that looks better than the facts and still passes a check.

| Move | Stopped by verify? | Why / why not | What raises the cost |
|---|---|---|---|
| 1. Edit numbers in the report JSON | Yes | The recomputed result differs, so you get `MISMATCH`. The same holds for `signature_observation` and `usage_terms` | Nothing more needed |
| 2. Hand over a report made from another repository or period as if it were the original | Yes | The analyzed SHA, observation date and input hashes are in provenance; recomputing on the repo you pass in does not match | Nothing more needed |
| 3. Rebuild with different `--as-of`, `--role-lens` or `--disclosure-level` | Yes | The options are recorded in provenance and verify recomputes with them; an edited report does not match | Nothing more needed |
| 4. Compare reports across definition versions | Cannot verify | `CANNOT_VERIFY` (exit 2). This is a different procedure, not forgery | Verify with the CLI of that version |
| 5. Build a repository with a fabricated history and report on it | No | The recomputation matches that fabricated history. verify only sees report-versus-repository consistency | Public forge records (next row), signature headers, attest |
| 6. Rewrite author name, email or dates in a history | No | Authorship is self-declared. An identity file is a claim that a person uses an email, not proof of identity | Cross-checking forge records, signature headers |
| 7. Hand-write forge records (reviews, issues) | Partly | A local export can be written by its author. Records fetched with `--fetch-public` from a public API can be fetched again by anyone, but attempting to delete non-existent files will result in an error. Ensure paths are exact with no leading/trailing whitespace.