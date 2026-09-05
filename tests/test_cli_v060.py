"""v0.6.0 subject-first CLI contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_cli.__main__ import build_parser, main
from tep_core.v2_constants import ACTOR_ADMIN_NOTICE, ALIGNMENT_NOTICE, FORBIDDEN_VERDICT_KEYS

from git_fixture import commit, git, init_repo
from tep_core.gitutil import rev_parse

ROOT = Path(__file__).resolve().parents[1]


def _identity(path: Path, *, patterns: bool = False, extra_actor: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = 'schema_version = "identity-v1"\n\n'
    if patterns:
        body += '[tenant]\nemail_patterns = ["@example\\\\.com$"]\n\n'
    body += (
        '[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n'
    )
    if extra_actor:
        body += (
            '\n[[actors]]\ncanonical_id = "other_actor"\n'
            'emails = ["b@example.com"]\nattribution_state = "claimed"\n'
        )
    path.write_text(body, encoding="utf-8")
    return path


def _repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = init_repo(tmp_path / name)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "api").mkdir(parents=True)
    for index in range(22):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"feat: {index}",
            filename="src/api/app.py",
        )
        if index % 2 == 0:
            commit(
                repo,
                email="a@example.com",
                date="2026-08-01",
                message=f"test: {index}",
                filename="tests/test_app.py",
            )
    commit(
        repo,
        email="b@example.com",
        date="2026-08-02",
        message="feat: other",
        filename="src/api/other.py",
    )
    _identity(repo / ".tep" / "identity.toml", extra_actor=True)
    git(repo, "add", ".tep/identity.toml")
    git(repo, "commit", "-qm", "chore: record fixture identity")
    return repo


def test_top_help_lists_subject_commands_and_norms(capsys: object) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in ("repo", "actor", "project", "align"):
        assert name in out
    assert "not a scoring" in out.lower() or "norms" in out.lower()
    assert "repo" in out.lower()


def test_repo_emits_report_v2_repo_scope(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    code = main(["repo", str(repo), "--format", "json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "report-v2"
    assert payload["subject"]["kind"] == "repo"
    assert payload["provenance"]["analysis_scope"] == "repo"
    assert payload["subject"]["selection"] == "repo_all_human"
    assert not (repo / ".grift").exists()


def test_actor_selects_one_canonical_id(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    code = main(
        [
            "actor",
            "candidate_001",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--format",
            "json",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "report-v2"
    assert payload["subject"]["kind"] == "actor"
    assert payload["subject"]["canonical_id"] == "candidate_001"
    assert payload["provenance"]["analysis_scope"] == "tenant"
    assert "interpretation" not in payload
    assert ACTOR_ADMIN_NOTICE in captured.err
    assert payload["identity"]["actor_count"] == 1
    assert "b@example.com" not in captured.out
    assert not (repo / ".grift").exists()


def test_unknown_actor_exit_2_no_file(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "out" / "actor-report.json"
    code = main(
        [
            "actor",
            "missing_id",
            str(repo),
            "--format",
            "json",
            "--out",
            str(out),
        ]
    )
    assert code == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "candidate_001" in err
    assert "@" not in err


def test_pattern_identity_refused(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    ident = tmp_path / "pattern.toml"
    _identity(ident, patterns=True)
    code = main(["actor", "candidate_001", str(repo), "--identity", str(ident), "--format", "json"])
    assert code == 2
    assert "email_patterns" in capsys.readouterr().err


def test_project_init_and_requirements_json(tmp_path: Path, capsys: object) -> None:
    dest = tmp_path / "project.toml"
    assert main(["project", "--init", "--out", str(dest)]) == 0
    text = dest.read_text(encoding="utf-8")
    assert 'schema_version = "tep-project-v1"' in text
    assigned = [
        line
        for line in text.splitlines()
        if "active_days_180d_min" in line and not line.strip().startswith("#")
    ]
    assert assigned == []
    code = main(["project", "--requirements", str(dest), "--format", "json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "project-v1"
    assert payload["declared"]["change_rhythm"]["active_days_180d_min"]["kind"] == "not_declared"
    assert payload["observed"]["kind"] == "not_observed"
    assert "@" not in json.dumps(payload)


def test_project_init_refuses_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "project.toml"
    dest.write_text("already\n", encoding="utf-8")
    assert main(["project", "--init", "--out", str(dest)]) == 2
    assert dest.read_text(encoding="utf-8") == "already\n"


def test_align_axes_without_verdict_keys(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    project = tmp_path / "project.toml"
    project.write_text(
        """schema_version = "tep-project-v1"
