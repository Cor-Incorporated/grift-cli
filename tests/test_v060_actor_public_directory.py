"""Provider-neutral public accounts in actor directory artifacts."""

from __future__ import annotations

import json

from tep_core.actor_directory import actor_directory_payload
from tep_core.attribution import build_attribution_index
from tep_core.gitutil import GitCommit
from tep_core.identity import empty_identity
from tep_core.origin import OriginResult


def test_actor_directory_serializes_account_without_canonical_email() -> None:
    sha = "1" * 40
    commits = [
        GitCommit(
            sha=sha,
            author_email="private@example.test",
            author_name="Alice",
            parents=(),
            date="2026-08-31",
            subject="fixture",
        )
    ]
    origin = OriginResult(classes_by_sha={sha: "unresolved"})
    index = build_attribution_index(
        commits,
        origin,
        empty_identity(),
        sha_to_accounts={
            sha: {
                "provider": "github",
                "host": "github.com",
                "account_id": "42",
                "handle": "alice-public",
                "profile_url": "https://github.com/alice-public",
                "evidence": {"basis": "commit.author.id", "commit_oid": sha},
            }
        },
    )

    payload = actor_directory_payload(index, human_commit_count=1)
    row = payload["actors"][0]
    assert row["internal_actor_id"].startswith("actor_")
    assert len(row["internal_actor_id"]) == len("actor_") + 32
    assert row["public_account_status"] == "linked"
    assert row["public_accounts"] == [
        {
            "provider": "github",
            "host": "github.com",
            "account_id": "42",
            "handle": "alice-public",
            "profile_url": "https://github.com/alice-public",
            "evidence": {
                "basis": "commit.author.id",
                "account_match_status": "linked",
            },
        }
    ]
    encoded = json.dumps(payload)
    assert "private@example.test" not in encoded
    assert "canonical_emails" not in encoded
    assert "commit_oid" not in encoded


def test_actor_directory_keeps_conflict_status_explicit() -> None:
    commits = [
        GitCommit(
            sha="1" * 40,
            author_email="alice@example.test",
            author_name="Alice",
            parents=(),
            date="2026-08-31",
            subject="a",
        ),
        GitCommit(
            sha="2" * 40,
            author_email="bob@example.test",
            author_name="Bob",
            parents=("1" * 40,),
            date="2026-08-31",
            subject="b",
        ),
    ]
    origin = OriginResult(classes_by_sha={item.sha: "unresolved" for item in commits})
    shared = {
        "provider": "github",
        "host": "github.com",
        "account_id": "42",
        "handle": "shared",
        "evidence": {"basis": "commit.author.id"},
    }
    index = build_attribution_index(
        commits,
        origin,
        empty_identity(),
        sha_to_accounts={"1" * 40: shared, "2" * 40: shared},
    )
    payload = actor_directory_payload(index, human_commit_count=2)
    assert {row["public_account_status"] for row in payload["actors"]} == {"conflict"}
    assert all(
        row["public_accounts"][0]["evidence"]["account_match_status"] == "conflict"
        for row in payload["actors"]
    )
