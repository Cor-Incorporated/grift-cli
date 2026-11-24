# Migrating to 0.9.6

0.9.6 closes #7, #8, #23, #24, #25 and #27. To reproduce results from an older version, record the CLI version and the repository revision you used. [日本語](../migration-v096.md)

## The definition version changed

The only TEP field name that changed on disk is `signature_text` → `corpus_text`. Read `corpus_text` for new files; keep accepting `signature_text` when migrating legacy input.

## Other breaking changes in 0.9.6

| Area | Before 0.9.6 | 0.9.6 | Why it matters |
|------|----------------|--------|----------------|
| Same field on disk | `signature_text` | `corpus_text` | Use `corpus_text` in new files and pipelines. |
| Hook metrics in `report-v2` | Optional / sparse | Required where applicable | Downstream parsers must handle absence vs zero consistently. |
| Contract JSON schema | Earlier draft | `v060-contracts.schema.json` | CI and golden tests pin this schema. |
| Ref Commit Depth cap | Higher default | Capped (shallow repos flagged) | Shallow clones may under-report history depth. |

## Recommended upgrade path

1. Run Grift CLI 0.9.6 on a representative repo and archive `report-v2`.
2. Regenerate golden expected JSON if you maintain them (`scripts/gen_golden_expected.py`).
3. Update any consumer that assumed `signature_text` only.
4. Re-run your CI golden suite (`tests/test_golden.py`).

## Notes for integrators

- **Corpus protocol**: see [corpus-protocol.md](corpus-protocol.md) for wire format.
- **TEP / metrics glossary**: unchanged metric *names* in output except the corpus field rename above.
- **Questions**: open an issue on the main repo or contact via your PoC channel.
