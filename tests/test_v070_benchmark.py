"""The release claims, and the artifact that records them, kept in agreement.

A benchmark that always passes is not a detector, and a benchmark only its
author can run is a press release. These tests hold the artifact to both
standards:

* every self-contained claim is re-measured here, not read back from the file
* the checked-in artifact must match what a fresh measurement produces
* the artifact must not quietly promote a corpus measurement into something a
  reader would assume they can reproduce

The claims themselves live in `scripts/v070_benchmark.py`; this file is the
thing that fails when the artifact and the code drift apart.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evidence" / "v070" / "benchmark.json"

sys.path.insert(0, str(ROOT / "scripts"))

import v070_benchmark as bench  # noqa: E402


@pytest.fixture(scope="module")
def artifact() -> dict:
    assert ARTIFACT.is_file(), (
        f"the benchmark artifact is missing; run "
        f"`python scripts/v070_benchmark.py --write` ({ARTIFACT})"
    )
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def measured() -> dict:
    """One fresh measurement, shared by the tests that compare against it."""
    return bench.measure()


# --------------------------------------------------------------------------
# The claims hold now, not only when the artifact was written
# --------------------------------------------------------------------------


def test_every_self_contained_claim_holds(measured: dict) -> None:
    failed = [
        {"id": claim["id"], "measured": claim.get("measured"), "error": claim.get("error")}
        for claim in measured["self_contained"]
        if not claim.get("holds")
    ]
    assert not failed, json.dumps(failed, ensure_ascii=False, indent=1)


def test_the_artifact_records_the_same_claims(artifact: dict, measured: dict) -> None:
    recorded = [claim["id"] for claim in artifact["self_contained"]]
    fresh = [claim["id"] for claim in measured["self_contained"]]
    assert recorded == fresh, (
        f"the artifact records {recorded} but the script measures {fresh}; "
        "one of them is out of date"
    )


def test_the_artifact_is_not_stale_on_outcomes(artifact: dict, measured: dict) -> None:
    """A recorded HOLDS beside a failing claim is worse than no artifact."""
    recorded = {claim["id"]: claim.get("holds") for claim in artifact["self_contained"]}
    fresh = {claim["id"]: claim.get("holds") for claim in measured["self_contained"]}
    assert recorded == fresh, (
        f"artifact says {recorded}, a fresh run says {fresh}. Re-run "
        "`python scripts/v070_benchmark.py --write`."
    )


# Keys whose value cannot be equal between two runs by construction, and so
# cannot be evidence that the artifact is current. Everything else is compared.
NON_DETERMINISTIC_KEYS = frozenset({"elapsed_seconds"})
# The tamper diagnostic quotes one line of `grift verify` output, including the
# recomputed value. Its *shape* is the claim ("names both numbers"), which is
# already asserted as a boolean beside it; the line itself moves with wording.
NON_DETERMINISTIC_MEASURED = {("tamper-detection", "diagnostic")}


def _comparable(claim: dict) -> dict:
    measured = claim.get("measured")
    if not isinstance(measured, dict):
        return {"measured": measured}
    return {
        key: value
        for key, value in measured.items()
        if key not in NON_DETERMINISTIC_KEYS
        and (claim["id"], key) not in NON_DETERMINISTIC_MEASURED
    }


def test_the_artifact_is_not_stale_on_measured_values(artifact: dict, measured: dict) -> None:
    """`holds` agreeing is not the same as the numbers agreeing.

    Comparing only the booleans let every recorded value -- `report_sha256`,
    the exit codes, the degraded-field counts -- stay at whatever it was when
    someone last ran `--write`, while the file kept passing. The digest is the
    sharpest of them: it is taken over the report with wall-clock fields and the
    checkout's directory name removed, so at a pinned revision it is the same on
    any machine, and a mismatch means the artifact predates a change in what the
    tool emits.
    """
    recorded = {claim["id"]: _comparable(claim) for claim in artifact["self_contained"]}
    fresh = {claim["id"]: _comparable(claim) for claim in measured["self_contained"]}
    drifted = sorted(key for key in fresh if recorded.get(key) != fresh[key])
    assert not drifted, (
        "the artifact records different measurements than a fresh run for "
        f"{drifted}:\n"
        + json.dumps(
            {key: {"artifact": recorded.get(key), "fresh": fresh[key]} for key in drifted},
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        )
        + "\nRe-run `python scripts/v070_benchmark.py --write`."
    )


def _with_value(report: dict, path: tuple[str, ...], value: object) -> dict:
    """Return a copy of `report` with one nested key replaced."""
    updated = copy.deepcopy(report)
    node: Any = updated
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return updated


def test_the_digest_ignores_the_environment_it_was_measured_in() -> None:
    """Equality on `report_sha256` is only fair if the digest is portable.

    The test above demands the recorded digest equal a fresh one. That demand
    is a staleness detector only while the digest depends on nothing but the
    pinned revision. `repository.name` is the checkout's directory basename, so
    without the normalisation in `_digest` the same revision hashes differently
    in `grift-cli/` and in a worktree, and the equality check would fail for
    anyone whose directory happens to be named something else -- a false red
    that says nothing about the artifact.

    Dropping the normalisation is therefore not a simplification, and this is
    what notices. The field is also asserted to still exist: if it were renamed
    upstream, the normalisation would keep running while removing nothing, and
    a test built on a synthetic report would never see it.
    """
    result = bench._grift(
        "repo", str(bench.PROJECT_ROOT), "--rev", bench.PINNED_OID, "--format", "json"
    )
    assert result.returncode == 0, result.stderr[-500:]
    report = json.loads(result.stdout)

    left, right = report, report
    for index, path in enumerate(bench.ENVIRONMENT_KEYS):
        node: Any = report
        for key in path:
            assert isinstance(node, dict) and key in node, (
                f"{'.'.join(path)} is no longer in the report, so the digest "
                "normalisation removes nothing and this guard is measuring air"
            )
            node = node[key]
        left = _with_value(left, path, f"left-checkout-{index}")
        right = _with_value(right, path, f"right-checkout-{index}")

    assert bench._digest(left) == bench._digest(right), (
        "the digest changes with "
        f"{['.'.join(path) for path in bench.ENVIRONMENT_KEYS]}, so report_sha256 "
        "describes the directory it was measured in rather than the revision"
    )


def test_the_recorded_digest_is_the_one_this_tree_produces(artifact: dict, measured: dict) -> None:
    """The single value a third party can check by hand, held to equality."""
    recorded = next(c for c in artifact["self_contained"] if c["id"] == "determinism")
    fresh = next(c for c in measured["self_contained"] if c["id"] == "determinism")
    assert recorded["measured"]["report_sha256"] == fresh["measured"]["report_sha256"], (
        f"the artifact records report_sha256={recorded['measured']['report_sha256']} "
        f"but this tree produces {fresh['measured']['report_sha256']} at "
        f"{bench.PINNED_OID}"
    )


def test_the_tool_version_matches(artifact: dict) -> None:
    from tep_core.version import __version__

    assert artifact["tool_version"] == __version__, (
        f"the artifact was produced by {artifact['tool_version']} but this tree is {__version__}"
    )


# --------------------------------------------------------------------------
# A benchmark that cannot fail is not a measurement
# --------------------------------------------------------------------------


def test_the_shallow_claim_cannot_pass_by_degrading_everything() -> None:
    """The claim needs both halves, or it stops being a measurement.

    Checking only that fields degrade would be satisfied by a build that
    returned not_observed for everything -- the over-correction that is its own
    defect. Requiring HEAD-anchored fields to survive is what makes the claim
    two-sided.

    This is a structural check, not a falsification: the claim runs the CLI in
    a subprocess, so an in-process patch cannot reach it. The falsification was
    run by hand against a mutated `context_profile.py` and is recorded in the
    commit; a test that monkeypatched something the subprocess never imports
    would only look like one.
    """
    assert bench.DEPTH_DEPENDENT, "the claim checks no fields"
    assert bench.HEAD_ANCHORED, "the claim would pass by degrading everything"
    overlap = set(bench.DEPTH_DEPENDENT) & set(bench.HEAD_ANCHORED)
    assert not overlap, f"a field is required to both degrade and survive: {overlap}"


def test_the_team_claim_fails_when_any_half_of_it_is_wrong(artifact: dict) -> None:
    """Each term of the team verdict is load-bearing, checked one at a time.

    The recorded measurement is taken as the passing case and each value is
    then broken on its own. A term that can be broken without the verdict
    changing is a term that was never being enforced -- which is exactly what
    happened while the verdict was an inline conjunction: deleting the
    below-minimum check left every recorded value and every boolean identical,
    so nothing anywhere went red.
    """
    recorded = next(c for c in artifact["self_contained"] if c["id"] == "team-minimum")["measured"]
    assert bench.team_minimum_holds(recorded), recorded

    broken = {
        "below_minimum_kind": "observed",
        "below_minimum_reason": None,
        "below_minimum_exit_code": 1,
        "at_minimum_kind": "not_observed",
        "at_minimum_exit_code": 1,
        "at_minimum_team_size": bench.MIN_TEAM_SIZE - 1,
        "at_minimum_requirements_measured": False,
        "distinct_actors": 1,
        "distinct_actor_ids_in_reports": 1,
    }
    survived = [
        key for key, value in broken.items() if bench.team_minimum_holds({**recorded, key: value})
    ]
    assert not survived, (
        f"the team claim still holds with {survived} wrong; those terms are "
        "decoration, not measurement"
    )


def test_the_script_exits_non_zero_when_a_claim_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The benchmark is usable as a gate only if failure reaches the exit code."""

    def failing() -> dict:
        return {
            "schema_version": bench.BENCHMARK_SCHEMA_VERSION,
            "tool_version": "test",
            "pinned_revision": bench.PINNED_OID,
            "how_to_reproduce": "x",
            "limitations": [],
            "self_contained": [
                {
                    "id": "x",
                    "claim": "c",
                    "reproducibility": "self_contained",
                    "elapsed_seconds": 0.0,
                    "measured": {},
                    "holds": False,
                }
            ],
            "corpus_dependent": [],
        }

    monkeypatch.setattr(bench, "measure", failing)
    assert bench.main([]) == 1


