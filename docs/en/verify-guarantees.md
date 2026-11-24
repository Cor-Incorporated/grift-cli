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
| 7. Hand-write forge records (reviews, issues) | Partly | A local export can be written by its author. Records fetched with `--fetch-public` from a public API can be fetched again by anyone, but this CLI alone cannot show that an API response was not altered | Fetch with `--fetch-public` and re-check the same records with `--public-evidence` |
| 8. Make unsigned commits look signed | Yes (presence only) | The signature header (`gpgsig`) is part of the commit object and can be recomputed. Whether a signature is valid depends on the reader's keys, so verify does not look at it | The reader runs `git verify-commit` with their own allowed signers |
| 9. Sign a report while pretending to be a real signer | No (attest's scope) | `grift attest` signs the report hash. Who the signer is depends on the key the recipient trusts | Pin `--allowed-signers` and `--principal` on the receiving side |
| 10. Make a later report look earlier | No | The observation date is a value you can choose with `--as-of`; it is not a proof of time | A third-party timestamp (not in this version; see "Not yet available") |

## Signature observation (0.9.6)

report-v2 carries `signature_observation`: the share of selected commits whose object has a signature header, with its count and population. Below 20 commits it is `not_observed` (`insufficient_population`).

- Only **header presence** is counted. Whether a signature is valid, or whose key it is, is not looked at: `%G?` depends on the reader's keyring and `grift verify` cannot replay it.
- Unsigned commits are common in legitimate history. The figure is not a score or a rank, and not a basis for cutting candidates (see the [usage norms](norms.md)).
- To check validity, run `git verify-commit` with signers you allow.

## "Raising the cost" is deliberate wording

The items in the last column do not make forgery impossible. They raise what forgery takes (creating real records on a public forge, holding a signing key, keeping several inputs consistent) and give the recipient more places to cross-check. This page never says a report "cannot be tampered with".

## Not yet available

- A third-party proof of time (for example a transparency-log entry). Recording the report hash somewhere external is something the user can do.
- Confirmation of a signer's identity. attest checks that a signature matches the report; who holds the key is the recipient's decision.

## Related

- [Usage](usage.md) (`verify` and `attest`)
- [Usage norms](norms.md)
- [Metric validation and limits](validation.md)
- [Migrating to 0.9.6](migration-v096.md)
