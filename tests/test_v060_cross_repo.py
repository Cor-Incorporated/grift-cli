"""Cross-repo alignment, surface file units, verify replay, manifest, windows."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.surface_profile import surface_profile

from git_fixture import commit, git, init_repo
from tep_core.gitutil import GitCommit, rev_parse

PACK = Path(__file__).resolve().parents[1] / "benchmarks" / "v060"


def _ident(repo: Path, canonical: str = "candidate_001", email: str = "a@example.com") -> Path:
    path = repo / ".tep" / "identity.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\n'
        f'canonical_id = "{canonical}"\nemails = ["{email}"]\n'
        'attribution_state = "verified"\n',
        encoding="utf-8",
    )
    return path


def _project_toml(path: Path, surfaces: str = '["backend"]') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""schema_version = "tep-project-v1"
project_id = "checkout-api"
[requirements.surfaces]
required = {surfaces}
""",
        encoding="utf-8",
    )
    return path


def _actor_repo(tmp: Path, name: str = "actor") -> Path:
    repo = init_repo(tmp / name)
    # v0.6 subjects read the repo-local identity from the fixed target tree.
    # Create it before the first fixture commit so checkout-only state cannot
    # influence Actor partitioning or consent eligibility.
    _ident(repo)
    git(repo, "add", ".tep/identity.toml")
    (repo / "src" / "api").mkdir(parents=True)
    commit(
        repo, email="a@example.com", date="2026-08-01", message="feat", filename="src/api/app.py"
    )
    commit(
        repo,
        email="a@example.com",
        date="2026-08-01",
        message="ui",
        filename="src/components/Button.tsx",
    )
    return repo


def _project_repo(tmp: Path, name: str = "project") -> Path:
    repo = init_repo(tmp / name)
    (repo / "src" / "api").mkdir(parents=True)
    commit(
        repo, email="p@example.com", date="2026-08-02", message="feat", filename="src/api/svc.py"
    )
    _project_toml(repo / ".tep" / "project.toml")
    (repo / ".tep").mkdir(parents=True, exist_ok=True)
    git(repo, "remote", "add", "origin", f"https://github.com/acme/{name}.git")
    return repo


