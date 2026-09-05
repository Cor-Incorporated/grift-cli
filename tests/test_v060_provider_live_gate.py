from __future__ import annotations

import argparse
import copy
import dataclasses
import importlib.util
import json
import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from tep_core.forge_public import GitObjectId, HttpResponse, parse_forge_locator
from tep_core.public_evidence import collect_public_evidence, verify_public_evidence

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v060_provider_live_gate_tested",
    ROOT / "scripts" / "v060_provider_live_gate.py",
)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(ROOT / "scripts"))
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _state(spec: object) -> dict:
    counts = spec.counts
    return {
        "counts": {
            "report.human_nonmerge": counts.human_nonmerge,
            "report.merge": counts.human_merge,
            "report.bot": counts.bots,
            "actors.full": counts.actors,
        },
        "partition_digest": "1" * 64,
        "sha_to_actor_digest": "2" * 64,
        "population_digest": "3" * 64,
        "target_oid": spec.target_oid,
        "merge_basis": gate.MERGE_BASIS,
        "output_sha256": {
            "repo-report.json": "4" * 64,
            "repo-report.md": "5" * 64,
            "actor-index.json": "6" * 64,
            "actor-index.md": "7" * 64,
            "collection-manifest.json": "8" * 64,
        },
        "license_evidence_digest": "9" * 64,
        "repo_provider_independent_digest": "a" * 64,
        "repo_provider_independent_numeric_digest": "b" * 64,
        "actor_provider_independent_digest": "c" * 64,
        "actor_provider_independent_numeric_digest": "d" * 64,
        "account_counts": {"stable": 0, "public_handle_actors": 0, "statuses": {}},
    }


def _result(spec: object) -> dict:
    state = _state(spec)
    exits = gate._expected_exit_contract(spec)
    return {
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
        "provider_evidence": {
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
            "bundle_payload_sha256": "5" * 64,
            "manifest_sha256": "6" * 64,
            "page_body_sha256": ["7" * 64 for _ in range(spec.expected_pages)],
            "rate_partial": False,
            "resumable": spec.expected_partial,
        },
        "states": {"offline": state, "live": dict(state), "replay": dict(state)},
        "sleep_seconds": 0,
        "collection_mode": "fresh",
        "prior_evidence_digests": None,
        "resumable_partial_staged": False,
        "mismatch_ids": [],
        "outcome": "PASS",
    }


def _binding(commit: str) -> dict:
    return {
        "tool_version": "0.6.0",
        "source_binding": {
            "definition_version": "grift-tool-source-tree-v1",
            "source_tree_digest": {"algorithm": "sha256", "value": "a" * 64},
            "file_count": 42,
            "commit_oid": {"algorithm": "sha1", "value": commit},
        },
    }


def test_fixed_pr_and_release_scenario_contracts_are_exact() -> None:
    assert [spec.scenario_id for spec in gate._selected("pr")] == [
        "P01-cloudflare-full",
        "P02-vite-forced-partial",
        "P03-gitlab-release-cli-full",
    ]
    release = gate._selected("release")
    assert len(release) == 6
    expected = {
        "P01-cloudflare-full": (667, 18, 7, 180, "complete"),
        "P02-vite-forced-partial": (9642, 1368, 1, 600, "complete"),
        "P03-gitlab-release-cli-full": (453, 47, 5, 180, "unsupported"),
        "L01-vite-full": (9642, 1368, 97, 600, "complete"),
        "L02-voicevox-full": (1899, 118, 19, 180, "complete"),
        "L03-gitlab-cli-full": (6127, 369, 62, 600, "unsupported"),
    }
    assert {
        spec.scenario_id: (
            spec.counts.total,
            spec.counts.actors,
            spec.expected_pages,
            spec.timeout_seconds,
            spec.account_linkage,
        )
        for spec in release
    } == expected
    assert gate.TOTAL_TIMEOUT_SECONDS == 1800


