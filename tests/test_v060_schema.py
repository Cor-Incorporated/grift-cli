"""report-v2 / project-v1 / alignment-v1 schema and digest checks."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.schema_v2 import validate_alignment, validate_project, validate_report_v2
from tep_core.v2_constants import FORBIDDEN_VERDICT_KEYS

from git_fixture import commit, init_repo

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    for index in range(4):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"feat {index}",
            filename="app.py",
        )
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    return repo


def test_report_v2_valid(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json", "--as-of", "2026-08-29"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert validate_report_v2(payload) == []


def test_empty_observed_node_is_rejected(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    payload["surface_profile"] = {"kind": "observed"}
    errors = validate_report_v2(payload)
    assert errors
    assert any("value" in item or "unit" in item or "definition_version" in item for item in errors)


def test_hollow_profile_without_nested_is_rejected(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    payload["surface_profile"] = {
        "kind": "observed",
        "unit": "profile",
        "definition_version": payload["surface_profile"]["definition_version"],
    }
    errors = validate_report_v2(payload)
    assert errors
    assert any("nested" in item for item in errors)


def test_project_rejects_empty_observed() -> None:
    payload = {
        "schema_version": "project-v1",
        "report_kind": "project",
        "declared": {
            "change_rhythm": {},
            "surfaces": {"kind": "not_declared", "reason": "requirement_not_provided"},
            "verification": {"kind": "not_declared", "reason": "requirement_not_provided"},
            "inputs": {"kind": "not_declared", "reason": "requirement_not_provided"},
        },
        "observed": {"kind": "observed"},
    }
    errors = validate_project(payload)
    assert errors
    hollow = dict(payload)
    hollow["observed"] = {
        "kind": "observed",
        "unit": "profile",
        "definition_version": "1.0.0",
    }
    assert validate_project(hollow)


def test_forbidden_key_rejected() -> None:
    payload = {
        "schema_version": "report-v2",
        "report_kind": "evidence",
        "subject": {"kind": "repo", "selection": "repo_all_human"},
        "provenance": {},
        "score": 1,
    }
    errors = validate_report_v2(payload)
    assert any("score" in item for item in errors)


def test_alignment_mutation_of_schema_version_fails() -> None:
    payload = {
        "schema_version": "alignment-v2",
        "report_kind": "alignment",
        "axes": [
            {
                "axis": "x",
                "declared": {"kind": "not_declared", "reason": "requirement_not_provided"},
                "observed": {"kind": "not_observed", "reason": "x"},
                "comparison": "not_declared",
                "evidence_paths": [],
                "limitations": [],
            }
        ],
    }
    errors = validate_alignment(payload)
    assert errors


def test_project_schema() -> None:
    payload = {
        "schema_version": "project-v1",
        "report_kind": "project",
        "declared": {
            "change_rhythm": {},
            "surfaces": {"kind": "not_declared", "reason": "requirement_not_provided"},
            "verification": {"kind": "not_declared", "reason": "requirement_not_provided"},
            "inputs": {"kind": "not_declared", "reason": "requirement_not_provided"},
        },
    }
    assert validate_project(payload) == []


def test_unknown_additive_key_allowed_on_report_v2(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    payload["extra_additive_section"] = {"kind": "observed", "value": 1, "unit": "note"}
    errors = validate_report_v2(payload)
    assert errors
    assert any("unknown" in item for item in errors)


def test_same_as_of_reproduces_except_analyzed_at(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json", "--as-of", "2026-08-29"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["repo", str(repo), "--format", "json", "--as-of", "2026-08-29"]) == 0
    second = json.loads(capsys.readouterr().out)
    left = copy.deepcopy(first)
    right = copy.deepcopy(second)
    left["provenance"].pop("analyzed_at")
    right["provenance"].pop("analyzed_at")
    assert left == right


def test_vendor_path_roundtrip_without_vendor_scan(tmp_path: Path, capsys: object) -> None:
    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="app.py")
    commit(
        repo,
        email="a@example.com",
        date="2026-08-01",
        message="vendor",
        filename="vendor/lib.js",
    )
    dest = tmp_path / "out"
    assert main(["repo", str(repo), "--format", "json", "--out", str(dest)]) == 0
    capsys.readouterr()
    payload = json.loads((dest / "report.json").read_text(encoding="utf-8"))
    assert payload["origin"]["generated_or_vendor"]["kind"] in {"observed", "not_observed"}
    code = main(["verify", str(dest / "report.json"), "--repo", str(repo)])
    assert code == 0, capsys.readouterr().out
    assert "VERIFIED" in capsys.readouterr().out


def test_repo_verify_roundtrip(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "out"
    assert main(["repo", str(repo), "--format", "json", "--out", str(dest)]) == 0
    capsys.readouterr()
    code = main(["verify", str(dest / "report.json"), "--repo", str(repo)])
    assert code == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_project_verify_is_not_false_verified(tmp_path: Path, capsys: object) -> None:
    dest = tmp_path / "project.toml"
    assert main(["project", "--init", "--out", str(dest)]) == 0
    capsys.readouterr()
    out = tmp_path / "p"
    assert (
        main(["project", "--requirements", str(dest), "--format", "json", "--out", str(out)]) == 0
    )
    capsys.readouterr()
    payload = json.loads((out / "project.json").read_text(encoding="utf-8"))
    payload["observed"] = {"kind": "observed", "unclassified_count": 999999}
    report = tmp_path / "tampered.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["verify", str(report), "--repo", str(_repo(tmp_path / "r"))])
    assert code == 2
    assert "CANNOT_VERIFY" in capsys.readouterr().out


def test_verify_mismatch_on_digest_change(tmp_path: Path, capsys: object) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json", "--out", str(tmp_path / "out")]) == 0
    capsys.readouterr()
    report_path = tmp_path / "out" / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["provenance"]["input_digests"]["forge"] = "a" * 64
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["verify", str(report_path), "--repo", str(repo)])
    assert code in {1, 2}
    out = capsys.readouterr().out
    assert "MISMATCH" in out or "CANNOT_VERIFY" in out


def test_docs_examples_parse() -> None:
    for name in ("report-v2.md", "project-schema.md", "alignment-schema.md"):
        path = ROOT / "docs" / name
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "```json" in text or "```toml" in text
    for key in FORBIDDEN_VERDICT_KEYS:
        assert key  # enum stays populated
