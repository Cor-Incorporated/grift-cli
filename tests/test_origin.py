"""Identity loader and origin classification falsification tests."""

from __future__ import annotations

from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.identity import load_identity
from tep_core.lineage import Lineage
from tep_core.origin import classify_commits
from tep_core.gitutil import read_commits

from git_fixture import commit, init_repo, merge_commit


def _write_identity(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_empty_identity_is_pending_and_unresolved(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="alice@acme.test", date="2026-01-02", message="one")
    identity = load_identity(None)
    assert identity.pending_attribution is True
    report = analyze_repository(repo, identity, Lineage(), include_files=False)
    assert report["identity"]["pending_attribution"] is True
    assert report["origin"]["tenant_unique"]["value"] == 0
    assert report["origin"]["unresolved"]["value"] == 1
    assert report["origin"]["ambiguous_origin"]["value"] == 0
    assert report["origin"]["inherited_upstream"]["value"] == 0


def test_no_builtin_org_fallback(tmp_path: Path) -> None:
    """A well-known corporate domain must not become tenant without identity."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="member@example.com", date="2026-01-02", message="one")
    report = analyze_repository(repo, load_identity(None), Lineage(), include_files=False)
    assert report["origin"]["tenant_unique"]["value"] == 0
    assert report["identity"]["pending_attribution"] is True


def test_cross_tenant_identity_not_applied(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="alice@acme.test", date="2026-01-02", message="alice")
    ident_a = _write_identity(
        tmp_path / "a.toml",
        """
schema_version = "identity-v1"
[[actors]]
canonical_id = "alice"
emails = ["alice@acme.test"]
attribution_state = "verified"
""",
    )
    ident_b = _write_identity(
        tmp_path / "b.toml",
        """
schema_version = "identity-v1"
[[actors]]
canonical_id = "bob"
emails = ["bob@other.test"]
attribution_state = "verified"
""",
    )
    with_a = analyze_repository(repo, load_identity(ident_a), Lineage(), include_files=False)
    with_b = analyze_repository(repo, load_identity(ident_b), Lineage(), include_files=False)
    assert with_a["origin"]["tenant_unique"]["value"] == 1
    assert with_b["origin"]["tenant_unique"]["value"] == 0
    assert with_b["origin"]["unresolved"]["value"] == 1
    assert with_b["origin"]["ambiguous_origin"]["value"] == 0


def test_lineage_marks_non_tenant_as_inherited_upstream(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="oss@example.com", date="2024-01-01", message="upstream")
    identity = load_identity(
        _write_identity(
            tmp_path / "id.toml",
            """
schema_version = "identity-v1"
[[actors]]
canonical_id = "local"
emails = ["local@tenant.test"]
attribution_state = "verified"
""",
        )
    )
    no_lineage = classify_commits(read_commits(repo), identity, Lineage())
    with_lineage = classify_commits(
        read_commits(repo), identity, Lineage(is_fork=True, parent="org/upstream")
    )
    assert no_lineage.counts["inherited_upstream"] == 0
    assert no_lineage.counts["unresolved"] == 1
    assert no_lineage.counts["ambiguous_origin"] == 0
    assert with_lineage.counts["inherited_upstream"] == 1
    assert with_lineage.counts["unresolved"] == 0
    assert with_lineage.counts["ambiguous_origin"] == 0


def test_vendor_only_commit_is_generated_or_vendor(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="alice@acme.test",
        date="2026-01-02",
        message="vendor",
        filename="vendor/lib.js",
        content="/* third party */\n",
    )
    ident = _write_identity(
        tmp_path / "id.toml",
        """
schema_version = "identity-v1"
[[actors]]
canonical_id = "alice"
emails = ["alice@acme.test"]
attribution_state = "verified"
""",
    )
    report = analyze_repository(repo, load_identity(ident), Lineage(), include_files=True)
    assert report["origin"]["generated_or_vendor"]["value"] == 1
    assert report["origin"]["tenant_unique"]["value"] == 0


def test_bot_excluded_from_origin(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(
        repo,
        email="dependabot[bot]@users.noreply.github.com",
        date="2026-01-02",
        message="bump",
    )
    report = analyze_repository(repo, load_identity(None), Lineage(), include_files=False)
    assert report["attribution"]["bot"]["value"] == 1
    assert report["origin"]["bot"]["value"] == 1
    assert report["origin"]["unresolved"]["value"] == 0
    assert report["origin"]["ambiguous_origin"]["value"] == 0
    assert report["origin"]["tenant_unique"]["value"] == 0


def test_first_party_merge_is_tenant_merge_not_upstream_sync(tmp_path: Path) -> None:
    """H-1 / P0-d-2: non-lineage tenant merges are PR flow, not upstream."""
    repo = init_repo(tmp_path / "repo")
    ident = _write_identity(
        tmp_path / "id.toml",
        """
schema_version = "identity-v1"
[[actors]]
canonical_id = "alice"
emails = ["alice@acme.test"]
attribution_state = "verified"
""",
    )
    commit(repo, email="alice@acme.test", date="2026-01-01", message="base")
    merge_commit(repo, email="alice@acme.test", date="2026-01-02")
    report = analyze_repository(repo, load_identity(ident), Lineage(), include_files=False)
    assert report["origin"]["tenant_merge_or_sync"]["kind"] == "observed"
    assert report["origin"]["tenant_merge_or_sync"]["value"] == 1
    assert report["origin"]["upstream_sync"]["kind"] == "not_observed"
    assert report["origin"]["upstream_sync"]["reason"] == "no_upstream_lineage"


def test_lineage_tenant_merge_is_upstream_sync(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    ident = _write_identity(
        tmp_path / "id.toml",
        """
schema_version = "identity-v1"
[[actors]]
canonical_id = "alice"
emails = ["alice@acme.test"]
attribution_state = "verified"
""",
    )
    commit(repo, email="alice@acme.test", date="2026-01-01", message="base")
    merge_commit(repo, email="alice@acme.test", date="2026-01-02")
    report = analyze_repository(
        repo,
        load_identity(ident),
        Lineage(is_fork=True, parent="org/upstream"),
        include_files=False,
    )
    assert report["origin"]["upstream_sync"]["kind"] == "observed"
    assert report["origin"]["upstream_sync"]["value"] == 1
    assert report["origin"]["tenant_merge_or_sync"]["kind"] == "not_observed"


def test_e2_fork_upstream_does_not_enter_tenant(tmp_path: Path) -> None:
    """E2: inherited_upstream must not be counted as tenant_unique."""
    test_lineage_marks_non_tenant_as_inherited_upstream(tmp_path)


def test_e7_unattributed_humans_are_unresolved_not_tenant(tmp_path: Path) -> None:
    """E7: template/copy inflation stays unresolved without identity."""
    test_empty_identity_is_pending_and_unresolved(tmp_path)


def test_empty_email_is_ambiguous_not_unresolved(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="", date="2026-01-02", message="anon")
    report = analyze_repository(repo, load_identity(None), Lineage(), include_files=False)
    assert report["origin"]["ambiguous_origin"]["value"] == 1
    assert report["origin"]["unresolved"]["value"] == 0
