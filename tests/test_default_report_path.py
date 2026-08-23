"""Bare `grift report` / `grift contribute`: default-path search + guidance.

代表 UX feedback (2026-08-23): invoking the subcommands without a path used
to hard-error on argparse / file-not-found without telling the user what to
do first. Now they search ./out, .grift-out, ./ and, when nothing is found,
exit 2 with actionable guidance.
"""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main

from git_fixture import commit, init_repo


def _make_report_json(dir_path: Path) -> Path:
    from tep_core.analyze import analyze_repository
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    repo = init_repo(dir_path / "repo")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    for index in range(12):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    target = dir_path / "out" / "report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return target


def test_report_bare_ignores_stale_out_and_reanalyzes(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    """Critical UX (提唱者 2026-08-23): bare `grift report` with an EXISTING
    ./out/report.json must RE-ANALYZE the current HEAD, not re-render the
    stale file."""
    import json as _json
    import subprocess as _sp

    from git_fixture import commit as _commit, init_repo as _init

    repo = _init(tmp_path / "repo")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    for index in range(5):
        _commit(repo, email="a@example.com", date="2026-01-05", message=f"feat: {index}")
    monkeypatch.chdir(repo)
    assert main(["report"]) == 0
    first_sha = _json.loads((repo / "out" / "report.json").read_text())["provenance"][
        "analyzed_commit_sha"
    ]
    _commit(repo, email="a@example.com", date="2026-01-06", message="feat: more")
    assert main(["report"]) == 0
    second_sha = _json.loads((repo / "out" / "report.json").read_text())["provenance"][
        "analyzed_commit_sha"
    ]
    assert first_sha != second_sha, "bare report must re-analyze, not re-render stale output"
    head = _sp.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=repo
    ).stdout.strip()
    assert second_sha == head
    assert "## Shared block" in capsys.readouterr().out


def test_report_with_explicit_path_still_re_renders(tmp_path: Path, capsys: object) -> None:
    """Explicit path keeps the re-render (no re-analysis) contract."""
    _make_report_json(tmp_path)
    code = main(["report", str(tmp_path / "out" / "report.json")])
    assert code == 0
    assert "## Shared block" in capsys.readouterr().out


def test_report_bare_without_prior_output_analyzes_cwd(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    """UX: bare `grift report` in a git repo with no ./out → analyze now and
    write ./out/report.{json,md}."""
    from git_fixture import commit as _commit, init_repo as _init

    repo = _init(tmp_path / "repo")
    for index in range(3):
        _commit(repo, email="a@example.com", date="2026-01-05", message=f"feat: {index}")
    monkeypatch.chdir(repo)
    code = main(["report"])
    assert code == 0
    out = capsys.readouterr()
    assert "## Shared block" in out.out
    assert (repo / "out" / "report.json").is_file()
    assert (repo / "out" / "report.md").is_file()


def test_report_bare_outside_git_repo_refused(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["report"])
    assert code == 2
    assert "not a git repository" in capsys.readouterr().err


def test_contribute_bare_without_report_gives_guidance(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["contribute"])
    assert code == 2
    err = capsys.readouterr().err
    assert "grift report" in err  # guidance points to the one-step entry


def test_contribute_bare_uses_out_default(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    # repo-scope report in ./out → bare contribute reaches the F-C1 gate
    _make_report_json(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(["contribute", "--out", str(tmp_path / "c.json")])  # non-TTY, no --yes
    assert code == 2  # F-C1 refusal path (not path-resolution error)
    err = capsys.readouterr().err
    assert "公開リポジトリに載ります" in err
    assert "grift analyze . --out ./out" not in err  # found the file; failed on consent instead
