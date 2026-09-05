"""Falsification tests for the v0.6 contribution privacy profiles."""

from __future__ import annotations

import json
import hashlib
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

import tep_core.contribution_v2 as contribution_v2_module
from tep_core.contribute import build_contribution, validate_contribution_payload
from tep_core.contribution_v2 import (
    build_contribution_bundle,
    public_payload_leaks,
    validate_controlled_bundle,
)


def _report() -> dict:
    oid = {"algorithm": "sha1", "value": "a" * 40}
    partition_digest = {"algorithm": "sha256", "value": "b" * 64}
    window = {"start": "2026-01-01T00:00:00Z", "end": "2026-08-31T00:00:00Z"}
    attribution = {
        "observed_actor_count": 2,
        "attributed_commit_count": 137,
        "attribution_human_including_merges": 137,
        "repo_human_nonmerge_commits": 125,
        "unresolved_commit_count": 0,
        "attribution_unresolved_commit_count": 0,
        "attribution_coverage": {
            "kind": "observed",
            "value": 1.0,
            "unit": "ratio",
            "sample_size": 137,
        },
        "bot_count": 0,
        "merge_count": 12,
        "coauthored_count": 0,
        "mailmap_present": False,
        "human_commit_count": 125,
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
            "repo_scope_digest": "c" * 64,
            "object_format": "sha1",
            "partition_digest": "b" * 64,
            "sha_to_actor_digest": "d" * 64,
            "provider_enrichment_changes_partition": False,
        },
        "public_join": {
            "matched": 7,
            "unmatched": 130,
            "ambiguous": 0,
            "public_handle_actors": 1,
            "fetched_login_count": None,
            "commit_login_count": 1,
            "account_conflict_count": 0,
            "count_note": "commit-linked account population",
        },
    }
    population = {
        "actor_count": 2,
        "human_commit_count": 137,
        "nonmerge_commit_count": 125,
        "merge_commit_count": 12,
        "basis": "git_primary_author_cluster",
        "partition_digest": partition_digest,
    }
    encoded_population = json.dumps(
        population,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    population["population_digest"] = {
        "algorithm": "sha256",
        "value": hashlib.sha256(b"tep-population-v1\0" + encoded_population).hexdigest(),
    }
    report = {
        "schema_version": "report-v2",
        "report_kind": "evidence",
        "subject": {"kind": "repo", "selection": "repo_all_human"},
        "target": {"oid": deepcopy(oid)},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "analysis_scope": "repo",
            "analyzed_at": "2026-08-31T01:02:03Z",
            "analyzed_commit_sha": "a" * 40,
            "observation_date": "2026-08-31",
            "definition_version": "tep-v0.6.0",
            "input_digests": {"git": "e" * 64, "tagset": "f" * 64},
            "tagset_digest": "f" * 64,
            "target_oid": deepcopy(oid),
            "revision_completeness": {"shallow": False, "promisor": False, "complete": True},
        },
        "repository": {
            "name": "private",
            "remote": "https://person:credential@gitlab.example/acme/private.git",
            "path": "/Users/person/Developer/private",
        },
        "identity": {"pending_attribution": False, "actor_count": 2},
        "population": population,
        "activity": {
            "repo_human_nonmerge_commits": {
                "kind": "observed",
                "unit": "commits",
                "value": 125,
                "sample_size": 125,
            },
            "tenant_commits": None,
            "active_days": {"kind": "observed", "unit": "days", "value": 70},
            "commits_per_active_day": {"kind": "observed", "unit": "commits", "value": 1.8},
            "commits_per_active_day_median": {
                "kind": "observed",
                "unit": "commits",
                "value": 1.0,
            },
            "active_days_13w": {"kind": "observed", "unit": "days", "value": 20},
        },
        "attribution": attribution,
        "surface_profile": {
            "kind": "observed",
            "unit": "commits",
            "value": 115,
            "sample_size": 125,
            "classification_basis": "path_pattern_and_extension_heuristic",
        },
        "input_coverage": {
            "git": {"kind": "observed", "provided": True},
            "forge": {"kind": "not_observed", "reason": "forge_export_not_provided"},
        },
        "actor_directory": {
            "observed_count": 2,
            "actors": [
                {
                    "actor_id": "actor_alice",
                    "display_name": "alice",
                    "display_status": "public_handle",
                    "commit_count": 101,
                    "commit_count_includes_merges": True,
                    "commit_count_nonmerge": 90,
                    "public_account_status": "linked",
                    "public_accounts": [
                        {
                            "provider": "github",
                            "host": "github.example",
                            "account_id": "42",
                            "handle": "alice",
                            "profile_url": "https://github.example/alice",
                            "evidence": {
                                "basis": "commit.author.id",
                                "account_match_status": "linked",
                            },
                        }
                    ],
                },
                {
                    "actor_id": "actor_bob",
                    "display_name": "actor_bob",
                    "display_status": "stable_hash",
                    "commit_count": 36,
                    "commit_count_includes_merges": True,
                    "commit_count_nonmerge": 35,
                    "public_account_status": "unlinked",
                    "public_accounts": [],
                },
            ],
            "attribution": deepcopy(attribution),
        },
        "window": window,
        "metrics": {},
        "limitations": ["Evidence, not a verdict."],
        "notices": ["Observation only."],
    }
    return report


def _governance() -> dict[str, str]:
    return {
        "controller": "research-controller-1",
        "authority": "repository-owner-authorization",
        "consent": "recorded-explicit-consent",
        "study_id": "study-2026-01",
        "key_id": "key-2026-01",
        "epoch": "2026-01",
        "retention": "until-2027-08-31",
        "withdrawal": "contact-controller-before-publication",
        "access_class": "named-research-team",
    }


def _public_authority(
    *,
    provider: str = "github",
    host: str = "github.example",
    project_id: str = "7",
    account_id: str = "42",
) -> dict[str, list[dict[str, str]]]:
    return {
        "accounts": [
            {
                "provider": provider,
                "host": host,
                "project_id": project_id,
                "account_id": account_id,
                "basis": "account_holder_explicit",
                "scope": "project_and_account",
                "assertion": "authorized_for_public_research_contribution",
            }
        ]
    }


def _key_file(tmp_path: Path, *, mode: int = 0o600) -> Path:
    path = tmp_path / "study.key"
    path.write_bytes(bytes(range(32)))
    path.chmod(mode)
    return path


def _nested_percent_encode(value: str, passes: int) -> str:
    if passes == 0:
        return value
    result = "".join(f"%{byte:02X}" for byte in value.encode("utf-8"))
    for _ in range(1, passes):
        result = quote(result, safe="")
    return result


