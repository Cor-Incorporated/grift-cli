"""v0.9.0, follow-up of #85: the detail layer never calls a shallow history whole.

#85 wrote the surface and verification windows as 「{end} までの全履歴」. A shallow
clone holds only the fetched slice, so the detail layer says 「{end} までの履歴」
everywhere. The opening section (ADR-0002) still says 全履歴 for an actor: it is
not shown for a shallow clone. 0.9.1 (L6): each clone here is checked to be really
shallow through `provenance.revision_completeness`, and the project-v1 detail layer
has its windows pinned too.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core.report_v2 import _window_text
from tep_core.v2_constants import HISTORY_WINDOW_PREFIX

AS_OF = "2026-08-31"
RHYTHM_START = "2026-03-04"


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


def _clones(tmp_path: Path) -> tuple[Path, Path]:
    source = init_repo(tmp_path / "full")
    for index in range(30):
        day = f"2026-06-{index + 1:02d}"
        commit(
            source,
            email="alice@example.com",
            date=day,
            message=f"feat: {index}",
            filename="src/api/svc.py",
            name="Alice",
        )
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "22", f"file://{source}", str(shallow)], check=True
    )
    return source, shallow


def test_the_history_window_is_not_called_whole() -> None:
    assert _window_text(f"{HISTORY_WINDOW_PREFIX}{AS_OF}") == f"{AS_OF} までの履歴"


def test_a_shallow_clone_detail_layer_does_not_claim_the_whole_history(tmp_path: Path) -> None:
    _source, shallow = _clones(tmp_path)
    report = json.loads(_cli(["repo", str(shallow), "--as-of", AS_OF, "--format", "json"]))
    assert report["provenance"]["revision_completeness"]["shallow"] is True
    markdown = _cli(["repo", str(shallow), "--as-of", AS_OF, "--format", "md"])
    assert "全履歴" not in markdown
    assert f"{AS_OF} までの履歴" in markdown


@pytest.mark.parametrize("shallow", [False, True], ids=["full", "shallow"])
def test_the_project_detail_layer_windows_are_pinned(tmp_path: Path, shallow: bool) -> None:
    """The 0.8.0 detail layer of project-v1: surface and verification count the history
    up to the date, the rhythm the 180-day window, whether or not the clone is shallow."""
    repo = _clones(tmp_path)[1 if shallow else 0]
    base = ["project", str(repo), "--as-of", AS_OF]
    report = json.loads(_cli([*base, "--format", "json"]))
    assert report["provenance"]["revision_completeness"]["shallow"] is shallow
    assert report["provenance"]["git_window"]["start"] == RHYTHM_START
    markdown = _cli([*base, "--format", "md"])
    assert f"window={AS_OF} までの履歴 source=git:path" in markdown
    assert f"window={RHYTHM_START}〜{AS_OF} source=git:author_timestamp" in markdown
    assert f"window={AS_OF} までの全履歴" not in markdown