def test_release_missing_credentials_fails_before_source_or_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TEST_TOKEN", raising=False)
    monkeypatch.setenv("GITLAB_TEST_TOKEN", "present")
    monkeypatch.setattr(
        gate,
        "build_runner_binding",
        lambda _root: pytest.fail("source inspection must not run before credential preflight"),
    )
    args = argparse.Namespace(
        tier="release",
        repo_root=tmp_path / "missing",
        summary=tmp_path / "summary.json",
        ledger=tmp_path / "ledger.jsonl",
        github_token_env="GITHUB_TEST_TOKEN",
        gitlab_token_env="GITLAB_TEST_TOKEN",
        source_commit="a" * 40,
    )
    with pytest.raises(gate.GateError, match="both provider credential"):
        gate.run_gate(args)


def test_cli_argv_never_contains_token_value_or_empty_token_flag(tmp_path: Path) -> None:
    spec = gate._selected("pr")[0]
    command = gate._repo_command(
        tmp_path / "repo",
        spec,
        tmp_path / "out",
        mode="fetch",
        bundle=tmp_path / "bundle",
        token_env=None,
    )
    assert "--auth-token-env" not in command
    command = gate._repo_command(
        tmp_path / "repo",
        spec,
        tmp_path / "out",
        mode="fetch",
        bundle=tmp_path / "bundle",
        token_env="TOKEN_NAME",
    )
    assert command[-2:] == ["--auth-token-env", "TOKEN_NAME"]
    assert "secret-token-value" not in command


def test_one_sided_expectation_mutation_is_red() -> None:
    spec = gate._selected("pr")[0]
    actual = _result(spec)
    assert gate.validate_scenario_result(spec, actual) == []
    mutated = dataclasses.replace(
        spec,
        counts=dataclasses.replace(spec.counts, total=spec.counts.total + 1),
    )
    mismatch = gate.validate_scenario_result(mutated, actual)
    assert "git-total" in mismatch
    assert "oid-expected" in mismatch


def test_live_and_replay_collection_mutations_are_red() -> None:
    spec = gate._selected("pr")[0]
    actual = _result(spec)
    actual["states"]["live"]["counts"] = dict(actual["states"]["live"]["counts"])
    actual["states"]["live"]["counts"]["actors.full"] = 0
    actual["states"]["replay"]["target_oid"] = "f" * 40
    actual["states"]["replay"]["output_sha256"] = dict(actual["states"]["replay"]["output_sha256"])
    actual["states"]["replay"]["output_sha256"]["actor-index.json"] = "9" * 64
    mismatch = gate.validate_scenario_result(spec, actual)
    assert "counts-live" in mismatch
    assert "target-oid-replay" in mismatch
    assert "live-replay-actor-index.json-digest" in mismatch


def test_provider_independent_repo_and_actor_digest_mutations_are_red() -> None:
    spec = gate._selected("pr")[0]
    actual = _result(spec)
    actual["states"]["live"] = dict(actual["states"]["live"])
    actual["states"]["replay"] = dict(actual["states"]["replay"])
    actual["states"]["live"]["repo_provider_independent_numeric_digest"] = "e" * 64
    actual["states"]["replay"]["actor_provider_independent_digest"] = "f" * 64
    mismatch = gate.validate_scenario_result(spec, actual)
    assert "repo_provider_independent_numeric_digest-offline-live" in mismatch
    assert "actor_provider_independent_digest-offline-replay" in mismatch

    actual = _result(spec)
    actual["states"]["live"] = dict(actual["states"]["live"])
    actual["states"]["live"]["unregistered_numeric_claim"] = 1
    assert "collection-state-members-live" in gate.validate_scenario_result(spec, actual)


