from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from tep_core.actor_artifacts import (
    ActorArtifactError,
    build_actor_artifacts,
    verify_actor_artifact_directory,
    write_actor_artifacts,
)
from tep_core.attribution import AttributionIndex, InferredActor, PublicAccount
from tep_core.schema import validate_schema


OID = "f" * 40
ACTOR_A = "actor_" + "a" * 12
ACTOR_B = "actor_" + "b" * 12
ACTOR_C = "actor_" + "c" * 12


def _index(*, public: bool = False) -> AttributionIndex:
    account = (
        PublicAccount(
            provider="github",
            host="github.com",
            account_id="42",
            handle="alice",
            profile_url="https://github.com/alice",
            evidence="commit_sha_to_account",
        )
        if public
        else None
    )
    actors = (
        InferredActor(
            actor_id=ACTOR_A,
            display_name="Alice <private@example.test>",
            display_status="public_handle" if public else "stable_hash",
            internal_actor_id="must-never-be-emitted",
            emails=("private@example.test",),
            canonical_emails=("private@example.test",),
            commit_shas=("1" * 40, "2" * 40, "3" * 40),
            nonmerge_count=2,
            merge_count=1,
            public_accounts=(account,) if account else (),
            public_account_status="linked" if account else "not_requested",
        ),
        InferredActor(
            actor_id=ACTOR_B,
            display_name="Bob",
            display_status="stable_hash",
            internal_actor_id="also-private",
            commit_shas=("4" * 40, "5" * 40),
            nonmerge_count=2,
            merge_count=0,
        ),
        InferredActor(
            actor_id=ACTOR_C,
            display_name="Carol",
            display_status="stable_hash",
            internal_actor_id="private-three",
            commit_shas=("6" * 40,),
            nonmerge_count=1,
            merge_count=0,
        ),
    )
    mapping = {sha: actor.actor_id for actor in actors for sha in actor.commit_shas}
    return AttributionIndex(
        actors=actors,
        sha_to_actor=mapping,
        bot_count=2,
        merge_count=1,
        coauthored_count=1,
        mailmap_present=True,
        join_matched=1 if public else 0,
        join_unmatched=5 if public else 0,
        commit_login_count=1 if public else 0,
        repo_scope_digest="a" * 64,
        object_format="sha1",
        partition_digest="b" * 64,
        sha_to_actor_digest="c" * 64,
    )


def _report(*, oid: str = OID, algorithm: str = "sha1") -> dict:
    return {
        "target": {"oid": {"algorithm": algorithm, "value": oid}},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "definition_version": "tep-v0.6.0-test",
            "analysis_scope": "repo",
            "analyzed_at": "2026-08-31T00:00:00Z",
            "analyzed_commit_sha": oid,
            "target_oid": {"algorithm": algorithm, "value": oid},
            "revision_completeness": {
                "shallow": False,
                "promisor": False,
                "complete": True,
            },
            "input_digests": {
                "git": {"algorithm": "sha256", "value": "d" * 64},
                "tagset": "e" * 64,
            },
            "tagset_digest": "e" * 64,
            "git_window": {
                "start": "2026-01-01",
                "end": "2026-08-31",
                "days": 242,
                "unit": "days",
            },
        },
        "limitations": ["Fixed OID observation."],
        "notices": ["No LLM."],
    }


def _write(tmp_path: Path, *, mode: str = "all", top: int | None = None, actor_ids=None):
    artifacts = build_actor_artifacts(
        _index(),
        _report(),
        selection_mode=mode,
        top=top,
        actor_ids=actor_ids,
    )
    destination = tmp_path / "actor-output"
    manifest = write_actor_artifacts(destination, artifacts)
    return destination, artifacts, manifest


