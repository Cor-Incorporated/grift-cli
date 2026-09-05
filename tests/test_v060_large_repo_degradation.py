"""R8 — a Git subprocess budget overrun must degrade, not crash.

`experience_collect` runs `git diff-tree ... --find-copies-harder`, whose cost
grows with repository size. On `dify-local` (11,982 commits) it exceeds the
subprocess budget and `subprocess.TimeoutExpired` escaped to the top level:
the CLI printed a traceback instead of an observation.

Every other missing observation in this codebase is reported as
``not_observed`` with a machine-readable ``reason`` (``history_incomplete``,
``consenting_actor_required``, ``forge_export_not_provided``). A budget
overrun must follow the same contract.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tep_core import experience_collect
from tep_core.analyze import _collection_failure_reason
from tep_core.experience_collect import ExperienceCollectionError

# --------------------------------------------------------------------------
# Layer 1: the Git wrapper converts a budget overrun into a typed error
# --------------------------------------------------------------------------


def test_subprocess_timeout_becomes_a_typed_collection_error(monkeypatch, tmp_path) -> None:
    def fake_run(*_args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["git", "diff-tree"], timeout=kwargs.get("timeout", 180)
        )

    monkeypatch.setattr(experience_collect.subprocess, "run", fake_run)
    with pytest.raises(ExperienceCollectionError) as excinfo:
        experience_collect._git_bytes(tmp_path, "diff-tree", "--stdin")
    assert "timed out" in str(excinfo.value)


def test_timeout_error_does_not_leak_subprocess_type(monkeypatch, tmp_path) -> None:
    """A caller catching ExperienceCollectionError must not also need TimeoutExpired."""

    def fake_run(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["git", "diff-tree"], timeout=180)

    monkeypatch.setattr(experience_collect.subprocess, "run", fake_run)
    try:
        experience_collect._git_bytes(tmp_path, "diff-tree")
    except subprocess.TimeoutExpired:  # pragma: no cover - the defect being fixed
        raise AssertionError("raw TimeoutExpired escaped the collector") from None
    except ExperienceCollectionError:
        pass


# --------------------------------------------------------------------------
# Layer 2: the analyzer maps that error to a reason, and keeps the old ones
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("git subprocess timed out after 180s: diff-tree", "experience_collection_timeout"),
        ("fatal: lazy fetching disabled", "history_incomplete"),
        ("could not fetch from promisor remote", "history_incomplete"),
    ],
)
def test_known_collection_failures_map_to_a_reason(message: str, expected: str) -> None:
    assert _collection_failure_reason(message) == expected


@pytest.mark.parametrize(
    "message",
    ["fatal: bad object HEAD", "error: unknown revision", "permission denied"],
)
def test_unknown_collection_failures_still_propagate(message: str) -> None:
    """Only the two known degradations are absorbed; anything else must surface."""
    assert _collection_failure_reason(message) is None


# --------------------------------------------------------------------------
# Declaration <-> enforcement: the schema enum and the code must not drift
# --------------------------------------------------------------------------


def test_schema_enum_covers_every_absorbed_reason() -> None:
    """Any reason the analyzer can emit must be accepted by the report schema."""
    import json
    from pathlib import Path

    from tep_core.analyze import _COLLECTION_FAILURE_LIMITATION

    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json")
        .read_text(encoding="utf-8")
    )

    enums: list[list[str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            reason = node.get("reason")
            if isinstance(reason, dict) and "enum" in reason:
                enum = reason["enum"]
                if "consenting_actor_required" in enum:
                    enums.append(enum)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert enums, "no actor not_observed reason enum found in the schema"
    emitted = set(_COLLECTION_FAILURE_LIMITATION)
    for enum in enums:
        missing = emitted - set(enum)
        assert not missing, (
            "reasons the analyzer emits are rejected by the schema:\n"
            f"  analyzer: {sorted(emitted)}\n"
            f"  schema:   {sorted(enum)}\n"
            f"  missing:  {sorted(missing)}"
        )


def test_every_absorbed_reason_has_a_limitation() -> None:
    from tep_core.analyze import _COLLECTION_FAILURE_LIMITATION, _collection_failure_reason

    produced = {
        _collection_failure_reason("fatal: lazy fetching disabled"),
        _collection_failure_reason("could not fetch from promisor remote"),
        _collection_failure_reason("git subprocess timed out after 180s"),
    }
    assert produced == set(_COLLECTION_FAILURE_LIMITATION), (
        f"reason producer and limitation table diverged: {produced} vs "
        f"{set(_COLLECTION_FAILURE_LIMITATION)}"
    )


# --------------------------------------------------------------------------
# R8b: copy detection breadth must not change any measured value
# --------------------------------------------------------------------------


def _fixture_with_a_cross_tree_copy(tmp_path):
    """A repo where a later commit adds a byte-identical copy of an untouched file.

    Only `--find-copies-harder` can attribute that as a copy: the source file
    is not modified in the same commit, so plain `-C50%` reports an addition.
    """
    import subprocess as sp

    repo = tmp_path / "copyfix"
    repo.mkdir()

    def git(*args):
        sp.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(tmp_path),
                "GIT_AUTHOR_NAME": "A",
                "GIT_AUTHOR_EMAIL": "a@example.test",
                "GIT_COMMITTER_NAME": "A",
                "GIT_COMMITTER_EMAIL": "a@example.test",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
            },
        )

    git("init", "-q")
    body = "\n".join(f"line {i} of a long enough body to match" for i in range(60)) + "\n"
    (repo / "original.py").write_text(body, encoding="utf-8")
    (repo / "unrelated.md").write_text("docs\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "feat: seed")
    # copy the untouched file; touch nothing else that could pair with it
    (repo / "duplicate.py").write_text(body, encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "feat: duplicate")
    return repo


def test_fixture_actually_exercises_the_flag(tmp_path) -> None:
    """Guard the guard: without this, the invariant test below proves nothing."""
    import subprocess as sp

    repo = _fixture_with_a_cross_tree_copy(tmp_path)
    head = sp.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    def statuses(*extra: str) -> str:
        return sp.run(
            ["git", "-C", str(repo), "diff-tree", "-r", "-M50%", "-C50%",
             *extra, "--name-status", head],
            capture_output=True, text=True, check=True,
        ).stdout

    assert "C" not in statuses().split("\n")[1][:1], "plain -C50% should report an addition"
    assert statuses("--find-copies-harder") != statuses(), (
        "fixture does not exercise --find-copies-harder; the invariant test would be vacuous"
    )


def test_copy_detection_breadth_does_not_change_measured_values(tmp_path, monkeypatch) -> None:
    from tep_core import experience_collect as ec

    repo = _fixture_with_a_cross_tree_copy(tmp_path)
    original = ec._git_bytes

    def collect(drop: bool):
        def patched(r, *args, **kwargs):
            if drop:
                args = tuple(a for a in args if a != "--find-copies-harder")
            return original(r, *args, **kwargs)

        monkeypatch.setattr(ec, "_git_bytes", patched)
        collection = ec.collect_experience_inputs(
            repo,
            revision="HEAD",
            sha_to_actor={},
            bot_actor_ids=(),
            tagger_actor_by_email={},
            snapshot_actor_ids=(),
        )
        return [
            sorted((c.status, c.path) for c in commit.changes) for commit in collection.commits
        ]

    with_flag = collect(drop=False)
    without_flag = collect(drop=True)
    normalised = [
        sorted(("A" if s == "C" else s, p) for s, p in rows) for rows in with_flag
    ]
    normalised_without = [
        sorted(("A" if s == "C" else s, p) for s, p in rows) for rows in without_flag
    ]
    assert normalised == normalised_without, (
        "copy attribution differs once C and A are collapsed, so dropping "
        "--find-copies-harder would change measured values:\n"
        f"  with:    {normalised}\n  without: {normalised_without}"
    )
