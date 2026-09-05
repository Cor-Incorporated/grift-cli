"""Product-path consent and fixed-tree AI co-author identity falsification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.analyze import analyze_repository
from tep_core.ai_identity import AI_IDENTITY_PATH, parse_ai_identities
from tep_core.identity import IdentityValidationError, email_identity_sha256, empty_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo


def _identity(
    path: Path,
    *,
    state: str,
    consent: bool = True,
    authority: str | None = "subject-authorization",
) -> Path:
    governance = ('consent = "recorded-explicit-consent"\n' if consent else "") + (
        f'authority = "{authority}"\n' if authority else ""
    )
    path.write_text(
        'schema_version = "identity-v2"\n\n'
        "[[actors]]\n"
        'canonical_id = "alice"\n'
        'emails = ["alice@example.com"]\n'
        f'attribution_state = "{state}"\n'
        f"{governance}",
        encoding="utf-8",
    )
    return path


def _identity_text(
    actor_id: str,
    *,
    state: str = "verified",
    consent: bool = True,
) -> str:
    return (
        'schema_version = "identity-v2"\n\n'
        "[[actors]]\n"
        f'canonical_id = "{actor_id}"\n'
        'emails = ["alice@example.com"]\n'
        f'attribution_state = "{state}"\n'
        + (
            'consent = "recorded-explicit-consent"\nauthority = "subject-authorization"\n'
            if consent
            else ""
        )
    )


def _ai_document(field: str) -> str:
    value = (
        '"ai@example.com"' if field == "emails" else f'"{email_identity_sha256("ai@example.com")}"'
    )
    return f'schema_version = "ai-identity-v1"\n{field} = [{value}]\n'


def _repo_with_twenty_commits(tmp_path: Path, *, ai_field: str | None) -> Path:
    repo = init_repo(tmp_path / "repo")
    if ai_field is not None:
        commit(
            repo,
            email="alice@example.com",
            date="2026-01-01",
            message="chore: declare AI co-author identity",
            filename=AI_IDENTITY_PATH,
            content=_ai_document(ai_field),
            name="Alice",
        )
        remaining = 19
    else:
        remaining = 20

    for index in range(remaining):
        if index == 0:
            message = "feat: assisted\n\nCo-authored-by: Tool <ai@example.com>"
        elif index == 1:
            message = "feat: pair\n\nCo-authored-by: Bob <bob@example.com>"
        else:
            message = f"feat: change {index}"
        commit(
            repo,
            email="alice@example.com",
            date=f"2026-01-{index + 2:02d}",
            message=message,
            filename="src/app.py",
            name="Alice",
        )
    return repo


def _actor_report(
    repo: Path,
    identity: Path,
    capsys: object,
    *,
    out: Path | None = None,
) -> dict[str, object]:
    args = [
        "actor",
        "alice",
        str(repo),
        "--identity",
        str(identity),
        "--format",
        "json",
    ]
    if out is not None:
        args.extend(("--out", str(out)))
    assert main(args) == 0
    captured = capsys.readouterr()
    return json.loads(out.read_text(encoding="utf-8") if out is not None else captured.out)


@pytest.mark.parametrize(
    ("ai_field", "state"),
    [("emails", "verified"), ("email_sha256", "claimed")],
)
def test_fixed_tree_ai_identity_routes_to_declared_ai_without_stealing_human_coauthor(
    tmp_path: Path,
    capsys: object,
    ai_field: str,
    state: str,
) -> None:
    repo = _repo_with_twenty_commits(tmp_path, ai_field=ai_field)
    identity = _identity(tmp_path / "identity.toml", state=state)

    # A checkout-only mutation tries to reclassify the human co-author too.
    # Product analysis must read the committed blob at the fixed OID instead.
    (repo / AI_IDENTITY_PATH).write_text(
        'schema_version = "ai-identity-v1"\nemails = ["ai@example.com", "bob@example.com"]\n',
        encoding="utf-8",
    )
    report_path = tmp_path / "actor-report.json"
    report = _actor_report(repo, identity, capsys, out=report_path)

    assert report["experience"]["consent_basis"] == (
        "identity_file_explicit_consent:recorded-explicit-consent"
    )
    metrics = report["experience"]["metrics"]
    declared = metrics["declared_ai_assist_share"]
    human = metrics["human_coauthored_share"]
    assert (declared["numerator"], declared["denominator"], declared["value"]) == (1, 20, 0.05)
    assert (human["numerator"], human["denominator"], human["value"]) == (1, 20, 0.05)
    assert (
        main(
            [
                "verify",
                str(report_path),
                "--repo",
                str(repo),
                "--identity",
                str(identity),
            ]
        )
        == 0
    )
    assert "VERIFIED" in capsys.readouterr().out


def test_working_tree_only_ai_identity_does_not_reclassify_coauthor(
    tmp_path: Path, capsys: object
) -> None:
    repo = _repo_with_twenty_commits(tmp_path, ai_field=None)
    identity = _identity(tmp_path / "identity.toml", state="verified")
    path = repo / AI_IDENTITY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ai_document("emails"), encoding="utf-8")

    report = _actor_report(repo, identity, capsys)
    metrics = report["experience"]["metrics"]
    declared = metrics["declared_ai_assist_share"]
    human = metrics["human_coauthored_share"]
    assert declared["numerator"] == 0
    assert declared["observation_state"] == "no_declared_ai_commits"
    assert human["numerator"] == 2
    assert human["denominator"] == 20


def test_hash_only_consent_identity_attributes_annotated_tagger(
    tmp_path: Path, capsys: object
) -> None:
    repo = _repo_with_twenty_commits(tmp_path, ai_field=None)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Alice"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "alice@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "tag", "-a", "v1.0.0", "-m", "release"],
        check=True,
        capture_output=True,
        text=True,
    )
    identity = tmp_path / "hash-identity.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        "[[actors]]\n"
        'canonical_id = "alice"\n'
        f'email_sha256 = ["{email_identity_sha256("alice@example.com")}"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )

    report = _actor_report(repo, identity, capsys)
    tag_metric = report["experience"]["metrics"]["annotated_tag_creation"]
    assert (tag_metric["numerator"], tag_metric["denominator"], tag_metric["value"]) == (
        1,
        20,
        1,
    )


def test_ai_identity_contract_rejects_unknown_keys() -> None:
    with pytest.raises(IdentityValidationError, match="unknown key"):
        parse_ai_identities(
            'schema_version = "ai-identity-v1"\n'
            'emails = ["ai@example.com"]\n'
            'provider_handle = "not-an-identity-proof"\n'
        )


def test_subject_and_verify_ignore_cwd_identity_for_another_repo(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path / "target")
    commit(
        repo,
        email="alice@example.com",
        date="2026-02-01",
        message="feat: target",
        filename="src/app.py",
        name="Alice",
    )
    cwd = tmp_path / "caller"
    cwd_identity = cwd / ".tep" / "identity.toml"
    cwd_identity.parent.mkdir(parents=True)
    cwd_identity.write_text(_identity_text("cwd_actor"), encoding="utf-8")
    monkeypatch.chdir(cwd)

    report_path = tmp_path / "repo-report.json"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--format",
                "json",
                "--out",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    actor_ids = {row["actor_id"] for row in report["actor_directory"]["actors"]}
    assert "cwd_actor" not in actor_ids
    capsys.readouterr()
    assert main(["actor", "cwd_actor", str(repo), "--format", "json"]) == 2
    assert "unknown actor id" in capsys.readouterr().err

    cwd_identity.write_text(_identity_text("changed_cwd_actor"), encoding="utf-8")
    assert main(["verify", str(report_path), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_report_v1_verify_ignores_cwd_identity(tmp_path: Path, capsys: object, monkeypatch) -> None:
    repo = init_repo(tmp_path / "legacy-target")
    commit(
        repo,
        email="alice@example.com",
        date="2026-02-01",
        message="feat: target",
        filename="src/app.py",
        name="Alice",
    )
    report_path = tmp_path / "report-v1.json"
    report_path.write_text(
        json.dumps(analyze_repository(repo, empty_identity(), Lineage(), scope="tenant")),
        encoding="utf-8",
    )
    caller = tmp_path / "caller-v1"
    cwd_identity = caller / ".tep" / "identity.toml"
    cwd_identity.parent.mkdir(parents=True)
    cwd_identity.write_text(_identity_text("cwd_actor"), encoding="utf-8")
    monkeypatch.chdir(caller)

    assert main(["verify", str(report_path), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_sha256_alignment_verify_replays_fixed_identity(tmp_path: Path, capsys: object) -> None:
    repo = tmp_path / "sha256-alignment"
    repo.mkdir()
    initialized = subprocess.run(
        ["git", "-C", str(repo), "init", "--quiet", "--object-format=sha256"],
        capture_output=True,
        text=True,
    )
    if initialized.returncode:
        pytest.skip("installed Git does not support SHA-256 repositories")
    for key, value in (("user.name", "Alice"), ("user.email", "alice@example.com")):
        subprocess.run(
            ["git", "-C", str(repo), "config", key, value],
            check=True,
            capture_output=True,
            text=True,
        )
    identity = repo / ".tep" / "identity.toml"
    identity.parent.mkdir(parents=True)
    identity.write_text(_identity_text("alice"), encoding="utf-8")
    (repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", ".tep/identity.toml", "app.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "feat: initial"],
        check=True,
        capture_output=True,
        text=True,
    )
    project = tmp_path / "project.toml"
    project.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "sha256-project"\n',
        encoding="utf-8",
    )
    output = tmp_path / "alignment"
    assert (
        main(
            [
                "align",
                "--repo",
                str(repo),
                "--identity",
                str(identity),
                "--actor",
                "alice",
                "--project",
                str(project),
                "--format",
                "json",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    capsys.readouterr()
    alignment_path = output / "alignment.json"
    recorded = json.loads(alignment_path.read_text(encoding="utf-8"))
    assert len(recorded["provenance"]["analyzed_commit_sha"]) == 64

    identity.write_text(_identity_text("mallory"), encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", ".tep/identity.toml"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "chore: change identity"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (
        main(
            [
                "verify",
                str(alignment_path),
                "--repo",
                str(repo),
                "--project",
                str(project),
            ]
        )
        == 0
    )
    assert "VERIFIED" in capsys.readouterr().out


def test_fixed_repo_identity_beats_checkout_mutation_and_explicit_override(
    tmp_path: Path, capsys: object
) -> None:
    repo = init_repo(tmp_path / "repo-identity")
    commit(
        repo,
        email="alice@example.com",
        date="2026-03-01",
        message="chore: declare repo identity",
        filename=".tep/identity.toml",
        content=_identity_text("repo_actor"),
        name="Alice",
    )
    commit(
        repo,
        email="alice@example.com",
        date="2026-03-02",
        message="feat: code",
        filename="src/app.py",
        name="Alice",
    )
    (repo / ".tep" / "identity.toml").write_text(
        _identity_text("working_tree_actor"), encoding="utf-8"
    )

    assert main(["repo", str(repo), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    actor_ids = {row["actor_id"] for row in report["actor_directory"]["actors"]}
    assert "repo_actor" in actor_ids
    assert "working_tree_actor" not in actor_ids

    assert main(["actor", "repo_actor", str(repo), "--format", "json"]) == 0
    actor = json.loads(capsys.readouterr().out)
    assert actor["experience"]["kind"] == "observed"
    assert actor["experience"]["consent_basis"] == (
        "identity_file_explicit_consent:recorded-explicit-consent"
    )

    explicit = tmp_path / "explicit-identity.toml"
    explicit.write_text(_identity_text("explicit_actor", state="claimed"), encoding="utf-8")
    assert (
        main(
            [
                "repo",
                str(repo),
                "--identity",
                str(explicit),
                "--format",
                "json",
            ]
        )
        == 0
    )
    explicit_report = json.loads(capsys.readouterr().out)
    explicit_ids = {row["actor_id"] for row in explicit_report["actor_directory"]["actors"]}
    assert "explicit_actor" in explicit_ids
    assert "repo_actor" not in explicit_ids


@pytest.mark.parametrize("state", ["inferred", "external", "unresolved"])
def test_nonconsenting_identity_states_suppress_experience_and_role(
    tmp_path: Path, capsys: object, state: str
) -> None:
    repo = _repo_with_twenty_commits(tmp_path, ai_field="emails")
    identity = _identity(tmp_path / "identity.toml", state=state, consent=False)

    report = _actor_report(repo, identity, capsys)
    assert report["experience"]["kind"] == "not_observed"
    assert report["experience"]["actor_id"] == "alice"
    assert report["experience"]["reason"] == "consenting_actor_required"
    assert report["role_profile"]["kind"] == "not_observed"
    assert report["role_profile"]["actor_id"] == "alice"
    assert report["role_profile"]["reason"] == "consenting_actor_required"


@pytest.mark.parametrize("state", ["verified", "claimed"])
def test_attribution_state_without_recorded_consent_fails_closed(
    tmp_path: Path, capsys: object, state: str
) -> None:
    repo = _repo_with_twenty_commits(tmp_path, ai_field="emails")
    identity = _identity(
        tmp_path / "identity.toml",
        state=state,
        consent=False,
        authority="repository-owner-authorization",
    )

    report = _actor_report(repo, identity, capsys)
    assert report["experience"] == {
        "kind": "not_observed",
        "actor_id": "alice",
        "reason": "consenting_actor_required",
        "definition_version": "experience-v1",
        "limitations": report["experience"]["limitations"],
    }
    assert report["role_profile"]["kind"] == "not_observed"
    assert report["role_profile"]["reason"] == "consenting_actor_required"


def test_selected_actor_retains_full_identity_bot_declarations(
    tmp_path: Path, capsys: object
) -> None:
    repo = init_repo(tmp_path / "repo-with-custom-bot")
    commit(
        repo,
        email="ci@example.test",
        date="2026-01-01",
        message="chore: generate source",
        filename="src/bot.py",
        name="Internal CI",
    )
    for index in range(20):
        commit(
            repo,
            email="alice@example.com",
            date=f"2026-01-{index + 2:02d}",
            message=f"feat: human change {index}",
            filename="src/bot.py" if index == 0 else f"src/app-{index}.py",
            name="Alice",
        )
    identity = tmp_path / "identity-with-bot.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        "[[actors]]\n"
        'canonical_id = "alice"\n'
        'emails = ["alice@example.com"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n\n'
        "[[actors]]\n"
        'canonical_id = "internal-ci"\n'
        'emails = ["ci@example.test"]\n'
        'attribution_state = "bot"\n',
        encoding="utf-8",
    )
    report_path = tmp_path / "actor-report.json"

    report = _actor_report(repo, identity, capsys, out=report_path)

    assert report["origin"]["bot"]["value"] == 1
    cross_author = report["experience"]["metrics"]["cross_author_modification_share"]
    assert cross_author["denominator"] == 0
    founder = report["experience"]["metrics"]["founder_timing"]
    assert (founder["numerator"], founder["denominator"], founder["value"]) == (0, 20, 0.0)
    assert (
        main(
            [
                "verify",
                str(report_path),
                "--repo",
                str(repo),
                "--identity",
                str(identity),
            ]
        )
        == 0
    )
    assert "VERIFIED" in capsys.readouterr().out