# --------------------------------------------------------------------------
# Honesty about what a reader can reproduce
# --------------------------------------------------------------------------


CORPUS_REPRODUCIBILITY = {"requires_corpus", "not_reproducible_on_this_version"}


def test_corpus_claims_are_labelled_as_not_reproducible(artifact: dict) -> None:
    for claim in artifact["corpus_dependent"]:
        assert claim["reproducibility"] in CORPUS_REPRODUCIBILITY, (
            f"{claim['id']} is labelled {claim['reproducibility']!r}; a corpus claim "
            f"must be one of {sorted(CORPUS_REPRODUCIBILITY)}"
        )
        assert claim.get("corpus"), (
            f"{claim['id']} says it needs a corpus but does not say which; a "
            "reader cannot judge the measurement"
        )


def test_a_claim_that_cannot_be_re_measured_says_why(artifact: dict) -> None:
    """ "Not reproducible" is an excuse until it names the thing in the way.

    `validity-person-signal` was measured under `role-profile-v1` and cannot be
    re-run on v0.7.0: the consent gate emits `role_profile` only for actors with
    a recorded explicit consent, and the study corpus is public OSS contributors
    who have given none. That is a design consequence, not a defect -- but a
    label alone would let any future claim retire behind the same word, so the
    reason has to be written out where a reader can disagree with it.

    The length floor is checked on any claim that carries the field, not only on
    the ones currently labelled. Otherwise the explanation could be reduced to a
    stub by first relabelling the claim, and the stub would be waiting the next
    time someone labelled it back.
    """
    for claim in artifact["corpus_dependent"]:
        reason = claim.get("why_not_reproducible")
        if claim["reproducibility"] == "not_reproducible_on_this_version":
            assert reason, (
                f"{claim['id']} declares itself not reproducible on this version "
                "without saying what is in the way"
            )
        if reason is None:
            continue
        assert len(reason) >= 40, (
            f"{claim['id']} explains why it cannot be re-measured in "
            f"{len(reason)} characters: {reason!r}"
        )


