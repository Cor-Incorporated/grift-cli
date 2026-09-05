from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _load_runner():
    runner_path = Path(__file__).resolve().parent / "fixtures" / "v060" / "run_p0_falsify.py"
    spec = importlib.util.spec_from_file_location("grift_v060_p0_runner", runner_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v059_override_has_priority_and_resolves_relative_to_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _load_runner()
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("explicit override must not invoke git discovery")

    monkeypatch.setattr(runner.subprocess, "run", unexpected_run)
    resolved = runner.resolve_v059_root(
        root=checkout,
        environ={"GRIFT_V059_ROOT": ".worktrees/comparison/v059"},
    )

    assert resolved == (checkout / ".worktrees" / "comparison" / "v059").resolve()


def test_v059_discovery_uses_git_common_repository_root(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    checkout = tmp_path / "repo" / ".worktrees" / "codex" / "v060"
    checkout.mkdir(parents=True)
    common_dir = tmp_path / "repo" / ".git"
    common_dir.mkdir()

    def git_common_dir(command, **kwargs):
        assert command == ["git", "-C", str(checkout), "rev-parse", "--git-common-dir"]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(command, 0, stdout=str(common_dir) + "\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", git_common_dir)

    assert runner.resolve_v059_root(root=checkout, environ={}) == (
        tmp_path / "repo" / ".worktrees" / "grok" / "v059"
    )


def test_v059_discovery_and_main_fail_closed_outside_git(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()

    def not_a_git_checkout(*_args, **_kwargs):
        raise subprocess.CalledProcessError(128, ["git"])

    monkeypatch.setattr(runner.subprocess, "run", not_a_git_checkout)
    assert runner.resolve_v059_root(root=tmp_path, environ={}) is None

    monkeypatch.setattr(runner, "V059", None)
    assert runner.main() == 2
