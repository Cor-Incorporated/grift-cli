"""0.9.6 (#25): the corpus bootstrap plans offline, refuses shipped versions, keeps n honest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import corpus_bootstrap as cb  # noqa: E402


def _candidate(name: str, **extra: str) -> dict[str, str]:
    return {"url": f"https://github.com/acme/{name}", **extra}


def test_plan_drops_duplicates_heavy_repos_and_non_public_urls() -> None:
    known = [{"url": "https://github.com/acme/old.git"}]
    candidates = [
        _candidate("new"),
        _candidate("old"),
        _candidate("new"),
        {"url": "https://github.com/wrtnlabs/autobe.git"},
        {"url": "https://token@github.com/acme/secret.git"},
        {"url": "git@github.com:acme/ssh.git"},
        {"url": "https://example.com/acme/other.git"},
    ]
    plan = cb.build_plan(candidates, known=known, version="v2026.12")
    assert [item["key"] for item in plan["planned"]] == ["acme/new"]
    reasons = [item["reason"] for item in plan["dropped"]]
    assert reasons == [
        "duplicate",
        "duplicate",
        "excluded_heavy_clone",
        "not_a_public_https_url",
        "not_a_public_https_url",
        "not_a_public_https_url",
    ]


def test_plan_normalises_the_url_and_keeps_a_pinned_sha() -> None:
    sha = "a" * 40
    plan = cb.build_plan([_candidate("tool", sha=sha, group="C")], known=[], version="v2026.12")
    entry = plan["planned"][0]
    assert entry["url"] == "https://github.com/acme/tool.git"
    assert entry["sha"] == sha
    assert entry["group"] == "C"


def test_plan_applies_the_limit() -> None:
    candidates = [_candidate(f"r{i}") for i in range(5)]
    plan = cb.build_plan(candidates, known=[], version="v2026.12", limit=2)
    assert len(plan["planned"]) == 2
    assert [item["reason"] for item in plan["dropped"]] == ["over_limit"] * 3


@pytest.mark.parametrize("version", sorted(cb.SHIPPED_VERSIONS))
def test_shipped_versions_are_immutable(version: str) -> None:
    with pytest.raises(cb.BootstrapError):
        cb.build_plan([], known=[], version=version)
    with pytest.raises(cb.BootstrapError):
        cb.build_distributions([], version=version, definition_version="x")


@pytest.mark.parametrize("version", ["2026.12", "v26.12", "latest", ""])
def test_version_shape_is_checked(version: str) -> None:
    with pytest.raises(cb.BootstrapError):
        cb.validate_version(version)


def _row(survival: float | None, lines: int = 100) -> dict:
    survival_block = (
        {"kind": "not_observed", "reason": "survival_scan_disabled"}
        if survival is None
        else {"kind": "observed", "survival_index": survival, "lines_sampled": lines}
    )
    return {
        "test_cochange": {
            "kind": "observed",
            "all_time": {"kind": "observed", "value": 0.3, "narrate_rate": True},
        },
        "rework": {
            "kind": "observed",
            "corrective_rework_rate": {"kind": "observed", "value": 0.1, "narrate_rate": True},
        },
        "survival": survival_block,
    }


def test_distributions_issue_deciles_only_from_min_n() -> None:
    rows = [_row(0.5 + i / 1000) for i in range(cb.MIN_N)]
    dist = cb.build_distributions(rows, version="v2026.12", definition_version="d")
    assert dist["metrics"]["survival"]["n"] == cb.MIN_N
    assert len(dist["metrics"]["survival"]["deciles"]) == 10
    assert dist["analysis_scope"] == "repo"
    assert dist["notes"] == []


def test_a_short_metric_gets_a_note_and_no_deciles() -> None:
    rows = [_row(0.5)] * (cb.MIN_N - 1)
    dist = cb.build_distributions(rows, version="v2026.12", definition_version="d")
    assert "survival" not in dist["metrics"]
    assert any(note.startswith("survival: n=29") for note in dist["notes"])


def test_survival_rows_with_few_sampled_lines_are_not_counted() -> None:
    assert cb.survival_rate(_row(0.5, lines=cb.SURVIVAL_MIN_LINES - 1)) is None
    assert cb.survival_rate(_row(0.5, lines=cb.SURVIVAL_MIN_LINES)) == 0.5
    assert cb.survival_rate(_row(None)) is None


def test_the_built_distribution_is_readable_by_the_reference_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tep_core import reference

    rows = [_row(i / 40) for i in range(40)]
    dist = cb.build_distributions(rows, version="v2026.12", definition_version="d")
    monkeypatch.setattr(reference, "load_distributions", lambda version=None: dist)
    result = reference.interpret_survival(
        report_scope="repo",
        observation={
            "kind": "observed",
            "survival_index": 0.5,
            "lines_sampled": 100,
            "unit": "dimensionless",
        },
    )
    assert result["kind"] == "observed"
    assert result["n"] == 40


def test_pins_file_holds_url_sha_and_group_only() -> None:
    text = cb.render_pins(
        "v2026.12",
        [
            {
                "key": "acme/tool",
                "url": "https://github.com/acme/tool.git",
                "group": "C",
                "sha": "b" * 40,
            }
        ],
    )
    assert 'url = "https://github.com/acme/tool.git"' in text
    assert f'sha = "{"b" * 40}"' in text
    assert "survival" not in text and "email" not in text


def test_plan_command_is_offline_and_writes_the_plan(tmp_path: Path) -> None:
    source = tmp_path / "candidates.json"
    source.write_text(json.dumps({"candidates": [_candidate("fresh")]}), encoding="utf-8")
    out = tmp_path / "plan.json"
    code = cb.main(
        ["plan", "--version", "v2026.12", "--candidates", str(source), "--out", str(out)]
    )
    assert code == 0
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["schema_version"] == cb.PLAN_SCHEMA
    assert [item["key"] for item in plan["planned"]] == ["acme/fresh"]


def test_plan_from_existing_pins_re_observes_them_at_their_pinned_sha(tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    pins = ROOT / "corpus" / "pins-v2026.11.toml"
    assert (
        cb.main(["plan", "--version", "v2026.12", "--from-pins", str(pins), "--out", str(out)]) == 0
    )
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["planned"], "the shipped pins should yield a plan"
    assert all(len(item["sha"]) == 40 for item in plan["planned"])


def test_plan_command_rejects_a_shipped_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cb.main(["plan", "--version", "v2026.11", "--candidates", str(tmp_path / "none.json")])
    assert code == 2
    assert "immutable" in capsys.readouterr().err
