from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import shlex
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "grift_package_smoke", Path(__file__).resolve().parents[1] / "scripts" / "package_smoke.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_PACKAGE_SMOKE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PACKAGE_SMOKE)
PackageContractError = _PACKAGE_SMOKE.PackageContractError
inspect_distribution = _PACKAGE_SMOKE.inspect_distribution
negative_guard_probe = _PACKAGE_SMOKE._negative_guard_probe
assert_required_members = _PACKAGE_SMOKE._assert_required_members
cleanup_sentinels = _PACKAGE_SMOKE._cleanup_sentinels
dirty_sentinels = _PACKAGE_SMOKE._dirty_sentinels
local_machine_path_violations = _PACKAGE_SMOKE._local_machine_path_violations
runtime_env = _PACKAGE_SMOKE._runtime_env
source_binding = _PACKAGE_SMOKE._source_binding
tracked_inventory_violations = _PACKAGE_SMOKE._tracked_inventory_violations


@dataclass(frozen=True)
class _RunBlock:
    job_name: str
    start_line: int
    end_line: int
    body_lines: tuple[tuple[int, str], ...]
    env: tuple[tuple[str, str], ...] = ()
    condition: str | None = None


@dataclass(frozen=True)
class _ActionStep:
    start_line: int
    end_line: int
    uses: str
    with_values: tuple[tuple[str, str], ...]
    env: tuple[tuple[str, str], ...] = ()
    condition: str | None = None


@dataclass(frozen=True)
class _WorkflowJob:
    needs: frozenset[str]
    runs: tuple[_RunBlock, ...]
    uses: tuple[str, ...]
    actions: tuple[_ActionStep, ...]


@dataclass(frozen=True)
class _WorkflowSubset:
    triggers: frozenset[str]
    dispatch_inputs: dict[str, dict[str, str]]
    jobs: dict[str, _WorkflowJob]


@dataclass(frozen=True)
class _ShellCommand:
    text: str
    source_lines: tuple[int, ...]


_Matcher = Callable[[_ShellCommand], bool]


def _strip_unquoted_comment(value: str) -> str:
    """Remove a YAML/shell comment without treating quoted ``#`` as syntax."""

    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote == '"':
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def _yaml_line(line: str) -> tuple[int, str] | None:
    prefix = line[: len(line) - len(line.lstrip(" \t"))]
    if "\t" in prefix:
        raise ValueError("workflow indentation must not contain tabs")
    content = line[len(prefix) :]
    if not content or content.startswith("#"):
        return None
    content = _strip_unquoted_comment(content)
    if not content:
        return None
    return len(prefix), content


def _mapping_entry(content: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"([A-Za-z0-9_.-]+):(?:\s*(.*))?", content)
    if match is None:
        return None
    return match.group(1), (match.group(2) or "").strip()


