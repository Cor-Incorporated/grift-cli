from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "benchmarks" / "v060" / "golden"
_SPEC = importlib.util.spec_from_file_location(
    "grift_v060_golden", ROOT / "scripts" / "v060_golden.py"
)
assert _SPEC is not None and _SPEC.loader is not None
v060_golden = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = v060_golden
_SPEC.loader.exec_module(v060_golden)
_BASELINE_SPEC = importlib.util.spec_from_file_location(
    "grift_v060_golden_baseline", ROOT / "scripts" / "v060_golden_baseline.py"
)
assert _BASELINE_SPEC is not None and _BASELINE_SPEC.loader is not None
v060_golden_baseline = importlib.util.module_from_spec(_BASELINE_SPEC)
sys.modules[_BASELINE_SPEC.name] = v060_golden_baseline
_BASELINE_SPEC.loader.exec_module(v060_golden_baseline)


def _copy_golden(tmp_path: Path) -> Path:
    target = tmp_path / "golden"
    shutil.copytree(GOLDEN, target)
    return target


def _rewrite_registry_digest(root: Path, relative: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["registered_files"][relative] = hashlib.sha256(
        (root / relative).read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _read_migrations(root: Path) -> dict:
    return json.loads((root / "migrations.json").read_text(encoding="utf-8"))


def _write_migrations(root: Path, migrations: dict) -> None:
    migration_path = root / "migrations.json"
    migration_path.write_text(json.dumps(migrations, indent=2) + "\n", encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["migration_log"]["sha256"] = hashlib.sha256(migration_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _seal_first_migration(root: Path, mutate: object) -> None:
    migrations = _read_migrations(root)
    entry = migrations["entries"][0]
    assert callable(mutate)
    mutate(entry)
    entry["record_sha256"] = v060_golden._migration_record_sha256(entry)
    _write_migrations(root, migrations)


def test_registered_fixture_manifest_is_closed_and_hashed() -> None:
    manifest = v060_golden.load_manifest(GOLDEN / "manifest.json")

    assert manifest["schema_version"] == v060_golden.MANIFEST_SCHEMA
    assert manifest["drift_policy_version"] == v060_golden.DRIFT_POLICY_VERSION
    assert set(manifest["registered_files"]) == {
        "fixtures/actor-partition-repo.json",
        "expected/actor-partition.json",
    }
    assert manifest["migration_log"]["path"] == "migrations.json"

    # 台帳は append-only なので特定の版を pin してはならない。不変条件だけを見る:
    # 先頭が ABSENT から始まり、隣接エントリの hash が連鎖し、末尾が manifest と一致する。
    entries = manifest["_migration_log"]["entries"]
    assert entries
    assert entries[0]["old_expected_sha256"] == v060_golden.ABSENT_BASELINE_SHA256
    for older, newer in zip(entries, entries[1:]):
        assert newer["old_expected_sha256"] == older["new_expected_sha256"]
        assert newer["previous_entry_sha256"] == older["record_sha256"]
    assert entries[-1]["registered_files"] == manifest["registered_files"]
    assert [entry["approval"]["status"] for entry in entries] == ["approved"] * len(entries)


def test_manifest_rejects_missing_unregistered_and_hash_mismatch(tmp_path: Path) -> None:
    missing = _copy_golden(tmp_path / "missing")
    (missing / "fixtures" / "actor-partition-repo.json").unlink()
    with pytest.raises(v060_golden.GoldenContractError, match="missing"):
        v060_golden.load_manifest(missing / "manifest.json")

    unregistered = _copy_golden(tmp_path / "unregistered")
    (unregistered / "expected" / "saved-fail.json").write_text(
        '{"overall":"FAIL"}\n', encoding="utf-8"
    )
    with pytest.raises(v060_golden.GoldenContractError, match="unregistered golden"):
        v060_golden.load_manifest(unregistered / "manifest.json")

    mismatched = _copy_golden(tmp_path / "mismatch")
    fixture = mismatched / "fixtures" / "actor-partition-repo.json"
    fixture.write_text(fixture.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(v060_golden.GoldenContractError, match="hash mismatch"):
        v060_golden.load_manifest(mismatched / "manifest.json")


def test_manifest_rejects_symlinked_registry_directory(tmp_path: Path) -> None:
    linked = _copy_golden(tmp_path)
    real_expected = linked / "expected-real"
    (linked / "expected").rename(real_expected)
    (linked / "expected").symlink_to(real_expected, target_is_directory=True)

    with pytest.raises(v060_golden.GoldenContractError, match="crosses a symlink"):
        v060_golden.load_manifest(linked / "manifest.json")


def test_manifest_rejects_registered_file_reuse_across_cases(tmp_path: Path) -> None:
    duplicated = _copy_golden(tmp_path)
    manifest_path = duplicated / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    second = copy.deepcopy(manifest["cases"][0])
    second["id"] = "actor-partition-copy"
    manifest["cases"].append(second)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(v060_golden.GoldenContractError, match="more than once"):
        v060_golden.load_manifest(manifest_path)


def test_manifest_rejects_missing_or_tampered_migration_log(tmp_path: Path) -> None:
    missing_reference = _copy_golden(tmp_path / "missing-reference")
    manifest_path = missing_reference / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["migration_log"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(v060_golden.GoldenContractError, match="migration_log must be"):
        v060_golden.load_manifest(manifest_path)

    tampered = _copy_golden(tmp_path / "tampered")
    migration_path = tampered / "migrations.json"
    migration_path.write_bytes(migration_path.read_bytes() + b"\n")
    with pytest.raises(v060_golden.GoldenContractError, match="migration log hash mismatch"):
        v060_golden.load_manifest(tampered / "manifest.json")

    missing_file = _copy_golden(tmp_path / "missing-file")
    (missing_file / "migrations.json").unlink()
    with pytest.raises(v060_golden.GoldenContractError, match="missing"):
        v060_golden.load_manifest(missing_file / "manifest.json")


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("migration_id", "migration_id is invalid"),
        ("old_expected_sha256", "old_expected_sha256 must be SHA-256"),
        ("new_expected_sha256", "new_expected_sha256 must be SHA-256"),
        ("approval", "approval must be an object"),
        ("registered_files", "registered_files must be an object"),
    ],
)
def test_migration_rejects_required_contract_field_removal(
    tmp_path: Path, field: str, match: str
) -> None:
    root = _copy_golden(tmp_path)
    migrations = _read_migrations(root)
    del migrations["entries"][0][field]
    _write_migrations(root, migrations)

    with pytest.raises(v060_golden.GoldenContractError, match=match):
        v060_golden.load_manifest(root / "manifest.json")


def test_migration_rejects_approval_and_chain_tampering_even_when_log_is_rehashed(
    tmp_path: Path,
) -> None:
    approval = _copy_golden(tmp_path / "approval")
    migrations = _read_migrations(approval)
    migrations["entries"][0]["approval"]["approved_by"] = "human:unreviewed"
    _write_migrations(approval, migrations)
    with pytest.raises(v060_golden.GoldenContractError, match="migration record digest mismatch"):
        v060_golden.load_manifest(approval / "manifest.json")

    chain = _copy_golden(tmp_path / "chain")

    def break_chain(entry: dict) -> None:
        entry["previous_entry_sha256"] = "0" * 64

    _seal_first_migration(chain, break_chain)
    with pytest.raises(v060_golden.GoldenContractError, match="previous migration record"):
        v060_golden.load_manifest(chain / "manifest.json")


def test_migration_rejects_d4_downgrade_and_duplicate_id(tmp_path: Path) -> None:
    downgraded = _copy_golden(tmp_path / "downgraded")

    def remove_d4(entry: dict) -> None:
        entry["drift_counts"]["D4"] = 0
        entry["difference_count"] -= 1

    _seal_first_migration(downgraded, remove_d4)
    with pytest.raises(v060_golden.GoldenContractError, match="requires D4 drift"):
        v060_golden.load_manifest(downgraded / "manifest.json")

    duplicated = _copy_golden(tmp_path / "duplicate")
    migrations = _read_migrations(duplicated)
    migrations["entries"].append(copy.deepcopy(migrations["entries"][0]))
    _write_migrations(duplicated, migrations)
    with pytest.raises(v060_golden.GoldenContractError, match="duplicate golden migration id"):
        v060_golden.load_manifest(duplicated / "manifest.json")


@pytest.mark.parametrize(
    "relative", ["fixtures/actor-partition-repo.json", "expected/actor-partition.json"]
)
def test_migration_rejects_registry_only_fixture_or_baseline_replacement(
    tmp_path: Path, relative: str
) -> None:
    root = _copy_golden(tmp_path)
    target = root / relative
    target.write_bytes(target.read_bytes() + b"\n")
    _rewrite_registry_digest(root, relative)

    with pytest.raises(v060_golden.GoldenContractError, match="active registered fixtures"):
        v060_golden.load_manifest(root / "manifest.json")


def test_baseline_tool_requires_explicit_approval_and_appends_a_valid_d4_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    golden = repo_root / "benchmarks" / "v060" / "golden"
    shutil.copytree(GOLDEN, golden)
    expected = json.loads((golden / "expected/actor-partition.json").read_text(encoding="utf-8"))
    observed = copy.deepcopy(expected)
    observed["schema_version"] = "tep-v060-golden-observation-v2"
    original_files = {
        relative: (golden / relative).read_bytes()
        for relative in ("manifest.json", "migrations.json", "expected/actor-partition.json")
    }
    monkeypatch.setattr(v060_golden_baseline, "ROOT", repo_root)
    monkeypatch.setattr(v060_golden_baseline, "MIGRATIONS_PATH", golden / "migrations.json")
    monkeypatch.setattr(
        v060_golden_baseline.v060_golden,
        "observe_case",
        lambda *args, **kwargs: copy.deepcopy(observed),
    )

    assert v060_golden_baseline.main(["--case", "actor-partition"]) == 1
    for relative, body in original_files.items():
        assert (golden / relative).read_bytes() == body

    # migration ID は append-only 台帳の現在長から導く。リテラルを焼き込むと
    # 次に承認移行を 1 本足した時点で duplicate id になって落ちる。
    before = _read_migrations(golden)["entries"]
    next_migration_id = f"gold-actor-partition-{len(before) + 1:04d}"
    assert (
        v060_golden_baseline.main(
            [
                "--case",
                "actor-partition",
                "--approve",
                "--migration-id",
                next_migration_id,
                "--approved-by",
                "human:release-owner",
                "--approved-at",
                "2026-08-31T12:00:00+09:00",
                "--requirement",
                "GOLD-01",
            ]
        )
        == 0
    )
    manifest = v060_golden_baseline.v060_golden.load_manifest(golden / "manifest.json")
    entries = manifest["_migration_log"]["entries"]
    assert len(entries) == len(before) + 1
    assert entries[-1]["migration_id"] == next_migration_id
    assert entries[-1]["old_expected_sha256"] == entries[-2]["new_expected_sha256"]
    assert (
        entries[-1]["new_expected_sha256"]
        == manifest["registered_files"]["expected/actor-partition.json"]
    )
    assert entries[-1]["previous_entry_sha256"] == entries[-2]["record_sha256"]
    assert entries[-1]["approval"]["requirements"] == ["GOLD-01"]


def test_baseline_tool_rejects_manual_update_without_d4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    golden = repo_root / "benchmarks" / "v060" / "golden"
    shutil.copytree(GOLDEN, golden)
    expected = json.loads((golden / "expected/actor-partition.json").read_text(encoding="utf-8"))
    observed = copy.deepcopy(expected)
    observed["commands"]["repo"]["exit_code"] = 7
    original_files = {
        relative: (golden / relative).read_bytes()
        for relative in ("manifest.json", "migrations.json", "expected/actor-partition.json")
    }
    monkeypatch.setattr(v060_golden_baseline, "ROOT", repo_root)
    monkeypatch.setattr(v060_golden_baseline, "MIGRATIONS_PATH", golden / "migrations.json")
    monkeypatch.setattr(
        v060_golden_baseline.v060_golden,
        "observe_case",
        lambda *args, **kwargs: copy.deepcopy(observed),
    )

    result = v060_golden_baseline.main(
        [
            "--case",
            "actor-partition",
            "--approve",
            "--migration-id",
            "gold-actor-partition-rejected",
            "--approved-by",
            "human:release-owner",
            "--approved-at",
            "2026-08-31T12:00:00+09:00",
            "--requirement",
            "GOLD-01",
        ]
    )

    assert result == 2
    for relative, body in original_files.items():
        assert (golden / relative).read_bytes() == body


def test_baseline_tool_rolls_back_a_partial_install_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    golden = repo_root / "benchmarks" / "v060" / "golden"
    shutil.copytree(GOLDEN, golden)
    expected = json.loads((golden / "expected/actor-partition.json").read_text(encoding="utf-8"))
    observed = copy.deepcopy(expected)
    observed["schema_version"] = "tep-v060-golden-observation-v2"
    original_files = {
        relative: (golden / relative).read_bytes()
        for relative in ("manifest.json", "migrations.json", "expected/actor-partition.json")
    }
    monkeypatch.setattr(v060_golden_baseline, "ROOT", repo_root)
    monkeypatch.setattr(v060_golden_baseline, "MIGRATIONS_PATH", golden / "migrations.json")
    monkeypatch.setattr(
        v060_golden_baseline.v060_golden,
        "observe_case",
        lambda *args, **kwargs: copy.deepcopy(observed),
    )
    real_replace = v060_golden_baseline._atomic_replace_bytes
    calls = 0

    def fail_second_replace(path: Path, body: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second-file install failure")
        real_replace(path, body)

    monkeypatch.setattr(v060_golden_baseline, "_atomic_replace_bytes", fail_second_replace)

    result = v060_golden_baseline.main(
        [
            "--case",
            "actor-partition",
            "--approve",
            "--migration-id",
            "gold-actor-partition-rollback",
            "--approved-by",
            "human:release-owner",
            "--approved-at",
            "2026-08-31T12:00:00+09:00",
            "--requirement",
            "GOLD-01",
        ]
    )

    assert result == 2
    for relative, original in original_files.items():
        assert (golden / relative).read_bytes() == original


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("$.artifacts.repo-report.json.content.provenance.analyzed_at", "D0"),
        ("$.artifacts.public-evidence.json.content.rate_state", "D0"),
        ("$.artifacts.actor-index.json.content.actors[0].display_name", "D1"),
        ("$.artifacts.actors/alice.json.content.accounts", "D2"),
        ("$.artifacts.actors/alice.json.content.account_status", "D2"),
        ("$.artifacts.actors/alice.json.content.accounts[0].host", "D2"),
        ("$.artifacts.repo-report.json.content.population.nonmerge_commit_count", "D3"),
        ("$.artifacts.repo-report.json.content.schema_version", "D4"),
    ],
)
def test_drift_classifier_is_fail_closed(path: str, expected: str) -> None:
    assert v060_golden.classify_drift(path) == expected


def test_population_priority_cannot_be_downgraded_to_public_drift() -> None:
    path = "$.artifacts.report.json.content.public_join.observed_actor_count"
    assert v060_golden.classify_drift(path) == "D3"


def test_runtime_fields_are_normalized_but_unknown_changes_fail() -> None:
    first = {"provenance": {"analyzed_at": "2026-08-31T00:00:00Z"}, "value": 1}
    second = {"provenance": {"analyzed_at": "2030-01-01T00:00:00Z"}, "value": 1}
    assert (
        v060_golden.compare_observation(
            v060_golden._normalize_d0(first), v060_golden._normalize_d0(second)
        )
        == []
    )

    differences = v060_golden.compare_observation({"unclassified": 1}, {"unclassified": 2})
    assert differences[0]["class"] == "D3"


def test_verified_manifest_digest_cascade_does_not_upgrade_underlying_drift() -> None:
    manifest = {
        "schema_version": "actor-artifact-manifest-v1",
        "members": [
            {"path": "repo-report.json", "bytes": 123, "sha256": "a" * 64},
        ],
    }
    normalized = v060_golden._normalize_verified_member_metadata(manifest)

    assert normalized["members"][0] == {
        "path": "repo-report.json",
        "bytes": "<VERIFIED:derived-member-metadata>",
        "sha256": "<VERIFIED:derived-member-metadata>",
    }


def test_missing_actor_card_is_d3_failure() -> None:
    expected = {
        "artifacts": {"actors/alice.json": {"content": {"actor_id": "alice"}, "kind": "json"}}
    }
    differences = v060_golden.compare_observation(expected, {"artifacts": {}})
    assert differences
    assert {item["class"] for item in differences} == {"D3"}
    assert v060_golden._verdict(differences) == "FAIL"


def test_runner_executes_repo_and_verify_cli(tmp_path: Path) -> None:
    result = v060_golden.run_manifest(
        GOLDEN / "manifest.json",
        python=Path(sys.executable),
        work_root=tmp_path / "work",
    )

    assert result["overall"] == "PASS"
    assert result["case_count"] == 1
    assert result["cases"][0]["cli_executed"] == ["repo", "verify"]
    assert result["cases"][0]["observation_sha256"]
    assert result["baseline_update"] == "forbidden_automatic"


def test_d2_and_d4_never_update_baseline_automatically() -> None:
    base = {"handle": "before", "schema_version": "report-v2"}
    source_drift = copy.deepcopy(base)
    source_drift["handle"] = "after"
    migration = copy.deepcopy(base)
    migration["schema_version"] = "report-v3"

    assert v060_golden._verdict(v060_golden.compare_observation(base, source_drift)) == (
        "SOURCE_DRIFT"
    )
    assert v060_golden._verdict(v060_golden.compare_observation(base, migration)) == (
        "MIGRATION_REQUIRED"
    )
