"""0.9.6: survival reference position, the actor self-view and forge evidence (#24, #27)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from v096_fixture import AS_OF_JUNE, alice_bob_repo, bind_forge_reviews, consenting_identity

from tep_cli.__main__ import main
from tep_core import reference
from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.schema import validate_report
from tep_core.self_view import HEADING_COORDINATION, HEADING_USE


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue() + err.getvalue()


def _stdout(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        assert main(argv) == 0
    return out.getvalue()


def _actor_md(repo: Path, *extra: str) -> str:
    code, text = _run(
        ["actor", "alice", str(repo), "--as-of", AS_OF_JUNE, "--format", "md", *extra]
    )
    assert code == 0, text
    return text


# --- survival interpretation (#24) -----------------------------------------


def _observation(index: float = 0.5, lines: int = 200) -> dict[str, Any]:
    return {
        "kind": "observed",
        "unit": "dimensionless",
        "survival_index": index,
        "lines_sampled": lines,
        "tau_days": 180,
    }


def _fake_distributions(n: int) -> dict[str, Any]:
    return {
        "version": "v-test",
        "analysis_scope": "repo",
        "metrics": {
            "survival": {"n": n, "deciles": [round(i / 10, 2) for i in range(10)]},
        },
    }


def test_shipped_references_carry_no_survival_block() -> None:
    result = reference.interpret_survival(report_scope="repo", observation=_observation())
    assert result == {"kind": "not_observed", "reason": "reference_too_small"}


def test_tenant_scope_has_no_survival_position() -> None:
    result = reference.interpret_survival(report_scope="tenant", observation=_observation())
    assert result["reason"] == "scope_is_tenant"


def test_unobserved_survival_has_no_position() -> None:
    off = {"kind": "not_observed", "reason": "survival_scan_disabled"}
    result = reference.interpret_survival(report_scope="repo", observation=off)
    assert result["reason"] == "metric_not_observed"


def test_few_sampled_lines_have_no_position() -> None:
    result = reference.interpret_survival(
        report_scope="repo", observation=_observation(lines=reference.SURVIVAL_MIN_LINES - 1)
    )
    assert result["reason"] == "insufficient_population"


def test_a_large_enough_reference_gives_a_decile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reference, "load_distributions", lambda version=None: _fake_distributions(40)
    )
    result = reference.interpret_survival(report_scope="repo", observation=_observation(0.55))
    assert result["kind"] == "observed"
    assert result["metric_id"] == "survival"
    assert result["n"] == 40
    assert 1 <= result["decile"] <= 10


def test_a_small_reference_still_gives_no_decile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reference,
        "load_distributions",
        lambda version=None: _fake_distributions(reference.MIN_N - 1),
    )
    result = reference.interpret_survival(report_scope="repo", observation=_observation())
    assert result["reason"] == "reference_too_small"


def test_interpretation_has_survival_only_when_the_scan_is_requested(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    plain = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    assert "survival" not in plain["interpretation"]
    scanned = analyze_repository(repo, empty_identity(), Lineage(), scope="repo", survival=True)
    assert scanned["interpretation"]["survival"]["kind"] == "not_observed"
    assert scanned["interpretation"]["survival"]["reason"] == "reference_too_small"
    # `$.survival.*` has an older check (it wants `value`); it is not part of this change.
    assert [e for e in validate_report(scanned) if not e.startswith("$.survival.")] == []


# --- actor self-view and forge evidence (#27, #24) -------------------------


def test_consenting_actor_report_has_the_self_use_block(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    identity = consenting_identity(tmp_path / "identity.toml")
    text = _actor_md(repo, "--identity", str(identity))
    assert HEADING_USE in text
    assert "経歴の要約" in text
    assert "--disclosure-level" in text
    assert text.index(HEADING_USE) < text.index("## 共有するときの条件")


def test_self_use_block_is_not_shown_without_consent(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    text = _actor_md(repo)
    assert HEADING_USE not in text


def test_forge_reviews_sit_beside_the_work_sentences(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    identity = consenting_identity(tmp_path / "identity.toml")
    export = bind_forge_reviews(repo, tmp_path / "forge.json", reviews=6)
    text = _actor_md(repo, "--identity", str(identity), "--forge-export", str(export))
    assert HEADING_COORDINATION in text
    block = text.split(HEADING_COORDINATION)[1].split("\n## ")[0]
    assert "6 件" in block
    assert "測っていません" in block
    assert "承認した記録" in block


def test_partial_forge_coverage_is_said_in_the_self_view(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    identity = consenting_identity(tmp_path / "identity.toml")
    export = bind_forge_reviews(repo, tmp_path / "forge.json", reviews=3, coverage="partial")
    text = _actor_md(repo, "--identity", str(identity), "--forge-export", str(export))
    block = text.split(HEADING_COORDINATION)[1].split("\n## ")[0]
    assert "少なくとも" in block


def test_no_forge_export_leaves_no_coordination_block(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    identity = consenting_identity(tmp_path / "identity.toml")
    text = _actor_md(repo, "--identity", str(identity))
    assert HEADING_COORDINATION not in text


def test_minimal_level_withholds_forge_sentences_but_not_the_json(tmp_path: Path) -> None:
    repo = alice_bob_repo(tmp_path / "repo")
    identity = consenting_identity(tmp_path / "identity.toml")
    export = bind_forge_reviews(repo, tmp_path / "forge.json", reviews=6)
    args = [
        "--identity",
        str(identity),
        "--forge-export",
        str(export),
        "--disclosure-level",
        "minimal",
    ]
    text = _actor_md(repo, *args)
    assert HEADING_COORDINATION not in text
    raw = _stdout(["actor", "alice", str(repo), "--as-of", AS_OF_JUNE, "--format", "json", *args])
    report = json.JSONDecoder().raw_decode(raw)[0]
    assert report["coordination_profile"]["review"]["review_event_count"]["value"] == 6