def _scalar_items(value: str) -> frozenset[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if not value:
        return frozenset()
    return frozenset(item.strip().strip("'\"") for item in value.split(",") if item.strip())


def _workflow_triggers(lines: list[str]) -> frozenset[str]:
    for index, line in enumerate(lines):
        parsed = _yaml_line(line)
        if parsed is None or parsed[0] != 0:
            continue
        entry = _mapping_entry(parsed[1])
        if entry is None or entry[0] != "on":
            continue
        if entry[1]:
            return _scalar_items(entry[1])
        triggers: set[str] = set()
        child_indent: int | None = None
        for nested in lines[index + 1 :]:
            nested_parsed = _yaml_line(nested)
            if nested_parsed is None:
                continue
            indent, content = nested_parsed
            if indent == 0:
                break
            if child_indent is None:
                child_indent = indent
            if indent != child_indent:
                continue
            nested_entry = _mapping_entry(content)
            if nested_entry is not None:
                triggers.add(nested_entry[0])
        return frozenset(triggers)
    raise ValueError("workflow has no top-level on mapping")


def _workflow_dispatch_inputs(lines: list[str]) -> dict[str, dict[str, str]]:
    """Extract the scalar ``workflow_dispatch.inputs`` subset used by releases."""

    on_index: int | None = None
    on_indent = 0
    for index, line in enumerate(lines):
        parsed = _yaml_line(line)
        if parsed is None or parsed[0] != 0:
            continue
        entry = _mapping_entry(parsed[1])
        if entry is not None and entry[0] == "on" and not entry[1]:
            on_index = index
            break
    if on_index is None:
        return {}

    dispatch_index: int | None = None
    dispatch_indent: int | None = None
    for index in range(on_index + 1, len(lines)):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if indent <= on_indent:
            break
        entry = _mapping_entry(content)
        if entry is not None and entry[0] == "workflow_dispatch" and not entry[1]:
            dispatch_index = index
            dispatch_indent = indent
            break
    if dispatch_index is None or dispatch_indent is None:
        return {}

    inputs_index: int | None = None
    inputs_indent: int | None = None
    for index in range(dispatch_index + 1, len(lines)):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if indent <= dispatch_indent:
            break
        entry = _mapping_entry(content)
        if entry is not None and entry[0] == "inputs" and not entry[1]:
            inputs_index = index
            inputs_indent = indent
            break
    if inputs_index is None or inputs_indent is None:
        return {}

    inputs: dict[str, dict[str, str]] = {}
    input_indent: int | None = None
    current: str | None = None
    for index in range(inputs_index + 1, len(lines)):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if indent <= inputs_indent:
            break
        entry = _mapping_entry(content)
        if entry is None:
            continue
        if input_indent is None:
            input_indent = indent
        if indent == input_indent and not entry[1]:
            if entry[0] in inputs:
                raise ValueError(f"workflow_dispatch has duplicate input {entry[0]}")
            current = entry[0]
            inputs[current] = {}
            continue
        if current is not None and indent > input_indent and entry[1]:
            inputs[current][entry[0]] = entry[1].strip().strip("'\"")
    return inputs


def _block_body(
    lines: list[str], *, run_line: int, run_indent: int, value: str
) -> tuple[_RunBlock, int]:
    if not re.fullmatch(r"[|>][+-]?", value):
        return (
            _RunBlock(
                job_name="",
                start_line=run_line,
                end_line=run_line + 1,
                body_lines=((run_line, value.strip().strip("'\"")),),
            ),
            run_line + 1,
        )
    end = run_line + 1
    while end < len(lines):
        parsed = _yaml_line(lines[end])
        if parsed is not None and parsed[0] <= run_indent:
            break
        end += 1
    body_candidates = lines[run_line + 1 : end]
    content_indents = [
        len(line) - len(line.lstrip(" "))
        for line in body_candidates
        if line.strip() and not line.lstrip().startswith("#")
    ]
    content_indent = min(content_indents, default=run_indent + 2)
    body_lines = tuple(
        (line_number, raw[content_indent:] if len(raw) >= content_indent else "")
        for line_number, raw in enumerate(
            body_candidates,
            start=run_line + 1,
        )
    )
    return (
        _RunBlock(
            job_name="",
            start_line=run_line,
            end_line=end,
            body_lines=body_lines,
        ),
        end,
    )


def _enclosing_step_bounds(
    lines: list[str],
    *,
    line_index: int,
    job_end: int,
    steps_indent: int,
) -> tuple[int, int, int]:
    """Return ``(start, end, indent)`` for the step containing ``line_index``."""

    step_indent = steps_indent + 2
    start: int | None = None
    for candidate in range(line_index, -1, -1):
        parsed = _yaml_line(lines[candidate])
        if parsed is None:
            continue
        indent, content = parsed
        if indent < step_indent:
            break
        if indent == step_indent and content.startswith("- "):
            start = candidate
            break
    if start is None:
        raise ValueError(f"workflow step has no list item near line {line_index + 1}")
    end = job_end
    for candidate in range(start + 1, job_end):
        parsed = _yaml_line(lines[candidate])
        if parsed is None:
            continue
        indent, content = parsed
        if indent <= steps_indent or (indent == step_indent and content.startswith("- ")):
            end = candidate
            break
    return start, end, step_indent


def _step_scalar_mapping(
    lines: list[str],
    *,
    start: int,
    end: int,
    step_indent: int,
    key: str,
) -> tuple[tuple[str, str], ...]:
    """Extract a scalar mapping nested directly below one workflow step key."""

    key_indent = step_indent + 2
    key_index: int | None = None
    for index in range(start, end):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if index == start and content.startswith("- "):
            content = content[2:].lstrip()
        entry = _mapping_entry(content)
        if indent in {step_indent, key_indent} and entry == (key, ""):
            key_index = index
            key_indent = indent
            break
    if key_index is None:
        return ()
    values: list[tuple[str, str]] = []
    names: set[str] = set()
    value_indent: int | None = None
    for index in range(key_index + 1, end):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if indent <= key_indent:
            break
        if value_indent is None:
            value_indent = indent
        if indent != value_indent:
            continue
        entry = _mapping_entry(content)
        if entry is not None and entry[1]:
            if entry[0] in names:
                raise ValueError(f"workflow step has duplicate {key}.{entry[0]}")
            names.add(entry[0])
            values.append((entry[0], entry[1].strip().strip("'\"")))
    return tuple(values)


def _step_condition(lines: list[str], *, start: int, end: int, step_indent: int) -> str | None:
    for index in range(start, end):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if index == start and content.startswith("- "):
            content = content[2:].lstrip()
        entry = _mapping_entry(content)
        if indent in {step_indent, step_indent + 2} and entry is not None and entry[0] == "if":
            return entry[1].strip().strip("'\"")
    return None


def _parse_job(
    lines: list[str], *, name: str, start: int, end: int, job_indent: int
) -> _WorkflowJob:
    needs: set[str] = set()
    runs: list[_RunBlock] = []
    uses: list[str] = []
    actions: list[_ActionStep] = []
    steps_indent: int | None = None
    index = start + 1
    while index < end:
        parsed = _yaml_line(lines[index])
        if parsed is None:
            index += 1
            continue
        indent, content = parsed
        entry = _mapping_entry(content)
        if indent == job_indent + 2 and entry is not None and entry[0] == "needs":
            if entry[1]:
                needs.update(_scalar_items(entry[1]))
            else:
                nested = index + 1
                while nested < end:
                    nested_parsed = _yaml_line(lines[nested])
                    if nested_parsed is None:
                        nested += 1
                        continue
                    if nested_parsed[0] <= indent:
                        break
                    item = nested_parsed[1]
                    if item.startswith("- "):
                        needs.add(item[2:].strip().strip("'\""))
                    nested += 1
        if indent == job_indent + 2 and entry is not None and entry[0] == "steps":
            steps_indent = indent
            index += 1
            continue
        if steps_indent is None or indent <= steps_indent:
            index += 1
            continue
        uses_match = re.fullmatch(r"(?:-\s*)?uses:\s*(\S+)", content)
        if uses_match is not None:
            use = uses_match.group(1).strip("'\"")
            uses.append(use)
            step_start, step_end, step_indent = _enclosing_step_bounds(
                lines,
                line_index=index,
                job_end=end,
                steps_indent=steps_indent,
            )
            actions.append(
                _ActionStep(
                    start_line=step_start,
                    end_line=step_end,
                    uses=use,
                    with_values=_step_scalar_mapping(
                        lines,
                        start=step_start,
                        end=step_end,
                        step_indent=step_indent,
                        key="with",
                    ),
                    env=_step_scalar_mapping(
                        lines,
                        start=step_start,
                        end=step_end,
                        step_indent=step_indent,
                        key="env",
                    ),
                    condition=_step_condition(
                        lines,
                        start=step_start,
                        end=step_end,
                        step_indent=step_indent,
                    ),
                )
            )
            index += 1
            continue
        run_match = re.fullmatch(r"(?:-\s*)?run:\s*(.*)", content)
        if run_match is None:
            index += 1
            continue
        block, next_index = _block_body(
            lines,
            run_line=index,
            run_indent=indent,
            value=run_match.group(1),
        )
        step_start, step_end, step_indent = _enclosing_step_bounds(
            lines,
            line_index=index,
            job_end=end,
            steps_indent=steps_indent,
        )
        runs.append(
            _RunBlock(
                job_name=name,
                start_line=block.start_line,
                end_line=block.end_line,
                body_lines=block.body_lines,
                env=_step_scalar_mapping(
                    lines,
                    start=step_start,
                    end=step_end,
                    step_indent=step_indent,
                    key="env",
                ),
                condition=_step_condition(
                    lines,
                    start=step_start,
                    end=step_end,
                    step_indent=step_indent,
                ),
            )
        )
        index = next_index
    return _WorkflowJob(
        needs=frozenset(needs),
        runs=tuple(runs),
        uses=tuple(uses),
        actions=tuple(actions),
    )


def _parse_workflow_subset(text: str) -> _WorkflowSubset:
    lines = text.splitlines()
    jobs_index: int | None = None
    for index, line in enumerate(lines):
        parsed = _yaml_line(line)
        if parsed == (0, "jobs:"):
            jobs_index = index
            break
    if jobs_index is None:
        raise ValueError("workflow has no top-level jobs mapping")
    job_headers: list[tuple[int, int, str]] = []
    job_indent: int | None = None
    for index in range(jobs_index + 1, len(lines)):
        parsed = _yaml_line(lines[index])
        if parsed is None:
            continue
        indent, content = parsed
        if indent == 0:
            break
        if job_indent is None:
            job_indent = indent
        if indent != job_indent:
            continue
        entry = _mapping_entry(content)
        if entry is not None and not entry[1]:
            job_headers.append((index, indent, entry[0]))
    if not job_headers:
        raise ValueError("workflow has no jobs")
    jobs: dict[str, _WorkflowJob] = {}
    for position, (start, indent, name) in enumerate(job_headers):
        if name in jobs:
            raise ValueError(f"workflow has duplicate job {name}")
        end = job_headers[position + 1][0] if position + 1 < len(job_headers) else len(lines)
        jobs[name] = _parse_job(
            lines,
            name=name,
            start=start,
            end=end,
            job_indent=indent,
        )
    return _WorkflowSubset(
        triggers=_workflow_triggers(lines),
        dispatch_inputs=_workflow_dispatch_inputs(lines),
        jobs=jobs,
    )


def _shell_commands(block: _RunBlock) -> tuple[_ShellCommand, ...]:
    commands: list[_ShellCommand] = []
    pending: list[str] = []
    source_lines: list[int] = []
    heredoc_delimiter: str | None = None
    for line_number, raw in block.body_lines:
        if heredoc_delimiter is not None:
            if raw.strip() == heredoc_delimiter:
                heredoc_delimiter = None
            continue
        active = _strip_unquoted_comment(raw).strip()
        if not active:
            continue
        pending.append(active[:-1].rstrip() if active.endswith("\\") else active)
        source_lines.append(line_number)
        if active.endswith("\\"):
            continue
        command = _ShellCommand(
            text=" ".join(part for part in pending if part),
            source_lines=tuple(source_lines),
        )
        commands.append(command)
        heredoc_delimiter = _heredoc_delimiter(command)
        pending = []
        source_lines = []
    if pending:
        commands.append(
            _ShellCommand(
                text=" ".join(part for part in pending if part),
                source_lines=tuple(source_lines),
            )
        )
    return tuple(commands)


def _heredoc_delimiter(command: _ShellCommand) -> str | None:
    match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", command.text)
    return None if match is None else match.group(2)


def _heredoc_payload(block: _RunBlock, command: _ShellCommand) -> str | None:
    delimiter = _heredoc_delimiter(command)
    if delimiter is None:
        return None
    line_numbers = [line_number for line_number, _raw in block.body_lines]
    try:
        start = line_numbers.index(command.source_lines[-1]) + 1
    except ValueError:
        return None
    payload: list[str] = []
    for _line_number, raw in block.body_lines[start:]:
        if raw.strip() == delimiter:
            return "\n".join(payload) + "\n"
        payload.append(raw)
    return None


def _tokens(command: _ShellCommand) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command.text, comments=False, posix=True))
    except ValueError:
        return ()


