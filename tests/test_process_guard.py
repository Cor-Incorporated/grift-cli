"""The audit-hook guard in process_guard.py: what it refuses, and that it lets go."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from process_guard import REFUSED_EVENTS, refusing_process_starts


# Written out on purpose: cases built from REFUSED_EVENTS itself shrink with it, so dropping an
# event would remove its test along with it. os.spawn and os.startfile are raised on Windows only
# (POSIX os.spawnv is a fork and exec, and shows up as os.fork), so no POSIX call can pin them.
EXPECTED_REFUSED = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "os.startfile",
    }
)


def test_the_refused_set_is_the_declared_one() -> None:
    assert REFUSED_EVENTS == EXPECTED_REFUSED, (
        f"expected {sorted(EXPECTED_REFUSED)}, observed {sorted(REFUSED_EVENTS)}"
    )


@pytest.mark.parametrize("event", sorted(EXPECTED_REFUSED))
def test_every_declared_event_is_refused_before_anything_runs(event: str) -> None:
    """sys.audit raises the event without starting anything: the declared set is what is refused."""
    with refusing_process_starts(), pytest.raises(RuntimeError, match=event):
        sys.audit(event)


def test_nothing_is_refused_outside_the_block() -> None:
    sys.audit("os.system", "true")  # would raise inside the block
    with refusing_process_starts():
        pass
    sys.audit("os.system", "true")


def test_the_block_is_released_when_the_test_body_raises() -> None:
    with pytest.raises(ValueError), refusing_process_starts():
        raise ValueError("test body failed")
    sys.audit("os.system", "true")


def test_an_inner_block_does_not_release_the_outer_one() -> None:
    with refusing_process_starts():
        with refusing_process_starts():
            pass
        with pytest.raises(RuntimeError):
            sys.audit("os.system", "true")
    sys.audit("os.system", "true")


_TRUE = shutil.which("true")


@pytest.mark.skipif(sys.platform == "win32" or _TRUE is None, reason="needs a POSIX `true` on PATH")
@pytest.mark.parametrize(
    "start",
    [
        lambda: subprocess.Popen(["true"]).wait(),
        lambda: subprocess.Popen(["true"], pass_fds=(0,)).wait(),
        lambda: os.system("true"),
        lambda: os.waitpid(os.posix_spawn(_TRUE, ["true"], dict(os.environ)), 0),
    ],
    ids=["Popen", "Popen-pass_fds", "system", "os.posix_spawn"],
)
def test_real_calls_to_popen_system_and_posix_spawn_are_refused(start) -> None:
    """The names are the ones CPython raises: a misspelt event would pass the set tests above.

    CPython raises subprocess.Popen first for every Popen, whichever way it then starts the
    process. A host can change that: a sitecustomize that replaces Popen._execute_child (one seen
    on a macOS development host prefers os.posix_spawn) makes a plain Popen raise only that
    event. The pass_fds case keeps a Popen call that raises subprocess.Popen there too, and
    os.posix_spawn is called directly so that its name is pinned in this file whatever Popen does.
    """
    with refusing_process_starts(), pytest.raises(RuntimeError, match="a test started a process"):
        start()
