"""0.8.0 #1 — the actor index never lists people by how much they committed.

Two readers again. The engineer asks whether appearing lower in the table says
anything about them; the client asks whether `--top N` still picks the same N.
Each has a test that fails when their side is broken, and the fixtures are built
so that volume order and id order disagree: the most prolific actor carries the
lexicographically last id. A sort by commit count puts them first, a sort by id
puts them last, and a test that cannot tell the two apart would prove nothing
(the 0.7.x order was `-len(commit_shas)`, see ADR-0001).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.actor_artifacts import (
    INDEX_ORDER_LIMITATION,
    ActorArtifactError,
    actor_summaries,
    build_actor_artifacts,
    verify_actor_artifact_directory,
    write_actor_artifacts,
)
from tep_core.attribution import AttributionIndex, InferredActor

from git_fixture import commit, init_repo

OID = "f" * 40
# Volume order: zed (4) > mid (2) > abe (1). Id order: abe < mid < zed.
ABE, MID, ZED = "abe", "mid", "zed"


def _actor(actor_id: str, shas: tuple[str, ...]) -> InferredActor:
    return InferredActor(
        actor_id=actor_id,
        display_name=actor_id.title(),
        display_status="stable_hash",
        internal_actor_id=f"private-{actor_id}",
        commit_shas=shas,
        nonmerge_count=len(shas),
        merge_count=0,
    )


def _index() -> AttributionIndex:
    actors = (
        _actor(ZED, ("1" * 40, "2" * 40, "3" * 40, "4" * 40)),
        _actor(ABE, ("5" * 40,)),
        _actor(MID, ("6" * 40, "7" * 40)),
    )
    mapping = {sha: actor.actor_id for actor in actors for sha in actor.commit_shas}
    return AttributionIndex(
        actors=actors,
        sha_to_actor=mapping,
        bot_count=0,
        merge_count=0,
        coauthored_count=0,
        mailmap_present=False,
        join_matched=0,
        join_unmatched=0,
        commit_login_count=0,
        repo_scope_digest="a" * 64,
        object_format="sha1",
        partition_digest="b" * 64,
        sha_to_actor_digest="c" * 64,
    )


def _report() -> dict:
    return {
        "target": {"oid": {"algorithm": "sha1", "value": OID}},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.8.0",
            "definition_version": "tep-v0.8.0-test",
            "analysis_scope": "repo",
            "analyzed_at": "2026-10-25T00:00:00Z",
            "analyzed_commit_sha": OID,
            "target_oid": {"algorithm": "sha1", "value": OID},
            "revision_completeness": {"shallow": False, "promisor": False, "complete": True},
            "input_digests": {
                "git": {"algorithm": "sha256", "value": "d" * 64},
                "tagset": "e" * 64,
            },
            "tagset_digest": "e" * 64,
        },
        "window": {"start": "2026-01-01", "end": "2026-10-25", "unit": "date-range"},
        "attribution": {"unresolved_commit_count": 0},
    }


# --- the engineer's side -----------------------------------------------------


def test_rows_are_ordered_by_actor_id_not_by_commit_count() -> None:
    rows = actor_summaries(_index())
    assert [row["actor_id"] for row in rows] == [ABE, MID, ZED]
    # The counts are still there, as facts; only their order stopped meaning anything.
    assert [row["commit_count"] for row in rows] == [1, 2, 4]


def test_index_and_markdown_carry_the_same_order_and_say_so() -> None:
    artifacts = build_actor_artifacts(_index(), _report())
    ids = [row["actor_id"] for row in artifacts.actor_index["actors"]]
    assert ids == [ABE, MID, ZED]
    assert INDEX_ORDER_LIMITATION in artifacts.actor_index["limitations"]
    markdown = artifacts.index_markdown
    assert INDEX_ORDER_LIMITATION in markdown
    table_rows = [line for line in markdown.splitlines() if line.startswith("| `")]
    assert [line.split("`")[1] for line in table_rows] == [ABE, MID, ZED]


# --- the client's side -------------------------------------------------------


def test_top_n_still_selects_the_most_prolific_but_lists_them_by_id() -> None:
    top_one = build_actor_artifacts(_index(), _report(), selection_mode="top", top=1)
    assert top_one.actor_index["selection"]["actor_ids"] == [ZED]
    top_two = build_actor_artifacts(_index(), _report(), selection_mode="top", top=2)
    # Set is the same as 0.7.x (zed, mid); order follows the index, not the volume.
    assert top_two.actor_index["selection"]["actor_ids"] == [MID, ZED]
    assert [card["actor_id"] for card in top_two.cards] == [MID, ZED]


# --- the verifier itself -----------------------------------------------------


def _rewrite_member(root: Path, relative: str, payload: dict) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    (root / relative).write_text(text, encoding="utf-8")
    manifest_path = root / "collection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    member = next(item for item in manifest["members"] if item["path"] == relative)
    member["bytes"] = len(text.encode("utf-8"))
    member["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def test_verifier_rejects_rows_put_back_into_volume_order(tmp_path: Path) -> None:
    destination = tmp_path / "collection"
    write_actor_artifacts(destination, build_actor_artifacts(_index(), _report()))
    verify_actor_artifact_directory(destination)

    index = json.loads((destination / "actor-index.json").read_text(encoding="utf-8"))
    index["actors"].sort(key=lambda row: -row["commit_count"])
    assert [row["actor_id"] for row in index["actors"]] == [ZED, MID, ABE]
    _rewrite_member(destination, "actor-index.json", index)
    # Even with the member digest refreshed, the order itself is rejected before
    # any digest comparison: a reordered table is not the same evidence.
    with pytest.raises(ActorArtifactError, match="ordered by actor id"):
        verify_actor_artifact_directory(destination)


# --- real git, end to end ----------------------------------------------------


def _repo_where_volume_and_id_disagree(tmp: Path) -> Path:
    """Three authors whose commit counts run opposite to their id order."""
    repo = init_repo(tmp / "repo")
    (repo / "src").mkdir()
    plan = (
        ("zed@example.com", "Zed", 5),
        ("mid@example.com", "Mid", 3),
        ("abe@example.com", "Abe", 1),
    )
    day = 1
    for email, name, count in plan:
        for index in range(count):
            commit(
                repo,
                email=email,
                date=f"2026-08-{day:02d}",
                message=f"feat: {name} {index}",
                filename=f"src/{name.lower()}.py",
                name=name,
            )
            day += 1
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n'
        + "".join(
            f'[[actors]]\ncanonical_id = "{name.lower()}"\nemails = ["{email}"]\n'
            'attribution_state = "verified"\n\n'
            for email, name, _ in plan
        ),
        encoding="utf-8",
    )
    return repo


def test_cli_collection_is_id_ordered_and_verifies(tmp_path: Path, capsys) -> None:
    repo = _repo_where_volume_and_id_disagree(tmp_path)
    out = tmp_path / "collection"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--actors",
                "--identity",
                str(repo / ".tep" / "identity.toml"),
                "--format",
                "json",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    index = json.loads((out / "actor-index.json").read_text(encoding="utf-8"))
    ids = [row["actor_id"] for row in index["actors"]]
    counts = [row["commit_count"] for row in index["actors"]]
    assert ids == [ABE, MID, ZED]
    assert counts == [1, 3, 5]

    assert (
        main(
            [
                "verify",
                str(out),
                "--repo",
                str(repo),
                "--identity",
                str(repo / ".tep" / "identity.toml"),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.startswith("VERIFIED")


# --- the repo report's directory (the other place volume used to order people) ---


def test_repo_report_actor_directory_is_id_ordered_in_json_and_markdown() -> None:
    from tep_core.actor_directory import actor_directory_payload
    from tep_core.report_v2 import _actor_directory_lines

    payload = actor_directory_payload(_index(), human_commit_count=7)
    assert [row["actor_id"] for row in payload["actors"]] == [ABE, MID, ZED]
    lines = _actor_directory_lines({"actor_directory": payload})
    table_rows = [line for line in lines if line.startswith("| ") and "actors/" in line]
    assert [line.split("|")[1].strip() for line in table_rows] == [ABE, MID, ZED]
    assert any("actor_id 順" in line for line in lines)


def test_cli_repo_report_directory_follows_id_order(tmp_path: Path, capsys) -> None:
    repo = _repo_where_volume_and_id_disagree(tmp_path)
    assert (
        main(
            [
                "repo",
                str(repo),
                "--identity",
                str(repo / ".tep" / "identity.toml"),
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    rows = report["actor_directory"]["actors"]
    assert [(row["actor_id"], row["commit_count"]) for row in rows] == [
        (ABE, 1),
        (MID, 3),
        (ZED, 5),
    ]


# --- `--top` at the edges ------------------------------------------------------


def _tied_index() -> AttributionIndex:
    actors = (
        _actor(ZED, ("1" * 40, "2" * 40)),
        _actor(ABE, ("3" * 40, "4" * 40)),
        _actor(MID, ("5" * 40,)),
    )
    mapping = {sha: actor.actor_id for actor in actors for sha in actor.commit_shas}
    return AttributionIndex(
        actors=actors,
        sha_to_actor=mapping,
        bot_count=0,
        merge_count=0,
        coauthored_count=0,
        mailmap_present=False,
        join_matched=0,
        join_unmatched=0,
        commit_login_count=0,
        repo_scope_digest="a" * 64,
        object_format="sha1",
        partition_digest="b" * 64,
        sha_to_actor_digest="c" * 64,
    )


def test_top_tie_breaks_on_actor_id_like_0_7_x() -> None:
    # abe and zed both have 2 commits; 0.7.x broke the tie by actor id (abe first).
    top_one = build_actor_artifacts(_tied_index(), _report(), selection_mode="top", top=1)
    assert top_one.actor_index["selection"]["actor_ids"] == [ABE]


def test_top_beyond_actor_count_selects_everyone_in_row_order() -> None:
    top_many = build_actor_artifacts(_index(), _report(), selection_mode="top", top=99)
    assert top_many.actor_index["selection"]["actor_ids"] == [ABE, MID, ZED]


# --- the verifier checks the selection, not just the rows ----------------------


def test_verifier_rejects_selection_out_of_row_order(tmp_path: Path) -> None:
    destination = tmp_path / "collection"
    write_actor_artifacts(destination, build_actor_artifacts(_index(), _report()))
    index = json.loads((destination / "actor-index.json").read_text(encoding="utf-8"))
    index["selection"]["actor_ids"] = [ZED, MID, ABE]
    _rewrite_member(destination, "actor-index.json", index)
    with pytest.raises(ActorArtifactError, match="follow index row order"):
        verify_actor_artifact_directory(destination)


def test_verifier_rejects_top_selection_that_is_not_the_most_commits(tmp_path: Path) -> None:
    destination = tmp_path / "collection"
    write_actor_artifacts(
        destination, build_actor_artifacts(_index(), _report(), selection_mode="top", top=1)
    )
    index = json.loads((destination / "actor-index.json").read_text(encoding="utf-8"))
    assert index["selection"]["actor_ids"] == [ZED]
    index["selection"]["actor_ids"] = [ABE]
    _rewrite_member(destination, "actor-index.json", index)
    # The card files still belong to zed, but the selection check runs first.
    with pytest.raises(ActorArtifactError, match="most commits"):
        verify_actor_artifact_directory(destination)


def test_row_order_error_names_only_the_first_pair() -> None:
    from tep_core.actor_artifacts import _require_actor_id_order

    with pytest.raises(ActorArtifactError) as info:
        _require_actor_id_order(["abe", "zed", "mid", "abc"])
    message = str(info.value)
    assert "'zed' before 'mid' at row 2" in message
    assert "abc" not in message