def test_provider_projection_allows_only_display_coverage_and_runtime_drift() -> None:
    report = {
        "attribution": {
            "observed_actor_count": 2,
            "public_join": {"matched": 0, "public_handle_actors": 0},
        },
        "input_coverage": {
            "public_forge": {
                "kind": "not_observed",
                "reason": "public_evidence_not_provided",
                "expected_count": None,
                "observed_count": None,
                "missing_count": 0,
                "repository_license": {"files": [{"path": "LICENSE", "bytes": 10}]},
            }
        },
        "provenance": {
            "analyzed_at": "2026-08-31T00:00:00Z",
            "input_digests": {"public_evidence": None, "tagset": "fixed"},
        },
    }
    enriched = json.loads(json.dumps(report))
    enriched["attribution"]["public_join"] = {"matched": 2, "public_handle_actors": 2}
    enriched["input_coverage"]["public_forge"].update(
        {
            "kind": "observed",
            "reason": "complete",
            "expected_count": 20,
            "observed_count": 20,
            "missing_count": 0,
        }
    )
    enriched["provenance"]["analyzed_at"] = "2026-08-31T00:01:00Z"
    enriched["provenance"]["input_digests"]["public_evidence"] = "evidence"
    baseline = gate._provider_independent_repo(report)
    public = gate._provider_independent_repo(enriched)
    assert gate._sha256(gate._canonical(baseline)) == gate._sha256(gate._canonical(public))
    assert gate._numeric_digest(baseline) == gate._numeric_digest(public)

    enriched["attribution"]["observed_actor_count"] = 3
    changed = gate._provider_independent_repo(enriched)
    assert gate._numeric_digest(baseline) != gate._numeric_digest(changed)
    enriched["attribution"]["observed_actor_count"] = 2
    enriched["input_coverage"]["public_forge"]["repository_license"]["files"][0]["bytes"] = 11
    changed_license = gate._provider_independent_repo(enriched)
    assert gate._numeric_digest(baseline) != gate._numeric_digest(changed_license)


def test_actor_projection_allows_account_display_but_not_actor_numbers() -> None:
    card = {
        "actor_id": "alice",
        "n": 20,
        "denominator": 40,
        "account_status": "not_requested",
        "accounts": [],
    }
    enriched = {
        **card,
        "account_status": "matched",
        "accounts": [{"provider": "github", "account_id": "42", "handle": "alice"}],
    }
    baseline = gate._provider_independent_actor_card(card)
    public = gate._provider_independent_actor_card(enriched)
    assert gate._sha256(gate._canonical(baseline)) == gate._sha256(gate._canonical(public))
    assert gate._numeric_digest(baseline) == gate._numeric_digest(public)
    enriched["n"] = 21
    assert gate._numeric_digest(baseline) != gate._numeric_digest(
        gate._provider_independent_actor_card(enriched)
    )


def test_long_rate_reset_is_safe_partial_without_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.time, "time", lambda: 1_000)
    manifest = {
        "coverage": {"status": "partial"},
        "pagination": {"stop_reason": "http_403"},
        "pages": [
            {
                "response_headers": {
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": "1031",
                }
            }
        ],
    }
    assert gate._is_long_rate_partial(manifest) is True
    manifest["pages"][0]["response_headers"]["x-ratelimit-reset"] = "1030"
    assert gate._is_long_rate_partial(manifest) is False
    manifest["pages"][0]["response_headers"] = {
        "ratelimit-remaining": "0",
        "ratelimit-reset": "1031",
    }
    assert gate._is_long_rate_partial(manifest) is True
    manifest["pages"][0]["response_headers"] = {
        "retry-after": "31",
    }
    assert gate._is_long_rate_partial(manifest) is True
    source = (ROOT / "scripts" / "v060_provider_live_gate.py").read_text()
    assert "time.sleep" not in source


def test_wall_clock_guard_interrupts_helper_work_past_deadline() -> None:
    with pytest.raises(gate.GateTimeout, match="wall-clock deadline"):
        with gate._wall_clock_deadline(0.001):
            while True:
                pass


