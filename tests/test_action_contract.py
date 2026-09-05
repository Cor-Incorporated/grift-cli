"""Executable contracts for the shipped composite GitHub Action."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tep_core.version import __version__


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "action.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
README_JA = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
COMPANION_SHA = "173fac600f3ce64e6df1ca86565f427a391810cc"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _intake_job(workflow: str) -> str:
    start = workflow.index("  intake-contract-parity:\n")
    end = workflow.index("\n  exact-pr-head:\n", start)
    return workflow[start:end]


def _assert_intake_job_contract(job: str) -> None:
    sender_ref = "${{ github.event.pull_request.head.sha || github.sha }}"
    assert "if: github.event_name != 'schedule'" in job
    assert f"SENDER_SHA: {sender_ref}" in job
    assert f"COMPANION_SHA: {COMPANION_SHA}" in job
    assert f"ref: {sender_ref}" in job
    assert f"ref: {COMPANION_SHA}" in job
    assert "path: sender" in job
    assert "path: receiver" in job
    assert job.count("fetch-depth: 0") == 2
    assert job.count("persist-credentials: false") == 2
    assert "working-directory: sender" in job
    assert "--companion-root ../receiver" in job
    assert '--expected-sender-sha "$SENDER_SHA"' in job
    assert '--expected-companion-sha "$COMPANION_SHA"' in job
    assert "--require-companion-clean" in job
    assert '--result "$INTAKE_EVIDENCE/result.json"' in job
    assert '--ledger "$INTAKE_EVIDENCE/guard-ledger.jsonl"' in job
    assert "python scripts/intake_contract_parity.py" in job
    assert "under socket denial" in job
    assert "- name: Upload intake parity evidence\n        if: always()" in job
    assert "path: ${{ runner.temp }}/intake-contract-evidence/" in job
    for marker in ("H5-guard: yes", "H5-NEGATIVE:", "H5-LEDGER:", "H5-RETIRE:", "H5-PAIR:"):
        assert marker in job


def _step_run(name: str) -> str:
    """Return the exact bash body for one named composite-action step."""

    lines = _read(ACTION).splitlines()
    marker = f"    - name: {name}"
    start = lines.index(marker)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("    - name:")),
        len(lines),
    )
    run = lines.index("      run: |", start, end)
    return "\n".join(line[8:] for line in lines[run + 1 : end]) + "\n"


def _run_validation(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GRIFT_ACTION_SCOPE": "repo",
            "GRIFT_ACTION_VERSION": "0.6.0",
            "GRIFT_ACTION_INSTALL_SOURCE": "pypi",
            "GRIFT_ACTION_COMMENT": "false",
            **overrides,
        }
    )
    return subprocess.run(
        ["bash", "-c", _step_run("Validate action inputs")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"GRIFT_ACTION_SCOPE": "all"}, "scope must be one of"),
        ({"GRIFT_ACTION_VERSION": "0.6"}, "version must be an exact release"),
        ({"GRIFT_ACTION_INSTALL_SOURCE": "wheel"}, "install-source must be one of"),
        ({"GRIFT_ACTION_COMMENT": "yes"}, "comment must be one of"),
    ],
)
def test_action_rejects_inputs_outside_the_closed_contract(
    overrides: dict[str, str], message: str
) -> None:
    result = _run_validation(**overrides)
    assert result.returncode == 2
    assert message in result.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "GRIFT_ACTION_SCOPE": "tenant",
            "GRIFT_ACTION_VERSION": "12.34.56rc7",
            "GRIFT_ACTION_INSTALL_SOURCE": "checkout",
            "GRIFT_ACTION_COMMENT": "true",
        },
    ],
)
def test_action_accepts_only_documented_input_combinations(overrides: dict[str, str]) -> None:
    result = _run_validation(**overrides)
    assert result.returncode == 0, result.stderr


def test_action_inputs_are_never_interpolated_into_shell_scripts() -> None:
    action = _read(ACTION)
    run_blocks = []
    lines = action.splitlines()
    for index, line in enumerate(lines):
        if line != "      run: |":
            continue
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate and not candidate.startswith("        "):
                break
            body.append(candidate[8:] if candidate else "")
        run_blocks.append("\n".join(body))

    assert run_blocks
    assert all("${{ inputs." not in block for block in run_blocks)
    for mapping in (
        "GRIFT_ACTION_SCOPE: ${{ inputs.scope }}",
        "GRIFT_ACTION_VERSION: ${{ inputs.version }}",
        "GRIFT_ACTION_INSTALL_SOURCE: ${{ inputs.install-source }}",
        "GRIFT_ACTION_COMMENT: ${{ inputs.comment }}",
    ):
        assert mapping in action


@pytest.mark.parametrize(
    ("input_name", "payload"),
    [
        ("GRIFT_ACTION_INSTALL_SOURCE", 'pypi"; touch "{sentinel}"; #'),
        ("GRIFT_ACTION_VERSION", '0.6.0$(touch "{sentinel}")'),
    ],
)
def test_shell_metacharacters_are_rejected_without_execution(
    tmp_path: Path, input_name: str, payload: str
) -> None:
    sentinel = tmp_path / "input-was-executed"
    result = _run_validation(**{input_name: payload.format(sentinel=sentinel)})
    assert result.returncode == 2
    assert not sentinel.exists()


def test_action_uses_its_own_checkout_and_rejects_incomplete_caller_history() -> None:
    action = _read(ACTION)
    preflight = _step_run("Validate repository checkout")
    install = _step_run("Install grift-cli (pinned)")
    analyze = _step_run("Run grift analyze (observation only)")

    assert "git rev-parse --is-inside-work-tree" in preflight
    assert "git rev-parse --is-shallow-repository" in preflight
    assert "actions/checkout with fetch-depth: 0" in preflight
    assert "GRIFT_ACTION_PATH: ${{ github.action_path }}" in action
    assert 'python -m pip install --no-input "$GRIFT_ACTION_PATH"' in install
    assert "python -m pip install --no-input ." not in install
    assert "test -s .grift/shared-block.md" in analyze
    assert analyze.count("cat .grift/shared-block.md") == 1


def test_repository_preflight_accepts_complete_history_and_rejects_shallow_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "--template=", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Action Test"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "action@example.test"],
        check=True,
    )
    tracked = source / "tracked.txt"
    for value in ("one\n", "two\n"):
        tracked.write_text(value, encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", value.strip()], check=True)

    preflight = _step_run("Validate repository checkout")
    non_repository = tmp_path / "not-a-repository"
    non_repository.mkdir()
    missing = subprocess.run(
        ["bash", "-c", preflight],
        cwd=non_repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "requires the caller repository" in missing.stderr

    complete = subprocess.run(
        ["bash", "-c", preflight], cwd=source, capture_output=True, text=True, check=False
    )
    assert complete.returncode == 0, complete.stderr

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", source.as_uri(), str(shallow)], check=True
    )
    rejected = subprocess.run(
        ["bash", "-c", preflight], cwd=shallow, capture_output=True, text=True, check=False
    )
    assert rejected.returncode == 2
    assert "requires complete history" in rejected.stderr


def test_ci_dogfoods_the_real_action_without_write_credentials() -> None:
    workflow = _read(CI)
    start = workflow.index("  action-dogfood:\n")
    end = workflow.index("\n  package-smoke:\n", start)
    job = workflow[start:end]
    normalized_job = " ".join(job.split())

    assert "permissions:\n      contents: read" in job
    assert "pull-requests: write" not in job
    assert "persist-credentials: false" in job
    assert "uses: ./" in job
    assert "install-source: checkout" in job
    assert "comment: false" in job
    assert "grift analyze" not in job
    assert "python scripts/action_contract_guard.py" in normalized_job
    assert "--ledger action-evidence/guard-ledger.jsonl" in normalized_job
    assert "RETIRE: remove the local input guard only after 3 consecutive" in job
    assert "- name: Upload action guard evidence\n        if: always()" in job
    assert "path: action-evidence/guard-ledger.jsonl" in job
    for artifact in (".grift/report.md", ".grift/report.json", ".grift/shared-block.md"):
        assert artifact in job


def test_ci_keeps_merge_ref_and_exact_pr_head_as_separate_gates() -> None:
    workflow = _read(CI)
    assert "permissions:\n  contents: read" in workflow
    start = workflow.index("  exact-pr-head:\n")
    end = workflow.index("\n  golden:\n", start)
    job = workflow[start:end]
    normalized_job = " ".join(job.split())

    assert "if: github.event_name == 'pull_request'" in job
    assert "ref: ${{ github.event.pull_request.head.sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$actual_head_sha" = "$EXPECTED_HEAD_SHA"' in job
    assert 'python -m pytest tests -m "not golden"' in job
    assert 'joinpath("head.json")' in job
    assert "Upload exact-head evidence" in normalized_job
    assert 'collection="$EXACT_HEAD_EVIDENCE/self-analysis"' in job
    assert "grift repo ." in job
    assert '--rev "$EXPECTED_HEAD_SHA"' in job
    assert "--actors" in job
    assert 'grift verify "$collection" --repo .' in job
    assert 'manifest["target"]["oid"]["value"]' in job
    assert 'index["population"]["actor_count"]' in job
    assert "manifest_sha256" in job
    assert "path: ${{ runner.temp }}/exact-head-evidence/" in job


def test_ci_runs_real_intake_contract_at_two_immutable_sibling_checkouts() -> None:
    _assert_intake_job_contract(_intake_job(_read(CI)))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            "ref: main",
        ),
        (f"ref: {COMPANION_SHA}", "ref: main"),
        ("path: receiver", "path: sender"),
        ("fetch-depth: 0", "fetch-depth: 1"),
        ("if: always()", "if: success()"),
        ('--expected-sender-sha "$SENDER_SHA"', "--sender-unbound"),
        ('--expected-companion-sha "$COMPANION_SHA"', "--receiver-unbound"),
        ("python scripts/intake_contract_parity.py", "echo parity-skipped"),
        ("# H5-PAIR:", "# PAIR-REMOVED:"),
    ],
)
def test_intake_ci_contract_rejects_one_sided_workflow_mutations(
    before: str,
    after: str,
) -> None:
    job = _intake_job(_read(CI))
    assert before in job
    mutated = job.replace(before, after, 1)
    with pytest.raises(AssertionError):
        _assert_intake_job_contract(mutated)


@pytest.mark.parametrize("readme", [README_JA, README_EN])
def test_readme_action_example_is_read_only_and_uses_complete_history(
    readme: Path,
) -> None:
    content = _read(readme)
    start = content.index(f"uses: Cor-Incorporated/grift-cli@v{__version__}")
    snippet_start = content.rfind("```yaml", 0, start)
    snippet_end = content.index("```", start)
    snippet = content[snippet_start:snippet_end]

    checkout = snippet.index("uses: actions/checkout@v4")
    setup_python = snippet.index("uses: actions/setup-python@v5")
    grift = snippet.index(f"uses: Cor-Incorporated/grift-cli@v{__version__}")
    assert checkout < setup_python < grift
    assert "permissions:\n  contents: read" in snippet
    assert "fetch-depth: 0" in snippet
    assert "persist-credentials: false" in snippet
    assert 'python-version: "3.12"' in snippet
    assert "comment: false" in snippet

    section_end = content.find("\n## ", snippet_end)
    section = content[snippet_end : section_end if section_end != -1 else None]
    assert "3.11" in section
    assert "fail-closed" in section
    assert "comment: true" in section
    assert "write" in section


def test_ci_describes_only_the_action_paths_it_executes() -> None:
    workflow = _read(CI)
    start = workflow.index("  action-dogfood:\n")
    end = workflow.index("\n  package-smoke:\n", start)
    job = workflow[start:end]

    assert "Read-only proof boundary" in job
    assert "not prove the PyPI install or PR-comment paths" in job
    assert "comment: false" in job


def test_guard_runner_emits_negative_and_pair_mutation_evidence(tmp_path: Path) -> None:
    ledger = tmp_path / "guard-ledger.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "action_contract_guard.py"),
            "--ledger",
            str(ledger),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert {record["case"] for record in records} == {
        "valid-defaults",
        "declaration-enforcement-pair",
        "malicious-install-source",
        "malicious-version",
        "declaration-only-mutation",
        "enforcement-only-mutation",
        "default-only-mutation",
        "checkout-install-mutation",
        "pypi-install-mutation",
        "scope-env-mutation",
        "analysis-command-mutation",
        "shallow-preflight-mutation",
    }
    assert all(record["status"] == "PASS" for record in records)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('default: "pypi"', 'default: "wheel"'),
        (
            'python -m pip install --no-input "$GRIFT_ACTION_PATH"',
            "python -m pip install --no-input .",
        ),
        (
            'python -m pip install --no-input "grift-cli==$GRIFT_ACTION_VERSION"',
            'echo "install skipped"',
        ),
        ("GRIFT_SCOPE: ${{ inputs.scope }}", "GRIFT_SCOPE: repo"),
        (
            'grift analyze . --scope "$GRIFT_SCOPE" --format both --out .grift',
            "grift analyze . --scope repo --format both --out .grift",
        ),
    ],
)
def test_guard_fails_closed_on_one_sided_contract_mutations(
    tmp_path: Path,
    before: str,
    after: str,
) -> None:
    source = _read(ACTION)
    assert source.count(before) == 1
    mutated = tmp_path / "action.yml"
    mutated.write_text(source.replace(before, after, 1), encoding="utf-8")
    ledger = tmp_path / "guard-ledger.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "action_contract_guard.py"),
            "--action",
            str(mutated),
            "--ledger",
            str(ledger),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert any(record["status"] == "FAIL" for record in records)
