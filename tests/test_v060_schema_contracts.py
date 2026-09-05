"""Strict v0.6 schema assets, stdlib runtime, and semantic invariants."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tep_core.contribution_v2 import PURPOSE, SOURCE_REPLAY_BY_PROFILE, TRANSFORMATION_SPEC_DIGESTS
from tep_core.experience import ExperienceCommit, FileChange, TenantConsent, build_experience
from tep_core.forge_public import GitObjectId, HttpResponse, parse_forge_locator
from tep_core.public_evidence import collect_public_evidence
from tep_core.role_profile import build_role_profile
from tep_core.schema import load_schema, schema_names, validate_report, validate_schema
from tep_core.schema_v2 import validate_alignment

HEX40 = "a" * 40
HEX64 = "b" * 64
OID = {"algorithm": "sha1", "value": HEX40}
PROVENANCE_OID = {"algorithm": "sha1", "value": HEX40}
DIGEST = {"algorithm": "sha256", "value": HEX64}
WINDOW = {
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-02-01T00:00:00Z",
}
PERIOD = {"start": "2026-01-01", "end": "2026-02-01", "unit": "date-range"}
ACTOR_ID = "actor_" + "a" * 20
LIMITATIONS = ["Observation only; not a score."]


def _metric(numerator: int = 1, denominator: int = 2) -> dict[str, Any]:
    return {
        "kind": "observed",
        "value": numerator / denominator,
        "numerator": numerator,
        "denominator": denominator,
        "unit": "ratio",
        "window": copy.deepcopy(WINDOW),
        "definition_version": "metric-v1",
        "limitations": copy.deepcopy(LIMITATIONS),
    }


def _policy(kind: str = "ssh") -> dict[str, Any]:
    if kind == "ssh":
        return {"kind": "ssh", "namespace": "grift-attestation-v1", "principal": "alice"}
    return {"kind": "cosign-key", "public_key_sha256": HEX64}


def _account() -> dict[str, Any]:
    return {
        "provider": "github",
        "host": "github.com",
        "account_id": "42",
        "handle": "alice",
        "profile_url": "https://github.com/alice",
        "evidence": {"basis": "commit_sha_to_account", "commit_oid": copy.deepcopy(OID)},
    }


def _contribution_account() -> dict[str, Any]:
    return {
        "provider": "github",
        "host": "github.com",
        "account_id": "42",
        "handle": "alice",
        "profile_url": "https://github.com/alice",
        "evidence": {
            "basis": "commit.author.id",
            "coverage_status": "partial",
            "account_match_status": "linked",
        },
    }


def _contribution_base(profile: str, door: str) -> dict[str, Any]:
    external = door == "public-pr"
    return {
        "contribution_schema": "tep-contribution-v2",
        "privacy_profile": profile,
        "door": door,
        "purpose": PURPOSE,
        "provenance_receipt_id": "receipt_" + "a" * 26,
        "transformation_spec_digest": TRANSFORMATION_SPEC_DIGESTS[profile],
        "policy": {
            "access_class": "public" if external else "controlled_local",
            "public_payload": external,
            "source_replay": SOURCE_REPLAY_BY_PROFILE[profile],
        },
    }


def _masked_contribution() -> dict[str, Any]:
    payload = _contribution_base("masked", "controlled")
    payload["data"] = {
        "actors": [
            {
                "actor_pid": "pa_" + "a" * 26,
                "measurements": {
                    "n": 20,
                    "denominator": 20,
                    "basis": "git_primary_author_cluster",
                    "commit_count_includes_merges": True,
                    "nonmerge_n": 18,
                    "merge_n": 2,
                },
            }
        ],
        "population": {"n": 1, "denominator": 20, "basis": "git_primary_author_cluster"},
        "measurements": {},
        "coverage": _coverage(),
        "missingness": [],
        "research": {"key_id": "key-1", "epoch": "2026", "study_id": "study-1"},
    }
    return payload


def _coverage() -> dict[str, Any]:
    return {"git": {"kind": "observed", "provided": True}}


def _attribution() -> dict[str, Any]:
    return {
        "observed_actor_count": 1,
        "attributed_commit_count": 2,
        "attribution_human_including_merges": 2,
        "repo_human_nonmerge_commits": 1,
        "unresolved_commit_count": 0,
        "attribution_unresolved_commit_count": 0,
        "attribution_coverage": {
            "kind": "observed",
            "value": 1.0,
            "unit": "ratio",
            "sample_size": 2,
        },
        "bot_count": 0,
        "merge_count": 1,
        "coauthored_count": 0,
        "mailmap_present": False,
        "human_commit_count": 1,
        "population_identity": (
            "repo_human_nonmerge_commits + merge_count = "
            "attribution_human_including_merges + attribution_unresolved_commit_count"
        ),
        "unresolved_definitions": {
            "origin_unresolved": "origin class unresolved",
            "attribution_unresolved": "no stable actor key",
        },
        "actor_partition": {
            "definition": "repo_local_git_primary_author_cluster",
            "repo_scope_digest": HEX64,
            "object_format": "sha1",
            "partition_digest": HEX64,
            "sha_to_actor_digest": HEX64,
            "provider_enrichment_changes_partition": False,
        },
        "public_join": {
            "matched": 0,
            "unmatched": 1,
            "ambiguous": 0,
            "public_handle_actors": 0,
            "fetched_login_count": None,
            "commit_login_count": 0,
            "account_conflict_count": 0,
            "count_note": "provider list size is not an actor join",
        },
    }


def _base_instances() -> dict[str, dict[str, Any]]:
    report = {
        "schema_version": "report-v2",
        "report_kind": "evidence",
        "subject": {"kind": "repo", "selection": "repo_all_human"},
        "target": {"oid": copy.deepcopy(OID)},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "definition_version": "tep-v0.6.0",
            "analysis_scope": "repo",
            "analyzed_at": "2026-02-01T00:00:00Z",
            "input_digests": {
                "git": copy.deepcopy(DIGEST),
                "tagset": "e" * 64,
            },
            "tagset_digest": "e" * 64,
            "target_oid": copy.deepcopy(PROVENANCE_OID),
            "revision_completeness": {"shallow": False, "promisor": False, "complete": True},
        },
        "population": {
            "actor_count": 1,
            "human_commit_count": 2,
            "nonmerge_commit_count": 1,
            "merge_commit_count": 1,
            "basis": "git_primary_author_cluster",
            "partition_digest": copy.deepcopy(DIGEST),
            "population_digest": copy.deepcopy(DIGEST),
        },
        "attribution": _attribution(),
        "window": copy.deepcopy(WINDOW),
        "metrics": {"activity_share": _metric()},
        "limitations": copy.deepcopy(LIMITATIONS),
        "notices": ["Evidence, not a verdict."],
    }
    population_for_digest = {
        key: report["population"][key]
        for key in (
            "actor_count",
            "human_commit_count",
            "nonmerge_commit_count",
            "merge_commit_count",
            "basis",
            "partition_digest",
        )
    }
    report["population"]["population_digest"]["value"] = hashlib.sha256(
        b"tep-population-v1\0"
        + json.dumps(
            population_for_digest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    actor_card = {
        "schema_version": "actor-card-v1",
        "report_kind": "actor_card",
        "actor_id": ACTOR_ID,
        "target": {"oid": copy.deepcopy(OID)},
        "partition_digest": copy.deepcopy(DIGEST),
        "population_digest": copy.deepcopy(DIGEST),
        "n": 1,
        "denominator": 2,
        "window": copy.deepcopy(WINDOW),
        "basis": "git_primary_author_cluster",
        "account_status": "unmatched",
        "accounts": [],
        "metrics": {"activity_share": _metric()},
        "limitations": copy.deepcopy(LIMITATIONS),
        "notices": ["Repo-local actor cluster."],
    }
    actor_index = {
        "schema_version": "actor-index-v1",
        "report_kind": "actor_index",
        "target": {"oid": copy.deepcopy(OID)},
        "partition_digest": copy.deepcopy(DIGEST),
        "population_digest": copy.deepcopy(DIGEST),
        "population": {
            "actor_count": 1,
            "human_commit_count": 2,
            "basis": "git_primary_author_cluster",
            "window": copy.deepcopy(WINDOW),
        },
        "actors": [
            {
                "actor_id": ACTOR_ID,
                "commit_count": 2,
                "nonmerge_commit_count": 1,
                "merge_commit_count": 1,
            }
        ],
        "selection": {"mode": "all", "selected_count": 1, "actor_ids": [ACTOR_ID]},
        "limitations": copy.deepcopy(LIMITATIONS),
    }
    project = {
        "schema_version": "project-v1",
        "report_kind": "project",
        "project_id": "demo",
        "target": {"oid": copy.deepcopy(OID)},
        "provenance_digest": copy.deepcopy(DIGEST),
        "window": copy.deepcopy(WINDOW),
        "declared": {"verification": _metric()},
        "observed": {"verification": _metric()},
        "limitations": copy.deepcopy(LIMITATIONS),
        "notices": ["Declared and observed remain separate."],
    }
    alignment = {
        "schema_version": "alignment-v1",
        "report_kind": "alignment",
        "subject": {
            "kind": "alignment",
            "actor_canonical_id": ACTOR_ID,
            "actor_selection": "inferred_actor",
            "project_id": "demo",
        },
        "actor_report_digest": copy.deepcopy(DIGEST),
        "project_report_digest": copy.deepcopy(DIGEST),
        "target": {"oid": copy.deepcopy(OID)},
        "window": copy.deepcopy(WINDOW),
        "axes": [
            {
                "axis": "verification",
                "actor_observed": _metric(),
                "project_observed": _metric(),
                "project_declared": _metric(),
                "actor_n": 1,
                "project_n": 1,
                "actor_denominator": 2,
                "project_denominator": 2,
                "actor_source": ["git"],
                "project_source": ["git"],
                "actor_basis": "actor commits",
                "project_basis": "project commits",
                "relationship": "similar_direction",
                "coverage": "present",
                "limitations": copy.deepcopy(LIMITATIONS),
            }
        ],
        "limitations": copy.deepcopy(LIMITATIONS),
        "notices": ["No fit score."],
    }
    public = {
        "schema_version": "public-evidence-v1",
        "provider": "github",
        "api_version": "2022-11-28",
        "source": {
            "provider": "github",
            "host": "github.com",
            "project_path": "acme/demo",
            "api_base": "https://api.github.com",
            "sanitized_remote": "github.com/acme/demo",
        },
        "target_oid": copy.deepcopy(OID),
        "fetched_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "collection_policy": {
            "network": "explicit_opt_in",
            "robots": "not_applicable_to_rest_api",
            "api_terms": "provider_terms_apply",
        },
        "account_linkage": "complete",
        "coverage": {"status": "complete", "item_count": 1, "missing": []},
        "pagination": {
            "pages": 1,
            "per_page": 100,
            "truncated": False,
            "stop_reason": "no_next_page",
            "next_request": None,
        },
        "pages": [
            {
                "number": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.github.com/repos/acme/demo/commits?per_page=100",
                    "headers": {"Accept": "application/json"},
                },
                "http_status": 200,
                "response_headers": {"etag": "page-1"},
                "body_sha256": HEX64,
                "body_bytes": 10,
                "item_count": 1,
            }
        ],
        "commit_oids": [HEX40],
        "duplicate_commit_oids": [],
        "sha_to_account": {
            HEX40: {
                "provider": "github",
                "host": "github.com",
                "account_id": "42",
                "handle": "alice",
                "profile_url": "https://github.com/alice",
                "evidence": {"basis": "commit.author.id", "commit_oid": HEX40},
            }
        },
        "mapping_conflicts": [],
        "unlinked_commit_count": 0,
        "bundle_payload_sha256": HEX64,
    }
    aggregate = _contribution_base("aggregate", "local")
    aggregate["data"] = {
        "measurements": {"activity": {"kind": "observed", "value_bucket": "00-10%"}},
        "population": {"n": 2, "denominator": 137},
        "coverage": _coverage(),
        "missingness": [],
    }
    sidecar = {
        "schema_version": "tep-controlled-sidecar-v1",
        "receipt_id": "receipt_" + "a" * 26,
        "privacy_profile": "masked",
        "payload_sha256": HEX64,
        "source": {
            "report_sha256": HEX64,
            "provenance": {},
            "repository": {},
            "identity": {},
            "actor_partition": None,
            "actor_correspondence": [],
        },
        "governance": {
            "purpose": PURPOSE,
            "controller": "research-controller-1",
            "authority": "repository-owner-authorization",
            "consent": "recorded-explicit-consent",
            "study_id": "study-1",
            "key_id": "key-1",
            "epoch": "2026",
            "retention": "until-2027-08-31",
            "withdrawal": "contact-controller-before-publication",
            "access_class": "named-research-team",
        },
    }
    attest = {
        "schema_version": "tep-attest-v1",
        "statement_type": "grift-report-attestation",
        "report": {"schema_version": "report-v2", "digest": copy.deepcopy(DIGEST)},
        "target": {"oid": copy.deepcopy(OID)},
        "measurement": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "definition_version": "tep-v0.6.0",
            "analysis_scope": "repo",
        },
        "scope": {"analysis_scope": "repo"},
        "inputs": {
            "aggregate_digest": copy.deepcopy(DIGEST),
            "members": {
                "public_evidence": None,
                "tagset": copy.deepcopy(DIGEST),
            },
        },
        "definition_versions": {"digest": copy.deepcopy(DIGEST)},
        "public_evidence": {"digest": None},
        "tagset": {"digest": copy.deepcopy(DIGEST)},
        "runner_hint": "grift attest",
        "executed_at": "2026-02-01T00:00:00Z",
        "expected_signer_policy": _policy(),
    }
    bundle = {
        "schema_version": "tep-attest-bundle-v1",
        "statement": {"path": "statement.json", "digest": copy.deepcopy(DIGEST)},
        "signature": {
            "kind": "ssh",
            "path": "statement.json.sig",
            "digest": copy.deepcopy(DIGEST),
        },
    }
    evidence = {
        "report": {
            "schema_version": "report-v2",
            "digest": copy.deepcopy(DIGEST),
            "target_oid": copy.deepcopy(OID),
            "definition_version": "tep-v0.6.0",
        },
        "attestation": {
            "statement_digest": copy.deepcopy(DIGEST),
            "bundle_manifest_digest": copy.deepcopy(DIGEST),
            "signature_digest": copy.deepcopy(DIGEST),
            "signer_policy": _policy(),
            "signature_verification": "not_verified_self_declared",
        },
    }
    entry = {
        "entry_id": "one",
        "subject_binding": {"method": "self_declared", "subject_id": "alice"},
        "context": "maintenance",
        "role": "maintainer",
        "period": copy.deepcopy(PERIOD),
        "activity_month_count": 2,
        "repository_bindings": [copy.deepcopy(DIGEST)],
        "evidence": evidence,
    }
    portfolio = {
        "schema_version": "tep-portfolio-v1",
        "report_kind": "portfolio",
        "portfolio_id": "portfolio-1",
        "subject_binding": {"method": "self_declared", "subject_id": "alice"},
        "summary": {
            "eligible_repository_count": 1,
            "included_repository_count": 1,
            "disclosure": {
                "kind": "declared",
                "numerator": 1,
                "denominator": 1,
                "value": 1.0,
                "unit": "ratio",
            },
            "period": copy.deepcopy(PERIOD),
        },
        "entries": [entry],
        "limitations": copy.deepcopy(LIMITATIONS),
        "notices": ["Selection is self-declared."],
    }
    portfolio_manifest = {
        "schema_version": "tep-portfolio-manifest-v1",
        "portfolio_id": "portfolio-1",
        "subject_id": "alice",
        "subject_binding": "self_declared",
        "eligible_repository_count": 1,
        "entries": [
            {
                "entry_id": "one",
                "subject_id": "alice",
                "subject_binding": "self_declared",
                "context": "maintenance",
                "role": "maintainer",
                "period_start": "2026-01-01",
                "period_end": "2026-02-01",
                "activity_month_count": 2,
                "report": "report.json",
                "attestation_bundle": "attest",
            }
        ],
    }
    scenario_manifest = {
        "schema_version": "tep-scenario-manifest-v1",
        "suite_id": "v060",
        "definition_version": "scenario-v1",
        "scenarios": [
            {
                "id": "local-1",
                "tier": "local",
                "target_oid": copy.deepcopy(OID),
                "expected_artifacts": ["report.json"],
                "timeout_seconds": 180,
            }
        ],
    }
    scenario_result = {
        "schema_version": "tep-scenario-result-v1",
        "scenario_id": "local-1",
        "runner": {
            "tool_version": "0.6.0",
            "source_binding": {
                "definition_version": "grift-tool-source-tree-v1",
                "source_tree_digest": copy.deepcopy(DIGEST),
                "file_count": 1,
                "commit_oid": None,
            },
        },
        "target_oid": copy.deepcopy(OID),
        "argv": ["grift", "repo"],
        "exit_code": 0,
        "duration_ms": 10,
        "counts": {"actors": 1},
        "partition_digest": copy.deepcopy(DIGEST),
        "provider_coverage": {"kind": "not_observed", "provided": False},
        "output_digests": {"report.json": copy.deepcopy(DIGEST)},
        "assertions": [{"id": "actor-count", "status": "PASS", "expected": 1, "actual": 1}],
        "verdict": "PASS",
    }
    scenario_summary = {
        "schema_version": "tep-scenario-summary-v1",
        "suite_id": "v060",
        "manifest_digest": copy.deepcopy(DIGEST),
        "result_digests": [copy.deepcopy(DIGEST)],
        "counts": {"total": 1, "pass": 1, "fail": 0, "not_proven": 0, "source_drift": 0},
        "verdict": "PASS",
    }
    binding = {
        "provider": "gitlab",
        "host": "gitlab.example.test",
        "project_id": "42",
        "project_path": "group/demo",
        "target_oid": copy.deepcopy(OID),
        "window": copy.deepcopy(WINDOW),
        "coverage": {
            "status": "complete",
            "observed": 1,
            "expected": 1,
            "unit": "events",
            "missing": 0,
        },
    }
    forge = {
        "schema_version": "tep-forge-export-v2",
        "binding": copy.deepcopy(binding),
        "events": [
            {
                "event_id": "f-1",
                "kind": "pull_request_review",
                "timestamp": "2026-01-15T00:00:00Z",
                "actor_canonical_id": "alice",
                "pr_number": 1,
                "commit_sha": HEX40,
                "project_id": "42",
                "project_path": "group/demo",
            }
        ],
    }
    tracker = {
        "schema_version": "tep-tracker-export-v2",
        "binding": copy.deepcopy(binding),
        "events": [
            {
                "event_id": "t-1",
                "kind": "issue_opened",
                "timestamp": "2026-01-15T00:00:00Z",
                "actor_canonical_id": "alice",
                "issue_number": 1,
                "commit_sha": HEX40,
                "project_id": "42",
                "project_path": "group/demo",
                "record_type": "issue",
                "record_id": "issue-1",
                "state": "open",
                "previous_state": None,
                "previous_event_id": None,
                "linked_event_id": None,
                "duration_seconds": None,
            }
        ],
    }
    identity = {
        "schema_version": "identity-v2",
        "actors": [
            {
                "canonical_id": "alice",
                "attribution_state": "verified",
                "email_sha256": [HEX64],
            }
        ],
    }
    not_consented = {
        "kind": "not_observed",
        "actor_id": ACTOR_ID,
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": copy.deepcopy(LIMITATIONS),
    }
    return {
        "report-v2": report,
        "actor-card-v1": actor_card,
        "actor-index-v1": actor_index,
        "project-v1": project,
        "alignment-v1": alignment,
        "public-evidence-v1": public,
        "contribution-v2": aggregate,
        "controlled-sidecar-v1": sidecar,
        "attest-v1": attest,
        "attest-bundle-v1": bundle,
        "portfolio-v1": portfolio,
        "portfolio-manifest-v1": portfolio_manifest,
        "scenario-manifest-v1": scenario_manifest,
        "scenario-result-v1": scenario_result,
        "scenario-summary-v1": scenario_summary,
        "forge-export-v2": forge,
        "tracker-export-v2": tracker,
        "identity-v2": identity,
        "experience-v1": not_consented,
        "role-profile-v1": {**not_consented, "definition_version": "role-profile-v1"},
    }


def _jsonschema_errors(name: str, payload: Any) -> list[Any]:
    jsonschema = pytest.importorskip("jsonschema")
    checker = jsonschema.FormatChecker()
    return list(
        jsonschema.Draft202012Validator(load_schema(name), format_checker=checker).iter_errors(
            payload
        )
    )


@pytest.mark.parametrize("name", schema_names())
def test_each_contract_is_a_valid_draft202012_schema(name: str) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(load_schema(name))


@pytest.mark.parametrize("name", schema_names())
def test_every_v060_contract_accepts_its_canonical_instance(name: str) -> None:
    payload = _base_instances()[name]
    assert validate_schema(name, payload) == []
    assert _jsonschema_errors(name, payload) == []


def test_attest_report_v2_requires_reachable_tagset_binding() -> None:
    payload = copy.deepcopy(_base_instances()["attest-v1"])
    payload["inputs"]["members"].pop("tagset")
    payload["tagset"]["digest"] = None

    runtime_errors = "\n".join(validate_schema("attest-v1", payload))
    assert "tagset" in runtime_errors
    assert _jsonschema_errors("attest-v1", payload)


def test_experience_producer_matches_strict_observed_contract() -> None:
    started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commit = ExperienceCommit(
        oid=HEX40,
        actor_id="alice",
        authored_at=started_at,
        message="initial implementation",
        changes=(FileChange("A", "src/main.py"),),
        parents=("parent",),
        repository_commit_count_after=1,
        repository_file_count_after=1,
        repository_line_count_after=10,
    )
    payload = build_experience(
        [commit],
        actor_id="alice",
        consent=TenantConsent(actor_id="alice", basis="explicit_owner_declaration"),
        observation_end=started_at + timedelta(days=40),
        min_population=1,
    )
    assert validate_schema("experience-v1", payload) == []
    assert _jsonschema_errors("experience-v1", payload) == []
    mutated = copy.deepcopy(payload)
    mutated["metrics"]["language_domain_timeline"]["periods"][0]["languages"]["values"]["python"][
        "share"
    ] = 0.5
    assert any("n / denominator" in error for error in validate_schema("experience-v1", mutated))


def test_insufficient_population_cannot_disclose_zero_ai_state() -> None:
    started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commits = [
        ExperienceCommit(
            oid=f"{index:040x}",
            actor_id="alice",
            authored_at=started_at + timedelta(days=index),
            message="change",
            parents=() if index == 0 else (f"{index - 1:040x}",),
        )
        for index in range(19)
    ]
    payload = build_experience(
        commits,
        actor_id="alice",
        consent=TenantConsent(actor_id="alice", basis="explicit_owner_declaration"),
    )
    metric = payload["metrics"]["declared_ai_assist_share"]
    assert metric["reason"] == "insufficient_population"
    assert "observation_state" not in metric

    mutated = copy.deepcopy(payload)
    mutated["metrics"]["declared_ai_assist_share"]["observation_state"] = "no_declared_ai_commits"
    assert validate_schema("experience-v1", mutated)
    assert _jsonschema_errors("experience-v1", mutated)


@pytest.mark.parametrize(
    "metric_name",
    ["cadence", "language_domain_timeline", "repository_size_at_contribution_points"],
)
def test_experience_special_observations_require_auditable_numerator(
    metric_name: str,
) -> None:
    started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commit = ExperienceCommit(
        oid=HEX40,
        actor_id="alice",
        authored_at=started_at,
        message="initial implementation",
        changes=(FileChange("A", "src/main.py"),),
        parents=(),
        repository_commit_count_after=1,
        repository_file_count_after=1,
        repository_line_count_after=10,
    )
    payload = build_experience(
        [commit],
        actor_id="alice",
        consent=TenantConsent(actor_id="alice", basis="explicit_owner_declaration"),
        observation_end=started_at + timedelta(days=40),
        min_population=1,
    )
    mutated = copy.deepcopy(payload)
    mutated["metrics"][metric_name].pop("numerator")
    assert validate_schema("experience-v1", mutated)
    assert _jsonschema_errors("experience-v1", mutated)


def test_experience_special_observation_numerator_invariants() -> None:
    started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commits = [
        ExperienceCommit(
            oid=character * 40,
            actor_id="alice",
            authored_at=started_at + timedelta(days=index),
            message="change",
            changes=(FileChange("A", f"src/{index}.py"),),
            parents=() if index == 0 else (chr(ord("a") + index - 1) * 40,),
            repository_commit_count_after=index + 1,
            repository_file_count_after=index + 1,
            repository_line_count_after=(index + 1) * 10,
        )
        for index, character in enumerate(("a", "b", "c"))
    ]
    payload = build_experience(
        commits,
        actor_id="alice",
        consent=TenantConsent(actor_id="alice", basis="explicit_owner_declaration"),
        observation_end=started_at + timedelta(days=40),
        min_population=1,
    )
    mutations = (
        ("cadence", 0, "adjacent interval count"),
        ("language_domain_timeline", 0, "path-touch commit total"),
        ("repository_size_at_contribution_points", 0, "snapshot commit count"),
    )
    for metric_name, replacement, expected in mutations:
        mutated = copy.deepcopy(payload)
        mutated["metrics"][metric_name]["numerator"] = replacement
        assert any(expected in error for error in validate_schema("experience-v1", mutated))


def test_role_profile_producer_matches_strict_observed_contract() -> None:
    started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commit = ExperienceCommit(
        oid=HEX40,
        actor_id="alice",
        authored_at=started_at,
        message="initial implementation",
        changes=(FileChange("A", "src/main.py"),),
        parents=("parent",),
    )
    payload = build_role_profile(
        [commit],
        actor_id="alice",
        consent=TenantConsent(actor_id="alice", basis="explicit_owner_declaration"),
        observation_end=started_at + timedelta(days=40),
        min_population=1,
    )
    assert validate_schema("role-profile-v1", payload) == []
    assert _jsonschema_errors("role-profile-v1", payload) == []
    mutated = copy.deepcopy(payload)
    mutated["dimensions"]["domain"]["core"]["denominator"] = 2
    assert any("one denominator" in error for error in validate_schema("role-profile-v1", mutated))


def test_public_evidence_producer_matches_strict_contract(tmp_path: Path) -> None:
    body = json.dumps(
        [
            {
                "sha": HEX40,
                "author": {
                    "id": 42,
                    "login": "alice",
                    "html_url": "https://github.com/alice",
                },
            }
        ]
    ).encode("utf-8")
    payload = collect_public_evidence(
        parse_forge_locator("github.com/acme/widget"),
        GitObjectId("sha1", HEX40),
        transport=lambda _request: HttpResponse(status=200, body=body, headers={}),
        evidence_dir=tmp_path / "bundle",
        fetched_at="2026-08-31T00:00:00Z",
    )
    assert validate_schema("public-evidence-v1", payload) == []
    assert _jsonschema_errors("public-evidence-v1", payload) == []


_NESTED_MUTATIONS: dict[str, tuple[Any, ...]] = {
    "report-v2": ("provenance", "revision_completeness"),
    "actor-card-v1": ("target",),
    "actor-index-v1": ("selection",),
    "project-v1": ("target",),
    "alignment-v1": ("axes", 0),
    "public-evidence-v1": ("source",),
    "contribution-v2": ("data", "population"),
    "controlled-sidecar-v1": ("governance",),
    "attest-v1": ("report",),
    "attest-bundle-v1": ("signature",),
    "portfolio-v1": ("summary",),
    "portfolio-manifest-v1": ("entries", 0),
    "scenario-manifest-v1": ("scenarios", 0),
    "scenario-result-v1": ("assertions", 0),
    "scenario-summary-v1": ("counts",),
    "forge-export-v2": ("binding",),
    "tracker-export-v2": ("binding",),
    "identity-v2": ("actors", 0),
    "experience-v1": (),
    "role-profile-v1": (),
}


@pytest.mark.parametrize("name", schema_names())
def test_nested_unknown_key_is_rejected_by_stdlib_and_draft202012(name: str) -> None:
    payload = copy.deepcopy(_base_instances()[name])
    node: Any = payload
    for part in _NESTED_MUTATIONS[name]:
        node = node[part]
    node["unexpected_v060_key"] = True
    # Union contracts intentionally collapse branch errors into a deterministic
    # oneOf/anyOf message.  A non-empty runtime result is the rejection contract;
    # Draft 2020-12 below independently proves the nested additionalProperties
    # violation.
    assert validate_schema(name, payload)
    assert _jsonschema_errors(name, payload)


def _stdlib_alignment_subject_errors(payload: dict[str, Any]) -> list[str]:
    return [error for error in validate_alignment(payload) if error.startswith("$.subject")]


def test_alignment_subject_is_required_closed_and_selection_state_coherent() -> None:
    valid = copy.deepcopy(_base_instances()["alignment-v1"])
    assert validate_schema("alignment-v1", valid) == []
    assert _jsonschema_errors("alignment-v1", valid) == []
    assert _stdlib_alignment_subject_errors(valid) == []

    missing = copy.deepcopy(valid)
    missing.pop("subject")
    assert any("$.subject" in error for error in validate_schema("alignment-v1", missing))
    assert _jsonschema_errors("alignment-v1", missing)
    assert _stdlib_alignment_subject_errors(missing)

    unknown_key = copy.deepcopy(valid)
    unknown_key["subject"]["unexpected"] = True
    assert any("$.subject" in error for error in validate_schema("alignment-v1", unknown_key))
    assert _jsonschema_errors("alignment-v1", unknown_key)
    assert any("unknown keys" in error for error in _stdlib_alignment_subject_errors(unknown_key))

    contradictory = copy.deepcopy(valid)
    contradictory["subject"]["actor_attribution_state"] = "verified"
    assert _jsonschema_errors("alignment-v1", contradictory)
    assert any(
        "actor_attribution_state" in error
        for error in _stdlib_alignment_subject_errors(contradictory)
    )

    legacy_unknown = copy.deepcopy(valid)
    legacy_unknown["subject"]["actor_selection"] = "explicit_actor"
    assert "actor_attribution_state" not in legacy_unknown["subject"]
    assert _jsonschema_errors("alignment-v1", legacy_unknown) == []
    assert _stdlib_alignment_subject_errors(legacy_unknown) == []

    provider_handle = copy.deepcopy(valid)
    provider_handle["subject"]["actor_canonical_id"] = "github:Alice"
    assert _jsonschema_errors("alignment-v1", provider_handle)
    assert any(
        "actor_canonical_id" in error for error in _stdlib_alignment_subject_errors(provider_handle)
    )


def test_runtime_cross_field_invariants_reject_mutations_json_schema_cannot_express() -> None:
    samples = _base_instances()
    report = copy.deepcopy(samples["report-v2"])
    report["attribution"]["attribution_coverage"]["sample_size"] = 3
    assert any("attributed + unresolved" in error for error in validate_schema("report-v2", report))
    assert _jsonschema_errors("report-v2", report) == []

    index = copy.deepcopy(samples["actor-index-v1"])
    index["selection"]["selected_count"] = 0
    assert validate_schema("actor-index-v1", index)
    assert _jsonschema_errors("actor-index-v1", index) == []

    index = copy.deepcopy(samples["actor-index-v1"])
    index["actors"][0]["commit_count"] = 3
    assert any(
        "nonmerge_commit_count" in error for error in validate_schema("actor-index-v1", index)
    )

    alignment = copy.deepcopy(samples["alignment-v1"])
    alignment["axes"][0]["actor_n"] = 3
    assert any("actor_denominator" in error for error in validate_schema("alignment-v1", alignment))

    portfolio = copy.deepcopy(samples["portfolio-v1"])
    portfolio["summary"]["disclosure"]["value"] = 0.5
    assert any(
        "numerator / denominator" in error for error in validate_schema("portfolio-v1", portfolio)
    )
    assert _jsonschema_errors("portfolio-v1", portfolio) == []

    summary = copy.deepcopy(samples["scenario-summary-v1"])
    summary["counts"]["total"] = 2
    assert validate_schema("scenario-summary-v1", summary)
    assert _jsonschema_errors("scenario-summary-v1", summary) == []


def test_portfolio_attested_binding_schema_requires_trust_verified_subject_evidence() -> None:
    samples = _base_instances()
    portfolio = copy.deepcopy(samples["portfolio-v1"])
    portfolio["subject_binding"]["method"] = "attested"
    entry = portfolio["entries"][0]
    entry["subject_binding"]["method"] = "attested"
    attestation = entry["evidence"]["attestation"]
    attestation["signature_verification"] = "recipient_trust_verified"
    attestation["bound_subject_id"] = "alice"

    assert validate_schema("portfolio-v1", portfolio) == []
    assert _jsonschema_errors("portfolio-v1", portfolio) == []

    missing_subject = copy.deepcopy(portfolio)
    missing_subject["entries"][0]["evidence"]["attestation"].pop("bound_subject_id")
    assert validate_schema("portfolio-v1", missing_subject)
    assert _jsonschema_errors("portfolio-v1", missing_subject)

    false_verification = copy.deepcopy(portfolio)
    false_verification["entries"][0]["evidence"]["attestation"]["signature_verification"] = (
        "not_verified_self_declared"
    )
    assert validate_schema("portfolio-v1", false_verification)
    assert _jsonschema_errors("portfolio-v1", false_verification)

    self_declared = copy.deepcopy(samples["portfolio-v1"])
    self_declared["entries"][0]["evidence"]["attestation"]["bound_subject_id"] = "alice"
    assert validate_schema("portfolio-v1", self_declared)
    assert _jsonschema_errors("portfolio-v1", self_declared)


def test_portfolio_manifest_rejects_mixed_subject_binding_methods() -> None:
    manifest = copy.deepcopy(_base_instances()["portfolio-manifest-v1"])
    manifest["subject_binding"] = "attested"

    errors = validate_schema("portfolio-manifest-v1", manifest)

    assert any("subject_binding" in error for error in errors)


def test_report_actor_partition_is_closed_and_provider_enrichment_invariant() -> None:
    report = copy.deepcopy(_base_instances()["report-v2"])
    report["attribution"]["actor_partition"]["provider_enrichment_changes_partition"] = True
    assert validate_schema("report-v2", report)
    assert _jsonschema_errors("report-v2", report)

    report = copy.deepcopy(_base_instances()["report-v2"])
    report["attribution"]["actor_partition"]["unexpected"] = True
    assert validate_schema("report-v2", report)
    assert _jsonschema_errors("report-v2", report)


def test_oid_window_binding_and_revision_invariants_fail_closed() -> None:
    samples = _base_instances()
    forge = copy.deepcopy(samples["forge-export-v2"])
    forge["events"][0]["commit_sha"] = HEX64
    assert any("target OID" in error for error in validate_schema("forge-export-v2", forge))

    tracker = copy.deepcopy(samples["tracker-export-v2"])
    tracker["events"][0]["timestamp"] = tracker["binding"]["window"]["end"]
    assert any(
        "outside binding window" in error for error in validate_schema("tracker-export-v2", tracker)
    )

    report = copy.deepcopy(samples["report-v2"])
    report["provenance"]["revision_completeness"] = {
        "shallow": True,
        "promisor": False,
        "complete": True,
    }
    assert any("not complete" in error for error in validate_schema("report-v2", report))


def test_identity_digest_reuse_across_actors_is_rejected() -> None:
    payload = copy.deepcopy(_base_instances()["identity-v2"])
    payload["actors"].append(
        {"canonical_id": "bob", "attribution_state": "verified", "email_sha256": [HEX64]}
    )
    assert any("already owned" in error for error in validate_schema("identity-v2", payload))


def test_identity_consent_and_authority_match_stdlib_and_draft202012() -> None:
    payload = copy.deepcopy(_base_instances()["identity-v2"])
    actor = payload["actors"][0]
    actor["consent"] = "recorded-explicit-consent"
    actor["authority"] = "subject-authorization"
    assert validate_schema("identity-v2", payload) == []
    assert _jsonschema_errors("identity-v2", payload) == []

    authority_only = copy.deepcopy(_base_instances()["identity-v2"])
    authority_only["actors"][0]["authority"] = "repository-owner-authorization"
    assert validate_schema("identity-v2", authority_only) == []
    assert _jsonschema_errors("identity-v2", authority_only) == []

    for field, value in (
        ("consent", "assumed"),
        ("authority", "github-login"),
    ):
        invalid = copy.deepcopy(_base_instances()["identity-v2"])
        invalid["actors"][0][field] = value
        assert validate_schema("identity-v2", invalid)
        assert _jsonschema_errors("identity-v2", invalid)

    incoherent = copy.deepcopy(payload)
    incoherent["actors"][0]["attribution_state"] = "inferred"
    assert validate_schema("identity-v2", incoherent)
    assert _jsonschema_errors("identity-v2", incoherent)


def test_contribution_four_profiles_and_public_door_boundaries() -> None:
    aggregate = _base_instances()["contribution-v2"]
    assert validate_schema("contribution-v2", aggregate) == []

    named = _contribution_base("named-public", "public-pr")
    named["data"] = {
        "project": {
            "provider": "github",
            "host": "github.example.test",
            "project_id": "42",
            "project_path": "group/demo",
        },
        "authority": {
            "accounts": [
                {
                    "provider": "github",
                    "host": "github.example.test",
                    "project_id": "42",
                    "account_id": "42",
                    "basis": "account_holder_explicit",
                    "scope": "project_and_account",
                    "assertion": "authorized_for_public_research_contribution",
                }
            ]
        },
        "actors": [
            {
                "account": {
                    **_contribution_account(),
                    "provider": "github",
                    "host": "github.example.test",
                    "profile_url": "https://github.example.test/alice",
                },
                "measurements": {
                    "linked_commit_count_bucket": "5-19",
                    "actor_commit_count_bucket": "20-99",
                    "linkage_coverage_bucket": "10-20%",
                    "commit_count_basis": "git_primary_author_cluster_including_merges",
                },
            }
        ],
        "measurements": {},
        "coverage": _coverage(),
        "missingness": [],
    }
    assert validate_schema("contribution-v2", named) == []

    masked = _masked_contribution()
    assert validate_schema("contribution-v2", masked) == []

    raw = _contribution_base("raw", "controlled")
    raw["data"] = {"raw_material": {"names": ["Alice"]}, "research": {"study_id": "study-1"}}
    assert validate_schema("contribution-v2", raw) == []

    masked["door"] = "public-pr"
    assert validate_schema("contribution-v2", masked)


def test_masked_precise_tree_accepts_year_but_rejects_arbitrary_numeric_and_identity_keys() -> None:
    masked = _masked_contribution()
    calendar_year = {"2024": {"kind": "observed", "n": 20, "share": 1.0}}
    masked["data"]["measurements"] = {
        "role_profile": {
            "dimensions": {"time": {"calendar_year": calendar_year}},
        }
    }
    assert validate_schema("contribution-v2", masked) == []
    assert _jsonschema_errors("contribution-v2", masked) == []

    arbitrary_numeric = copy.deepcopy(masked)
    arbitrary_numeric["data"]["measurements"]["role_profile"]["dimensions"]["time"][
        "calendar_year"
    ] = {"42": {"kind": "observed", "n": 20, "share": 1.0}}
    assert validate_schema("contribution-v2", arbitrary_numeric)
    assert _jsonschema_errors("contribution-v2", arbitrary_numeric)

    identifying = copy.deepcopy(masked)
    identifying["data"]["measurements"]["role_profile"]["actor_id"] = "actor_private"
    assert any(
        "identifying key" in error for error in validate_schema("contribution-v2", identifying)
    )


def test_report_v1_remains_additive_and_separate_from_strict_contracts() -> None:
    assert (
        validate_report(
            {"schema_version": "report-v1", "future_additive_section": {"any": "value"}},
            subset=True,
        )
        == []
    )