project_id = "checkout-api"
title = "Checkout API"

[requirements.change_rhythm]
active_days_180d_min = 1
median_gap_days_max = 14
p90_gap_days_max = 60

[requirements.surfaces]
required = ["backend"]

[requirements.verification]
required = ["unit"]

[requirements.inputs]
required = ["git"]
""",
        encoding="utf-8",
    )
    code = main(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "candidate_001",
            "--project",
            str(project),
            "--format",
            "json",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "alignment-v1"
    assert payload["axes"]
    for key in FORBIDDEN_VERDICT_KEYS:
        assert f'"{key}"' not in json.dumps(payload)
    assert "総合" not in captured.out
    assert ALIGNMENT_NOTICE.split("。")[0] in captured.out


def test_format_json_stdout_is_one_object(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    captured = capsys.readouterr()
    json.loads(captured.out)
    assert captured.out.strip().startswith("{")
    assert captured.out.count("{") >= 1


def test_out_directory_fixed_names_and_stdout(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "artifacts"
    assert main(["repo", str(repo), "--format", "json", "--out", str(dest)]) == 0
    assert (dest / "report.json").is_file()
    json.loads(capsys.readouterr().out)
    assert (dest / "report.md").is_file() is False


def test_actor_help_mentions_optional_identity(capsys: object) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["actor", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "optional" in out.lower()
    assert "--all" in out and "--top" in out


def test_actor_export_is_refused(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    code = main(
        [
            "actor",
            "candidate_001",
            str(repo),
            "--export",
            str(tmp_path / "export"),
            "--format",
            "json",
        ]
    )
    assert code == 2
    assert "export" in capsys.readouterr().err.lower()
    assert not (tmp_path / "export").exists()


def test_markdown_has_no_raw_dict_and_shows_lens(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert (
        main(["actor", "candidate_001", str(repo), "--role-lens", "backend", "--format", "md"]) == 0
    )
    text = capsys.readouterr().out
    assert "{'kind'" not in text
    assert "表示プリセット: `backend`" in text
    assert "職種" in text
    assert "このレポートは誰・何を対象にしたか" in text
    assert "数値の読み方" in text
    assert "採用の合否" in text


def test_parser_does_not_share_analyze_defaults() -> None:
    parser = build_parser()
    repo_help = parser._subparsers._group_actions[0].choices["repo"].format_help()
    analyze_help = parser._subparsers._group_actions[0].choices["analyze"].format_help()
    assert "default: md" in repo_help
    assert "default: both" in analyze_help


def test_project_markdown_lists_coordination_without_repr(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    git(repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    project = tmp_path / "project.toml"
    project.write_text(
        """schema_version = "tep-project-v1"
project_id = "checkout-api"

[requirements.surfaces]
required = ["backend", "frontend"]
""",
        encoding="utf-8",
    )
    forge = tmp_path / "forge.json"
    forge.write_text(
        json.dumps(
            {
                "schema_version": "tep-forge-export-v2",
                "binding": {
                    "provider": "github",
                    "host": "github.com",
                    "project_id": "R_repo",
                    "project_path": "acme/repo",
                    "target_oid": {"algorithm": "sha1", "value": rev_parse(repo)},
                    "window": {
                        "start": "2026-08-01T00:00:00Z",
                        "end": "2026-09-01T00:00:00Z",
                    },
                    "coverage": {
                        "status": "complete",
                        "observed": 1,
                        "expected": 1,
                        "missing": 0,
                        "unit": "events",
                    },
                },
                "events": [
                    {
                        "event_id": "a",
                        "kind": "pull_request_review",
                        "timestamp": "2026-08-02T00:00:00Z",
                        "actor_canonical_id": "candidate_001",
                        "pr_number": 1,
                        "commit_sha": rev_parse(repo),
                        "project_id": "R_repo",
                        "project_path": "acme/repo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "project",
            str(repo),
            "--requirements",
            str(project),
            "--forge-export",
            str(forge),
            "--format",
            "md",
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "{'kind'" not in text
    assert "['backend'" not in text
    assert "backend, frontend" in text
    assert "調整の観測" in text
    assert "review" in text.lower() or "レビュー" in text or "forge" in text.lower()


def test_project_observation_date_without_as_of(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["project", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    date = payload["provenance"]["observation_date"]
    assert date and len(date) == 10
    assert payload["provenance"]["window_basis"] == "legacy_head_date"
    review = payload["observed"]["coordination_profile"]["review"]
    assert review["kind"] == "not_observed"