def _rewrite_member(root: Path, relative: str, value: dict) -> None:
    path = root / relative
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    manifest_path = root / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    member = next(item for item in manifest["members"] if item["path"] == relative)
    member["bytes"] = len(encoded)
    member["sha256"] = hashlib.sha256(encoded).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def test_all_selection_writes_closed_verified_population(tmp_path: Path) -> None:
    destination, artifacts, manifest = _write(tmp_path)

    result = verify_actor_artifact_directory(destination)
    assert result.full_actor_count == 3
    assert result.selected_actor_count == 3
    assert result.member_count == 10
    assert artifacts.repo_report["provenance"]["tagset_digest"] == "e" * 64
    assert artifacts.repo_report["provenance"]["input_digests"]["tagset"] == "e" * 64
    assert artifacts.actor_index["population"]["human_commit_count"] == 6
    assert artifacts.actor_index["selection"] == {
        "mode": "all",
        "selected_count": 3,
        "actor_ids": [ACTOR_A, ACTOR_B, ACTOR_C],
    }
    assert validate_schema("actor-index-v1", artifacts.actor_index) == []
    assert validate_schema("report-v2", artifacts.repo_report) == []
    assert all(validate_schema("actor-card-v1", card) == [] for card in artifacts.cards)
    assert manifest["full"]["actor_count"] == 3
    assert manifest["selection"]["actor_count"] == 3
    assert manifest["selection"]["links"][0] == {
        "actor_id": ACTOR_A,
        "json": f"actors/{ACTOR_A}.json",
        "markdown": f"actors/{ACTOR_A}.md",
    }

    corpus = "\n".join(
        path.read_text(errors="replace") for path in destination.rglob("*") if path.is_file()
    )
    assert "private@example.test" not in corpus
    assert "must-never-be-emitted" not in corpus
    assert "internal_actor_id" not in corpus
    assert "repo-report.json" in {item["path"] for item in manifest["members"]}


def test_repo_projection_rejects_divergent_tagset_binding() -> None:
    report = _report()
    report["provenance"]["input_digests"]["tagset"] = "0" * 64

    with pytest.raises(ActorArtifactError, match="must equal input_digests.tagset"):
        build_actor_artifacts(_index(), report)


def test_top_and_explicit_keep_full_population_digest_but_change_selection() -> None:
    all_artifacts = build_actor_artifacts(_index(), _report())
    top = build_actor_artifacts(_index(), _report(), selection_mode="top", top=2)
    explicit = build_actor_artifacts(
        _index(),
        _report(),
        selection_mode="explicit",
        actor_ids=[ACTOR_C, ACTOR_A],
        actor_details={
            ACTOR_A: {
                "experience": {
                    "kind": "not_observed",
                    "actor_id": ACTOR_A,
                    "reason": "consenting_actor_required",
                    "definition_version": "experience-v1",
                    "limitations": ["Consent is required."],
                },
                "role_profile": {
                    "kind": "not_observed",
                    "actor_id": ACTOR_A,
                    "reason": "consenting_actor_required",
                    "definition_version": "role-profile-v1",
                    "limitations": ["Consent is required."],
                },
            }
        },
    )

    assert top.actor_index["population"]["actor_count"] == 3
    assert top.actor_index["selection"]["actor_ids"] == [ACTOR_A, ACTOR_B]
    assert explicit.actor_index["selection"]["actor_ids"] == [ACTOR_A, ACTOR_C]
    assert len(top.cards) == len(explicit.cards) == 2
    assert all_artifacts.population_digest == top.population_digest == explicit.population_digest
    assert (
        len(
            {
                all_artifacts.selection_digest["value"],
                top.selection_digest["value"],
                explicit.selection_digest["value"],
            }
        )
        == 3
    )
    assert "actors/actor_aaaaaaaaaaaa.json" in explicit.index_markdown
    assert "actors/actor_bbbbbbbbbbbb.json" not in explicit.index_markdown
    explicit_cards = {card["actor_id"]: card for card in explicit.cards}
    assert explicit_cards[ACTOR_A]["experience"]["actor_id"] == ACTOR_A
    assert "experience" not in explicit_cards[ACTOR_C]


