#!/usr/bin/env python3
"""Measure the claims v0.7.0 makes, in a form someone else can re-run.

A tool whose differentiator is verifiability cannot ship a benchmark that only
its author can reproduce; that is a marketing claim wearing a number. So every
measurement here builds its own fixture from this repository's own history at a
pinned commit, and runs from a fresh clone with nothing else installed.

What is deliberately *not* here: anything needing the local corpus of 152
repositories, the 12-repository AI comparison gate, or the 352-pair validity
study. Those measurements are real and are recorded in the artifact with
`reproducibility: "requires_corpus"` and the corpus stated, but a third party
cannot re-run them and the artifact says so rather than implying otherwise.

    python scripts/v070_benchmark.py            # measure and print
    python scripts/v070_benchmark.py --write    # update evidence/v070/benchmark.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tep_core.complementarity import MIN_TEAM_SIZE  # noqa: E402
from tep_core.identity import RECORDED_EXPLICIT_CONSENT  # noqa: E402
from tep_core.v2_constants import FORBIDDEN_UNITS, MIN_POPULATION_FOR_RATES  # noqa: E402
from tep_core.version import __version__  # noqa: E402

BENCHMARK_SCHEMA_VERSION = "tep-benchmark-v070"

# A commit every clone of this repository has. Pinning it is what makes the
# fixtures reproducible while the branch keeps moving.
PINNED_OID = "fa9bc317cc0ac1953ed09cbab11d3de2232c2fb0"
SHALLOW_DEPTH = 20

# Three people for the team claim. Distinct names and addresses, on a reserved
# `.test` TLD so nothing here can ever resolve to a real mailbox.
TEAM_PEOPLE = (
    ("ana", "Ana Rivera", "ana@example.test"),
    ("bo", "Bo Tanaka", "bo@example.test"),
    ("cy", "Cy Nguyen", "cy@example.test"),
)
# `MIN_POPULATION_FOR_RATES` commits each, or `surface_commit_share` stays
# not_observed and the requirement is never actually measured.
TEAM_COMMITS_EACH = MIN_POPULATION_FOR_RATES
TEAM_FIXTURE_EPOCH = date(2026, 1, 1)

# Fields whose value describes the whole repository and therefore cannot be
# measured from a truncated clone. Same list the R03 scenario asserts.
DEPTH_DEPENDENT = (
    ("context_profile", "repo_age_days"),
    ("context_profile", "resolved_human_actors"),
    ("context_profile", "lifecycle_stage"),
    ("context_profile", "actor_turnover"),
    ("context_profile", "scale", "first_commit"),
    ("context_profile", "scale", "human_commits"),
    ("activity", "repo_human_nonmerge_commits"),
    ("activity", "repo_active_days"),
)
# HEAD is real at any depth; over-degrading is its own defect.
HEAD_ANCHORED = (
    ("context_profile", "scale", "last_commit"),
    ("context_profile", "days_since_last_human_commit"),
)

# Wall-clock fields differ between two runs by definition and are excluded from
# the determinism digest.
VOLATILE_KEYS = ("analyzed_at", "observation_date")

# `repository.name` is the checkout's directory basename, so the same pinned
# revision digests differently in `grift-cli/` and in a worktree. It is the only
# field that differs between two checkouts of this revision (verified by diffing
# the full reports), and leaving it in would make the recorded `report_sha256` a
# fact about one directory rather than about the revision. Excluding it costs
# the determinism claim nothing: within a run pair the name is a constant, so it
# could never have been the thing that differed.
ENVIRONMENT_KEYS = (("repository", "name"),)

# The audit events the offline probe refuses. Interpolated into the probe source
# so the set the artifact reports is the set the probe enforces. Deliberately
# NOT including `subprocess.Popen` / `os.exec*`: see claim_offline.
WATCHED_AUDIT_EVENTS = (
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "urllib.Request",
)


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": "src", "GIT_NO_LAZY_FETCH": "1"}


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    author: tuple[str, str] | None = None,
    stamp: str | None = None,
) -> str:
    """Run git. `author`/`stamp` pin who wrote a commit and when.

    Both halves matter: leaving the author to the ambient git config would make
    the fixture describe whoever ran the benchmark, and leaving the dates to the
    clock would make the same fixture produce a different report tomorrow.
    """
    environment = _env()
    if author is not None:
        name, email = author
        environment |= {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
    if stamp is not None:
        environment |= {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
        env=environment,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def _grift(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tep_cli", *args],
        cwd=cwd or PROJECT_ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=1800,
    )


def _scrub(node: Any) -> None:
    if isinstance(node, dict):
        for key in VOLATILE_KEYS:
            node.pop(key, None)
        for value in node.values():
            _scrub(value)
    elif isinstance(node, list):
        for value in node:
            _scrub(value)


def _digest(report: dict) -> str:
    copy = json.loads(json.dumps(report))
    _scrub(copy)
    for *parents, leaf in ENVIRONMENT_KEYS:
        node = _read(copy, tuple(parents))
        if isinstance(node, dict):
            node.pop(leaf, None)
    blob = json.dumps(copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read(node: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _team_fixture(destination: Path) -> Path:
    """A repository three distinguishable people wrote, built from nothing.

    Not a slice of this repository: the claim is about several actors, and this
    repository does not contain three people with enough history each. Every
    commit is dated and authored explicitly so the fixture is the same on any
    machine, and each person gets `MIN_POPULATION_FOR_RATES` commits because
    below that `surface_commit_share` is `not_observed` and the requirement the
    team view is asked about would never be measured at all.
    """
    destination.mkdir(parents=True, exist_ok=True)
    _git(destination, "init", "-q", "-b", "main")
    (destination / "tests").mkdir(exist_ok=True)
    (destination / "src").mkdir(exist_ok=True)
    day = 0
    for canonical_id, name, email in TEAM_PEOPLE:
        for index in range(TEAM_COMMITS_EACH):
            day += 1
            (destination / "tests" / f"test_{canonical_id}_{index}.py").write_text(
                f"def test_{canonical_id}_{index}():\n    assert True\n", encoding="utf-8"
            )
            (destination / "src" / f"{canonical_id}_{index}.py").write_text(
                f"VALUE_{index} = {index}\n", encoding="utf-8"
            )
            _git(destination, "add", "-A")
            when = TEAM_FIXTURE_EPOCH + timedelta(days=day)
            _git(
                destination,
                "commit",
                "-q",
                "-m",
                f"{canonical_id}: change {index}",
                author=(name, email),
                stamp=f"{when.isoformat()}T12:00:00+00:00",
            )
    return destination


def _shallow_fixture(destination: Path) -> Path:
    """A truncated clone of this repository at the pinned commit."""
    destination.mkdir(parents=True, exist_ok=True)
    _git(destination, "init", "-q")
    _git(
        destination,
        "fetch",
        "-q",
        "--no-tags",
        "--depth",
        str(SHALLOW_DEPTH),
        f"file://{PROJECT_ROOT}",
        PINNED_OID,
    )
    _git(destination, "checkout", "-q", "--detach", "FETCH_HEAD")
    if not (destination / ".git" / "shallow").is_file():
        raise RuntimeError("fixture is not shallow; the measurement would prove nothing")
    return destination


def _pinned_fixture(workdir: Path) -> Path:
    """A full, tag-free fetch of this repository at the pinned commit.

    `--rev` pins the commit but not the tag set, and `scale.tags`,
    `release_cadence`, and `tagset_digest` are derived from whatever tags the
    clone happens to carry. On 2026-09-04 (PR #66) the developer's checkout had
    three tags and a fresh clone of origin had one, so the same pinned revision
    produced two different `report_sha256` values and the artifact could not be
    reproduced in CI. Measuring a `--no-tags` fetch makes the subject the same
    on every machine: the pinned revision, and nothing the clone adds to it.
    """
    destination = workdir / "pinned"
    if destination.exists():
        return destination
    destination.mkdir(parents=True)
    _git(destination, "init", "-q")
    _git(destination, "fetch", "-q", "--no-tags", f"file://{PROJECT_ROOT}", PINNED_OID)
    _git(destination, "checkout", "-q", "--detach", "FETCH_HEAD")
    if _git(destination, "tag", "-l").strip():
        raise RuntimeError("pinned fixture carries tags; the digest would depend on the clone")
    return destination


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------


def claim_determinism(workdir: Path) -> dict[str, Any]:
    """Two runs of the same input produce the same report, byte for byte."""
    digests: list[str] = []
    subject = _pinned_fixture(workdir)
    for _ in range(2):
        result = _grift("repo", str(subject), "--rev", PINNED_OID, "--format", "json")
        if result.returncode != 0:
            return {"measured": None, "error": result.stderr.strip()[:300]}
        digests.append(_digest(json.loads(result.stdout)))
    return {
        "measured": {
            "runs": len(digests),
            "identical": len(set(digests)) == 1,
            "report_sha256": digests[0],
        },
        "holds": len(set(digests)) == 1,
    }


def claim_tamper_detection(workdir: Path) -> dict[str, Any]:
    """A changed value makes `verify` exit non-zero and name both numbers."""
    subject = _pinned_fixture(workdir)
    result = _grift("repo", str(subject), "--rev", PINNED_OID, "--format", "json")
    if result.returncode != 0:
        return {"measured": None, "error": result.stderr.strip()[:300]}
    report = json.loads(result.stdout)
    clean = workdir / "clean.json"
    clean.write_text(json.dumps(report), encoding="utf-8")

    original = _read(report, ("context_profile", "repo_age_days", "value"))
    tampered_value = (original or 0) + 4242
    report["context_profile"]["repo_age_days"]["value"] = tampered_value
    tampered = workdir / "tampered.json"
    tampered.write_text(json.dumps(report), encoding="utf-8")

    ok = _grift("verify", str(clean), "--repo", str(subject))
    bad = _grift("verify", str(tampered), "--repo", str(subject))
    detected = bad.returncode != 0
    names_both = str(tampered_value) in bad.stdout and str(original) in bad.stdout
    return {
        "measured": {
            "clean_exit_code": ok.returncode,
            "tampered_exit_code": bad.returncode,
            "diagnostic_names_reported_and_recomputed": names_both,
            "diagnostic": bad.stdout.strip().splitlines()[-1][:160] if bad.stdout.strip() else "",
        },
        "holds": ok.returncode == 0 and detected and names_both,
    }


def claim_truncated_history(workdir: Path) -> dict[str, Any]:
    """A shallow clone degrades instead of reporting the fetched slice."""
    fixture = _shallow_fixture(workdir / "shallow")
    result = _grift("repo", str(fixture), "--format", "json")
    if result.returncode != 0:
        return {"measured": None, "error": result.stderr.strip()[:300]}
    report = json.loads(result.stdout)
    degraded = {".".join(path): (_read(report, path) or {}).get("kind") for path in DEPTH_DEPENDENT}
    survived = {".".join(path): (_read(report, path) or {}).get("kind") for path in HEAD_ANCHORED}
    return {
        "measured": {
            "shallow": _read(report, ("provenance", "revision_completeness", "shallow")),
            "depth_dependent_fields": len(degraded),
            "degraded_to_not_observed": sum(1 for v in degraded.values() if v == "not_observed"),
            "head_anchored_still_observed": sum(1 for v in survived.values() if v == "observed"),
            "fields": degraded,
        },
        "holds": all(v == "not_observed" for v in degraded.values())
        and all(v == "observed" for v in survived.values()),
    }


def claim_no_verdict_vocabulary(workdir: Path) -> dict[str, Any]:
    """No emitted key or unit is a score, a rank, or a hiring judgement."""
    subject = _pinned_fixture(workdir)
    result = _grift("repo", str(subject), "--rev", PINNED_OID, "--format", "json")
    if result.returncode != 0:
        return {"measured": None, "error": result.stderr.strip()[:300]}
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in FORBIDDEN_UNITS:
                    found.append(f"{path}.{key}")
                if key == "unit" and value in FORBIDDEN_UNITS:
                    found.append(f"{path}.unit={value}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(json.loads(result.stdout), "$")
    return {
        "measured": {"forbidden_vocabulary": sorted(FORBIDDEN_UNITS), "occurrences": found},
        "holds": not found,
    }


def claim_offline(workdir: Path) -> dict[str, Any]:
    """The Python process opens no socket. Subprocess egress is NOT measured.

    `sys.addaudithook` sees only the process that installed it. Every git read
    in grift goes through `subprocess.run` (gitutil.py), so a `git fetch` or a
    `curl` started from there would pass this probe untouched. Adding
    `subprocess.Popen` to the watched set would not fix that -- it would abort
    the analysis at its first `git rev-parse` and measure nothing at all.

    So the claim is narrowed to what the probe actually covers, and the artifact
    says the subprocess layer is unmeasured here rather than implying a proof it
    does not have. `GIT_NO_LAZY_FETCH=1` in `_env()` is a setting, not evidence.
    """
    probe = workdir / "no_network.py"
    # An audit hook rather than a patched `socket.socket`: replacing the class
    # breaks `ssl.SSLSocket`, which subclasses it, so the probe would die during
    # import and prove nothing about what the analysis does. The hook refuses
    # connections and name lookups while leaving every import intact, and it is
    # armed before grift is imported so import-time traffic is caught too.
    probe.write_text(
        "import sys\n"
        f"WATCHED = {set(WATCHED_AUDIT_EVENTS)!r}\n"
        "def _audit(event, args):\n"
        "    if event in WATCHED:\n"
        "        sys.stderr.write('network access attempted during analysis: '\n"
        "                         + event + chr(10))\n"
        "        raise RuntimeError('network access attempted during analysis')\n"
        "sys.addaudithook(_audit)\n"
        "sys.argv = ['grift', 'repo', sys.argv[1], '--rev', sys.argv[2], '--format', 'json']\n"
        "from tep_cli.__main__ import main\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(probe), str(_pinned_fixture(workdir)), PINNED_OID],
        cwd=PROJECT_ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return {
        "measured": {
            "exit_code": result.returncode,
            "network_attempted": "network access attempted" in result.stderr,
            "scope": "python_process_only",
            "watched_audit_events": sorted(WATCHED_AUDIT_EVENTS),
            "git_subprocess_network": "not_measured",
        },
        "holds": result.returncode == 0 and "network access attempted" not in result.stderr,
    }


def claim_team_minimum(workdir: Path) -> dict[str, Any]:
    """Below the declared minimum the team view refuses rather than identifies.

    Measured through the CLI on a repository written by three people who are
    actually distinct. The earlier version called `build_complementarity` in
    process on `[one_dict] * 3`, which is the same object three times: it could
    not have caught a build that deduplicated actors, and it was the only claim
    here that never started a `grift` process. `elapsed_seconds` was 0.00,
    which is what a measurement of nothing costs.
    """
    repo = _team_fixture(workdir / "team-repo")
    identity = workdir / "team-identity.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        + "\n".join(
            f"[[actors]]\n"
            f'canonical_id = "{canonical_id}"\n'
            f'emails = ["{email}"]\n'
            f'attribution_state = "claimed"\n'
            f'consent = "{RECORDED_EXPLICIT_CONSENT}"\n'
            f'authority = "subject-authorization"\n'
            for canonical_id, _name, email in TEAM_PEOPLE
        ),
        encoding="utf-8",
    )

    requirements = workdir / "team-requirements.toml"
    requirements.write_text(
        'schema_version = "tep-project-v1"\n'
        'project_id = "benchmark-team-minimum"\n'
        'title = "benchmark fixture"\n\n'
        "[requirements.surfaces]\n"
        'required = ["test"]\n\n'
        "[requirements.surfaces.min_share]\n"
        "test = 0.2\n",
        encoding="utf-8",
    )

    project_report = workdir / "team-project.json"
    project = _grift(
        "project",
        str(repo),
        "--requirements",
        str(requirements),
        "--format",
        "json",
        "--out",
        str(project_report),
    )
    if project.returncode != 0:
        return {"measured": None, "error": project.stderr.strip()[:300]}

    at_dir = workdir / "team-actors"
    below_dir = workdir / "team-actors-below"
    at_dir.mkdir(parents=True, exist_ok=True)
    below_dir.mkdir(parents=True, exist_ok=True)
    for index, (canonical_id, _name, _email) in enumerate(TEAM_PEOPLE):
        card = at_dir / f"{canonical_id}.json"
        actor = _grift(
            "actor",
            canonical_id,
            str(repo),
            "--identity",
            str(identity),
            "--format",
            "json",
            "--out",
            str(card),
        )
        if actor.returncode != 0:
            return {"measured": None, "error": actor.stderr.strip()[:300]}
        # The below-minimum directory is the same evidence, one person short.
        if index < MIN_TEAM_SIZE - 1:
            (below_dir / card.name).write_text(card.read_text(encoding="utf-8"), encoding="utf-8")

    errors: list[str] = []

    def align(directory: Path) -> tuple[int, dict[str, Any]]:
        result = _grift(
            "align",
            "--actor-dir",
            str(directory),
            "--project-report",
            str(project_report),
            "--team",
        )
        if result.returncode != 0:
            errors.append(f"{directory.name}: {result.stderr.strip()[:150]}")
            return result.returncode, {}
        return result.returncode, json.loads(result.stdout)

    below_code, below = align(below_dir)
    at_code, at = align(at_dir)
    if errors:
        return {"measured": None, "error": " | ".join(errors)[:300]}

    # Three canonical_ids is the declaration; three distinct authors in the
    # emitted evidence is the fact. Only the second one rules out a build that
    # collapsed them.
    distinct_actors = len({card.stem for card in at_dir.glob("*.json")})
    observed_authors = len(
        {
            str((json.loads(card.read_text(encoding="utf-8")).get("subject") or {}).get("actor_id"))
            for card in sorted(at_dir.glob("*.json"))
        }
    )

    measured = {
        "measured": {
            "minimum_team_size": MIN_TEAM_SIZE,
            "distinct_actors": distinct_actors,
            "distinct_actor_ids_in_reports": observed_authors,
            "below_minimum_team_size": MIN_TEAM_SIZE - 1,
            "below_minimum_exit_code": below_code,
            "below_minimum_kind": below.get("kind"),
            "below_minimum_reason": below.get("reason"),
            "at_minimum_exit_code": at_code,
            "at_minimum_kind": at.get("kind"),
            "at_minimum_team_size": at.get("team_size"),
            # A requirement stuck at not_observed would let the claim pass
            # without the three actors ever having been compared to anything.
            "at_minimum_requirement_states": sorted(
                str(requirement.get("state")) for requirement in at.get("requirements") or []
            ),
            "at_minimum_requirements_measured": bool(at.get("requirements"))
            and all(
                requirement.get("state") != "not_observed" for requirement in at.get("requirements")
            ),
            "path": "cli_subprocess",
        }
    }
    return {**measured, "holds": team_minimum_holds(measured["measured"])}


def team_minimum_holds(measured: Mapping[str, Any]) -> bool:
    """Decide the team claim from the values the artifact records.

    A separate function so a test can put a wrong observation in and watch the
    verdict go false. While the verdict was an inline conjunction, deleting one
    of its terms changed no recorded value and no boolean -- the claim simply
    checked less and kept saying HOLDS, which is the failure mode this whole
    benchmark exists to refuse.
    """
    return (
        measured.get("below_minimum_exit_code") == 0
        and measured.get("at_minimum_exit_code") == 0
        and measured.get("distinct_actors") == MIN_TEAM_SIZE
        and measured.get("distinct_actor_ids_in_reports") == MIN_TEAM_SIZE
        # Below the minimum the view must refuse, and refuse for this reason.
        and measured.get("below_minimum_kind") == "not_observed"
        and measured.get("below_minimum_reason") == "insufficient_team_size"
        # At the minimum it must actually report, over three actors.
        and measured.get("at_minimum_kind") == "observed"
        and measured.get("at_minimum_team_size") == MIN_TEAM_SIZE
        # ...having compared them against something. See the key's comment.
        and measured.get("at_minimum_requirements_measured") is True
    )


CLAIMS = (
    (
        "determinism",
        "Two runs over one fixed revision produce an identical report (SHA-256 over "
        "the whole document, excluding wall-clock fields and the checkout's "
        "directory name).",
        claim_determinism,
    ),
    (
        "tamper-detection",
        "`grift verify` exits non-zero on a modified report and names the reported "
        "and recomputed values.",
        claim_tamper_detection,
    ),
    (
        "truncated-history",
        "On a shallow clone, repository-wide fields degrade to not_observed while "
        "HEAD-anchored facts survive.",
        claim_truncated_history,
    ),
    (
        "no-verdict-vocabulary",
        "No emitted key or unit is a score, rank, fit, hire, percentile, or recommendation.",
        claim_no_verdict_vocabulary,
    ),
    (
        "offline",
        "The default analysis path opens no socket from the Python process; git "
        "subprocesses run with GIT_NO_LAZY_FETCH=1 and their network behaviour is "
        "not measured here.",
        claim_offline,
    ),
    (
        "team-minimum",
        "Run through the CLI over a repository written by three distinct people, "
        "`grift align --team` reports coverage counts at the minimum team size and "
        "refuses below it instead of emitting a count that identifies an individual.",
        claim_team_minimum,
    ),
)

# Measured, real, and not reproducible from this repository alone. Recorded with
# what they needed so a reader can tell them apart from the ones above.
CORPUS_CLAIMS = (
    {
        "id": "validity-person-signal",
        "claim": "role_profile tracks the person more than the project: same-person "
        "distances are lower than different-person distances -- measured on "
        "role-profile-v1, before the v0.7.0 consent gate.",
        "measured": {
            "pairs": 352,
            "actors": 300,
            "repositories": 41,
            "same_person_median": 0.0537,
            "different_person_median": 0.1565,
            "cliffs_delta": -0.7871,
            "external_maintainers_only_delta": -0.8096,
            "leave_one_actor_out_min_abs_delta": 0.769,
            "definition_version_at_measurement": "role-profile-v1",
        },
        "reproducibility": "not_reproducible_on_this_version",
        "why_not_reproducible": "v0.7.0 emits role_profile only for actors with a "
        "recorded explicit consent (identity-v2 `consent` + `authority`). The study "
        "corpus is public OSS contributors with no such record; re-measuring would "
        "require asserting consent on their behalf, which the project refuses to do.",
        "corpus": "352 actor-repository pairs over 41 public repositories; see "
        "PREREGISTRATION-2.md for the selection rule fixed before results.",
    },
    {
        "id": "secrets-guard-false-rejection",
        "claim": "Matching credential-shaped values instead of credential vocabulary "
        "stopped the guard refusing repositories whose ordinary public identifiers "
        "merely contained words like `secret`.",
        "measured": {
            "before": "18/181 repositories refused by bare-word match",
            "after": "0/181 with credential-shaped patterns",
        },
        "reproducibility": "requires_corpus",
        "corpus": "181 locally available repositories, 2026-09-02.",
    },
    {
        "id": "provider-independence",
        "claim": "Measurements do not depend on the hosting provider.",
        "measured": {
            "configurations": ["no remote", "GitLab", "self-hosted", "Bitbucket SSH", "Gitea"],
            "identical_reports": True,
        },
        "reproducibility": "requires_corpus",
        "corpus": "One repository re-pointed at five remote configurations.",
    },
    {
        "id": "ai-comparison-gate",
        "claim": "Against a blind LLM given the same repositories, grift wins "
        "determinism and third-party verifiability and loses accuracy and "
        "calibration. SUPERIOR is not claimed.",
        "measured": {
            "verdict": "PARITY",
            "g1_accuracy": {
                "grift": 0.75,
                "llm": 1.0,
                "note": "only the LLM was given the definitions",
            },
            "g2_determinism": {"grift": 1.0, "llm": 0.938},
            "g3_calibration_fabrications": {"grift_at_gate_time": 9, "llm": 0},
            "g4_verifiability": {"grift_tamper_detected": "2/2", "llm": "no binding"},
        },
        "reproducibility": "requires_corpus",
        "corpus": "12 full-clone repositories from 1 to 13,149 non-merge commits; "
        "see PREREGISTRATION-3.md, fixed before results.",
    },
)


def measure() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="grift-benchmark-") as tmp:
        workdir = Path(tmp)
        results = []
        for claim_id, statement, runner in CLAIMS:
            started = time.monotonic()
            outcome = runner(workdir)
            results.append(
                {
                    "id": claim_id,
                    "claim": statement,
                    "reproducibility": "self_contained",
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    **outcome,
                }
            )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "tool_version": __version__,
        "pinned_revision": PINNED_OID,
        "how_to_reproduce": "python scripts/v070_benchmark.py",
        "limitations": [
            "Self-contained claims are re-measured on every run from this "
            "repository's own history at the pinned revision. They are properties "
            "of the tool, not statements about anyone's work.",
            "Corpus claims were measured once against repositories that do not ship "
            "with this package. They are recorded verbatim and cannot be re-run here.",
            "The offline claim is about the Python process layer only: the probe is "
            "an audit hook, which sees nothing a subprocess does. Git subprocess "
            "egress is not measured here; that proof is the upstream "
            "intake_contract_parity egress proof, not this artifact.",
            "report_sha256 is taken over the report with wall-clock fields and the "
            "checkout's directory name removed, so the value is a property of the "
            "pinned revision rather than of the directory it was measured in.",
            "The pinned subject is a tag-free fetch of the pinned commit. Tags are "
            "not part of a revision and differ between clones, and tag-derived "
            "fields (scale.tags, release_cadence, tagset_digest) would otherwise "
            "change report_sha256 from one machine to the next.",
            "No claim here is a benchmark of a person, a team, or a project.",
        ],
        "self_contained": results,
        "corpus_dependent": list(CORPUS_CLAIMS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "evidence" / "v070" / "benchmark.json",
    )
    args = parser.parse_args(argv)

    report = measure()
    failed = [c["id"] for c in report["self_contained"] if not c.get("holds")]

    width = max(len(c["id"]) for c in report["self_contained"])
    for claim in report["self_contained"]:
        mark = "HOLDS" if claim.get("holds") else "FAILED"
        print(f"  {claim['id']:{width}s}  {mark:6s} {claim['elapsed_seconds']:6.2f}s")
    print(
        f"\nself-contained: {len(report['self_contained']) - len(failed)}"
        f"/{len(report['self_contained'])} hold"
    )
    print(f"corpus-dependent (recorded, not re-run): {len(report['corpus_dependent'])}")

    if args.write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.out.relative_to(PROJECT_ROOT)}")

    if failed:
        print(f"\nFAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