def test_aggregate_public_payload_has_no_source_fingerprint() -> None:
    payload = build_contribution(
        _report(),
        privacy="aggregate",
        door="public-pr",
        receipt_id="receipt_" + "a" * 26,
    )
    assert payload["privacy_profile"] == "aggregate"
    assert payload["data"]["population"] == {
        "n": 2,
        "denominator": 137,
    }
    blob = json.dumps(payload, ensure_ascii=False)
    for needle in (
        "alice@example.com",
        "gitlab.example",
        "acme/private",
        "scope-secret",
        "2026-08-31T01:02:03Z",
        "actor_internal",
        "a" * 40,
    ):
        assert needle not in blob
    assert public_payload_leaks(payload) == []
    assert validate_contribution_payload(payload) == []


@pytest.mark.parametrize(
    "invalid_population",
    [
        {"n_bucket": "1-4", "denominator_bucket": "100-499"},
        {"n": True, "denominator": 137},
        {"n": 2, "denominator": -1},
        {"n": 2, "denominator": 137.0},
        {"n": 138, "denominator": 137},
        {"n": 2, "denominator": 137, "basis": "unregistered"},
    ],
)
def test_aggregate_population_rejects_legacy_noninteger_negative_and_extra_fields(
    invalid_population: dict[str, object],
) -> None:
    payload = build_contribution(
        _report(),
        privacy="aggregate",
        door="public-pr",
        receipt_id="receipt_" + "z" * 26,
    )
    payload["data"]["population"] = invalid_population

    assert validate_contribution_payload(payload)


@pytest.mark.parametrize("door", ["local", "public-pr"])
def test_contribution_rejects_non_schema_report_before_transform(door: str) -> None:
    codename = "PRIVATE-REPO-CODENAME-ALPHA"
    report = deepcopy(_report())
    report["surface_profile"].update(
        {
            "classification_basis": codename,
            "denominator_definition": codename,
            "reason": codename,
            "private_repo_codename_alpha": {
                "value": 7,
                "notes": [{"classification_basis": codename}],
            },
            "surface_commit_counts": {
                "kind": "observed",
                "unit": "commits",
                "values": {"backend": 5, "private_repo_codename_alpha": 2},
            },
        }
    )
    report["input_coverage"]["private_repo_codename_alpha"] = {
        "kind": "not_observed",
        "reason": codename,
    }

    with pytest.raises(ValueError, match="schema-valid report-v2"):
        build_contribution(
            report,
            privacy="aggregate",
            door=door,
            receipt_id="receipt_" + "f" * 26,
        )


def test_public_aggregate_validator_rejects_reintroduced_free_form_text() -> None:
    codename = "PRIVATE-REPO-CODENAME-ALPHA"
    payload = build_contribution(
        _report(),
        privacy="aggregate",
        door="public-pr",
        receipt_id="receipt_" + "g" * 26,
    )
    payload["data"]["measurements"]["surface_profile"]["classification_basis"] = codename
    violations = validate_contribution_payload(payload)
    assert any("unregistered measurement text" in item for item in violations)


def test_report_v2_library_default_is_public_safe_aggregate() -> None:
    payload = build_contribution(_report())
    assert payload["privacy_profile"] == "aggregate"
    assert payload["door"] == "local"
    blob = json.dumps(payload, ensure_ascii=False)
    for needle in ("alice@example.com", "gitlab.example", "actor_internal", "a" * 40):
        assert needle not in blob


def test_named_public_accepts_documented_github_linkage_and_requires_authority() -> None:
    project = {
        "provider": "github",
        "host": "github.example",
        "project_id": "R_kgDO7",
        "project_path": "acme/public",
    }
    authority = _public_authority(project_id="R_kgDO7")
    payload = build_contribution(
        _report(),
        privacy="named-public",
        door="public-pr",
        public_project=project,
        public_authority=authority,
        receipt_id="receipt_" + "b" * 26,
    )
    assert payload["data"]["project"] == project
    assert payload["data"]["actors"][0]["account"]["account_id"] == "42"
    assert len(payload["data"]["actors"]) == 1
    actor = payload["data"]["actors"][0]
    assert actor["account"]["evidence"]["coverage_status"] == "partial"
    assert actor["measurements"] == {
        "linked_commit_count_bucket": "5-19",
        "actor_commit_count_bucket": "100-499",
        "linkage_coverage_bucket": "00-10%",
        "commit_count_basis": "git_primary_author_cluster_including_merges",
    }
    text = json.dumps(payload)
    assert "actor_internal_alice" not in text
    assert "alice@example.com" not in text
    assert validate_contribution_payload(payload) == []

    with pytest.raises(ValueError, match="authority"):
        build_contribution(
            _report(),
            privacy="named-public",
            door="public-pr",
            public_project=project,
        )


def test_named_public_rejects_gitlab_account_linkage_as_unsupported() -> None:
    report = deepcopy(_report())
    account = report["actor_directory"]["actors"][0]["public_accounts"][0]
    account.update(
        {
            "provider": "gitlab",
            "host": "gitlab.example",
            "profile_url": "https://gitlab.example/alice",
            "evidence": {
                "basis": "provider_commit_account",
                "account_match_status": "linked",
            },
        }
    )
    with pytest.raises(ValueError, match="unsupported"):
        build_contribution_bundle(
            report,
            privacy="named-public",
            door="public-pr",
            public_project={
                "provider": "gitlab",
                "host": "gitlab.example",
                "project_id": "7",
                "project_path": "acme/public",
            },
            public_authority=_public_authority(
                provider="gitlab", host="gitlab.example", project_id="7"
            ),
        )


