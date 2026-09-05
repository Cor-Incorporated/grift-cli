"""grift benchmark list|inspect|validate. Offline pack only."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

from tep_core.archive_events import load_archive_events, summarize_archive
from tep_core.benchmark import (
    catalog,
    find_entry,
    load_manifest,
    resolve_registered,
    validate_manifest,
)
from tep_core.event_rhythm import event_rhythm
from tep_core.role_validation import validate_role_sample
from tep_core.secrets_guard import InputValidationError
from tep_core.tracker_lifecycle import load_tracker_lifecycle, summarize_lifecycle


def _fail(message: str) -> int:
    sys.stderr.write(message if message.endswith("\n") else message + "\n")
    return 2


def _dump(payload: object) -> int:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


def _alignment_rows(manifest: dict) -> list[dict]:
    path = resolve_registered(manifest, "data/alignment_cases.jsonl")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        observed = case.get("observed") or {}
        requirements = case.get("requirements") or {}
        for axis, requirement in requirements.items():
            rows.append(
                {
                    "axis": axis,
                    "requirement": requirement,
                    "observed": observed.get(axis) or observed,
                    "unit": "fixture",
                    "source": observed.get("source"),
                    "n": observed.get("active_days"),
                    "coverage": observed.get("confidence") or "fixture_only",
                    "limitations": case.get("expected_assertions") or [],
                    "fixture_kind": case.get("fixture_kind"),
                    "case_id": case.get("case_id"),
                }
            )
    return rows


def inspect_source(source_id: str, manifest_path: Path | None) -> dict:
    manifest = load_manifest(manifest_path)
    entry = find_entry(manifest, source_id)
    payload: dict = {"catalog": entry, "offline": True}
    artifact = entry.get("artifact")
    if artifact == "data/gharchive_events_2024-01-15_to_21.ndjson":
        path = resolve_registered(manifest, artifact)
        bundle = load_archive_events(path)
        payload["event_observation"] = summarize_archive(bundle)
        payload["event_rhythm"] = event_rhythm(bundle)
    elif artifact == "data/role_ground_truth_sample.csv":
        path = resolve_registered(manifest, artifact)
        payload["role_validation"] = validate_role_sample(path)
    elif source_id == "tawos-v1-1":
        path = resolve_registered(manifest, "data/tracker_lifecycle_fixture.csv")
        payload["tracker_lifecycle"] = summarize_lifecycle(load_tracker_lifecycle(path))
    if source_id in {"numfocus-2022-to-2024", "tawos-v1-1"} or "alignment" in source_id:
        payload["alignment_cases"] = _alignment_rows(manifest)
        payload["alignment_cases_note"] = "axis rows only; no overall score"
    return payload


def run_benchmark(args: Namespace) -> int:
    try:
        command = args.benchmark_command
        if command == "list":
            manifest = load_manifest(args.manifest)
            return _dump(
                {
                    "pack_id": manifest["pack_id"],
                    "pack_version": manifest["pack_version"],
                    "as_of": manifest["as_of"],
                    "artifacts": catalog(manifest),
                }
            )
        if command == "inspect":
            return _dump(inspect_source(args.source_id, getattr(args, "manifest", None)))
        if command == "validate":
            path = args.manifest
            if path is None:
                path = None
            return _dump(validate_manifest(path))
        return _fail("unknown benchmark command")
    except InputValidationError as exc:
        return _fail(str(exc))
