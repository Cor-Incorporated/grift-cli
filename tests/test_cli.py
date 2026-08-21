"""CLI smoke test."""

from __future__ import annotations

from pathlib import Path

import pytest

from tep_cli.__main__ import main

from git_fixture import commit, init_repo


def test_analyze_json(tmp_path: Path, capsys: object) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one")
    code = main(["analyze", str(repo), "--format", "json"])
    assert code == 0
    captured = capsys.readouterr()
    assert '"schema_version": "tep-report-v1"' in captured.out
    assert '"tool_name": "grift"' in captured.out
    assert '"method_name": "TEP"' in captured.out
    assert "pending_attribution" in captured.out
    assert '"path"' not in captured.out


def test_cli_prog_is_grift() -> None:
    from tep_cli.__main__ import build_parser

    assert build_parser().prog == "grift"


def test_include_local_path_flag(tmp_path: Path, capsys: object) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-02", message="one")
    code = main(["analyze", str(repo), "--format", "json", "--include-local-path"])
    assert code == 0
    captured = capsys.readouterr()
    assert str(repo.resolve()) in captured.out


def test_top_help_exits_zero_and_mentions_scope(capsys: object) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--scope" in out
    assert "詳細: README" in out


def test_analyze_help_exits_zero_and_mentions_scope(capsys: object) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["analyze", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--scope" in out
    assert "詳細: README" in out