def _is_noop_or_masked(command: _ShellCommand) -> bool:
    return bool(re.search(r"(?:^|\s)(?:\|\||;\s*(?:true|:)(?:\s|$)|&\s*$)", command.text))


def _python_script_matcher(
    script: str,
    *,
    required: tuple[str, ...] = (),
    required_options: tuple[tuple[str, str], ...] = (),
    forbidden: tuple[str, ...] = (),
) -> _Matcher:
    def option_values(tokens: tuple[str, ...], option: str) -> list[str | None]:
        values: list[str | None] = []
        for index, token in enumerate(tokens):
            if token == option:
                values.append(tokens[index + 1] if index + 1 < len(tokens) else None)
            elif token.startswith(option + "="):
                values.append(token.removeprefix(option + "="))
        return values

    def matches(command: _ShellCommand) -> bool:
        tokens = _tokens(command)
        return (
            len(tokens) >= 2
            and tokens[0] in {"python", "python3"}
            and tokens[1] == script
            and all(item in tokens for item in required)
            and all(option_values(tokens, option) == [value] for option, value in required_options)
            and all(not option_values(tokens, item) for item in forbidden)
            and not _is_noop_or_masked(command)
        )

    return matches


def _pytest_matcher(command: _ShellCommand) -> bool:
    tokens = _tokens(command)
    return (
        len(tokens) >= 4
        and tokens[:3] in {("python", "-m", "pytest"), ("python3", "-m", "pytest")}
        and "tests" in tokens
        and "not golden" in tokens
        and not _is_noop_or_masked(command)
    )


def _annotated_tag_matcher(command: _ShellCommand) -> bool:
    return (
        command.text.startswith("test ")
        and "git cat-file -t" in command.text
        and "refs/tags/$RELEASE_TAG" in command.text
        and command.text.endswith("= tag")
        and not _is_noop_or_masked(command)
    )


def _find_commands(
    job: _WorkflowJob, matcher: _Matcher
) -> list[tuple[_RunBlock, int, _ShellCommand]]:
    found: list[tuple[_RunBlock, int, _ShellCommand]] = []
    for block in job.runs:
        for index, command in enumerate(_shell_commands(block)):
            if matcher(command):
                found.append((block, index, command))
    return found


def _strict_mode_precedes(block: _RunBlock, command_index: int) -> bool:
    commands = _shell_commands(block)
    return any(
        _tokens(command) == ("set", "-euo", "pipefail") for command in commands[:command_index]
    )


def _require_enforced_command(
    errors: list[str],
    *,
    job: _WorkflowJob | None,
    job_name: str,
    label: str,
    matcher: _Matcher,
) -> None:
    if job is None:
        errors.append(f"missing job {job_name}")
        return
    matches = _find_commands(job, matcher)
    if not matches:
        errors.append(f"{job_name}: missing executable {label} command")
        return
    unconditional = [match for match in matches if match[0].condition is None]
    if not unconditional:
        errors.append(f"{job_name}: {label} must not be guarded by a step condition")
        return
    if not any(_strict_mode_precedes(block, index) for block, index, _ in unconditional):
        errors.append(f"{job_name}: {label} must follow set -euo pipefail in the same run block")


_CI_GOLDEN = _python_script_matcher(
    "scripts/v060_golden.py",
    required=("--result", "golden-evidence/v060-golden-result.json"),
)
_CI_PACKAGE_SMOKE = _python_script_matcher(
    "scripts/package_smoke.py",
    required_options=(
        ("--out", "package-dist"),
        ("--ledger", "package-evidence/guard-ledger.jsonl"),
    ),
    forbidden=("--root", "--skip-install"),
)
_CI_PUBLIC_SCENARIO = _python_script_matcher(
    "scripts/v060_scenario_matrix.py",
    required=(
        "--verify-registry",
        "--digest-only",
        "--output-root",
        "evidence/v060/scenarios-public",
    ),
)


def _ci_admission_errors(text: str) -> list[str]:
    try:
        workflow = _parse_workflow_subset(text)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    requirements = (
        ("v060-golden", "v0.6 golden", _CI_GOLDEN),
        ("v060-golden", "public scenario registry", _CI_PUBLIC_SCENARIO),
        ("package-smoke", "package smoke", _CI_PACKAGE_SMOKE),
    )
    for job_name, label, matcher in requirements:
        _require_enforced_command(
            errors,
            job=workflow.jobs.get(job_name),
            job_name=job_name,
            label=label,
            matcher=matcher,
        )
    return errors


_SCENARIO_LOCAL = _python_script_matcher(
    "scripts/v060_scenario_matrix.py",
    required=("--verify-registry",),
    forbidden=("--output-root",),
)
_SCENARIO_PUBLIC = _python_script_matcher(
    "scripts/v060_scenario_matrix.py",
    required=(
        "--verify-registry",
        "--digest-only",
        "--output-root",
        "evidence/v060/scenarios-public",
    ),
)
_PUBLISH_P0 = _python_script_matcher("tests/fixtures/v060/run_p0_falsify.py")
_PUBLISH_GOLDEN = _python_script_matcher(
    "scripts/v060_golden.py",
    required=("--result", "v060-golden-result.json"),
)
_PUBLISH_PACKAGE = _python_script_matcher(
    "scripts/package_smoke.py",
    required_options=(
        ("--out", "package-dist"),
        ("--ledger", "guard-ledger.jsonl"),
    ),
    forbidden=("--root", "--skip-install"),
)
_PROVIDER_LIVE_VERIFY_TOKENS = (
    "scripts/v060_provider_live_gate.py",
    "--verify-summary",
    "provider-live-release-evidence/scenario-summary.json",
    "--verify-ledger",
    "provider-live-release-evidence/guard-ledger.jsonl",
    "--expected-tier",
    "release",
    "--expected-source-commit",
    "$VERIFIED_COMMIT_OID",
)
_EXACT_RELEASE_TAG_CHECK = r'[[ "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]'


def _provider_live_verify_matcher(command: _ShellCommand) -> bool:
    tokens = _tokens(command)
    return (
        len(tokens) == len(_PROVIDER_LIVE_VERIFY_TOKENS) + 1
        and tokens[0] in {"python", "python3"}
        and tokens[1:] == _PROVIDER_LIVE_VERIFY_TOKENS
        and not _is_noop_or_masked(command)
    )


def _env_access(node: ast.AST, key: str) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "os"
        and node.value.attr == "environ"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == key
    )