def test_masked_uses_secret_hmac_and_writes_separate_sidecar(tmp_path: Path) -> None:
    key = _key_file(tmp_path)
    sidecar = tmp_path / "controlled" / "sidecar.json"
    first = build_contribution(
        _report(),
        privacy="masked",
        door="controlled",
        key_file=key,
        controlled_context=_governance(),
        controlled_sidecar=sidecar,
        receipt_id="receipt_" + "c" * 26,
    )
    second = build_contribution_bundle(
        _report(),
        privacy="masked",
        door="controlled",
        key_file=key,
        controlled_context=_governance(),
        receipt_id="receipt_" + "d" * 26,
    )
    first_pids = [row["actor_pid"] for row in first["data"]["actors"]]
    second_pids = [row["actor_pid"] for row in second.payload["data"]["actors"]]
    assert first_pids == second_pids
    assert all(item.startswith("pa_") and len(item) == 29 for item in first_pids)
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["privacy_profile"] == "masked"
    assert saved["source"]["report_sha256"]
    assert saved["governance"]["study_id"] == "study-2026-01"
    correspondence = saved["source"]["actor_correspondence"]
    assert {row["actor_pid"] for row in correspondence} == set(first_pids)
    assert {(row["source_actor_field"], row["source_actor_id"]) for row in correspondence} == {
        ("actor_id", "actor_alice"),
        ("actor_id", "actor_bob"),
    }
    assert "credential" not in saved["source"]["repository"]["remote"]
    assert stat_mode(sidecar) & 0o077 == 0
    combined = json.dumps(first) + json.dumps(saved)
    assert bytes(range(32)).hex() not in combined
    assert "alice@example.com" not in json.dumps(first)
    assert first["data"]["population"] == {
        "n": 2,
        "denominator": 137,
        "basis": "git_primary_author_cluster",
    }
    assert first["data"]["actors"][0]["measurements"]["n"] in {36, 101}
    assert "commit_count_bucket" not in json.dumps(first["data"]["actors"])
    assert first["data"]["measurements"]["activity"]["active_days"]["value"] == 70
    assert validate_controlled_bundle(first, saved, report=_report(), key_file=key) == []


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def test_masked_key_and_public_door_fail_closed(tmp_path: Path) -> None:
    loose = _key_file(tmp_path, mode=0o644)
    with pytest.raises(ValueError, match="permissions"):
        build_contribution_bundle(
            _report(),
            privacy="masked",
            door="controlled",
            key_file=loose,
            controlled_context=_governance(),
        )
    secure = _key_file(tmp_path, mode=0o600)
    with pytest.raises(ValueError, match="cannot use"):
        build_contribution_bundle(
            _report(),
            privacy="masked",
            door="public-pr",
            key_file=secure,
            controlled_context=_governance(),
        )


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o700])
def test_masked_key_file_rejects_group_other_or_execute_modes(tmp_path: Path, mode: int) -> None:
    key = _key_file(tmp_path, mode=mode)

    with pytest.raises(ValueError, match="0400 or 0600"):
        contribution_v2_module._read_key_file(key)


@pytest.mark.parametrize("mode", [0o400, 0o600])
def test_masked_key_file_accepts_owner_read_only_modes(tmp_path: Path, mode: int) -> None:
    key = _key_file(tmp_path, mode=mode)

    assert contribution_v2_module._read_key_file(key) == bytes(range(32))


def test_masked_key_file_rejects_symlink_hardlink_and_oversize(tmp_path: Path) -> None:
    key = _key_file(tmp_path)
    symlink = tmp_path / "symlink.key"
    symlink.symlink_to(key)
    with pytest.raises(ValueError, match="unreadable"):
        contribution_v2_module._read_key_file(symlink)

    hardlink = tmp_path / "hardlink.key"
    os.link(key, hardlink)
    with pytest.raises(ValueError, match="exactly one link"):
        contribution_v2_module._read_key_file(key)
    hardlink.unlink()

    key.write_bytes(b"x" * 4097)
    key.chmod(0o600)
    with pytest.raises(ValueError, match="too large"):
        contribution_v2_module._read_key_file(key)


def test_masked_key_file_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "study.fifo"
    os.mkfifo(fifo, 0o600)

    with pytest.raises(ValueError, match="must be regular"):
        contribution_v2_module._read_key_file(fifo)


def test_masked_key_file_reads_from_opened_descriptor_after_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key_file(tmp_path)
    expected = key.read_bytes()
    replacement = tmp_path / "replacement.key"
    replacement.write_bytes(b"z" * 32)
    replacement.chmod(0o600)
    opened_inode = tmp_path / "opened-inode.key"
    real_open = os.open

    def open_then_swap(path: str, flags: int) -> int:
        fd = real_open(path, flags)
        key.rename(opened_inode)
        key.symlink_to(replacement)
        return fd

    monkeypatch.setattr(contribution_v2_module.os, "open", open_then_swap)

    assert contribution_v2_module._read_key_file(key) == expected


def test_masked_key_file_rejects_foreign_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key_file(tmp_path)
    real_fstat = os.fstat

    def foreign_owner(fd: int) -> SimpleNamespace:
        info = real_fstat(fd)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_uid=os.getuid() + 1,
            st_nlink=info.st_nlink,
            st_size=info.st_size,
        )

    monkeypatch.setattr(contribution_v2_module.os, "fstat", foreign_owner)

    with pytest.raises(ValueError, match="owned by the current user"):
        contribution_v2_module._read_key_file(key)


def test_masked_key_fd_is_supported_without_serializing_key(tmp_path: Path) -> None:
    key = _key_file(tmp_path)
    descriptor = os.open(key, os.O_RDONLY)
    try:
        bundle = build_contribution_bundle(
            _report(),
            privacy="masked",
            door="controlled",
            key_fd=descriptor,
            controlled_context=_governance(),
        )
    finally:
        os.close(descriptor)
    assert bundle.payload["data"]["actors"]
    assert "key_material" not in json.dumps(bundle.payload)


@pytest.mark.parametrize("mode", [0o500, 0o640, 0o700])
def test_masked_regular_key_fd_rejects_noncanonical_modes(tmp_path: Path, mode: int) -> None:
    key = _key_file(tmp_path, mode=mode)
    descriptor = os.open(key, os.O_RDONLY)
    try:
        with pytest.raises(ValueError, match="0400 or 0600"):
            contribution_v2_module._read_key_fd(descriptor)
    finally:
        os.close(descriptor)


def test_masked_regular_key_fd_rejects_hardlink_and_foreign_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key_file(tmp_path)
    hardlink = tmp_path / "hardlink.key"
    os.link(key, hardlink)
    descriptor = os.open(key, os.O_RDONLY)
    try:
        with pytest.raises(ValueError, match="exactly one link"):
            contribution_v2_module._read_key_fd(descriptor)
    finally:
        os.close(descriptor)
    hardlink.unlink()

    descriptor = os.open(key, os.O_RDONLY)
    real_fstat = os.fstat

    def foreign_owner(fd: int) -> SimpleNamespace:
        info = real_fstat(fd)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_uid=os.getuid() + 1,
            st_nlink=info.st_nlink,
            st_size=info.st_size,
        )

    monkeypatch.setattr(contribution_v2_module.os, "fstat", foreign_owner)
    try:
        with pytest.raises(ValueError, match="owned by the current user"):
            contribution_v2_module._read_key_fd(descriptor)
    finally:
        os.close(descriptor)


