# Identity file schema (identity-v1 / identity-v2)

Japanese original: [identity-schema.md](../identity-schema.md).

| Field | Meaning |
|---|---|
| `canonical_id` | Durable pseudonymous id (never an email; no personal scorecards) |
| `emails` | Raw git author emails mapped to this actor (local file only) |
| `github_login` | Optional |
| `attribution_state` | `verified` / `claimed` / `inferred` / `unresolved` / `external` / `bot` |
| `consent` | Optional closed marker: `recorded-explicit-consent`. Required, together with `attribution_state=verified|claimed`, to observe experience/role. The CLI validates the record, not real-world consent or personhood. |
| `authority` | Optional declared basis: `repository-owner-authorization` / `subject-authorization`. Authority alone never unlocks experience/role. |

`consent` is separate from `attribution_state`. A legacy row containing only
`verified` or `claimed` remains readable, but experience/role fails closed as
`not_observed(consenting_actor_required)`. A consent marker on
`inferred|external|unresolved|bot` is contradictory and rejected. Both optional
fields enter `identity_digest` when present.

```toml
schema_version = "identity-v2"

[[actors]]
canonical_id = "candidate_001"
email_sha256 = ["<64 lowercase hex>"]
attribution_state = "claimed"
consent = "recorded-explicit-consent"
authority = "subject-authorization"
```

## canonical_id validity (F-P10-3, version-managed)

`canonical_id` must **fullmatch**:

```
^[a-z0-9][a-z0-9._-]{0,63}$
```

Lowercase alphanumeric start; then lowercase alphanumerics and `.` `_` `-`;
length 1–64. **`@`, whitespace, control characters, uppercase, and multi-byte
characters are invalid** (this pattern — not a blocklist — is what makes the
export's no-`@` contract data-independent). Duplicates are rejected, and so is
the hash-id shape (see "The hash-id shape is reserved" below; from 0.9.1). The
regex must match the implementation (`tep_core.identity.CANONICAL_ID_PATTERN`)
verbatim; `tests/test_identity_validation.py` enforces the doc↔code parity.

| Version | Pattern | Introduced |
|---|---|---|
| 1 | `^[a-z0-9][a-z0-9._-]{0,63}$` | 2026-08-22 (F-P10-3) |

### The hash-id shape is reserved (from 0.9.1)

A `canonical_id` that fullmatches the following is also rejected (exit 2), even
though it matches the pattern above:

```
^actor_[a-f0-9]{12,32}$
```

`actor_` followed by 12–32 hex digits is the hash id grift gives to a cluster
that has no declared identity. When an identity could declare that shape, it
could equal another cluster's hash id, and that cluster's commits were counted
as the declared person's (the consented role_profile among them) — for
example when an id from `--all` output was copied with an email that does not
belong to that cluster. Write a readable id such as `alice`. This reservation is
a separate rule from `CANONICAL_ID_PATTERN` above; that pattern itself is
unchanged, so `CANONICAL_ID_PATTERN_VERSION` stays 1. The regex matches
the implementation (`tep_core.identity.RESERVED_ACTOR_HASH_PATTERN`) verbatim;
`tests/test_v091_identity_ids.py` ties the Japanese and English docs, the
implementation and the hash-id generator (`stable_actor_hash`) together.

An author whose name has this shape is counted under their own hash id, not
their name. A name equal to another cluster's hash id no longer stops the
analysis (0.9.0 and earlier stopped with exit 2).

`tenant.email_patterns` are regexes; a match counts as tenant membership
(state `inferred`). Empty/missing file: `pending_attribution = true`.