def test_self_contained_claims_are_labelled_as_such(artifact: dict) -> None:
    for claim in artifact["self_contained"]:
        assert claim["reproducibility"] == "self_contained", claim["id"]


def test_the_two_classes_do_not_overlap(artifact: dict) -> None:
    self_ids = {claim["id"] for claim in artifact["self_contained"]}
    corpus_ids = {claim["id"] for claim in artifact["corpus_dependent"]}
    assert not (self_ids & corpus_ids), sorted(self_ids & corpus_ids)


def test_the_ai_gate_result_is_recorded_without_softening(artifact: dict) -> None:
    """The gate was not won. The artifact must say so in its own words."""
    gate = next(c for c in artifact["corpus_dependent"] if c["id"] == "ai-comparison-gate")
    assert gate["measured"]["verdict"] == "PARITY"
    assert "SUPERIOR is not claimed" in gate["claim"]
    assert gate["measured"]["g1_accuracy"]["grift"] < gate["measured"]["g1_accuracy"]["llm"]
    assert gate["measured"]["g3_calibration_fabrications"]["grift_at_gate_time"] > 0


def test_the_artifact_states_it_does_not_benchmark_people(artifact: dict) -> None:
    text = " ".join(artifact["limitations"]).lower()
    assert "is a benchmark of a person, a team, or a project" in text, text


def test_the_artifact_says_how_to_reproduce_it(artifact: dict) -> None:
    command = artifact["how_to_reproduce"]
    assert "v070_benchmark.py" in command
    assert (ROOT / "scripts" / "v070_benchmark.py").is_file()