def test_masked_key_fd_rejects_nonregular_pipe() -> None:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, bytes(range(32)))
        with pytest.raises(ValueError, match="must be regular"):
            contribution_v2_module._read_key_fd(read_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_masked_repo_scope_is_stable_and_cross_repo_linkage_requires_manifest(
    tmp_path: Path,
) -> None:
    key = _key_file(tmp_path)
    first = build_contribution_bundle(
        _report(),
        privacy="masked",
        door="controlled",
        key_file=key,
        controlled_context=_governance(),
    )
    drifted = deepcopy(_report())
    drifted["provenance"]["observation_date"] = "2026-09-01"
    drifted["actor_directory"]["actors"][0]["public_accounts"][0]["handle"] = "renamed"
    second = build_contribution_bundle(
        drifted,
        privacy="masked",
        door="controlled",
        key_file=key,
        controlled_context=_governance(),
    )
    assert [row["actor_pid"] for row in first.payload["data"]["actors"]] == [
        row["actor_pid"] for row in second.payload["data"]["actors"]
    ]

    with pytest.raises(ValueError, match="study manifest"):
        build_contribution(
            _report(),
            privacy="masked",
            door="controlled",
            key_file=key,
            controlled_context=_governance(),
            controlled_sidecar=tmp_path / "sidecar.json",
            repo_subject_id="study-subject-7",
        )


@pytest.mark.parametrize(
    "profile_url",
    [
        "https://github.example:8443/alice",
        "https://github.example/alice?access_token=do-not-leak",
        "https://github.example/alice?opaque=do-not-leak",
        "https://github.example/alice#private-fragment",
        "https://person@github.example/alice",
        "https://github.example/acme/../alice",
        "https://github.example/%2e%2e/alice",
        "https://github.example//alice",
        "https://github.example/not-alice",
        "https://github.example/alice/",
        "https://github.example/users/alice",
        "https://github.example/users;opaque=PRIVATECANARY/alice",
        "https://github.example/@PRIVATECANARY/alice",
        "https://github.example/users:PRIVATECANARY/alice",
        "https://github.example/users\u200bPRIVATECANARY/alice",
    ],
)
def test_named_public_rejects_noncanonical_account_url(
    profile_url: str,
) -> None:
    report = deepcopy(_report())
    report["actor_directory"]["actors"][0]["public_accounts"][0]["profile_url"] = profile_url
    with pytest.raises(ValueError, match="named-public"):
        build_contribution_bundle(
            report,
            privacy="named-public",
            door="public-pr",
            public_project={
                "provider": "github",
                "host": "github.example",
                "project_id": "7",
                "project_path": "acme/public",
            },
            public_authority=_public_authority(),
        )


@pytest.mark.parametrize(
    ("field", "value", "profile_url"),
    [
        ("handle", "canary@example.test", "https://github.example/canary@example.test"),
        ("account_id", "canary@example.test", "https://github.example/alice"),
        ("host", "github.example:", "https://github.example:/alice"),
        ("host", "github..example", "https://github..example/alice"),
        ("host", "-github.example", "https://-github.example/alice"),
        ("host", "github_.example", "https://github_.example/alice"),
        ("host", "github.example:0443", "https://github.example:0443/alice"),
        ("host", "github.example:443", "https://github.example:443/alice"),
    ],
)
def test_named_public_rejects_free_form_account_identifiers_before_build(
    field: str,
    value: str,
    profile_url: str,
) -> None:
    report = deepcopy(_report())
    account = report["actor_directory"]["actors"][0]["public_accounts"][0]
    account[field] = value
    account["profile_url"] = profile_url
    with pytest.raises(ValueError, match="named-public"):
        build_contribution_bundle(
            report,
            privacy="named-public",
            door="public-pr",
            public_project={
                "provider": "github",
                "host": "github.example",
                "project_id": "7",
                "project_path": "acme/public",
            },
            public_authority=_public_authority(),
        )


@pytest.mark.parametrize(
    ("host", "profile_url"),
    [
        ("github.example:8443", "https://github.example:8443/alice"),
        ("[2001:db8::1]:8443", "https://[2001:db8::1]:8443/alice"),
    ],
)
def test_named_public_accepts_exact_canonical_self_managed_host(
    host: str,
    profile_url: str,
) -> None:
    report = deepcopy(_report())
    account = report["actor_directory"]["actors"][0]["public_accounts"][0]
    account["host"] = host
    account["profile_url"] = profile_url
    payload = build_contribution_bundle(
        report,
        privacy="named-public",
        door="public-pr",
        public_project={
            "provider": "github",
            "host": host,
            "project_id": "7",
            "project_path": "acme/public",
        },
        public_authority=_public_authority(host=host),
    ).payload
    assert payload["data"]["actors"][0]["account"]["host"] == host
    assert payload["data"]["actors"][0]["account"]["profile_url"] == profile_url


def test_named_public_validator_rejects_tampered_account_url() -> None:
    payload = build_contribution(
        _report(),
        privacy="named-public",
        door="public-pr",
        public_project={
            "provider": "github",
            "host": "github.example",
            "project_id": "7",
            "project_path": "acme/public",
        },
        public_authority=_public_authority(),
    )
    payload["data"]["actors"][0]["account"]["profile_url"] += "?opaque=do-not-leak"
    assert any("not canonical" in violation for violation in validate_contribution_payload(payload))


def test_raw_is_controlled_and_rejects_key_material(tmp_path: Path) -> None:
    raw = {
        "mailmap": {"before": "Alias <alias@example.com>", "after": "Alice <alice@example.com>"},
        "object_ids": [{"algorithm": "sha1", "value": "a" * 40}],
        "provider_manifest": {"coverage": "complete"},
    }
    with pytest.raises(ValueError, match="cannot use"):
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="public-pr",
            controlled_context=_governance(),
            raw_material=raw,
        )
    with pytest.raises(ValueError, match="secret field"):
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={"token": "do-not-store"},
        )
    sidecar = tmp_path / "raw-sidecar.json"
    payload = build_contribution(
        _report(),
        privacy="raw",
        door="controlled",
        controlled_context=_governance(),
        controlled_sidecar=sidecar,
        raw_material=raw,
    )
    assert "alias@example.com" in json.dumps(payload)
    assert sidecar.is_file()


