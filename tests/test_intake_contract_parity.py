"""Sender-side tests for the executable tep-contributions parity gate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "intake_contract_parity.py"


def _module():
    spec = importlib.util.spec_from_file_location("intake_contract_parity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sender_profiles_are_generated_by_the_real_cli(tmp_path: Path) -> None:
    module = _module()
    payloads, commands = module.generate_sender_payloads(tmp_path)

    assert set(payloads) == {"aggregate", "named-public", "masked", "raw"}
    assert payloads["aggregate"]["door"] == "public-pr"
    assert payloads["named-public"]["door"] == "public-pr"
    assert payloads["masked"]["door"] == "controlled"
    assert payloads["raw"]["door"] == "controlled"
    assert payloads["aggregate"]["policy"]["source_replay"] == ("unavailable_from_public_payload")
    assert payloads["named-public"]["policy"]["source_replay"] == ("public_api_recollect_required")
    assert (
        payloads["aggregate"]["transformation_spec_digest"]
        != payloads["named-public"]["transformation_spec_digest"]
    )
    named_data = payloads["named-public"]["data"]
    assert named_data["project"] == {
        "provider": "github",
        "host": "github.com",
        "project_id": "R_kgDOContract",
        "project_path": "example/public-contract",
    }
    assert named_data["authority"]["accounts"][0]["project_id"] == "R_kgDOContract"
    assert named_data["actors"][0]["account"]["evidence"] == {
        "basis": "commit.author.id",
        "coverage_status": "complete",
        "account_match_status": "linked",
    }
    assert all(command[:4] == ["python", "-m", "tep_cli", "contribute"] for command in commands)


def test_socket_denial_is_dynamically_proven_and_recorded(tmp_path: Path) -> None:
    module = _module()
    network_env, seed = module._install_network_denial(tmp_path)
    assert network_env["GRIFT_INTAKE_NETWORK_PHASE"] == "workload"

    proof = module._network_denial_report(seed)
    assert proof["mode"] == "python_socket_deny"
    assert proof["probe_exit_code"] != 0
    assert proof["probe_signal"] == "GRIFT_INTAKE_NETWORK_DENIED"
    assert proof["probe_denied_calls"] == 1
    assert proof["workload_denied_calls"] == 0
    assert proof["workload_network_attempted"] is False
    assert len(proof["ledger_sha256"]) == 64


def test_missing_companion_contract_is_cannot_verify(tmp_path: Path, capsys) -> None:
    module = _module()
    result = tmp_path / "result.json"
    ledger = tmp_path / "guard-ledger.jsonl"
    code = module.main(
        [
            "--companion-root",
            str(tmp_path / "missing"),
            "--result",
            str(result),
            "--ledger",
            str(ledger),
        ]
    )
    assert code == 1
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "CANNOT_VERIFY"
    assert "validate.py" in payload["error"]
    ledger_row = json.loads(ledger.read_text(encoding="utf-8"))
    assert ledger_row == {
        "actual": None,
        "case": "preflight",
        "expected": None,
        "exit_code": None,
        "guard": "intake_contract_parity",
        "passed": False,
        "payload_sha256": None,
        "profile": None,
        "receiver_commit": None,
        "schema_version": "tep-intake-contract-guard-v1",
        "sender_commit": None,
        "status": "CANNOT_VERIFY",
    }
    assert "CANNOT_VERIFY" in capsys.readouterr().out


def test_case_result_requires_expected_receiver_outcome() -> None:
    module = _module()
    assert module.CaseResult("ok", "aggregate", "accepted", "accepted", 0, "a" * 64, "").passed
    assert not module.CaseResult("bad", "aggregate", "rejected", "accepted", 0, "b" * 64, "").passed


def test_result_schema_refuses_nonfinite_json() -> None:
    module = _module()
    with pytest.raises(ValueError):
        module._payload_text({"value": float("nan")})


def test_synthetic_repo_ignores_host_git_templates_and_global_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    template = tmp_path / "template"
    hooks = template / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    global_config = tmp_path / "host.gitconfig"
    global_config.write_text(
        f"[init]\n\ttemplateDir = {template}\n[user]\n\tname = Host User\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    report = module._make_report(workspace, network_env={})

    assert report.is_file()
    assert not (workspace / "source-repo" / ".git" / "hooks" / "pre-commit").exists()


def test_verified_requires_clean_exact_sender_and_receiver_revisions() -> None:
    module = _module()
    passed = [module.CaseResult("ok", "aggregate", "accepted", "accepted", 0, "a" * 64, "")]
    args = {
        "expected_sender_sha": "a" * 40,
        "actual_sender_sha": "a" * 40,
        "sender_dirty": False,
        "expected_companion_sha": "b" * 40,
        "actual_companion_sha": "b" * 40,
        "companion_dirty": False,
    }
    assert module._final_status(passed, **args) == "VERIFIED"
    assert module._final_status(passed, **(args | {"sender_dirty": True})) == ("PREREQUISITE_DIRTY")
    assert module._final_status(passed, **(args | {"companion_dirty": True})) == (
        "PREREQUISITE_DIRTY"
    )
    assert module._final_status(passed, **(args | {"expected_sender_sha": None})) == (
        "CANNOT_VERIFY"
    )
