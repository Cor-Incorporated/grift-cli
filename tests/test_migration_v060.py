"""v0.6.0 must not change v0.5.9 verb / schema contracts."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.contribute import build_contribution

from git_fixture import commit, init_repo
from test_verb_semantics import (
    test_d1_bare_analyze_stdout_only_no_grift_dir,
    test_d2_bare_report_records_grift_dir_repo_scope,
    test_d3a_report_scope_tenant,
    test_d3b_bare_analyze_defaults_to_repo_scope,
    test_d3b_explicit_path_still_defaults_tenant,
    test_help_text_has_no_stale_out_dir,
)


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests" / "t.py").write_text("def test_o():\n    pass\n", encoding="utf-8")
    for index in range(24):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
    return repo


def test_legacy_analyze_still_report_v1(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["analyze", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "report-v1"
    assert payload["provenance"]["analysis_scope"] == "tenant"


def test_export_omitted_scope_is_resolved(tmp_path: Path, capsys: object, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    dest = tmp_path / "export"
    assert main(["analyze", "--format", "json", "--export", str(dest)]) == 0
    meta = json.loads((dest / "export-meta.json").read_text(encoding="utf-8"))
    assert meta["analysis_scope"] == "repo"
    assert str(meta["analysis_scope"]) != "None"


def test_contribute_accepts_report_v2_repo_masked(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "r"
    assert main(["repo", str(repo), "--format", "json", "--out", str(out)]) == 0
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    key = tmp_path / "study.key"
    key.write_bytes(bytes(range(32)))
    key.chmod(0o600)
    payload = build_contribution(
        report,
        privacy="masked",
        door="controlled",
        key_file=key,
        controlled_context={
            "controller": "research-controller-1",
            "authority": "repository-owner-authorization",
            "consent": "recorded-explicit-consent",
            "study_id": "study-2026-01",
            "key_id": "key-2026-01",
            "epoch": "2026-01",
            "retention": "until-2027-08-31",
            "withdrawal": "contact-controller-before-publication",
            "access_class": "named-research-team",
        },
        controlled_sidecar=tmp_path / "sidecar.json",
    )
    assert payload["contribution_schema"] == "tep-contribution-v2"
    assert payload["privacy_profile"] == "masked"


def test_contribute_refuses_report_v2_actor(tmp_path: Path) -> None:
    report = {
        "schema_version": "report-v2",
        "subject": {"kind": "actor", "canonical_id": "candidate_001"},
        "provenance": {"analysis_scope": "tenant"},
    }
    try:
        build_contribution(report)
    except ValueError as exc:
        assert "report-v1" in str(exc) or "actor" in str(exc)
    else:
        raise AssertionError("contribute must refuse report-v2 actor")


def test_contribute_refuses_alignment(tmp_path: Path) -> None:
    report = {
        "schema_version": "alignment-v1",
        "provenance": {"analysis_scope": "tenant"},
    }
    try:
        build_contribution(report)
    except ValueError as exc:
        assert "alignment" in str(exc) or "report-v1" in str(exc)
    else:
        raise AssertionError("contribute must refuse alignment-v1")


def test_verb_semantics_still_imported() -> None:
    assert callable(test_d1_bare_analyze_stdout_only_no_grift_dir)
    assert callable(test_d2_bare_report_records_grift_dir_repo_scope)
    assert callable(test_d3a_report_scope_tenant)
    assert callable(test_d3b_bare_analyze_defaults_to_repo_scope)
    assert callable(test_d3b_explicit_path_still_defaults_tenant)
    assert callable(test_help_text_has_no_stale_out_dir)
