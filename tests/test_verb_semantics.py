"""v0.5.6 verb semantics (D-1/D-2/D-3 fixes): analyze=display, report=record.

Falsifiable pins:
- bare `grift analyze` prints to stdout and does NOT create .grift/ (D-1)
- bare `grift analyze` uses repo scope (D-3b)
- bare `grift report` writes .grift/report.{json,md} with scope=repo (D-2)
- `grift report --scope tenant` records a tenant-scope report (D-3a)
- help text pins (no stale ./out mention)
"""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import build_parser, main

from git_fixture import commit, init_repo


def _repo_with_tests(tmp_path: Path, name: str = "repo") -> Path:
    repo = init_repo(tmp_path / name)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "t.py").write_text("def test_o():\n    pass\n", encoding="utf-8")
    (repo / ".tep").mkdir()
    (repo / ".tep" / "identity.toml").write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    for index in range(24):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
        if index % 2 == 0:
            commit(
                repo,
                email="a@example.com",
                date="2026-01-05",
                message=f"test: {index}",
                filename="tests/t.py",
            )
    return repo


def test_d1_bare_analyze_stdout_only_no_grift_dir(tmp_path, capsys, monkeypatch):
    """D-1: bare analyze = display. Prints to stdout, never creates .grift/."""
    repo = _repo_with_tests(tmp_path)
    monkeypatch.chdir(repo)
    code = main(["analyze"])
    assert code == 0
    out = capsys.readouterr()
    assert "# TEP analysis" in out.out  # markdown on stdout
    assert not (repo / ".grift").exists(), "analyze must NOT create .grift/ (that is report's job)"


def test_d3b_bare_analyze_defaults_to_repo_scope(tmp_path, capsys, monkeypatch):
    """D-3b: bare analyze default scope = repo (deciles may appear)."""
    repo = _repo_with_tests(tmp_path)
    monkeypatch.chdir(repo)
    code = main(["analyze", "--format", "json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provenance"]["analysis_scope"] == "repo"


def test_d3b_explicit_path_still_defaults_tenant(tmp_path, capsys):
    """Back-compat: explicit-path invocation keeps the tenant default."""
    repo = _repo_with_tests(tmp_path, "explicit")
    code = main(["analyze", str(repo), "--format", "json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provenance"]["analysis_scope"] == "tenant"


def test_d2_bare_report_records_grift_dir_repo_scope(tmp_path, capsys, monkeypatch):
    """D-2: bare report = record. Writes .grift/report.{json,md} with repo scope."""
    repo = _repo_with_tests(tmp_path)
    monkeypatch.chdir(repo)
    code = main(["report"])
    assert code == 0
    payload = json.loads((repo / ".grift" / "report.json").read_text(encoding="utf-8"))
    assert payload["provenance"]["analysis_scope"] == "repo"
    assert (repo / ".grift" / "report.md").is_file()


def test_d3a_report_scope_tenant(tmp_path, capsys, monkeypatch):
    """D-3a: report --scope tenant records a tenant-scope report."""
    repo = _repo_with_tests(tmp_path)
    monkeypatch.chdir(repo)
    code = main(["report", "--scope", "tenant"])
    assert code == 0
    payload = json.loads((repo / ".grift" / "report.json").read_text(encoding="utf-8"))
    assert payload["provenance"]["analysis_scope"] == "tenant"
    assert payload["identity"]["actor_count"] == 1


def test_help_text_has_no_stale_out_dir(tmp_path):
    """D-2 doc pin: help mentions .grift/, never the stale './out' default."""
    parser = build_parser()
    report_help = parser._subparsers._group_actions[0].choices["report"].format_help()
    analyze_help = parser._subparsers._group_actions[0].choices["analyze"].format_help()
    assert ".grift/" in report_help
    collapsed = " ".join(report_help.split())
    assert "default: analyze the current repo into .grift/" in collapsed
    assert "./out" not in collapsed and "./out" not in " ".join(analyze_help.split())
