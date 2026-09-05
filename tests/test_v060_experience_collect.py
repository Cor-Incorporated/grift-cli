"""Fixed-OID Git collection falsification for experience/role inputs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import tep_core.experience_collect as experience_collect
from tep_core.experience import TenantConsent, build_experience
from tep_core.experience_collect import ExperienceHistoryIncomplete, collect_experience_inputs
from tep_core.identity import email_identity_sha256


def _git(repo: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2025-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2025-01-01T00:00:00Z",
        },
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def _commit(repo: Path, subject: str, *, body: str | None = None) -> str:
    message = subject if body is None else f"{subject}\n\n{body}"
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-F", "-", input_text=message)
    return _git(repo, "rev-parse", "HEAD")


def _fixture_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = tmp_path / "experience-repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Alice Example")
    _git(repo, "config", "user.email", "Alice@Example.com")

    source = repo / "src"
    source.mkdir()
    (source / "base.py").write_text("one\ntwo\n", encoding="utf-8")
    (source / "readd.py").write_text("old\n", encoding="utf-8")
    oids = [_commit(repo, "feat: initial")]

    _git(repo, "mv", "src/base.py", "src/renamed.py")
    oids.append(_commit(repo, "refactor: rename"))
    _git(repo, "tag", "-a", "v1.0.0", oids[-1], "-m", "release")

    shutil.copyfile(source / "renamed.py", source / "copied.py")
    oids.append(
        _commit(
            repo,
            "feat: copy",
            body=(
                "A complete body that must survive collection.\n\n"
                "AI-Assisted-By: codex\n"
                "Co-authored-by: Bob <bob@example.com>"
            ),
        )
    )

    (source / "readd.py").unlink()
    oids.append(_commit(repo, "refactor: delete"))

    (source / "readd.py").write_text("new\nbody\nhere\n", encoding="utf-8")
    oids.append(_commit(repo, "feat: re-add"))
    _git(repo, "tag", "latest", oids[-1])
    return repo, oids


def test_collects_exact_statuses_bodies_tags_and_size_snapshots(tmp_path: Path) -> None:
    repo, oids = _fixture_repo(tmp_path)
    actor_map = {oid: "alice" for oid in oids}

    result = collect_experience_inputs(
        repo,
        sha_to_actor=actor_map,
        tagger_actor_by_email={"alice@example.com": "alice"},
        snapshot_actor_ids=("alice",),
    )

    assert result.target_oid.algorithm == "sha1"
    assert result.target_oid.value == oids[-1]
    assert [row.oid for row in result.commits] == oids
    assert [row.sequence for row in result.commits] == list(range(5))
    assert all(row.actor_id == "alice" for row in result.commits)
    assert all(
        row.parents == (() if index == 0 else (oids[index - 1],))
        for index, row in enumerate(result.commits)
    )

    root_changes = {(row.status, row.path) for row in result.commits[0].changes}
    assert root_changes == {("A", "src/base.py"), ("A", "src/readd.py")}
    assert result.commits[1].changes == (
        experience_collect.FileChange(
            "R", "src/renamed.py", old_path="src/base.py", similarity=100
        ),
    )
    # A copy whose source is untouched in the same commit is reported as an
    # addition. Attributing it as "C" needed `--find-copies-harder`, which was
    # removed: it cost ~100x on large repositories and was the sole cause of the
    # collection timeout on an 11,982-commit repository, while every consumer
    # already treats "A" and "C" identically (experience.py:861,1001,1004 and
    # role_profile.py:150,171). Removing it left all 133 checked-in actor cards
    # byte-identical. See tests/test_v060_large_repo_degradation.py, which pins
    # that equivalence with a fixture proven to exercise the flag.
    assert result.commits[2].changes == (experience_collect.FileChange("A", "src/copied.py"),)
    assert result.commits[3].changes == (experience_collect.FileChange("D", "src/readd.py"),)
    assert result.commits[4].changes == (experience_collect.FileChange("A", "src/readd.py"),)

    full_message = result.commits[2].message
    assert "A complete body that must survive collection." in full_message
    assert "AI-Assisted-By: codex" in full_message
    assert "Co-authored-by: Bob <bob@example.com>" in full_message

    snapshots = {
        row.sequence: (
            row.repository_commit_count_after,
            row.repository_file_count_after,
            row.repository_line_count_after,
        )
        for row in result.commits
        if row.repository_file_count_after is not None
    }
    assert snapshots == {0: (1, 2, 3), 2: (3, 3, 5), 4: (5, 3, 7)}

    assert [
        (tag.name, tag.annotated, tag.tagger_actor_id, tag.target_oid)
        for tag in result.release_tags
    ] == [
        ("latest", False, None, oids[-1]),
        ("v1.0.0", True, "alice", oids[1]),
    ]


def test_hash_only_identity_can_attribute_annotated_tagger(tmp_path: Path) -> None:
    repo, oids = _fixture_repo(tmp_path)
    result = collect_experience_inputs(
        repo,
        sha_to_actor={oid: "alice" for oid in oids},
        tagger_actor_by_email_sha256={email_identity_sha256("alice@example.com"): "alice"},
    )
    annotated = next(tag for tag in result.release_tags if tag.annotated)
    assert annotated.tagger_actor_id == "alice"


def test_real_shallow_repository_is_rejected_before_metrics(tmp_path: Path) -> None:
    source, _oids = _fixture_repo(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth=1", f"file://{source}", str(shallow)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    with pytest.raises(ExperienceHistoryIncomplete, match="shallow repository"):
        collect_experience_inputs(shallow)


def test_promisor_repository_is_rejected_even_when_current_objects_exist(tmp_path: Path) -> None:
    repo, _oids = _fixture_repo(tmp_path)
    _git(repo, "remote", "add", "partial", "https://example.invalid/repo.git")
    _git(repo, "config", "remote.partial.promisor", "true")
    with pytest.raises(ExperienceHistoryIncomplete, match="promisor repository"):
        collect_experience_inputs(repo)


def test_global_promisor_config_does_not_taint_a_complete_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _oids = _fixture_repo(tmp_path)
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        '[remote "partial"]\n\tpromisor = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))

    result = collect_experience_inputs(repo)

    assert result.commits


def test_missing_reachable_object_is_history_incomplete(tmp_path: Path) -> None:
    repo, _oids = _fixture_repo(tmp_path)
    missing = _git(repo, "rev-parse", "HEAD^")
    object_path = repo / ".git" / "objects" / missing[:2] / missing[2:]
    assert object_path.is_file()
    object_path.unlink()
    with pytest.raises(ExperienceHistoryIncomplete, match="history_incomplete"):
        collect_experience_inputs(repo)


def test_merge_added_secondary_lineage_inherits_creator_deterministically(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "branched"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    base_branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    _git(repo, "config", "user.name", "Carol")
    _git(repo, "config", "user.email", "carol@example.com")
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    root = _commit(repo, "feat: root")
    _git(repo, "branch", "side")

    _git(repo, "config", "user.name", "Alice")
    _git(repo, "config", "user.email", "alice@example.com")
    (repo / "main.py").write_text("main\n", encoding="utf-8")
    main = _commit(repo, "feat: main")

    _git(repo, "checkout", "--quiet", "side")
    _git(repo, "config", "user.name", "Bob")
    _git(repo, "config", "user.email", "bob@example.com")
    (repo / "side.py").write_text("side\n", encoding="utf-8")
    side = _commit(repo, "feat: side")

    _git(repo, "checkout", "--quiet", base_branch)
    _git(repo, "config", "user.name", "Alice")
    _git(repo, "config", "user.email", "alice@example.com")
    _git(repo, "merge", "--quiet", "--no-ff", "-m", "merge side", "side")
    merge = _git(repo, "rev-parse", "HEAD")
    (repo / "side.py").write_text("side changed\n", encoding="utf-8")
    touch = _commit(repo, "feat: touch side")

    actor_map = {
        root: "carol",
        main: "alice",
        side: "bob",
        merge: "alice",
        touch: "alice",
    }
    collection = collect_experience_inputs(repo, sha_to_actor=actor_map)
    merge_row = next(row for row in collection.commits if row.oid == merge)
    assert merge_row.changes == (experience_collect.FileChange("A", "side.py"),)
    metric = build_experience(
        collection.commits,
        actor_id="alice",
        consent=TenantConsent("alice", "test"),
        min_population=1,
    )["metrics"]["cross_author_modification_share"]
    assert (metric["numerator"], metric["denominator"], metric["value"]) == (1, 1, 1.0)


def test_all_collection_git_processes_disable_lazy_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, oids = _fixture_repo(tmp_path)
    original_run = subprocess.run
    observed: list[str | None] = []

    def recording_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        observed.append(environment.get("GIT_NO_LAZY_FETCH"))
        return original_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(experience_collect.subprocess, "run", recording_run)
    collect_experience_inputs(repo, sha_to_actor={oid: "alice" for oid in oids})
    assert observed
    assert set(observed) == {"1"}


def test_sha256_repository_uses_generic_object_ids(tmp_path: Path) -> None:
    repo = tmp_path / "sha256-repo"
    repo.mkdir()
    init = subprocess.run(
        ["git", "-C", str(repo), "init", "--quiet", "--object-format=sha256"],
        capture_output=True,
        text=True,
    )
    if init.returncode:
        pytest.skip("installed Git does not support SHA-256 repositories")
    _git(repo, "config", "user.name", "SHA User")
    _git(repo, "config", "user.email", "sha@example.com")
    (repo / "README.md").write_text("sha256\n", encoding="utf-8")
    oid = _commit(repo, "feat: sha256")

    result = collect_experience_inputs(repo, sha_to_actor={oid: "sha-user"})
    assert result.target_oid.algorithm == "sha256"
    assert len(result.target_oid.value) == 64
    assert result.commits[0].oid == result.target_oid.value
    assert result.commits[0].actor_id == "sha-user"
