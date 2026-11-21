"""`grift identity --init` / `--list` (issue #26, v0.9.3).

Falsification pairs kept in this file:

- a raw email must never appear in a generated file (digests only);
- a generated file must load through the same loader a hand-written
  identity-v2 uses, because the writer and the loader share the
  normalisation and the domain-separated digest;
- canonical_id derivation refuses the reserved hash-id shape and characters
  outside ``CANONICAL_ID_PATTERN`` instead of inventing a different rule.
"""

from __future__ import annotations

import errno
import os
import tomllib
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path

import pytest

from git_fixture import commit, init_repo
from tep_cli.__main__ import main
from tep_cli.identity_cmd import run_identity
from tep_cli.options import build_parser
from tep_core.identity import email_identity_sha256, load_identity
from tep_core.identity_init import (
    author_email_counts,
    derive_canonical_id,
    render_empty_template,
    render_identity_template,
)


def _args(**kwargs: object) -> Namespace:
    defaults: dict[str, object] = {
        "command": "identity",
        "repo": None,
        "init": False,
        "out": None,
        "emails": None,
        "canonical_id": None,
        "list_emails": False,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


# --- tep_core.identity_init -------------------------------------------------


def test_render_records_digests_only() -> None:
    text = render_identity_template("alice", ["Alice@Example.com", "alice@example.com"])
    assert "Alice@Example.com" not in text
    assert email_identity_sha256("alice@example.com") in text


def test_generated_template_loads_like_a_hand_written_one() -> None:
    text = render_identity_template("alice", ["Alice@Example.com"])
    config = load_identity(None, _document=tomllib.loads(text))
    actor = config.actors[0]
    assert actor.canonical_id == "alice"
    assert actor.email_sha256 == (email_identity_sha256("alice@example.com"),)
    assert actor.attribution_state == "claimed"
    assert actor.identity_schema_version == "identity-v2"


def test_render_refuses_invalid_canonical_id() -> None:
    with pytest.raises(ValueError):
        render_identity_template("Alice", ["a@example.com"])
    with pytest.raises(ValueError):
        render_identity_template("actor_a1b2c3d4e5f6a7b8", ["a@example.com"])
    with pytest.raises(ValueError):
        render_identity_template("alice", [])


def test_empty_template_round_trips() -> None:
    config = load_identity(None, _document=tomllib.loads(render_empty_template()))
    assert config.actors == ()


def test_derive_canonical_id_cases() -> None:
    assert derive_canonical_id("Alice@Example.com") == "alice"
    assert derive_canonical_id(" alice@example.com ") == "alice"
    assert derive_canonical_id("alice+work@example.com") is None
    assert derive_canonical_id("actor_a1b2c3d4e5f6a7b8@example.com") is None
    assert derive_canonical_id("Example Person@example.com") is None


def test_author_email_counts_are_deterministic(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    for index, email in enumerate(
        ["A@Example.com", "a@example.com", "a@example.com", "b@example.com"]
    ):
        commit(repo, email=email, date=f"2026-01-{index + 2:02d}", message=f"m{index}")
    counts = author_email_counts(repo)
    assert counts == [("a@example.com", 3), ("b@example.com", 1)]


# --- CLI surface ------------------------------------------------------------


def test_init_writes_digest_only_file(tmp_path: Path) -> None:
    out = tmp_path / ".tep" / "identity.toml"
    rc = main(
        [
            "identity",
            "--init",
            "--out",
            str(out),
            "--email",
            "Alice@Example.com",
            "--email",
            "alice@example.com",
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "Alice@Example.com" not in text
    config = load_identity(out)
    actor = config.actors[0]
    assert actor.canonical_id == "alice"
    assert actor.email_sha256 == (email_identity_sha256("alice@example.com"),)
    assert actor.attribution_state == "claimed"


def test_init_without_email_writes_empty_template(tmp_path: Path) -> None:
    out = tmp_path / "identity.toml"
    assert main(["identity", "--init", "--out", str(out)]) == 0
    assert load_identity(out).actors == ()


def test_init_requires_out() -> None:
    assert main(["identity", "--init"]) == 2


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "identity.toml"
    out.write_text("keep me", encoding="utf-8")
    rc = main(["identity", "--init", "--out", str(out), "--email", "a@example.com"])
    assert rc == 2
    assert out.read_text(encoding="utf-8") == "keep me"


def test_init_exclusive_create_refuses_a_concurrent_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "identity.toml"
    operation = "rename" if os.name == "nt" else "link"
    publish = getattr(os, operation)

    def concurrent_winner(staged: Path, destination: Path) -> None:
        # Simulate another initializer winning just before atomic publication.
        assert not destination.exists()
        assert load_identity(staged).actors[0].canonical_id == "alice"
        destination.write_text("created by the other initializer", encoding="utf-8")
        publish(staged, destination)

    monkeypatch.setattr(os, operation, concurrent_winner)
    rc = main(["identity", "--init", "--out", str(out), "--email", "alice@example.com"])

    assert rc == 2
    assert "refusing to overwrite existing file" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "created by the other initializer"
    assert list(tmp_path.iterdir()) == [out]


def test_init_can_retry_after_partial_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "identity.toml"
    args = ["identity", "--init", "--out", str(out), "--email", "alice@example.com"]
    original_open = Path.open

    @contextmanager
    def fail_writing_template(path: Path, mode: str, *args: object, **kwargs: object):
        with original_open(path, mode, *args, **kwargs) as stream:
            write = stream.write

            def write_until_full(text: str) -> int:
                write(text[:5])
                stream.flush()
                raise OSError(errno.ENOSPC, "fixture volume full")

            monkeypatch.setattr(stream, "write", write_until_full)
            yield stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", fail_writing_template)
        assert main(args) == 2

    assert "fixture volume full" in capsys.readouterr().err
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []
    assert main(args) == 0
    assert load_identity(out).actors[0].canonical_id == "alice"


def test_init_reports_unsupported_atomic_creation_without_leaving_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "identity.toml"
    args = ["identity", "--init", "--out", str(out)]
    operation = "rename" if os.name == "nt" else "link"

    def unsupported(staged: Path, destination: Path) -> None:
        assert load_identity(staged).actors == ()
        assert not destination.exists()
        raise OSError(errno.ENOTSUP, "fixture filesystem")

    with monkeypatch.context() as patch:
        patch.setattr(os, operation, unsupported)
        assert main(args) == 2

    assert "retry with --out" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
    assert main(args) == 0
    assert load_identity(out).actors == ()


def test_init_reports_filesystem_errors_as_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("keep", encoding="utf-8")
    out = parent_file / "identity.toml"

    rc = main(["identity", "--init", "--out", str(out), "--email", "a@example.com"])

    assert rc == 2
    stderr = capsys.readouterr().err
    assert "could not write identity file" in stderr
    assert "Traceback" not in stderr
    assert parent_file.read_text(encoding="utf-8") == "keep"


def test_init_requires_id_when_derivation_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "identity",
            "--init",
            "--out",
            str(tmp_path / "identity.toml"),
            "--email",
            "alice+work@example.com",
        ]
    )
    assert rc == 2
    assert "--id" in capsys.readouterr().err


def test_init_accepts_explicit_id(tmp_path: Path) -> None:
    out = tmp_path / "identity.toml"
    rc = main(
        [
            "identity",
            "--init",
            "--out",
            str(out),
            "--email",
            "alice+work@example.com",
            "--id",
            "alice",
        ]
    )
    assert rc == 0
    assert load_identity(out).actors[0].canonical_id == "alice"


def test_init_rejects_reserved_hash_id(tmp_path: Path) -> None:
    rc = main(
        [
            "identity",
            "--init",
            "--out",
            str(tmp_path / "identity.toml"),
            "--email",
            "a@example.com",
            "--id",
            "actor_a1b2c3d4e5f6a7b8",
        ]
    )
    assert rc == 2


def test_list_orders_by_count_then_email(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = init_repo(tmp_path / "repo")
    for index, email in enumerate(
        ["A@Example.com", "a@example.com", "a@example.com", "b@example.com"]
    ):
        commit(repo, email=email, date=f"2026-01-{index + 2:02d}", message=f"m{index}")
    assert main(["identity", "--list", str(repo)]) == 0
    assert capsys.readouterr().out == "3\ta@example.com\n1\tb@example.com\n"


def test_list_fails_closed_off_a_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["identity", "--list", str(tmp_path)]) == 2
    assert "not a git repository" in capsys.readouterr().err


def test_run_identity_rejects_init_and_list_together() -> None:
    assert run_identity(_args(init=True, list_emails=True, out="x")) == 2
    assert run_identity(_args()) == 2


# --- parser parity ----------------------------------------------------------


def test_parser_exposes_identity_with_init() -> None:
    parser = build_parser()
    args = parser.parse_args(["identity", "--init", "--out", "x.toml", "--email", "a@b.c"])
    assert args.command == "identity"
    assert args.init is True
    assert args.emails == ["a@b.c"]
    assert args.out == Path("x.toml")
