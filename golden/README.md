# Golden corpus (write expected output before implementing metrics)

Fourteen pins (public repositories, SHA-pinned; `G1R-click-repo` reuses G1's clone at repo scope). Expected JSON lives in `expected/` and is
the acceptance contract for `grift analyze`.

Canonical ids in identity fixtures are pseudonymous (`maintainer-1`). Reports
must not emit a named-person scorecard.

The public G1 identity uses `identity-v2.email_sha256` with the
`tep-email-v1\0` domain separator. The plaintext address is not distributed;
identity-v1 remains readable for local compatibility.

`pins.toml` takes two optional keys: `template` (a template repository URL; it only
marks `--template` as provided so `origin.template_inherited` is observed) and
`scope` (`repo` for the repo-scope report that carries `interpretation`).

Run (requires network):

```bash
TEP_GOLDEN=1 python -m pytest tests/test_golden.py -m golden
```
