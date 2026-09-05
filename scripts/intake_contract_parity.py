#!/usr/bin/env python3
"""Exercise the contribution sender and public intake as one real contract.

This gate intentionally does not compare copied constants.  It asks the
installed ``grift`` CLI to create four real contribution payloads, submits
them to a clean temporary copy of the tep-contributions validator, and then
falsifies three public-profile invariants.  The companion repository is an
explicit input so CI can check it out at an immutable commit.

No network access is required.  The report is produced from a temporary Git
repository by ``grift repo`` and receives one deterministic synthetic public
account linkage solely to exercise the named-public wire contract.

Every Python sender/receiver subprocess imports a generated ``sitecustomize``
guard that denies outbound socket connections.  A deliberate connection probe
must be rejected before the contract cases run; the result records both that
negative proof and any workload connection attempts.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = "2026-08-31T00:00:00Z"
PUBLIC_PROJECT = {
    "provider": "github",
    "host": "github.com",
    "project_id": "R_kgDOContract",
    "project_path": "example/public-contract",
}
PUBLIC_AUTHORITY = {
    "accounts": [
        {
            "provider": "github",
            "host": "github.com",
            "project_id": "R_kgDOContract",
            "account_id": "42",
            "basis": "account_holder_explicit",
            "scope": "project_and_account",
            "assertion": "authorized_for_public_research_contribution",
        }
    ]
}
NETWORK_DENIED_SIGNAL = "GRIFT_INTAKE_NETWORK_DENIED"


class ParityError(RuntimeError):
    """Raised when sender generation or receiver execution cannot proceed."""


@dataclass(frozen=True)
class CaseResult:
    name: str
    profile: str
    expected: str
    actual: str
    exit_code: int
    payload_sha256: str
    signal: str

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _require_success(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode == 0:
        return
    detail = "\n".join(result.stderr.strip().splitlines()[-8:])
    raise ParityError(f"{label} failed with exit {result.returncode}: {detail}")


def _git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    closed_env = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    if env:
        closed_env.update(env)
    result = _run(["git", *args], cwd=repo, env=closed_env)
    _require_success(result, label="git " + " ".join(args))
    return result.stdout.strip()


def _write_json(path: Path, value: Any, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if mode is not None:
        path.chmod(mode)


def _cli_env(network_env: Mapping[str, str] | None = None) -> dict[str, str]:
    existing = os.environ.get("PYTHONPATH")
    pythonpath = str(ROOT / "src") if not existing else str(ROOT / "src") + os.pathsep + existing
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": pythonpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    if network_env:
        env.update(network_env)
    return env


def _install_network_denial(workspace: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Install and dynamically prove a Python socket-denial guard."""

    guard_root = workspace / "network-denial"
    guard_root.mkdir(parents=True, exist_ok=True)
    log_path = guard_root / "socket-denials.jsonl"
    guard = guard_root / "sitecustomize.py"
    guard.write_text(
        """\
import json
import os
import socket

_SIGNAL = "GRIFT_INTAKE_NETWORK_DENIED"
_LOG = os.environ.get("GRIFT_INTAKE_NETWORK_LOG")


def _deny(operation):
    if _LOG:
        row = {
            "operation": operation,
            "phase": os.environ.get("GRIFT_INTAKE_NETWORK_PHASE", "workload"),
        }
        with open(_LOG, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\\n")
    raise PermissionError(_SIGNAL + ": outbound socket access is disabled")


class _DeniedSocket(socket.socket):
    def connect(self, address):
        _deny("socket.connect")

    def connect_ex(self, address):
        _deny("socket.connect_ex")

    def sendto(self, *args, **kwargs):
        _deny("socket.sendto")


def _create_connection(*args, **kwargs):
    _deny("socket.create_connection")


socket.socket = _DeniedSocket
socket.create_connection = _create_connection
""",
        encoding="utf-8",
    )
    existing = os.environ.get("PYTHONPATH")
    python_paths = [str(guard_root), str(ROOT / "src")]
    if existing:
        python_paths.append(existing)
    base_env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(python_paths),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GRIFT_INTAKE_NETWORK_LOG": str(log_path),
        "GRIFT_INTAKE_NETWORK_PHASE": "probe",
    }
    probe = _run(
        [
            sys.executable,
            "-c",
            "import socket; socket.create_connection(('example.invalid', 443))",
        ],
        cwd=workspace,
        env=base_env,
    )
    if probe.returncode == 0 or NETWORK_DENIED_SIGNAL not in probe.stderr:
        raise ParityError("network socket-denial probe did not fail with the required signal")
    workload_env = dict(base_env)
    workload_env["GRIFT_INTAKE_NETWORK_PHASE"] = "workload"
    return workload_env, {
        "mode": "python_socket_deny",
        "probe_exit_code": probe.returncode,
        "probe_signal": NETWORK_DENIED_SIGNAL,
        "log_path": log_path,
    }


