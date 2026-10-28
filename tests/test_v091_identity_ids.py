"""v0.9.1: a hash id, a declared id and an author name never share one actor id.

grift gives a cluster without a declared identity a hash id ``actor_<32 hex>``.
#92 stopped a *name slug* from taking a declared identity's id. Two older
paths still let two different people meet on one id:

- M5: an identity file could declare ``canonical_id = "actor_<32 hex>"``. When
  that id was another cluster's hash id (copied from ``--all`` output with an
  email that does not belong to that cluster), the consented role profile
  counted the other cluster's commits as the declared actor's.
- L11: an author whose *name* was another cluster's hash id got that id as a
  name slug, and the analysis stopped with exit 2 ("actor id collision").

L10: a collection with a same-name person can only be verified with the same
identity it was written with. The collection now records the identity digest,
so verify names the identity instead of a bare partition MISMATCH.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
from pathlib import Path

import pytest
from git_fixture import git, init_repo

from tep_cli.__main__ import main
from tep_core.attribution import ACTOR_ID_PATTERN, stable_actor_hash
from tep_core.identity import (
    RESERVED_ACTOR_HASH_PATTERN,
    RESERVED_ACTOR_HASH_RE,
    IdentityValidationError,
    identity_digest,
    load_identity,
)

ROOT = Path(__file__).resolve().parents[1]


def _identity_text(canonical_id: str, email: str) -> str:
    return (
        'schema_version = "identity-v2"\n\n[[actors]]\n'
        f'canonical_id = "{canonical_id}"\nemails = ["{email}"]\n'
        'attribution_state = "claimed"\nconsent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n'
    )


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _commit(repo: Path, name: str, email: str, index: int) -> None:
    path = repo / "src" / "a.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((path.read_text(encoding="utf-8") if path.exists() else "") + f"{index}\n")
    when = f"2026-06-{index % 28 + 1:02d}T12:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": when,
    }
    git(repo, "add", "src/a.py", env=env)
    git(repo, "commit", "-q", "-m", f"feat: a {index}", env=env)


def _two_alices(tmp_path: Path) -> Path:
    """Two people named "Alice" with different emails: both get hash ids."""

    repo = init_repo(tmp_path / "alices")
    for index in range(10):
        _commit(repo, "Alice", "alice.a@example.org", index)
    for index in range(10, 25):
        _commit(repo, "Alice", "alice.b@example.org", index)
    return repo


def _directory(repo: Path) -> list[dict]:
    code, out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 0, err
    return json.loads(out)["actor_directory"]["actors"]


def _hash_id_with(repo: Path, commit_count: int) -> str:
    rows = [row for row in _directory(repo) if row["commit_count"] == commit_count]
    assert len(rows) == 1, rows
    assert RESERVED_ACTOR_HASH_RE.fullmatch(rows[0]["actor_id"]), rows
    return str(rows[0]["actor_id"])


# --- the reserved shape is the shape grift gives to clusters ----------------


def test_the_reserved_shape_is_the_hash_id_shape_of_the_actor_id_pattern() -> None:
    produced = stable_actor_hash("email\0someone@example.com", repo_scope_digest="0" * 64)
    assert RESERVED_ACTOR_HASH_RE.fullmatch(produced), (produced, RESERVED_ACTOR_HASH_PATTERN)
    body = RESERVED_ACTOR_HASH_PATTERN.removeprefix("^").removesuffix("$")
    assert body in ACTOR_ID_PATTERN, (RESERVED_ACTOR_HASH_PATTERN, ACTOR_ID_PATTERN)


@pytest.mark.parametrize("doc", ["docs/identity-schema.md", "docs/en/identity-schema.md"])
def test_identity_schema_docs_carry_the_reserved_shape_verbatim(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    fenced = re.findall(r"```\n(\^.*\$)\n```", text)
    assert RESERVED_ACTOR_HASH_PATTERN in fenced, (doc, fenced, RESERVED_ACTOR_HASH_PATTERN)


# --- M5: a declared id cannot take the hash-id shape -------------------------


@pytest.mark.parametrize("bad_id", ["actor_0123456789abcdef0123456789abcdef", "actor_0123456789ab"])
def test_identity_refuses_a_declared_id_of_the_hash_form(tmp_path: Path, bad_id: str) -> None:
    path = tmp_path / "identity.toml"
    path.write_text(_identity_text(bad_id, "carol@example.com"), encoding="utf-8")
    with pytest.raises(IdentityValidationError) as caught:
        load_identity(path)
    message = str(caught.value)
    assert bad_id in message and "reserved" in message, message


@pytest.mark.parametrize("good_id", ["actor_alice", "actor-0123456789abcdef0123456789abcdef"])
def test_identity_still_accepts_ids_that_only_look_alike(tmp_path: Path, good_id: str) -> None:
    path = tmp_path / "identity.toml"
    path.write_text(_identity_text(good_id, "carol@example.com"), encoding="utf-8")
    assert [actor.canonical_id for actor in load_identity(path).actors] == [good_id]


def test_an_identity_that_declares_another_clusters_hash_id_is_refused(tmp_path: Path) -> None:
    repo = _two_alices(tmp_path)
    other = _hash_id_with(repo, 15)
    identity = tmp_path / "identity.toml"
    identity.write_text(_identity_text(other, "carol@example.com"), encoding="utf-8")
    argv = ["actor", other, str(repo), "--identity", str(identity), "--as-of", "2026-08-31"]
    code, out, err = _run([*argv, "--format", "json"])
    facts: dict = {"code": code, "stderr": err.strip()[-300:]}
    if code == 0:
        report = json.loads(out)
        dimensions = report["role_profile"].get("dimensions") or {}
        work = (dimensions.get("work_type") or {}).get("create") or {}
        facts["own_commits"] = report["activity"]["tenant_commits"]["value"]
        facts["role_denominator"] = work.get("denominator")
    assert code == 2, facts
    assert other in err and "reserved" in err, facts
    assert out == "", facts


# --- L11: an author name of the hash-id shape keeps its own hash id ----------


def test_an_author_named_like_another_clusters_hash_id_does_not_stop_the_analysis(
    tmp_path: Path,
) -> None:
    repo = _two_alices(tmp_path)
    taken = _hash_id_with(repo, 10)
    # Index 27 is the latest date (06-28), so the window still holds every commit.
    _commit(repo, taken, "mallory@example.org", 27)
    code, out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 0, err.strip()[-300:]
    rows = json.loads(out)["actor_directory"]["actors"]
    ids = [row["actor_id"] for row in rows]
    assert len(ids) == len(set(ids)), ids
    by_count = {row["commit_count"]: row for row in rows}
    assert by_count[10]["actor_id"] == taken, rows
    named = by_count[1]
    assert named["actor_id"] != taken, rows
    assert RESERVED_ACTOR_HASH_RE.fullmatch(named["actor_id"]), rows
    assert named["display_name"] == taken, rows


# --- L10: a collection records which identity it was written with ------------


def _namesake(tmp_path: Path) -> tuple[Path, Path]:
    """alice is declared with no commits; another "Alice" has 25 commits."""

    repo = init_repo(tmp_path / "namesake")
    for index in range(25):
        _commit(repo, "Alice", "alice.other@example.org", index)
    identity = tmp_path / "identity.toml"
    identity.write_text(_identity_text("alice", "alice@example.com"), encoding="utf-8")
    return repo, identity


def _collection(repo: Path, out: Path, identity: Path | None) -> dict:
    argv = ["actor", str(repo), "--all", "--format", "json", "--out", str(out)]
    if identity is not None:
        argv += ["--identity", str(identity)]
    code, _out, err = _run(argv)
    assert code == 0, err.strip()[-300:]
    return json.loads((out / "repo-report.json").read_text(encoding="utf-8"))["provenance"]


def _verify(directory: Path, repo: Path, identity: Path | None) -> tuple[int, str]:
    argv = ["verify", str(directory), "--repo", str(repo)]
    if identity is not None:
        argv += ["--identity", str(identity)]
    code, out, _err = _run(argv)
    return code, out.strip()


def test_verify_names_the_identity_when_a_collection_is_checked_without_it(
    tmp_path: Path,
) -> None:
    repo, identity = _namesake(tmp_path)
    provenance = _collection(repo, tmp_path / "collection", identity)
    recorded = identity_digest(load_identity(identity))
    assert provenance.get("identity_digest") == recorded, provenance

    code, out = _verify(tmp_path / "collection", repo, identity)
    assert (code, out.split(":")[0]) == (0, "VERIFIED"), out
    code, out = _verify(tmp_path / "collection", repo, None)
    assert code == 1, out
    assert "identity differs" in out and str(recorded) in out and "observed none" in out, out


def test_a_collection_without_identity_records_none_and_verify_says_so(tmp_path: Path) -> None:
    repo, identity = _namesake(tmp_path)
    provenance = _collection(repo, tmp_path / "collection", None)
    assert "identity_digest" not in provenance, provenance

    code, out = _verify(tmp_path / "collection", repo, None)
    assert (code, out.split(":")[0]) == (0, "VERIFIED"), out
    code, out = _verify(tmp_path / "collection", repo, identity)
    assert code == 1, out
    assert "records no identity_digest" in out, out
    assert str(identity_digest(load_identity(identity))) in out, out
    # The same MISMATCH can come from another cause; the note must not claim it.
    assert "may be the cause" in out, out


def test_an_old_collection_written_with_identity_gets_a_note_when_verified_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, identity = _namesake(tmp_path)
    # grift 0.9.0 recorded no identity_digest in a collection, even with --identity.
    monkeypatch.setattr("tep_core.analyze_v2.identity_digest", lambda _identity: None)
    provenance = _collection(repo, tmp_path / "collection", identity)
    monkeypatch.undo()
    assert "identity_digest" not in provenance, provenance

    code, out = _verify(tmp_path / "collection", repo, identity)
    assert (code, out.split(":")[0]) == (0, "VERIFIED"), out
    code, out = _verify(tmp_path / "collection", repo, None)
    assert code == 1, out
    assert "note:" in out and "0.9.0 or earlier" in out and "--identity FILE" in out, out


def test_a_collection_verify_with_an_identity_that_cannot_load_cannot_verify(
    tmp_path: Path,
) -> None:
    repo, _identity = _namesake(tmp_path)
    _collection(repo, tmp_path / "collection", None)
    reserved = "actor_0123456789abcdef0123456789abcdef"
    bad = tmp_path / "bad-identity.toml"
    bad.write_text(_identity_text(reserved, "carol@example.com"), encoding="utf-8")
    code, out = _verify(tmp_path / "collection", repo, bad)
    # Same answer as a saved report's verify: the input is unusable, not different.
    assert code == 2, out
    assert out.startswith("CANNOT_VERIFY: identity cannot be loaded:"), out
    assert reserved in out, out


@pytest.mark.parametrize("doc", ["docs/usage.md", "docs/en/usage.md", "docs/report-v2.md"])
def test_docs_quote_the_identity_item_verify_prints(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert "`identity (recorded identity_digest …, observed …)`" in text, doc


# --- the leftover collision names the id it saw -----------------------------


def test_an_actor_id_collision_names_the_observed_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _two_alices(tmp_path)
    constant = "actor_00000000000000000000000000000000"
    # Two same-name clusters both fall back to hash ids; make them equal.
    monkeypatch.setattr("tep_core.attribution.stable_actor_hash", lambda *_a, **_k: constant)
    code, _out, err = _run(["repo", str(repo), "--format", "json"])
    assert code == 2, err
    assert f"(observed {constant!r})" in err, err
