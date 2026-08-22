"""F-P10-3: producer-side canonical_id validation + no-@ export property.

Adversarial inputs (the exact three shapes from ACCEPTANCE addendum11):
empty, @-containing, and duplicate canonical_id must be REJECTED with
IdentityValidationError / non-zero exit — never silently accepted. And the
property test: whenever analyze exits 0, the export contains zero '@' bytes
regardless of identity content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tep_core.identity import (
    CANONICAL_ID_PATTERN,
    CANONICAL_ID_PATTERN_VERSION,
    IdentityValidationError,
    load_identity,
)
from tep_cli.__main__ import main

from git_fixture import commit, init_repo

ROOT = Path(__file__).resolve().parents[1]


# --- doc <-> code parity (recipe-test style) ------------------------------


def test_schema_doc_regex_matches_implementation_verbatim() -> None:
    text = (ROOT / "docs" / "identity-schema.md").read_text(encoding="utf-8")
    fenced = re.findall(r"```\n(\^.*\$)\n```", text)
    assert fenced, "identity-schema.md must carry the canonical_id regex in a fenced block"
    assert fenced[0] == CANONICAL_ID_PATTERN, (
        f"schema doc regex {fenced[0]!r} != implementation {CANONICAL_ID_PATTERN!r}"
    )
    assert CANONICAL_ID_PATTERN_VERSION == 1


# --- the three adversarial shapes -----------------------------------------


def _identity_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "identity.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_reject_empty_canonical_id(tmp_path: Path) -> None:
    path = _identity_file(
        tmp_path,
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = ""\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
    )
    with pytest.raises(IdentityValidationError, match="empty"):
        load_identity(path)


def test_reject_at_containing_canonical_id(tmp_path: Path) -> None:
    path = _identity_file(
        tmp_path,
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "leak@example.com"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
    )
    with pytest.raises(IdentityValidationError, match="invalid canonical_id"):
        load_identity(path)


def test_reject_duplicate_canonical_id(tmp_path: Path) -> None:
    path = _identity_file(
        tmp_path,
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n\n'
        '[[actors]]\ncanonical_id = "alice"\nemails = ["b@example.com"]\n'
        'attribution_state = "claimed"\n',
    )
    with pytest.raises(IdentityValidationError, match="duplicate"):
        load_identity(path)


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "leak@example.com",
        "Alice",  # uppercase
        " has-space",  # whitespace
        "tab\there",  # control char inside
        "-leading-dash",  # must start with lowercase alnum
        ".dot",  # must start with lowercase alnum
        "a" * 65,  # length ceiling (64 max)
        "user/name",  # path separator
        "id#hash",
    ],
)
def test_reject_invalid_canonical_id_shapes(tmp_path: Path, bad_id: str) -> None:
    body = (
        f'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = {json.dumps(bad_id)}\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n'
    )
    with pytest.raises(IdentityValidationError):
        load_identity(_identity_file(tmp_path, body))


def test_accept_valid_canonical_ids(tmp_path: Path) -> None:
    body = (
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n\n'
        '[[actors]]\ncanonical_id = "dev.bob_1"\nemails = ["b@example.com"]\n'
        'attribution_state = "claimed"\n'
    )
    identity = load_identity(_identity_file(tmp_path, body))
    assert identity.actor_count == 2


# --- CLI: non-zero exit, no files written ---------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="leak@example.com", date="2026-01-02", message="one")
    return repo


@pytest.mark.parametrize(
    "body",
    [
        '[[actors]]\ncanonical_id = ""\nemails = ["a@example.com"]\nattribution_state = "verified"\n',
        '[[actors]]\ncanonical_id = "leak@example.com"\nemails = ["a@example.com"]\nattribution_state = "verified"\n',
        '[[actors]]\ncanonical_id = "alice"\nemails = ["a@example.com"]\nattribution_state = "verified"\n'
        '[[actors]]\ncanonical_id = "alice"\nemails = ["b@example.com"]\nattribution_state = "claimed"\n',
    ],
    ids=["empty", "at-containing", "duplicate"],
)
def test_cli_rejects_adversarial_identity_with_nonzero_exit(
    tmp_path: Path, body: str, capsys: object
) -> None:
    repo = _repo(tmp_path)
    identity_path = _identity_file(tmp_path, body)
    out_dir = tmp_path / "export"
    code = main(
        [
            "analyze",
            str(repo),
            "--identity",
            str(identity_path),
            "--format",
            "json",
            "--export",
            str(out_dir),
        ]
    )
    assert code != 0
    captured = capsys.readouterr()
    assert "identity validation error" in captured.err
    # No export may be written from an invalid identity.
    assert not out_dir.exists()


# --- property test: exit 0 ==> zero '@' bytes in export -------------------


def test_property_exit0_implies_no_at_bytes_in_export(tmp_path: Path) -> None:
    """The reproducing setup from ACCEPTANCE addendum11, inverted.

    An identity whose canonical_id is valid must still yield exports with
    zero '@' bytes even when commit author emails contain '@'. Combined with
    the rejection tests above: no identity content can make '@' leak.
    """
    repo = _repo(tmp_path)
    identity_path = _identity_file(
        tmp_path,
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["leak@example.com"]\nattribution_state = "verified"\n',
    )
    out_dir = tmp_path / "export"
    code = main(
        [
            "analyze",
            str(repo),
            "--identity",
            str(identity_path),
            "--format",
            "json",
            "--export",
            str(out_dir),
        ]
    )
    assert code == 0
    for name in ("commits.ndjson", "actors.json", "export-meta.json"):
        raw = (out_dir / name).read_bytes()
        assert b"@" not in raw, f"{name} leaked an email-shaped string"


def test_golden_identity_still_loads() -> None:
    identity = load_identity(ROOT / "golden" / "identity" / "G1-click.toml")
    assert identity.actor_count >= 1
    assert all(
        CANONICAL_ID_PATTERN and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", a.canonical_id)
        for a in identity.actors
    )
