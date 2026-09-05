from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tep_core.schema import load_schema, validate_schema


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v060_provider_live_gate_public_export_tested",
    ROOT / "scripts" / "v060_provider_live_gate.py",
)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(ROOT / "scripts"))
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)
matrix = importlib.import_module("v060_scenario_matrix")


COLLECTION_MEMBERS = (
    "actor-index.json",
    "actor-index.md",
    "collection-manifest.json",
    "repo-report.json",
    "repo-report.md",
)


def _sha256_file(path: Path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def _committed_source(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    inventory = matrix._commit_source_inventory(ROOT, head)
    runner = {
        "tool_version": "0.6.0",
        "source_binding": {
            "definition_version": matrix.SOURCE_BINDING_DEFINITION_VERSION,
            "source_tree_digest": matrix._source_digest(inventory),
            "file_count": len(inventory),
            "commit_oid": {"algorithm": "sha1", "value": head},
        },
    }
    monkeypatch.setattr(matrix, "build_runner_binding", lambda _root: copy.deepcopy(runner))
    monkeypatch.setattr(gate, "build_runner_binding", lambda _root: copy.deepcopy(runner))
    source = {
        "tool_version": runner["tool_version"],
        **copy.deepcopy(runner["source_binding"]),
    }
    return source, runner


def _state(
    spec: Any,
    raw_root: Path,
    phase: str,
    stable: dict[str, str],
) -> dict[str, Any]:
    output_sha256 = {
        relative: _sha256_file(
            raw_root / spec.scenario_id / phase / relative,
            f"{spec.scenario_id}:{phase}:{relative}\n".encode(),
        )
        for relative in COLLECTION_MEMBERS
    }
    # Live and replay actor artifacts must be byte-for-byte stable.
    if phase in {"live", "replay"}:
        for relative in ("actor-index.json", "actor-index.md"):
            output_sha256[relative] = stable.setdefault(relative, output_sha256[relative])
    return {
        "counts": {
            "report.human_nonmerge": spec.counts.human_nonmerge,
            "report.merge": spec.counts.human_merge,
            "report.bot": spec.counts.bots,
            "actors.full": spec.counts.actors,
        },
        "partition_digest": "1" * 64,
        "sha_to_actor_digest": "2" * 64,
        "population_digest": "3" * 64,
        "target_oid": spec.target_oid,
        "merge_basis": gate.MERGE_BASIS,
        "output_sha256": output_sha256,
        "repo_provider_independent_digest": "a" * 64,
        "repo_provider_independent_numeric_digest": "b" * 64,
        "actor_provider_independent_digest": "c" * 64,
        "actor_provider_independent_numeric_digest": "d" * 64,
        "license_evidence_digest": "9" * 64,
        "account_counts": {"stable": 0, "public_handle_actors": 0, "statuses": {}},
    }


def _synthetic_result(
    spec: Any,
    raw_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    stable: dict[str, str] = {}
    states = {
        phase: _state(spec, raw_root, phase, stable) for phase in ("offline", "live", "replay")
    }
    license_digest = _sha256_file(
        raw_root / spec.scenario_id / "license" / "LICENSE",
        f"synthetic license for {spec.scenario_id}\n".encode(),
    )
    for state in states.values():
        state["license_evidence_digest"] = license_digest

    manifest_digest = _sha256_file(
        raw_root / spec.scenario_id / "public-evidence" / "manifest.json",
        json.dumps(
            {"scenario_id": spec.scenario_id, "pages": spec.expected_pages},
            sort_keys=True,
        ).encode(),
    )
    page_digests = [
        _sha256_file(
            raw_root
            / spec.scenario_id
            / "public-evidence"
            / "blobs"
            / "sha256"
            / f"page-{number:02d}.body",
            f"{spec.scenario_id}:provider-page:{number}\n".encode(),
        )
        for number in range(1, spec.expected_pages + 1)
    ]
    payload_digest = _sha256_file(
        raw_root / spec.scenario_id / "public-evidence" / "payload.bin",
        "\n".join(page_digests).encode(),
    )
    provider_evidence = {
        "coverage": spec.expected_coverage,
        "stop_reason": "max_pages_reached" if spec.expected_partial else "no_next_page",
        "pages": spec.expected_pages,
        "items": spec.expected_items,
        "expected_oids": spec.counts.total,
        "observed_oids": spec.counts.total - spec.expected_missing,
        "missing_oids": spec.expected_missing,
        "extra_oids": 0,
        "duplicate_oids": 0,
        "account_linkage": spec.account_linkage,
        "bundle_payload_sha256": payload_digest,
        "manifest_sha256": manifest_digest,
        "page_body_sha256": page_digests,
        "rate_partial": False,
        "resumable": spec.expected_partial,
    }
    exits = gate._expected_exit_contract(spec)
    result = {
        "scenario_id": spec.scenario_id,
        "provider": spec.provider,
        "target_oid": {"algorithm": "sha1", "value": spec.target_oid},
        "timeout_seconds": spec.timeout_seconds,
        "duration_ms": 10,
        "git_counts": {
            "total": spec.counts.total,
            "nonmerge": spec.counts.raw_nonmerge,
            "merge": spec.counts.raw_merge,
        },
        "exit_contract": exits,
        "command_duration_ms": {name: 1 for name in exits},
        "provider_evidence": provider_evidence,
        "states": states,
        "sleep_seconds": 0,
        "collection_mode": "fresh",
        "prior_evidence_digests": None,
        "resumable_partial_staged": False,
        "mismatch_ids": [],
        "outcome": "PASS",
    }
    expected_digests = {
        "derived/license-evidence": {"algorithm": "sha256", "value": license_digest},
        "derived/population": {
            "algorithm": "sha256",
            "value": states["offline"]["population_digest"],
        },
        "derived/sha-to-actor": {
            "algorithm": "sha256",
            "value": states["offline"]["sha_to_actor_digest"],
        },
        "derived/repo-provider-independent": {
            "algorithm": "sha256",
            "value": states["offline"]["repo_provider_independent_digest"],
        },
        "derived/repo-provider-independent-numeric": {
            "algorithm": "sha256",
            "value": states["offline"]["repo_provider_independent_numeric_digest"],
        },
        "derived/actor-provider-independent": {
            "algorithm": "sha256",
            "value": states["offline"]["actor_provider_independent_digest"],
        },
        "derived/actor-provider-independent-numeric": {
            "algorithm": "sha256",
            "value": states["offline"]["actor_provider_independent_numeric_digest"],
        },
        "public-evidence/manifest.json": {
            "algorithm": "sha256",
            "value": manifest_digest,
        },
        "public-evidence/payload": {"algorithm": "sha256", "value": payload_digest},
    }
    for number, digest in enumerate(page_digests, start=1):
        expected_digests[f"public-evidence/page-{number:02d}.body"] = {
            "algorithm": "sha256",
            "value": digest,
        }
    public_phase = "partial" if spec.expected_partial else "live"
    for result_phase, logical_phase in (
        ("offline", "offline"),
        ("live", public_phase),
        ("replay", "replay"),
    ):
        expected_digests.update(
            {
                f"{logical_phase}/{relative}": {"algorithm": "sha256", "value": digest}
                for relative, digest in states[result_phase]["output_sha256"].items()
            }
        )
    return result, expected_digests


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    source, runner = _committed_source(monkeypatch)
    raw_root = tmp_path / "synthetic-private-live-input"
    results: list[dict[str, Any]] = []
    expected: dict[str, Any] = {}
    for spec in gate._selected("pr"):
        result, logical = _synthetic_result(spec, raw_root)
        assert gate.validate_scenario_result(spec, result) == []
        results.append(result)
        expected[spec.scenario_id] = logical
    return results, source, runner, expected, raw_root


def _rebuild_summary(root: Path) -> None:
    result_paths = [
        root / row["id"] / "scenario-result.json"
        for row in json.loads((root / "manifest.json").read_text())["scenarios"]
    ]
    matrix.write_json(
        root / "summary.json", matrix.build_summary(root / "manifest.json", result_paths)
    )


def test_pr_export_is_closed_source_bound_and_digest_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, source, runner, expected, raw_root = _fixture(tmp_path, monkeypatch)
    output_root = tmp_path / "evidence" / "v060" / "scenarios-public"

    summary = gate.export_public_registry("pr", results, source, output_root)

    assert summary == matrix.verify_digest_only_registry(output_root, project_root=ROOT)
    assert summary["counts"] == {
        "total": 3,
        "pass": 3,
        "fail": 0,
        "not_proven": 0,
        "source_drift": 0,
    }
    manifest = json.loads((output_root / "manifest.json").read_text())
    assert manifest == {
        "schema_version": "tep-scenario-manifest-v1",
        "suite_id": "v060-public-live-gates",
        "definition_version": "scenario-public-v2",
        "scenarios": [
            {
                "id": spec.scenario_id,
                "tier": "live-pr",
                "target_oid": {"algorithm": "sha1", "value": spec.target_oid},
                "expected_artifacts": ["scenario-result.json"],
                "timeout_seconds": spec.timeout_seconds,
            }
            for spec in gate._selected("pr")
        ],
    }
    assert {path.relative_to(output_root).as_posix() for path in output_root.rglob("*")} == {
        "manifest.json",
        "summary.json",
        "P01-cloudflare-full",
        "P01-cloudflare-full/scenario-result.json",
        "P02-vite-forced-partial",
        "P02-vite-forced-partial/scenario-result.json",
        "P03-gitlab-release-cli-full",
        "P03-gitlab-release-cli-full/scenario-result.json",
    }
    for source_result in results:
        scenario_id = source_result["scenario_id"]
        public = json.loads((output_root / scenario_id / "scenario-result.json").read_text())
        assert public["schema_version"] == "tep-public-scenario-result-v2"
        assert public["collection_mode"] == "fresh"
        assert public["prior_evidence_digests"] is None
        assert validate_schema("scenario-result-v1", public) == []
        jsonschema = pytest.importorskip("jsonschema")
        assert not list(
            jsonschema.Draft202012Validator(
                load_schema("scenario-result-v1")
            ).iter_errors(public)
        )
        assert public["runner"] == runner
        assert public["output_digests"] == expected[scenario_id]
        assert public["counts"]["provider.pages"] == source_result["provider_evidence"]["pages"]
        assert (
            public["counts"]["actor.full"]
            == source_result["states"]["offline"]["counts"]["actors.full"]
        )
    output_bytes = b"".join(path.read_bytes() for path in output_root.rglob("*") if path.is_file())
    assert str(raw_root).encode() not in output_bytes
    assert b"blobs/sha256" not in output_bytes
    assert not any("blobs" in path.parts for path in output_root.rglob("*"))


def test_export_rejects_tampered_current_source_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, source, _runner, _expected, _raw_root = _fixture(tmp_path, monkeypatch)
    source["source_tree_digest"]["value"] = "f" * 64
    output_root = tmp_path / "public"

    with pytest.raises(
        (gate.GateError, matrix.ScenarioContractError),
        match="source binding|source tree|stale",
    ):
        gate.export_public_registry("pr", results, source, output_root)

    assert not output_root.exists()


def test_public_v2_resume_exports_prior_chain_and_resume_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, source, _runner, _expected, _raw_root = _fixture(tmp_path, monkeypatch)
    resumed = results[0]
    resumed["collection_mode"] = "resume"
    resumed["prior_evidence_digests"] = {
        "manifest": {"algorithm": "sha256", "value": "a" * 64},
        "payload": {"algorithm": "sha256", "value": "b" * 64},
    }
    assert gate.validate_scenario_result(gate._selected("pr")[0], resumed) == []
    output_root = tmp_path / "public"

    gate.export_public_registry("pr", results, source, output_root)

    public = json.loads(
        (output_root / resumed["scenario_id"] / "scenario-result.json").read_text()
    )
    assert public["collection_mode"] == "resume"
    assert public["prior_evidence_digests"] == resumed["prior_evidence_digests"]
    assert "--resume-public-evidence" in public["argv"]
    assert "--fetch-public" not in public["argv"]
    assert matrix.verify_digest_only_registry(output_root, project_root=ROOT)


def test_relabelling_old_result_with_current_source_fails_acquisition_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, source, _runner, _expected, _raw_root = _fixture(tmp_path, monkeypatch)
    output_root = tmp_path / "public"
    gate.export_public_registry("pr", results, source, output_root)
    result_path = output_root / "P01-cloudflare-full" / "scenario-result.json"
    result = json.loads(result_path.read_text())
    result["runner"]["source_binding"]["source_tree_digest"]["value"] = "e" * 64
    result["runner"]["source_binding"]["commit_oid"] = None
    rewritten_runner = copy.deepcopy(result["runner"])
    monkeypatch.setattr(
        matrix,
        "build_runner_binding",
        lambda _root: copy.deepcopy(rewritten_runner),
    )
    matrix.write_json(result_path, result)
    _rebuild_summary(output_root)

    with pytest.raises(matrix.ScenarioContractError, match="acquisition receipt differs"):
        matrix.verify_digest_only_registry(output_root, project_root=ROOT)


def test_public_v2_mode_prior_and_receipt_tampering_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, source, _runner, _expected, _raw_root = _fixture(tmp_path, monkeypatch)
    exported = tmp_path / "public"
    gate.export_public_registry("pr", results, source, exported)

    missing_mode = tmp_path / "missing-mode"
    shutil.copytree(exported, missing_mode)
    missing_path = missing_mode / "P01-cloudflare-full" / "scenario-result.json"
    missing = json.loads(missing_path.read_text())
    missing.pop("collection_mode")
    assert validate_schema("scenario-result-v1", missing)
    jsonschema = pytest.importorskip("jsonschema")
    assert list(
        jsonschema.Draft202012Validator(load_schema("scenario-result-v1")).iter_errors(
            missing
        )
    )
    matrix.write_json(missing_path, missing)
    with pytest.raises(matrix.ScenarioContractError, match="validation failed"):
        _rebuild_summary(missing_mode)

    relabelled = tmp_path / "relabelled-resume"
    shutil.copytree(exported, relabelled)
    relabelled_path = relabelled / "P01-cloudflare-full" / "scenario-result.json"
    result = json.loads(relabelled_path.read_text())
    spec = next(row for row in gate._selected("pr") if row.scenario_id == result["scenario_id"])
    result["collection_mode"] = "resume"
    result["prior_evidence_digests"] = {
        "manifest": {"algorithm": "sha256", "value": "a" * 64},
        "payload": {"algorithm": "sha256", "value": "b" * 64},
    }
    result["argv"] = gate._public_collection_argv(
        spec,
        phase="live",
        collection_mode="resume",
    )
    matrix.write_json(relabelled_path, result)
    _rebuild_summary(relabelled)
    with pytest.raises(matrix.ScenarioContractError, match="acquisition receipt differs"):
        matrix.verify_digest_only_registry(relabelled, project_root=ROOT)


def test_missing_page_digest_and_extra_member_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, source, _runner, _expected, _raw_root = _fixture(tmp_path, monkeypatch)
    exported = tmp_path / "public"
    gate.export_public_registry("pr", results, source, exported)

    missing_page = tmp_path / "missing-page"
    shutil.copytree(exported, missing_page)
    result_path = missing_page / "P01-cloudflare-full" / "scenario-result.json"
    result = json.loads(result_path.read_text())
    result["output_digests"].pop("public-evidence/page-07.body")
    receipt = matrix.public_acquisition_digest(result)["value"]
    receipt_row = next(
        assertion
        for assertion in result["assertions"]
        if assertion["id"] == "acquisition-receipt-digest"
    )
    receipt_row.update({"expected": receipt, "actual": receipt})
    matrix.write_json(result_path, result)
    _rebuild_summary(missing_page)
    with pytest.raises(matrix.ScenarioContractError, match="logical digest registry mismatch"):
        matrix.verify_digest_only_registry(missing_page, project_root=ROOT)

    extra_member = tmp_path / "extra-member"
    shutil.copytree(exported, extra_member)
    (extra_member / "P03-gitlab-release-cli-full" / "raw-provider.json").write_text("{}")
    with pytest.raises(matrix.ScenarioContractError, match="scenario member registry mismatch"):
        matrix.verify_digest_only_registry(extra_member, project_root=ROOT)
