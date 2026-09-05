from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tep_core.analyze import analyze_repository
from tep_core.experience_collect import ExperienceHistoryIncomplete
from tep_core.identity import load_identity
from tep_core.lineage import Lineage


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_missing_promisor_objects_suppress_experience_without_lazy_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Alice")
    _git(repo, "config", "user.email", "alice@example.test")
    (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "feat: initial")

    identity_path = tmp_path / "identity.toml"
    identity_path.write_text(
        'schema_version = "identity-v2"\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'email_sha256 = ["8d48fbae257e37c4718dcc149cbbe36711728291e43ea88f3bf50f6f9f57f5af"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )

    def unavailable(*args: object, **kwargs: object) -> object:
        raise ExperienceHistoryIncomplete(
            "warning: lazy fetching disabled; some objects may not be available\n"
            "fatal: could not fetch object from promisor remote"
        )

    monkeypatch.setattr("tep_core.experience_collect.collect_experience_inputs", unavailable)
    report = analyze_repository(
        repo,
        load_identity(identity_path),
        Lineage(),
        scope="tenant",
    )

    assert report["experience"]["reason"] == "history_incomplete"
    assert report["role_profile"]["reason"] == "history_incomplete"
    assert "fetch" in report["experience"]["limitations"][0]


def test_real_shallow_history_suppresses_experience_and_role(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Alice")
    _git(source, "config", "user.email", "alice@example.test")
    for index in range(2):
        (source / "app.py").write_text(f"print({index})\n", encoding="utf-8")
        _git(source, "add", "app.py")
        _git(source, "commit", "-qm", f"feat: change {index}")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth=1", f"file://{source}", str(shallow)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"

    identity_path = tmp_path / "identity.toml"
    identity_path.write_text(
        'schema_version = "identity-v2"\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["alice@example.test"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )
    report = analyze_repository(
        shallow,
        load_identity(identity_path),
        Lineage(),
        scope="tenant",
    )
    assert report["experience"]["kind"] == "not_observed"
    assert report["experience"]["reason"] == "history_incomplete"
    assert report["role_profile"]["kind"] == "not_observed"
    assert report["role_profile"]["reason"] == "history_incomplete"