@pytest.mark.parametrize(
    "field",
    [
        "access_token",
        "access-token",
        "accessToken",
        "accesstoken",
        "accesstokenid",
        "ACCESS TOKEN",
        "private_token",
        "api_secret",
        "apisecret",
        "apisecretvalue",
        "client.secret",
        "clientsecretvalue",
        "auth",
        "authToken",
        "authtoken",
        "authtokenvalue",
        "authentication",
        "authcode",
        "bearer",
        "jwt",
        "oauth",
        "oauth2",
        "pat",
        "patvalue",
        "passphrase",
        "password",
        "passwordhash",
        "pwd",
        "Authorization",
        "authorizationheader",
        "Cookie",
        "cookievalue",
        "Set-Cookie",
        "Credential",
        "credentialvalue",
        "APIKey",
        "privateKey",
        "session_id",
        "secretvalue",
        "tokenvalue",
        "x-api-key",
        "xapikey",
    ],
)
def test_raw_rejects_nested_credential_key_variants_without_logging(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
) -> None:
    credential = "CREDENTIAL-VALUE-DO-NOT-LEAK"
    sidecar = tmp_path / "controlled-sidecar.json"
    with pytest.raises(ValueError, match="secret field") as raised:
        build_contribution(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            controlled_sidecar=sidecar,
            raw_material={"outer": [{"inner": {field: credential}}]},
        )
    captured = capsys.readouterr()
    assert credential not in str(raised.value)
    assert credential not in captured.out
    assert credential not in captured.err
    assert not sidecar.exists()


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://person:password@gitlab.example/acme/private.git",
        "https://gitlab.example/acme/private.git?opaque=do-not-leak",
        "https://gitlab.example/acme/private.git#private-fragment",
        "ssh://git:password@gitlab.example/acme/private.git",
        "git@gitlab.example:acme/private.git",
        "//person:password@gitlab.example/acme/private.git",
        "https://gitlab.example/access_token/do-not-leak",
        "clone command: https://person:password@gitlab.example/acme/private.git",
        "mirror=//person:password@gitlab.example/acme/private.git?opaque=do-not-leak",
    ],
)
def test_raw_rejects_nested_credential_url_surfaces_without_serializing(
    tmp_path: Path,
    unsafe_url: str,
) -> None:
    sidecar = tmp_path / "controlled-sidecar.json"
    with pytest.raises(ValueError, match="credential-bearing") as raised:
        build_contribution(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            controlled_sidecar=sidecar,
            raw_material={"outer": [{"source_url": unsafe_url}]},
        )
    assert unsafe_url not in str(raised.value)
    assert not sidecar.exists()


@pytest.mark.parametrize(
    "token_value",
    [
        "".join(("gh", "p_", "A" * 36)),
        "".join(("gl", "pat-", "A" * 24)),
        "eyJ" + "A" * 20 + "." + "B" * 20 + "." + "C" * 20,
        "AK" + "IA" + "A" * 16,
        "".join(("s", "k-proj-", "A" * 24)),
        "".join(("xo", "xb-", "A" * 24)),
        "Private-Token: " + "A" * 24,
        "Authorization: token " + "A" * 24,
        "Cookie: session=" + "A" * 24,
        'headers={"Private-Token":"SYNTHETIC_CANARY"}',
        'headers={"JOB-TOKEN":"SYNTHETIC_CANARY"}',
        'headers={"Deploy-Token":"SYNTHETIC_CANARY"}',
        'headers={"X-Gitlab-Token":"SYNTHETIC_CANARY"}',
        'headers={"X-Auth-Token":"SYNTHETIC_CANARY"}',
        'headers={"X-CSRF-Token":"SYNTHETIC_CANARY"}',
        "headers=[Private-Token: SYNTHETIC_CANARY]",
        "headers={Authorization: token SYNTHETIC_CANARY}",
        "authcode: SYNTHETIC_CANARY",
        "machine gitlab.example login researcher password SYNTHETIC_CANARY",
        "-----BEGIN PGP PRIVATE " + "KEY BLOCK-----",
    ],
)
def test_raw_rejects_high_confidence_token_values_under_benign_keys(
    token_value: str,
) -> None:
    with pytest.raises(ValueError, match="credential-bearing") as raised:
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={"provider_manifest": {"opaque_value": token_value}},
        )
    assert token_value not in str(raised.value)


def test_raw_keeps_noncredential_author_metadata_for_controlled_research() -> None:
    serialized = '{"author":"Alice","authorship":"human"}'
    safe_metadata = {
        "serialized_public_metadata": serialized,
        "authentication_method": "oauth2",
        "cookie_count": 0,
        "session_duration_seconds": 120,
    }
    bundle = build_contribution_bundle(
        _report(),
        privacy="raw",
        door="controlled",
        controlled_context=_governance(),
        raw_material={"provider_manifest": safe_metadata},
    )
    assert (
        bundle.payload["data"]["raw_material"]["provider_manifest"]["serialized_public_metadata"]
        == serialized
    )
    assert (
        bundle.payload["data"]["raw_material"]["provider_manifest"]["authentication_method"]
        == "oauth2"
    )
    assert bundle.controlled_sidecar is not None
    assert "raw_material" not in bundle.controlled_sidecar["source"]
    assert serialized not in json.dumps(bundle.controlled_sidecar)


@pytest.mark.parametrize(
    "safe_url",
    [
        "https://api.github.com/repos/acme/repo/commits?sha=" + "a" * 40 + "&per_page=100&page=2",
        "https://gitlab.example/api/v4/projects/acme%2Frepo/repository/commits"
        "?ref_name=main&per_page=100&page=2",
    ],
)
def test_raw_keeps_closed_provider_page_and_ref_queries(safe_url: str) -> None:
    bundle = build_contribution_bundle(
        _report(),
        privacy="raw",
        door="controlled",
        controlled_context=_governance(),
        raw_material={"provider_manifest": {"request_url": safe_url}},
    )

    assert bundle.payload["data"]["raw_material"]["provider_manifest"]["request_url"] == safe_url


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://api.github.com/repos/acme/repo/commits?token=SYNTHETICCANARY",
        "https://api.github.com/repos/acme/repo/commits?%74oken=SYNTHETICCANARY",
        "https://gitlab.example/api/v4/projects/7/repository/commits?access_token=SYNTHETICCANARY",
        "https://gitlab.example/api/v4/projects/7/repository/commits?signature=SYNTHETICCANARY",
        "https://gitlab.example/api/v4/projects/7/repository/commits"
        "?ref=https%3A%2F%2Fperson%40example.test%2Fprivate",
        "https://person@gitlab.example/api/v4/projects/7/repository/commits?page=2",
    ],
)
def test_raw_rejects_query_credentials_and_userinfo(unsafe_url: str) -> None:
    with pytest.raises(ValueError, match="credential-bearing") as raised:
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={"provider_manifest": {"request_url": unsafe_url}},
        )
    assert "SYNTHETICCANARY" not in str(raised.value)


