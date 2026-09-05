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
export's no-`@` contract data-independent). Duplicates are rejected. The
regex must match the implementation (`tep_core.identity.CANONICAL_ID_PATTERN`)
verbatim; `tests/test_identity_validation.py` enforces the doc↔code parity.

| Version | Pattern | Introduced |
|---|---|---|
| 1 | `^[a-z0-9][a-z0-9._-]{0,63}$` | 2026-08-22 (F-P10-3) |

`tenant.email_patterns` are regexes; a match counts as tenant membership
(state `inferred`). Empty/missing file: `pending_attribution = true`.