def test_summary_and_ledger_are_closed_source_bound_and_replayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "b" * 40
    specs = gate._selected("release")
    results = [_result(spec) for spec in specs]
    definition = gate.definition_digest("release")
    ledger = gate._ledger_bytes("release", results, definition)
    ledger_path = tmp_path / "guard-ledger.jsonl"
    ledger_path.write_bytes(ledger)
    source = gate._source_summary(_binding(commit), commit)
    summary = {
        "schema_version": gate.SCHEMA_VERSION,
        "guard_id": gate.GUARD_ID,
        "tier": "release",
        "verdict": "PASS",
        "source": source,
        "definition_digest": definition,
        "scenario_count": 6,
        "suite_timeout_seconds": 1800,
        "duration_ms": 123,
        "ledger_sha256": gate._sha256(ledger),
        "results": results,
    }
    summary_path = tmp_path / "summary.json"
    gate._write_json(summary_path, summary)
    monkeypatch.setattr(gate, "build_runner_binding", lambda _root: _binding(commit))
    gate.verify_summary(
        summary_path,
        ledger_path,
        expected_tier="release",
        expected_commit=commit,
        project_root=ROOT,
    )

    mutated_rows = [json.loads(line) for line in ledger.splitlines()]
    mutated_rows[0]["negative_case"] = "weakened"
    mutated_ledger = b"".join(gate._canonical(row) + b"\n" for row in mutated_rows)
    ledger_path.write_bytes(mutated_ledger)
    summary["ledger_sha256"] = gate._sha256(mutated_ledger)
    gate._write_json(summary_path, summary)
    with pytest.raises(gate.GateError, match="guard ledger contract differs"):
        gate.verify_summary(
            summary_path,
            ledger_path,
            expected_tier="release",
            expected_commit=commit,
            project_root=ROOT,
        )

    ledger_path.write_bytes(ledger)
    summary["ledger_sha256"] = gate._sha256(ledger)
    summary["results"][0]["git_counts"]["total"] += 1
    gate._write_json(summary_path, summary)
    with pytest.raises(gate.GateError, match="assertions do not replay"):
        gate.verify_summary(
            summary_path,
            ledger_path,
            expected_tier="release",
            expected_commit=commit,
            project_root=ROOT,
        )


@pytest.mark.parametrize(
    "needle",
    ["/tmp/private", "/Users/example/repo", "https://example.test", "Bearer abc"],
)
def test_sanitized_artifacts_reject_paths_urls_and_credentials(needle: str) -> None:
    with pytest.raises(gate.GateError, match="forbidden"):
        gate._assert_sanitized(json.dumps({"value": needle}).encode())


def test_complete_raw_bundles_are_temporary_and_partial_storage_is_explicit() -> None:
    source = (ROOT / "scripts" / "v060_provider_live_gate.py").read_text()
    assert 'TemporaryDirectory(prefix="grift-v060-live-")' in source
    parser = gate._parser()
    options = {action.dest for action in parser._actions}
    assert "bundle_out" not in options
    assert "raw_out" not in options
    assert {"registry_output", "replace_registry", "partial_bundle_root"}.issubset(options)


def test_resumable_partial_is_private_atomic_and_completes_from_seed(tmp_path: Path) -> None:
    spec = gate._selected("pr")[0]
    locator = parse_forge_locator("github.com/acme/widget")
    oid = GitObjectId("sha1", spec.target_oid)
    working = tmp_path / "first-run-bundle"
    token = "runtime-provider-secret"
    partial = collect_public_evidence(
        locator,
        oid,
        transport=lambda _request: HttpResponse(
            status=429,
            body=b'{"message":"rate limited"}',
            headers={"retry-after": "60"},
        ),
        evidence_dir=working,
        auth_token=token,
    )
    assert partial["coverage"]["status"] == "unavailable"

    evidence_root = tmp_path / "provider-live-evidence"
    registry = evidence_root / "public-registry"
    registry.mkdir(parents=True)
    sentinel = registry / "sanitized-only.json"
    sentinel.write_text("{}\n", encoding="utf-8")
    private_root = evidence_root / "private-resume-bundles"
    preserved = gate._preserve_private_bundle(
        working,
        private_root,
        spec,
        secrets=(token,),
    )
    assert preserved == private_root / spec.scenario_id
    assert sentinel.read_text(encoding="utf-8") == "{}\n"
    assert registry not in preserved.parents
    for path in (private_root, preserved, *preserved.rglob("*")):
        mode = path.lstat().st_mode
        expected = 0o700 if stat.S_ISDIR(mode) else 0o600
        assert stat.S_IMODE(mode) == expected
        if stat.S_ISREG(mode):
            assert token.encode() not in path.read_bytes()

    seeded = tmp_path / "second-run-bundle"
    gate._seed_private_bundle(preserved, seeded, spec)
    command = gate._repo_command(
        tmp_path / "repo",
        spec,
        tmp_path / "out",
        mode="resume",
        bundle=seeded,
        token_env="TOKEN_NAME",
    )
    assert "--resume-public-evidence" in command
    assert "--fetch-public" not in command
    assert "--public-evidence-out" not in command
    resumed = collect_public_evidence(
        locator,
        oid,
        transport=lambda request: HttpResponse(status=200, body=b"[]", headers={}),
        evidence_dir=seeded,
        auth_token=token,
        resume=True,
    )
    assert resumed["coverage"]["status"] == "complete"
    assert verify_public_evidence(seeded)["status"] == "VERIFIED"

    gate._remove_private_bundle(private_root, spec)
    assert not preserved.exists()
    assert sentinel.exists()