def test_raw_percent_decode_accepts_pass_16_and_rejects_pass_17() -> None:
    safe_ref = "refs/heads/main"
    accepted_url = (
        "https://gitlab.example/api/v4/projects/7/repository/commits?ref="
        + _nested_percent_encode(safe_ref, 16)
    )
    bundle = build_contribution_bundle(
        _report(),
        privacy="raw",
        door="controlled",
        controlled_context=_governance(),
        raw_material={"provider_manifest": {"request_url": accepted_url}},
    )
    assert (
        bundle.payload["data"]["raw_material"]["provider_manifest"]["request_url"] == accepted_url
    )

    excessive_url = (
        "https://gitlab.example/api/v4/projects/7/repository/commits?ref="
        + _nested_percent_encode(safe_ref, 17)
    )
    with pytest.raises(ValueError, match="credential-bearing"):
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={"provider_manifest": {"request_url": excessive_url}},
        )


@pytest.mark.parametrize("passes", [1, 3, 16])
def test_raw_rejects_nested_percent_encoded_query_credential(passes: int) -> None:
    credential_url = "https://person:password@gitlab.example/acme/private.git"
    request_url = (
        "https://gitlab.example/api/v4/projects/7/repository/commits?ref="
        + _nested_percent_encode(credential_url, passes)
    )

    with pytest.raises(ValueError, match="credential-bearing") as raised:
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={"provider_manifest": {"request_url": request_url}},
        )
    assert "password" not in str(raised.value)


@pytest.mark.parametrize("passes", range(18))
@pytest.mark.parametrize(
    ("template", "raw_value", "safe"),
    [
        ("{value}", "ordinary observation", True),
        ("{value}", "Bearer syntheticcredentialvalue1234567890", False),
        ("https://gitlab.example{value}", "/api/v4/projects/7/repository/commits", True),
        ("https://gitlab.example{value}", "/api/v4/token", False),
        ("https://gitlab.example/api?{value}=main", "ref", True),
        ("https://gitlab.example/api?{value}=main", "token", False),
        ("https://gitlab.example/api?ref={value}", "refs/heads/main", True),
        (
            "https://gitlab.example/api?ref={value}",
            "https://person:synthetic@gitlab.example/acme/repo.git",
            False,
        ),
    ],
)
def test_raw_percent_decode_boundary_across_general_path_query_key_and_value(
    passes: int, template: str, raw_value: str, safe: bool
) -> None:
    candidate = template.format(value=_nested_percent_encode(raw_value, passes))
    expected_accept = safe and passes <= 16

    if expected_accept:
        bundle = build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={"observation": candidate},
        )
        assert bundle.payload["data"]["raw_material"]["observation"] == candidate
    else:
        with pytest.raises(ValueError, match="credential-bearing"):
            build_contribution_bundle(
                _report(),
                privacy="raw",
                door="controlled",
                controlled_context=_governance(),
                raw_material={"observation": candidate},
            )


@pytest.mark.parametrize("passes", range(18))
def test_raw_percent_decode_boundary_applies_to_mapping_keys(passes: int) -> None:
    safe_key = _nested_percent_encode("observation", passes)
    credential_key = _nested_percent_encode("token", passes)

    if passes <= 16:
        bundle = build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={safe_key: "synthetic-value"},
        )
        assert safe_key in bundle.payload["data"]["raw_material"]
    else:
        with pytest.raises(ValueError, match="secret field"):
            build_contribution_bundle(
                _report(),
                privacy="raw",
                door="controlled",
                controlled_context=_governance(),
                raw_material={safe_key: "synthetic-value"},
            )

    with pytest.raises(ValueError, match="secret field"):
        build_contribution_bundle(
            _report(),
            privacy="raw",
            door="controlled",
            controlled_context=_governance(),
            raw_material={credential_key: "synthetic-value"},
        )


def test_masked_precise_transform_retains_timeline_year_period_and_categories() -> None:
    source = {
        "experience": {
            "kind": "observed",
            "actor_id": "actor-private",
            "window": {"start": "2024-01-01", "end": "2026-01-01"},
            "metrics": {
                "language_domain_timeline": {
                    "kind": "observed",
                    "periods": [
                        {
                            "period": "2025",
                            "commit_n": 12,
                            "languages": {"values": {"python": {"n": 9, "share": 0.75}}},
                            "domains": {"values": {"core": {"n": 8, "share": 2 / 3}}},
                        }
                    ],
                }
            },
            "limitations": ["fixed OID observation"],
        },
        "role_profile": {
            "kind": "observed",
            "actor_id": "actor-private",
            "dimensions": {
                "time": {
                    "periods": [
                        {"period": "early", "n": 3},
                        {"period": "middle", "n": 4},
                        {"period": "recent", "n": 5},
                    ],
                    "calendar_years": {"2024": 2, "2025": 10},
                },
                "domain": {"values": {"core": 8, "test": 4}},
            },
        },
    }

    measurements = contribution_v2_module._precise_measurements(source)

    assert measurements["experience"]["metrics"]["language_domain_timeline"]["periods"] == [
        {
            "period": "2025",
            "commit_n": 12,
            "languages": {"values": {"python": {"n": 9, "share": 0.75}}},
            "domains": {"values": {"core": {"n": 8, "share": 2 / 3}}},
        }
    ]
    assert measurements["role_profile"]["dimensions"]["time"]["calendar_years"] == {
        "2024": 2,
        "2025": 10,
    }
    serialized = json.dumps(measurements, ensure_ascii=False)
    assert "actor-private" not in serialized
    assert "fixed OID observation" in serialized


def test_masked_precise_transform_removes_source_actor_ids_from_all_values() -> None:
    report = _report()
    report["experience"] = {
        "kind": "not_observed",
        "actor_id": "actor_alice",
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": ["actor_alice", "safe limitation"],
    }
    report["role_profile"] = {
        "kind": "not_observed",
        "actor_id": "actor_bob",
        "reason": "consenting_actor_required",
        "definition_version": "role-profile-v1",
        "limitations": ["actor_bob", "safe role limitation"],
    }

    data = contribution_v2_module._masked_data(
        report,
        key=bytes(range(32)),
        governance=_governance(),
    )
    serialized = json.dumps(data, ensure_ascii=False)

    assert "actor_alice" not in serialized
    assert "actor_bob" not in serialized
    assert "safe limitation" in serialized
    assert "safe role limitation" in serialized


