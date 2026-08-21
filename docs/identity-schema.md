# Identity file schema (identity-v1)

Local entry point for the same concept as Grift `actor_attributions`.

| Field | Grift column | Meaning |
|---|---|---|
| `canonical_id` | stable member id (email is the DB key there) | Durable id for a person. CLI uses a non-email id so reports are not scorecards. |
| `emails` | `canonical_email` plus aliases | Raw git author emails that map to this actor. |
| `github_login` | `github_login` | Optional. |
| `attribution_state` | `attribution_state` | `verified` / `claimed` / `inferred` / `unresolved` / `external` / `bot`. |

`tenant.email_patterns` are regular expressions matched against author emails. A match counts as tenant membership even without an `[[actors]]` row (`attribution_state` then becomes `inferred`).

Empty file / missing file: `pending_attribution = true`. No built-in organisation pattern exists.
