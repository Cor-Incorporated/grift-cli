"""CLI regression tests for provider-account source binding.

The actor collection is intentionally a closed, self-consistent artifact.  A
provider account is nevertheless not independently verifiable unless the
public-evidence bundle that supplied the stable account mapping is replayed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import tep_core.actor_artifacts as actor_artifacts
from git_fixture import commit, git, init_repo
from tep_cli.__main__ import main
from tep_core.forge_public import GitObjectId, HttpResponse, RequestSpec, parse_forge_locator
from tep_core.public_evidence import collect_public_evidence


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def source_bound_collection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[Path, Path, Path]:
    """Create a one-actor collection from a complete replayable GitHub bundle."""

    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://github.com/acme/widget.git")
    commit(
        repo,
        email="alice@example.test",
        date="2026-08-30",
        message="initial evidence",
        name="Alice",
    )
    target = _head(repo)
    locator = parse_forge_locator("https://github.com/acme/widget.git")

    def transport(_request: RequestSpec) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps(
                [
                    {
                        "sha": target,
                        "author": {
                            "id": 42,
                            "node_id": "MDQ6VXNlcjQy",
                            "login": "alice",
                            "html_url": "https://github.com/alice",
                        },
                    }
                ]
            ).encode("utf-8"),
            headers={"ETag": '"fixture-page-1"'},
        )

    bundle = tmp_path / "public-evidence"
    manifest = collect_public_evidence(
        locator,
        GitObjectId("sha1", target),
        transport=transport,
        evidence_dir=bundle,
        fetched_at="2026-08-31T00:00:00Z",
    )
    assert manifest["coverage"]["status"] == "complete"

    collection = tmp_path / "actor-collection"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--rev",
                target,
                "--public-evidence",
                str(bundle),
                "--actors",
                "--format",
                "json",
                "--out",
                str(collection),
            ]
        )
        == 0
    )
    capsys.readouterr()
    cards = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((collection / "actors").glob("*.json"))
    ]
    assert len(cards) == 1
    assert cards[0]["account_status"] == "matched"
    assert cards[0]["accounts"][0]["account_id"] == "42"
    return repo, bundle, collection


def _rewrite_self_consistent_account_metadata(collection: Path) -> None:
    """Change account metadata while refreshing every collection-local digest."""

    index = json.loads((collection / "actor-index.json").read_text(encoding="utf-8"))
    report = json.loads((collection / "repo-report.json").read_text(encoding="utf-8"))
    card_path = next(iter(sorted((collection / "actors").glob("*.json"))))
    card = json.loads(card_path.read_text(encoding="utf-8"))
    account = card["accounts"][0]
    account.update(
        {
            "account_id": "9001",
            "handle": "forged-account",
            "profile_url": "https://github.com/forged-account",
        }
    )

    card_path.write_bytes(actor_artifacts._json_bytes(card))
    card_markdown = collection / "actors" / f"{card['actor_id']}.md"
    card_markdown.write_text(
        actor_artifacts._render_card_markdown(card),
        encoding="utf-8",
    )

    selection = index["selection"]
    selected_cards = [
        json.loads((collection / "actors" / f"{actor_id}.json").read_text(encoding="utf-8"))
        for actor_id in selection["actor_ids"]
    ]
    selection_digest = actor_artifacts._digest(
        {
            "domain": "tep-actor-selection-v1",
            "mode": selection["mode"],
            "actor_ids": selection["actor_ids"],
            "cards": [
                {
                    "actor_id": selected_card["actor_id"],
                    "digest": actor_artifacts._digest(selected_card),
                }
                for selected_card in selected_cards
            ],
        }
    )
    index_digest = actor_artifacts._digest(index)
    (collection / "repo-report.md").write_text(
        actor_artifacts._render_repo_markdown(
            report,
            index,
            index_digest,
            selection_digest,
        ),
        encoding="utf-8",
    )
    (collection / "actor-index.md").write_text(
        actor_artifacts._render_index_markdown(index, index_digest, selection_digest),
        encoding="utf-8",
    )

    manifest_path = collection / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selection"]["digest"] = selection_digest
    for member in manifest["members"]:
        content = (collection / member["path"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(actor_artifacts._json_bytes(manifest))

    # This mutation is deliberately internally consistent.  The external
    # public-evidence binding, rather than a stale member hash, must reject it.
    actor_artifacts.verify_actor_artifact_directory(collection)


def test_provider_accounts_without_bound_bundle_cannot_verify(
    source_bound_collection: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, _bundle, collection = source_bound_collection

    assert main(["verify", str(collection), "--repo", str(repo)]) == 2
    output = capsys.readouterr().out
    assert "CANNOT_VERIFY" in output
    assert "--public-evidence" in output


def test_provider_accounts_with_matching_bundle_verify(
    source_bound_collection: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, bundle, collection = source_bound_collection

    assert (
        main(
            [
                "verify",
                str(collection),
                "--repo",
                str(repo),
                "--public-evidence",
                str(bundle),
            ]
        )
        == 0
    )
    assert "VERIFIED" in capsys.readouterr().out


def test_self_consistent_account_replacement_mismatches_bound_bundle(
    source_bound_collection: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, bundle, collection = source_bound_collection
    _rewrite_self_consistent_account_metadata(collection)

    assert (
        main(
            [
                "verify",
                str(collection),
                "--repo",
                str(repo),
                "--public-evidence",
                str(bundle),
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "MISMATCH" in output
    assert "provider account metadata/OID binding" in output


def test_explicit_missing_public_evidence_bundle_cannot_verify(
    source_bound_collection: tuple[Path, Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, _bundle, collection = source_bound_collection
    missing = tmp_path / "missing-public-evidence"

    assert (
        main(
            [
                "verify",
                str(collection),
                "--repo",
                str(repo),
                "--public-evidence",
                str(missing),
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "CANNOT_VERIFY" in output
    assert "manifest is missing" in output


def test_offline_collection_without_provider_accounts_verifies_without_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = init_repo(tmp_path / "offline-repo")
    commit(
        repo,
        email="offline@example.test",
        date="2026-08-30",
        message="offline evidence",
        name="Offline Author",
    )
    collection = tmp_path / "offline-collection"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--actors",
                "--format",
                "json",
                "--out",
                str(collection),
            ]
        )
        == 0
    )
    capsys.readouterr()

    cards = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((collection / "actors").glob("*.json"))
    ]
    assert cards and all(card["accounts"] == [] for card in cards)
    assert main(["verify", str(collection), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out
