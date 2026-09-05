"""Consent and pair-commit regressions for controlled contribution artifacts."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import tep_core.contribute as contribute_module
from tep_cli.__main__ import main
from tep_core.contribute import prepare_contribution, write_controlled_contribution_atomic

from test_v060_contribution_profiles import _governance, _report


class _NonTTY(io.StringIO):
    def isatty(self) -> bool:
        return False


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _controlled_cli_args(
    tmp_path: Path, profile: str, *, yes: bool
) -> tuple[list[str], Path, Path]:
    report_path = tmp_path / "inputs" / "report.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    manifest: dict[str, object] = {"governance": _governance()}
    if profile == "raw":
        manifest["raw_material"] = {
            "mailmap": {
                "before": "Alias <alias@example.com>",
                "after": "Alice <alice@example.com>",
            },
            "object_ids": [{"algorithm": "sha1", "value": "a" * 40}],
            "provider_manifest": {"coverage": "complete"},
        }
    manifest_path = tmp_path / "inputs" / "study.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    payload_path = tmp_path / "controlled" / f"{profile}.json"
    sidecar_path = tmp_path / "controlled" / f"{profile}.sidecar.json"
    args = [
        "contribute",
        str(report_path),
        "--privacy",
        profile,
        "--door",
        "controlled",
        "--study-manifest",
        str(manifest_path),
        "--controlled-sidecar",
        str(sidecar_path),
        "--out",
        str(payload_path),
    ]
    if profile == "masked":
        key_path = tmp_path / "inputs" / "study.key"
        key_path.write_bytes(bytes(range(32)))
        key_path.chmod(0o600)
        args.extend(["--key-file", str(key_path)])
    if yes:
        args.append("--yes")
    return args, payload_path, sidecar_path


def _aggregate_cli_args(report_path: Path, *, output: Path | None = None) -> list[str]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    args = [
        "contribute",
        str(report_path),
        "--privacy",
        "aggregate",
        "--door",
        "local",
        "--yes",
    ]
    if output is not None:
        args.extend(["--out", str(output)])
    return args


@pytest.mark.parametrize("report", [None, [], "report", 1])
def test_prepare_contribution_rejects_non_object_json_roots(report: object) -> None:
    with pytest.raises(ValueError, match="report must be a JSON object"):
        prepare_contribution(report, privacy="aggregate", door="local")


def test_contribute_cli_rejects_non_object_json_root_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("[]\n", encoding="utf-8")
    output = tmp_path / "contribution.json"

    assert (
        main(
            [
                "contribute",
                str(report_path),
                "--privacy",
                "aggregate",
                "--door",
                "local",
                "--out",
                str(output),
                "--yes",
            ]
        )
        == 2
    )
    assert not output.exists()
    assert "report must be a JSON object" in capsys.readouterr().err


@pytest.mark.parametrize("profile", ["masked", "raw"])
def test_controlled_non_tty_refusal_writes_neither_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    profile: str,
) -> None:
    args, payload_path, sidecar_path = _controlled_cli_args(tmp_path, profile, yes=False)
    monkeypatch.setattr(sys, "stdin", _NonTTY())

    assert main(args) == 2
    assert not payload_path.exists()
    assert not sidecar_path.exists()
    assert not payload_path.parent.exists()
    assert "interactive confirmation required" in capsys.readouterr().err


def test_controlled_interactive_decline_writes_neither_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, payload_path, sidecar_path = _controlled_cli_args(tmp_path, "raw", yes=False)
    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    assert main(args) == 1
    assert not payload_path.exists()
    assert not sidecar_path.exists()
    assert not payload_path.parent.exists()
    assert "nothing was written" in capsys.readouterr().err


@pytest.mark.parametrize("profile", ["masked", "raw"])
def test_consented_controlled_pair_is_private(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    profile: str,
) -> None:
    args, payload_path, sidecar_path = _controlled_cli_args(tmp_path, profile, yes=True)

    assert main(args) == 0
    assert stat.S_IMODE(payload_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(sidecar_path.stat().st_mode) == 0o600
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["privacy_profile"] == profile
    assert sidecar["privacy_profile"] == profile
    if profile == "raw":
        assert "alias@example.com" in json.dumps(payload)
    captured = capsys.readouterr()
    terminal_text = captured.out + captured.err
    assert "controlled contribution payload summary" in captured.out
    assert "controlled payload was written locally" in captured.err
    assert "Full controlled payload is not printed" in captured.out
    assert "the private output file is the complete payload" in terminal_text
    assert "The payload above is the entirety of the submission" not in terminal_text
    for secret in (
        "alias@example.com",
        "alice@example.com",
        "actor_alice",
        '"raw_material"',
        bytes(range(32)).hex(),
    ):
        assert secret not in terminal_text


def test_prepare_controlled_contribution_has_no_filesystem_side_effect(
    tmp_path: Path,
) -> None:
    sidecar_path = tmp_path / "not-created" / "sidecar.json"
    bundle = prepare_contribution(
        _report(),
        privacy="raw",
        door="controlled",
        controlled_context=_governance(),
        controlled_sidecar=sidecar_path,
        raw_material={"mailmap": {"before": "A <a@example.com>", "after": "A"}},
    )

    assert bundle.controlled_sidecar is not None
    assert not sidecar_path.exists()
    assert not sidecar_path.parent.exists()


def test_controlled_pair_second_install_failure_leaves_neither_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_path = tmp_path / "payload.json"
    sidecar_path = tmp_path / "sidecar.json"
    real_replace = os.replace

    def fail_sidecar_install(source: str | bytes, destination: str | bytes) -> None:
        if Path(destination) == sidecar_path and ".stage-" in Path(source).name:
            raise OSError("injected sidecar install failure")
        real_replace(source, destination)

    monkeypatch.setattr(contribute_module.os, "replace", fail_sidecar_install)
    with pytest.raises(OSError, match="injected sidecar install failure"):
        write_controlled_contribution_atomic(
            payload_path=payload_path,
            payload={"private": "payload"},
            sidecar_path=sidecar_path,
            sidecar={"private": "sidecar"},
        )

    assert not payload_path.exists()
    assert not sidecar_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_controlled_pair_failure_restores_both_previous_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_path = tmp_path / "payload.json"
    sidecar_path = tmp_path / "sidecar.json"
    payload_path.write_text("old payload\n", encoding="utf-8")
    sidecar_path.write_text("old sidecar\n", encoding="utf-8")
    real_replace = os.replace

    def fail_sidecar_install(source: str | bytes, destination: str | bytes) -> None:
        if Path(destination) == sidecar_path and ".stage-" in Path(source).name:
            raise OSError("injected sidecar install failure")
        real_replace(source, destination)

    monkeypatch.setattr(contribute_module.os, "replace", fail_sidecar_install)
    with pytest.raises(OSError, match="injected sidecar install failure"):
        write_controlled_contribution_atomic(
            payload_path=payload_path,
            payload={"private": "new payload"},
            sidecar_path=sidecar_path,
            sidecar={"private": "new sidecar"},
        )

    assert payload_path.read_text(encoding="utf-8") == "old payload\n"
    assert sidecar_path.read_text(encoding="utf-8") == "old sidecar\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["payload.json", "sidecar.json"]


def test_aggregate_leaf_symlink_cannot_overwrite_victim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    victim = tmp_path / "victim.json"
    victim.write_text("owner data\n", encoding="utf-8")
    output = tmp_path / "contribution.json"
    output.symlink_to(victim)
    args = _aggregate_cli_args(tmp_path / "inputs" / "report.json", output=output)

    assert main(args) == 2
    assert output.is_symlink()
    assert victim.read_text(encoding="utf-8") == "owner data\n"
    assert "must not be a symlink" in capsys.readouterr().err


def test_default_grift_parent_symlink_cannot_escape_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    victim = victim_dir / "contribution.json"
    victim.write_text("owner data\n", encoding="utf-8")
    (repository / ".grift").symlink_to(victim_dir, target_is_directory=True)
    args = _aggregate_cli_args(repository / "inputs" / "report.json")
    monkeypatch.chdir(repository)

    assert main(args) == 2
    assert (repository / ".grift").is_symlink()
    assert victim.read_text(encoding="utf-8") == "owner data\n"
    assert "must not traverse a symlink" in capsys.readouterr().err


def test_controlled_parent_symlink_writes_neither_private_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, payload_path, sidecar_path = _controlled_cli_args(tmp_path, "raw", yes=True)
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    payload_path.parent.symlink_to(victim_dir, target_is_directory=True)

    assert main(args) == 2
    assert payload_path.parent.is_symlink()
    assert list(victim_dir.iterdir()) == []
    assert "must not traverse a symlink" in capsys.readouterr().err