def test_private_partial_storage_rejects_token_symlink_and_unowned_root(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "manifest.json").write_text("{}\n", encoding="utf-8")
    (unsafe / "body").write_text("actual-provider-secret", encoding="utf-8")
    with pytest.raises(gate.GateError, match="provider credential"):
        gate._secure_private_bundle_tree(unsafe, secrets=("actual-provider-secret",))
    (unsafe / "body").write_text(
        "actual%252Dprovider%252Dsecret",
        encoding="utf-8",
    )
    with pytest.raises(gate.GateError, match="provider credential"):
        gate._secure_private_bundle_tree(unsafe, secrets=("actual-provider-secret",))

    unowned = tmp_path / "unowned"
    unowned.mkdir()
    (unowned / "someone-elses-file").write_text("keep\n", encoding="utf-8")
    with pytest.raises(gate.GateError, match="unowned"):
        gate._private_resume_root(unowned, create=True)
    assert (unowned / "someone-elses-file").read_text(encoding="utf-8") == "keep\n"

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(gate.GateError, match="symlink"):
        gate._private_resume_root(linked, create=True)


@pytest.mark.parametrize(
    ("depth", "reason"),
    [*((depth, "provider credential") for depth in range(17)), (17, "excessively")],
)
def test_private_partial_token_decode_boundary(
    tmp_path: Path,
    depth: int,
    reason: str,
) -> None:
    token = b"provider-secret"
    encoded = token
    for _ in range(depth):
        encoded = encoded.replace(b"%", b"%25").replace(b"-", b"%2D")
    bundle = tmp_path / f"bundle-{depth}"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}\n", encoding="utf-8")
    (bundle / "body").write_bytes(encoded)

    with pytest.raises(gate.GateError, match=reason):
        gate._secure_private_bundle_tree(bundle, secrets=(token.decode(),))


def test_private_partial_scans_inactive_provider_token(tmp_path: Path) -> None:
    spec = gate._selected("pr")[0]
    locator = parse_forge_locator("github.com/acme/widget")
    inactive = "gitlab-token-must-not-persist"
    source = tmp_path / "partial"
    collect_public_evidence(
        locator,
        GitObjectId("sha1", spec.target_oid),
        transport=lambda _request: HttpResponse(
            status=429,
            body=inactive.encode(),
            headers={"retry-after": "60"},
        ),
        evidence_dir=source,
        auth_token="github-active-token",
    )

    with pytest.raises(gate.GateError, match="provider credential"):
        gate._preserve_private_bundle(
            source,
            tmp_path / "private",
            spec,
            secrets=("github-active-token", inactive),
        )


def test_provider_subprocess_environment_exposes_only_selected_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("CUSTOM_GITLAB_TOKEN", "gitlab-secret")
    monkeypatch.setenv("V060_GITHUB_TOKEN", "default-github-secret")
    monkeypatch.setenv("UNRELATED_SETTING", "keep")
    tokens = {
        "CUSTOM_GITHUB_TOKEN": "github-secret",
        "CUSTOM_GITLAB_TOKEN": "gitlab-secret",
    }

    selected = gate._environment(
        ROOT,
        selected_token_env="CUSTOM_GITHUB_TOKEN",
        provider_tokens=tokens,
    )
    offline = gate._environment(ROOT, provider_tokens=tokens)

    assert selected["CUSTOM_GITHUB_TOKEN"] == "github-secret"
    assert "CUSTOM_GITLAB_TOKEN" not in selected
    assert "V060_GITHUB_TOKEN" not in selected
    assert selected["UNRELATED_SETTING"] == "keep"
    assert "CUSTOM_GITHUB_TOKEN" not in offline
    assert "CUSTOM_GITLAB_TOKEN" not in offline
    matrix_git_environment = gate.isolated_subprocess_environment.__wrapped__.__globals__[
        "_git_environment"
    ]
    with gate.isolated_subprocess_environment(tuple(tokens)):
        git_environment = matrix_git_environment()
    assert "CUSTOM_GITHUB_TOKEN" not in git_environment
    assert "CUSTOM_GITLAB_TOKEN" not in git_environment


