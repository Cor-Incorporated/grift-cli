"""Explicit update routing without package downloads or installation changes."""

from __future__ import annotations

import http.client
import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.version import __version__

from process_guard import refusing_process_starts


@pytest.fixture(autouse=True)
def refuse_external_actions(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "plain-venv"))

    def refuse(*args, **kwargs):
        pytest.fail("unexpected network request or package manager execution")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    # run/call/check_* start a process through Popen, and os.system through the shell.
    monkeypatch.setattr("subprocess.Popen", refuse)
    monkeypatch.setattr("os.system", refuse)
    # spawn/exec/fork bypass all of the names above (os.execv would even replace the pytest
    # process): the audit hook refuses every way of starting one for the length of the test.
    with refusing_process_starts():
        yield


def test_check_only_fetches_metadata_and_reports_versions(monkeypatch, capsys):
    calls = []

    def metadata(url, *, timeout):
        calls.append((url, timeout))
        return io.BytesIO(json.dumps({"info": {"version": __version__}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", metadata)
    assert main(["update", "--check"]) == 0
    output = capsys.readouterr().out
    assert f"installed: {__version__}" in output
    assert f"latest:    {__version__}" in output
    assert "up to date" in output
    assert calls == [("https://pypi.org/pypi/grift-cli/json", 10)]


def test_check_offline_reports_failure_without_upgrade(monkeypatch, capsys):
    def offline(*args, **kwargs):
        raise urllib.error.URLError("offline fixture")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    assert main(["update", "--check"]) == 2
    captured = capsys.readouterr()
    assert f"installed: {__version__}" in captured.out
    assert "version check unavailable" in captured.err
    assert "grift --version" in captured.err
    assert "up to date" not in captured.out


@pytest.mark.parametrize(
    "body", [b"invalid json", b"{}", b'{"info":null}', b'{"info":{"version":12}}']
)
def test_bad_metadata_is_not_success(monkeypatch, body, capsys):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(body))
    assert main(["update", "--check"]) == 2
    assert "version check unavailable" in capsys.readouterr().err


def test_pip_update_targets_running_python_even_with_pipx_on_path(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: f"/unrelated/bin/{name}")
    monkeypatch.setenv("PYTHONPATH", "/source/override")
    for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT"):
        monkeypatch.setenv(name, "/elsewhere")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="grift fixture-updated\n")

    monkeypatch.setattr("subprocess.run", run)
    assert main(["update"]) == 0
    # -P: the installer must not import a pip.py that sits in the current directory.
    assert calls[0][0] == [sys.executable, "-P", "-m", "pip", "install", "--upgrade", "grift-cli"]
    assert "PYTHONPATH" not in calls[0][1]["env"]
    # The running environment is the only target: pip must not be redirected by PIP_* variables.
    for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT"):
        assert name not in calls[0][1]["env"], name
    # The installer starts outside the user's repository and keeps sys.path clean for its children.
    assert calls[0][1]["env"]["PYTHONSAFEPATH"] == "1"
    assert calls[0][1]["cwd"] == sys.prefix
    assert calls[1][0] == [sys.executable, "-P", "-m", "tep_cli", "--version"]
    assert "PYTHONPATH" not in calls[1][1]["env"]
    assert calls[1][1]["capture_output"] is True
    assert "installed after update: grift fixture-updated" in capsys.readouterr().out


def _pipx_environment(monkeypatch, tmp_path, *, package="grift-cli") -> Path:
    prefix = tmp_path / "custom-pipx" / "venvs" / "grift-cli-suffix"
    prefix.mkdir(parents=True)
    (prefix / "pipx_metadata.json").write_text(
        json.dumps({"main_package": {"package": package}}), encoding="utf-8"
    )
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr("shutil.which", lambda name: "/tools/pipx" if name == "pipx" else None)
    return prefix


def test_pipx_update_binds_current_home_and_suffixed_environment(monkeypatch, tmp_path):
    prefix = _pipx_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("PIPX_HOME", "/different/pipx-home")
    monkeypatch.setenv("PYTHONPATH", "/source/override")
    for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT"):
        monkeypatch.setenv(name, "/elsewhere")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="grift fixture-updated\n")

    monkeypatch.setattr("subprocess.run", run)
    assert main(["update"]) == 0
    assert calls[0][0] == ["/tools/pipx", "upgrade", "grift-cli-suffix"]
    assert calls[0][1]["env"]["PIPX_HOME"] == str(prefix.parent.parent)
    # pipx starts its own Python children: none of them may see PYTHONPATH or a PIP_* target, and
    # the working directory (the user's repository) must not be theirs or on their sys.path.
    assert "PYTHONPATH" not in calls[0][1]["env"]
    for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT"):
        assert name not in calls[0][1]["env"], name
    assert calls[0][1]["env"]["PYTHONSAFEPATH"] == "1"
    assert calls[0][1]["cwd"] == str(prefix)


def test_unrelated_pipx_package_is_not_upgraded(monkeypatch, tmp_path, capsys):
    _pipx_environment(monkeypatch, tmp_path, package="another-cli")
    assert main(["update"]) == 2
    assert "cannot identify the running pipx installation" in capsys.readouterr().err


