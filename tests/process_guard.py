"""Refuse the ways a test can start a process while the guard is armed.

Replacing ``subprocess.run`` / ``Popen`` / ``os.system`` only stops the callers that go through
them. ``os.execv`` replaces the pytest process itself (the run then ends with an empty report and
the installer's exit code), and ``os.spawnv``, ``os.posix_spawn`` and ``os.fork`` start a process
without touching any of those names. An audit hook sees all of them before they run.

Scope: the ``os`` and ``subprocess`` entry points that raise one of ``REFUSED_EVENTS`` (that
includes ``os.popen``, ``asyncio`` subprocesses, ``pty.fork`` and ``multiprocessing`` with the
``fork`` start method). Not covered: a direct call into ``ctypes`` or ``_posixsubprocess.fork_exec``,
and ``multiprocessing`` with the ``spawn`` or ``forkserver`` start method (``src/`` uses none).

The hook is registered once per process and cannot be removed, so it only acts while a test holds
``refusing_process_starts()``.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator

REFUSED_EVENTS = frozenset(
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
_state = {"armed": False}


def _refuse(event: str, args: tuple[object, ...]) -> None:
    if _state["armed"] and event in REFUSED_EVENTS:
        raise RuntimeError(f"a test started a process: {event}")


sys.addaudithook(_refuse)


@contextlib.contextmanager
def refusing_process_starts() -> Iterator[None]:
    """Refuse process starts inside the block; leaving it restores the state it found."""
    previous = _state["armed"]
    _state["armed"] = True
    try:
        yield
    finally:
        _state["armed"] = previous