def _provider_run_payload_valid(payload: str) -> bool:
    """Recognize the fail-closed run API checks, not comments or string mentions."""

    try:
        tree = ast.parse(payload)
    except SyntaxError:
        return False

    assignments = {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    run_id = assignments.get("run_id")
    if run_id is None or not _env_access(run_id, "PROVIDER_LIVE_RUN_ID"):
        return False

    url = assignments.get("url")
    if not isinstance(url, ast.JoinedStr):
        return False
    url_text = "".join(
        value.value
        for value in url.values
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    )
    if "/actions/runs/" not in url_text or not any(
        isinstance(value, ast.FormattedValue)
        and isinstance(value.value, ast.Name)
        and value.value.id == "run_id"
        for value in url.values
    ):
        return False

    expected = assignments.get("expected")
    if not isinstance(expected, ast.Dict) or len(expected.keys) != 4:
        return False
    expected_values: dict[str, ast.AST] = {}
    for key, value in zip(expected.keys, expected.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return False
        expected_values[key.value] = value
    if set(expected_values) != {"name", "event", "conclusion", "head_sha"}:
        return False
    for key, value in (
        ("name", "v060-provider-live"),
        ("event", "workflow_dispatch"),
        ("conclusion", "success"),
    ):
        node = expected_values[key]
        if not isinstance(node, ast.Constant) or node.value != value:
            return False
    if not _env_access(expected_values["head_sha"], "VERIFIED_COMMIT_OID"):
        return False

    payload_value = assignments.get("payload")
    if not (
        isinstance(payload_value, ast.Call)
        and isinstance(payload_value.func, ast.Attribute)
        and isinstance(payload_value.func.value, ast.Name)
        and payload_value.func.value.id == "json"
        and payload_value.func.attr == "load"
    ):
        return False
    actual = assignments.get("actual")
    if not (
        isinstance(actual, ast.DictComp)
        and isinstance(actual.key, ast.Name)
        and actual.key.id == "key"
        and isinstance(actual.value, ast.Call)
        and isinstance(actual.value.func, ast.Attribute)
        and isinstance(actual.value.func.value, ast.Name)
        and actual.value.func.value.id == "payload"
        and actual.value.func.attr == "get"
        and len(actual.generators) == 1
        and isinstance(actual.generators[0].target, ast.Name)
        and actual.generators[0].target.id == "key"
        and isinstance(actual.generators[0].iter, ast.Name)
        and actual.generators[0].iter.id == "expected"
    ):
        return False

    return any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "actual"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.NotEq)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Name)
        and node.test.comparators[0].id == "expected"
        and any(isinstance(child, ast.Raise) for child in node.body)
        for node in ast.walk(tree)
    )


def _provider_run_validation_block(job: _WorkflowJob) -> tuple[_RunBlock, int] | None:
    required_env = {
        "PROVIDER_LIVE_RUN_ID": "${{ inputs.provider_live_run_id }}",
        "VERIFIED_COMMIT_OID": "${{ steps.release_ref.outputs.commit_oid }}",
        "GH_TOKEN": "${{ github.token }}",
    }
    for block in job.runs:
        if block.condition is not None:
            continue
        env = dict(block.env)
        if any(env.get(key) != value for key, value in required_env.items()):
            continue
        commands = _shell_commands(block)
        for index, command in enumerate(commands):
            if _tokens(command)[:2] not in {("python", "-"), ("python3", "-")}:
                continue
            payload = _heredoc_payload(block, command)
            if payload is not None and _provider_run_payload_valid(payload):
                return block, index
    return None


def _provider_live_download_action(job: _WorkflowJob) -> _ActionStep | None:
    required = {
        "name": "v060-provider-live-release-${{ steps.release_ref.outputs.commit_oid }}",
        "path": "provider-live-release-evidence",
        "run-id": "${{ inputs.provider_live_run_id }}",
        "github-token": "${{ github.token }}",
    }
    matches = [
        action
        for action in job.actions
        if action.uses == "actions/download-artifact@v4"
        and action.condition is None
        and all(dict(action.with_values).get(key) == value for key, value in required.items())
    ]
    return matches[0] if len(matches) == 1 else None


def _exact_tag_validation(job: _WorkflowJob) -> tuple[_RunBlock, int] | None:
    for block in job.runs:
        commands = _shell_commands(block)
        for index, command in enumerate(commands):
            if command.text == _EXACT_RELEASE_TAG_CHECK + " || exit 2":
                return block, index
            if command.text != _EXACT_RELEASE_TAG_CHECK + " || {":
                continue
            for nested in commands[index + 1 :]:
                if nested.text == "exit 2":
                    return block, index
                if nested.text == "}":
                    break
    return None


def _version_binding_block(job: _WorkflowJob) -> tuple[_RunBlock, int] | None:
    for block in job.runs:
        commands = _shell_commands(block)
        python_index = next(
            (
                index
                for index, command in enumerate(commands)
                if _tokens(command)[:2] in {("python", "-"), ("python3", "-")}
            ),
            None,
        )
        if python_index is None:
            continue
        payload = _heredoc_payload(block, commands[python_index])
        if payload is not None and _python_version_payload_valid(payload):
            return block, python_index
    return None


def _python_version_payload_valid(payload: str) -> bool:
    try:
        tree = ast.parse(payload)
    except SyntaxError:
        return False
    run_path = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "runpy"
        and node.func.attr == "run_path"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "src/tep_core/version.py"
        for node in ast.walk(tree)
    )
    release_tag = any(
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "os"
        and node.value.attr == "environ"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "RELEASE_TAG"
        for node in ast.walk(tree)
    )
    version_compare = any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "__version__"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == "expected"
        for node in ast.walk(tree)
    )
    return run_path and release_tag and version_compare


def _publish_admission_errors(text: str) -> list[str]:
    try:
        workflow = _parse_workflow_subset(text)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    if "workflow_dispatch" not in workflow.triggers:
        errors.append("publish workflow requires workflow_dispatch")
    if "push" in workflow.triggers:
        errors.append("publish workflow must not run on push or tag push")
    provider_run_input = workflow.dispatch_inputs.get("provider_live_run_id", {})
    if provider_run_input.get("required") != "true" or provider_run_input.get("type") != "string":
        errors.append("publish workflow requires a string provider_live_run_id input")
    verify_job = workflow.jobs.get("verify-release")
    publish_job = workflow.jobs.get("publish")
    if publish_job is None:
        errors.append("missing job publish")
    elif publish_job.needs != {"verify-release"}:
        errors.append("publish job must need only verify-release")
    requirements: tuple[tuple[str, _Matcher], ...] = (
        ("annotated tag", _annotated_tag_matcher),
        ("unit suite", _pytest_matcher),
        ("P0 falsify", _PUBLISH_P0),
        ("v0.6 golden", _PUBLISH_GOLDEN),
        ("local scenario registry", _SCENARIO_LOCAL),
        ("public scenario registry", _SCENARIO_PUBLIC),
        ("package smoke", _PUBLISH_PACKAGE),
        ("provider live evidence summary", _provider_live_verify_matcher),
    )
    for label, matcher in requirements:
        _require_enforced_command(
            errors,
            job=verify_job,
            job_name="verify-release",
            label=label,
            matcher=matcher,
        )
    if verify_job is not None:
        exact_tag = _exact_tag_validation(verify_job)
        if exact_tag is None:
            errors.append("verify-release: missing exact SemVer tag validation")
        elif not _strict_mode_precedes(*exact_tag):
            errors.append(
                "verify-release: exact tag validation must follow set -euo pipefail "
                "in the same run block"
            )
        version_binding = _version_binding_block(verify_job)
        if version_binding is None:
            errors.append("verify-release: missing executable source-version binding")
        elif not _strict_mode_precedes(*version_binding):
            errors.append(
                "verify-release: source-version binding must follow set -euo pipefail "
                "in the same run block"
            )
        provider_run = _provider_run_validation_block(verify_job)
        if provider_run is None:
            errors.append("verify-release: missing executable same-commit provider run validation")
        elif not _strict_mode_precedes(*provider_run):
            errors.append(
                "verify-release: provider run validation must follow set -euo pipefail "
                "in the same run block"
            )
        provider_download = _provider_live_download_action(verify_job)
        if provider_download is None:
            errors.append("verify-release: missing same-run-id release evidence download")
        provider_verifiers = _find_commands(verify_job, _provider_live_verify_matcher)
        unconditional_verifiers = [
            match for match in provider_verifiers if match[0].condition is None
        ]
        if (
            provider_run is not None
            and provider_download is not None
            and unconditional_verifiers
            and not (
                provider_run[0].start_line
                < provider_download.start_line
                < unconditional_verifiers[0][0].start_line
            )
        ):
            errors.append(
                "verify-release: provider run validation, artifact download, and summary "
                "verification must execute in that order"
            )
    if publish_job is not None:
        exact_tag = _exact_tag_validation(publish_job)
        if exact_tag is None:
            errors.append("publish: missing exact SemVer tag revalidation")
        elif not _strict_mode_precedes(*exact_tag):
            errors.append(
                "publish: exact tag revalidation must follow set -euo pipefail "
                "in the same run block"
            )
        if any(
            "${{ inputs.tag }}" in command.text
            for block in publish_job.runs
            for command in _shell_commands(block)
        ):
            errors.append("publish: tag input must reach shell only through a quoted env variable")
        if not any(use.startswith("pypa/gh-action-pypi-publish@") for use in publish_job.uses):
            errors.append("publish job has no PyPI publish action")
    return errors