def test_explicit_detail_actor_binding_fails_closed() -> None:
    mismatched = {
        "kind": "not_observed",
        "actor_id": ACTOR_B,
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": ["Consent is required."],
    }
    with pytest.raises(ActorArtifactError, match=r"experience\.actor_id"):
        build_actor_artifacts(
            _index(),
            _report(),
            selection_mode="explicit",
            actor_ids=[ACTOR_A],
            actor_details={
                ACTOR_A: {
                    "experience": mismatched,
                    "role_profile": {
                        **mismatched,
                        "definition_version": "role-profile-v1",
                    },
                }
            },
        )


@pytest.mark.parametrize(
    ("mode", "top", "actor_ids", "message"),
    [
        ("all", 1, None, "all selection"),
        ("top", None, None, "requires an integer"),
        ("top", 1, [ACTOR_A], "cannot include"),
        ("explicit", None, None, "requires actor IDs"),
        ("explicit", None, [ACTOR_A, ACTOR_A], "must be unique"),
        ("explicit", None, ["actor_" + "f" * 12], "unknown explicit"),
    ],
)
def test_selection_modes_are_mutually_exclusive(mode, top, actor_ids, message) -> None:
    with pytest.raises(ActorArtifactError, match=message):
        build_actor_artifacts(
            _index(),
            _report(),
            selection_mode=mode,
            top=top,
            actor_ids=actor_ids,
        )


def test_provider_account_needs_exact_member_commit_evidence() -> None:
    with pytest.raises(ActorArtifactError, match="missing exact commit evidence"):
        build_actor_artifacts(_index(public=True), _report())

    artifacts = build_actor_artifacts(
        _index(public=True),
        _report(),
        account_evidence={"github|github.com|42": ["2" * 40]},
    )
    account = artifacts.cards[0]["accounts"][0]
    assert account == {
        "provider": "github",
        "host": "github.com",
        "account_id": "42",
        "handle": "alice",
        "profile_url": "https://github.com/alice",
        "evidence": [
            {
                "kind": "commit_account_link",
                "commit_oid": {"algorithm": "sha1", "value": "2" * 40},
            }
        ],
    }


def test_account_evidence_cannot_bind_another_actor_commit() -> None:
    with pytest.raises(ActorArtifactError, match="not a member"):
        build_actor_artifacts(
            _index(public=True),
            _report(),
            account_evidence={"github|github.com|42": ["4" * 40]},
        )


def test_conflicted_account_keeps_only_each_actor_commit_evidence() -> None:
    index = _index()
    shared = PublicAccount(
        provider="github",
        host="github.com",
        account_id="42",
        handle="shared",
        profile_url="https://github.com/shared",
        evidence="commit_sha_to_account",
    )
    index.actors[0].public_accounts = (shared,)
    index.actors[0].public_account_status = "conflict"
    index.actors[1].public_accounts = (shared,)
    index.actors[1].public_account_status = "conflict"

    artifacts = build_actor_artifacts(
        index,
        _report(),
        account_evidence={"github|github.com|42": ["1" * 40, "4" * 40]},
    )

    cards = {card["actor_id"]: card for card in artifacts.cards}
    assert cards[ACTOR_A]["account_status"] == "conflict"
    assert cards[ACTOR_B]["account_status"] == "conflict"
    assert cards[ACTOR_A]["accounts"][0]["evidence"] == [
        {
            "kind": "commit_account_link",
            "commit_oid": {"algorithm": "sha1", "value": "1" * 40},
        }
    ]
    assert cards[ACTOR_B]["accounts"][0]["evidence"] == [
        {
            "kind": "commit_account_link",
            "commit_oid": {"algorithm": "sha1", "value": "4" * 40},
        }
    ]
    assert artifacts.actor_index["partition_digest"]["value"] == index.partition_digest


def test_conflicted_account_still_rejects_invalid_oid() -> None:
    index = _index(public=True)
    index.actors[0].public_account_status = "conflict"
    with pytest.raises(ActorArtifactError, match="invalid Git OID"):
        build_actor_artifacts(
            index,
            _report(),
            account_evidence={"github|github.com|42": ["not-an-oid"]},
        )