def test_masked_precise_transform_collects_direct_ids_and_removes_contextual_occurrences() -> None:
    report = _report()
    report["experience"] = {
        "kind": "not_observed",
        "actor_id": "actor_outside",
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": [" subject=ACTOR_OUTSIDE ", "safe experience limitation"],
    }
    report["role_profile"] = {
        "kind": "not_observed",
        "actor_id": "actor_bob",
        "reason": "consenting_actor_required",
        "definition_version": "role-profile-v1",
        "limitations": ["prefix actor_bob suffix", "safe role limitation"],
    }

    data = contribution_v2_module._masked_data(
        report,
        key=bytes(range(32)),
        governance=_governance(),
    )
    serialized = json.dumps(data, ensure_ascii=False).casefold()

    assert "actor_outside" not in serialized
    assert "actor_bob" not in serialized
    assert "safe experience limitation" in serialized
    assert "safe role limitation" in serialized


def test_masked_short_actor_id_does_not_match_static_payload_vocabulary() -> None:
    report = _report()
    report["actor_directory"]["actors"][0]["actor_id"] = "actor"
    report["experience"] = {
        "kind": "not_observed",
        "actor_id": "actor",
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": ["actor", "safe limitation"],
    }

    data = contribution_v2_module._masked_data(
        report,
        key=bytes(range(32)),
        governance=_governance(),
    )

    assert "safe limitation" in json.dumps(data["measurements"])
    assert not contribution_v2_module._contains_forbidden_string_value(
        data["measurements"], frozenset({"actor"})
    )


def test_masked_sidecar_only_validator_rejects_source_id_reintroduced_as_value(
    tmp_path: Path,
) -> None:
    report = _report()
    key_file = _key_file(tmp_path)
    bundle = build_contribution_bundle(
        report,
        privacy="masked",
        door="controlled",
        key_file=key_file,
        controlled_context=_governance(),
    )
    assert bundle.controlled_sidecar is not None
    payload = deepcopy(bundle.payload)
    sidecar = deepcopy(bundle.controlled_sidecar)
    payload["data"]["measurements"]["experience"] = {
        "kind": "not_observed",
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": ["subject=actor_alice"],
    }
    sidecar["payload_sha256"] = contribution_v2_module._sha256(payload)

    violations = validate_controlled_bundle(payload, sidecar)

    assert "controlled masked payload contains a source actor identifier" in violations


def test_masked_validator_rejects_reintroduced_identity_without_source_report(
    tmp_path: Path,
) -> None:
    key_file = _key_file(tmp_path)
    bundle = build_contribution_bundle(
        _report(),
        privacy="masked",
        door="controlled",
        key_file=key_file,
        controlled_context=_governance(),
    )
    assert bundle.controlled_sidecar is not None
    payload = deepcopy(bundle.payload)
    sidecar = deepcopy(bundle.controlled_sidecar)
    payload["data"]["measurements"]["role_profile"] = {
        "email": "alice@example.test",
        "owner": "Alice Private",
        "resolution_seed": "actor-private",
    }
    sidecar["payload_sha256"] = contribution_v2_module._sha256(payload)

    violations = validate_controlled_bundle(payload, sidecar)

    assert any("identifying" in item for item in violations)
    serialized = json.dumps(violations)
    for source_value in ("alice@example.test", "Alice Private", "actor-private"):
        assert source_value not in serialized


def test_sidecar_recursive_credential_guard_runs_without_source_report() -> None:
    bundle = build_contribution_bundle(
        _report(),
        privacy="raw",
        door="controlled",
        controlled_context=_governance(),
        raw_material={"provider_manifest": {"coverage": "complete"}},
    )
    assert bundle.controlled_sidecar is not None
    poisoned = deepcopy(bundle.controlled_sidecar)
    poisoned["source"]["identity"]["nested"] = {"Authorization": "Bearer SYNTHETIC-SIDECAR-CANARY"}

    violations = validate_controlled_bundle(bundle.payload, poisoned)

    assert "controlled sidecar source contains credential material" in violations
    assert "SYNTHETIC-SIDECAR-CANARY" not in json.dumps(violations)


def test_masked_bundle_exact_replay_rejects_pid_report_key_and_mapping_mutations(
    tmp_path: Path,
) -> None:
    report = _report()
    key_file = _key_file(tmp_path)
    bundle = build_contribution_bundle(
        report,
        privacy="masked",
        door="controlled",
        key_file=key_file,
        controlled_context=_governance(),
    )
    assert bundle.controlled_sidecar is not None
    assert (
        validate_controlled_bundle(
            bundle.payload,
            bundle.controlled_sidecar,
            report=report,
            key_file=key_file,
        )
        == []
    )

    pid_payload = deepcopy(bundle.payload)
    pid_sidecar = deepcopy(bundle.controlled_sidecar)
    pid_payload["data"]["actors"][0]["actor_pid"] = "pa_" + "a" * 26
    pid_sidecar["payload_sha256"] = contribution_v2_module._sha256(pid_payload)
    assert any(
        "does not replay" in item
        for item in validate_controlled_bundle(
            pid_payload, pid_sidecar, report=report, key_file=key_file
        )
    )

    changed_report = deepcopy(report)
    changed_report["repository"]["name"] = "different-private-repository"
    assert validate_controlled_bundle(
        bundle.payload,
        bundle.controlled_sidecar,
        report=changed_report,
        key_file=key_file,
    )

    wrong_key = tmp_path / "wrong-study.key"
    wrong_key.write_bytes(bytes(range(31, -1, -1)))
    wrong_key.chmod(0o600)
    assert any(
        "replay" in item or "sidecar" in item
        for item in validate_controlled_bundle(
            bundle.payload,
            bundle.controlled_sidecar,
            report=report,
            key_file=wrong_key,
        )
    )

    changed_key_id_payload = deepcopy(bundle.payload)
    changed_key_id_sidecar = deepcopy(bundle.controlled_sidecar)
    changed_key_id_payload["data"]["research"]["key_id"] = "key-other"
    changed_key_id_sidecar["payload_sha256"] = contribution_v2_module._sha256(
        changed_key_id_payload
    )
    assert any(
        "key_id does not match" in item
        for item in validate_controlled_bundle(
            changed_key_id_payload,
            changed_key_id_sidecar,
            report=report,
            key_file=key_file,
        )
    )

    changed_sidecar = deepcopy(bundle.controlled_sidecar)
    changed_sidecar["source"]["actor_correspondence"][0]["source_actor_id"] = "actor_other"
    assert any(
        "sidecar does not match" in item
        for item in validate_controlled_bundle(
            bundle.payload,
            changed_sidecar,
            report=report,
            key_file=key_file,
        )
    )

    assert any(
        "valid private key source" in item
        for item in validate_controlled_bundle(
            bundle.payload,
            bundle.controlled_sidecar,
            report=report,
        )
    )