def _mutate_command(
    text: str,
    *,
    job_name: str,
    matcher: _Matcher,
    mode: str,
) -> str:
    workflow = _parse_workflow_subset(text)
    matches = _find_commands(workflow.jobs[job_name], matcher)
    assert matches, f"mutation target missing in {job_name}"
    return _mutate_command_location(text, matches[0], mode=mode)


def _mutate_command_location(
    text: str,
    location: tuple[_RunBlock, int, _ShellCommand] | tuple[_RunBlock, int],
    *,
    mode: str,
) -> str:
    block, index = location[:2]
    command = _shell_commands(block)[index]
    lines = text.splitlines()
    for position, line_number in enumerate(command.source_lines):
        raw = lines[line_number]
        indent = raw[: len(raw) - len(raw.lstrip(" "))]
        if mode == "comment" or position > 0:
            lines[line_number] = indent + "# " + raw.strip()
        elif mode == "noop":
            lines[line_number] = indent + 'echo "admission command intentionally disabled"'
        else:
            raise AssertionError(f"unknown mutation mode: {mode}")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _mutate_pipefail(text: str, *, job_name: str, matcher: _Matcher) -> str:
    workflow = _parse_workflow_subset(text)
    matches = _find_commands(workflow.jobs[job_name], matcher)
    assert matches, f"mutation target missing in {job_name}"
    return _mutate_pipefail_location(text, matches[0])


def _mutate_pipefail_location(
    text: str,
    location: tuple[_RunBlock, int, _ShellCommand] | tuple[_RunBlock, int],
) -> str:
    block, command_index = location[:2]
    strict = next(
        command
        for command in _shell_commands(block)[:command_index]
        if _tokens(command) == ("set", "-euo", "pipefail")
    )
    lines = text.splitlines()
    line_number = strict.source_lines[0]
    lines[line_number] = lines[line_number].replace("set -euo pipefail", "set -eu")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _unsafe_sdist(path: Path, name: str, body: bytes) -> None:
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))


@pytest.mark.parametrize(
    "name",
    [
        "grift-cli-0.6.0/.worktrees/private/file.txt",
        "grift-cli-0.6.0/.claude/settings.json",
        "grift-cli-0.6.0/smoke/output.json",
        "grift-cli-0.6.0/grift-cli/.git/config",
        "grift-cli-0.6.0/uv.lock",
    ],
)
def test_package_inventory_rejects_owner_unknown_paths(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _unsafe_sdist(archive, name, b"ordinary")
    with pytest.raises(PackageContractError, match="forbidden"):
        inspect_distribution(archive)


def test_package_inventory_rejects_owner_unknown_member_inside_allowed_source(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _unsafe_sdist(
        archive,
        "grift-cli-0.6.0/src/tep_core/owner_unknown_probe.py",
        b"OWNER_UNKNOWN = True\n",
    )

    with pytest.raises(
        PackageContractError,
        match="untracked package member: src/tep_core/owner_unknown_probe.py",
    ):
        inspect_distribution(archive, tracked_paths=frozenset({"README.md"}))


def test_package_tracked_inventory_allows_only_closed_build_metadata() -> None:
    tracked = frozenset(
        {
            "LICENSE",
            "pyproject.toml",
            "src/tep_cli/__main__.py",
            "src/tep_core/__init__.py",
        }
    )
    sdist_rows = [
        ("grift_cli-0.6.0/src/tep_cli/__main__.py", b""),
        ("grift_cli-0.6.0/src/tep_core/__init__.py", b""),
        ("grift_cli-0.6.0/PKG-INFO", b"generated"),
    ]
    wheel_rows = [
        ("tep_cli/__main__.py", b""),
        ("tep_core/__init__.py", b""),
        *[
            (f"grift_cli-0.6.0.dist-info/{relative}", b"generated")
            for relative in sorted(_PACKAGE_SMOKE.GENERATED_WHEEL_DIST_INFO_MEMBERS)
        ],
    ]
    content_sha256 = {
        "src/tep_cli/__main__.py": _PACKAGE_SMOKE.hashlib.sha256(b"").hexdigest(),
        "src/tep_core/__init__.py": _PACKAGE_SMOKE.hashlib.sha256(b"").hexdigest(),
    }

    sdist_errors, sdist_result = tracked_inventory_violations(
        Path("grift_cli-0.6.0.tar.gz"),
        sdist_rows,
        tracked_paths=tracked,
        tracked_content_sha256=content_sha256,
    )
    wheel_errors, wheel_result = tracked_inventory_violations(
        Path("grift_cli-0.6.0-py3-none-any.whl"),
        wheel_rows,
        tracked_paths=tracked,
        tracked_content_sha256=content_sha256,
    )

    assert sdist_errors == []
    assert sdist_result == {
        "enforced": True,
        "tracked_source_member_count": 2,
        "generated_member_count": 1,
        "generated_members": ["PKG-INFO"],
    }
    assert wheel_errors == []
    assert wheel_result["enforced"] is True
    assert wheel_result["tracked_source_member_count"] == 2
    assert wheel_result["generated_members"] == sorted(
        _PACKAGE_SMOKE.GENERATED_WHEEL_DIST_INFO_MEMBERS
    )


def test_package_tracked_inventory_rejects_unknown_generated_wheel_metadata() -> None:
    tracked = frozenset({"LICENSE", "pyproject.toml", "src/tep_core/__init__.py"})
    rows = [
        ("tep_core/__init__.py", b""),
        *[
            (f"grift_cli-0.6.0.dist-info/{relative}", b"generated")
            for relative in sorted(_PACKAGE_SMOKE.GENERATED_WHEEL_DIST_INFO_MEMBERS)
        ],
        ("grift_cli-0.6.0.dist-info/owner-unknown.txt", b"untracked"),
    ]

    errors, _result = tracked_inventory_violations(
        Path("grift_cli-0.6.0-py3-none-any.whl"), rows, tracked_paths=tracked
    )

    assert "unapproved generated wheel metadata: owner-unknown.txt" in errors


def test_package_tracked_inventory_rejects_changed_tracked_member_bytes() -> None:
    rows = [
        ("grift_cli-0.6.0/src/tep_core/__init__.py", b"changed"),
        ("grift_cli-0.6.0/PKG-INFO", b"generated"),
    ]

    errors, _result = tracked_inventory_violations(
        Path("grift_cli-0.6.0.tar.gz"),
        rows,
        tracked_paths=frozenset({"src/tep_core/__init__.py"}),
        tracked_content_sha256={
            "src/tep_core/__init__.py": _PACKAGE_SMOKE.hashlib.sha256(b"expected").hexdigest()
        },
    )

    assert "tracked package member content mismatch: src/tep_core/__init__.py" in errors


def test_package_source_binding_requires_clean_tracked_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Package Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "package@example.test"], check=True
    )
    tracked = repo / "README.md"
    tracked.write_text("tracked\n", encoding="utf-8")
    version = repo / "src" / "tep_core" / "version.py"
    version.parent.mkdir(parents=True)
    version.write_text('__version__ = "0.6.0"\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md", str(version)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-gpg-sign", "-m", "fixture"],
        check=True,
    )

    binding, paths, content_sha256 = source_binding(repo)

    assert binding["schema_version"] == "grift-package-source-binding-v1"
    assert (
        binding["head_commit_oid"]
        == subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    )
    assert (
        binding["head_tree_oid"]
        == subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True
        ).strip()
    )
    assert binding["tracked_clean"] is True
    assert binding["source_version"] == "0.6.0"
    assert binding["tracked_path_count"] == 2
    assert len(str(binding["tracked_path_inventory_sha256"])) == 64
    assert len(str(binding["tracked_content_inventory_sha256"])) == 64
    assert (
        binding["content_equality_policy"]
        == "all_non_generated_members_match_tracked_worktree_sha256"
    )
    assert binding["generated_metadata_exceptions"] == {
        "sdist": ["PKG-INFO"],
        "wheel_dist_info": sorted(_PACKAGE_SMOKE.GENERATED_WHEEL_DIST_INFO_MEMBERS),
    }
    assert len(str(binding["binding_sha256"])) == 64
    assert paths == frozenset({"README.md", "src/tep_core/version.py"})
    assert content_sha256 == {
        "README.md": _PACKAGE_SMOKE.hashlib.sha256(b"tracked\n").hexdigest(),
        "src/tep_core/version.py": _PACKAGE_SMOKE.hashlib.sha256(
            b'__version__ = "0.6.0"\n'
        ).hexdigest(),
    }

    tracked.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(PackageContractError, match="tracked source must be clean"):
        source_binding(repo)


