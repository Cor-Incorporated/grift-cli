#!/usr/bin/env python3
"""Build and audit the v0.6 blind-pilot evidence without touching source repos.

The program deliberately has three separated inputs:

* a pool declaration (which asserts an ownership/use-right category),
* a pre-observation questionnaire response, and
* later, a measurement result file.

It never clones, fetches, checks out, or writes a candidate repository.  Its
``inventory`` command only asks Git for the current OID, origin and shallow
state, so an operator can pin the input before running the product elsewhere.
``audit`` never turns an old free-text response into an identity or role claim:
unasked fields remain ``NOT_ANSWERED``.  ``summarize`` makes the release gates
mechanical once independently produced measurement records are supplied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11 is required.
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "docs" / "pilot" / "pool.toml"
DEFAULT_ANSWERS = ROOT / "docs" / "pilot" / "ANSWERS-20260822.csv"
DEFAULT_DRAW = ROOT / "docs" / "pilot" / "DRAW-20260822.json"
NOT_ANSWERED = "NOT_ANSWERED"
REQUIRED_ROLE_CELLS = (
    "domain",
    "work_type",
    "time",
    "process_position",
)
REQUIRED_QUESTION_KEYS = (
    "authority",
    "local_measurement_authorized",
    "identity_consent",
    "identity_subject",
    "disclosure",
    "startup",
    "handoff",
    "role.domain",
    "role.work_type",
    "role.time",
    "role.process_position",
    "ai_primary_method",
    "ai_trailer_memory",
)
AUTHORITY_VALUES = {"owner", "authorised_operator", "not_authorised"}
DISCLOSURE_VALUES = {"local_only", "controlled_only", "named_public"}
STARTUP_VALUES = {"from_scratch", "template", "fork", "inherited"}
HANDOFF_VALUES = {"none", "minor", "substantial", "mostly_other"}
YES_NO_VALUES = {"yes", "no"}
ROLE_VALUES = {
    "domain": {"core", "test", "docs", "infra", "deps", "unclassified"},
    "work_type": {"create", "modify", "rename", "test", "dependency", "corrective"},
    "time": {"early", "middle", "recent"},
    "process_position": {"creator", "maintainer", "integrator", "release"},
}
STRUCTURED_RESPONSE_KEYS = {
    "repo_id",
    "target_oid",
    "authority",
    "local_measurement_authorized",
    "identity_consent",
    "identity_subject",
    "disclosure",
    "startup",
    "handoff",
    "context_note",
    "role",
    "role_rationale",
    "ai_primary_method",
    "ai_trailer_memory",
    "ai_trailer_convention",
}


@dataclass(frozen=True)
class Candidate:
    repo_id: str
    directory: str
    rights: str
    remote_declared: str
    required_reference: bool


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _artifact_source_label(path: Path) -> str:
    """Keep evidence relocatable and avoid publishing workstation paths."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def draw_candidate_names(draw_path: Path) -> list[str]:
    """Load the preregistered draw plus mandatory reference repositories."""

    try:
        payload = json.loads(draw_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"blind-pilot draw is unreadable: {draw_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "pilot-draw-v1":
        raise ValueError("blind-pilot draw must use pilot-draw-v1")
    picked = payload.get("picked")
    references = payload.get("references")
    if not isinstance(picked, list) or not isinstance(references, list):
        raise ValueError("blind-pilot draw requires picked and references arrays")
    names: list[str] = []
    for index, row in enumerate(picked):
        if not isinstance(row, dict) or not isinstance(row.get("dir"), str) or not row["dir"]:
            raise ValueError(f"blind-pilot draw picked[{index}].dir is invalid")
        names.append(row["dir"])
    for index, value in enumerate(references):
        if not isinstance(value, str) or not value:
            raise ValueError(f"blind-pilot draw references[{index}] is invalid")
        names.append(value)
    if len(names) != len(set(names)):
        raise ValueError("blind-pilot draw contains duplicate repositories")
    if not 10 <= len(names) <= 15:
        raise ValueError("blind-pilot draw must contain 10..15 repositories including references")
    for required in ("BenevolentDirector", "corsweb"):
        if required not in names:
            raise ValueError(f"blind-pilot draw omits mandatory reference: {required}")
    return names


def selected_candidates(pool_path: Path, names: list[str] | None = None) -> list[Candidate]:
    """Return declared company/personal candidates, with required references first."""

    requested = set(names or [])
    rows: list[Candidate] = []
    for item in _read_toml(pool_path).get("repos", []):
        directory = str(item.get("dir", ""))
        if not directory or item.get("rights") not in {"company", "personal"}:
            continue
        if requested and directory not in requested:
            continue
        rows.append(
            Candidate(
                # A local directory is the stable pilot key.  A forge/project
                # display alias (for example ``corsweb2024``) must not split
                # questionnaire and inventory records for the same repository.
                repo_id=directory,
                directory=directory,
                rights=str(item["rights"]),
                remote_declared=str(item.get("remote", "")),
                required_reference=bool(item.get("reference", False)),
            )
        )
    if requested:
        found = {row.directory for row in rows}
        missing = sorted(requested - found)
        if missing:
            raise ValueError(
                f"candidate(s) absent or not declared company/personal: {', '.join(missing)}"
            )
    rows.sort(key=lambda row: (not row.required_reference, row.directory.casefold()))
    return rows


def _safe_candidate_path(developer_root: Path, directory: str) -> Path:
    root = developer_root.resolve()
    candidate = (root / directory).resolve()
    if candidate.parent != root:
        raise ValueError(f"candidate escapes developer root: {directory}")
    return candidate


def _git(repo: Path, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or completed.stderr).strip()
    return completed.returncode, output


def inventory(
    candidates: list[Candidate],
    developer_root: Path,
    pins: dict[str, str] | None = None,
    *,
    pool_path: Path = DEFAULT_POOL,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read current Git pins.  No network or mutating Git command is used."""

    rows: list[dict[str, Any]] = []
    pins = pins or {}
    for candidate in candidates:
        repo = _safe_candidate_path(developer_root, candidate.directory)
        row: dict[str, Any] = {
            "repo_id": candidate.repo_id,
            "directory": candidate.directory,
            "rights_declared": candidate.rights,
            "authority_status": "DECLARED_IN_POOL_NEEDS_QUESTIONNAIRE_CONFIRMATION",
            "required_reference": candidate.required_reference,
            "remote_declared": candidate.remote_declared,
        }
        if not repo.is_dir():
            row.update({"status": "MISSING", "target_oid": None, "shallow": None, "origin": None})
            rows.append(row)
            continue
        oid_code, oid = _git(repo, "rev-parse", "HEAD")
        shallow_code, shallow = _git(repo, "rev-parse", "--is-shallow-repository")
        origin_code, origin = _git(repo, "remote", "get-url", "origin")
        pinned = pins.get(candidate.directory)
        pin_code, _pin_message = (0, "")
        if pinned and oid_code == 0:
            pin_code, _pin_message = _git(repo, "cat-file", "-e", f"{pinned}^{{commit}}")
        row.update(
            {
                "status": (
                    "PINNED"
                    if oid_code == 0 and (not pinned or pin_code == 0)
                    else "PIN_NOT_PRESENT"
                    if oid_code == 0
                    else "NOT_A_GIT_REPOSITORY"
                ),
                "target_oid": pinned
                if pinned and pin_code == 0
                else oid
                if oid_code == 0
                else None,
                "observed_head_oid": oid if oid_code == 0 else None,
                "pin_source": "operator_supplied" if pinned else "observed_head",
                "shallow": shallow if shallow_code == 0 else "unknown",
                "origin": origin if origin_code == 0 else None,
            }
        )
        rows.append(row)
    return {
        "schema_version": "tep-v060-blind-pilot-inventory-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source": {
            "pool": _artifact_source_label(pool_path),
            "network": "not_used",
            "git_mutation": "not_used",
        },
        "selection": selection or {"kind": "explicit_candidates", "candidate_count": len(rows)},
        "candidate_count": len(rows),
        "required_references": ["BenevolentDirector", "corsweb"],
        "candidates": rows,
    }


def parse_pins(raw_pins: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in raw_pins:
        directory, separator, oid = raw.partition("=")
        if (
            not separator
            or not directory
            or len(oid) not in {40, 64}
            or any(char not in "0123456789abcdef" for char in oid)
        ):
            raise ValueError("--pin must be DIRECTORY=<40-or-64-lowercase-hex-OID>")
        if directory in pins:
            raise ValueError(f"duplicate --pin for {directory}")
        pins[directory] = oid
    return pins


def legacy_answers(path: Path) -> dict[str, dict[str, str]]:
    """Read old answers verbatim; no role/identity inference is allowed."""

    with path.open(encoding="utf-8", newline="") as handle:
        return {row["dir"]: row for row in csv.DictReader(handle)}


def _generic_oid(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field} must be a 40-or-64-lowercase-hex Git OID")
    return value


def structured_answers(path: Path) -> dict[str, dict[str, Any]]:
    """Read the closed pre-observation response format without identity inference."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"structured blind-pilot answers are unreadable: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "responses"}:
        raise ValueError("structured answers require only schema_version and responses")
    if payload["schema_version"] != "tep-v060-blind-pilot-answers-v1":
        raise ValueError("structured answers must use tep-v060-blind-pilot-answers-v1")
    responses = payload["responses"]
    if not isinstance(responses, list):
        raise ValueError("structured answers responses must be an array")
    result: dict[str, dict[str, Any]] = {}
    for index, response in enumerate(responses):
        label = f"responses[{index}]"
        if not isinstance(response, dict):
            raise ValueError(f"{label} must be an object")
        unknown = sorted(set(response) - STRUCTURED_RESPONSE_KEYS)
        missing = sorted(STRUCTURED_RESPONSE_KEYS - set(response))
        if unknown or missing:
            raise ValueError(f"{label} closed fields differ: missing={missing}, unknown={unknown}")
        repo_id = response["repo_id"]
        if not isinstance(repo_id, str) or not repo_id or repo_id in result:
            raise ValueError(f"{label}.repo_id is empty or duplicate")
        _generic_oid(response["target_oid"], field=f"{label}.target_oid")
        if response["authority"] not in AUTHORITY_VALUES:
            raise ValueError(f"{label}.authority is invalid")
        if not isinstance(response["local_measurement_authorized"], bool):
            raise ValueError(f"{label}.local_measurement_authorized must be boolean")
        if response["identity_consent"] not in YES_NO_VALUES:
            raise ValueError(f"{label}.identity_consent is invalid")
        subject = response["identity_subject"]
        if not isinstance(subject, str) or not subject or subject == NOT_ANSWERED:
            raise ValueError(f"{label}.identity_subject must be an explicit subject or DECLINED")
        if response["identity_consent"] == "yes" and subject == "DECLINED":
            raise ValueError(f"{label}.identity_subject cannot be DECLINED when consent is yes")
        if response["identity_consent"] == "no" and subject != "DECLINED":
            raise ValueError(f"{label}.identity_subject must be DECLINED when consent is no")
        if response["disclosure"] not in DISCLOSURE_VALUES:
            raise ValueError(f"{label}.disclosure is invalid")
        if response["startup"] not in STARTUP_VALUES:
            raise ValueError(f"{label}.startup is invalid")
        if response["handoff"] not in HANDOFF_VALUES:
            raise ValueError(f"{label}.handoff is invalid")
        if not isinstance(response["context_note"], str):
            raise ValueError(f"{label}.context_note must be a string")
        role = response["role"]
        rationale = response["role_rationale"]
        if not isinstance(role, dict) or set(role) != set(ROLE_VALUES):
            raise ValueError(f"{label}.role must contain the four closed dimensions")
        if not isinstance(rationale, dict) or set(rationale) != set(ROLE_VALUES):
            raise ValueError(f"{label}.role_rationale must contain the four closed dimensions")
        for dimension, allowed in ROLE_VALUES.items():
            selected = role[dimension]
            if (
                not isinstance(selected, list)
                or len(selected) != len(set(selected))
                or any(not isinstance(value, str) or value not in allowed for value in selected)
            ):
                raise ValueError(f"{label}.role.{dimension} is invalid")
            reason = rationale[dimension]
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{label}.role_rationale.{dimension} is required")
        if response["ai_primary_method"] not in YES_NO_VALUES:
            raise ValueError(f"{label}.ai_primary_method is invalid")
        if response["ai_trailer_memory"] not in YES_NO_VALUES:
            raise ValueError(f"{label}.ai_trailer_memory is invalid")
        if not isinstance(response["ai_trailer_convention"], str):
            raise ValueError(f"{label}.ai_trailer_convention must be a string")
        result[repo_id] = response
    return result


def questionnaire_audit(
    candidates: list[Candidate],
    answers_path: Path,
    *,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    structured = answers_path.suffix.casefold() == ".json"
    answers: dict[str, dict[str, Any]] = (
        structured_answers(answers_path) if structured else legacy_answers(answers_path)
    )
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        old = answers.get(candidate.directory)
        answered: dict[str, Any] = {key: NOT_ANSWERED for key in REQUIRED_QUESTION_KEYS}
        legacy: dict[str, str] = {}
        blocking_reasons: list[str] = []
        target_oid: str | None = None
        role_rationale: dict[str, str] | None = None
        if old and structured:
            target_oid = str(old["target_oid"])
            answered.update(
                {
                    "authority": old["authority"],
                    "local_measurement_authorized": old["local_measurement_authorized"],
                    "identity_consent": old["identity_consent"],
                    "identity_subject": old["identity_subject"],
                    "disclosure": old["disclosure"],
                    "startup": old["startup"],
                    "handoff": old["handoff"],
                    "role.domain": old["role"]["domain"],
                    "role.work_type": old["role"]["work_type"],
                    "role.time": old["role"]["time"],
                    "role.process_position": old["role"]["process_position"],
                    "ai_primary_method": old["ai_primary_method"],
                    "ai_trailer_memory": old["ai_trailer_memory"],
                }
            )
            role_rationale = dict(old["role_rationale"])
            if old["authority"] == "not_authorised":
                blocking_reasons.append("repository_authority_not_granted")
            if not old["local_measurement_authorized"]:
                blocking_reasons.append("local_measurement_not_authorized")
            if old["identity_consent"] != "yes":
                blocking_reasons.append("identity_consent_not_granted")
        elif old:
            # These three questions were actually asked in the legacy form.
            answered["startup"] = old.get("立ち上げ", NOT_ANSWERED) or NOT_ANSWERED
            answered["handoff"] = old.get("引き継ぎ範囲", NOT_ANSWERED) or NOT_ANSWERED
            answered["ai_primary_method"] = old.get("AI併用", NOT_ANSWERED) or NOT_ANSWERED
            legacy = {
                "current_state": old.get("現在の状況", ""),
                "role_free_text": old.get("役割構成の実感・補足", ""),
            }
        missing = [key for key, value in answered.items() if value == NOT_ANSWERED]
        ready = not missing and not blocking_reasons
        rows.append(
            {
                "repo_id": candidate.repo_id,
                "directory": candidate.directory,
                "legacy_response_present": old is not None,
                "answer_format": "structured-v1" if structured else "legacy-csv",
                "target_oid": target_oid,
                "answers": answered,
                "role_rationale": role_rationale,
                "legacy_context_not_mapped_to_role_cells": legacy,
                "missing_required_questions": missing,
                "blocking_reasons": blocking_reasons,
                "status": "READY_FOR_BLIND_MEASUREMENT" if ready else "BLOCKED",
            }
        )
    return {
        "schema_version": "tep-v060-blind-pilot-answer-audit-v1",
        "answers_source": _artifact_source_label(answers_path),
        "answers_sha256": hashlib.sha256(answers_path.read_bytes()).hexdigest(),
        "inference_policy": (
            "closed structured cells are copied exactly; no Git/email/handle/free-text inference"
            if structured
            else "only exactly asked legacy fields are carried forward; free text is not role-mapped"
        ),
        "selection": selection or {"kind": "explicit_candidates", "candidate_count": len(rows)},
        "required_question_keys": list(REQUIRED_QUESTION_KEYS),
        "repos": rows,
        "ready_count": sum(1 for row in rows if row["status"] == "READY_FOR_BLIND_MEASUREMENT"),
        "blocked_count": sum(1 for row in rows if row["status"] != "READY_FOR_BLIND_MEASUREMENT"),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.strip():
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"results line {number} is not an object")
            records.append(value)
    return records


def _is_missing(value: object) -> bool:
    return value is None or (
        isinstance(value, str) and value in {"", NOT_ANSWERED, "NOT_OBSERVED", "NOT_COMPARABLE"}
    )


def summarize_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only supplied result facts; absent evidence stays not proven."""

    per_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        repo_id = record.get("repo_id") or record.get("label")
        if not isinstance(repo_id, str) or not repo_id:
            raise ValueError("each result needs repo_id (or legacy label)")
        per_repo[repo_id].append(record)

    comparisons: list[dict[str, Any]] = []
    repo_rows: list[dict[str, Any]] = []
    for repo_id, rows in sorted(per_repo.items()):
        crash = any(bool(row.get("crashed")) or row.get("exit_code") == -1 for row in rows)
        verify_rows = [row for row in rows if row.get("kind") == "verify"]
        verify_ok = bool(verify_rows) and all(row.get("exit_code") == 0 for row in verify_rows)
        timed = [
            float(row["seconds"])
            for row in rows
            if isinstance(row.get("seconds"), (int, float))
            and not bool(row.get("survival_excluded"))
        ]
        for row in rows:
            for comparison in row.get("comparisons", []):
                if not isinstance(comparison, dict):
                    raise ValueError(f"comparison for {repo_id} is not an object")
                expected, observed = comparison.get("expected"), comparison.get("observed")
                comparable = not _is_missing(expected) and not _is_missing(observed)
                matched = comparable and expected == observed
                item = {
                    "repo_id": repo_id,
                    "cell": comparison.get("cell", "unnamed"),
                    "comparable": comparable,
                    "matched": matched,
                    "mismatch_classification": comparison.get("mismatch_classification"),
                    "explanation": comparison.get("explanation"),
                }
                comparisons.append(item)
        repo_rows.append(
            {
                "repo_id": repo_id,
                "crash": crash,
                "verify_ok": verify_ok,
                "eligible_seconds": round(sum(timed), 3) if timed else None,
                "under_five_minutes": bool(timed) and sum(timed) < 300,
            }
        )

    comparable = [row for row in comparisons if row["comparable"]]
    mismatches = [row for row in comparable if not row["matched"]]
    unexplained = [
        row
        for row in mismatches
        if not isinstance(row["mismatch_classification"], str)
        or not row["mismatch_classification"].strip()
        or not isinstance(row["explanation"], str)
        or not row["explanation"].strip()
    ]
    matched = sum(1 for row in comparable if row["matched"])
    rate = None if not comparable else round(100 * matched / len(comparable), 2)
    gates = {
        "crash_zero": bool(repo_rows) and not any(row["crash"] for row in repo_rows),
        "verify_all_success": bool(repo_rows) and all(row["verify_ok"] for row in repo_rows),
        "under_five_minutes": bool(repo_rows)
        and all(row["under_five_minutes"] for row in repo_rows),
        "match_rate_at_least_80": rate is not None and rate >= 80,
        "all_mismatches_classified": bool(mismatches) and not unexplained if mismatches else True,
        "unexplained_zero": not unexplained,
    }
    return {
        "schema_version": "tep-v060-blind-pilot-summary-v1",
        "repo_count": len(repo_rows),
        "repos": repo_rows,
        "comparison": {
            "comparable_cells": len(comparable),
            "matched_cells": matched,
            "match_rate_percent": rate,
            "mismatch_count": len(mismatches),
            "unexplained_mismatch_count": len(unexplained),
        },
        "gates": gates,
        "pr_ready": all(gates.values()) if repo_rows and comparable else False,
        "limitations": [
            "A missing result is not a pass.",
            "No comparison is counted until a pre-observation answer exists.",
            "This summary does not establish authority, consent, release, or production evidence.",
        ],
    }


def parse_identity_maps(raw_values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in raw_values:
        repo_id, separator, raw_path = raw.partition("=")
        if not separator or not repo_id or not raw_path or repo_id in result:
            raise ValueError("--identity-map must be unique REPO_ID=PATH")
        path = Path(raw_path)
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ValueError(f"identity file is unreadable for {repo_id}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"identity file must be a regular non-symlink for {repo_id}")
        result[repo_id] = path.resolve()
    return result


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_run_inputs(
    *,
    inventory_payload: dict[str, Any],
    audit_payload: dict[str, Any],
    identity_files: dict[str, Path],
    developer_root: Path,
) -> list[dict[str, Any]]:
    if inventory_payload.get("schema_version") != "tep-v060-blind-pilot-inventory-v1":
        raise ValueError("run inventory must use tep-v060-blind-pilot-inventory-v1")
    if audit_payload.get("schema_version") != "tep-v060-blind-pilot-answer-audit-v1":
        raise ValueError("run audit must use tep-v060-blind-pilot-answer-audit-v1")
    inventory_rows = inventory_payload.get("candidates")
    audit_rows = audit_payload.get("repos")
    if not isinstance(inventory_rows, list) or not isinstance(audit_rows, list):
        raise ValueError("run inputs require candidates/repos arrays")
    if audit_payload.get("blocked_count") != 0 or audit_payload.get("ready_count") != len(
        inventory_rows
    ):
        raise ValueError("blind-pilot run is blocked until every structured answer is ready")
    inventory_by_id: dict[str, dict[str, Any]] = {}
    audit_by_id: dict[str, dict[str, Any]] = {}
    for label, rows, target in (
        ("inventory", inventory_rows, inventory_by_id),
        ("audit", audit_rows, audit_by_id),
    ):
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("repo_id"), str):
                raise ValueError(f"{label}[{index}] has no repo_id")
            repo_id = row["repo_id"]
            if not repo_id or repo_id in target:
                raise ValueError(f"{label} has empty or duplicate repo_id")
            target[repo_id] = row
    if set(inventory_by_id) != set(audit_by_id) or set(inventory_by_id) != set(identity_files):
        raise ValueError("inventory, audit, and --identity-map repository sets must match exactly")
    prepared: list[dict[str, Any]] = []
    for repo_id in sorted(inventory_by_id):
        inventory_row = inventory_by_id[repo_id]
        audit_row = audit_by_id[repo_id]
        if inventory_row.get("status") != "PINNED":
            raise ValueError(f"inventory target is not PINNED for {repo_id}")
        target_oid = _generic_oid(
            inventory_row.get("target_oid"), field=f"inventory[{repo_id}].target_oid"
        )
        if audit_row.get("status") != "READY_FOR_BLIND_MEASUREMENT":
            raise ValueError(f"answer audit is not ready for {repo_id}")
        if audit_row.get("answer_format") != "structured-v1":
            raise ValueError(f"legacy answers cannot unlock blind measurement for {repo_id}")
        if audit_row.get("target_oid") != target_oid:
            raise ValueError(f"answer target OID differs from inventory for {repo_id}")
        answers = audit_row.get("answers")
        if not isinstance(answers, dict):
            raise ValueError(f"answers are missing for {repo_id}")
        if (
            answers.get("authority") not in {"owner", "authorised_operator"}
            or answers.get("local_measurement_authorized") is not True
            or answers.get("identity_consent") != "yes"
        ):
            raise ValueError(f"authority or identity consent is not granted for {repo_id}")
        actor_id = answers.get("identity_subject")
        if not isinstance(actor_id, str) or not actor_id or actor_id == "DECLINED":
            raise ValueError(f"identity subject is unavailable for {repo_id}")
        directory = inventory_row.get("directory")
        if not isinstance(directory, str) or not directory:
            raise ValueError(f"inventory directory is missing for {repo_id}")
        repo = _safe_candidate_path(developer_root, directory)
        if not repo.is_dir():
            raise ValueError(f"candidate repository is missing for {repo_id}")
        code, _message = _git(repo, "cat-file", "-e", f"{target_oid}^{{commit}}")
        if code != 0:
            raise ValueError(f"fixed target OID is unavailable for {repo_id}")
        prepared.append(
            {
                "repo_id": repo_id,
                "repo": repo,
                "target_oid": target_oid,
                "actor_id": actor_id,
                "identity": identity_files[repo_id],
                "answers": answers,
            }
        )
    if not 10 <= len(prepared) <= 15:
        raise ValueError("blind-pilot run requires 10..15 prepared repositories")
    return prepared


def _private_output_root(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("blind-pilot output root must be a non-symlink directory")
    if metadata.st_uid != os.getuid():
        raise ValueError("blind-pilot output root must be owned by the current user")
    os.chmod(path, 0o700)
    return path.resolve()


def _run_cli(argv: list[str], *, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    env = {
        key: value
        for key, value in os.environ.items()
        if "TOKEN" not in key.upper() and "AUTH" not in key.upper()
    }
    env["GIT_NO_LAZY_FETCH"] = "1"
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        crashed = exit_code < 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        exit_code = -1
        stdout = ""
        stderr = str(exc)
        crashed = True
    return {
        "exit_code": exit_code,
        "crashed": crashed,
        "seconds": round(time.monotonic() - started, 3),
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
    }


def _artifact_actor_card(collection: Path, actor_id: str) -> dict[str, Any]:
    manifest = _load_json_object(collection / "collection-manifest.json", label="actor manifest")
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or selection.get("actor_ids") != [actor_id]:
        raise ValueError("actor collection selection does not match the questionnaire subject")
    links = selection.get("links")
    if not isinstance(links, list) or len(links) != 1 or not isinstance(links[0], dict):
        raise ValueError("actor collection must contain one selected link")
    if links[0].get("actor_id") != actor_id or not isinstance(links[0].get("json"), str):
        raise ValueError("actor collection link does not match the questionnaire subject")
    relative = Path(links[0]["json"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("actor collection link escapes its root")
    path = (collection / relative).resolve()
    if collection.resolve() not in path.parents:
        raise ValueError("actor collection link escapes its root")
    return _load_json_object(path, label="actor card")


def _role_comparisons(answers: dict[str, Any], card: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    role = card.get("role_profile")
    dimensions = role.get("dimensions") if isinstance(role, dict) else None
    for dimension in REQUIRED_ROLE_CELLS:
        expected_values = answers.get(f"role.{dimension}")
        if not isinstance(expected_values, list):
            continue
        dimension_payload: object = dimensions
        if isinstance(dimensions, dict):
            dimension_payload = dimensions.get(dimension)
            if dimension == "time" and isinstance(dimension_payload, dict):
                dimension_payload = dimension_payload.get("phase")
        for expected in expected_values:
            metric = (
                dimension_payload.get(expected)
                if isinstance(dimension_payload, dict)
                else None
            )
            observed: object = "NOT_OBSERVED"
            if isinstance(metric, dict) and isinstance(metric.get("numerator"), int):
                observed = metric["numerator"] > 0
            comparisons.append(
                {
                    "cell": f"role.{dimension}.{expected}",
                    "expected": True,
                    "observed": observed,
                    "mismatch_classification": None,
                    "explanation": None,
                }
            )
    experience = card.get("experience")
    metrics = experience.get("metrics") if isinstance(experience, dict) else None
    declared = metrics.get("declared_ai_assist_share") if isinstance(metrics, dict) else None
    observed_ai: object = "NOT_OBSERVED"
    if isinstance(declared, dict) and isinstance(declared.get("numerator"), int):
        observed_ai = declared["numerator"] > 0
    remembered = answers.get("ai_trailer_memory")
    comparisons.append(
        {
            "cell": "ai_trailer_memory",
            "expected": True if remembered == "yes" else False if remembered == "no" else None,
            "observed": observed_ai,
            "mismatch_classification": None,
            "explanation": None,
        }
    )
    return comparisons


def run_blind_measurements(
    prepared: list[dict[str, Any]],
    *,
    output_root: Path,
    results_path: Path,
    grift: str,
    timeout: int,
    replace: bool,
) -> list[dict[str, Any]]:
    """Run only fixed-OID, consented local observations and write controlled JSONL."""

    root = _private_output_root(output_root)
    resolved_results = results_path.resolve(strict=False)
    if root != resolved_results.parent and root not in resolved_results.parents:
        raise ValueError("blind-pilot results must stay under the controlled output root")
    if results_path.exists() and not replace:
        raise ValueError("blind-pilot results already exist; pass --replace explicitly")
    if results_path.is_symlink():
        raise ValueError("blind-pilot results must not be a symlink")
    results_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    command_prefix = [sys.executable, "-m", "tep_cli"] if grift == "source" else [grift]
    rows: list[dict[str, Any]] = []
    for ordinal, item in enumerate(prepared, start=1):
        repo_id = str(item["repo_id"])
        run_id = f"{ordinal:02d}-{hashlib.sha256(repo_id.encode('utf-8')).hexdigest()[:12]}"
        repo_output = root / run_id / "repo"
        actor_output = root / run_id / "actor"
        if repo_output.exists() or actor_output.exists():
            raise ValueError(
                f"blind-pilot artifact directory already exists for {repo_id}; use a new --out root"
            )
        repo_output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        base = {
            "repo_id": repo_id,
            "target_oid": item["target_oid"],
            "survival_excluded": False,
        }
        commands = [
            (
                "repo",
                "repo",
                command_prefix
                + [
                    "repo",
                    str(item["repo"]),
                    "--rev",
                    item["target_oid"],
                    "--actors",
                    "--format",
                    "both",
                    "--out",
                    str(repo_output),
                ],
            ),
            (
                "verify",
                "repo",
                command_prefix
                + ["verify", str(repo_output), "--repo", str(item["repo"])],
            ),
            (
                "actor",
                "actor",
                command_prefix
                + [
                    "actor",
                    item["actor_id"],
                    str(item["repo"]),
                    "--identity",
                    str(item["identity"]),
                    "--rev",
                    item["target_oid"],
                    "--format",
                    "both",
                    "--out",
                    str(actor_output),
                ],
            ),
            (
                "verify",
                "actor",
                command_prefix
                + [
                    "verify",
                    str(actor_output),
                    "--repo",
                    str(item["repo"]),
                    "--identity",
                    str(item["identity"]),
                ],
            ),
        ]
        for kind, scope, argv in commands:
            result = _run_cli(argv, timeout=timeout)
            result.update(
                {
                    **base,
                    "kind": kind,
                    "scope": scope,
                    "argv_contract": [
                        "${GRIFT}",
                        kind,
                        "${FIXED_INPUTS_AND_CONTROLLED_OUTPUTS}",
                    ],
                }
            )
            rows.append(result)
        comparisons: list[dict[str, Any]] = []
        actor_run = next(
            row for row in reversed(rows) if row["repo_id"] == repo_id and row["kind"] == "actor"
        )
        if actor_run["exit_code"] == 0:
            try:
                comparisons = _role_comparisons(
                    item["answers"], _artifact_actor_card(actor_output, item["actor_id"])
                )
            except ValueError:
                comparisons = []
        rows.append(
            {
                **base,
                "kind": "compare",
                "scope": "pre_observation_answers_vs_actor_observation",
                "exit_code": 0 if comparisons else 2,
                "crashed": False,
                "seconds": 0.0,
                "comparisons": comparisons,
                "limitations": [
                    "ai_primary_method is respondent context and is never compared with Git trailers.",
                    "A selected role cell is compared only with whether a non-suppressed observed numerator exists.",
                ],
            }
        )
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_TRUNC if replace else os.O_EXCL
    descriptor = os.open(results_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.chmod(results_path, 0o600)
    return rows


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("blind-pilot JSON output must not be a symlink")
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument(
        "--draw",
        type=Path,
        default=None,
        help=(
            "preregistered pilot-draw-v1 selection; the repository default is used "
            "automatically with the default pool"
        ),
    )
    parser.add_argument("--developer-root", type=Path, default=Path.home() / "Developer")
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument(
        "--pin",
        action="append",
        default=[],
        metavar="DIRECTORY=OID",
        help="use an existing commit as the target instead of the observed HEAD",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser(
        "inventory", help="read fixed Git OIDs without mutation"
    )
    inventory_parser.add_argument("--out", type=Path, required=True)
    audit_parser = subparsers.add_parser("audit", help="audit old answers without inference")
    audit_parser.add_argument("--out", type=Path, required=True)
    summary_parser = subparsers.add_parser(
        "summarize", help="aggregate independently produced run JSONL"
    )
    summary_parser.add_argument("--results", type=Path, required=True)
    summary_parser.add_argument("--out", type=Path, required=True)
    run_parser = subparsers.add_parser(
        "run", help="run fixed-OID observations after every structured answer is ready"
    )
    run_parser.add_argument("--inventory", type=Path, required=True)
    run_parser.add_argument("--answer-audit", type=Path, required=True)
    run_parser.add_argument(
        "--identity-map",
        action="append",
        default=[],
        metavar="REPO_ID=PATH",
        help="controlled identity-v2 path; never copied into results",
    )
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--results", type=Path, default=None)
    run_parser.add_argument(
        "--grift",
        default="source",
        help="'source' uses the current python -m tep_cli; otherwise an installed grift executable",
    )
    run_parser.add_argument("--timeout", type=int, default=300)
    run_parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)

    selected_names: list[str] | None = args.candidate or None
    draw_path = args.draw
    if (
        selected_names is None
        and draw_path is None
        and args.pool.resolve() == DEFAULT_POOL.resolve()
    ):
        draw_path = DEFAULT_DRAW
    if selected_names is None and draw_path is not None:
        selected_names = draw_candidate_names(draw_path)
    candidates = selected_candidates(args.pool, selected_names)
    if draw_path is not None:
        selection = {
            "kind": "preregistered_draw",
            "source": _artifact_source_label(draw_path),
            "sha256": hashlib.sha256(draw_path.read_bytes()).hexdigest(),
            "candidate_count": len(candidates),
        }
    else:
        selection = {"kind": "explicit_candidates", "candidate_count": len(candidates)}
    pins = parse_pins(args.pin)
    unknown_pins = sorted(set(pins) - {candidate.directory for candidate in candidates})
    if unknown_pins:
        parser.error(f"--pin is not a selected candidate: {', '.join(unknown_pins)}")
    if args.command == "inventory":
        _write_json(
            args.out,
            inventory(
                candidates,
                args.developer_root,
                pins,
                pool_path=args.pool,
                selection=selection,
            ),
        )
        return 0
    if args.command == "audit":
        _write_json(
            args.out,
            questionnaire_audit(candidates, args.answers, selection=selection),
        )
        return 0
    if args.command == "summarize":
        _write_json(args.out, summarize_results(_read_jsonl(args.results)))
        return 0
    if args.command == "run":
        if args.timeout < 1 or args.timeout > 600:
            parser.error("--timeout must be between 1 and 600 seconds")
        try:
            identities = parse_identity_maps(args.identity_map)
            prepared = _validate_run_inputs(
                inventory_payload=_load_json_object(args.inventory, label="pilot inventory"),
                audit_payload=_load_json_object(args.answer_audit, label="answer audit"),
                identity_files=identities,
                developer_root=args.developer_root,
            )
            results = args.results or (args.out / "results.jsonl")
            rows = run_blind_measurements(
                prepared,
                output_root=args.out,
                results_path=results,
                grift=args.grift,
                timeout=args.timeout,
                replace=args.replace,
            )
        except ValueError as exc:
            parser.error(str(exc))
        crashed = sum(1 for row in rows if row.get("crashed"))
        failed = sum(1 for row in rows if row.get("exit_code") != 0)
        print(
            f"blind-pilot run wrote {results} rows={len(rows)} "
            f"crashed={crashed} nonzero={failed}"
        )
        return 1 if crashed or failed else 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
