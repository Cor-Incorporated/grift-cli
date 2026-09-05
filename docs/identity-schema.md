# Identity file schema (identity-v1 / identity-v2)

Local entry point for the same concept as Grift `actor_attributions`.

| Field | Grift column | Meaning |
|---|---|---|
| `canonical_id` | stable member id (email is the DB key there) | Durable id for a person. CLI uses a non-email id so reports are not scorecards. |
| `emails` | `canonical_email` plus aliases | Raw git author emails that map to this actor. |
| `github_login` | `github_login` | Optional. |
| `attribution_state` | `attribution_state` | `verified` / `claimed` / `inferred` / `unresolved` / `external` / `bot`. |
| `consent` | — | Optional closed marker: `recorded-explicit-consent`. Required, together with `attribution_state=verified|claimed`, to observe experience/role. The CLI validates the record, not real-world consent or personhood. |
| `authority` | — | Optional declared basis: `repository-owner-authorization` / `subject-authorization`. Authority alone never unlocks experience/role. |

`consent` is deliberately separate from `attribution_state`. A legacy row with
only `verified` or `claimed` remains readable, but experience/role fails closed
as `not_observed(consenting_actor_required)`. A consent marker on
`inferred|external|unresolved|bot` is contradictory and rejected. Both optional
fields are included in `identity_digest` when present.

```toml
schema_version = "identity-v2"

[[actors]]
canonical_id = "candidate_001"
email_sha256 = ["<64 lowercase hex>"]
attribution_state = "claimed"
consent = "recorded-explicit-consent"
authority = "subject-authorization"
```

## canonical_id validity (F-P10-3・版管理)

`canonical_id` は次の正規表現に **fullmatch** しなければならない（producer が `IdentityValidationError` で拒否する）:

```
^[a-z0-9][a-z0-9._-]{0,63}$
```

意味: 小文字英数字で開始・以降は小文字英数字と `.` `_` `-` のみ・長さ 1〜64。**`@`・空白・制御文字・大文字・多バイト文字は不正**（export の no-`@` 契約をデータ非依存に保証するための定義パターン。blocklist ではない）。

追加の拒否条件: 空文字（上記正規表現の fullmatch で自動的に拒否）・**重複 canonical_id**（各行一意であること）。

本正規表現は実装（`tep_core.identity.CANONICAL_ID_PATTERN`）と**逐語一致**しなければならない — `tests/test_identity_validation.py` が schema 文書と実装の一致を検査する（レシピテストと同型の doc-code パリティ）。正規表現を変える場合は schema 文書・実装・テストを同じ PR で更新し、`CANONICAL_ID_PATTERN_VERSION` を上げる。

| 版 | 正規表現 | 導入 |
|---|---|---|
| 1 | `^[a-z0-9][a-z0-9._-]{0,63}$` | 2026-08-22（F-P10-3 修正） |

`tenant.email_patterns` are regular expressions matched against author emails. A match counts as tenant membership even without an `[[actors]]` row (`attribution_state` then becomes `inferred`).

Empty file / missing file: `pending_attribution = true`. No built-in organisation pattern exists.
