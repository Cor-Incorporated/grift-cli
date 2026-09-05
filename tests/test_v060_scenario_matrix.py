"""Falsification tests for the reproducible v0.6 real-repository matrix."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tep_core.version import __version__ as TOOL_VERSION

from tep_core.schema import validate_schema

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v060_scenario_matrix.py"
_PUBLIC_EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "v060" / "scenarios-public"
_SPEC = importlib.util.spec_from_file_location("v060_scenario_matrix", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
matrix = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = matrix
_SPEC.loader.exec_module(matrix)


def _git(repo: Path, *args: str) -> str:
    environment = {
        **os.environ,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _two_commit_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q", "--template=")
    _git(repo, "config", "user.name", "Scenario Test")
    _git(repo, "config", "user.email", "scenario@example.test")
    (repo / "tracked.txt").write_text("first\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "first")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "tracked.txt").write_text("second\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "second")
    return repo, first, _git(repo, "rev-parse", "HEAD")


def _spec(target: str) -> matrix.ScenarioSpec:
    return matrix.ScenarioSpec(
        scenario_id="T01-local",
        tier="local",
        repo_relative="fixture",
        target_oid=target,
        expected=matrix.ExpectedCounts(total=2, nonmerge=2, merge=0, actors=1),
        timeout_seconds=30,
        expected_complete=True,
    )


def _result(scenario_id: str, target: str, *, verdict: str = "PASS") -> dict:
    digest = matrix.digest_record(b"partition")
    return {
        "schema_version": "tep-scenario-result-v1",
        "scenario_id": scenario_id,
        "runner": matrix.build_runner_binding(Path(__file__).resolve().parents[1]),
        "target_oid": {"algorithm": "sha1", "value": target},
        "argv": ["python", "-m", "tep_cli", "repo", "${DEVELOPER_ROOT}/fixture"],
        "exit_code": 0,
        "duration_ms": 1,
        "counts": {"git.total": 2},
        "partition_digest": digest,
        "provider_coverage": {
            "kind": "not_observed",
            "provided": False,
            "reason": "public_evidence_not_provided",
        },
        "output_digests": {"repo-report.json": digest},
        "assertions": [
            {
                "id": "runner-tool-version",
                "status": "PASS",
                "expected": TOOL_VERSION,
                "actual": TOOL_VERSION,
            },
            {"id": "git-total", "status": verdict, "expected": 2, "actual": 2},
        ],
        "verdict": verdict,
    }


def _registered_fixture(tmp_path: Path) -> Path:
    target = "a" * 40
    root = tmp_path / "registry"
    scenario_root = root / "T01-local"
    artifact_root = scenario_root / "artifacts"
    actor_root = artifact_root / "actors"
    actor_root.mkdir(parents=True)
    members = {
        "artifacts/repo-report.json": b"{}\n",
        "artifacts/repo-report.md": b"# repo\n",
        "artifacts/actor-index.json": b"{}\n",
        "artifacts/actor-index.md": b"# actors\n",
        "artifacts/collection-manifest.json": b"{}\n",
        "artifacts/actors/a.json": b"{}\n",
        "artifacts/actors/a.md": b"# actor\n",
    }
    for relative, body in members.items():
        path = scenario_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    manifest = matrix.build_manifest([_spec(target)])
    manifest_path = root / "manifest.json"
    matrix.write_json(manifest_path, manifest)
    result = _result("T01-local", target)
    result["output_digests"] = {
        relative: matrix.digest_record(body) for relative, body in members.items()
    }
    result_path = scenario_root / "scenario-result.json"
    matrix.write_json(result_path, result)
    matrix.write_json(root / "summary.json", matrix.build_summary(manifest_path, [result_path]))
    return root


def _digest_only_fixture(tmp_path: Path) -> Path:
    target = "a" * 40
    root = tmp_path / "digest-registry"
    scenario_root = root / "T01-local"
    scenario_root.mkdir(parents=True)
    manifest = matrix.build_manifest([_spec(target)])
    manifest["scenarios"][0]["tier"] = "live-pr"
    manifest["scenarios"][0]["expected_artifacts"] = ["scenario-result.json"]
    manifest_path = root / "manifest.json"
    matrix.write_json(manifest_path, manifest)
    result = _result("T01-local", target)
    result["counts"]["provider.pages"] = 2
    result["provider_coverage"] = {"kind": "observed", "provided": True}
    logical = set(matrix._DIGEST_ONLY_DERIVED)
    for phase in ("offline", "live", "replay"):
        logical.update(f"{phase}/{relative}" for relative in matrix._DIGEST_ONLY_COLLECTION_MEMBERS)
    logical.update(
        {
            "public-evidence/manifest.json",
            "public-evidence/page-01.body",
            "public-evidence/page-02.body",
            "public-evidence/payload",
        }
    )
    result["output_digests"] = {
        relative: matrix.digest_record(relative.encode("utf-8")) for relative in sorted(logical)
    }
    receipt = matrix.public_acquisition_digest(result)
    result["assertions"].append(
        {
            "id": "acquisition-receipt-digest",
            "status": "PASS",
            "expected": receipt["value"],
            "actual": receipt["value"],
        }
    )
    result_path = scenario_root / "scenario-result.json"
    matrix.write_json(result_path, result)
    matrix.write_json(root / "summary.json", matrix.build_summary(manifest_path, [result_path]))
    return root


def test_manifest_and_summary_are_strict_and_register_every_result(tmp_path: Path) -> None:
    target = "a" * 40
    manifest = matrix.build_manifest([_spec(target)])
    assert validate_schema("scenario-manifest-v1", manifest) == []
    manifest_path = tmp_path / "manifest.json"
    matrix.write_json(manifest_path, manifest)
    result_path = tmp_path / "result.json"
    matrix.write_json(result_path, _result("T01-local", target))

    summary = matrix.build_summary(manifest_path, [result_path])
    assert summary["counts"] == {
        "total": 1,
        "pass": 1,
        "fail": 0,
        "not_proven": 0,
        "source_drift": 0,
    }
    assert validate_schema("scenario-summary-v1", summary) == []

    with pytest.raises(matrix.ScenarioContractError, match="missing result"):
        matrix.build_summary(manifest_path, [])
    with pytest.raises(matrix.ScenarioContractError, match="duplicate scenario result"):
        matrix.build_summary(manifest_path, [result_path, result_path])


def test_registry_rejects_missing_unregistered_and_hash_mismatch(tmp_path: Path) -> None:
    root = _registered_fixture(tmp_path)
    summary = matrix.verify_evidence_registry(root)
    assert summary["counts"] == {
        "total": 1,
        "pass": 1,
        "fail": 0,
        "not_proven": 0,
        "source_drift": 0,
    }

    report = root / "T01-local" / "artifacts" / "repo-report.json"
    original = report.read_bytes()
    report.write_bytes(b'{"tampered":true}\n')
    with pytest.raises(matrix.ScenarioContractError, match="artifact hash mismatch"):
        matrix.verify_evidence_registry(root)
    report.write_bytes(original)

    extra = root / "T01-local" / "artifacts" / "unregistered.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(matrix.ScenarioContractError, match="artifact registry mismatch"):
        matrix.verify_evidence_registry(root)
    extra.unlink()

    report.unlink()
    with pytest.raises(matrix.ScenarioContractError, match="artifact registry mismatch"):
        matrix.verify_evidence_registry(root)

    result_root = _registered_fixture(tmp_path / "result-digest")
    result_path = result_root / "T01-local" / "scenario-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["duration_ms"] += 1
    matrix.write_json(result_path, result)
    with pytest.raises(matrix.ScenarioContractError, match="summary digest/count"):
        matrix.verify_evidence_registry(result_root)


def test_registry_rejects_result_from_a_different_tool_source_tree(tmp_path: Path) -> None:
    root = _registered_fixture(tmp_path)
    result_path = root / "T01-local" / "scenario-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["runner"]["source_binding"]["source_tree_digest"]["value"] = "f" * 64
    matrix.write_json(result_path, result)
    result_paths = [result_path]
    matrix.write_json(
        root / "summary.json",
        matrix.build_summary(root / "manifest.json", result_paths),
    )

    with pytest.raises(matrix.ScenarioContractError, match="source binding is stale"):
        matrix.verify_evidence_registry(root)


def test_digest_only_registry_verifies_result_hashes_without_raw_artifacts(
    tmp_path: Path,
) -> None:
    root = _digest_only_fixture(tmp_path)
    summary = matrix.verify_digest_only_registry(root)
    assert summary["counts"] == {
        "total": 1,
        "pass": 1,
        "fail": 0,
        "not_proven": 0,
        "source_drift": 0,
    }
    assert matrix.main(["--verify-registry", "--digest-only", "--output-root", str(root)]) == 0
    with pytest.raises(matrix.ScenarioContractError, match="artifact registry mismatch"):
        matrix.verify_evidence_registry(root)


def test_digest_only_registry_rejects_missing_unregistered_and_tampered_result(
    tmp_path: Path,
) -> None:
    missing = _digest_only_fixture(tmp_path / "missing")
    (missing / "T01-local" / "scenario-result.json").unlink()
    with pytest.raises(matrix.ScenarioContractError, match="member registry mismatch"):
        matrix.verify_digest_only_registry(missing)

    unregistered = _digest_only_fixture(tmp_path / "unregistered")
    (unregistered / "T01-local" / "raw.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(matrix.ScenarioContractError, match="member registry mismatch"):
        matrix.verify_digest_only_registry(unregistered)

    tampered = _digest_only_fixture(tmp_path / "tampered")
    result_path = tampered / "T01-local" / "scenario-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["duration_ms"] += 1
    matrix.write_json(result_path, result)
    with pytest.raises(matrix.ScenarioContractError, match="summary/result hash"):
        matrix.verify_digest_only_registry(tampered)


def test_digest_only_registry_rejects_logical_members_and_source_binding_mutation(
    tmp_path: Path,
) -> None:
    for name, mutate, message in (
        (
            "missing-logical",
            lambda result: result["output_digests"].pop("public-evidence/payload"),
            "logical digest registry mismatch",
        ),
        (
            "unregistered-logical",
            lambda result: result["output_digests"].update(
                {"public-evidence/raw.body": matrix.digest_record(b"raw")}
            ),
            "logical digest registry mismatch",
        ),
        (
            "source-binding",
            lambda result: result["runner"]["source_binding"]["source_tree_digest"].update(
                {"value": "f" * 64}
            ),
            "source binding is stale",
        ),
    ):
        root = _digest_only_fixture(tmp_path / name)
        result_path = root / "T01-local" / "scenario-result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        mutate(result)
        matrix.write_json(result_path, result)
        matrix.write_json(
            root / "summary.json",
            matrix.build_summary(root / "manifest.json", [result_path]),
        )
        with pytest.raises(matrix.ScenarioContractError, match=message):
            matrix.verify_digest_only_registry(root)


def test_digest_only_requires_registry_verification_mode(capsys) -> None:
    assert matrix.main(["--digest-only"]) == 2
    assert "requires --verify-registry" in capsys.readouterr().err


def test_registry_requires_output_to_prove_the_recorded_tool_version(tmp_path: Path) -> None:
    root = _registered_fixture(tmp_path)
    result_path = root / "T01-local" / "scenario-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["assertions"][0]["actual"] = "0.5.1"
    result["assertions"][0]["status"] = "FAIL"
    result["verdict"] = "FAIL"
    matrix.write_json(result_path, result)
    matrix.write_json(
        root / "summary.json",
        matrix.build_summary(root / "manifest.json", [result_path]),
    )

    # A failed scenario may be retained as honest evidence; relabelling it PASS
    # without an exact version assertion must never make it acceptable.
    result["assertions"][0]["status"] = "PASS"
    result["verdict"] = "PASS"
    matrix.write_json(result_path, result)
    matrix.write_json(
        root / "summary.json",
        matrix.build_summary(root / "manifest.json", [result_path]),
    )
    with pytest.raises(matrix.ScenarioContractError, match="version is not proven"):
        matrix.verify_evidence_registry(root)


def test_runner_binding_uses_working_source_bytes_before_commit(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q", "--template=")
    _git(project, "config", "user.name", "Scenario Test")
    _git(project, "config", "user.email", "scenario@example.test")
    source = project / "tool.py"
    source.write_text("VERSION = 1\n", encoding="utf-8")
    _git(project, "add", "tool.py")
    _git(project, "commit", "-q", "-m", "tool v1")
    monkeypatch.setattr(matrix, "SOURCE_BINDING_PATHS", ("tool.py",))

    committed = matrix.build_runner_binding(project)
    assert committed["source_binding"]["commit_oid"] is not None
    first_digest = committed["source_binding"]["source_tree_digest"]

    source.write_text("VERSION = 2\n", encoding="utf-8")
    dirty = matrix.build_runner_binding(project)
    assert dirty["source_binding"]["commit_oid"] is None
    assert dirty["source_binding"]["source_tree_digest"] != first_digest

    with pytest.raises(matrix.ScenarioContractError, match="source binding is stale"):
        matrix.verify_runner_binding(committed, project_root=project, current=dirty)


def test_runner_binding_cli_is_available_for_external_live_scenarios(capsys) -> None:
    assert matrix.main(["--print-runner-binding"]) == 0
    binding = json.loads(capsys.readouterr().out)
    assert binding["tool_version"] == TOOL_VERSION
    assert binding["source_binding"]["definition_version"] == ("grift-tool-source-tree-v1")
    assert binding["source_binding"]["file_count"] > 0
    assert binding["source_binding"]["source_tree_digest"]["algorithm"] == "sha256"


def test_default_selects_every_registered_offline_scenario_in_stable_order(
    tmp_path: Path,
) -> None:
    registered = [spec.scenario_id for spec in matrix.REGISTERED_OFFLINE_SCENARIOS]
    defaults = [spec.scenario_id for spec in matrix._selection([], include_cloudflare=False)]
    assert defaults == registered == [
        "R01-benevolent-director",
        "R02-grift-landing-blueprint",
        "R03-shallow-history",
        "R04-grift-cli-baseline",
        "R07-voicevox",
        "R08-kilo",
    ]
    assert len(defaults) == len(set(defaults))
    defaults_with_replay = [
        spec.scenario_id for spec in matrix._selection([], include_cloudflare=True)
    ]
    assert defaults_with_replay == [*registered, "R05-cloudflare-os-replay"]

    selected = matrix._selection(
        ["R07-voicevox", "R08-kilo"],
        include_cloudflare=False,
    )
    assert [spec.target_oid for spec in selected] == [
        "c72a94cbcf501be054a239446c7eb8cf53be34b4",
        "323d93b29bd89a2cb446de90c4ed4fea1764176e",
    ]
    assert [spec.expected.actors for spec in selected] == [118, 7]
    assert [
        spec.scenario_id
        for spec in matrix._selection(["R05-cloudflare-os-replay"], include_cloudflare=True)
    ] == ["R05-cloudflare-os-replay"]
    overrides = matrix._parse_source_overrides(
        [
            f"R07-voicevox={tmp_path / 'voicevox'}",
            f"R08-kilo={tmp_path / 'kilo'}",
        ],
        selected_ids=set(defaults),
    )
    assert overrides == {
        "R07-voicevox": (tmp_path / "voicevox").resolve(),
        "R08-kilo": (tmp_path / "kilo").resolve(),
    }
    with pytest.raises(matrix.ScenarioContractError, match="not selected"):
        matrix._parse_source_overrides(
            [f"R01-benevolent-director={tmp_path}"],
            selected_ids={"R07-voicevox"},
        )


def test_checked_in_registry_closes_all_six_offline_results() -> None:
    root = Path(__file__).resolve().parents[1] / "evidence" / "v060" / "scenarios"
    summary = matrix.verify_evidence_registry(root)
    assert matrix.main(["--verify-registry", "--output-root", str(root)]) == 0
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in manifest["scenarios"]] == [
        "R01-benevolent-director",
        "R02-grift-landing-blueprint",
        "R03-shallow-history",
        "R04-grift-cli-baseline",
        "R07-voicevox",
        "R08-kilo",
    ]
    assert summary["counts"] == {
        "total": 6,
        "pass": 6,
        "fail": 0,
        "not_proven": 0,
        "source_drift": 0,
    }


def test_manifest_keeps_result_outside_the_closed_actor_collection() -> None:
    manifest = matrix.build_manifest([_spec("a" * 40)])
    expected = manifest["scenarios"][0]["expected_artifacts"]
    assert "artifacts/collection-manifest.json" in expected
    assert "artifacts/actors/*.json" in expected
    assert "scenario-result.json" in expected
    assert matrix.recorded_repo_argv(_spec("a" * 40), public_evidence=False)[-1].endswith(
        "/artifacts"
    )


def test_expectation_mismatch_is_fail_and_never_rewrites_the_spec() -> None:
    spec = _spec("b" * 40)
    assertion = matrix.compare("git-total", spec.expected.total, 3)
    assert assertion == {
        "id": "git-total",
        "status": "FAIL",
        "expected": 2,
        "actual": 3,
    }
    assert matrix.verdict_from_assertions([assertion]) == "FAIL"
    assert spec.expected.total == 2


def test_read_only_materialization_never_registers_a_source_worktree(tmp_path: Path) -> None:
    source, first, second = _two_commit_repo(tmp_path)
    before_worktrees = _git(source, "worktree", "list", "--porcelain")
    before_status = _git(source, "status", "--porcelain=v1", "--untracked-files=all")

    with matrix.materialize_read_only_repo(source, first) as materialized:
        assert _git(materialized, "rev-parse", "HEAD") == first
        assert (materialized / "tracked.txt").read_text(encoding="utf-8") == "first\n"
        assert materialized.resolve() != source.resolve()

    assert _git(source, "rev-parse", "HEAD") == second
    assert _git(source, "worktree", "list", "--porcelain") == before_worktrees
    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_artifact_inventory_hashes_json_markdown_and_rejects_raw_bundle(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "report.json").write_text('{"ok":true}\n', encoding="utf-8")
    (root / "report.md").write_text("# report\n", encoding="utf-8")
    digests = matrix.artifact_digests(root, forbidden_needles=(str(tmp_path),))
    assert set(digests) == {"report.json", "report.md"}
    assert all(value["algorithm"] == "sha256" for value in digests.values())

    blobs = root / "blobs" / "sha256"
    blobs.mkdir(parents=True)
    (blobs / ("f" * 64)).write_bytes(b"raw provider response")
    with pytest.raises(matrix.ScenarioContractError, match="raw provider body"):
        matrix.artifact_digests(root, forbidden_needles=())


def test_provider_coverage_records_sanitized_counts_and_partial_state(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "coverage": {"status": "complete", "item_count": 667, "missing": []},
                "pages": [{}, {}, {}, {}, {}, {}, {}],
            }
        ),
        encoding="utf-8",
    )
    coverage, counts = matrix._provider_coverage(bundle)
    assert coverage == {"kind": "observed", "provided": True}
    assert counts == {"provider.item_count": 667, "provider.pages": 7}

    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "coverage": {
                    "status": "partial",
                    "item_count": 100,
                    "missing": ["commits_beyond_last_page"],
                },
                "pages": [{}],
            }
        ),
        encoding="utf-8",
    )
    coverage, counts = matrix._provider_coverage(bundle)
    assert coverage == {
        "kind": "not_proven",
        "provided": True,
        "reason": "public_evidence_partial",
    }
    assert counts == {"provider.item_count": 100, "provider.pages": 1}


def test_report_metrics_keep_population_window_merge_basis_and_partition() -> None:
    partition = "c" * 64
    report = {
        "provenance": {
            "target_oid": {"algorithm": "sha1", "value": "d" * 40},
            "revision_completeness": {"shallow": False, "promisor": False, "complete": True},
        },
        "target": {"oid": {"algorithm": "sha1", "value": "d" * 40}},
        "window": {
            "start": "2026-01-01",
            "end": "2026-06-30",
            "unit": "date-range",
            "basis": "legacy_head_date",
        },
        "population": {
            "actor_count": 2,
            "human_commit_count": 6,
            "nonmerge_commit_count": 4,
            "merge_commit_count": 2,
            "partition_digest": {"algorithm": "sha256", "value": partition},
        },
        "attribution": {
            "repo_human_nonmerge_commits": 4,
            "attribution_human_including_merges": 6,
            "attribution_unresolved_commit_count": 0,
            "bot_count": 0,
            "merge_count": 2,
            "population_identity": "repo_human_nonmerge_commits + merge_count = attribution_human_including_merges + attribution_unresolved_commit_count",
            "actor_partition": {"partition_digest": partition},
        },
        "metrics": {"human_nonmerge_commit_share": {"numerator": 4, "denominator": 6}},
    }
    actor_index = {
        "partition_digest": {"algorithm": "sha256", "value": partition},
        "population": {"actor_count": 2},
        "selection": {"selected_count": 2},
    }
    metrics = matrix.report_metrics(report, actor_index)
    assert metrics["counts"]["report.human_nonmerge"] == 4
    assert metrics["counts"]["report.merge"] == 2
    assert metrics["counts"]["actors.full"] == 2
    assert metrics["window"] == {
        "start": "2026-01-01",
        "end": "2026-06-30",
        "days": 180,
        "unit": "date-range",
        "basis": "legacy_head_date",
    }
    assert metrics["merge_basis"].startswith("repo_human_nonmerge_commits")
    assert metrics["partition_digest"] == partition
    assert metrics["counts"]["metric.human_nonmerge.numerator"] == 4
    assert metrics["counts"]["metric.human_nonmerge.denominator"] == 6


def test_committed_public_live_gate_summary_registers_every_result() -> None:
    manifest_path = _PUBLIC_EVIDENCE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert validate_schema("scenario-manifest-v1", manifest) == []
    expected_paths = [
        _PUBLIC_EVIDENCE / row["id"] / "scenario-result.json" for row in manifest["scenarios"]
    ]
    assert all(path.is_file() for path in expected_paths)

    rebuilt = matrix.build_summary(manifest_path, expected_paths)
    committed = json.loads((_PUBLIC_EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    assert validate_schema("scenario-summary-v1", committed) == []
    assert rebuilt == committed
    assert committed["counts"] == {
        "total": 3,
        "pass": 3,
        "fail": 0,
        "not_proven": 0,
        "source_drift": 0,
    }
    assert committed["verdict"] == "PASS"


def test_committed_public_live_gate_values_and_partial_contract_are_exact() -> None:
    expected = {
        "P01-cloudflare-full": {
            "exit": 0,
            "git": 667,
            "actors": 18,
            "pages": 7,
            "observed": 667,
            "missing": 0,
            "coverage": "observed",
        },
        "P02-vite-forced-partial": {
            "exit": 3,
            "git": 9642,
            "actors": 1368,
            "pages": 1,
            "observed": 100,
            "missing": 9542,
            "coverage": "not_proven",
        },
        "P03-gitlab-release-cli-full": {
            "exit": 0,
            "git": 453,
            "actors": 47,
            "pages": 5,
            "observed": 453,
            "missing": 0,
            "coverage": "observed",
        },
    }
    for scenario_id, wanted in expected.items():
        path = _PUBLIC_EVIDENCE / scenario_id / "scenario-result.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        assert validate_schema("scenario-result-v1", result) == []
        assert result["verdict"] == "PASS"
        assert result["exit_code"] == wanted["exit"]
        assert result["counts"]["git.total"] == wanted["git"]
        assert result["counts"]["actor.full"] == wanted["actors"]
        assert result["counts"]["provider.pages"] == wanted["pages"]
        assert result["counts"]["oid.observed"] == wanted["observed"]
        assert result["counts"]["oid.missing"] == wanted["missing"]
        assert result["provider_coverage"]["kind"] == wanted["coverage"]
        statuses = {row["id"]: row["status"] for row in result["assertions"]}
        assert statuses
        assert set(statuses.values()) == {"PASS"}
        assert any(key.endswith("repo-report.json") for key in result["output_digests"])
        assert any(key.endswith("repo-report.md") for key in result["output_digests"])
        assert any(key.endswith("actor-index.json") for key in result["output_digests"])
        assert any(key.endswith("actor-index.md") for key in result["output_digests"])

    vite = json.loads(
        (_PUBLIC_EVIDENCE / "P02-vite-forced-partial" / "scenario-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert vite["provider_coverage"] == {
        "kind": "not_proven",
        "provided": True,
        "reason": "public_evidence_partial",
    }
    assert vite["verdict"] == "PASS"  # safe partial is the scenario expectation

    gitlab = json.loads(
        (_PUBLIC_EVIDENCE / "P03-gitlab-release-cli-full" / "scenario-result.json").read_text(
            encoding="utf-8"
        )
    )
    assertions = {row["id"]: row for row in gitlab["assertions"]}
    assert assertions["account-linkage"]["actual"] == "unsupported"
    assert gitlab["counts"]["account.stable"] == 0


def test_committed_public_evidence_is_sanitized_and_contains_no_raw_bundle() -> None:
    files = sorted(path for path in _PUBLIC_EVIDENCE.rglob("*") if path.is_file())
    assert [path.relative_to(_PUBLIC_EVIDENCE).as_posix() for path in files] == [
        "P01-cloudflare-full/scenario-result.json",
        "P02-vite-forced-partial/scenario-result.json",
        "P03-gitlab-release-cli-full/scenario-result.json",
        "manifest.json",
        "summary.json",
    ]
    forbidden = (
        "/Users/",
        "/tmp/",
        "access_token=",
        "authorization:",
        "bearer ",
        "private-token",
        "blobs/sha256",
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        folded = text.casefold()
        assert all(needle.casefold() not in folded for needle in forbidden)
        assert "https://" not in folded


def test_sanitized_argv_never_records_owner_local_paths(tmp_path: Path) -> None:
    source = tmp_path / "Developer" / "private-repo"
    argv = matrix.recorded_repo_argv(
        matrix.ScenarioSpec(
            scenario_id="T02-private",
            tier="local",
            repo_relative="private-repo",
            target_oid="e" * 40,
            expected=matrix.ExpectedCounts(total=1, nonmerge=1, merge=0, actors=1),
            timeout_seconds=30,
            expected_complete=True,
        ),
        public_evidence=False,
    )
    assert str(source) not in json.dumps(argv)
    assert "${DEVELOPER_ROOT}/private-repo" in argv
