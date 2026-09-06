"""Falsification tests for v0.7.1 bot / app account handling.

A GitHub commit whose author is a Bot or app installation (``dependabot[bot]``,
``renovate[bot]``, ``Copilot``) has an ``html_url`` under ``/apps/<slug>`` and a
handle the downstream intake contract rejects.  Such a row must be counted as an
unlinked commit rather than attached as a public account, because a public
account row is required to carry both a handle and a canonical profile URL.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_core.actor_artifacts import ActorArtifactError, build_actor_artifacts
from tep_core.attribution import AttributionIndex, InferredActor, PublicAccount
from tep_core.forge_public import GitObjectId, HttpResponse, RequestSpec, parse_forge_locator
from tep_core.public_evidence import collect_public_evidence, verify_public_evidence


def _collect(tmp_path: Path, rows: list[dict[str, object]], name: str) -> dict:
    locator = parse_forge_locator("https://github.com/acme/widget.git")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(status=200, body=json.dumps(rows).encode(), headers={})

    bundle = tmp_path / name
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", "a" * 40),
        transport=transport,
        evidence_dir=bundle,
    )
    assert verify_public_evidence(bundle)["status"] == "VERIFIED"
    return manifest


@pytest.mark.parametrize(
    ("login", "slug"),
    [
        ("Copilot", "copilot-swe-agent"),
        ("dependabot[bot]", "dependabot"),
        ("renovate[bot]", "renovate"),
        ("github-actions[bot]", "github-actions"),
    ],
)
def test_github_bot_author_is_unlinked_not_a_public_account(
    tmp_path: Path, login: str, slug: str
) -> None:
    manifest = _collect(
        tmp_path,
        [
            {
                "sha": "1" * 40,
                "author": {
                    "id": 198982749,
                    "login": login,
                    "type": "Bot",
                    "html_url": f"https://github.com/apps/{slug}",
                },
            }
        ],
        f"bot-{slug}",
    )
    assert manifest["sha_to_account"] == {}
    assert manifest["unlinked_commit_count"] == 1


def test_github_bot_author_with_canonical_profile_url_is_still_unlinked(
    tmp_path: Path,
) -> None:
    """``type == "Bot"`` alone disqualifies the row, profile shape aside."""

    manifest = _collect(
        tmp_path,
        [
            {
                "sha": "1" * 40,
                "author": {
                    "id": 49699333,
                    "login": "dependabot",
                    "type": "Bot",
                    "html_url": "https://github.com/dependabot",
                },
            }
        ],
        "bot-canonical-profile",
    )
    assert manifest["sha_to_account"] == {}
    assert manifest["unlinked_commit_count"] == 1


@pytest.mark.parametrize(
    "html_url",
    [
        "https://example.test/alice",
        "https://github.com/alice/extra",
        "https://github.com/apps/alice",
        "http://github.com/alice",
        "https://github.com/bob",
        None,
    ],
)
def test_github_user_without_canonical_profile_url_is_unlinked(
    tmp_path: Path, html_url: object
) -> None:
    author: dict[str, object] = {"id": 42, "login": "alice", "type": "User"}
    if html_url is not None:
        author["html_url"] = html_url
    manifest = _collect(
        tmp_path,
        [{"sha": "1" * 40, "author": author}],
        f"noncanonical-{abs(hash(html_url))}",
    )
    assert manifest["sha_to_account"] == {}
    assert manifest["unlinked_commit_count"] == 1


def test_github_human_author_with_canonical_profile_stays_linked(tmp_path: Path) -> None:
    manifest = _collect(
        tmp_path,
        [
            {
                "sha": "1" * 40,
                "author": {
                    "id": 42,
                    "login": "alice",
                    "type": "User",
                    "html_url": "https://github.com/alice",
                },
            },
            {
                "sha": "2" * 40,
                "author": {
                    "id": 198982749,
                    "login": "Copilot",
                    "type": "Bot",
                    "html_url": "https://github.com/apps/copilot-swe-agent",
                },
            },
        ],
        "human-linked",
    )
    account = manifest["sha_to_account"]["1" * 40]
    assert account["account_id"] == "42"
    assert account["handle"] == "alice"
    assert account["profile_url"] == "https://github.com/alice"
    assert "2" * 40 not in manifest["sha_to_account"]
    assert manifest["unlinked_commit_count"] == 1


def _actor_index(account: PublicAccount) -> AttributionIndex:
    actor = InferredActor(
        actor_id="actor_" + "a" * 12,
        display_name="Alice <private@example.test>",
        display_status="public_handle",
        internal_actor_id="never-emitted",
        commit_shas=("1" * 40,),
        nonmerge_count=1,
        merge_count=0,
        public_accounts=(account,),
        public_account_status="linked",
    )
    return AttributionIndex(
        actors=(actor,),
        sha_to_actor={"1" * 40: actor.actor_id},
        join_matched=1,
        commit_login_count=1,
        repo_scope_digest="a" * 64,
        object_format="sha1",
        partition_digest="b" * 64,
        sha_to_actor_digest="c" * 64,
    )


def _report(oid: str = "f" * 40) -> dict:
    return {
        "target": {"oid": {"algorithm": "sha1", "value": oid}},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.7.1",
            "definition_version": "tep-v0.7.1-test",
            "analysis_scope": "repo",
            "analyzed_at": "2026-09-05T00:00:00Z",
            "analyzed_commit_sha": oid,
            "target_oid": {"algorithm": "sha1", "value": oid},
            "revision_completeness": {"shallow": False, "promisor": False, "complete": True},
            "input_digests": {
                "git": {"algorithm": "sha256", "value": "d" * 64},
                "tagset": "e" * 64,
            },
            "tagset_digest": "e" * 64,
            "git_window": {
                "start": "2026-01-01",
                "end": "2026-09-05",
                "days": 247,
                "unit": "days",
            },
        },
        "limitations": ["Fixed OID observation."],
        "notices": ["No LLM."],
    }


@pytest.mark.parametrize(
    "account",
    [
        PublicAccount(
            provider="github",
            host="github.com",
            account_id="198982749",
            handle="Copilot",
            profile_url=None,
            evidence="commit_sha_to_account",
        ),
        PublicAccount(
            provider="github",
            host="github.com",
            account_id="42",
            handle=None,
            profile_url="https://github.com/alice",
            evidence="commit_sha_to_account",
        ),
    ],
)
def test_account_rows_still_reject_missing_handle_or_profile_url(
    account: PublicAccount,
) -> None:
    """The human-account requirement is unchanged: this must keep raising."""

    with pytest.raises(ActorArtifactError, match="needs a handle and profile URL"):
        build_actor_artifacts(
            _actor_index(account),
            _report(),
            account_evidence={
                f"github|github.com|{account.account_id}": ["1" * 40],
            },
        )
