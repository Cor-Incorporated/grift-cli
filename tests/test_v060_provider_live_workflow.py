from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v060-provider-live.yml"
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"
_SPEC = importlib.util.spec_from_file_location(
    "v060_scenario_matrix_workflow_test",
    ROOT / "scripts" / "v060_scenario_matrix.py",
)
assert _SPEC is not None and _SPEC.loader is not None
matrix = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = matrix
_SPEC.loader.exec_module(matrix)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_provider_live_is_manual_only_and_outside_ordinary_ci() -> None:
    body = _workflow()
    trigger = body.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "pull_request:" not in trigger
    assert "push:" not in trigger
    assert "schedule:" not in trigger
    assert "v060-provider-live" not in (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )


def test_release_credentials_fail_before_checkout_or_provider_runner() -> None:
    body = _workflow()
    preflight = body.index("credential-preflight:")
    provider = body.index("provider-live:", preflight + 1)
    checkout = body.index("actions/checkout@v4")
    assert preflight < provider < checkout
    block = body[preflight:provider]
    assert '[[ "$LIVE_TIER" == "release" ]]' in block
    assert 'test -n "$V060_GITHUB_TOKEN"' in block
    assert 'test -n "$V060_GITLAB_TOKEN"' in block
    assert block.count("exit 2") == 2


def test_release_credential_preflight_is_red_before_any_network_command() -> None:
    body = _workflow()
    start = body.index("      - name: Require release provider credentials")
    run_marker = body.index("        run: |\n", start) + len("        run: |\n")
    end = body.index("\n\n  provider-live:", run_marker)
    script = textwrap.dedent(body[run_marker:end])
    assert "git " not in script
    assert "python " not in script

    for github_token, gitlab_token, expected_message in (
        ("", "gitlab-token", "requires V060_GITHUB_TOKEN"),
        ("github-token", "", "requires V060_GITLAB_TOKEN"),
    ):
        result = subprocess.run(
            ["/bin/bash", "-c", script],
            env={
                "LIVE_TIER": "release",
                "V060_GITHUB_TOKEN": github_token,
                "V060_GITLAB_TOKEN": gitlab_token,
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert expected_message in result.stderr

    pr = subprocess.run(
        ["/bin/bash", "-c", script],
        env={
            "LIVE_TIER": "pr",
            "V060_GITHUB_TOKEN": "",
            "V060_GITLAB_TOKEN": "",
        },
        capture_output=True,
        text=True,
    )
    assert pr.returncode == 0


def test_workflow_uploads_only_sanitized_summary_ledger_and_public_registry() -> None:
    body = _workflow()
    upload = body.split("Upload sanitized provider evidence only", 1)[1]
    path_block = upload.split("path: |", 1)[1].split("if-no-files-found:", 1)[0]
    uploaded_paths = [line.strip() for line in path_block.splitlines() if line.strip()]
    assert uploaded_paths == [
        "provider-live-evidence/scenario-summary.json",
        "provider-live-evidence/guard-ledger.jsonl",
        "provider-live-evidence/public-registry/",
    ]
    assert "private-resume-bundles" not in upload
    for forbidden in ("blobs", "raw", "work-root", "RUNNER_TEMP"):
        assert forbidden not in upload
    assert "if-no-files-found: error" in upload


def test_workflow_has_strict_shell_timeout_and_no_sleep() -> None:
    body = _workflow()
    assert body.count("set -euo pipefail") >= 3
    assert "timeout-minutes: 30" in body
    assert " sleep " not in body
    assert "scripts/v060_provider_live_gate.py" in body
    assert '--tier "${{ inputs.tier }}"' in body
    assert '--source-commit "${GITHUB_SHA}"' in body
    assert '--suite-deadline-epoch "${LIVE_GATE_DEADLINE_EPOCH}"' in body
    assert '[[ "$LIVE_TIER" == "pr" ]]' in body
    assert "--registry-output provider-live-evidence/public-registry" in body
    assert (
        '--partial-bundle-root "${RUNNER_TEMP}/grift-v060-provider-live/'
        'private-resume-bundles"' in body
    )
    assert "never uploads or claims cross-run" in body
    assert "--partial-bundle-root provider-live-evidence" not in body
    assert "LIVE_GATE_DEADLINE_EPOCH=$(($(date +%s) + 1680))" in body
    assert body.index("Establish the suite deadline") < body.index("actions/checkout@v4")
    assert "run_before_deadline" in body
    assert "clone_before_deadline" in body
    assert body.count("LIVE_GATE_DEADLINE_EPOCH - $(date +%s) - 120") == 3
    assert '"reason": "runner_not_completed"' in body


def test_workflow_materializes_complete_pr_and_release_source_sets() -> None:
    body = _workflow()
    for timeout, remote, name in (
        (180, "https://github.com/cloudflare/cloudflare-os.git", "cloudflare-os"),
        (600, "https://github.com/vitejs/vite.git", "vite"),
        (180, "https://gitlab.com/gitlab-org/release-cli.git", "release-cli"),
        (180, "https://github.com/VOICEVOX/voicevox.git", "voicevox"),
        (600, "https://gitlab.com/gitlab-org/cli.git", "cli"),
    ):
        assert f'clone_before_deadline {timeout} {remote} "$repo_root/{name}"' in body
    clone_block = body.split("Materialize full fixed-OID source repositories", 1)[1].split(
        "Run fixed-OID provider live gate", 1
    )[0]
    release_guard = clone_block.index('[[ "$LIVE_TIER" == "release" ]]')
    assert clone_block.index("VOICEVOX/voicevox.git") > release_guard
    assert clone_block.index("gitlab-org/cli.git") > release_guard
    assert "--depth" not in clone_block
    assert "--filter" not in clone_block


def test_live_runner_is_part_of_scenario_source_binding() -> None:
    assert "scripts/v060_provider_live_gate.py" in matrix.SOURCE_BINDING_PATHS


def _assert_publish_live_admission(body: str) -> None:
    required = (
        "provider_live_run_id:",
        "Validate successful release provider run",
        '"conclusion": "success"',
        '"head_sha": os.environ["VERIFIED_COMMIT_OID"]',
        "Download same-commit release provider evidence",
        "run-id: ${{ inputs.provider_live_run_id }}",
        "v060-provider-live-release-${{ steps.release_ref.outputs.commit_oid }}",
        "Verify same-commit release provider evidence",
        "--verify-summary provider-live-release-evidence/scenario-summary.json",
        "--verify-ledger provider-live-release-evidence/guard-ledger.jsonl",
        "--expected-tier release",
        '--expected-source-commit "$VERIFIED_COMMIT_OID"',
    )
    for marker in required:
        assert marker in body
    assert body.index("Verify same-commit release provider evidence") < body.index(
        "Publish to PyPI"
    )


def test_publish_requires_successful_same_commit_release_live_evidence() -> None:
    _assert_publish_live_admission(PUBLISH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "removed",
    [
        '"conclusion": "success"',
        '"head_sha": os.environ["VERIFIED_COMMIT_OID"]',
        "run-id: ${{ inputs.provider_live_run_id }}",
        "--expected-tier release",
        '--expected-source-commit "$VERIFIED_COMMIT_OID"',
    ],
)
def test_publish_live_admission_one_sided_mutation_is_red(removed: str) -> None:
    body = PUBLISH.read_text(encoding="utf-8")
    assert removed in body
    with pytest.raises(AssertionError):
        _assert_publish_live_admission(body.replace(removed, "removed-by-mutation", 1))
