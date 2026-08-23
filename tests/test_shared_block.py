"""P1a: shared block + report composition + snapshot (fixture-based)."""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown, shared_block

from git_fixture import commit, init_repo


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "t.py").write_text("def test_o():\n    pass\n", encoding="utf-8")
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


def test_shared_block_shape_and_limits(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    block = shared_block(report)
    assert 3 <= len(block) <= 5
    joined = "\n".join(block)
    assert str(repo.resolve()) not in joined  # no absolute paths
    assert "ratio" in joined and "commits" in joined
    assert report["provenance"]["definition_version"] in joined
    assert "norms" in joined  # reader's-guide one-liner


def test_shared_block_first_section_of_markdown(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage())
    markdown = render_markdown(report)
    assert markdown.index("## Shared block") < markdown.index("## Provenance")
    # composition order (P1a-1): Provenance before evidence before observations
    assert markdown.index("## Provenance") < markdown.index("## Test co-change")
    assert markdown.index("## Test co-change") < markdown.index("## Rework")


def test_insufficient_population_not_narrated(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "tiny")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "t"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
    for index in range(8):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
    report = analyze_repository(repo, empty_identity(), Lineage())
    block = "\n".join(shared_block(report))
    assert "not narrated" in block or "test co-change" not in block
    # 8 commits < 20 or pending attribution: either way the raw rate is absent
    # (strip the tool/version lines first — they legitimately contain 0.5.x)
    body = "\n".join(line for line in block.splitlines() if not line.startswith("- tool:"))
    assert "0." not in body.split("読み方")[0]


def test_report_subcommand_re_renders_without_analysis(tmp_path: Path, capsys: object) -> None:
    from tep_cli.__main__ import main

    repo = _repo(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    report_path = tmp_path / "report.json"
    report_path.write_text(
        __import__("json").dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    code = main(["report", str(report_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "## Shared block" in out
    # no re-analysis: tampering a value must surface verbatim in the md
    report["origin"]["unresolved"]["value"] = 424242
    report_path.write_text(__import__("json").dumps(report), encoding="utf-8")
    main(["report", str(report_path)])
    assert "424242" in capsys.readouterr().out


def test_vocab_gate_on_shared_block(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_forbidden_vocab",
        Path(__file__).resolve().parents[1] / "scripts" / "check_forbidden_vocab.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = _repo(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage())
    assert module.violations("\n".join(shared_block(report))) == []
    assert module.violations(render_markdown(report)) == []
