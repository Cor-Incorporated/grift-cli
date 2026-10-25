# Contributing to grift-cli

[日本語](CONTRIBUTING.md) | **English**

grift takes facts that cannot be inflated out of an engineer's git history and places them next to a project's requirements, without a score and without a ranking.
This document is the shortest route to changing it without breaking that design. Five minutes to get it running locally, ten to read the whole thing.

- Just want to use it: [README](README.en.md) (one command on your own repo)
- How to read the numbers: [docs/en/metrics-guide.md](docs/en/metrics-guide.md)
- The usage norms every contribution must respect: [docs/en/norms.md](docs/en/norms.md) (seven articles, JA/EN)
- Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) / vulnerability reports: [SECURITY.md](SECURITY.md)

---

## 1. Two repositories

| | Development repository | Public repository |
|---|---|---|
| Where | `Cor-Incorporated/grift-cli-dev` (private) | [`Cor-Incorporated/grift-cli`](https://github.com/Cor-Incorporated/grift-cli) (public, MIT) |
| History | Day-to-day PRs land on `main` | One snapshot per release: `git archive` from the dev `main`, pushed as a `release/vX.Y.Z` branch → PR → `main` → annotated tag |
| Branches | Many working branches | `main` only (measured 2026-10-25) |
| PyPI | Never | Only when a human hands the tag to the `publish` workflow; `publish.yml` publishes only when `github.repository == 'Cor-Incorporated/grift-cli'` |
| Evidence (§5) | Bound to dev commits | Re-bound to public commits |

The public repository does not contain the dev commits, so anything pushed straight onto its `main` is overwritten by the next snapshot.
The procedure of record is [docs/RELEASE-REPORT-v0.7.2-20260908.md](docs/RELEASE-REPORT-v0.7.2-20260908.md) §5 and
[docs/RELEASE-REHEARSAL-v051-20260822.md](docs/RELEASE-REHEARSAL-v051-20260822.md) §5 (Japanese).

### Where to send a change from outside

- **Issues go to the public repository.** The templates (bug / feature / question) ask for "observed vs expected" and "the shape of a reproducing repo".
- **Where PRs are accepted is (unverified).** As of 2026-10-25 the public repository has never received an external PR (PRs #5–#16 are all maintainer release PRs). One of two options will be chosen:
  - **Option A (recommended): open the PR on the public repository.** A maintainer transplants it to the dev repository, keeps the contributor on the commit with `Co-authored-by:`, and closes the public PR with the dev PR number. Contributors only ever look at one repository.
  - **Option B: get invited to the dev repository and open PRs there directly.** For people who keep contributing. Heavy for a one-line fix.
  - §6 (PR etiquette) and §7 (what is forbidden) are the same either way.
- Discussions are disabled as of 2026-10-25. Enabling them is a maintainer decision; until then use the question issue template.

---

## 2. Run it locally (five minutes)

You need Python 3.11 or newer and git. There are zero runtime dependencies (`dependencies = []` in `pyproject.toml`).

```bash
git clone https://github.com/Cor-Incorporated/grift-cli.git
cd grift-cli
uv venv && source .venv/bin/activate        # without uv: python -m venv .venv
uv pip install -e ".[dev]"                  # without uv: python -m pip install -e ".[dev]"
python -m pytest tests -m "not golden" -q   # same scope as the CI `test` job
```

- `-m "not golden"` excludes the live golden corpus, which clones pinned public repositories over the network. Run it with `python -m pytest -m golden`.
- Lint is ruff. The repository's only settings are `[tool.ruff]` in `pyproject.toml` (`line-length = 100`, `target-version = "py311"`); the rule set is `E4` / `E7` / `E9` / `F` (ruff's default up to 0.15). CI has no ruff job, so get to zero findings locally before you push. ruff 0.17 and later widened the default rule set and report 463 findings on the same tree (measured 2026-10-25; 0.15.14 reports zero), so pin the rules explicitly to stay independent of the version.

```bash
uvx ruff check --isolated --select E4,E7,E9,F --line-length 100 --target-version py311 src tests scripts
```

- To try the CLI after a change, use the `grift` from the same venv (installed by `pip install -e`).

```bash
grift repo .            # Markdown to stdout; add --out DIR only when you want it saved
grift --version
```

---

## 3. Test layers and CI

| Layer | How to run | What it protects |
|---|---|---|
| Unit / contract | `python -m pytest tests -m "not golden" -q` | Schemas, forbidden keys, docs ↔ code agreement (§7). Synthetic git repositories are built with `tests/git_fixture.py` |
| Golden (network) | `python -m pytest -m golden` | Clones pinned public repositories (pallets/click and others) and compares against expected values |
| Evidence gates | §5 | That the bundled evidence was produced by this source tree |

CI jobs (`.github/workflows/ci.yml`) and where to look when one fails:

| job | Role | When it fails |
|---|---|---|
| `test (3.11 / 3.12)` | Unit / contract above; fails if the intake contract test is skipped instead of run | Paste the failing test names into the PR |
| `p0-falsify` | Compatibility falsification suite (43 hypotheses) against the public v0.5.9 baseline | Did you change legacy (report-v1 / export-v1) output? |
| `intake-contract-parity` | Real send to the `tep-contributions` intake schema, comparing `PURPOSES` | Both sides: `contribution_v2.py` and the intake schema |
| `exact-pr-head` | Analyze → verify the exact PR head | Determinism |
| `v060-golden` | Replays the v0.6 golden fixture and verifies the public digest-only registry | §5 #2 and #4 |
| `action-dogfood` | Runs the bundled GitHub Action (`action.yml`) against this repo | `action.yml` and `scripts/action_contract_guard.py` |
| `package-smoke` | Builds sdist / wheel from a dirty tree and smoke-tests a clean install | `only-include` in `pyproject.toml` vs tracked files |
| `gitleaks` | Secret scan (`.gitleaks.toml`) | A public OID false positive: check whether the path is allowlisted |
| `golden` | Live golden corpus; skipped on PRs, runs on schedule | Network-dependent expected values |

---

## 4. Shortest route by kind of change

| Change | Minimum you must do |
|---|---|
| Docs only | Fix the counterpart in the other language in the same PR (`README.md` ↔ `README.en.md`, `docs/*` ↔ `docs/en/*`). `tests/test_v060_docs_parity.py` and `tests/test_v070_norms_link.py` check JA/EN and code agreement |
| Metric names or definitions | The glossary in `docs/metrics-guide.md` is the one source. README links to it instead of copying rows (`test_site_glossary_is_linked_not_copied`) |
| `src/` | The evidence gates in §5 go red. If the output change is intended, say which gate and why in the PR body |
| A new observation | Schema (`src/tep_core/schemas/`), `docs/report-v2.md`, `docs/metrics-guide.md` and tests in the same PR. Names that hit the forbidden keys in §7 cannot be used |
| An article of `norms.md` | If the article and its enforcement point (code / schema) live in two places, tie them with one test (the shape used in `tests/test_v070_norms_link.py`) |

---

## 5. The four evidence gates that go red when `src/` changes

Bundled evidence is bound to the source tree that produced it (`runner.source_binding`: a sha256 `source_tree_digest` plus `commit_oid`).
Change any of `src/`, `pyproject.toml`, `scripts/v060_provider_live_gate.py` or `scripts/v060_scenario_matrix.py` and the four gates below fail with "source binding is stale" or a digest mismatch. **Going red is the design.** It detects a one-sided change.

| # | Evidence | Test / CI | Verify | Regenerate (when the change is intended) |
|---|---|---|---|---|
| 1 | `evidence/v060/scenarios` (private registry, six R0x scenarios) | `tests/test_v060_scenario_matrix.py` | `python scripts/v060_scenario_matrix.py --verify-registry --output-root evidence/v060/scenarios` | `python scripts/v060_scenario_matrix.py --output-root evidence/v060/scenarios --replace` |
| 2 | `evidence/v060/scenarios-public` (digest-only registry, P01–P03) | CI `v060-golden`, `tests/test_v060_public_registry_export.py` | `python scripts/v060_scenario_matrix.py --verify-registry --digest-only --output-root evidence/v060/scenarios-public` | Provider live gate, PR tier: `python scripts/v060_provider_live_gate.py --tier pr --registry-output evidence/v060/scenarios-public --replace-registry` (read-only fetch of public repositories) |
| 3 | `evidence/v070/benchmark.json` (measures this repository's own history at `PINNED_OID`) | `tests/test_v070_benchmark.py` | `python scripts/v070_benchmark.py` | `python scripts/v070_benchmark.py --write` |
| 4 | `benchmarks/v060/golden` (expected / manifest / migrations) and `DEFINITION_VERSION` | CI `v060-golden`, `scripts/v060_golden.py` | `python scripts/v060_golden.py --result /tmp/v060-golden-result.json` | If the output legitimately changes, bump `DEFINITION_VERSION` in `src/tep_core/version.py` and update the expected files. After a bump, reports saved by the previous version become `CANNOT_VERIFY` under `grift verify` |

At release time (every release, from [RELEASE-REPORT v0.7.2 §5](docs/RELEASE-REPORT-v0.7.2-20260908.md)):

1. All four gates are green on the dev `main`.
2. On the `release/vX.Y.Z` branch that carries the snapshot into the public repository, #1–#3 are **re-bound to public commits** (#3 pins a different OID on each side: `fa9bc31` in dev, `6711a3c` in public).
3. The PR is opened only after `--verify-registry` ×2 returns rc=0, the benchmark holds 6/6 and the full pytest run returns rc=0 on the public branch.

What a contributor does and does not do:

- If #1, #3 or #4 go red on a PR that touches `src/`, **state in the PR body whether the output change is intended.** If it is, regenerate with the commands above and include the result in the same PR.
- #2 (the public registry) is bound to public commits, so it may stay red on a contributor PR. A maintainer re-binds it at release.
- Editing expected values just to make a gate green is not accepted. The condition is that "what changed" is readable in the diff.

---

## 6. PR etiquette

- **One PR, one intent.** The branch name and the PR title share a type: `feat/<what>`, `fix/<what>`, `docs/<what>`, `refactor/<what>`, `chore/<what>`.
- **Commits follow Conventional Commits** `<type>: <description>` (types: `feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci`). Japanese or English descriptions are both fine (the history is mostly Japanese).
- **A `feat` ships with tests.** A new observation comes with the test that fails when the value is missing.
- **Fill in the PR template** (`.github/PULL_REQUEST_TEMPLATE.md`).
  - `H5-E2E:` the command you actually ran and a summary of its raw output (20 characters or more) or a stable log path. For changes with no runtime (docs only): `H5-E2E: none`.
  - **ADR-0001 check G / R / B** (as defined by this template):
    - **G (Green)**: a test that states the acceptance criterion passes. Paste the command and output.
    - **R (Red)**: you measured that the test fails when only one side changes (revert the code, or change only the docs). Say what you broke and what failed.
    - **B (Binding)**: if a declaration (docs / norms / schema) and its enforcement (code) live in two places, one test now ties them together. Write "not applicable" if nothing qualifies.
- **CHANGELOG** follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Add one line under `## [Unreleased]` for anything a user can see. Version numbers and tags are set by maintainers.
- Review checks §7 before it checks correctness.

---

## 7. Design prohibitions (a PR that breaks these is not merged, even when it is correct)

grift **never produces a composite score, a rank, a recommendation or a pass/fail.** This is not a style preference; it is enforced by code, schema and tests.

| Forbidden | Enforced by | Concretely |
|---|---|---|
| Verdict keys | `FORBIDDEN_VERDICT_KEYS` ([src/tep_core/v2_constants.py](src/tep_core/v2_constants.py)) | `score` `rank` `percentile_for_actor` `fit` `compatibility_score` `recommendation` `hire` `pass` `fail` `overall` `fit_score`. Any of these in an alignment output lands in `forbidden_key_hits`, and schema validation plus tests (`tests/test_v060_schema.py` and others) fail |
| Grade vocabulary and multipliers | [scripts/check_forbidden_vocab.py](scripts/check_forbidden_vocab.py) | Literals `素晴らしい` `シニア相当` `ジュニア相当` `スコアカード`; patterns `総合スコア` `grade` `elite` `N倍` `シニア` `ジュニア`. Tests run it over generated Markdown |
| The seven usage norms | [docs/en/norms.md](docs/en/norms.md) | 1 do not read absence as negative / 2 no single-metric cutoff / 3 do not read declaration as negative / 4 no third-party profiling without consent / 5 surveillance use is non-compliant / 6 disclose selectivity / 7 no weighting or conversion |
| Ordering or selecting people by observed volume | [docs/adr/ADR-0001-v08-no-volume-ordering.md](docs/adr/ADR-0001-v08-no-volume-ordering.md) (Japanese) | R1 default artifacts never order people by an observed quantity (actor listings are in id order) / R2 selection by volume says so in its name and notes / R3 a position on a reference distribution appears only when asked for / R4 every observation discloses how it can be inflated, with no correction / R5 two-sided views keep declared and observed apart |
| Declaration and enforcement drifting apart | `tests/test_v070_norms_link.py`, `tests/test_v060_docs_parity.py` | Numbers in the norms (minimum team size 3, for example) and the purpose set are tied to code constants by a single test. Change one side and the test fails naming both values |

Other premises to keep:

- **No LLM.** The same input (SHA, identity, export, `--as-of`) yields the same output except `analyzed_at`.
- **Local by default.** Network is reached only on explicit paths (`--fetch-public`, `update --check`, `contribute --open`, cosign keyless). A new network path needs an opt-in flag.
- **No raw email or other identifying value in output.** Identities carry `email_sha256`; reports never print a raw email.
- **`not_observed` means "could not measure", not "low".** Rates below a population of 20 are suppressed. Invisible history is never filled in or inferred.
- **`--top N` extracts by commit count and is not a quality ranking.** Do not add new selection flags based on observed volume (ADR-0001 R2).

When in doubt, ask: "could a recruiter reject someone from this output without an interview?" If the shape allows that, it does not belong in this repository.

---

## 8. Good first contributions

- Bring the English README / `docs/en/*` back in step with the Japanese (`tests/test_v060_docs_parity.py` tells you where they differ)
- Finish [docs/READERS-GUIDE-draft-20260822.md](docs/READERS-GUIDE-draft-20260822.md) (how non-engineers should read a report; Japanese draft) or start its English counterpart
- Add questions the issue templates should ask but do not
- Run `grift repo` on a real repository, read the output, and report wording you found unclear through the question template

---

## 9. License

By contributing you agree that your contribution is published under the [MIT License](LICENSE).
When you bring in code or text written by someone else, state its license and origin in the PR.