def test_missing_pipx_does_not_fall_back_to_another_installer(monkeypatch, tmp_path, capsys):
    _pipx_environment(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert main(["update"]) == 2
    assert "pipx is not on PATH" in capsys.readouterr().err


def test_corrupt_pipx_metadata_is_not_upgraded(monkeypatch, tmp_path, capsys):
    prefix = _pipx_environment(monkeypatch, tmp_path)
    (prefix / "pipx_metadata.json").write_text("invalid", encoding="utf-8")
    assert main(["update"]) == 2
    assert "cannot identify the running pipx installation" in capsys.readouterr().err


def test_installer_failure_is_propagated_without_version_success(monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 17)

    monkeypatch.setattr("subprocess.run", run)
    assert main(["update"]) == 17
    assert len(calls) == 1
    assert "installed after update" not in capsys.readouterr().out


def test_missing_installer_is_a_readable_failure(monkeypatch, capsys):
    def run(*args, **kwargs):
        raise FileNotFoundError("fixture Python unavailable")

    monkeypatch.setattr("subprocess.run", run)
    assert main(["update"]) == 2
    assert "could not start the package manager" in capsys.readouterr().err


def test_version_readback_failure_does_not_claim_success(monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0 if len(calls) == 1 else 1, stdout="")

    monkeypatch.setattr("subprocess.run", run)
    assert main(["update"]) == 2
    captured = capsys.readouterr()
    assert "installed after update" not in captured.out
    assert "version could not be checked" in captured.err


def test_local_version_and_update_help_are_offline(capsys):
    for args in (["--version"], ["update", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 0
    output = capsys.readouterr().out
    assert f"grift {__version__}" in output
    assert "--check" in output


def test_check_with_a_newer_release_never_installs(monkeypatch, capsys):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps({"info": {"version": "99.0.0"}}).encode()),
    )
    # subprocess.run is refused by the autouse fixture: any installer start fails the test.
    assert main(["update", "--check"]) == 0
    output = capsys.readouterr().out
    assert "latest:    99.0.0" in output
    assert "up to date" not in output


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"{", 100),
        http.client.BadStatusLine("not http"),
        http.client.RemoteDisconnected("closed"),
    ],
)
def test_check_with_a_cut_or_malformed_http_response_is_a_readable_failure(
    monkeypatch, capsys, error
):
    class Response(io.BytesIO):
        def read(self, *args, **kwargs):
            raise error

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    assert main(["update", "--check"]) == 2
    captured = capsys.readouterr()
    assert "version check unavailable" in captured.err
    assert "Traceback" not in captured.err


_EXEC_REPLACED_PYTEST = (
    "import sys; sys.stderr.write('process guard is broken: os.execv replaced the pytest process "
    "in test_the_process_guard_refuses_every_way_to_start_one[execv]\\n'); raise SystemExit(70)"
)


def _execv_that_exits_70() -> None:
    """A broken guard ends the pytest process with 70 (red) and says why, not with 0 (green)."""
    os.execv(sys.executable, [sys.executable, "-c", _EXEC_REPLACED_PYTEST])


def _spawnv() -> None:
    # On POSIX os.spawnv is a fork and exec, so the guard sees "os.fork", not "os.spawn" (Windows).
    os.spawnv(os.P_WAIT, sys.executable, [sys.executable, "-c", "pass"])


def _forkpty_that_leaves_the_child_out_of_pytest() -> None:
    pid, _fd = os.forkpty()
    if pid == 0:
        os._exit(70)
    os.waitpid(pid, 0)


def _posix_spawn() -> None:
    pid = os.posix_spawn(sys.executable, [sys.executable, "-c", "pass"], dict(os.environ))
    os.waitpid(pid, 0)


def _fork_that_leaves_the_child_out_of_pytest() -> None:
    pid = os.fork()
    if pid == 0:
        os._exit(70)  # a broken guard must not let the child run the rest of the test session
    os.waitpid(pid, 0)


@pytest.mark.skipif(not hasattr(os, "forkpty"), reason="os.forkpty is POSIX only")
def test_the_process_guard_refuses_forkpty():
    with pytest.raises(RuntimeError, match="a test started a process: os.forkpty"):
        _forkpty_that_leaves_the_child_out_of_pytest()


@pytest.mark.parametrize(
    "start",
    [_spawnv, _posix_spawn, _fork_that_leaves_the_child_out_of_pytest, _execv_that_exits_70],
    ids=["spawnv", "posix_spawn", "fork", "execv"],
)
def test_the_process_guard_refuses_every_way_to_start_one(start, capsys):
    """These four pass the subprocess.run/Popen/os.system stubs untouched (Popen and system are
    stubbed above). execv runs last: it would replace the pytest process if the guard failed."""
    # pytest's fd capture would swallow what a replaced process writes to stderr: capture is off
    # here so that a broken guard names itself in the CI log before the run ends with exit code 70.
    with capsys.disabled(), pytest.raises(RuntimeError, match="a test started a process"):
        start()
