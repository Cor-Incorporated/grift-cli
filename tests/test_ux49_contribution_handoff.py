"""Consent must leave an actionable, destination-aware local handoff.

The handoff printed after consent is only useful if every instruction in it
can be carried out. A v2 payload records its door, so a ``door=local`` draft
is rejected by the public intake whatever it is renamed to; a purpose that
``PURPOSE_DOORS`` keeps away from ``public-pr`` cannot be rebuilt for the
intake at all; and ``--open`` commits and pushes on the submitter's behalf.
These tests pin what each of those cases may and may not print.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tep_cli.__main__ import _open_browser as real_open_browser
from tep_cli.__main__ import _open_submission_flow as real_open_submission_flow
from tep_cli.__main__ import main
from tep_core import contribution_v2
from tep_core.contribution_v2 import PURPOSE_DOORS, PURPOSES

from test_v060_contribute_atomic_consent import _controlled_cli_args
from test_v060_contribution_profiles import _report

INTAKE = "https://github.com/Cor-Incorporated/tep-contributions"
PUBLIC_DOOR_URL = f"{INTAKE}/blob/main/README.en.md#submitting-via-the-public-door"
PROXY_DOOR_URL = f"{INTAKE}/blob/main/README.en.md#the-identity-private-door"
META_KEYS = {"id", "sha256", "received_at", "door"}
# Every line shape that names a concrete public submission. None of them may
# appear for a payload the public intake would reject.
PUBLIC_SUBMISSION_MARKERS = (
    "提出ID / submission_id:",
    "PR payload:",
    "PR metadata:",
    "payloads/",
    ".meta.json",
    "meta / manifest row",
    '"door":"pr"',
    "#submitting-via-the-public-door",
    "#the-identity-private-door",
)
V1_REPORT: dict[str, Any] = {
    "schema_version": "report-v1",
    "provenance": {"analysis_scope": "repo", "definition_version": "x"},
}


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _no_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("local contribution must not send or open a browser")

    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", refuse)
    monkeypatch.setattr("tep_cli.__main__._open_browser", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)


def _write_default_report(tmp_path: Path, report: dict[str, Any] | None = None) -> None:
    report_path = tmp_path / ".grift" / "report.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps(_report() if report is None else report), encoding="utf-8")


def _handoff(err: str) -> str:
    """The stderr printed after the payload was written (the disclosure is excluded)."""
    _before, marker, after = err.partition("payload written to")
    assert marker, f"payload was not reported as written:\n{err}"
    return after


def _meta_row(handoff: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in handoff.splitlines() if line.startswith('{"id":')]
    assert len(rows) == 1, f"expected exactly one meta row, got {rows}"
    return rows[0]


def _public_markers(handoff: str) -> list[str]:
    return [marker for marker in PUBLIC_SUBMISSION_MARKERS if marker in handoff]


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("door", ["local", "public-pr"])
def test_default_file_and_copyable_handoff_after_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interactive: bool,
    door: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    args = ["contribute"]
    if door != "local":
        args += ["--door", door]
    if interactive:
        monkeypatch.setattr(sys, "stdin", _TTY())
        monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    else:
        args += ["--yes"]

    assert main(args) == 0
    target = tmp_path / ".grift" / "contribution.json"
    written = target.read_bytes()
    payload = json.loads(written)
    assert payload["door"] == door
    digest = hashlib.sha256(written).hexdigest()
    handoff = _handoff(capsys.readouterr().err)
    assert "nothing was sent" in handoff
    if door == "local":
        # The intake rejects a door=local v2 payload, and the receipt id is
        # random per build: an id, path or meta row from this run would never
        # match the payload a rebuild produces.
        assert _public_markers(handoff) == []
        assert not any(line.startswith('{"id":') for line in handoff.splitlines())
        assert digest not in handoff
        assert "not submission-ready" in handoff
        assert "--door public-pr" in handoff
        assert "payload は書き出したファイルをそのまま使用" not in handoff
        return
    row = _meta_row(handoff)
    assert set(row) == META_KEYS
    submission_id = row["id"]
    assert re.fullmatch(r"\d{4}-\d{4}-[0-9a-f]{8}", submission_id)
    assert submission_id.endswith(digest[:8])
    assert row["sha256"] == digest
    assert row["door"] == "pr"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row["received_at"])
    year = row["received_at"][:4]
    assert f"提出ID / submission_id: {submission_id}" in handoff
    assert f"PR payload: payloads/{year}/{submission_id}.json" in handoff
    assert f"PR metadata: payloads/{year}/{submission_id}.meta.json" in handoff
    assert "manifest.jsonl は編集・追加不要" in handoff
    assert f"公開ドア URL: {PUBLIC_DOOR_URL}" in handoff
    assert f"身元を伏せる代理PR URL: {PROXY_DOOR_URL}" in handoff
    assert "payload自体は最終的に公開" in handoff
    assert "not submission-ready" not in handoff
    assert "自動でコミット済み" not in handoff
    assert "copy-ready metadata" in handoff


def test_declined_contribution_has_no_file_or_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    assert main(["contribute", str(report_path)]) == 1
    assert not (tmp_path / ".grift" / "contribution.json").exists()
    assert "PR payload:" not in capsys.readouterr().err


@pytest.mark.parametrize("door", ["local", "controlled"])
@pytest.mark.parametrize("profile", ["masked", "raw"])
def test_controlled_payload_does_not_receive_public_handoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], profile: str, door: str
) -> None:
    # masked/raw are controlled profiles whichever door they were built for;
    # `--door local` must not route them into the public handoff.
    args, target, sidecar = _controlled_cli_args(tmp_path, profile, yes=True)
    args[args.index("--door") + 1] = door
    assert main(args) == 0
    assert target.is_file() and sidecar.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["door"] == door
    captured = capsys.readouterr()
    handoff = _handoff(captured.err)
    assert "controlled payload was written locally" in handoff
    assert _public_markers(handoff) == []
    assert "--door public-pr" not in handoff
    for secret in ("alias@example.com", "alice@example.com", "actor_alice"):
        assert secret not in captured.out + captured.err


def test_purpose_without_public_door_gets_no_public_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)

    assert main(["contribute", "--purpose", "outcome-linkage", "--yes"]) == 0
    handoff = _handoff(capsys.readouterr().err)
    assert "local payload only" in handoff
    assert "--door public-pr" not in handoff
    assert _public_markers(handoff) == []
    lines = [line for line in handoff.splitlines() if "public intake" in line]
    assert len(lines) == 1, f"expected one public-intake line, got {lines}"
    assert "'outcome-linkage'" in lines[0]
    assert "cannot be submitted to the public intake" in lines[0]
    assert "公開受け口に提出できません" in lines[0]


@pytest.mark.parametrize("purpose", sorted(PURPOSES))
def test_rebuild_advice_is_accepted_by_the_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    purpose: str,
) -> None:
    """The guidance and the door check are two statements of PURPOSE_DOORS.

    Whatever the local run advises must be what the next run accepts: if it
    says to rebuild with ``--door public-pr``, that rebuild must exit 0.
    """
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    reachable = "public-pr" in PURPOSE_DOORS[purpose]

    assert main(["contribute", "--purpose", purpose, "--yes"]) == 0
    handoff = _handoff(capsys.readouterr().err)
    advised = "--door public-pr" in handoff
    assert advised == reachable, (
        f"purpose {purpose!r}: PURPOSE_DOORS public-pr={reachable}, guidance advised={advised}"
    )
    rebuilt = main(["contribute", "--purpose", purpose, "--door", "public-pr", "--yes"])
    rebuilt_err = capsys.readouterr().err
    assert (rebuilt == 0) == advised, (
        f"purpose {purpose!r}: advised={advised} but the rebuild exited {rebuilt}: "
        f"{rebuilt_err.strip().splitlines()[-1]}"
    )


@pytest.mark.parametrize(
    ("purpose", "public_pr"),
    [("outcome-linkage", True), ("reference-distributions", False)],
)
def test_public_guidance_follows_purpose_doors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    purpose: str,
    public_pr: bool,
) -> None:
    """Flip PURPOSE_DOORS and the guidance must follow (no purpose name is hard-coded)."""
    doors = {"local", "controlled"} | ({"public-pr"} if public_pr else set())
    monkeypatch.setitem(contribution_v2.PURPOSE_DOORS, purpose, frozenset(doors))
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)

    assert main(["contribute", "--purpose", purpose, "--yes"]) == 0
    handoff = _handoff(capsys.readouterr().err)
    assert ("--door public-pr" in handoff) is public_pr
    assert ("cannot be submitted to the public intake" in handoff) is not public_pr
    assert _public_markers(handoff) == []


def test_open_guidance_describes_the_push_before_the_flow_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    calls: list[dict[str, Any]] = []

    def flow(payload_text: str, submission_id: str, digest: str, now: Any, target: Path) -> None:
        # Read what was printed up to the moment the push flow starts.
        calls.append(
            {
                "printed": capsys.readouterr().err,
                "payload_text": payload_text,
                "submission_id": submission_id,
                "digest": digest,
                "year": now.year,
                "target": target,
            }
        )

    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", flow)

    assert main(["contribute", "--open", "--yes"]) == 0
    after = capsys.readouterr().err
    assert len(calls) == 1, "--open must call the submission flow exactly once"
    call = calls[0]
    written = (tmp_path / ".grift" / "contribution.json").read_text(encoding="utf-8")
    assert call["payload_text"] == written
    assert call["target"].resolve() == tmp_path / ".grift" / "contribution.json"
    assert call["digest"] == hashlib.sha256(written.encode("utf-8")).hexdigest()
    before = _handoff(call["printed"])
    # The guidance is printed before the flow and names what the flow commits.
    row = _meta_row(before)
    assert row["id"] == call["submission_id"] and row["sha256"] == call["digest"]
    path = f"payloads/{call['year']}/{call['submission_id']}"
    assert f"PR payload: {path}.json" in before
    assert f"PR metadata: {path}.meta.json" in before
    assert "--open" in before
    assert "commit" in before and "push" in before and "fork" in before
    assert "手でファイルを追加する必要はありません" in before
    assert "no manual file adding" in before
    # The push path must not claim that nothing is sent, nor ask for manual adding.
    for text in (before, after):
        assert "nothing was sent" not in text
        assert "何も送信していません" not in text
        assert "payload は書き出したファイルをそのまま使用" not in text
        assert "meta行は .meta.json に保存します" not in text
    assert after == "", f"nothing may be printed after the flow returns: {after!r}"


def test_v1_report_is_not_a_local_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """report-v1 payloads carry no door, so they keep the copy-ready metadata."""
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path, V1_REPORT)

    assert main(["contribute", "--yes"]) == 0
    written = (tmp_path / ".grift" / "contribution.json").read_bytes()
    payload = json.loads(written)
    assert payload["contribution_schema"] == "tep-contribution-v1"
    assert "door" not in payload
    handoff = _handoff(capsys.readouterr().err)
    row = _meta_row(handoff)
    assert set(row) == META_KEYS
    assert row["sha256"] == hashlib.sha256(written).hexdigest()
    assert f"PR payload: payloads/{row['received_at'][:4]}/{row['id']}.json" in handoff
    assert "copy-ready metadata" in handoff
    assert "not submission-ready" not in handoff
    assert "--door public-pr" not in handoff


def _run_open_without_automation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    failing_tools: bool,
) -> tuple[str, Path]:
    """Run `contribute --open --out <custom>` through the real flow with gh/git unusable."""
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", opened.append)
    if failing_tools:
        monkeypatch.setattr(shutil, "which", lambda name: f"/fake/{name}")

        def broken(*_args: object, **_kwargs: object) -> None:
            raise OSError("fixture: gh/git cannot run")

        monkeypatch.setattr(subprocess, "run", broken)
    else:
        monkeypatch.setattr(shutil, "which", lambda name: None)
    target = tmp_path / "out dir" / "custom payload.json"
    target.parent.mkdir()
    assert main(["contribute", "--open", "--yes", "--out", str(target)]) == 0
    assert len(opened) == 1 and "tep-contributions" in opened[0]
    return capsys.readouterr().err, target


@pytest.mark.parametrize("failing_tools", [False, True], ids=["gh-missing", "flow-failed"])
def test_open_fallback_names_the_file_that_was_written_and_its_meta_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failing_tools: bool,
) -> None:
    """When the automated push cannot run, the manual steps must work for this payload.

    The fallback used to name `.grift/contribution.json` whatever `--out` said (a stale file there
    would be attached instead of the payload that was just consented to), gave no meta row, and
    after a failed flow gave no steps at all although the guidance printed before had promised
    that nothing needed adding by hand.
    """
    err, target = _run_open_without_automation(
        tmp_path, monkeypatch, capsys, failing_tools=failing_tools
    )
    digest = hashlib.sha256(target.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    assert "To submit by hand" in err, f"the fallback gave no manual steps:\n{err}"
    printed, _, steps = err.rpartition("To submit by hand")
    copy_ready = _meta_row(_handoff(printed))  # what this run showed before the flow started
    assert copy_ready["sha256"] == digest
    assert [json.loads(line) for line in steps.splitlines() if line.startswith('{"id":')] == [
        copy_ready
    ], f"the steps carry a different row than the copy-ready one:\n{steps}"
    path = f"payloads/{copy_ready['received_at'][:4]}/{copy_ready['id']}"
    assert f"PR payload: {path}.json" in printed
    assert shlex.quote(str(target)) in steps, "the written file must be named, quoted"
    assert f"{path}.json" in steps and f"{path}.meta.json" in steps, steps
    assert "contribution.json" not in steps, "the default path is not the file that was written"


def _fake_gh_and_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    no_browser_opener: bool = False,
    opener_returncode: int = 0,
    fail_push: bool = False,
) -> tuple[dict[str, str], list[list[str]]]:
    """Make gh/git succeed without touching a network; record what `git add -A` would commit."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/fake/{name}")
    committed: dict[str, str] = {}
    commands: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[0] in {"open", "xdg-open"}:
            if no_browser_opener:
                raise FileNotFoundError(cmd[0])
            return subprocess.CompletedProcess(cmd, opener_returncode, stdout="", stderr="")
        if "push" in cmd and fail_push:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="! [rejected]")
        if cmd[-2:] == ["add", "-A"]:
            repo = Path(cmd[cmd.index("-C") + 1])
            for file in sorted(path for path in repo.rglob("*") if path.is_file()):
                committed[str(file.relative_to(repo))] = file.read_text(encoding="utf-8")
        stdout = "octocat\n" if cmd[1:3] == ["api", "user"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return committed, commands


def test_the_flow_commits_the_files_and_the_row_the_guidance_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The copy-ready row, the PR file names and the committed sidecar are one fact, not three."""
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", lambda url: opened.append(url) or True)
    committed, _commands = _fake_gh_and_git(monkeypatch)

    assert main(["contribute", "--open", "--yes"]) == 0
    handoff = _handoff(capsys.readouterr().err)
    row = _meta_row(handoff)
    path = f"payloads/{row['received_at'][:4]}/{row['id']}"
    assert f"PR payload: {path}.json" in handoff and f"PR metadata: {path}.meta.json" in handoff
    assert sorted(committed) == [f"{path}.json", f"{path}.meta.json"]
    assert json.loads(committed[f"{path}.meta.json"]) == row
    written = (tmp_path / ".grift" / "contribution.json").read_text(encoding="utf-8")
    assert committed[f"{path}.json"] == written
    assert row["sha256"] == hashlib.sha256(written.encode("utf-8")).hexdigest()
    assert len(opened) == 1 and opened[0].startswith(
        "https://github.com/Cor-Incorporated/tep-contributions/compare/"
    )


def test_after_a_successful_push_a_missing_browser_opener_is_not_a_manual_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The branch is already on the fork: sending the user to submit by hand opens a second PR.

    On a host with no xdg-open (SSH, container) the opener raised after the push, the failure
    handler printed the by-hand steps, and its own browser call raised again, uncaught.
    """
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", real_open_browser)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    committed, commands = _fake_gh_and_git(monkeypatch, no_browser_opener=True)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert any(cmd[:2] == ["/fake/git", "-C"] and "push" in cmd for cmd in commands)
    assert committed, "the flow must have committed the payload before the opener failed"
    assert "To submit by hand" not in err, err
    assert "could not open a browser" in err
    assert "browser opened" not in err, err
    compare = [line for line in err.splitlines() if line.startswith("https://github.com/")]
    assert compare and "/compare/" in compare[-1], err
    assert "pushed to your fork" in err


def test_any_failure_after_the_push_points_at_the_pull_request_page_not_at_manual_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)

    def broken_opener(_url: str) -> bool:
        raise RuntimeError("fixture: the opener failed after the push")

    monkeypatch.setattr("tep_cli.__main__._open_browser", broken_opener)
    committed, commands = _fake_gh_and_git(monkeypatch)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert committed and any("push" in cmd for cmd in commands)
    assert "already pushed to your fork" in err and "do not submit by hand" in err
    assert "To submit by hand" not in err, err
    assert [line for line in err.splitlines() if "/compare/" in line], err


