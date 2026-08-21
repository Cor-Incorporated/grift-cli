# Golden corpus (write expected output before implementing metrics)

Five public repositories, SHA-pinned. Expected JSON lives in `expected/` and is
the acceptance contract for `grift analyze`.

Canonical ids in identity fixtures are pseudonymous (`maintainer-1`). Reports
must not emit a named-person scorecard.

Run (requires network):

```bash
TEP_GOLDEN=1 python -m pytest tests/test_golden.py -m golden
```
