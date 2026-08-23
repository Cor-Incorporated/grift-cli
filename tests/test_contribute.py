"""grift contribute tests: payload rules (ruling §2-3) + public-disclosure
confirmation + no-transmission rail."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.analyze import analyze_repository
from tep_core.contribute import (
    CONFIRMATION_TEXT,
    CONTRIBUTE_PURPOSE,
    build_contribution,
)
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo


def _repo_report(tmp_path: Path, *, scope: str = "repo") -> dict:
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
    return analyze_repository(repo, empty_identity(), Lineage(), scope=scope)


def test_payload_contents_repo_scope_only(tmp_path: Path) -> None:
    report = _repo_report(tmp_path)
    payload = build_contribution(report)
    assert payload["contribution_schema"] == "tep-contribution-v1"
    assert payload["purpose"] == CONTRIBUTE_PURPOSE
    text = json.dumps(payload, ensure_ascii=False)
    # Allowed: repo aggregates + context + definition versions
    assert "test_cochange" in text and "origin" in text
    assert payload["context_profile"]["collaboration_class"]["value"] == "solo"
    assert payload["provenance"]["definition_version"] == report["provenance"]["definition_version"]


def test_payload_excludes_private_layers(tmp_path: Path) -> None:
    report = _repo_report(tmp_path)
    payload = build_contribution(report)
    text = json.dumps(payload, ensure_ascii=False)
    assert "@" not in text, "no emails ever"
    for banned in ("canonical_id", '"actor"', '"emails"', '"path"'):
        assert banned not in text, f"payload must not carry {banned}"
    assert "identity" not in payload
    assert "repository" not in payload  # repo name excluded by default
    assert "activity" not in payload["metrics"], "identity-derived activity is tenant-private"


def test_tenant_scope_report_rejected(tmp_path: Path) -> None:
    report = _repo_report(tmp_path, scope="tenant")
    try:
        build_contribution(report)
    except ValueError as exc:
        assert "repo-scope" in str(exc)
    else:
        raise AssertionError("tenant-scope reports must be rejected")


def test_context_profile_slimmed_but_scale_dropped(tmp_path: Path) -> None:
    """scale carries first/last commit dates + dir names — a quasi-fingerprint.
    Ruling §2-3: repo 名/パスを含めない。We keep class-level fields only."""
    report = _repo_report(tmp_path)
    payload = build_contribution(report)
    ctx = payload["context_profile"]
    assert "scale" not in ctx
    assert set(ctx) <= {
        "kind",
        "definition_version",
        "analysis_scope",
        "resolved_human_actors",
        "top_actor_share",
        "collaboration_class",
        "pr_flow_share",
        "repo_age_days",
        "lifecycle_stage",
        "conventional_commit_share",
        "language_composition",
        "test_file_ratio",
        "docs_share",
        "dependency_manifests",
        "monorepo_markers",
        "issue_link_density",
        "release_cadence",
        "actor_turnover",
    }


def test_confirmation_mentions_public_disclosure() -> None:
    assert "公開コーパスに載ります" in CONFIRMATION_TEXT
    assert "何も送信しません" in CONFIRMATION_TEXT
    assert CONTRIBUTE_PURPOSE in CONFIRMATION_TEXT
    assert "repo 名は含まれません" in CONFIRMATION_TEXT
    assert "推測されるリスクはゼロではありません" in CONFIRMATION_TEXT
    assert "二枚扉" in CONFIRMATION_TEXT and "非公開ドア" in CONFIRMATION_TEXT


def test_cli_contribute_writes_payload_and_never_silent(tmp_path: Path, capsys: object) -> None:
    report = _repo_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "contribution.json"
    code = main(["contribute", str(path), "--out", str(out), "--yes"])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["contribution_schema"] == "tep-contribution-v1"
    err = capsys.readouterr().err
    assert "nothing was sent" in err


def test_cli_contribute_rejects_tenant_report(tmp_path: Path, capsys: object) -> None:
    report = _repo_report(tmp_path, scope="tenant")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    code = main(["contribute", str(path), "--yes"])
    assert code == 2
    assert "repo-scope" in capsys.readouterr().err


# --- F-C1 (addendum17): consent gate enforced on every path ----------------


def test_f_c1_non_tty_without_yes_is_refused(tmp_path: Path, capsys: object) -> None:
    """Falsifiable: non-TTY + no --yes used to write the payload silently.
    It must now exit 2 with the public-disclosure text on stderr and write
    nothing."""
    report = _repo_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "contribution.json"
    code = main(["contribute", str(path), "--out", str(out)])
    assert code == 2, "non-TTY without --yes must be refused"
    captured = capsys.readouterr()
    assert "公開コーパスに載ります" in captured.err, "disclosure must be shown on stderr"
    assert "推測されるリスクはゼロではありません" in captured.err, "inference-risk disclosure required"
    assert "--yes" in captured.err
    assert not out.exists(), "nothing may be written when refused"


def test_f_c1_yes_still_discloses_before_writing(tmp_path: Path, capsys: object) -> None:
    """Falsifiable: --yes used to write without showing the disclosure.
    It must now print disclosure + payload summary (stderr) and full payload
    (stdout) BEFORE writing — consent leaves a trace."""
    report = _repo_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "contribution.json"
    code = main(["contribute", str(path), "--out", str(out), "--yes"])
    assert code == 0
    captured = capsys.readouterr()
    assert "公開コーパスに載ります" in captured.err, "disclosure on stderr even with --yes"
    assert "推測されるリスクはゼロではありません" in captured.err
    assert "payload summary:" in captured.err
    assert "definition=" in captured.err
    assert "=== contribution payload (full) ===" in captured.out, "full payload on stdout"
    assert out.exists()
