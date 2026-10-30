# Migrating to v0.9.2

Japanese original: [migration-v092.md](../migration-v092.md). That page also keeps the notes for
0.9.1 and earlier (in Japanese). This page covers what changed in 0.9.2. For 0.9.1, see
[migration-v091.md](migration-v091.md).

The existing `analyze` / `report` / `verify` / `contribute` commands still produce report-v1. Every
command from v0.6.0 to v0.9.1 is still there.

## What changes in 0.9.2

**No new commands. 0.9.2 makes grift runnable in Docker and fixes what `contribute`, the context
profile and `update` print or do.** CLI flags, enum values and the JSON shapes do not change, and neither do the
analysis values: building a repo report for a synthetic repository (30 commits by one author) with 0.9.1 and with
0.9.2 and comparing them, only three fields differ: `provenance.tool_version` and `definition_version`
(in `provenance` and in `metrics.human_nonmerge_commit_share`). Four things change.

### grift runs in Docker (PR #115)

- A `Dockerfile` (two stages on `python:3.12-slim`; only `git` and `openssh-client` are bundled; a non-root
  user, uid 1000; the entrypoint is `grift`) and a `.dockerignore` that lets only the wheel inputs through.
  Usage is in the README, "Use with Docker"
- `gh` and `cosign` are not bundled. Run `contribute --open` and anything that calls cosign (`attest --sign cosign`,
  and `verify` or `portfolio` with a cosign trust policy) on the host
- You build the image from your own clone with `docker build`. The image is not published to a registry
- A linked `git worktree` cannot be mounted (its `.git` points outside the mount, so the run stops with exit 2).
  A shallow clone does not stop the run, but grift counts only the commits it was given and reports
  `revision_completeness` as incomplete (`complete: false`)
- CI gets a `docker` job. It checks the image's version, the bundled tools, that the wheel holds exactly the tracked
  package files, and `repo` on a read-only mount with no network, and keeps the result as `guard-ledger.jsonl` in an
  artifact. `tests/test_docker_build_inputs.py` ties the readme and the wheel inputs in `pyproject.toml` to the
  Dockerfile's `COPY` lines and to `.dockerignore`

### `grift contribute` shows only steps that can be run after consent (PR #111, stderr wording only)