def test_email_like_provider_value_is_rejected() -> None:
    index = _index(public=True)
    index.actors[0].public_accounts = (
        PublicAccount(
            provider="github",
            host="github.com",
            account_id="private@example.test",
            handle="alice",
            profile_url="https://github.com/alice",
            evidence="commit_sha_to_account",
        ),
    )
    with pytest.raises(ActorArtifactError, match="email-like value"):
        build_actor_artifacts(
            index,
            _report(),
            account_evidence={"github|github.com|private@example.test": ["1" * 40]},
        )


def test_card_arithmetic_tamper_fails_even_with_updated_file_digest(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    relative = f"actors/{ACTOR_A}.json"
    card = json.loads((destination / relative).read_text())
    card["n"] = 2
    _rewrite_member(destination, relative, card)

    with pytest.raises(ActorArtifactError, match="numerator mismatch"):
        verify_actor_artifact_directory(destination)


def test_index_arithmetic_tamper_fails_schema_validation(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    index = json.loads((destination / "actor-index.json").read_text())
    index["actors"][0]["nonmerge_commit_count"] = 1
    _rewrite_member(destination, "actor-index.json", index)

    with pytest.raises(ActorArtifactError, match="nonmerge_commit_count"):
        verify_actor_artifact_directory(destination)


def test_population_digest_tamper_fails_after_member_digest_refresh(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    relative = f"actors/{ACTOR_A}.json"
    card = json.loads((destination / relative).read_text())
    card["population_digest"]["value"] = "0" * 64
    _rewrite_member(destination, relative, card)

    with pytest.raises(ActorArtifactError, match="population mismatch"):
        verify_actor_artifact_directory(destination)


def test_markdown_tamper_fails_even_with_updated_file_digest(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    relative = f"actors/{ACTOR_A}.md"
    path = destination / relative
    content = path.read_bytes().replace(b"Observed commits: 3 / 6", b"Observed commits: 2 / 6")
    path.write_bytes(content)
    manifest_path = destination / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    member = next(item for item in manifest["members"] if item["path"] == relative)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    with pytest.raises(ActorArtifactError, match="Markdown does not match"):
        verify_actor_artifact_directory(destination)


def test_manifest_selection_digest_tamper_is_detected(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    manifest_path = destination / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["selection"]["digest"]["value"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    with pytest.raises(ActorArtifactError, match="selection digest mismatch"):
        verify_actor_artifact_directory(destination)


def test_unregistered_member_is_rejected(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    (destination / "actors" / "unknown.json").write_text("{}\n")

    with pytest.raises(ActorArtifactError, match="unknown"):
        verify_actor_artifact_directory(destination)


def test_symlink_member_is_rejected_before_following_it(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"private":"do-not-read"}\n')
    os.symlink(outside, destination / "actors" / "escape.json")

    with pytest.raises(ActorArtifactError, match="symlink"):
        verify_actor_artifact_directory(destination)


def test_manifest_traversal_is_rejected(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    manifest_path = destination / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["members"][0]["path"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    with pytest.raises(ActorArtifactError, match="unsafe manifest member path"):
        verify_actor_artifact_directory(destination)


def test_manifest_unknown_key_is_rejected(tmp_path: Path) -> None:
    destination, _, _ = _write(tmp_path)
    manifest_path = destination / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["unregistered"] = True
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    with pytest.raises(ActorArtifactError, match="unknown keys"):
        verify_actor_artifact_directory(destination)


def test_writer_refuses_existing_directory_without_replace_and_replaces_atomically(
    tmp_path: Path,
) -> None:
    destination, _, first = _write(tmp_path)
    artifacts = build_actor_artifacts(_index(), _report(), selection_mode="top", top=1)
    with pytest.raises(ActorArtifactError, match="already exists"):
        write_actor_artifacts(destination, artifacts)
    assert verify_actor_artifact_directory(destination).selected_actor_count == 3

    second = write_actor_artifacts(destination, artifacts, replace=True)
    assert verify_actor_artifact_directory(destination).selected_actor_count == 1
    assert first["selection"]["digest"] != second["selection"]["digest"]


def test_writer_refuses_symlink_destination(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    artifacts = build_actor_artifacts(_index(), _report())
    with pytest.raises(ActorArtifactError, match="must not be a symlink"):
        write_actor_artifacts(linked, artifacts)


def test_writer_refuses_symlink_parent_without_writing_outside(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    artifacts = build_actor_artifacts(_index(), _report())

    with pytest.raises(ActorArtifactError, match="must not traverse a symlink"):
        write_actor_artifacts(linked_parent / "actor-output", artifacts)

    assert list(outside.iterdir()) == []


def test_verifier_refuses_collection_reached_through_symlink_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    destination = real_parent / "actor-output"
    write_actor_artifacts(destination, build_actor_artifacts(_index(), _report()))
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ActorArtifactError, match="must not traverse a symlink"):
        verify_actor_artifact_directory(linked_parent / "actor-output")


def test_writer_refuses_regular_file_destination(tmp_path: Path) -> None:
    destination = tmp_path / "actor-output"
    destination.write_text("owner data\n")
    artifacts = build_actor_artifacts(_index(), _report())
    with pytest.raises(ActorArtifactError, match="must be a directory"):
        write_actor_artifacts(destination, artifacts, replace=True)
    assert destination.read_text() == "owner data\n"


def test_provider_profile_url_cannot_contain_userinfo() -> None:
    index = _index(public=True)
    index.actors[0].public_accounts = (
        PublicAccount(
            provider="github",
            host="github.com",
            account_id="42",
            handle="alice",
            profile_url="https://credential@github.com/alice",
            evidence="commit_sha_to_account",
        ),
    )
    with pytest.raises(ActorArtifactError, match="credential-free HTTPS"):
        build_actor_artifacts(
            index,
            _report(),
            account_evidence={"github|github.com|42": ["1" * 40]},
        )


@pytest.mark.parametrize(
    "unsafe_profile",
    [
        "https://github.com/alice?access_token=super-secret",
        "https://github.com/alice#access_token=super-secret",
        "https://github.com/alice?tab=repositories#profile",
        "https://github.com.evil.example/alice",
        "https://github.com/alice/settings",
        "https://github.com/alice/",
        "http://github.com/alice",
    ],
)
def test_actor_artifact_rejects_noncanonical_profile_url(unsafe_profile: str) -> None:
    index = _index(public=True)
    index.actors[0].public_accounts = (
        PublicAccount(
            provider="github",
            host="github.com",
            account_id="42",
            handle="alice",
            profile_url=unsafe_profile,
            evidence="commit_sha_to_account",
        ),
    )
    with pytest.raises(ActorArtifactError, match="canonical credential-free HTTPS"):
        build_actor_artifacts(
            index,
            _report(),
            account_evidence={"github|github.com|42": ["1" * 40]},
        )


def test_sha256_target_and_account_evidence_remain_generic() -> None:
    actor = InferredActor(
        actor_id=ACTOR_A,
        display_name="Alice",
        display_status="public_handle",
        commit_shas=("1" * 64,),
        nonmerge_count=1,
        public_accounts=(
            PublicAccount(
                provider="gitlab",
                host="gitlab.example.test",
                account_id="1001",
                handle="alice",
                profile_url="https://gitlab.example.test/alice",
                evidence="commit_sha_to_account",
            ),
        ),
        public_account_status="linked",
    )
    index = AttributionIndex(
        actors=(actor,),
        sha_to_actor={"1" * 64: ACTOR_A},
        repo_scope_digest="a" * 64,
        object_format="sha256",
        partition_digest="b" * 64,
        sha_to_actor_digest="c" * 64,
    )
    artifacts = build_actor_artifacts(
        index,
        _report(oid="f" * 64, algorithm="sha256"),
        account_evidence={"gitlab|gitlab.example.test|1001": ["1" * 64]},
    )
    assert artifacts.cards[0]["target"]["oid"]["algorithm"] == "sha256"
    assert artifacts.cards[0]["accounts"][0]["evidence"][0]["commit_oid"] == {
        "algorithm": "sha256",
        "value": "1" * 64,
    }
