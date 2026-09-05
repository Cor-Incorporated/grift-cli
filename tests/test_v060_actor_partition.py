"""Actor partition is repo-local and independent from public forge enrichment."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from git_fixture import commit as git_commit
from git_fixture import init_repo

from tep_core.attribution import (
    PublicAccount,
    attribution_payload,
    build_attribution_index,
    canonicalize_author,
    derive_repo_scope_digest,
    parse_mailmap,
    read_mailmap_at_revision,
)
from tep_core.gitutil import GitCommit, normalize_remote, repository_identity
from tep_core.identity import Actor, IdentityConfig, empty_identity
from tep_core.origin import OriginResult, is_bot_email


def _commit(
    oid: str,
    *,
    email: str,
    name: str,
    parent: str | None = None,
) -> GitCommit:
    return GitCommit(
        sha=oid,
        author_email=email,
        author_name=name,
        parents=(() if parent is None else (parent,)),
        date="2026-08-01",
        subject="fixture",
    )


def _origin(commits: list[GitCommit]) -> OriginResult:
    return OriginResult(classes_by_sha={item.sha: "unresolved" for item in commits})


def _partition(index) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        sorted((actor.actor_id, tuple(sorted(actor.commit_shas))) for actor in index.actors)
    )


def test_same_email_different_names_merge_and_same_name_different_emails_split() -> None:
    commits = [
        _commit("1" * 40, email=" Alice@Example.COM ", name="Alice Old"),
        _commit("2" * 40, email="alice@example.com", name="Alice New", parent="1" * 40),
        _commit("3" * 40, email="other@example.com", name="Alice New", parent="2" * 40),
    ]

    index = build_attribution_index(commits, _origin(commits), empty_identity())

    assert len(index.actors) == 2
    assert index.sha_to_actor["1" * 40] == index.sha_to_actor["2" * 40]
    assert index.sha_to_actor["2" * 40] != index.sha_to_actor["3" * 40]
    assert all(actor.actor_id.startswith("actor_") for actor in index.actors)
    reversed_index = build_attribution_index(
        list(reversed(commits)), _origin(commits), empty_identity()
    )
    assert _partition(reversed_index) == _partition(index)
    assert reversed_index.partition_digest == index.partition_digest


def test_unique_author_name_slugs_remain_cli_compatible() -> None:
    commits = [
        _commit("1" * 40, email="alice@example.com", name="Alice"),
        _commit("2" * 40, email="bob@example.com", name="Bob", parent="1" * 40),
    ]

    index = build_attribution_index(commits, _origin(commits), empty_identity())

    assert {actor.actor_id for actor in index.actors} == {"alice", "bob"}


def test_explicit_identity_aliases_have_precedence_over_email_clusters() -> None:
    commits = [
        _commit("1" * 40, email="old@example.com", name="Old Name"),
        _commit("2" * 40, email="new@example.com", name="New Name", parent="1" * 40),
    ]
    identity = IdentityConfig(
        actors=(
            Actor(
                canonical_id="alice",
                emails=("old@example.com", "new@example.com"),
                github_login="alice-gh",
                attribution_state="verified",
            ),
        ),
        pending_attribution=False,
    )

    index = build_attribution_index(commits, _origin(commits), identity)

    assert len(index.actors) == 1
    assert index.actors[0].actor_id == "alice"
    assert index.actors[0].display_status == "public_handle"
    assert index.actors[0].public_handle_basis == "identity_declared"


def test_mailmap_is_loaded_from_fixed_revision_not_working_tree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git_commit(
        repo,
        email="maintainer@example.com",
        name="Maintainer",
        date="2026-08-01",
        message="add fixed mailmap",
        filename=".mailmap",
        content="Canonical <canonical@example.com> <old@example.com>\n",
    )
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    (repo / ".mailmap").write_text(
        "Wrong <wrong@example.com> <old@example.com>\n", encoding="utf-8"
    )
    snapshot = read_mailmap_at_revision(repo, revision)
    commits = [
        _commit("1" * 40, email="old@example.com", name="Old"),
        _commit("2" * 40, email="canonical@example.com", name="Canonical", parent="1" * 40),
    ]

    index = build_attribution_index(
        commits,
        _origin(commits),
        empty_identity(),
        mailmap=snapshot,
    )

    assert snapshot.present is True
    assert snapshot.target_oid.value == revision
    assert snapshot.blob_oid is not None
    assert len(index.actors) == 1
    assert index.mailmap_present is True
    assert "canonical@example.com" in index.actors[0].canonical_emails
    assert "wrong@example.com" not in index.actors[0].canonical_emails


def test_all_four_official_mailmap_forms_match_git_check_mailmap(tmp_path: Path) -> None:
    cases = (
        (
            "Proper One <commit-one@example.test>\n",
            "Commit One",
            "COMMIT-ONE@example.test",
        ),
        (
            "<proper-two@example.test> <commit-two@example.test>\n",
            "Commit Two",
            "commit-two@example.test",
        ),
        (
            "Proper Three <proper-three@example.test> <commit-three@example.test>\n",
            "Commit Three",
            "commit-three@example.test",
        ),
        (
            "Proper Four <proper-four@example.test> Commit Four <commit-four@example.test>\n",
            "commit four",
            "COMMIT-FOUR@example.test",
        ),
    )
    for index, (mailmap, author_name, author_email) in enumerate(cases):
        repo = init_repo(tmp_path / f"mailmap-{index}")
        (repo / ".mailmap").write_text(mailmap, encoding="utf-8")
        checked = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "check-mailmap",
                f"{author_name} <{author_email}>",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        matched = re.fullmatch(r"(.*) <([^<>]+)>", checked)
        assert matched is not None

        canonical_name, canonical_email, mapped = canonicalize_author(
            name=author_name,
            email=author_email,
            entries=parse_mailmap(mailmap),
        )

        assert mapped is True
        assert (canonical_name, canonical_email) == (
            matched.group(1),
            matched.group(2).casefold(),
        )


def test_public_enrichment_never_changes_partition() -> None:
    commits = [
        _commit("1" * 40, email="alice@example.com", name="Alice"),
        _commit("2" * 40, email="alice@example.com", name="A. Example", parent="1" * 40),
        _commit("3" * 40, email="bob@example.com", name="Bob", parent="2" * 40),
    ]
    account = PublicAccount(
        provider="github",
        host="github.com",
        account_id="1234",
        handle="alice-gh",
        profile_url="https://github.com/alice-gh",
        evidence="commit_author_object",
    )

    offline = build_attribution_index(commits, _origin(commits), empty_identity())
    partial = build_attribution_index(
        commits,
        _origin(commits),
        empty_identity(),
        sha_to_accounts={"1" * 40: account},
    )
    full = build_attribution_index(
        commits,
        _origin(commits),
        empty_identity(),
        sha_to_accounts={"1" * 40: account, "2" * 40: account},
    )

    assert _partition(offline) == _partition(partial) == _partition(full)
    assert offline.partition_digest == partial.partition_digest == full.partition_digest
    assert offline.sha_to_actor_digest == partial.sha_to_actor_digest == full.sha_to_actor_digest
    payload = attribution_payload(full, human_commit_count=3)
    assert payload["actor_partition"] == {
        "definition": "repo_local_git_primary_author_cluster",
        "repo_scope_digest": full.repo_scope_digest,
        "object_format": "sha1",
        "partition_digest": full.partition_digest,
        "sha_to_actor_digest": full.sha_to_actor_digest,
        "provider_enrichment_changes_partition": False,
    }
    alice = next(actor for actor in full.actors if len(actor.commit_shas) == 2)
    assert alice.display_name == "alice-gh"
    assert alice.public_accounts == (account,)
    assert alice.public_account_status == "linked"


def test_account_ambiguity_and_cross_actor_conflict_do_not_merge_actors() -> None:
    commits = [
        _commit("1" * 40, email="alice@example.com", name="Alice"),
        _commit("2" * 40, email="alice@example.com", name="Alice", parent="1" * 40),
        _commit("3" * 40, email="bob@example.com", name="Bob", parent="2" * 40),
    ]
    shared = PublicAccount("github", "github.com", "7", "shared")
    second = PublicAccount("github", "github.com", "8", "alice-alt")

    index = build_attribution_index(
        commits,
        _origin(commits),
        empty_identity(),
        sha_to_accounts={
            "1" * 40: (shared, second),
            "2" * 40: shared,
            "3" * 40: shared,
        },
    )

    assert len(index.actors) == 2
    assert _partition(index) == _partition(
        build_attribution_index(commits, _origin(commits), empty_identity())
    )
    assert index.join_ambiguous >= 1
    assert len(index.account_conflicts) == 1
    assert set(next(iter(index.account_conflicts.values()))) == {
        index.sha_to_actor["1" * 40],
        index.sha_to_actor["3" * 40],
    }
    assert all(actor.public_account_status in {"ambiguous", "conflict"} for actor in index.actors)


def test_missing_email_uses_name_and_missing_both_is_unresolved() -> None:
    commits = [
        _commit("1" * 40, email="", name="No Email"),
        _commit("2" * 40, email="", name=" no email ", parent="1" * 40),
        _commit("3" * 40, email="", name="", parent="2" * 40),
    ]

    index = build_attribution_index(commits, _origin(commits), empty_identity())

    assert len(index.actors) == 1
    assert index.actors[0].display_status == "git_author_name"
    assert index.actors[0].commit_shas == ("1" * 40, "2" * 40)
    assert index.unresolved_shas == ("3" * 40,)


def test_bot_email_heuristic_requires_a_registered_address_or_bot_suffix() -> None:
    assert is_bot_email("bot[bot]@users.noreply.github.com") is True
    assert is_bot_email("41898282+github-actions[bot]@users.noreply.github.com") is True
    assert is_bot_email("action@github.com") is True
    assert is_bot_email("github-actions@github.com") is True
    assert is_bot_email("dependabot@github.com") is True
    assert is_bot_email("renovate@whitesourcesoftware.com") is True

    assert is_bot_email("renovate.engineer@example.com") is False
    assert is_bot_email("github-actions-maintainer@example.com") is False
    assert is_bot_email("dependabotanist@example.com") is False
    assert is_bot_email("action@github.com.example") is False


def test_sha256_git_oids_are_supported_in_repo_scope_and_joins() -> None:
    commits = [
        _commit("a" * 64, email="alice@example.com", name="Alice"),
        _commit("b" * 64, email="bob@example.com", name="Bob", parent="a" * 64),
    ]
    account = PublicAccount("gitlab", "gitlab.example", "42", "alice")

    index = build_attribution_index(
        commits,
        _origin(commits),
        empty_identity(),
        sha_to_accounts={"A" * 64: account},
    )

    assert index.object_format == "sha256"
    assert len(index.repo_scope_digest) == 64
    assert len(index.partition_digest) == 64
    assert index.join_matched == 1
    assert index.sha_to_actor["a" * 64] != index.sha_to_actor["b" * 64]


def test_repo_scope_includes_pre_sanitized_canonical_origin() -> None:
    commits = [_commit("a" * 40, email="alice@example.com", name="Alice")]

    no_origin, object_format = derive_repo_scope_digest(commits)
    first, _ = derive_repo_scope_digest(commits, "github.com/acme/repo")
    second, _ = derive_repo_scope_digest(commits, "gitlab.example/acme/repo")
    index = build_attribution_index(
        commits,
        _origin(commits),
        empty_identity(),
        canonical_origin="github.com/acme/repo",
    )

    assert object_format == "sha1"
    assert len({no_origin, first, second}) == 3
    assert index.repo_scope_digest == first


def test_offline_remote_identity_strips_credentials_query_and_fragment() -> None:
    expected = "github.com/acme/repo"
    assert normalize_remote("https://github.com/acme/repo.git") == expected
    assert normalize_remote("https://token@github.com/acme/repo.git") == expected
    assert (
        normalize_remote("https://alice:secret@github.com/acme/repo.git?access_token=leak#private")
        == expected
    )
    assert normalize_remote("git@github.com:acme/repo.git") == expected
    assert normalize_remote("github.com/acme/repo.git?token=leak#private") == expected
    assert (
        normalize_remote("ssh://git@gitlab.example.test:2222/group/repo.git")
        == "gitlab.example.test:2222/group/repo"
    )
    assert (
        normalize_remote("ssh://git@[2001:db8::7]:2222/group/repo.git")
        == "[2001:db8::7]:2222/group/repo"
    )
    assert (
        normalize_remote("forge.example.test:8443/group/repo.git")
        == "forge.example.test:8443/group/repo"
    )


def test_offline_remote_identity_never_exposes_filesystem_paths(tmp_path: Path) -> None:
    assert normalize_remote("/Users/example/private.git") is None
    assert normalize_remote("file:///Users/example/private.git") is None
    assert normalize_remote("../private.git") is None
    assert normalize_remote("./private.git") is None
    assert normalize_remote("private/repo.git") is None

    repo = init_repo(tmp_path / "source")
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "/Users/example/private.git"],
        check=True,
    )
    identity = repository_identity(repo, include_local_path=False)
    assert identity["remote"] is None
    assert "/Users/example" not in repr(identity)


def test_sanitized_remote_produces_same_scope_as_clean_remote() -> None:
    commits = [_commit("a" * 40, email="alice@example.com", name="Alice")]
    clean = normalize_remote("https://github.com/acme/repo.git")
    tainted = normalize_remote(
        "https://token@github.com/acme/repo.git?access_token=secret#fragment"
    )
    assert clean == tainted == "github.com/acme/repo"
    clean_digest, _ = derive_repo_scope_digest(commits, clean)
    tainted_digest, _ = derive_repo_scope_digest(commits, tainted)
    assert clean_digest == tainted_digest
