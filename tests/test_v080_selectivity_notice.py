"""v0.8.0 #2: a single-repo actor report and an alignment always say the repo
was chosen by the provider (norms §6), in JSON ``notices`` and in Markdown.

Boundaries covered (see PR body): declaration ↔ artifact (norms §6 text ↔
``notices`` output), the verifier itself (a report without the notice is
MISMATCH), and single repo ↔ collection (no doubled fixed sentences).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core.v2_constants import SELECTIVITY_NOTICE

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "checkout-api"
title = "Checkout API"

[requirements.surfaces]
required = ["backend"]

[requirements.verification]
required = ["unit"]

[requirements.inputs]
required = ["git"]
"""


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    for index in range(6):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"feat: a {index}",
            filename="src/app.py",
            name="Alice",
        )
    commit(
        repo,
        email="b@example.com",
        date="2026-08-02",
        message="feat: b",
        filename="src/other.py",
        name="Bob",
    )
    return repo


def _identity(tmp_path: Path) -> Path:
    path = tmp_path / "identity.toml"
    path.write_text(
        'schema_version = "identity-v1"\n\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    return path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(argv)
    return code, capsys.readouterr().out


def _align_args(repo: Path, identity: Path, project: Path, fmt: str) -> list[str]:
    return [
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
        fmt,
    ]


def _forbidden_vocab():
    spec = importlib.util.spec_from_file_location(
        "check_forbidden_vocab", ROOT / "scripts" / "check_forbidden_vocab.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notice_text_is_english_limitation_style_and_passes_vocab_check() -> None:
    assert SELECTIVITY_NOTICE.isascii(), "notice is aligned with the English limitation lines"
    assert SELECTIVITY_NOTICE.endswith(".")
    assert _forbidden_vocab().violations(SELECTIVITY_NOTICE) == []


def test_norms_section_6_declares_the_exact_notice_text() -> None:
    """Declaration ↔ artifact: the sentence norms §6 promises is the one emitted."""

    for path in ("docs/norms.md", "docs/en/norms.md"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert SELECTIVITY_NOTICE in text, f"{path} does not quote SELECTIVITY_NOTICE"


def test_actor_report_json_and_markdown_carry_selectivity_notice(tmp_path, capsys) -> None:
    repo = _repo(tmp_path)
    identity = _identity(tmp_path)
    for selection_args in ([], ["--identity", str(identity)]):
        code, out = _run(["actor", "alice", str(repo), *selection_args, "--format", "json"], capsys)
        assert code == 0
        payload = json.loads(out)
        assert payload["notices"].count(SELECTIVITY_NOTICE) == 1, payload["notices"]
        code, markdown = _run(
            ["actor", "alice", str(repo), *selection_args, "--format", "md"], capsys
        )
        assert code == 0
        assert markdown.count(SELECTIVITY_NOTICE) == 1


def test_alignment_json_and_markdown_carry_selectivity_notice(tmp_path, capsys) -> None:
    repo = _repo(tmp_path)
    identity = _identity(tmp_path)
    project = tmp_path / "project.toml"
    project.write_text(PROJECT_TOML, encoding="utf-8")
    code, out = _run(_align_args(repo, identity, project, "json"), capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["schema_version"] == "alignment-v1"
    assert payload["notices"].count(SELECTIVITY_NOTICE) == 1, payload["notices"]
    code, markdown = _run(_align_args(repo, identity, project, "md"), capsys)
    assert code == 0
    assert markdown.count(SELECTIVITY_NOTICE) == 1


def test_collection_artifacts_stay_out_of_scope(tmp_path, capsys) -> None:
    """Single repo ↔ collection: repo-kind report and actor-card-v1 carry no
    selectivity notice (v0.8.0 #2 scope is actor report-v2 and alignment-v1)."""

    repo = _repo(tmp_path)
    out_dir = tmp_path / "collection"
    assert main(["repo", str(repo), "--actors", "--format", "both", "--out", str(out_dir)]) == 0
    capsys.readouterr()
    notices = json.loads((out_dir / "repo-report.json").read_text(encoding="utf-8"))["notices"]
    assert SELECTIVITY_NOTICE not in notices, notices
    cards = sorted((out_dir / "actors").glob("*.json"))
    assert cards, "collection must write actor cards"
    for card in cards:
        card_notices = json.loads(card.read_text(encoding="utf-8")).get("notices") or []
        assert SELECTIVITY_NOTICE not in card_notices, (card.name, card_notices)


def test_verify_accepts_notice_and_rejects_report_saved_without_it(tmp_path, capsys) -> None:
    """Verifier itself: a 0.7.x-shaped report (no notice) must be MISMATCH."""

    repo = _repo(tmp_path)
    report_path = tmp_path / "actor.json"
    assert main(["actor", "alice", str(repo), "--format", "json", "--out", str(report_path)]) == 0
    capsys.readouterr()
    assert main(["verify", str(report_path), "--repo", str(repo)]) == 0
    assert "VERIFIED" in capsys.readouterr().out

    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["notices"] = [item for item in report["notices"] if item != SELECTIVITY_NOTICE]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert main(["verify", str(report_path), "--repo", str(repo)]) == 1
    output = capsys.readouterr().out
    assert "MISMATCH" in output
    assert "notices" in output


def test_verify_rejects_alignment_saved_without_notice(tmp_path, capsys) -> None:
    """Verifier itself, alignment path: a 0.7.x-shaped alignment is MISMATCH."""

    repo = _repo(tmp_path)
    identity = _identity(tmp_path)
    project = tmp_path / "project.toml"
    project.write_text(PROJECT_TOML, encoding="utf-8")
    align_path = tmp_path / "alignment.json"
    args = _align_args(repo, identity, project, "json")
    assert main([*args, "--out", str(align_path)]) == 0
    capsys.readouterr()
    verify = [
        "verify",
        str(align_path),
        "--repo",
        str(repo),
        "--identity",
        str(identity),
        "--project",
        str(project),
    ]
    assert main(verify) == 0
    assert "VERIFIED" in capsys.readouterr().out

    payload = json.loads(align_path.read_text(encoding="utf-8"))
    payload["notices"] = [item for item in payload["notices"] if item != SELECTIVITY_NOTICE]
    align_path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(verify) == 1
    output = capsys.readouterr().out
    assert "MISMATCH" in output
    assert "notices" in output
