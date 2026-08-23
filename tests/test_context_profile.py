"""context_profile v2 tests: classification parity, ruling §5, rails.

The push-copy-fork violation corpus: a fork whose history contains upstream
authors MUST NOT count them in resolved_human_actors (ruling §5 — the
original incident counted "186 authors" from un-excluded upstream work).
"""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.context_profile import CONTEXT_DEFINITION_VERSION
from tep_core.identity import empty_identity, load_identity
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo, merge_commit


def _profile(tmp_path: Path, *, scope: str = "repo", fork: bool = False):
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="founder@example.com",
        date="2020-01-02",
        message="feat: initial",
        filename="app.py",
    )
    for index in range(30):
        commit(
            repo,
            email="founder@example.com",
            date=f"2021-{index % 12 + 1:02d}-05",
            message=f"feat(core): work {index}",
            filename=f"src/mod{index % 4}.py",
        )
        if index % 3 == 0:
            commit(
                repo,
                email="founder@example.com",
                date=f"2021-{index % 12 + 1:02d}-06",
                message=f"test: cover {index} (refs #{100 + index})",
                filename=f"tests/test_mod{index % 4}.py",
            )
    for name in ("alice", "bob"):
        for index in range(6):
            commit(
                repo,
                email=f"{name}@example.com",
                date=f"2022-{index + 1:02d}-10",
                message=f"fix(mod): {name} {index}",
                filename="src/mod1.py",
            )
    merge_commit(repo, email="founder@example.com", date="2022-07-01")
    lineage = Lineage(is_fork=fork, parent="upstream/parent" if fork else None)
    return analyze_repository(repo, empty_identity(), lineage, scope=scope)


def test_classification_and_ratios(tmp_path: Path) -> None:
    report = _profile(tmp_path)
    ctx = report["context_profile"]
    assert ctx["kind"] == "observed"
    assert ctx["definition_version"] == CONTEXT_DEFINITION_VERSION
    assert ctx["resolved_human_actors"]["value"] == 3  # founder + alice + bob
    assert ctx["collaboration_class"]["value"] == "small_team"  # 3 actors <= 5
    assert 0 < ctx["top_actor_share"]["value"] < 1
    assert ctx["pr_flow_share"]["value"] > 0  # the merge commit
    assert ctx["conventional_commit_share"]["value"] > 0.5  # conventional subjects dominate


def test_lifecycle_and_cadence(tmp_path: Path) -> None:
    report = _profile(tmp_path)
    ctx = report["context_profile"]
    assert ctx["lifecycle_stage"]["value"] in {"active", "maintained", "dormant"}
    assert ctx["repo_age_days"]["value"] > 0
    turnover = ctx["actor_turnover"]["value"]
    assert turnover["2020"]["joined"] == 1
    assert turnover["2022"]["joined"] == 2


def test_language_and_monorepo(tmp_path: Path) -> None:
    report = _profile(tmp_path)
    ctx = report["context_profile"]
    assert "py" in ctx["language_composition"]["value"]
    assert ctx["test_file_ratio"]["value"] > 0
    assert ctx["docs_share"]["kind"] == "observed"
    assert isinstance(ctx["dependency_manifests"]["value"], list)


def test_no_names_only_counts(tmp_path: Path) -> None:
    """Rail: no author strings, emails, or identifiers may appear."""
    report = _profile(tmp_path)
    ctx_text = repr(report["context_profile"])
    assert "@" not in ctx_text, "context_profile must not carry author emails"
    assert "founder" not in ctx_text and "alice" not in ctx_text and "bob" not in ctx_text


def test_tenant_scope_still_emits_context(tmp_path: Path) -> None:
    """context_profile is a repo-scope layer: same repo facts regardless of
    evidence scope (it classifies the REPO, not the tenant)."""
    report = _profile(tmp_path, scope="tenant")
    assert report["context_profile"]["kind"] == "observed"
    assert report["context_profile"]["resolved_human_actors"]["value"] == 3


def test_push_copy_fork_excludes_upstream(tmp_path: Path) -> None:
    """Ruling §5 violation corpus: push-copy fork must not count upstream
    authors. Simulated by declaring fork lineage with a tenant identity that
    covers only the post-fork work: pre-fork (upstream) authors classify as
    inherited_upstream and must drop out of resolved_human_actors."""
    import subprocess

    repo = init_repo(tmp_path / "repo")
    # upstream history (pre-fork authors)
    for index in range(10):
        commit(
            repo,
            email=f"upstream{index % 3}@example.com",
            date=f"2020-0{index % 9 + 1}-10",
            message=f"upstream work {index}",
            filename=f"src/up{index}.py",
        )
    # tenant (post-fork) work
    for index in range(8):
        commit(
            repo,
            email="tenant@example.com",
            date=f"2026-0{index + 1}-10",
            message=f"tenant work {index}",
            filename=f"src/own{index}.py",
        )
    identity_path = tmp_path / "identity.toml"
    identity_path.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "tenant"\n'
        'emails = ["tenant@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    identity = load_identity(identity_path)
    fork = Lineage(is_fork=True, parent="upstream/parent")
    report = analyze_repository(repo, identity, fork, scope="repo")
    ctx = report["context_profile"]
    # Upstream authors (3) excluded; only the tenant side counts.
    assert ctx["resolved_human_actors"]["value"] == 1, (
        "push-copy fork must not count upstream authors in "
        "resolved_human_actors (the 2026-08 fork incident: 186 raw authors)"
    )
    raw = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%ae"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.lower()
    raw_authors = len({line.strip() for line in raw.splitlines() if line.strip()})
    assert raw_authors == 4  # 3 upstream + 1 tenant (the forbidden raw number)
    assert ctx["resolved_human_actors"]["value"] < raw_authors


def test_report_v1_existing_keys_unchanged(tmp_path: Path) -> None:
    """Rail (ruling 受入③): context_profile is additive; existing keys intact."""
    report = _profile(tmp_path)
    for key in (
        "schema_version",
        "provenance",
        "repository",
        "identity",
        "lineage",
        "origin",
        "attribution",
        "activity",
        "core_activity_period",
        "test_frameworks",
        "test_cochange",
        "rework",
        "survival",
        "interpretation",
    ):
        assert key in report, f"existing key {key} lost"
