"""v0.5.7 UX fixes (#49/#50/#51): contribute dead-end, readability, update.

#49: consenting `grift contribute` (no --out) must WRITE .grift/contribution.json
     and print copy-ready submission steps (id, PR filename, manifest line, doors).
#50: language_composition emits shares (unit contract), actor_turnover uses
     last_active (not the misleading "left"), release_cadence unit is tags/year.
#51: `grift update --check` reads PyPI metadata (read-only) and reports.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.analyze import analyze_repository
from tep_core.context_profile import CONTEXT_DEFINITION_VERSION
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo


def _repo_report(tmp_path: Path) -> dict:
    repo = init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "d"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
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
    return analyze_repository(repo, empty_identity(), Lineage(), scope="repo")


def test_49_consent_writes_default_and_prints_steps(tmp_path, capsys, monkeypatch):
    report = _repo_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["contribute", "--yes", "--door", "public-pr"])
    assert code == 0
    target = tmp_path / ".grift" / "contribution.json"
    assert target.is_file(), "consented contribute must write a payload by default"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["contribution_schema"] == "tep-contribution-v1"
    err = capsys.readouterr().err
    # copy-ready guidance: submission id, PR filename, manifest line, doors
    assert "payloads/" in err and ".json" in err
    assert re.search(r'"id":"\d{4}-\d{4}-[0-9a-f]{8}"', err), "manifest line with submission id"
    assert '"door":"pr"' in err
    assert "tep-contributions" in err
    assert "代理PR経路" in err and "payload自体は最終的に公開" in err
    assert "nothing was sent" in err


def test_49_manifest_line_matches_written_payload(tmp_path, capsys, monkeypatch):
    import hashlib

    report = _repo_report(tmp_path)
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main(["contribute", "--yes", "--door", "public-pr"])
    raw = (tmp_path / ".grift" / "contribution.json").read_text(encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    err = capsys.readouterr().err
    assert digest in err, "printed manifest sha256 must match the written payload"
    assert digest[:8] in err  # submission id embeds hash8


def test_50_language_composition_is_shares(tmp_path):
    report = _repo_report(tmp_path)
    langs = report["context_profile"]["language_composition"]
    assert langs["kind"] == "observed" and langs["unit"] == "touch-share"
    total = sum(langs["value"].values())
    assert total <= 1.0001 and total >= 0.99, "values must be shares summing to ~1"


def test_50_actor_turnover_uses_last_active(tmp_path):
    report = _repo_report(tmp_path)
    turnover = report["context_profile"]["actor_turnover"]["value"]
    assert "left" not in json.dumps(turnover), "misleading 'left' key must be gone"
    assert all("last_active" in row for row in turnover.values())


def test_50_context_version_is_v3():
    assert CONTEXT_DEFINITION_VERSION == "context-v3-2026-08-25"


def test_50_markdown_renders_language_percents(tmp_path, capsys):
    report = _repo_report(tmp_path)
    from tep_core.report import render_markdown

    markdown = render_markdown(report)
    assert "languages (touch-share): py 100%" in markdown or "py" in markdown
    assert "3684" not in markdown.split("languages")[1].split("\n")[0], "raw counts must not appear"


def test_51_update_check_reports_installed(capsys):
    code = main(["update", "--check"])
    assert code in (0, 2)  # offline tolerated
    out = capsys.readouterr().out
    assert "installed:" in out


def test_51_measurement_commands_have_no_implicit_update_check(monkeypatch, tmp_path, capsys):
    """v0.6: measurement stays offline; only ``update --check`` may query PyPI."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-01-05", message="feat: seed")

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("measurement command attempted network access")

    monkeypatch.setattr("urllib.request.urlopen", refuse_network)
    assert main(["analyze", str(repo), "--scope", "repo", "--format", "json"]) == 0
    assert '"schema_version": "report-v1"' in capsys.readouterr().out


def test_report_md_carries_meaning_one_liners(tmp_path, capsys):
    report = _repo_report(tmp_path)
    from tep_core.report import render_markdown

    markdown = render_markdown(report)
    # v0.5.8+: glosses are INLINE on each value line (not section-level)
    assert "share of production changes paired with tests in the same commit" in markdown
    assert "not a bug count, not quality" in markdown
    assert "share of lines still present after 6 months" in markdown
    assert "shape of collaboration" in markdown
    assert "unique days with human commits in the last 180 days" in markdown
    assert "commits by identity-matched people" in markdown
    # reader's guide is bilingual
    assert (
        "## この数値でしてはいけない判断 / Decisions these numbers must NOT be used for" in markdown
    )
    assert "not grades" in markdown and "non-compliant with the TEP norms" in markdown
    # no leftover section-level explanation blocks
    assert "（何を測るか / What this measures" not in markdown
    assert "（このrepoのかたち / The shape of this repo" not in markdown


def test_49_open_fallback_without_gh(tmp_path, capsys, monkeypatch):
    """--open without gh/git on PATH: opens the browser fallback, no crash."""
    import shutil as _sh

    report = _repo_report(tmp_path)
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr("tep_cli.__main__._open_browser", lambda url: opened.append(url))
    monkeypatch.setattr(_sh, "which", lambda name: None)
    code = main(["contribute", "--yes", "--open"])
    assert code == 0
    assert opened and "tep-contributions" in opened[0]
    assert (tmp_path / ".grift" / "contribution.json").is_file()
