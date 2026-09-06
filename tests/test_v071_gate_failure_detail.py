"""Falsification tests for the live gate's recorded failure detail.

``scenario-execution-failed`` on its own says nothing about why a scenario
died, which is how the v0.7.0 release tier reported a bare mismatch id for a
hard ``exit 2``.  The recorded detail is display text built from an untrusted
exception message, so it is held to the same sanitization contract as every
other emitted byte.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "v071_gate_failure_detail_tested",
    ROOT / "scripts" / "v060_provider_live_gate.py",
)
assert _SPEC is not None and _SPEC.loader is not None
gate = importlib.util.module_from_spec(_SPEC)
sys.path.insert(0, str(ROOT / "scripts"))
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


def _spec() -> object:
    return gate._selected("pr")[0]


def test_failure_result_records_sanitized_failure_detail() -> None:
    started = time.monotonic()
    result = gate._failure_result(
        _spec(),
        "scenario-execution-failed",
        started,
        error=gate.GateError("public account attachment rejected the bot row"),
    )
    assert result["mismatch_ids"] == ["scenario-execution-failed"]
    assert result["failure_detail"] == ("GateError: public account attachment rejected the bot row")
    gate._assert_sanitized(json.dumps(result).encode("utf-8"))


def test_failure_detail_is_truncated_to_two_hundred_characters() -> None:
    message = "x" * 500
    result = gate._failure_result(
        _spec(),
        "scenario-execution-failed",
        time.monotonic(),
        error=ValueError(message),
    )
    assert result["failure_detail"] == "ValueError: " + "x" * 200


def test_assert_sanitized_rejects_a_token_bearing_failure_detail() -> None:
    body = json.dumps({"failure_detail": "GateError: ghp_livetokenvalue rejected"}).encode()
    with pytest.raises(gate.GateError, match="provider credential"):
        gate._assert_sanitized(body, secrets=("ghp_livetokenvalue",))


@pytest.mark.parametrize(
    ("message", "secrets"),
    [
        ("token ghp_livetokenvalue leaked", ("ghp_livetokenvalue",)),
        ("cannot open /Users/someone/repo/manifest.json", ()),
        ("GET https://api.github.com/repos/a/b failed", ()),
    ],
)
def test_failure_detail_is_redacted_when_it_would_not_survive_sanitization(
    message: str, secrets: tuple[str, ...]
) -> None:
    result = gate._failure_result(
        _spec(),
        "scenario-execution-failed",
        time.monotonic(),
        error=RuntimeError(message),
        secrets=secrets,
    )
    assert result["failure_detail"] == "RuntimeError: <redacted>"
    gate._assert_sanitized(json.dumps(result).encode("utf-8"), secrets=secrets)


def test_failure_detail_absent_reason_keeps_detail_none() -> None:
    result = gate._failure_result(_spec(), "suite-timeout", time.monotonic())
    assert result["failure_detail"] is None


def test_run_gate_writes_failure_detail_without_leaking_the_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    binding = {
        "tool_version": "0.7.1",
        "source_binding": {
            "definition_version": "grift-tool-source-tree-v1",
            "source_tree_digest": {"algorithm": "sha256", "value": "c" * 64},
            "file_count": 1,
            "commit_oid": {"algorithm": "sha1", "value": "d" * 40},
        },
    }
    monkeypatch.setattr(gate, "_selected", lambda _tier: (spec,))
    monkeypatch.setattr(gate, "build_runner_binding", lambda _root: binding)
    monkeypatch.setattr(gate, "definition_digest", lambda _tier: "e" * 64)
    monkeypatch.setattr(gate, "_acquisition_context", lambda *_a, **_k: gate.AcquisitionContext())
    monkeypatch.setattr(gate, "_has_private_bundle", lambda *_a, **_k: False)

    def fail_scenario(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise gate.GateError("account 'github|github.com|198982749' rejected")

    monkeypatch.setattr(gate, "_run_scenario", fail_scenario)
    monkeypatch.setenv("CUSTOM_GITHUB_TOKEN", "github-secret-not-for-summary")
    monkeypatch.setenv("CUSTOM_GITLAB_TOKEN", "gitlab-secret-not-for-summary")
    args = argparse.Namespace(
        tier="pr",
        repo_root=tmp_path / "repos",
        summary=tmp_path / "summary.json",
        ledger=tmp_path / "ledger.jsonl",
        github_token_env="CUSTOM_GITHUB_TOKEN",
        gitlab_token_env="CUSTOM_GITLAB_TOKEN",
        source_commit="d" * 40,
        suite_deadline_epoch=None,
        partial_bundle_root=tmp_path / "private",
        registry_output=None,
        replace_registry=False,
    )

    assert gate.run_gate(args) == 1
    result = json.loads(args.summary.read_text(encoding="utf-8"))["results"][0]
    assert result["outcome"] == "FAIL"
    assert result["mismatch_ids"] == ["scenario-execution-failed"]
    assert result["failure_detail"] == ("GateError: account 'github|github.com|198982749' rejected")
    summary_bytes = args.summary.read_bytes()
    assert b"github-secret-not-for-summary" not in summary_bytes
    assert b"gitlab-secret-not-for-summary" not in summary_bytes
