from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXACT_HEAD_ROOT = REPOSITORY_ROOT / "evidence" / "v060" / "exact-head"
EVIDENCE_ROOT = EXACT_HEAD_ROOT / "R04-grift-cli-add5bc0"
SCHEMA_PATH = EXACT_HEAD_ROOT / "historical-exact-head-evidence.schema.json"
MANIFEST_NAME = "historical-evidence-manifest.json"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract_errors(payload: dict[str, Any], schema_path: Path) -> list[Any]:
    jsonschema = pytest.importorskip("jsonschema")
    schema = _load_json(schema_path)
    jsonschema.Draft202012Validator.check_schema(schema)
    return list(jsonschema.Draft202012Validator(schema).iter_errors(payload))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _verify_historical_bundle(evidence_root: Path) -> None:
    manifest_path = evidence_root / MANIFEST_NAME
    manifest = _load_json(manifest_path)

    raw_contract_path = evidence_root / manifest["contract"]["path"]
    _require(not raw_contract_path.is_symlink(), "contract must not be a symlink")
    contract_path = raw_contract_path.resolve()
    expected_contract = evidence_root.parent / SCHEMA_PATH.name
    _require(contract_path == expected_contract.resolve(), "contract path escaped exact-head root")
    _require(_sha256(contract_path) == manifest["contract"]["sha256"], "contract digest mismatch")

    manifest_errors = _contract_errors(manifest, contract_path)
    _require(not manifest_errors, f"historical manifest schema mismatch: {manifest_errors}")

    result = _load_json(evidence_root / "exact-head-result.json")
    result_errors = _contract_errors(result, contract_path)
    _require(not result_errors, f"historical result schema mismatch: {result_errors}")

    for candidate in evidence_root.rglob("*"):
        _require(not candidate.is_symlink(), f"historical evidence contains symlink: {candidate}")

    members = manifest["artifact_set"]["members"]
    registered_paths = [member["path"] for member in members]
    _require(
        registered_paths == sorted(set(registered_paths)),
        "artifact members must be unique and bytewise sorted",
    )
    _require(
        manifest["artifact_set"]["member_count"] == len(members),
        "artifact member_count mismatch",
    )

    actual_paths = sorted(
        str(candidate.relative_to(evidence_root))
        for candidate in evidence_root.rglob("*")
        if candidate.is_file() and candidate.name != MANIFEST_NAME
    )
    _require(actual_paths == registered_paths, "unregistered or missing historical artifact")

    for member in members:
        relative = PurePosixPath(member["path"])
        _require(not relative.is_absolute(), "absolute artifact path")
        _require(".." not in relative.parts, "artifact path traversal")
        artifact = evidence_root.joinpath(*relative.parts)
        _require(
            artifact.resolve().is_relative_to(evidence_root.resolve()),
            "artifact escaped root",
        )
        _require(artifact.is_file(), "artifact is not a regular file")
        _require(artifact.stat().st_size == member["bytes"], "artifact byte count mismatch")
        _require(_sha256(artifact) == member["sha256"], "artifact digest mismatch")
        expected_media_type = "application/json" if artifact.suffix == ".json" else "text/markdown"
        _require(member["media_type"] == expected_media_type, "artifact media type mismatch")

    canonical_members = "".join(
        f'{member["sha256"]}  {member["path"]}\n' for member in members
    ).encode("utf-8")
    artifact_set_digest = hashlib.sha256(canonical_members).hexdigest()
    _require(
        artifact_set_digest == manifest["artifact_set"]["digest"]["value"],
        "artifact set digest mismatch",
    )

    _require(result["historical_manifest"] == MANIFEST_NAME, "result manifest link mismatch")
    for key in ("evidence_status", "final_evidence_eligible", "consumer_action", "replacement"):
        _require(result[key] == manifest[key], f"result/manifest {key} mismatch")

    for relative_path, expected_digest in result["output_sha256"].items():
        _require(
            _sha256(evidence_root / relative_path) == expected_digest,
            f"result output digest mismatch: {relative_path}",
        )


def test_historical_exact_head_bundle_is_closed_and_digest_bound() -> None:
    _verify_historical_bundle(EVIDENCE_ROOT)


def test_result_is_standalone_machine_rejected_as_final() -> None:
    result = _load_json(EVIDENCE_ROOT / "exact-head-result.json")
    assert _contract_errors(result, SCHEMA_PATH) == []
    assert result["evidence_status"] == "HISTORICAL_NON_FINAL"
    assert result["final_evidence_eligible"] is False
    assert result["consumer_action"] == "REJECT_AS_FINAL"
    assert result["replacement"] == {
        "required_evidence_kind": "external_ci_exact_pr_head",
        "status": "NOT_PROVEN",
    }


@pytest.mark.parametrize(
    ("key", "invalid_value"),
    [
        ("evidence_status", "FINAL"),
        ("final_evidence_eligible", True),
        ("consumer_action", "ACCEPT_AS_FINAL"),
    ],
)
def test_closed_contract_rejects_promotion_to_final(key: str, invalid_value: Any) -> None:
    for filename in ("exact-head-result.json", MANIFEST_NAME):
        payload = _load_json(EVIDENCE_ROOT / filename)
        payload[key] = invalid_value
        assert _contract_errors(payload, SCHEMA_PATH)


def test_closed_contract_rejects_missing_status_unknown_keys_and_path_traversal() -> None:
    manifest = _load_json(EVIDENCE_ROOT / MANIFEST_NAME)

    missing_status = copy.deepcopy(manifest)
    missing_status.pop("evidence_status")
    assert _contract_errors(missing_status, SCHEMA_PATH)

    unknown_key = copy.deepcopy(manifest)
    unknown_key["consumer_policy"]["accept_verified_text"] = True
    assert _contract_errors(unknown_key, SCHEMA_PATH)

    traversal = copy.deepcopy(manifest)
    traversal["artifact_set"]["members"][0]["path"] = "../final-evidence.json"
    assert _contract_errors(traversal, SCHEMA_PATH)


def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    copied_exact_head_root = tmp_path / "exact-head"
    shutil.copytree(EXACT_HEAD_ROOT, copied_exact_head_root)
    copied_evidence_root = copied_exact_head_root / EVIDENCE_ROOT.name

    tampered = copied_evidence_root / "repo-report.md"
    tampered.write_bytes(tampered.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="artifact byte count mismatch"):
        _verify_historical_bundle(copied_evidence_root)
