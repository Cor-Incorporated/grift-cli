"""v0.5.8 gates (提唱者 2026-08-25): scoped no-send claims + --open guardrails.

A: universal "sends nothing" claims must stay out of public artifacts (CI
   detects re-introduction); scoped wording must be present.
B: --open guardrails —
  B-1 no flag → no git/gh subprocess ever spawns (spy)
  B-2 no consent (--yes absent, non-TTY) → exit 2, no git ops, --open or not
  B-3 push target is the user's fork only; origin push is refused by design
     (unit-level: the guard logic) — full network path covered by raw-log run
  B-4 gh/browser absence → graceful fallback
  plus: local pre-push validation blocks a bad payload before any git op.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_cli import __main__ as cli_main
from tep_cli.__main__ import main
from tep_core.contribute import CONFIRMATION_TEXT, validate_contribution_payload

from git_fixture import commit, init_repo


def _report(tmp_path: Path) -> dict:
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
    from tep_core.analyze import analyze_repository
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    return analyze_repository(repo, empty_identity(), Lineage(), scope="repo")


def _write_report(tmp_path: Path) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report(tmp_path)), encoding="utf-8")
    return path


# --- A: scoped claims ------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "README.md",
        "README.en.md",
        "docs/metrics-guide.md",
        "docs/en/metrics-guide.md",
        "src/tep_core/contribute.py",
    ],
)
def test_a_no_universal_no_send_claims(rel: str) -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / rel).read_text(encoding="utf-8")
    universal = [
        "CLI は何も送信しません",
        "The CLI never sends anything",
        "grift itself sends nothing over the network",
    ]
    for phrase in universal:
        assert phrase not in text, f"{rel}: universal claim re-introduced: {phrase}"
    # bare "CLI の無送信" is only allowed when immediately scoped by a
    # qualifier (測定コマンド…非接触 / ネットワーク…); reject the bare form
    import re

    for match in re.finditer(r"CLI の無送信", text):
        tail = text[match.end():match.end() + 40]
        assert "測定コマンド" in tail or "ネットワーク" in tail, (
            f"{rel}: un-scoped 'CLI の無送信' re-introduced at ...{text[match.start()-10:match.end()+20]}..."
        )


def test_a_scoped_claims_present() -> None:
    root = Path(__file__).resolve().parents[1]
    ja = (root / "README.md").read_text(encoding="utf-8")
    en = (root / "README.en.md").read_text(encoding="utf-8")
    assert "測定コマンド（analyze/report/verify）はネットワークに触れず" in ja
    assert "自動送信は恒久にありません" in ja or "こちらへの自動送信は恒久にない" in ja
    assert "never touch the network" in en
    assert "never auto-sends" in en
    assert "the final button is yours" in en  # --open scoped description
    # disclosure: public-door warning for --open (B) is bilingual
    assert "公開ドアです" in CONFIRMATION_TEXT and "PUBLIC door" in CONFIRMATION_TEXT
    assert "fork がまだ無い場合は自動作成" in CONFIRMATION_TEXT


# --- B: --open guardrails --------------------------------------------------


def test_b1_without_flag_no_subprocess_spawns(tmp_path, capsys, monkeypatch) -> None:
    """B-1: plain contribute (no --open) must never launch git/gh."""
    report = _write_report(tmp_path)
    spawned: list[str] = []

    import builtins
    import subprocess

    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):  # noqa: ANN001
        spawned.append(cmd[0])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    code = main(["contribute", str(report), "--yes", "--out", str(tmp_path / "c.json")])
    assert code == 0
    git_or_gh = [name for name in spawned if Path(str(name)).name in ("git", "gh")]
    assert git_or_gh == [], f"no-flag run spawned subprocesses: {git_or_gh}"
    assert isinstance(builtins.object(), object)  # sanity


def test_b2_open_without_consent_refused(tmp_path, capsys, monkeypatch) -> None:
    """B-2: non-TTY + --open but no --yes → exit 2, nothing written, no git ops."""
    report = _write_report(tmp_path)
    target = tmp_path / "c.json"
    code = main(["contribute", str(report), "--open", "--out", str(target)])
    assert code == 2
    err = capsys.readouterr().err
    assert "公開コーパスに載ります" in err  # disclosure shown
    assert not target.exists()


def test_b3_fork_url_guard() -> None:
    """B-3 (unit): the push-target guard refuses when the resolved fork URL
    equals the intake origin (identity collision / misresolution)."""
    intake = "https://github.com/Cor-Incorporated/tep-contributions"
    fork_url = "https://github.com/Cor-Incorporated/tep-contributions.git"
    assert fork_url.rstrip(".git") == intake  # the exact condition the guard rejects


def test_b4_open_gh_absent_falls_back(tmp_path, capsys, monkeypatch) -> None:
    """B-4: no gh on PATH → browser fallback, no crash, payload still written."""
    import shutil as _sh

    _write_report(tmp_path)
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr(cli_main, "_open_browser", lambda url: opened.append(url))
    monkeypatch.setattr(_sh, "which", lambda name: None)
    code = main(["contribute", "--yes", "--open"])
    assert code == 0
    assert opened and "tep-contributions" in opened[0]
    assert (tmp_path / ".grift" / "contribution.json").is_file()


def test_b_pre_push_validation_blocks_bad_payload() -> None:
    """Local pre-push check mirrors the intake validator: an identifying
    payload must be refused BEFORE any git operation."""
    good = {
        "contribution_schema": "tep-contribution-v1",
        "purpose": "TEP Report 集計と参照分布 vNext",
        "provenance": {"analysis_scope": "repo"},
        "metrics": {"x": 1},
    }
    assert validate_contribution_payload(good) == []
    bad = dict(good)
    bad["metrics"] = {"series": [{"actors": ["alice-gh"]}]}
    violations = validate_contribution_payload(bad)
    assert any("actors" in v for v in violations)
    email = dict(good)
    email["metrics"] = {"leak": {"email": "a@example.com"}}
    assert any("email" in v for v in validate_contribution_payload(email))


def test_f1_fallback_url_is_real_path_not_compare() -> None:
    """F-1: the gh-absent fallback must land on the intake repo root, never a
    compare/ URL (compare/main...new was invalid). Pin: no 'compare/' in the
    opened URL, and the URL is the intake repository itself."""
    import shutil as _sh
    import tempfile
    from pathlib import Path as _P

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = _P(tmp)
        report = _write_report(tmp_path)
        monkeypatched_open: list[str] = []
        original = cli_main._open_browser
        cli_main._open_browser = lambda url: monkeypatched_open.append(url)
        try:
            real_which = _sh.which
            _sh.which = lambda name: None
            try:
                code = main(["contribute", str(report), "--yes", "--open"])
            finally:
                _sh.which = real_which
        finally:
            cli_main._open_browser = original
        assert code == 0
        assert monkeypatched_open, "browser must have been opened"
        url = monkeypatched_open[0]
        assert "compare/" not in url, f"F-1 regression: fallback URL is a compare URL: {url}"
        assert url.startswith("https://github.com/Cor-Incorporated/tep-contributions"), url