def test_package_source_binding_rejects_untracked_or_nonliteral_version_ssot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "--template=", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Package Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "package@example.test"], check=True
    )
    readme = repo / "README.md"
    readme.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-gpg-sign", "-m", "fixture"],
        check=True,
    )
    version = repo / "src" / "tep_core" / "version.py"
    version.parent.mkdir(parents=True)
    version.write_text('__version__ = "0.6.0"\n', encoding="utf-8")

    with pytest.raises(PackageContractError, match="version SSOT must be tracked"):
        source_binding(repo)

    subprocess.run(["git", "-C", str(repo), "add", str(version)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-gpg-sign", "-m", "version"],
        check=True,
    )
    version.write_text("__version__ = compute_version()\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", str(version)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-gpg-sign", "-m", "dynamic"],
        check=True,
    )
    with pytest.raises(PackageContractError, match="literal __version__"):
        source_binding(repo)


def test_partial_dirty_sentinel_creation_is_rolled_back(tmp_path: Path) -> None:
    owner_file = tmp_path / "grift-cli"
    owner_file.write_text("owner content\n", encoding="utf-8")

    with pytest.raises(PackageContractError, match="must be a directory"):
        dirty_sentinels(tmp_path)

    assert owner_file.read_text(encoding="utf-8") == "owner content\n"
    assert not (tmp_path / "smoke").exists()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".worktrees").exists()
    assert not (tmp_path / "uv.lock").exists()


def test_dirty_sentinels_never_follow_owner_parent_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / ".worktrees").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PackageContractError, match="must not be a symlink"):
        dirty_sentinels(root)

    assert list(outside.iterdir()) == []
    assert (root / ".worktrees").is_symlink()
    assert not (root / "smoke").exists()
    assert not (root / ".claude").exists()
    assert not (root / "grift-cli").exists()
    assert not (root / "uv.lock").exists()


def test_dirty_sentinel_exclusive_create_preserves_owner_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedUuid:
        hex = "fixed"

    smoke = tmp_path / "smoke"
    smoke.mkdir()
    owner_file = smoke / "package-sentinel-fixed.txt"
    owner_file.write_text("owner content\n", encoding="utf-8")
    monkeypatch.setattr(_PACKAGE_SMOKE.uuid, "uuid4", lambda: FixedUuid())

    with pytest.raises(FileExistsError):
        dirty_sentinels(tmp_path)

    assert owner_file.read_text(encoding="utf-8") == "owner content\n"
    assert sorted(path.name for path in smoke.iterdir()) == [owner_file.name]
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".worktrees").exists()
    assert not (tmp_path / "grift-cli").exists()
    assert not (tmp_path / "uv.lock").exists()


def test_dirty_sentinels_preserve_dangling_uv_lock_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-lock"
    lock = tmp_path / "uv.lock"
    lock.symlink_to(outside)

    files, directories, _needle = dirty_sentinels(tmp_path)
    try:
        assert lock.is_symlink()
        assert not outside.exists()
    finally:
        cleanup_sentinels(files, directories)

    assert lock.is_symlink()
    assert not outside.exists()


def test_package_runtime_environment_isolated_from_global_git_config() -> None:
    env = runtime_env()

    assert env["GIT_CONFIG_GLOBAL"] == _PACKAGE_SMOKE.os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