def test_private_resume_path_rejects_dotdot_before_normalization(tmp_path: Path) -> None:
    unsafe = tmp_path / "safe" / ".." / "victim"
    with pytest.raises(gate.GateError, match="lexically safe"):
        gate._private_resume_root(unsafe, create=True)
    assert not (tmp_path / "victim").exists()


def test_failure_result_preserves_fixed_resume_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = gate._selected("pr")[0]
    prior = {
        "manifest": {"algorithm": "sha256", "value": "a" * 64},
        "payload": {"algorithm": "sha256", "value": "b" * 64},
    }
    acquisition = gate.AcquisitionContext("resume", prior)
    binding = {
        "tool_version": "0.6.0",
        "source_binding": {
            "definition_version": "grift-tool-source-tree-v1",
            "source_tree_digest": {"algorithm": "sha256", "value": "c" * 64},
            "file_count": 1,
            "commit_oid": {"algorithm": "sha1", "value": "d" * 40},
        },
    }
    monkeypatch.setattr(gate, "_selected", lambda _tier: (spec,))
    monkeypatch.setattr(gate, "build_runner_binding", lambda _root: binding)
    monkeypatch.setattr(gate, "definition_digest", lambda _tier: "e" * 64)
    monkeypatch.setattr(gate, "_acquisition_context", lambda *_a, **_k: acquisition)
    monkeypatch.setattr(gate, "_has_private_bundle", lambda *_a, **_k: True)

    def fail_scenario(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise gate.GateError("injected failure after resume selection")

    monkeypatch.setattr(gate, "_run_scenario", fail_scenario)
    monkeypatch.setenv("CUSTOM_GITHUB_TOKEN", "github-secret-not-for-summary")
    monkeypatch.setenv("CUSTOM_GITLAB_TOKEN", "gitlab-secret-not-for-summary")
    args = argparse.Namespace(
        tier="pr",
        repo_root=tmp_path / "repos",
        summary=tmp_path / "summary.json",
        ledger=tmp_path / "ledger.jsonl",
        github_token_env="CUSTOM_GITHUB_TOKEN",
        gitlab_token_env="CUSTOM_GITLAB_TOKEN",
        source_commit="d" * 40,
        suite_deadline_epoch=None,
        partial_bundle_root=tmp_path / "private",
        registry_output=None,
        replace_registry=False,
    )

    assert gate.run_gate(args) == 1
    result = json.loads(args.summary.read_text(encoding="utf-8"))["results"][0]
    assert result["collection_mode"] == "resume"
    assert result["prior_evidence_digests"] == prior
    assert result["outcome"] == "FAIL"
    summary_bytes = args.summary.read_bytes()
    assert b"github-secret-not-for-summary" not in summary_bytes
    assert b"gitlab-secret-not-for-summary" not in summary_bytes


def test_forced_partial_is_fresh_and_unstaged_on_two_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = next(row for row in gate._selected("pr") if row.expected_partial)
    synthetic = _result(spec)
    state = synthetic["states"]["offline"]
    provider = synthetic["provider_evidence"]
    commands: list[list[str]] = []

    def git_count(_repo: Path, _oid: str, *extra: str, **_kwargs: object) -> int:
        if "--no-merges" in extra:
            return spec.counts.raw_nonmerge
        if "--merges" in extra:
            return spec.counts.raw_merge
        return spec.counts.total

    @contextmanager
    def materialized(source: Path, _oid: str):
        yield source

    def execute(argv: object, **_kwargs: object) -> dict[str, int]:
        commands.append(list(argv))
        return {"exit_code": 0, "duration_ms": 1}

    def no_preserve(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("forced partial must not be staged")

    monkeypatch.setattr(gate, "_git_count", git_count)
    monkeypatch.setattr(gate, "materialize_read_only_repo", materialized)
    monkeypatch.setattr(gate, "_execute", execute)
    monkeypatch.setattr(gate, "_collection_state", lambda _path: copy.deepcopy(state))
    monkeypatch.setattr(
        gate,
        "_manifest_state",
        lambda *_args, **_kwargs: copy.deepcopy(provider),
    )
    monkeypatch.setattr(gate, "_preserve_private_bundle", no_preserve)
    monkeypatch.setattr(gate, "validate_scenario_result", lambda *_args: [])

    results = [
        gate._run_scenario_inner(
            spec,
            source=tmp_path / "repo",
            project_root=ROOT,
            token_env=None,
            provider_tokens={},
            acquisition=gate.AcquisitionContext(),
            suite_deadline=time.monotonic() + 60,
            partial_bundle_root=tmp_path / "private",
        )
        for _ in range(2)
    ]

    assert all(result["collection_mode"] == "fresh" for result in results)
    assert all(result["prior_evidence_digests"] is None for result in results)
    assert all(result["resumable_partial_staged"] is False for result in results)
    assert all(result["provider_evidence"]["pages"] == spec.expected_pages for result in results)
    assert all(result["provider_evidence"]["items"] == spec.expected_items for result in results)
    assert sum("--fetch-public" in argv for argv in commands) == 2
    assert not any("--resume-public-evidence" in argv for argv in commands)
    assert not (tmp_path / "private").exists()


def test_seed_and_preserve_reject_nested_link_before_external_read_or_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = gate._selected("pr")[0]
    locator = parse_forge_locator("github.com/acme/widget")
    source = tmp_path / "partial"
    collect_public_evidence(
        locator,
        GitObjectId("sha1", spec.target_oid),
        transport=lambda _request: HttpResponse(status=429, body=b"{}", headers={}),
        evidence_dir=source,
    )
    nested = source / "nested"
    nested.mkdir()
    external = tmp_path / "external-secret"
    external.write_text("must-never-be-read-or-copied\n", encoding="utf-8")
    (nested / "escape").symlink_to(external)

    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == external:
            raise AssertionError("external symlink target was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    destination = tmp_path / "seeded"
    with pytest.raises(gate.GateError, match="symlink"):
        gate._seed_private_bundle(source, destination, spec)
    private_root = tmp_path / "private"
    with pytest.raises(gate.GateError, match="symlink"):
        gate._preserve_private_bundle(source, private_root, spec)
    assert not destination.exists()
    assert not private_root.exists()
    assert external.read_text(encoding="utf-8") == "must-never-be-read-or-copied\n"

    (nested / "escape").unlink()
    fifo = nested / "device"
    os.mkfifo(fifo)
    with pytest.raises(gate.GateError, match="non-regular"):
        gate._seed_private_bundle(source, destination, spec)
    with pytest.raises(gate.GateError, match="non-regular"):
        gate._preserve_private_bundle(source, private_root, spec)
    assert not destination.exists()
    assert not private_root.exists()


def test_atomic_partial_replacement_restores_previous_bundle_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = gate._selected("pr")[0]
    locator = parse_forge_locator("github.com/acme/widget")
    source = tmp_path / "partial"
    collect_public_evidence(
        locator,
        GitObjectId("sha1", spec.target_oid),
        transport=lambda _request: HttpResponse(status=429, body=b"{}", headers={}),
        evidence_dir=source,
    )
    private_root = tmp_path / "private"
    target = gate._preserve_private_bundle(source, private_root, spec)
    original_inode = target.stat().st_ino
    original_replace = gate.os.replace
    calls = 0

    def fail_install(source_path: object, target_path: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected install failure")
        original_replace(source_path, target_path)

    monkeypatch.setattr(gate.os, "replace", fail_install)
    with pytest.raises(OSError, match="injected install failure"):
        gate._preserve_private_bundle(source, private_root, spec)
    assert calls == 3
    assert target.stat().st_ino == original_inode
    assert verify_public_evidence(target)["status"] == "VERIFIED"
    assert not list(private_root.glob(f".{spec.scenario_id}.*-*"))
