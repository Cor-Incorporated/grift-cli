"""v0.6.0 complete: identity-optional actors, repo population, contribute v2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_cli.options import build_parser
from tep_core import actor_artifacts
from tep_core.actor_artifacts import verify_actor_artifact_directory
from tep_core.contribute import build_contribution
from tep_core.public_fetch import parse_robots, path_allowed
from tep_core.schema_v2 import validate_alignment, validate_report_v2
from tep_core.secrets_guard import artifact_leaks
from tep_core.tendency import relationship

from git_fixture import commit, init_repo


def _repo_two_authors(tmp: Path) -> Path:
    repo = init_repo(tmp / "repo")
    (repo / "src" / "api").mkdir(parents=True)
    for index in range(6):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"feat a {index}",
            filename="src/api/app.py",
            name="Alice",
        )
    for index in range(3):
        commit(
            repo,
            email="b@example.com",
            date="2026-08-02",
            message=f"feat b {index}",
            filename="src/api/other.py",
            name="Bob",
        )
    return repo


def _rewrite_self_consistent_explicit_card(dest: Path, card: dict) -> None:
    """Rewrite card plus every dependent digest/Markdown member."""

    index = json.loads((dest / "actor-index.json").read_text(encoding="utf-8"))
    report = json.loads((dest / "repo-report.json").read_text(encoding="utf-8"))
    manifest = json.loads((dest / "collection-manifest.json").read_text(encoding="utf-8"))
    card_path = f"actors/{card['actor_id']}.json"
    card_md_path = f"actors/{card['actor_id']}.md"
    selection_digest = actor_artifacts._digest(
        {
            "domain": "tep-actor-selection-v1",
            "mode": index["selection"]["mode"],
            "actor_ids": index["selection"]["actor_ids"],
            "cards": [{"actor_id": card["actor_id"], "digest": actor_artifacts._digest(card)}],
        }
    )
    manifest["selection"]["digest"] = selection_digest
    changed = {
        card_path: actor_artifacts._json_bytes(card),
        card_md_path: actor_artifacts._render_card_markdown(card).encode("utf-8"),
        "repo-report.md": actor_artifacts._render_repo_markdown(
            report,
            index,
            manifest["actor_index_digest"],
            selection_digest,
        ).encode("utf-8"),
        "actor-index.md": actor_artifacts._render_index_markdown(
            index,
            manifest["actor_index_digest"],
            selection_digest,
        ).encode("utf-8"),
    }
    members = {member["path"]: member for member in manifest["members"]}
    for relative, content in changed.items():
        (dest / relative).write_bytes(content)
        members[relative]["bytes"] = len(content)
        members[relative]["sha256"] = actor_artifacts._sha256_bytes(content)
    (dest / "collection-manifest.json").write_bytes(actor_artifacts._json_bytes(manifest))


def test_identityless_repo_builds_actor_directory(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    directory = payload["actor_directory"]
    assert directory["observed_count"] >= 2
    assert payload["activity"]["scope"] == "repo"
    assert payload["activity"]["tenant_commits"] is None
    assert payload["activity"]["repo_commits"]["value"] >= 9
    assert (
        directory["observed_count"] == payload["context_profile"]["resolved_human_actors"]["value"]
    )
    assert directory["attribution"]["unresolved_commit_count"] >= 0
    assert "interpretation" not in payload
    errors = validate_report_v2(payload)
    assert errors == []


def test_actor_all_and_top(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    assert main(["actor", "--all", str(repo), "--format", "json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["schema_version"] == "actor-index-v1"
    assert listing["selection"]["mode"] == "all"
    assert listing["selection"]["selected_count"] >= 2
    capsys.readouterr()
    assert main(["actor", "--top", "1", str(repo), "--format", "json"]) == 0
    top = json.loads(capsys.readouterr().out)
    assert top["selection"]["mode"] == "top"
    assert top["selection"]["selected_count"] == 1
    assert "quality rank" in " ".join(top.get("limitations") or []).lower()


def test_actor_selection_modes_are_mutually_exclusive(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["actor", "--all", "--top", "1", str(repo)])
    assert exc.value.code == 2
    capsys.readouterr()
    assert main(["actor", "alice", str(repo), "--all", "--format", "json"]) == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_named_handle_and_unknown_actor_lists_ids(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    assert main(["actor", "--all", str(repo), "--format", "json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    actor_id = listing["actors"][0]["actor_id"]
    assert listing["actors"][0]["commit_count"] > 0
    capsys.readouterr()
    assert main(["actor", actor_id, str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"]["kind"] == "actor"
    assert payload["subject"]["canonical_id"] == actor_id
    capsys.readouterr()
    code = main(["actor", "missing_id", str(repo), "--format", "json"])
    assert code == 2
    err = capsys.readouterr().err
    assert actor_id in err
    assert "@" not in err


def test_actor_id_directory_output_is_explicit_strict_collection(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    assert main(["actor", "alice", str(repo), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["subject"]["selection"] == "inferred_actor"

    dest = tmp_path / "explicit"
    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--format",
                "both",
                "--out",
                str(dest),
            ]
        )
        == 0
    )
    capsys.readouterr()
    index = json.loads((dest / "actor-index.json").read_text(encoding="utf-8"))
    assert index["selection"] == {
        "mode": "explicit",
        "selected_count": 1,
        "actor_ids": ["alice"],
    }
    card = json.loads((dest / "actors" / "alice.json").read_text(encoding="utf-8"))
    assert card["experience"]["reason"] == "consenting_actor_required"
    assert card["role_profile"]["reason"] == "consenting_actor_required"
    assert main(["verify", str(dest), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out

    card["experience"]["reason"] = "history_incomplete"
    _rewrite_self_consistent_explicit_card(dest, card)
    verify_actor_artifact_directory(dest)
    assert main(["verify", str(dest), "--repo", str(repo)]) == 1
    assert "experience recomputation:alice" in capsys.readouterr().out


def test_actor_id_rejects_toml_output_as_ambiguous(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    output = tmp_path / "actor.toml"

    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--format",
                "json",
                "--fetch-public",
                "--out",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
    error = capsys.readouterr().err
    assert ".json or .md" in error
    assert ".toml output is not supported" in error


def test_explicit_collection_keeps_consented_experience_and_role(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    identity = tmp_path / "identity.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )
    dest = tmp_path / "consented"
    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--identity",
                str(identity),
                "--format",
                "both",
                "--out",
                str(dest),
            ]
        )
        == 0
    )
    capsys.readouterr()
    card = json.loads((dest / "actors" / "alice.json").read_text(encoding="utf-8"))
    assert card["experience"]["kind"] == "observed"
    assert card["experience"]["actor_id"] == "alice"
    assert card["role_profile"]["kind"] == "observed"
    assert card["role_profile"]["actor_id"] == "alice"
    markdown = (dest / "actors" / "alice.md").read_text(encoding="utf-8")
    assert "Experience: `observed`" in markdown
    assert "Role profile: `observed`" in markdown
    assert main(["verify", str(dest), "--repo", str(repo), "--identity", str(identity)]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_explicit_observed_detail_self_consistent_tamper_is_mismatch(
    tmp_path: Path, capsys
) -> None:
    repo = _repo_two_authors(tmp_path)
    identity = tmp_path / "identity.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )
    dest = tmp_path / "tampered-consented"
    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--identity",
                str(identity),
                "--format",
                "both",
                "--out",
                str(dest),
            ]
        )
        == 0
    )
    capsys.readouterr()
    card = json.loads((dest / "actors" / "alice.json").read_text(encoding="utf-8"))
    card["experience"]["consent_basis"] += "x"
    _rewrite_self_consistent_explicit_card(dest, card)
    verify_actor_artifact_directory(dest)
    assert (
        main(
            [
                "verify",
                str(dest),
                "--repo",
                str(repo),
                "--identity",
                str(identity),
            ]
        )
        == 1
    )
    assert "experience recomputation:alice" in capsys.readouterr().out


def test_repo_actors_out_writes_collection(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    dest = tmp_path / "out"
    assert main(["repo", str(repo), "--actors", "--format", "json", "--out", str(dest)]) == 0
    capsys.readouterr()
    assert (dest / "repo-report.json").is_file()
    assert (dest / "actor-index.json").is_file()
    assert (dest / "actors").is_dir()
    assert (dest / "collection-manifest.json").is_file()


def test_contribute_v2_masked_and_named_rules(tmp_path: Path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    out = tmp_path / "r"
    assert main(["repo", str(repo), "--format", "json", "--out", str(out)]) == 0
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="door=controlled"):
        build_contribution(report, mode="masked")

    key = tmp_path / "study.key"
    key.write_bytes(bytes(range(32)))
    key.chmod(0o600)
    study = tmp_path / "study.json"
    study.write_text(
        json.dumps(
            {
                "governance": {
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
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    rejected_out = tmp_path / "rejected.json"
    code = main(
        [
            "contribute",
            str(out / "report.json"),
            "--mode",
            "masked",
            "--yes",
            "--out",
            str(rejected_out),
        ]
    )
    assert code == 2
    assert "door=controlled" in capsys.readouterr().err
    assert not rejected_out.exists()

    contribution = tmp_path / "c.json"
    sidecar = tmp_path / "sidecar.json"
    code = main(
        [
            "contribute",
            str(out / "report.json"),
            "--mode",
            "masked",
            "--door",
            "controlled",
            "--key-file",
            str(key),
            "--controlled-sidecar",
            str(sidecar),
            "--study-manifest",
            str(study),
            "--yes",
            "--out",
            str(contribution),
        ]
    )
    assert code == 0, capsys.readouterr().err
    written = json.loads(contribution.read_text(encoding="utf-8"))
    assert written["contribution_schema"] == "tep-contribution-v2"
    assert written["privacy_profile"] == "masked"
    assert written["door"] == "controlled"
    assert "mode" not in written
    blob = json.dumps(written)
    assert "a@example.com" not in blob
    assert artifact_leaks(blob) == []
    assert sidecar.is_file()
    try:
        build_contribution(report, mode="named-public")
    except ValueError as exc:
        assert "public" in str(exc).lower() or "source" in str(exc).lower()
    actor_only = {
        "schema_version": "report-v2",
        "subject": {"kind": "actor"},
        "provenance": {"analysis_scope": "tenant"},
    }
    try:
        build_contribution(actor_only, mode="masked")
    except ValueError as exc:
        assert "actor" in str(exc)
    else:
        raise AssertionError("actor contribute must fail")


def test_n_thresholds_relationship() -> None:
    actor = {"kind": "observed", "value": 4, "unit": "commits"}
    project = {"kind": "observed", "value": 4, "unit": "commits"}
    one = relationship(
        actor_node=actor,
        project_node=project,
        declared_node={"kind": "declared", "value": 1, "unit": "commits"},
        windows_comparable=True,
        actor_n=1,
        project_n=1,
    )
    assert one["kind"] == "not_proven"
    assert one["direction"] == "similar_direction"
    five = relationship(
        actor_node=actor,
        project_node=project,
        declared_node={"kind": "declared", "value": 1, "unit": "commits"},
        windows_comparable=True,
        actor_n=5,
        project_n=5,
    )
    assert five["confidence"] == "weak_signal"
    nineteen = relationship(
        actor_node=actor,
        project_node=project,
        declared_node={"kind": "declared", "value": 1, "unit": "commits"},
        windows_comparable=True,
        actor_n=19,
        project_n=19,
    )
    assert nineteen["kind"] == "not_proven"
    twenty = relationship(
        actor_node=actor,
        project_node=project,
        declared_node={"kind": "declared", "value": 1, "unit": "commits"},
        windows_comparable=True,
        actor_n=20,
        project_n=20,
    )
    assert twenty["kind"] == "similar_direction"
    assert twenty["confidence"] == "directional_candidate"


def test_unknown_alignment_key_rejected() -> None:
    payload = {
        "schema_version": "alignment-v1",
        "report_kind": "alignment",
        "hire": 1,
        "axes": [{"axis": "x", "comparison": "overlap"}],
    }
    errors = validate_alignment(payload)
    assert errors


def test_robots_disallow_and_parser() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /\n")
    assert path_allowed(rules, "/") is False
    empty = parse_robots("")
    assert path_allowed(empty, "/repos/") is True


def test_email_as_author_name_does_not_leak(tmp_path: Path, capsys) -> None:
    repo = init_repo(tmp_path / "mailname")
    commit(
        repo,
        email="hidden@example.com",
        date="2026-08-01",
        message="feat",
        filename="src/a.py",
        name="hidden@example.com",
    )
    assert main(["repo", str(repo), "--format", "json"]) == 0
    out = capsys.readouterr().out
    assert "hidden@example.com" not in out
    payload = json.loads(out)
    names = [actor.get("display_name") for actor in payload["actor_directory"]["actors"]]
    assert all("@" not in str(name) for name in names)


def test_actor_help_does_not_require_consent() -> None:
    help_text = build_parser()._subparsers._group_actions[0].choices["actor"].format_help()
    assert "optional" in help_text.lower()
    assert "quality rank" in help_text.lower() or "--top" in help_text
    assert "FILE.json|FILE.md" in help_text
    assert "FILE.toml is rejected" in help_text