def test_package_inventory_rejects_dirty_sentinel_content(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    dirty_canary = b"GRIFT_PACKAGE_" + b"DIRTY_SENTINEL_" + b"DO_NOT_SHIP"
    _unsafe_sdist(archive, "grift-cli-0.6.0/README.md", dirty_canary)
    with pytest.raises(PackageContractError, match="forbidden needle"):
        inspect_distribution(archive)


def test_package_inventory_rejects_explicit_secret_needle(tmp_path: Path) -> None:
    archive = tmp_path / "secret.tar.gz"
    _unsafe_sdist(
        archive,
        "grift-cli-0.6.0/README.md",
        b"ordinary-prefix PRIVATE-CANARY ordinary-suffix",
    )
    with pytest.raises(PackageContractError, match="forbidden needle"):
        inspect_distribution(archive, extra_needle=b"PRIVATE-CANARY")


def test_package_inventory_rejects_private_key_material(tmp_path: Path) -> None:
    archive = tmp_path / "private-key.tar.gz"
    private_key_header = b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----"
    _unsafe_sdist(archive, "grift-cli-0.6.0/package.key", private_key_header)
    with pytest.raises(PackageContractError, match="secret pattern openssh_private_key"):
        inspect_distribution(archive)


@pytest.mark.parametrize(
    ("label", "local_path"),
    [
        (
            "developer_home",
            b"/" + b"Users" + b"/" + b"teradakousuke" + b"/Developer/grift-cli/private-result.json",
        ),
        ("macos_temp", b"/" + b"var" + b"/" + b"folders" + b"/aa/private-result.json"),
        (
            "macos_private_temp",
            b"/" + b"private" + b"/" + b"var" + b"/" + b"folders" + b"/bb/private-result.json",
        ),
    ],
)
def test_package_inventory_rejects_captured_local_machine_path(
    tmp_path: Path, label: str, local_path: bytes
) -> None:
    archive = tmp_path / "local-path.tar.gz"
    _unsafe_sdist(archive, "grift-cli-0.6.0/docs/result.txt", local_path)
    with pytest.raises(PackageContractError, match=f"local machine path prefix {label}"):
        inspect_distribution(archive)


def test_package_inventory_rejects_current_build_root_path(tmp_path: Path) -> None:
    archive = tmp_path / "local-build-root.tar.gz"
    _unsafe_sdist(
        archive,
        "grift-cli-0.6.0/docs/result.txt",
        b"/opt/ci/build/grift-cli/private-result.json",
    )

    with pytest.raises(PackageContractError, match="local machine path prefix build_source_root"):
        inspect_distribution(
            archive,
            extra_local_path_prefixes={"build_source_root": b"/opt/ci/build/grift-cli/"},
        )


def test_package_local_path_scan_allows_fake_user_and_rehearsal_placeholder() -> None:
    assert (
        local_machine_path_violations(
            "grift-cli-0.6.0/tests/fixture.txt", b"/Users/person/Developer/private"
        )
        == []
    )
    placeholder = b"/" + b"var" + b"/" + b"folders" + b"/.../opencode/rehearsal-v051"
    assert (
        local_machine_path_violations(
            "grift-cli-0.6.0/docs/RELEASE-REHEARSAL-v051-20260822.md",
            placeholder,
        )
        == []
    )


def test_package_inventory_rejects_archive_links(tmp_path: Path) -> None:
    archive = tmp_path / "link.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        info = tarfile.TarInfo("grift-cli-0.6.0/src/tep_core/escape")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        stream.addfile(info)
    with pytest.raises(PackageContractError, match="link/device member is forbidden"):
        inspect_distribution(archive)


def test_package_inventory_requires_runtime_and_evidence_members(tmp_path: Path) -> None:
    archive = tmp_path / "incomplete.tar.gz"
    _unsafe_sdist(archive, "grift-cli-0.6.0/README.md", b"ordinary")
    with pytest.raises(PackageContractError, match="required package member missing"):
        inspect_distribution(archive)


def test_sdist_inventory_rejects_registered_golden_hash_mismatch() -> None:
    artifact = Path("grift_cli-0.6.0.tar.gz")
    manifest = {
        "registered_files": {"fixtures/example.json": "0" * 64},
    }
    rows = [
        (
            "grift_cli-0.6.0/benchmarks/v060/sources.json",
            b'{"local_artifact_sha256":{}}',
        ),
        (
            "grift_cli-0.6.0/benchmarks/v060/golden/manifest.json",
            json.dumps(manifest).encode("utf-8"),
        ),
        (
            "grift_cli-0.6.0/benchmarks/v060/golden/fixtures/example.json",
            b"different",
        ),
    ]

    violations = assert_required_members(artifact, rows)

    assert "registered golden hash mismatch: fixtures/example.json" in violations


def test_package_guard_negative_probe_is_actually_blocked() -> None:
    result = negative_guard_probe()
    assert result == {
        "incident": (
            "dirty worktree member, owner-unknown allowlist member, sentinel content, "
            "and captured host path"
        ),
        "result": "blocked",
        "regression_evidence": {
            "before_fix": "ACCEPTED member_count=371 contains_owner_unknown=True",
            "after_fix": ("REJECTED untracked package member: src/tep_core/owner_unknown_probe.py"),
        },
        "enforced": [
            "forbidden path",
            "forbidden needle",
            "untracked allowlist member",
            "local machine path prefix developer_home",
            "local machine path prefix macos_private_temp",
            "local machine path prefix macos_temp",
        ],
    }


def _workflow_text(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_ci_executes_golden_and_package_guards_in_strict_run_blocks() -> None:
    assert _ci_admission_errors(_workflow_text("ci.yml")) == []


@pytest.mark.parametrize(
    ("job_name", "label", "matcher"),
    [
        ("v060-golden", "v0.6 golden", _CI_GOLDEN),
        ("v060-golden", "public scenario registry", _CI_PUBLIC_SCENARIO),
        ("package-smoke", "package smoke", _CI_PACKAGE_SMOKE),
    ],
    ids=("v060-golden", "public-scenario", "package-smoke"),
)
@pytest.mark.parametrize("mode", ("comment", "noop"))
def test_ci_guard_command_comment_or_noop_mutation_is_rejected(
    job_name: str,
    label: str,
    matcher: _Matcher,
    mode: str,
) -> None:
    mutated = _mutate_command(
        _workflow_text("ci.yml"),
        job_name=job_name,
        matcher=matcher,
        mode=mode,
    )
    errors = _ci_admission_errors(mutated)
    assert any(label in error for error in errors), errors


@pytest.mark.parametrize(
    ("job_name", "label", "matcher"),
    [
        ("v060-golden", "v0.6 golden", _CI_GOLDEN),
        ("v060-golden", "public scenario registry", _CI_PUBLIC_SCENARIO),
        ("package-smoke", "package smoke", _CI_PACKAGE_SMOKE),
    ],
    ids=("v060-golden", "public-scenario", "package-smoke"),
)
def test_ci_guard_pipefail_mutation_is_rejected(
    job_name: str,
    label: str,
    matcher: _Matcher,
) -> None:
    mutated = _mutate_pipefail(
        _workflow_text("ci.yml"),
        job_name=job_name,
        matcher=matcher,
    )
    errors = _ci_admission_errors(mutated)
    assert any(label in error and "pipefail" in error for error in errors), errors


@pytest.mark.parametrize(
    "bypass",
    (
        "--skip-install",
        "--skip-install=true",
        "--root /tmp/other-source",
        "--root=/tmp/other-source",
        "--out /tmp/unbound-dist",
    ),
)
def test_ci_package_gate_rejects_install_and_source_binding_bypasses(bypass: str) -> None:
    workflow = _workflow_text("ci.yml")
    target = "            --out package-dist \\\n"
    assert target in workflow, "package gate mutation target changed"
    mutated = workflow.replace(
        target,
        f"            --out package-dist {bypass} \\\n",
        1,
    )

    errors = _ci_admission_errors(mutated)

    assert any("package smoke" in error for error in errors), errors


@pytest.mark.parametrize(
    "bypass",
    (
        "--skip-install",
        "--skip-install=true",
        "--root /tmp/other-source",
        "--root=/tmp/other-source",
        "--out /tmp/unbound-dist",
    ),
)
def test_publish_package_gate_rejects_install_and_source_binding_bypasses(
    bypass: str,
) -> None:
    workflow = _workflow_text("publish.yml")
    target = "            --out package-dist \\\n"
    assert target in workflow, "publish package mutation target changed"
    mutated = workflow.replace(
        target,
        f"            --out package-dist {bypass} \\\n",
        1,
    )

    errors = _publish_admission_errors(mutated)

    assert any("package smoke" in error for error in errors), errors


def test_ci_guard_command_inside_heredoc_is_not_execution() -> None:
    workflow = """\
name: negative
on:
  workflow_dispatch:
jobs:
  v060-golden:
    steps:
      - name: No-op documentation
        run: |
          set -euo pipefail
          cat <<'EOF'
          python scripts/v060_golden.py --result golden-evidence/v060-golden-result.json
          EOF
  package-smoke:
    steps:
      - name: Actual package gate
        run: |
          set -euo pipefail
          python scripts/package_smoke.py --ledger package-evidence/guard-ledger.jsonl
"""
    errors = _ci_admission_errors(workflow)
    assert "v060-golden: missing executable v0.6 golden command" in errors


def test_ci_guard_command_in_wrong_job_or_yaml_comment_is_not_execution() -> None:
    workflow = """\
name: negative
on:
  workflow_dispatch:
jobs:
  v060-golden:
    steps:
      - name: python scripts/v060_golden.py is only documentation
        run: |
          set -euo pipefail
          # python scripts/v060_golden.py --result golden-evidence/v060-golden-result.json
          echo "golden disabled"
  decoy:
    steps:
      - run: |
          set -euo pipefail
          python scripts/v060_golden.py --result golden-evidence/v060-golden-result.json
  package-smoke:
    steps:
      - run: |
          set -euo pipefail
          python scripts/package_smoke.py --ledger package-evidence/guard-ledger.jsonl
"""
    errors = _ci_admission_errors(workflow)
    assert "v060-golden: missing executable v0.6 golden command" in errors


def test_publish_requires_manual_dispatch_and_all_pre_publish_run_gates() -> None:
    assert _publish_admission_errors(_workflow_text("publish.yml")) == []


@pytest.mark.parametrize(
    ("label", "matcher"),
    [
        ("annotated tag", _annotated_tag_matcher),
        ("unit suite", _pytest_matcher),
        ("P0 falsify", _PUBLISH_P0),
        ("v0.6 golden", _PUBLISH_GOLDEN),
        ("local scenario registry", _SCENARIO_LOCAL),
        ("public scenario registry", _SCENARIO_PUBLIC),
        ("package smoke", _PUBLISH_PACKAGE),
        ("provider live evidence summary", _provider_live_verify_matcher),
    ],
    ids=(
        "annotated-tag",
        "unit",
        "p0",
        "v060-golden",
        "scenario-local",
        "scenario-public",
        "package-smoke",
        "provider-live-summary",
    ),
)
def test_publish_gate_comment_mutation_is_rejected(label: str, matcher: _Matcher) -> None:
    mutated = _mutate_command(
        _workflow_text("publish.yml"),
        job_name="verify-release",
        matcher=matcher,
        mode="comment",
    )
    errors = _publish_admission_errors(mutated)
    assert any(label in error for error in errors), errors


@pytest.mark.parametrize(
    ("label", "matcher"),
    [
        ("annotated tag", _annotated_tag_matcher),
        ("unit suite", _pytest_matcher),
        ("P0 falsify", _PUBLISH_P0),
        ("v0.6 golden", _PUBLISH_GOLDEN),
        ("local scenario registry", _SCENARIO_LOCAL),
        ("public scenario registry", _SCENARIO_PUBLIC),
        ("package smoke", _PUBLISH_PACKAGE),
        ("provider live evidence summary", _provider_live_verify_matcher),
    ],
    ids=(
        "annotated-tag",
        "unit",
        "p0",
        "v060-golden",
        "scenario-local",
        "scenario-public",
        "package-smoke",
        "provider-live-summary",
    ),
)
def test_publish_gate_pipefail_mutation_is_rejected(label: str, matcher: _Matcher) -> None:
    mutated = _mutate_pipefail(
        _workflow_text("publish.yml"),
        job_name="verify-release",
        matcher=matcher,
    )
    errors = _publish_admission_errors(mutated)
    assert any(label in error and "pipefail" in error for error in errors), errors


@pytest.mark.parametrize("mode", ("comment", "noop"))
def test_publish_provider_run_validation_comment_or_noop_is_rejected(mode: str) -> None:
    workflow = _workflow_text("publish.yml")
    parsed = _parse_workflow_subset(workflow)
    location = _provider_run_validation_block(parsed.jobs["verify-release"])
    assert location is not None

    mutated = _mutate_command_location(workflow, location, mode=mode)
    errors = _publish_admission_errors(mutated)

    assert any("provider run validation" in error for error in errors), errors


def test_publish_provider_run_validation_pipefail_mutation_is_rejected() -> None:
    workflow = _workflow_text("publish.yml")
    parsed = _parse_workflow_subset(workflow)
    location = _provider_run_validation_block(parsed.jobs["verify-release"])
    assert location is not None

    mutated = _mutate_pipefail_location(workflow, location)
    errors = _publish_admission_errors(mutated)

    assert any("provider run validation" in error and "pipefail" in error for error in errors), (
        errors
    )


@pytest.mark.parametrize(
    ("before", "after", "expected_error"),
    [
        (
            "      provider_live_run_id:\n"
            '        description: "同一commitで成功したv060-provider-live release tierのrun ID"\n'
            "        required: true\n"
            "        type: string",
            "      provider_live_run_id:\n"
            '        description: "同一commitで成功したv060-provider-live release tierのrun ID"\n'
            "        required: false\n"
            "        type: string",
            "provider_live_run_id input",
        ),
        (
            "        uses: actions/download-artifact@v4\n"
            "        with:\n"
            "          name: v060-provider-live-release-",
            "        # uses: actions/download-artifact@v4\n"
            "        with:\n"
            "          name: v060-provider-live-release-",
            "release evidence download",
        ),
        (
            "          run-id: ${{ inputs.provider_live_run_id }}",
            "          run-id: ${{ github.run_id }}",
            "release evidence download",
        ),
        (
            "          name: v060-provider-live-release-${{ steps.release_ref.outputs.commit_oid }}",
            "          name: v060-provider-live-pr-${{ steps.release_ref.outputs.commit_oid }}",
            "release evidence download",
        ),
        (
            "          github-token: ${{ github.token }}",
            "          # github-token: ${{ github.token }}",
            "release evidence download",
        ),
        (
            '              "conclusion": "success",',
            '              "conclusion": "failure",',
            "provider run validation",
        ),
        (
            '              "head_sha": os.environ["VERIFIED_COMMIT_OID"],',
            '              "head_sha": os.environ["GITHUB_SHA"],',
            "provider run validation",
        ),
        (
            "            --expected-tier release \\",
            "            --expected-tier pr \\",
            "provider live evidence summary",
        ),
        (
            '            --expected-source-commit "$VERIFIED_COMMIT_OID"',
            '            --expected-source-commit "$GITHUB_SHA"',
            "provider live evidence summary",
        ),
    ],
    ids=(
        "run-id-required",
        "download-action-commented",
        "download-run-id",
        "download-release-tier-name",
        "download-token-commented",
        "run-conclusion",
        "run-head-sha",
        "summary-tier",
        "summary-source-commit",
    ),
)
def test_publish_provider_live_binding_mutations_are_rejected(
    before: str,
    after: str,
    expected_error: str,
) -> None:
    workflow = _workflow_text("publish.yml")
    assert before in workflow, "provider-live mutation target changed"

    errors = _publish_admission_errors(workflow.replace(before, after, 1))

    assert any(expected_error in error for error in errors), errors


def test_publish_trigger_and_needs_mutations_are_rejected() -> None:
    workflow = _workflow_text("publish.yml")
    tag_push = workflow.replace(
        "on:\n  workflow_dispatch:",
        'on:\n  push:\n    tags: ["v*"]\n  workflow_dispatch:',
        1,
    )
    assert "tag push" in " ".join(_publish_admission_errors(tag_push))

    wrong_needs = workflow.replace("needs: verify-release", "needs: unrelated-job", 1)
    assert "must need only verify-release" in " ".join(_publish_admission_errors(wrong_needs))


def test_publish_weak_tag_and_version_binding_mutations_are_rejected() -> None:
    workflow = _workflow_text("publish.yml")
    weak_tag = workflow.replace(
        r"^v[0-9]+\.[0-9]+\.[0-9]+$",
        "v[0-9]*.[0-9]*.[0-9]*",
    )
    assert "exact SemVer tag" in " ".join(_publish_admission_errors(weak_tag))

    wrong_version_source = workflow.replace(
        'runpy.run_path("src/tep_core/version.py")',
        'runpy.run_path("src/tep_core/version.py.disabled")',
        1,
    )
    assert "source-version binding" in " ".join(_publish_admission_errors(wrong_version_source))