A bare `grift contribute` also saves `.grift/contribution.json` after consent. It never submits by itself. A v2 payload
made with the default `--door local` cannot be submitted to the public intake, so no submission id, file name inside the
PR or meta line is printed for it: only the step to make it again with `--door public-pr` is. To submit publicly, use what
that run prints: the submission id, the file name inside the PR, a meta line with the SHA-256 of the saved bytes, and the
URLs of the two submission paths. For a purpose the public intake cannot take, such as `--purpose outcome-linkage`, one
line says so and no public submission guide is printed. The output for controlled, masked and raw shows no public
submission guide. With `--open`, it explains that after the local pre-push check it creates a branch on your fork and
commits and pushes (you still press the last button); if gh/git is unavailable or fails, it prints the steps for the file
that was written (the `--out` path as `payloads/<year>/<submission-id>.json`, and the meta line saved as `.meta.json`), and
if it fails after the push it prints the URL of the pull request page instead of steps. Exit codes and the JSON on stdout
do not change. For a report-v1 report, `--purpose` is still ignored (existing behaviour, not fixed: see "Known
limitations" in `CHANGELOG.md`).

### The context profile shows the basis of the activity years and the tag frequency (PR #112, Markdown only)

The context in the report-v1 Markdown now shows the first and last activity years (`joined` / `last_active`; not a
departure) and the numerator and denominator of the tag frequency (`tags / active_span_days × 365.25`). For a repository
whose activity span is shorter than 20 days the tag frequency is not annualized and only the counts are shown (no rate on
a small denominator). The JSON values do not change. These two rows appear only in the report-v1 Markdown (`grift
analyze` and a bare `grift report`), not in the report-v2 Markdown of `grift repo` and the like (same as 0.9.1). The
metrics guide (both languages) says the same.

### `grift update` updates only the running environment (PR #113, **behaviour changes**)

| | 0.9.1 | 0.9.2 |
|---|---|---|
| `grift update` (without `--check`) | Fetches the PyPI metadata first. Upgrades with `pipx` on PATH, otherwise `pip` / `pip3` on PATH | Does not fetch metadata. If the running environment is managed by pipx it runs `pipx upgrade` for that environment, otherwise `-P -m pip install --upgrade grift-cli` with the running Python. Never uses another environment on PATH. Prints the installed version as `installed after update: grift X.Y.Z` |
| `grift update --check` | Reads the metadata. Exits 0 when it cannot connect (`version check skipped`) | Only reads the metadata and installs nothing. Exits **2** when it cannot connect |
| When the installer fails | Returns its exit code | Returns its exit code and does not print success. If the version cannot be read back it exits 2 |

The installer is started as `python -P -m pip` (so a `pip.py` in the current directory is not read), from the directory
of the running environment rather than the repository being analysed, and `PYTHONPATH`, `PIP_TARGET`, `PIP_PREFIX` and
`PIP_ROOT` are not passed on. Measuring commands still never touch the network (neither does `grift --version`).

### Not in 0.9.2 (left for 0.9.3 and later)

- The 0.9.2 stock listed in the 0.9.1 notes (M3 and others) is not in 0.9.2
- The MEDIUM and LOW findings from the reviews of the three PRs that were not fixed are listed under "Known limits" in
  the 0.9.2 section of `CHANGELOG.md`

### Do you need to re-collect?

| Artifact | What 0.9.2 `verify` says about one written by 0.9.1 | Regenerate |
|---|---|---|
| report-v1 (`analyze` / `report`) | CANNOT_VERIFY (definition version), rc=2 | yes, if you use verify |
| actor / repo report-v2 (outside a collection) | CANNOT_VERIFY (definition version), rc=2 | yes |
| project report (project-v1) | One that observed a repository (`grift project REPO`) is MISMATCH (the `definition_version` field), rc=1. One made only from requirements (`grift project --requirements`) is VERIFIED, rc=0 | yes for the one that observed a repository |
| alignment (alignment-v1, `align`) | CANNOT_VERIFY (definition version), rc=2 | yes |
| actor collection (`repo --actors` and so on) | Does not look at the definition version. One written by `repo --actors` is VERIFIED, rc=0 | no (the `--as-of` plus identity cases are as in the 0.9.1 notes; not re-measured for 0.9.2) |
| attest / portfolio | Re-sign if the digest of the input report changes | depends on the input |

```
# synthetic repo (30 commits by one author, 2026-07-01 to 28, one annotated tag). Measured 2026-10-30
# 0.9.1 = the src of main 7f2acec, 0.9.2 = the src of this release
$ grift verify out091-analyze/report.json --repo repo      # grift analyze by 0.9.1
CANNOT_VERIFY:
  - definition version 'tep-v0.9.1-2026-10-28' is not the current 'tep-v0.9.2-2026-10-30' — historical versions cannot be reproduced yet (compatibility table: docs/report-schema.md)
# rc=2. The repo report-v2, the actor report-v2 and the alignment are CANNOT_VERIFY rc=2 for the same reason

$ grift verify p091/project.json --repo repo --project project.toml    # grift project REPO --requirements … by 0.9.1
MISMATCH: 1 field(s) differ
  - definition_version: report='tep-v0.9.1-2026-10-28' recomputed='tep-v0.9.2-2026-10-30'
# rc=1

$ grift verify pd091/project.json --project project.toml               # grift project --requirements … by 0.9.1 (no repository)
VERIFIED: all fields match recomputation under recorded provenance
# rc=0

$ grift verify coll091 --repo repo                                     # grift repo --actors --out coll091 by 0.9.1
VERIFIED: actor collection 6 member(s), full=1, selected=1
# rc=0
```

## Definition version

`DEFINITION_VERSION` goes from `tep-v0.9.1-2026-10-28` to `tep-v0.9.2-2026-10-30` (REL-092). This follows the version
and is not caused by a change in JSON values. The version cannot be raised alone (the golden runner fails a difference in
`provenance.tool_version` as D3, and approval needs D4, a difference in the definition version; the same since 0.7.1). The date in
the definition version is the planned release date; if the release day changes, fix it before the golden approval.

The golden baseline was approved as `gold-actor-partition-0008` (approved by human:teradakousuke at
2026-10-30T13:17:31Z, requirement REL-092; the dry-run drift was D3 ×1, D4 ×2, D0–D2 = 0, no observed-value drift).

## CI

CI gets a `docker` job (see "grift runs in Docker" above). The other jobs do not change.
