#!/usr/bin/env python3
"""Falsify the composite-action input guard and emit a durable JSONL ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INSTALL_SOURCES = {"checkout", "pypi"}
def _declared_version() -> str:
    """Read the release version from the SSOT file inside this checkout.

    Read rather than imported: an editable install can put a different checkout's
    ``tep_core`` on the path, and this guard must compare ``action.yml`` against
    the version declared beside it. A retyped literal would report drift on every
    release bump against the very value it is meant to pin.
    """

    source = (ROOT / "src" / "tep_core" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if match is None:
        raise SystemExit("version.py does not declare __version__")
    return match.group(1)


EXPECTED_INPUT_DEFAULTS = {
    "GRIFT_ACTION_SCOPE": "repo",
    "GRIFT_ACTION_VERSION": _declared_version(),
    "GRIFT_ACTION_INSTALL_SOURCE": "pypi",
    "GRIFT_ACTION_COMMENT": "false",
}


def _step_block(action: str, name: str) -> str:
    lines = action.splitlines()
    marker = f"    - name: {name}"
    start = lines.index(marker)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("    - name:")),
        len(lines),
    )
    return "\n".join(lines[start:end]) + "\n"


def _step_run(action: str, name: str) -> str:
    lines = _step_block(action, name).splitlines()
    run = lines.index("      run: |")
    return "\n".join(line[8:] for line in lines[run + 1 :]) + "\n"


def _input_block(action: str, name: str) -> str:
    lines = action.splitlines()
    marker = f"  {name}:"
    start = lines.index(marker)
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[index])
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _input_defaults(action: str) -> dict[str, str]:
    mapping = {
        "scope": "GRIFT_ACTION_SCOPE",
        "version": "GRIFT_ACTION_VERSION",
        "install-source": "GRIFT_ACTION_INSTALL_SOURCE",
        "comment": "GRIFT_ACTION_COMMENT",
    }
    defaults: dict[str, str] = {}
    for input_name, environment_name in mapping.items():
        block = _input_block(action, input_name)
        match = re.search(r'^    default: "([^"]*)"$', block, re.MULTILINE)
        if match is None:
            raise ValueError(f"{input_name} input default is missing or malformed")
        defaults[environment_name] = match.group(1)
    return defaults


def _pair_errors(action: str) -> list[str]:
    declaration = _input_block(action, "install-source")
    declared = set(re.findall(r"'([a-z][a-z0-9-]*)'", declaration))

    validation = _step_run(action, "Validate action inputs")
    case = re.search(
        r'case "\$GRIFT_ACTION_INSTALL_SOURCE" in(?P<body>.*?)\n\s*esac',
        validation,
        re.DOTALL,
    )
    if case is None:
        return ["install-source enforcement case is missing"]
    allowlist = re.search(
        r"^\s+([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)+)\) ;;\s*$",
        case.group("body"),
        re.MULTILINE,
    )
    if allowlist is None:
        return ["install-source enforcement allowlist is missing"]
    enforced = set(allowlist.group(1).split("|"))

    errors = []
    if declared != EXPECTED_INSTALL_SOURCES:
        errors.append(f"declared install sources drifted: {sorted(declared)}")
    if enforced != EXPECTED_INSTALL_SOURCES:
        errors.append(f"enforced install sources drifted: {sorted(enforced)}")
    if declared != enforced:
        errors.append(
            f"declaration/enforcement mismatch: declared={sorted(declared)} "
            f"enforced={sorted(enforced)}"
        )
    return errors


def _wiring_errors(action: str) -> list[str]:
    errors: list[str] = []
    try:
        defaults = _input_defaults(action)
    except (ValueError, IndexError) as exc:
        errors.append(str(exc))
    else:
        if defaults != EXPECTED_INPUT_DEFAULTS:
            errors.append(f"input defaults drifted: {defaults}")

    validation_block = _step_block(action, "Validate action inputs")
    for mapping in (
        "GRIFT_ACTION_SCOPE: ${{ inputs.scope }}",
        "GRIFT_ACTION_VERSION: ${{ inputs.version }}",
        "GRIFT_ACTION_INSTALL_SOURCE: ${{ inputs.install-source }}",
        "GRIFT_ACTION_COMMENT: ${{ inputs.comment }}",
    ):
        if mapping not in validation_block:
            errors.append(f"validation input wiring is missing: {mapping}")

    preflight = _step_run(action, "Validate repository checkout")
    for command in (
        "git rev-parse --is-inside-work-tree",
        "git rev-parse --is-shallow-repository",
        "actions/checkout with fetch-depth: 0",
    ):
        if command not in preflight:
            errors.append(f"repository preflight is missing: {command}")

    install_block = _step_block(action, "Install grift-cli (pinned)")
    install_run = _step_run(action, "Install grift-cli (pinned)")
    for mapping in (
        "GRIFT_ACTION_VERSION: ${{ inputs.version }}",
        "GRIFT_ACTION_INSTALL_SOURCE: ${{ inputs.install-source }}",
        "GRIFT_ACTION_PATH: ${{ github.action_path }}",
    ):
        if mapping not in install_block:
            errors.append(f"install input wiring is missing: {mapping}")
    for command in (
        'python -m pip install --no-input "$GRIFT_ACTION_PATH"',
        'python -m pip install --no-input "grift-cli==$GRIFT_ACTION_VERSION"',
    ):
        if command not in install_run:
            errors.append(f"install enforcement is missing: {command}")
    if "python -m pip install --no-input ." in install_run:
        errors.append("checkout install must not resolve against the caller workspace")

    analyze_block = _step_block(action, "Run grift analyze (observation only)")
    analyze_run = _step_run(action, "Run grift analyze (observation only)")
    if "GRIFT_SCOPE: ${{ inputs.scope }}" not in analyze_block:
        errors.append("analysis scope input wiring is missing")
    for command in (
        'grift analyze . --scope "$GRIFT_SCOPE" --format both --out .grift',
        "test -s .grift/shared-block.md",
    ):
        if command not in analyze_run:
            errors.append(f"analysis enforcement is missing: {command}")
    if analyze_run.count("cat .grift/shared-block.md") != 1:
        errors.append("shared block must be appended to the summary exactly once")
    return errors


def _contract_errors(action: str) -> list[str]:
    return [*_pair_errors(action), *_wiring_errors(action)]


def _run_validation(
    script: str,
    defaults: dict[str, str],
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(defaults)
    env.update(overrides)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _record(case: str, expected: str, observed: str, passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "grift-action-guard-v1",
        "guard": "action-input-contract",
        "case": case,
        "expected": expected,
        "observed": observed,
        "status": "PASS" if passed else "FAIL",
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def _evaluate(action: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    validation = _step_run(action, "Validate action inputs")
    defaults = _input_defaults(action)

    valid = _run_validation(validation, defaults)
    records.append(
        _record("valid-defaults", "exit 0", f"exit {valid.returncode}", valid.returncode == 0)
    )

    pair_errors = _contract_errors(action)
    records.append(
        _record(
            "declaration-enforcement-pair",
            "metadata, validation, install, preflight, and analysis wiring match",
            "matched" if not pair_errors else "; ".join(pair_errors),
            not pair_errors,
        )
    )

    with tempfile.TemporaryDirectory(prefix="grift-action-guard-") as temporary:
        sentinel = Path(temporary) / "shell-injection-sentinel"
        malicious_cases = (
            (
                "malicious-install-source",
                {"GRIFT_ACTION_INSTALL_SOURCE": f'pypi"; touch "{sentinel}"; #'},
            ),
            (
                "malicious-version",
                {"GRIFT_ACTION_VERSION": f'0.6.0$(touch "{sentinel}")'},
            ),
        )
        for case_name, override in malicious_cases:
            sentinel.unlink(missing_ok=True)
            result = _run_validation(validation, defaults, **override)
            passed = result.returncode == 2 and not sentinel.exists()
            records.append(
                _record(
                    case_name,
                    "exit 2 and no shell side effect",
                    f"exit {result.returncode}; side_effect={sentinel.exists()}",
                    passed,
                )
            )

    declaration_mutation = action.replace(
        "'checkout' (install this action's immutable source checkout",
        "'checkout' or 'wheel' (install this action's immutable source checkout",
        1,
    )
    declaration_detected = declaration_mutation != action and bool(
        _contract_errors(declaration_mutation)
    )
    records.append(
        _record(
            "declaration-only-mutation",
            "guard rejects a declaration-only wheel addition",
            "rejected" if declaration_detected else "accepted",
            declaration_detected,
        )
    )

    enforcement_mutation = action.replace("pypi|checkout) ;;", "pypi|checkout|wheel) ;;", 1)
    enforcement_detected = enforcement_mutation != action and bool(
        _contract_errors(enforcement_mutation)
    )
    records.append(
        _record(
            "enforcement-only-mutation",
            "guard rejects an enforcement-only wheel addition",
            "rejected" if enforcement_detected else "accepted",
            enforcement_detected,
        )
    )

    mutations = (
        (
            "default-only-mutation",
            'default: "pypi"',
            'default: "wheel"',
            "guard rejects an undeclared metadata default",
        ),
        (
            "checkout-install-mutation",
            'python -m pip install --no-input "$GRIFT_ACTION_PATH"',
            "python -m pip install --no-input .",
            "guard rejects caller-workspace installation",
        ),
        (
            "pypi-install-mutation",
            'python -m pip install --no-input "grift-cli==$GRIFT_ACTION_VERSION"',
            'echo "pypi install skipped"',
            "guard rejects a missing pinned PyPI install",
        ),
        (
            "scope-env-mutation",
            "GRIFT_SCOPE: ${{ inputs.scope }}",
            "GRIFT_SCOPE: repo",
            "guard rejects analysis scope wiring drift",
        ),
        (
            "analysis-command-mutation",
            'grift analyze . --scope "$GRIFT_SCOPE" --format both --out .grift',
            "grift analyze . --scope repo --format both --out .grift",
            "guard rejects analysis command wiring drift",
        ),
        (
            "shallow-preflight-mutation",
            "git rev-parse --is-shallow-repository",
            "git rev-parse --show-toplevel",
            "guard rejects removal of the complete-history preflight",
        ),
    )
    for case_name, before, after, expected in mutations:
        mutation = action.replace(before, after, 1)
        detected = mutation != action and bool(_contract_errors(mutation))
        records.append(
            _record(
                case_name,
                expected,
                "rejected" if detected else "accepted",
                detected,
            )
        )
    return records


def _write_ledger(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    path.write_text(serialized, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", type=Path, default=ROOT / "action.yml")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=ROOT / "action-evidence" / "guard-ledger.jsonl",
    )
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    try:
        records = _evaluate(args.action.read_text(encoding="utf-8"))
    except Exception as exc:  # keep a durable failure record for the always-upload step
        records.append(
            _record(
                "guard-runner",
                "runner succeeds",
                f"{type(exc).__name__}: {exc}",
                False,
            )
        )
    finally:
        _write_ledger(args.ledger, records)

    passed = sum(record["status"] == "PASS" for record in records)
    print(f"action-contract-guard: {passed}/{len(records)} PASS; ledger={args.ledger}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
