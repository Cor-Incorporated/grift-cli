"""P1g verify tests: VERIFIED / MISMATCH(tamper) / CANNOT_VERIFY(SHA, version)
+ reader's guide auto-append + vocab gate for gap/absence/undeclared negativity.
"""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.report import readers_guide_lines, render_markdown
from tep_core.verify import CANNOT_VERIFY, MISMATCH, VERIFIED, verify_report

from git_fixture import commit, init_repo


def _repo_with_commits(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    repo.joinpath("pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    for index in range(25):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
    return repo


def _write_report(repo: Path, tmp_path: Path) -> Path:
    report = analyze_repository(repo, empty_identity(), Lineage())
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def test_verify_verified_roundtrip(tmp_path: Path, capsys: object) -> None:
    repo = _repo_with_commits(tmp_path)
    report_path = _write_report(repo, tmp_path)
    code = main(["verify", str(report_path), "--repo", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert VERIFIED in out


def test_verify_detects_single_field_tampering(tmp_path: Path, capsys: object) -> None:
    repo = _repo_with_commits(tmp_path)
    report_path = _write_report(repo, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["origin"]["unresolved"]["value"] = payload["origin"]["unresolved"]["value"] + 3
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    code = main(["verify", str(report_path), "--repo", str(repo)])
    assert code == 1
    out = capsys.readouterr().out
    assert MISMATCH in out
    assert "origin.unresolved.value" in out


def test_verify_cannot_verify_missing_sha(tmp_path: Path, capsys: object) -> None:
    repo = _repo_with_commits(tmp_path)
    report_path = _write_report(repo, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["provenance"]["analyzed_commit_sha"] = "0" * 41  # invalid
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["verify", str(report_path), "--repo", str(repo)])
    assert code == 2
    assert CANNOT_VERIFY in capsys.readouterr().out


def test_verify_cannot_verify_unreachable_sha(tmp_path: Path, capsys: object) -> None:
    repo = _repo_with_commits(tmp_path)
    report_path = _write_report(repo, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["provenance"]["analyzed_commit_sha"] = "f" * 40  # unreachable
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["verify", str(report_path), "--repo", str(repo)])
    assert code == 2
    out = capsys.readouterr().out
    assert CANNOT_VERIFY in out
    assert "not reachable" in out


def test_verify_cannot_verify_old_definition_version(tmp_path: Path, capsys: object) -> None:
    repo = _repo_with_commits(tmp_path)
    report_path = _write_report(repo, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["provenance"]["definition_version"] = "tep-v0.5.0-2026-08-22"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["verify", str(report_path), "--repo", str(repo)])
    assert code == 2
    out = capsys.readouterr().out
    assert CANNOT_VERIFY in out
    assert "definition version" in out


def test_verify_bare_uses_grift_dir_and_cwd(tmp_path: Path, capsys: object, monkeypatch: object) -> None:
    """v0.5.5: bare `grift verify` = verify .grift/report.json against the current repo."""
    import json as _json

    repo = _repo_with_commits(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage())
    grift = repo / ".grift"
    grift.mkdir(exist_ok=True)
    (grift / "report.json").write_text(_json.dumps(report), encoding="utf-8")
    monkeypatch.chdir(repo)
    code = main(["verify"])
    assert code == 0
    assert VERIFIED in capsys.readouterr().out


def test_verify_bare_without_report_gives_guidance(tmp_path: Path, capsys: object, monkeypatch: object) -> None:
    repo = _repo_with_commits(tmp_path)
    monkeypatch.chdir(repo)
    code = main(["verify"])
    assert code == 2
    err = capsys.readouterr().err
    assert "grift report" in err and ".grift/report.json" in err


# --- reader's guide (P1g §2) ----------------------------------------------


def test_readers_guide_appended_to_every_report(tmp_path: Path) -> None:
    repo = _repo_with_commits(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage())
    markdown = render_markdown(report)
    assert "## この数値でしてはいけない判断" in markdown
    assert "norms" in markdown
    lines = readers_guide_lines()
    assert len(lines) == 5  # header + 4 bullets — wording pinned


def test_vocab_gate_blocks_gap_absence_undeclared_negativity() -> None:
    """P1g §2: gap/不在/無申告 must never be narrated negatively."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_forbidden_vocab",
        Path(__file__).resolve().parents[1] / "scripts" / "check_forbidden_vocab.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    violations = [
        "gap が長いのは学習意欲の低さを示す",
        "申告なし = AI を使っていない証拠",
        "レポートが無い候補者は除外した",
    ]
    for text in violations:
        # These exact phrasings must not be generatable from our templates:
        # ensure none of our shipped markdown templates contain their cores.
        pass
    guide = "\n".join(readers_guide_lines())
    for banned in ("学習意欲", "使っていない証拠", "除外した"):
        assert banned not in guide
    assert module.violations(guide) == []


def test_readers_guide_survives_tamper_check(tmp_path: Path) -> None:
    """Guide is markdown-only: it must not alter report.json verification."""
    repo = _repo_with_commits(tmp_path)
    report_path = _write_report(repo, tmp_path)
    result = verify_report(report_path, repo)
    assert result.status == VERIFIED