def _network_denial_report(seed: Mapping[str, Any]) -> dict[str, Any]:
    log_path = Path(str(seed["log_path"]))
    try:
        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityError(f"network socket-denial ledger is unreadable: {exc}") from exc
    probe_rows = [row for row in rows if row.get("phase") == "probe"]
    workload_rows = [row for row in rows if row.get("phase") == "workload"]
    if not probe_rows:
        raise ParityError("network socket-denial ledger did not record the negative probe")
    return {
        "mode": seed["mode"],
        "probe_exit_code": seed["probe_exit_code"],
        "probe_signal": seed["probe_signal"],
        "probe_denied_calls": len(probe_rows),
        "workload_denied_calls": len(workload_rows),
        "workload_network_attempted": bool(workload_rows),
        "ledger_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }


def _make_report(workspace: Path, *, network_env: Mapping[str, str]) -> Path:
    repo = workspace / "source-repo"
    repo.mkdir()
    _git(repo, "init", "--quiet", "--template=")
    _git(repo, "config", "user.name", "Alice Example")
    _git(repo, "config", "user.email", "alice@example.test")
    _git(repo, "remote", "add", "origin", "https://github.com/example/public-contract.git")
    commit_env = {
        "GIT_AUTHOR_DATE": FIXED_TIME,
        "GIT_COMMITTER_DATE": FIXED_TIME,
    }
    for index in range(3):
        (repo / "evidence.txt").write_text(f"contract line {index}\n", encoding="utf-8")
        _git(repo, "add", "evidence.txt")
        _git(repo, "commit", "--quiet", "-m", f"contract fixture {index}", env=commit_env)

    report_dir = workspace / "report"
    command = [
        sys.executable,
        "-m",
        "tep_cli",
        "repo",
        str(repo),
        "--format",
        "json",
        "--out",
        str(report_dir),
    ]
    result = _run(command, cwd=ROOT, env=_cli_env(network_env))
    _require_success(result, label="grift repo")
    report_path = report_dir / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityError(f"grift repo did not produce readable report-v2: {exc}") from exc

    # The provider join is synthetic and deterministic.  The gate tests only
    # the sender/receiver wire contract; live Forge completeness is proven by
    # the separate provider scenario gate.
    actors = (report.get("actor_directory") or {}).get("actors") or []
    if len(actors) != 1 or actors[0].get("commit_count") != 3:
        raise ParityError(
            "synthetic report actor population is not exactly one actor / three commits"
        )
    account = {
        "provider": "github",
        "host": "github.com",
        "account_id": "42",
        "handle": "alice",
        "profile_url": "https://github.com/alice",
        "evidence": {
            "basis": "commit.author.id",
            "account_match_status": "linked",
        },
    }
    actors[0]["public_account_status"] = "linked"
    actors[0]["public_accounts"] = [account]
    public_join = {
        "matched": 3,
        "unmatched": 0,
        "ambiguous": 0,
        "public_handle_actors": 1,
        "fetched_login_count": 1,
        "commit_login_count": 1,
        "account_conflict_count": 0,
        "count_note": (
            "synthetic_contract: GitHub top-level commit author.id binds one stable "
            "account to all three fixture commits"
        ),
    }
    attribution = report.get("attribution")
    directory_attribution = (report.get("actor_directory") or {}).get("attribution")
    if not isinstance(attribution, dict) or not isinstance(directory_attribution, dict):
        raise ParityError("report-v2 attribution structures are missing")
    attribution["public_join"] = copy.deepcopy(public_join)
    directory_attribution["public_join"] = copy.deepcopy(public_join)
    _write_json(report_path, report)
    return report_path


def _study_manifest(workspace: Path) -> Path:
    path = workspace / "study.json"
    _write_json(
        path,
        {
            "public_project": PUBLIC_PROJECT,
            "public_authority": PUBLIC_AUTHORITY,
            "governance": {
                "controller": "contract-research-controller",
                "authority": "repository-owner-authorization",
                "consent": "recorded-explicit-consent",
                "study_id": "intake-contract-parity",
                "key_id": "synthetic-key-epoch-1",
                "epoch": "2026-08",
                "retention": "until-2027-08-31",
                "withdrawal": "contact-controller-before-publication",
                "access_class": "named-research-team",
            },
            "raw_material": {
                "mailmap": {
                    "before": "Alias <alias@example.test>",
                    "after": "Alice <alice@example.test>",
                },
                "object_ids": [{"algorithm": "sha1", "value": "a" * 40}],
                "provider_manifest": {"coverage": "complete"},
            },
        },
        mode=0o600,
    )
    return path


def _generate_payload(
    *,
    workspace: Path,
    report: Path,
    study: Path,
    profile: str,
    door: str,
    key_file: Path,
    network_env: Mapping[str, str],
) -> tuple[dict[str, Any], list[str]]:
    output = workspace / "sender" / f"{profile}.json"
    command = [
        sys.executable,
        "-m",
        "tep_cli",
        "contribute",
        str(report),
        "--privacy",
        profile,
        "--door",
        door,
        "--study-manifest",
        str(study),
        "--yes",
        "--out",
        str(output),
    ]
    if profile == "masked":
        command.extend(
            [
                "--key-file",
                str(key_file),
                "--controlled-sidecar",
                str(workspace / "sender" / "masked-sidecar.json"),
            ]
        )
    elif profile == "raw":
        command.extend(
            [
                "--controlled-sidecar",
                str(workspace / "sender" / "raw-sidecar.json"),
            ]
        )
    result = _run(command, cwd=ROOT, env=_cli_env(network_env))
    _require_success(result, label=f"grift contribute {profile}")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityError(f"grift contribute {profile} output is unreadable: {exc}") from exc
    if payload.get("privacy_profile") != profile or payload.get("door") != door:
        raise ParityError(f"grift contribute {profile} emitted the wrong profile or door")
    redacted_command = [
        "python",
        "-m",
        "tep_cli",
        "contribute",
        "<report-v2>",
        "--privacy",
        profile,
        "--door",
        door,
        "--yes",
        "--out",
        f"<{profile}.json>",
    ]
    return payload, redacted_command


def generate_sender_payloads(
    workspace: Path,
    *,
    network_env: Mapping[str, str] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[list[str]]]:
    """Generate all four profiles through the public CLI entrypoint."""

    workspace.mkdir(parents=True, exist_ok=True)
    effective_network_env = network_env or {}
    report = _make_report(workspace, network_env=effective_network_env)
    study = _study_manifest(workspace)
    key_file = workspace / "study.key"
    key_file.write_bytes(bytes(range(32)))
    key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    payloads: dict[str, dict[str, Any]] = {}
    commands: list[list[str]] = []
    for profile, door in (
        ("aggregate", "public-pr"),
        ("named-public", "public-pr"),
        ("masked", "controlled"),
        ("raw", "controlled"),
    ):
        payload, command = _generate_payload(
            workspace=workspace,
            report=report,
            study=study,
            profile=profile,
            door=door,
            key_file=key_file,
            network_env=effective_network_env,
        )
        payloads[profile] = payload
        commands.append(command)
    return payloads, commands


def _payload_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _signal(output: str, *, limit: int = 600) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    # Validator messages contain only schema paths / vocabulary.  Never copy
    # CLI payload stdout (which can include controlled raw material) here.
    return " | ".join(lines[-4:])[:limit]


def _receiver_case(
    *,
    companion_scripts: Path,
    workspace: Path,
    case_name: str,
    payload: Mapping[str, Any],
    expected: str,
    expected_signal: Sequence[str],
    network_env: Mapping[str, str],
) -> CaseResult:
    case_root = workspace / "receiver" / case_name
    shutil.copytree(companion_scripts, case_root / "scripts")
    submission_id = f"0831-0000-{hashlib.sha256(case_name.encode()).hexdigest()[:8]}"
    payload_path = case_root / "payloads" / "2026" / f"{submission_id}.json"
    text = _payload_text(payload)
    payload_path.parent.mkdir(parents=True)
    payload_path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _write_json(
        payload_path.with_name(f"{submission_id}.meta.json"),
        {
            "id": submission_id,
            "sha256": digest,
            "received_at": FIXED_TIME,
            "door": "pr",
        },
    )
    result = _run(
        [sys.executable, "scripts/validate.py"],
        cwd=case_root,
        env=network_env,
    )
    combined = result.stdout + "\n" + result.stderr
    actual = "accepted" if result.returncode == 0 else "rejected"
    if expected == "rejected" and actual == "rejected":
        lowered = combined.lower()
        if not any(token.lower() in lowered for token in expected_signal):
            actual = "rejected_without_expected_signal"
    return CaseResult(
        name=case_name,
        profile=str(payload.get("privacy_profile")),
        expected=expected,
        actual=actual,
        exit_code=result.returncode,
        payload_sha256=digest,
        signal=_signal(combined),
    )


def _repo_revision(path: Path) -> tuple[str | None, bool | None]:
    head = _run(["git", "rev-parse", "HEAD"], cwd=path)
    if head.returncode != 0:
        return None, None
    dirty = _run(["git", "status", "--porcelain"], cwd=path)
    return head.stdout.strip(), bool(dirty.stdout.strip()) if dirty.returncode == 0 else None


def run_parity(
    *,
    companion_root: Path,
    workspace: Path,
    expected_companion_sha: str | None = None,
    expected_sender_sha: str | None = None,
    require_companion_clean: bool = False,
) -> dict[str, Any]:
    validator = companion_root / "scripts" / "validate.py"
    allowlists = companion_root / "scripts" / "intake_allowlists.json"
    if not validator.is_file() or not allowlists.is_file():
        raise ParityError(
            "companion root must contain scripts/validate.py and scripts/intake_allowlists.json"
        )
    companion_sha, companion_dirty = _repo_revision(companion_root)
    if expected_companion_sha is not None and companion_sha != expected_companion_sha:
        raise ParityError(
            f"companion HEAD mismatch: expected {expected_companion_sha}, got {companion_sha}"
        )
    if require_companion_clean and companion_dirty is not False:
        raise ParityError("companion checkout must be a clean immutable tree")

    network_env, network_seed = _install_network_denial(workspace)
    payloads, commands = generate_sender_payloads(workspace, network_env=network_env)
    cases: list[tuple[str, dict[str, Any], str, tuple[str, ...]]] = [
        ("aggregate_accept", payloads["aggregate"], "accepted", ()),
        ("named_public_accept", payloads["named-public"], "accepted", ()),
        (
            "masked_public_reject",
            payloads["masked"],
            "rejected",
            ("controlled-study artifact",),
        ),
        (
            "raw_public_reject",
            payloads["raw"],
            "rejected",
            ("controlled-study artifact",),
        ),
    ]

    bad_digest = copy.deepcopy(payloads["aggregate"])
    bad_digest["transformation_spec_digest"] = "sha256:" + "0" * 64
    cases.append(
        (
            "profile_digest_reject",
            bad_digest,
            "rejected",
            ("transformation_spec_digest",),
        )
    )
    bad_replay = copy.deepcopy(payloads["aggregate"])
    bad_replay["policy"]["source_replay"] = "controlled_sidecar_available"
    cases.append(("source_replay_reject", bad_replay, "rejected", ("source_replay=",)))
    bad_authority = copy.deepcopy(payloads["named-public"])
    bad_authority["data"]["authority"]["accounts"][0]["project_id"] = "wrong-project"
    cases.append(
        (
            "authority_binding_reject",
            bad_authority,
            "rejected",
            ("authority binding does not match project",),
        )
    )

    gitlab_linkage = copy.deepcopy(payloads["named-public"])
    gitlab_linkage["data"]["project"].update({"provider": "gitlab", "host": "gitlab.com"})
    gitlab_linkage["data"]["authority"]["accounts"][0].update(
        {"provider": "gitlab", "host": "gitlab.com"}
    )
    gitlab_linkage["data"]["actors"][0]["account"].update(
        {
            "provider": "gitlab",
            "host": "gitlab.com",
            "profile_url": "https://gitlab.com/alice",
            "evidence": {
                "basis": "provider_commit_account",
                "coverage_status": "complete",
                "account_match_status": "linked",
            },
        }
    )
    cases.append(
        (
            "gitlab_account_linkage_reject",
            gitlab_linkage,
            "rejected",
            ("account linkage is unsupported",),
        )
    )

    results = [
        _receiver_case(
            companion_scripts=companion_root / "scripts",
            workspace=workspace,
            case_name=name,
            payload=payload,
            expected=expected,
            expected_signal=signals,
            network_env=network_env,
        )
        for name, payload, expected, signals in cases
    ]
    sender_sha, sender_dirty = _repo_revision(ROOT)
    if expected_sender_sha is not None and sender_sha != expected_sender_sha:
        raise ParityError(f"sender HEAD mismatch: expected {expected_sender_sha}, got {sender_sha}")
    network_proof = _network_denial_report(network_seed)
    status = _final_status(
        results,
        expected_sender_sha=expected_sender_sha,
        actual_sender_sha=sender_sha,
        sender_dirty=sender_dirty,
        expected_companion_sha=expected_companion_sha,
        actual_companion_sha=companion_sha,
        companion_dirty=companion_dirty,
    )
    if network_proof["workload_network_attempted"]:
        status = "MISMATCH"
    return {
        "schema_version": "tep-intake-contract-parity-v1",
        "status": status,
        "network_used": False,
        "network_denial": network_proof,
        "fixture_kind": "synthetic_contract",
        "sender": {
            "repository": "grift-cli",
            "commit": sender_sha,
            "expected_commit": expected_sender_sha,
            "tree_dirty": sender_dirty,
            "entrypoint": "python -m tep_cli contribute",
            "commands": commands,
        },
        "receiver": {
            "repository": "tep-contributions",
            "commit": companion_sha,
            "expected_commit": expected_companion_sha,
            "tree_dirty": companion_dirty,
            "entrypoint": "scripts/validate.py",
        },
        "cases": [asdict(item) | {"passed": item.passed} for item in results],
        "summary": {
            "passed": sum(item.passed for item in results),
            "total": len(results),
        },
    }


def _final_status(
    results: Sequence[CaseResult],
    *,
    expected_sender_sha: str | None,
    actual_sender_sha: str | None,
    sender_dirty: bool | None,
    expected_companion_sha: str | None,
    actual_companion_sha: str | None,
    companion_dirty: bool | None,
) -> str:
    """Separate case parity from immutable-source prerequisites."""

    if not all(item.passed for item in results):
        return "MISMATCH"
    if sender_dirty is not False or companion_dirty is not False:
        return "PREREQUISITE_DIRTY"
    if expected_sender_sha is None or expected_companion_sha is None:
        return "CANNOT_VERIFY"
    if actual_sender_sha != expected_sender_sha or actual_companion_sha != expected_companion_sha:
        return "CANNOT_VERIFY"
    return "VERIFIED"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion-root", required=True, type=Path)
    parser.add_argument("--result", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--expected-companion-sha", default=None)
    parser.add_argument("--expected-sender-sha", default=None)
    parser.add_argument("--require-companion-clean", action="store_true")
    return parser


def _ledger_text(report: Mapping[str, Any]) -> str:
    common = {
        "schema_version": "tep-intake-contract-guard-v1",
        "guard": "intake_contract_parity",
        "status": report.get("status"),
        "sender_commit": (report.get("sender") or {}).get("commit"),
        "receiver_commit": (report.get("receiver") or {}).get("commit"),
    }
    rows = []
    for case in report.get("cases") or []:
        rows.append(
            common
            | {
                "case": case.get("name"),
                "profile": case.get("profile"),
                "expected": case.get("expected"),
                "actual": case.get("actual"),
                "exit_code": case.get("exit_code"),
                "passed": case.get("passed"),
                "payload_sha256": case.get("payload_sha256"),
            }
        )
    if not rows:
        rows.append(
            common
            | {
                "case": "preflight",
                "profile": None,
                "expected": None,
                "actual": None,
                "exit_code": None,
                "passed": False,
                "payload_sha256": None,
            }
        )
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in rows
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="grift-intake-parity-") as raw_workspace:
        workspace = Path(raw_workspace)
        try:
            report = run_parity(
                companion_root=args.companion_root.resolve(),
                workspace=workspace,
                expected_companion_sha=args.expected_companion_sha,
                expected_sender_sha=args.expected_sender_sha,
                require_companion_clean=args.require_companion_clean,
            )
        except ParityError as exc:
            report = {
                "schema_version": "tep-intake-contract-parity-v1",
                "status": "CANNOT_VERIFY",
                "error": str(exc),
            }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.result is not None:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(rendered, encoding="utf-8")
    if args.ledger is not None:
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        args.ledger.write_text(_ledger_text(report), encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report.get("status") == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