@pytest.mark.parametrize("profile", ["masked", "raw"])
def test_controlled_bundle_cross_validates_payload_sidecar_and_report(
    tmp_path: Path, profile: str
) -> None:
    report = _report()
    replay_kwargs: dict[str, object] = {}
    kwargs: dict[str, object] = {
        "privacy": profile,
        "door": "controlled",
        "controlled_context": _governance(),
    }
    if profile == "masked":
        key_file = _key_file(tmp_path)
        kwargs["key_file"] = key_file
        replay_kwargs["key_file"] = key_file
    else:
        kwargs["raw_material"] = {"provider_manifest": {"coverage": "complete"}}
    bundle = build_contribution_bundle(report, **kwargs)
    assert bundle.controlled_sidecar is not None
    assert (
        validate_controlled_bundle(
            bundle.payload,
            bundle.controlled_sidecar,
            report=report,
            **replay_kwargs,
        )
        == []
    )

    mutation_cases: list[tuple[dict, dict, dict, str]] = []
    payload = deepcopy(bundle.payload)
    sidecar = deepcopy(bundle.controlled_sidecar)
    sidecar["receipt_id"] = "receipt_" + "z" * 26
    mutation_cases.append((payload, sidecar, report, "receipt"))

    payload = deepcopy(bundle.payload)
    sidecar = deepcopy(bundle.controlled_sidecar)
    payload["purpose"] = "tampered-purpose"
    mutation_cases.append((payload, sidecar, report, "purpose"))

    payload = deepcopy(bundle.payload)
    sidecar = deepcopy(bundle.controlled_sidecar)
    sidecar["governance"]["study_id"] = "different-study"
    mutation_cases.append((payload, sidecar, report, "study"))

    payload = deepcopy(bundle.payload)
    sidecar = deepcopy(bundle.controlled_sidecar)
    changed_report = deepcopy(report)
    changed_report["repository"]["remote"] = "gitlab.example/other/project"
    mutation_cases.append((payload, sidecar, changed_report, "source report"))

    for mutated_payload, mutated_sidecar, source_report, expected in mutation_cases:
        violations = validate_controlled_bundle(
            mutated_payload,
            mutated_sidecar,
            report=source_report,
            **replay_kwargs,
        )
        assert violations
        assert any(expected in violation for violation in violations)


@pytest.mark.parametrize("profile", ["masked", "raw"])
def test_controlled_bundle_accepts_local_door_from_profile_contract(
    tmp_path: Path, profile: str
) -> None:
    report = _report()
    replay_kwargs: dict[str, object] = {}
    kwargs: dict[str, object] = {
        "privacy": profile,
        "door": "local",
        "controlled_context": _governance(),
    }
    if profile == "masked":
        key_file = _key_file(tmp_path)
        kwargs["key_file"] = key_file
        replay_kwargs["key_file"] = key_file
    else:
        kwargs["raw_material"] = {"provider_manifest": {"coverage": "complete"}}

    bundle = build_contribution_bundle(report, **kwargs)
    assert bundle.payload["door"] == "local"
    assert bundle.controlled_sidecar is not None
    assert (
        validate_controlled_bundle(
            bundle.payload,
            bundle.controlled_sidecar,
            report=report,
            **replay_kwargs,
        )
        == []
    )


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        (
            "https://person:URL-CREDENTIAL-LEAK@gitlab.example/acme/private.git?opaque=hidden#fragment",
            "https://gitlab.example/acme/private.git",
        ),
        (
            "ssh://person:URL-CREDENTIAL-LEAK@gitlab.example:2222/acme/private.git?opaque=hidden#fragment",
            "ssh://gitlab.example:2222/acme/private.git",
        ),
        (
            "person:URL-CREDENTIAL-LEAK@gitlab.example:acme/private.git?opaque=hidden#fragment",
            "ssh://gitlab.example/acme/private.git",
        ),
    ],
)
def test_controlled_sidecar_sanitizes_repository_remote_credentials(
    tmp_path: Path,
    remote: str,
    expected: str,
) -> None:
    report = deepcopy(_report())
    report["repository"]["remote"] = remote
    sidecar = tmp_path / "controlled-sidecar.json"
    payload = build_contribution(
        report,
        privacy="masked",
        door="controlled",
        key_file=_key_file(tmp_path),
        controlled_context=_governance(),
        controlled_sidecar=sidecar,
    )
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["source"]["repository"]["remote"] == expected
    combined = json.dumps(payload, ensure_ascii=False) + json.dumps(saved, ensure_ascii=False)
    for needle in ("URL-CREDENTIAL-LEAK", "opaque=hidden", "#fragment"):
        assert needle not in combined


def test_deprecated_mode_masked_is_a_strict_v2_alias(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="door=controlled"):
        build_contribution(_report(), mode="masked")

    with pytest.raises(ValueError, match="key file or key fd"):
        build_contribution(
            _report(),
            mode="masked",
            door="controlled",
            controlled_context=_governance(),
            controlled_sidecar=tmp_path / "missing-key-sidecar.json",
        )

    key = _key_file(tmp_path)
    with pytest.raises(ValueError, match="controlled-sidecar"):
        build_contribution(
            _report(),
            mode="masked",
            door="controlled",
            key_file=key,
            controlled_context=_governance(),
        )

    sidecar = tmp_path / "strict-alias-sidecar.json"
    payload = build_contribution(
        _report(),
        mode="masked",
        door="controlled",
        key_file=key,
        controlled_context=_governance(),
        controlled_sidecar=sidecar,
    )
    assert payload["privacy_profile"] == "masked"
    assert payload["door"] == "controlled"
    assert "mode" not in payload
    assert "legacy_compatibility" not in json.dumps(payload)
    assert sidecar.is_file()


def test_public_validator_rejects_controlled_or_tampered_payload(tmp_path: Path) -> None:
    controlled = build_contribution(
        _report(),
        privacy="masked",
        door="controlled",
        key_file=_key_file(tmp_path),
        controlled_context=_governance(),
        controlled_sidecar=tmp_path / "controlled-sidecar.json",
    )
    violations = validate_contribution_payload(controlled)
    assert any("controlled" in item or "privacy" in item for item in violations)

    public = build_contribution(
        _report(), privacy="aggregate", door="public-pr", receipt_id="receipt_" + "e" * 26
    )
    public["data"]["repository"] = {"remote": "https://example.test/private"}
    violations = validate_contribution_payload(public)
    assert any("identifying" in item or "source value" in item for item in violations)
