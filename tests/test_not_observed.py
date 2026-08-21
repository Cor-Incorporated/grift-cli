"""not_observed is a distinct kind from observed zero."""

from __future__ import annotations

from pathlib import Path

from tep_core.observation import NotObserved, Observed
from tep_core.tests_observed import observe_test_frameworks


def test_observed_zero_is_not_not_observed() -> None:
    zero = Observed(0, "commits").to_dict()
    missing = NotObserved("pending_attribution").to_dict()
    assert zero["kind"] == "observed"
    assert zero["value"] == 0
    assert missing["kind"] == "not_observed"
    assert "value" not in missing


def test_missing_test_dir_is_not_observed(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    result = observe_test_frameworks(tmp_path)
    assert result["kind"] == "not_observed"
    assert result["reason"] == "no_test_framework_or_directory"


def test_pytest_manifest_is_observed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n[dependency-groups]\ntests = ["pytest"]\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    result = observe_test_frameworks(tmp_path)
    assert result["kind"] == "observed"
    assert result["value"] is True
    assert "pytest" in result["names"]