def test_an_opener_that_exits_non_zero_is_not_reported_as_a_browser_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """xdg-open exits 3 on a host with xdg-utils but no display; `open` fails without a session.

    The command was started, so the old check called it a success, printed "browser opened" and
    never showed the PR creation page URL that the docs promise after a failure.
    """
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", real_open_browser)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    _fake_gh_and_git(monkeypatch, opener_returncode=3)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert "browser opened" not in err, err
    assert "xdg-open exited 3" in err
    assert [line for line in err.splitlines() if "/compare/" in line], err
    assert "To submit by hand" not in err, err


def test_a_rejected_push_still_gets_the_manual_steps_not_the_already_pushed_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only a push that succeeded makes submitting by hand a duplicate.

    Setting the flag before the push (or never testing it) would tell a user whose push was
    rejected that the branch is on the fork, with a page that does not exist.
    """
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", lambda _url: True)
    _committed, commands = _fake_gh_and_git(monkeypatch, fail_push=True)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert any("push" in cmd for cmd in commands)
    assert "To submit by hand" in err, err
    assert "already pushed" not in err, err


def test_without_gh_or_a_browser_the_fallback_does_not_claim_the_browser_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", real_open_browser)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    _fake_gh_and_git(monkeypatch, no_browser_opener=True)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert "could not open a browser" in err
    assert "opened the intake repository in your browser" not in err, err
    assert "To submit by hand" in err


def test_an_opener_that_exits_zero_is_reported_as_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The success path through the real opener: every other opener test here is a failure."""
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", real_open_browser)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    _committed, commands = _fake_gh_and_git(monkeypatch, opener_returncode=0)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert any(cmd[0] == "xdg-open" for cmd in commands)
    assert "browser opened at the PR creation page" in err, err
    assert "could not open a browser" not in err, err
    assert "To submit by hand" not in err, err


def test_without_gh_but_with_a_browser_the_fallback_says_the_browser_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_default_report(tmp_path)
    monkeypatch.setattr("tep_cli.__main__._open_submission_flow", real_open_submission_flow)
    monkeypatch.setattr("tep_cli.__main__._open_browser", real_open_browser)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    _committed, commands = _fake_gh_and_git(monkeypatch, opener_returncode=0)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert main(["contribute", "--open", "--yes"]) == 0
    err = capsys.readouterr().err
    assert any(cmd[0] == "xdg-open" for cmd in commands)
    assert "opened the intake repository in your browser" in err, err
    assert "could not open a browser" not in err, err
    assert "To submit by hand" in err
