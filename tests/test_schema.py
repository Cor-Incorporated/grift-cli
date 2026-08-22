"""report-v1 schema validation: golden expected payloads, live reports, mutations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tep_core.analyze import analyze_repository
from tep_core.identity import empty_identity, load_identity
from tep_core.lineage import Lineage
from tep_core.schema import validate_report

from git_fixture import commit, init_repo, merge_commit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "golden" / "expected"
_DELETE = object()


@pytest.mark.parametrize("path", sorted(EXPECTED.glob("*.json")), ids=lambda p: p.stem)
def test_golden_expected_subset_conforms(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert validate_report(payload, subset=True) == []


def _fixture_report(tmp_path: Path, *, scope: str) -> dict[str, Any]:
    repo = init_repo(tmp_path / "repo")
    repo.joinpath("pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    tests_dir.joinpath("test_smoke.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    for index in range(30):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-02",
            message=f"work {index}",
            filename="app.py",
        )
        if index % 2 == 0:
            commit(
                repo,
                email="a@example.com",
                date="2026-01-02",
                message=f"test {index}",
                filename="tests/test_app.py",
            )
    commit(
        repo,
        email="bot[bot]@users.noreply.github.com",
        date="2026-01-03",
        message="chore: automated",
    )
    merge_commit(repo, email="a@example.com", date="2026-01-03")
    return analyze_repository(repo, empty_identity(), Lineage(), scope=scope)


def test_live_tenant_report_conforms(tmp_path: Path) -> None:
    report = _fixture_report(tmp_path, scope="tenant")
    assert validate_report(report) == []


def test_live_repo_scope_report_conforms(tmp_path: Path) -> None:
    report = _fixture_report(tmp_path, scope="repo")
    assert validate_report(report) == []
    assert report["interpretation"]["test_cochange"]["kind"] == "observed"


def _set(base: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    variant = copy.deepcopy(base)
    node: Any = variant
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[keys[-1]]
    else:
        node[keys[-1]] = value
    return variant


def test_mutations_are_rejected(tmp_path: Path) -> None:
    base = _fixture_report(tmp_path, scope="repo")
    assert validate_report(base) == []
    mutations: dict[str, tuple[str, Any]] = {
        "schema_version": ("schema_version", "report-v2"),
        "bad_sha": ("provenance.analyzed_commit_sha", "xyz"),
        "bad_timestamp": ("provenance.analyzed_at", "2026-08-22 00:00:00"),
        "bad_scope": ("provenance.analysis_scope", "org"),
        "negative_commits": ("origin.tenant_unique.value", -1),
        "bad_unit": ("activity.active_days.unit", "commits"),
        "bad_kind": ("survival.kind", "probably"),
        "bad_reason": ("survival.reason", "Not A Reason"),
        "cochange_ratio_out_of_range": ("test_cochange.all_time.value", 1.5),
        "interpretation_decile_out_of_range": ("interpretation.test_cochange.decile", 11),
        "missing_survival_section": ("survival", _DELETE),
        "test_frameworks_false": ("test_frameworks.value", False),
        "sample_size_zero": (
            "activity.commits_per_active_day_median",
            {
                "kind": "observed",
                "value": 2,
                "unit": "commits/active-day",
                "sample_size": 0,
            },
        ),
        "window_days_zero": ("rework.window_days", 0),
    }
    for name, (path, value) in mutations.items():
        errors = validate_report(_set(base, path, value))
        assert errors, f"{name}: mutation at {path} was not detected"
        assert any(path.split(".")[-1] in item or path in item for item in errors), (
            f"{name}: errors do not point at {path}: {errors}"
        )


@pytest.mark.golden
@pytest.mark.parametrize(
    "pin_name", ["G1-click", "G2-gitignore", "G3-spoon-knife", "G4-express", "G5-typer"]
)
def test_golden_live_report_conforms(pin_name: str) -> None:
    import tomllib

    import test_golden

    pins = {
        p["id"]: p
        for p in tomllib.loads((ROOT / "golden" / "pins.toml").read_text(encoding="utf-8"))["repos"]
    }
    pin = pins[pin_name]
    dest = ROOT / ".golden-cache" / pin["name"]
    test_golden._ensure_clone(pin["url"], dest, pin["sha"])
    identity_rel = pin.get("identity") or ""
    identity = load_identity(ROOT / identity_rel) if identity_rel else empty_identity()
    report = analyze_repository(
        dest,
        identity,
        Lineage(is_fork=bool(pin.get("fork")), parent=pin.get("parent") or None),
    )
    assert validate_report(report) == []
