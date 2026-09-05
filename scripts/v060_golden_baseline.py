#!/usr/bin/env python3
"""Approved baseline migration for the offline v0.6 CLI golden fixture.

The golden runner never updates its baseline automatically
(``baseline_update: forbidden_automatic``).  When a reviewed schema or
definition change intentionally alters CLI output, this tool re-records the
observation as the new expected baseline and rewrites the closed
``registered_files`` hash registry.

Required workflow (GOLD-01):

1. Run ``scripts/v060_golden.py`` and save the result JSON.
2. Review every drift row.  D3/D4 rows must map to an approved requirement
   in ``docs/REQUIREMENTS-v060.md``; quote that requirement ID here.
3. Re-run this tool with an explicit migration ID, human/committee approver,
   approval timestamp, and one or more approved requirement IDs.
4. Commit the fixture, manifest, and the migration record together.

The tool refuses to run unless the current drift is exactly reproduced by
the observation it is about to freeze, and it records the drift summary in
``benchmarks/v060/golden/migrations.json`` so the approved diff stays
auditable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v060_golden  # noqa: E402

MIGRATIONS_PATH = ROOT / "benchmarks" / "v060" / "golden" / "migrations.json"


def _serialize(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(body: bytes) -> str:
    import hashlib

    return hashlib.sha256(body).hexdigest()


def _atomic_replace_bytes(path: Path, body: bytes) -> None:
    """Durably stage one file before replacing its active path."""

    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="Golden case id to re-baseline.")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Write the new expected baseline and manifest hashes.",
    )
    parser.add_argument(
        "--requirement",
        action="append",
        default=[],
        help="REQUIREMENTS-v060.md requirement ID that approves this migration.",
    )
    parser.add_argument("--migration-id", default=None, help="Unique append-only migration ID.")
    parser.add_argument(
        "--approved-by",
        default=None,
        help="Human/committee authority, e.g. human:release-owner.",
    )
    parser.add_argument(
        "--approved-at",
        default=None,
        help="RFC 3339 approval timestamp with timezone.",
    )
    args = parser.parse_args(argv)
    if args.approve and not all(
        (args.requirement, args.migration_id, args.approved_by, args.approved_at)
    ):
        parser.error(
            "--approve requires --migration-id, --approved-by, --approved-at, and --requirement"
        )

    manifest_path = ROOT / "benchmarks" / "v060" / "golden" / "manifest.json"
    manifest = v060_golden.load_manifest(manifest_path)
    case = next((row for row in manifest["cases"] if row["id"] == args.case), None)
    if case is None:
        print(f"unknown golden case: {args.case}", file=sys.stderr)
        return 2
    root = Path(manifest["_manifest_path"]).parent

    with tempfile.TemporaryDirectory(prefix="grift-v060-baseline-") as temporary:
        workspace = Path(temporary)
        observed = v060_golden.observe_case(
            case, root=root, workspace=workspace, python=Path(sys.executable)
        )
    expected = v060_golden._read_json(root / case["expected"], label="golden expected")
    differences = v060_golden.compare_observation(expected, observed)
    counts: dict[str, int] = {key: 0 for key in ("D0", "D1", "D2", "D3", "D4")}
    for item in differences:
        counts[item["class"]] += 1
    summary = {
        "case_id": case["id"],
        "verdict": v060_golden._verdict(differences),
        "drift_counts": counts,
        "difference_count": len(differences),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    for item in differences:
        print(
            f"  {item['class']} {item['path']}\n"
            f"    expected={json.dumps(item['expected'], ensure_ascii=False, sort_keys=True)}\n"
            f"    actual  ={json.dumps(item['actual'], ensure_ascii=False, sort_keys=True)}"
        )
    if not args.approve:
        print(
            "dry-run only; explicit migration ID, approval metadata, and requirement IDs "
            "are required to freeze this observation"
        )
        return 0 if not differences else 1
    if counts["D4"] < 1:
        print("baseline migration rejected: current drift has no D4 change", file=sys.stderr)
        return 2

    expected_path = root / case["expected"]
    body = _serialize(observed)
    old_expected_body = expected_path.read_bytes()
    old_expected_digest = _sha256_bytes(old_expected_body)
    new_expected_digest = _sha256_bytes(body)
    manifest_body = manifest_path.read_text(encoding="utf-8")
    migrations_body = MIGRATIONS_PATH.read_bytes()
    manifest_payload = json.loads(manifest_body)
    migrations = dict(manifest["_migration_log"])
    migrations.pop("_path", None)
    migrations.pop("_sha256", None)
    previous_record = migrations["entries"][-1]["record_sha256"]
    requirements = sorted(set(args.requirement))
    entry = {
        "migration_id": args.migration_id,
        "case_id": case["id"],
        "old_expected_state": "registered",
        "old_expected_sha256": old_expected_digest,
        "new_expected_sha256": new_expected_digest,
        "registered_files": {
            case["fixture"]: manifest["registered_files"][case["fixture"]],
            case["expected"]: new_expected_digest,
        },
        **summary,
        "approval": {
            "status": "approved",
            "approved_by": args.approved_by,
            "approved_at": args.approved_at,
            "requirements": requirements,
        },
        "previous_entry_sha256": previous_record,
    }
    entry["record_sha256"] = v060_golden._migration_record_sha256(entry)
    migrations["entries"].append(entry)
    new_migrations = _serialize(migrations)
    manifest_payload["registered_files"][case["expected"]] = new_expected_digest
    manifest_payload["migration_log"]["sha256"] = _sha256_bytes(new_migrations)
    new_manifest = _serialize(manifest_payload)

    originals = {
        expected_path: old_expected_body,
        MIGRATIONS_PATH: migrations_body,
        manifest_path: manifest_body.encode("utf-8"),
    }
    try:
        _atomic_replace_bytes(expected_path, body)
        _atomic_replace_bytes(MIGRATIONS_PATH, new_migrations)
        _atomic_replace_bytes(manifest_path, new_manifest)
        v060_golden.load_manifest(manifest_path)
    except (OSError, v060_golden.GoldenContractError) as exc:
        rollback_errors = []
        for path, original in originals.items():
            try:
                _atomic_replace_bytes(path, original)
            except OSError as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        detail = f"; rollback errors: {rollback_errors}" if rollback_errors else ""
        print(f"migration transaction rejected and rolled back: {exc}{detail}", file=sys.stderr)
        return 2
    print(
        f"baseline frozen for {case['id']} "
        f"(migration {args.migration_id}, requirements {','.join(requirements)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
