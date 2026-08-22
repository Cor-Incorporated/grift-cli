"""export-v1 contract tests: parity with report aggregates, no raw emails."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tep_core.analyze import analyze_repository
from tep_core.export import EXPORT_SCHEMA_VERSION, build_export, config_digest, write_export
from tep_core.identity import empty_identity, load_identity
from tep_core.lineage import Lineage

from git_fixture import commit, git, init_repo, merge_commit

ROOT = Path(__file__).resolve().parents[1]


def commit_many(repo: Path, *, email: str, date: str, message: str, files: dict[str, str]) -> None:
    import os

    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(existing + content, encoding="utf-8")
        git(repo, "add", name)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Author",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": f"{date}T12:00:00",
        "GIT_COMMITTER_NAME": "Author",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": f"{date}T12:00:00",
    }
    git(repo, "commit", "-m", message, env=env)


_IDENTITY_TOML = """schema_version = "identity-v1"

[tenant]
email_patterns = ["@corp\\\\.example\\\\.com$"]

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "verified"

[[actors]]
canonical_id = "bob"
emails = ["bob@example.com"]
attribution_state = "claimed"
"""


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = init_repo(tmp_path / "repo")
    repo.joinpath("pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    tests_dir.joinpath("test_smoke.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    identity_path = tmp_path / "identity.toml"
    identity_path.write_text(_IDENTITY_TOML, encoding="utf-8")
    # alice: co-changed production commit (prod + test in one commit)
    commit_many(
        repo,
        email="alice@example.com",
        date="2026-01-02",
        message="feat: one",
        files={"app.py": "print(1)\n", "tests/test_app.py": "def test_one():\n    assert True\n"},
    )
    # alice: production without test (cochange false), then a fix subject
    commit(
        repo, email="alice@example.com", date="2026-01-03", message="feat: two", filename="app.py"
    )
    commit(
        repo, email="alice@example.com", date="2026-01-04", message="fix: three", filename="app.py"
    )
    # bob: revert subject + test-only commit
    commit(
        repo,
        email="bob@example.com",
        date="2026-02-01",
        message="Revert: feat: two",
        filename="app.py",
    )
    commit(
        repo,
        email="bob@example.com",
        date="2026-02-02",
        message="test: more",
        filename="tests/test_more.py",
    )
    # carol: pattern-inferred tenant without an actor row (actor must be null)
    commit(
        repo,
        email="carol@corp.example.com",
        date="2026-02-03",
        message="feat: carol",
        filename="app.py",
    )
    # bot
    commit(repo, email="bot[bot]@users.noreply.github.com", date="2026-02-04", message="chore: bot")
    # merge by alice (tenant_merge_or_sync; no file list in git log --name-only)
    merge_commit(repo, email="alice@example.com", date="2026-02-05")
    return repo, identity_path


def _build(tmp_path: Path, *, scope: str = "tenant") -> tuple[dict, dict]:
    repo, identity_path = _fixture(tmp_path)
    identity = load_identity(identity_path)
    report = analyze_repository(repo, identity, Lineage(), scope=scope)
    export = build_export(repo, identity, Lineage(), scope=scope)
    return report, export


def test_origin_parity_ndjson_vs_report(tmp_path: Path) -> None:
    """Acceptance (1): per-commit origin counts must equal report aggregates."""
    report, export = _build(tmp_path)
    counts: dict[str, int] = {}
    for row in export["commits"]:
        counts[row["origin"]] = counts.get(row["origin"], 0) + 1
    for name, obs in report["origin"].items():
        if obs.get("kind") != "observed":
            continue
        assert counts.get(name, 0) == obs["value"], f"origin parity broke at {name}"


def test_no_raw_email_leak(tmp_path: Path) -> None:
    """Acceptance (2): zero '@' bytes in commits.ndjson and actors.json."""
    _report, export = _build(tmp_path)
    out = tmp_path / "export"
    write_export(export, out)
    for name in ("commits.ndjson", "actors.json"):
        raw = (out / name).read_bytes()
        assert b"@" not in raw, f"{name} leaked an email-shaped string"
    meta = json.loads((out / "export-meta.json").read_text(encoding="utf-8"))
    assert meta["schema"] == EXPORT_SCHEMA_VERSION
    assert len(meta["config_digest"]) == 64


def test_row_semantics(tmp_path: Path) -> None:
    _report, export = _build(tmp_path)
    rows = export["commits"]
    assert len(rows) == 9  # 8 explicit + on-feature + merge from the merge fixture
    by_subject = {}
    for row, subject in zip(
        rows,
        [
            "merge",
            "on-feature",
            "chore: bot",
            "feat: carol",
            "test: more",
            "Revert: feat: two",
            "fix: three",
            "feat: two",
            "feat: one",
        ],
        strict=True,
    ):
        by_subject[subject] = row
    merge_row = rows[0]
    assert merge_row["is_merge"] is True
    assert merge_row["origin"] == "tenant_merge_or_sync"
    assert merge_row["cochange"] is None
    bot_row = by_subject["chore: bot"]
    assert bot_row["origin"] == "bot" and bot_row["bot"] is True
    assert bot_row["actor"] is None
    carol_row = by_subject["feat: carol"]
    assert carol_row["origin"] == "tenant_unique"
    assert carol_row["actor"] is None  # pattern-inferred: no canonical_id
    assert by_subject["test: more"]["cochange"] is None  # test-only
    assert by_subject["feat: one"]["cochange"] is True
    assert by_subject["feat: two"]["cochange"] is False
    assert by_subject["fix: three"]["subject_class"] == "fix"
    assert by_subject["Revert: feat: two"]["subject_class"] == "revert"
    assert by_subject["feat: one"]["subject_class"] == "other"


def test_actor_rows_engagement_only(tmp_path: Path) -> None:
    _report, export = _build(tmp_path)
    actors = {a["canonical_id"]: a for a in export["actors"]}
    assert set(actors) == {"alice", "bob"}  # carol (inferred) and bots excluded
    alice = actors["alice"]
    assert alice["attribution_state"] == "verified"
    assert alice["core_period"]["kind"] == "observed"
    assert alice["first_ts"] <= alice["last_ts"]
    tenant_rows = [
        r for r in export["commits"] if r["origin"] == "tenant_unique" and r["actor"] == "alice"
    ]
    assert alice["commits"] == len(tenant_rows)
    assert alice["active_days"] == len({r["ts"] for r in tenant_rows})
    for actor in export["actors"]:
        for key in actor:
            assert key in {
                "canonical_id",
                "attribution_state",
                "commits",
                "active_days",
                "first_ts",
                "last_ts",
                "core_period",
            }, "per-actor quality metrics are forbidden (scorecard rail)"


def test_cochange_recompute_parity(tmp_path: Path) -> None:
    """The WP-G1 ingestion recompute: ndjson must reproduce report aggregates."""
    report, export = _build(tmp_path)
    all_time = report["test_cochange"]["all_time"]
    pop = [
        r for r in export["commits"] if r["origin"] == "tenant_unique" and r["cochange"] is not None
    ]
    co = [r for r in pop if r["cochange"] is True]
    assert len(pop) == all_time["population"]
    assert len(co) == all_time["cochanged"]


def test_cochange_recompute_parity_repo_scope(tmp_path: Path) -> None:
    report, export = _build(tmp_path, scope="repo")
    all_time = report["test_cochange"]["all_time"]
    pop = [
        r
        for r in export["commits"]
        if not r["bot"] and not r["is_merge"] and r["cochange"] is not None
    ]
    co = [r for r in pop if r["cochange"] is True]
    assert len(pop) == all_time["population"]
    assert len(co) == all_time["cochanged"]


def test_config_digest_stable_and_sensitive(tmp_path: Path) -> None:
    repo, identity_path = _fixture(tmp_path)
    identity = load_identity(identity_path)
    digest1 = config_digest(
        identity,
        Lineage(),
        template_provided=False,
        parent_repo_provided=False,
        vendor_scan=False,
        scope="tenant",
    )
    digest2 = config_digest(
        identity,
        Lineage(),
        template_provided=False,
        parent_repo_provided=False,
        vendor_scan=False,
        scope="tenant",
    )
    assert digest1 == digest2
    changed = load_identity(identity_path)
    object.__setattr__(
        changed,
        "actors",
        changed.actors
        + (
            type(changed.actors[0])(
                canonical_id="dave",
                emails=("dave@example.com",),
                github_login=None,
                attribution_state="verified",
            ),
        ),
    )
    changed.__post_init__()
    digest3 = config_digest(
        changed,
        Lineage(),
        template_provided=False,
        parent_repo_provided=False,
        vendor_scan=False,
        scope="tenant",
    )
    assert digest3 != digest1


def test_cli_export_writes_three_files(tmp_path: Path, capsys: object) -> None:
    from tep_cli.__main__ import main

    repo, _identity_path = _fixture(tmp_path)
    out = tmp_path / "export-out"
    code = main(
        [
            "analyze",
            str(repo),
            "--identity",
            str(tmp_path / "identity.toml"),
            "--format",
            "json",
            "--export",
            str(out),
        ]
    )
    assert code == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["actors.json", "commits.ndjson", "export-meta.json"]
    captured = capsys.readouterr()
    assert captured.out.startswith("{")  # stdout purity unchanged by --export
    rows = [
        json.loads(line)
        for line in (out / "commits.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert all(
        r["origin"]
        in {
            "inherited_upstream",
            "upstream_sync",
            "tenant_unique",
            "tenant_merge_or_sync",
            "tenant_derivative",
            "external_upstream_contribution",
            "template_inherited",
            "generated_or_vendor",
            "ambiguous_origin",
            "unresolved",
            "bot",
        }
        for r in rows
    )


@pytest.mark.golden
def test_golden_click_export_parity() -> None:
    """Golden G1: ndjson origin sums == report origin aggregates; no '@' bytes."""
    import test_golden

    pins = {
        p["id"]: p
        for p in tomllib.loads((ROOT / "golden" / "pins.toml").read_text(encoding="utf-8"))["repos"]
    }
    pin = pins["G1-click"]
    dest = ROOT / ".golden-cache" / pin["name"]
    test_golden._ensure_clone(pin["url"], dest, pin["sha"])
    identity = load_identity(ROOT / pin["identity"]) if pin.get("identity") else empty_identity()
    report = analyze_repository(dest, identity, Lineage())
    export = build_export(dest, identity, Lineage())
    counts: dict[str, int] = {}
    for row in export["commits"]:
        counts[row["origin"]] = counts.get(row["origin"], 0) + 1
    for name, obs in report["origin"].items():
        if obs.get("kind") == "observed":
            assert counts.get(name, 0) == obs["value"], f"parity broke at {name}"
    out = ROOT / ".golden-cache" / "export-check"
    write_export(export, out)
    for name in ("commits.ndjson", "actors.json"):
        assert b"@" not in (out / name).read_bytes()