def _bound_tracker(repo: Path, path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "tep-tracker-export-v2",
                "binding": {
                    "provider": "github",
                    "host": "github.com",
                    "project_id": f"R_{repo.name}",
                    "project_path": f"acme/{repo.name}",
                    "target_oid": {"algorithm": "sha1", "value": rev_parse(repo)},
                    "window": {
                        "start": "2026-08-01T00:00:00Z",
                        "end": "2026-09-01T00:00:00Z",
                    },
                    "coverage": {
                        "status": "complete",
                        "observed": 31,
                        "expected": 31,
                        "missing": 0,
                        "unit": "days",
                    },
                },
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cross_repo_alignment_succeeds(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = _project_repo(tmp_path)
    assert (
        main(
            [
                "actor",
                "candidate_001",
                str(actor),
                "--format",
                "json",
                "--out",
                str(tmp_path / "actor-report.json"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "project",
                str(project),
                "--requirements",
                str(project / ".tep" / "project.toml"),
                "--format",
                "json",
                "--out",
                str(tmp_path / "project-report.json"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "actor-report.json"),
            "--project-report",
            str(tmp_path / "project-report.json"),
            "--format",
            "json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "alignment-v1"
    assert payload["actor_observed"]
    assert payload["project_observed"]["kind"] == "observed"
    assert payload["project_declared"]
    assert payload["actor_provenance"]["analyzed_commit_sha"]
    assert payload["project_provenance"]["analyzed_commit_sha"]
    assert payload["actor_report_digest"]
    assert payload["project_report_digest"]
    assert (
        payload["actor_provenance"]["analyzed_commit_sha"]
        != payload["project_provenance"]["analyzed_commit_sha"]
    )


def test_project_observed_change_is_isolated(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = _project_repo(tmp_path)
    main(
        [
            "actor",
            "candidate_001",
            str(actor),
            "--format",
            "json",
            "--out",
            str(tmp_path / "a.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "project",
            str(project),
            "--requirements",
            str(project / ".tep" / "project.toml"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "p1.json"),
        ]
    )
    capsys.readouterr()
    commit(
        project, email="p@example.com", date="2026-08-03", message="more", filename="src/api/two.py"
    )
    main(
        [
            "project",
            str(project),
            "--requirements",
            str(project / ".tep" / "project.toml"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "p2.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a.json"),
            "--project-report",
            str(tmp_path / "p1.json"),
            "--format",
            "json",
        ]
    )
    first = json.loads(capsys.readouterr().out)
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a.json"),
            "--project-report",
            str(tmp_path / "p2.json"),
            "--format",
            "json",
        ]
    )
    second = json.loads(capsys.readouterr().out)
    assert first["actor_report_digest"] == second["actor_report_digest"]
    assert first["project_report_digest"] != second["project_report_digest"]


def test_declared_change_is_isolated(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = _project_repo(tmp_path)
    main(
        [
            "actor",
            "candidate_001",
            str(actor),
            "--format",
            "json",
            "--out",
            str(tmp_path / "a.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "project",
            str(project),
            "--requirements",
            str(project / ".tep" / "project.toml"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "p1.json"),
        ]
    )
    capsys.readouterr()
    _project_toml(project / ".tep" / "project.toml", '["frontend"]')
    main(
        [
            "project",
            str(project),
            "--requirements",
            str(project / ".tep" / "project.toml"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "p2.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a.json"),
            "--project-report",
            str(tmp_path / "p1.json"),
            "--format",
            "json",
        ]
    )
    first = json.loads(capsys.readouterr().out)
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a.json"),
            "--project-report",
            str(tmp_path / "p2.json"),
            "--format",
            "json",
        ]
    )
    second = json.loads(capsys.readouterr().out)
    assert first["declared"] != second["declared"]
    assert first["actor_report_digest"] == second["actor_report_digest"]


def test_actor_repo_change_is_isolated(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = _project_repo(tmp_path)
    main(
        [
            "actor",
            "candidate_001",
            str(actor),
            "--format",
            "json",
            "--out",
            str(tmp_path / "a1.json"),
        ]
    )
    capsys.readouterr()
    commit(
        actor, email="a@example.com", date="2026-08-04", message="extra", filename="src/api/more.py"
    )
    main(
        [
            "actor",
            "candidate_001",
            str(actor),
            "--format",
            "json",
            "--out",
            str(tmp_path / "a2.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "project",
            str(project),
            "--requirements",
            str(project / ".tep" / "project.toml"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "p.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a1.json"),
            "--project-report",
            str(tmp_path / "p.json"),
            "--format",
            "json",
        ]
    )
    first = json.loads(capsys.readouterr().out)
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a2.json"),
            "--project-report",
            str(tmp_path / "p.json"),
            "--format",
            "json",
        ]
    )
    second = json.loads(capsys.readouterr().out)
    assert first["project_report_digest"] == second["project_report_digest"]
    assert first["actor_report_digest"] != second["actor_report_digest"]


def test_alignment_contains_both_shas_and_no_verdict(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = _project_repo(tmp_path)
    main(
        [
            "actor",
            "candidate_001",
            str(actor),
            "--format",
            "json",
            "--out",
            str(tmp_path / "a.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "project",
            str(project),
            "--requirements",
            str(project / ".tep" / "project.toml"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "p.json"),
        ]
    )
    capsys.readouterr()
    main(
        [
            "align",
            "--actor-report",
            str(tmp_path / "a.json"),
            "--project-report",
            str(tmp_path / "p.json"),
            "--format",
            "both",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out[captured.out.find("{") :])
    assert payload["provenance"]["actor_commit_sha"]
    assert payload["provenance"]["project_commit_sha"]
    for key in ("overall", "score", "rank", "fit", "recommendation", "hire"):
        assert f'"{key}"' not in json.dumps(payload)


def test_surface_file_and_commit_counts_differ() -> None:
    commits = [
        GitCommit(
            "1" * 40,
            "a@x",
            ("p",),
            "2026-08-01",
            "a",
            files=("src/api/a.py", "src/api/b.py"),
            author_iso="2026-08-01T12:00:00Z",
        ),
        GitCommit(
            "2" * 40,
            "a@x",
            ("p",),
            "2026-08-01",
            "b",
            files=("src/api/a.py",),
            author_iso="2026-08-01T13:00:00Z",
        ),
    ]
    profile = surface_profile(commits, empty_reason="x")
    commits_n = profile["surface_commit_counts"]["values"]["backend"]
    files_n = profile["surface_file_counts"]["values"]["backend"]
    unique_n = profile["surface_unique_file_counts"]["values"]["backend"]
    assert commits_n == 2
    assert files_n == 3
    assert unique_n == 2
    assert profile["surface_commit_counts"]["unit"] != profile["surface_file_counts"]["unit"]
    assert profile["surface_line_counts"]["kind"] == "not_observed"
    assert profile["surface_line_counts"]["reason"] == "numstat_unavailable"
    assert profile["surface_line_counts"].get("value") != 0


def test_project_rejects_unbound_tracker_lifecycle_benchmark(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    code = main(
        [
            "project",
            str(repo),
            "--tracker-export",
            str(PACK / "data" / "tracker_lifecycle_fixture.csv"),
            "--format",
            "md",
        ]
    )
    assert code == 2
    assert "not a target-bound subject export" in capsys.readouterr().err


def test_manifest_requires_denominator(tmp_path: Path) -> None:
    from tep_core.benchmark import validate_manifest
    from tep_core.secrets_guard import InputValidationError

    manifest = json.loads((PACK / "sources.json").read_text(encoding="utf-8"))
    del manifest["artifacts"][0]["denominator"]
    dest = tmp_path / "sources.json"
    dest.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        validate_manifest(dest)
    except InputValidationError as exc:
        assert "denominator" in str(exc)
        return
    raise AssertionError("missing denominator must fail")


def test_reference_manifest_from_other_cwd(tmp_path: Path, capsys, monkeypatch) -> None:
    actor = _actor_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "repo",
            str(actor),
            "--reference",
            "gharchive-2024-01-15-to-21-selected-repos",
            "--reference-manifest",
            str(PACK / "sources.json"),
            "--format",
            "json",
        ]
    )
    assert code == 0, capsys.readouterr().err
    payload = json.loads(capsys.readouterr().out)
    assert payload["reference"]["catalog"]["id"] == "gharchive-2024-01-15-to-21-selected-repos"


def test_unbound_archive_is_refused_before_event_window_comparison(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    code = main(
        [
            "project",
            str(repo),
            "--forge-export",
            str(PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson"),
            "--event-window",
            "2020-01-01",
            "2020-01-02",
            "--format",
            "json",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "not a target-bound subject export" in err


def test_unbound_archive_is_refused_without_event_window(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    code = main(
        [
            "project",
            str(repo),
            "--forge-export",
            str(PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson"),
            "--format",
            "json",
        ]
    )
    assert code == 2
    assert "not a target-bound subject export" in capsys.readouterr().err


def test_verify_replays_forge_tracker(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    tracker = _bound_tracker(repo, tmp_path / "tracker-v2.json")
    out = tmp_path / "out"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--tracker-export",
                str(tracker),
                "--format",
                "json",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(
        [
            "verify",
            str(out / "report.json"),
            "--repo",
            str(repo),
            "--tracker-export",
            str(tracker),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "VERIFIED" in captured.out


def test_verify_alignment_with_role_lens(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = tmp_path / "p.toml"
    _project_toml(project)
    out = tmp_path / "al"
    assert (
        main(
            [
                "align",
                "--repo",
                str(actor),
                "--identity",
                str(actor / ".tep" / "identity.toml"),
                "--actor",
                "candidate_001",
                "--project",
                str(project),
                "--role-lens",
                "backend",
                "--format",
                "json",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(
        [
            "verify",
            str(out / "alignment.json"),
            "--repo",
            str(actor),
            "--identity",
            str(actor / ".tep" / "identity.toml"),
            "--project",
            str(project),
            "--actor",
            "candidate_001",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "VERIFIED" in captured.out


def test_verify_reference_report(tmp_path: Path, capsys) -> None:
    repo = _actor_repo(tmp_path)
    out = tmp_path / "r"
    assert (
        main(
            [
                "repo",
                str(repo),
                "--reference",
                "numfocus-2022-to-2024",
                "--reference-manifest",
                str(PACK / "sources.json"),
                "--format",
                "json",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(["verify", str(out / "report.json"), "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "VERIFIED" in captured.out


def test_dirty_worktree_verify_does_not_destroy_files(tmp_path: Path, capsys) -> None:
    repo = _actor_repo(tmp_path)
    out = tmp_path / "r"
    assert main(["repo", str(repo), "--format", "json", "--out", str(out)]) == 0
    capsys.readouterr()
    extra = repo / "KEEP_ME.txt"
    extra.write_text("untouched\n", encoding="utf-8")
    code = main(["verify", str(out / "report.json"), "--repo", str(repo)])
    capsys.readouterr()
    assert extra.is_file()
    assert extra.read_text(encoding="utf-8") == "untouched\n"
    assert code in {0, 1, 2}


def test_verify_observed_project(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    out = tmp_path / "p"
    assert main(["project", str(repo), "--format", "json", "--out", str(out)]) == 0
    capsys.readouterr()
    code = main(["verify", str(out / "project.json"), "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "VERIFIED" in captured.out


def test_declared_only_project_is_not_false_verified_without_toml(tmp_path: Path, capsys) -> None:
    dest = tmp_path / "project.toml"
    assert main(["project", "--init", "--out", str(dest)]) == 0
    capsys.readouterr()
    out = tmp_path / "p"
    assert (
        main(["project", "--requirements", str(dest), "--format", "json", "--out", str(out)]) == 0
    )
    capsys.readouterr()
    payload = json.loads((out / "project.json").read_text(encoding="utf-8"))
    payload["observed"] = {"kind": "observed", "unclassified_count": 99}
    (out / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    code = main(
        ["verify", str(out / "project.json"), "--repo", str(_actor_repo(tmp_path, "other"))]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "CANNOT_VERIFY" in captured.out


def test_actor_report_has_no_other_actor_or_email(tmp_path: Path, capsys) -> None:
    repo = _actor_repo(tmp_path)
    commit(
        repo, email="b@example.com", date="2026-08-02", message="other", filename="src/api/other.py"
    )
    ident = repo / ".tep" / "identity.toml"
    ident.write_text(
        ident.read_text(encoding="utf-8")
        + '\n[[actors]]\ncanonical_id = "other_actor"\nemails = ["b@example.com"]\nattribution_state = "claimed"\n',
        encoding="utf-8",
    )
    assert main(["actor", "candidate_001", str(repo), "--format", "json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    blob = captured.out + captured.err
    assert "b@example.com" not in blob
    assert payload["identity"]["actor_count"] == 1
    assert "other_actor" not in json.dumps(payload.get("subject"))


def test_live_golden_not_claimed() -> None:
    import os

    import pytest

    conftest = Path(__file__).resolve().parent / "conftest.py"
    text = conftest.read_text(encoding="utf-8")
    assert 'os.environ.get("TEP_GOLDEN") == "1"' in text
    assert "skip" in text
    if os.environ.get("TEP_GOLDEN") == "1":
        pytest.skip("TEP_GOLDEN=1 opted in live golden; NOT_PROVEN claim does not apply")
    assert os.environ.get("TEP_GOLDEN") != "1"
