"""Regression for independent 2026-08-30 repo/actor/public-fetch audit findings."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_core.attribution import build_attribution_index, infer_actor_key
from tep_core.contribute import build_contribution
from tep_core.identity import empty_identity
from tep_core.origin import classify_commits
from tep_core.public_fetch import collect_public_handles
from tep_core.schema import validate_schema
from tep_core.tendency import relationship
from tep_core.lineage import Lineage

from git_fixture import commit, init_repo


def _two_authors(tmp: Path) -> Path:
    repo = init_repo(tmp / "repo")
    (repo / "src").mkdir()
    for index in range(3):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"a {index}",
            filename="src/a.py",
            name="Alice",
        )
    commit(
        repo,
        email="b@example.com",
        date="2026-08-02",
        message="b",
        filename="src/b.py",
        name="Bob",
    )
    return repo


def test_unbound_contributors_endpoint_is_not_collected(tmp_path: Path, capsys) -> None:
    repo = _two_authors(tmp_path)
    pages = {
        "https://github.com/robots.txt": (
            200,
            "User-agent: *\nAllow: /\n",
            {},
        ),
        "https://api.github.com/repos/acme/app/contributors?per_page=100": (
            200,
            json.dumps([{"login": f"user{i}"} for i in range(19)]),
            {},
        ),
        "https://api.github.com/repos/acme/app/commits?per_page=100": (
            200,
            "[]",
            {},
        ),
        "https://api.github.com/repos/acme/app/license": (404, "", {}),
    }

    def transport(url: str):
        for key, value in pages.items():
            if url.startswith(key.split("?")[0]) or url == key:
                return value
        if "commits" in url:
            return 200, "[]", {}
        if "contributors" in url:
            raise AssertionError("contributors endpoint is outside the commit CAS contract")
        return 404, "", {}

    manifest = collect_public_handles(
        "github.com/acme/app", fetch=True, transport=transport, head_sha="abc"
    )
    assert manifest["fetched_login_count"] is None
    assert manifest["commit_login_count"] == 0
    assert manifest["sha_to_login"] == {}
    assert manifest["license_status"] == "not_observed"
    assert manifest["terms_status"] == "not_observed"
    assert any(page.get("digest") for page in manifest["page_digests"])
    identity = empty_identity()
    from tep_core.gitutil import read_commits

    commits = read_commits(repo, include_files=True)
    origin = classify_commits(commits, identity, Lineage())
    index = build_attribution_index(
        commits, origin, identity, sha_to_login=manifest["sha_to_login"]
    )
    public_n = sum(1 for actor in index.actors if actor.display_status == "public_handle")
    assert public_n == 0
    report_out = tmp_path / "report"
    assert main(["repo", str(repo), "--format", "json", "--out", str(report_out)]) == 0
    capsys.readouterr()
    report = json.loads((report_out / "report.json").read_text(encoding="utf-8"))
    assert validate_schema("report-v2", report) == []
    assert all(not actor["public_accounts"] for actor in report["actor_directory"]["actors"])
    project = {
        "provider": "github",
        "host": "github.com",
        "project_id": "R_acme_app",
        "project_path": "acme/app",
    }
    authority = {
        "accounts": [
            {
                "provider": "github",
                "host": "github.com",
                "project_id": "R_acme_app",
                "account_id": "42",
                "basis": "account_holder_explicit",
                "scope": "project_and_account",
                "assertion": "authorized_for_public_research_contribution",
            }
        ]
    }
    try:
        build_contribution(
            report,
            mode="named-public",
            public_project=project,
            public_authority=authority,
        )
        raise AssertionError("empty named-public must not succeed")
    except ValueError as exc:
        assert "not_available" in str(exc)


def test_sha_join_sets_public_handle(tmp_path: Path) -> None:
    repo = _two_authors(tmp_path)
    from tep_core.gitutil import read_commits

    commits = read_commits(repo, include_files=True)
    origin = classify_commits(commits, empty_identity(), Lineage())
    mapping = {commits[0].sha.lower(): "alice-gh"}
    index = build_attribution_index(commits, origin, empty_identity(), sha_to_login=mapping)
    public = [actor for actor in index.actors if actor.display_status == "public_handle"]
    assert public
    assert public[0].display_name == "alice-gh"
    assert all("@" not in actor.display_name for actor in index.actors)


def test_population_keys_reconcile(tmp_path: Path, capsys) -> None:
    repo = _two_authors(tmp_path)
    assert main(["repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    activity = payload["activity"]
    attr = payload["attribution"]
    nonmerge = activity["repo_human_nonmerge_commits"]["value"]
    merge_count = attr["merge_count"]
    including = attr["attribution_human_including_merges"]
    unresolved = attr["attribution_unresolved_commit_count"]
    assert nonmerge + merge_count == including + unresolved
    assert "repo_human_nonmerge_commits" in json.dumps(payload)
    md = main(["repo", str(repo), "--format", "md"])
    assert md == 0
    text = capsys.readouterr().out
    assert "actor 一覧" in text
    assert "merge込み" in text


def test_actor_dir_requires_id_and_aligns(tmp_path: Path, capsys) -> None:
    repo = _two_authors(tmp_path)
    dest = tmp_path / "col"
    assert main(["repo", str(repo), "--actors", "--format", "both", "--out", str(dest)]) == 0
    capsys.readouterr()
    # v0.6 strict collections separate the full repo population from the
    # selected actor set.  The index replaces the legacy actors.json listing.
    assert (dest / "repo-report.json").is_file()
    assert (dest / "actor-index.json").is_file()
    cards = list((dest / "actors").glob("*.json"))
    assert cards
    first = json.loads(cards[0].read_text(encoding="utf-8"))
    assert first["schema_version"] == "actor-card-v1"
    project = tmp_path / "p.toml"
    project.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "x"\n'
        '[requirements.surfaces]\nrequired=["backend"]\n',
        encoding="utf-8",
    )
    pout = tmp_path / "proj"
    assert (
        main(
            [
                "project",
                str(repo),
                "--requirements",
                str(project),
                "--format",
                "json",
                "--out",
                str(pout),
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(
        [
            "align",
            "--actor-dir",
            str(dest),
            "--project-report",
            str(pout / "project.json"),
            "--format",
            "json",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "requires --actor" in err
    actor_id = first["actor_id"]
    code = main(
        [
            "align",
            "--actor-dir",
            str(dest),
            "--actor",
            actor_id,
            "--project-report",
            str(pout / "project.json"),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "本人同意のある identity" not in captured.err
    assert "本人性を証明しません" in captured.err
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "alignment-v1"


def test_project_n_null_is_not_comparable() -> None:
    node = relationship(
        actor_node={"kind": "observed", "value": 4, "unit": "commits"},
        project_node={"kind": "observed", "value": 4, "unit": "commits"},
        declared_node={"kind": "declared", "value": 1, "unit": "commits"},
        windows_comparable=True,
        actor_n=10,
        project_n=None,
    )
    assert node["kind"] == "not_comparable"
    assert node["reason"] == "n_missing"
    assert node.get("direction") != "similar_direction"


def test_commit_pagination_and_offline() -> None:
    calls = []

    def transport(url: str):
        calls.append(url)
        if url.endswith("robots.txt"):
            return 200, "User-agent: *\nAllow: /\n", {}
        if "page=2" in url or url.endswith("page=2"):
            return (
                200,
                json.dumps(
                    [
                        {
                            "sha": "b" * 40,
                            "author": {
                                "id": 2,
                                "login": "bob",
                                "html_url": "https://github.com/bob",
                            },
                        }
                    ]
                ),
                {},
            )
        if "/commits" in url:
            return (
                200,
                json.dumps(
                    [
                        {
                            "sha": "a" * 40,
                            "author": {
                                "id": 1,
                                "login": "alice",
                                "html_url": "https://github.com/alice",
                            },
                        }
                    ]
                ),
                {
                    "Link": (
                        "<https://api.github.com/repos/acme/app/commits?sha="
                        + ("0" * 40)
                        + '&per_page=100&page=2>; rel="next"'
                    )
                },
            )
        if "/contributors" in url:
            raise AssertionError("contributors endpoint is outside the commit CAS contract")
        if "/license" in url:
            return 404, "", {}
        return 404, "", {}

    manifest = collect_public_handles(
        "github.com/acme/app", fetch=True, transport=transport, head_sha="abc"
    )
    assert manifest["pagination"]["pages"] >= 2
    assert len(manifest["sha_to_login"]) == 2
    assert all(
        "digest" in page for page in manifest["page_digests"] if "/commits" in page.get("url", "")
    )
    offline = collect_public_handles("github.com/acme/app", fetch=False)
    assert offline["robots_status"] == "fetch_not_requested"
    assert offline["sha_to_login"] == {}


def test_email_author_name_key_is_not_public_handle() -> None:
    key = infer_actor_key(
        email="x@example.com",
        name="x@example.com",
        identity=empty_identity(),
        sha_login=None,
    )
    assert key[2] != "public_handle"
    assert "@" not in key[1]


def test_independent_golden_invariants() -> None:
    golden = Path("benchmarks/v060/data/independent_repo_actor_audit_2026-08-30.json")
    data = json.loads(golden.read_text(encoding="utf-8"))
    cf = data["scenarios"][2]["observed"]["cloudflare-os"]
    vite = data["scenarios"][2]["observed"]["vite"]
    assert cf["fetched_handles"] == 19
    assert cf["actor_display_status_public_handle"] == 0
    assert vite["fetched_handles"] == 30
    assert vite["actor_display_status_public_handle"] == 0
    pop = data["scenarios"][1]["observed"]["cloudflare-os"]
    assert pop["repo_commits"] + pop["merge_count"] == pop["attributed_commit_count"]


def test_public_join_counts_separate_list_from_sha_join(tmp_path: Path) -> None:
    """F-01: contributors login list size and SHA-join login counts stay distinct."""
    from tep_core.attribution import attribution_payload
    from tep_core.gitutil import read_commits

    repo = _two_authors(tmp_path)
    commits = read_commits(repo, include_files=True)
    origin = classify_commits(commits, empty_identity(), Lineage())
    mapping = {commits[0].sha.lower(): "alice-gh"}
    index = build_attribution_index(
        commits,
        origin,
        empty_identity(),
        sha_to_login=mapping,
        fetched_login_count=19,
    )
    payload = attribution_payload(index, human_commit_count=len(commits))
    join = payload["public_join"]
    assert join["fetched_login_count"] == 19
    assert join["commit_login_count"] == 1
    assert join["public_handle_actors"] == 1
    assert "not a commit-author join" in join["count_note"]


def test_actor_dir_rejects_unknown_card_schema(tmp_path: Path, capsys) -> None:
    """§3.4: align must not auto-guess arbitrary JSON as an actor card."""
    repo = _two_authors(tmp_path)
    dest = tmp_path / "col"
    assert main(["repo", str(repo), "--actors", "--format", "both", "--out", str(dest)]) == 0
    capsys.readouterr()
    pout = tmp_path / "proj"
    assert main(["project", str(repo), "--format", "json", "--out", str(pout)]) == 0
    capsys.readouterr()
    bad = dest / "actors" / "rogue.json"
    bad.write_text(json.dumps({"schema_version": "project-v1", "actor_id": "x"}), encoding="utf-8")
    code = main(
        [
            "align",
            "--actor-dir",
            str(dest),
            "--actor-id",
            "rogue",
            "--project-report",
            str(pout / "project.json"),
            "--format",
            "json",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "unsupported schema_version" in err
    assert "no format guessing" in err


def test_pagination_truncation_is_explicit() -> None:
    """§3.1: stopped pagination must declare truncation and unfetched range."""

    def transport(url: str):
        if url.endswith("robots.txt"):
            return 200, "User-agent: *\nAllow: /\n", {}
        if "/commits" in url:
            return (
                200,
                json.dumps([{"sha": "a" * 40, "author": {"login": "alice"}}]),
                {
                    "Link": (
                        "<https://api.github.com/repos/acme/app/commits?sha="
                        + ("0" * 40)
                        + '&per_page=100&page=2>; rel="next"'
                    )
                },
            )
        if "/contributors" in url:
            raise AssertionError("contributors endpoint is outside the commit CAS contract")
        if "/license" in url:
            return 404, "", {}
        return 404, "", {}

    manifest = collect_public_handles(
        "github.com/acme/app", fetch=True, transport=transport, head_sha="abc", max_pages=1
    )
    assert manifest["pagination"]["pages"] == 1
    assert manifest["pagination"]["truncated"] is True
    assert manifest["pagination"]["stop_reason"] == "max_pages_reached"
    assert manifest["pagination"]["unfetched_range"]
    assert "sha_to_login_beyond_last_page" in manifest["coverage"]["missing"]


def test_public_join_schema_rejects_conflated_counts() -> None:
    """強制点 public join: schema side rejects a public_join without separated counts."""
    from tep_core.schema_v2 import validate_actor_card, validate_report_v2

    minimal = {
        "schema_version": "report-v2",
        "report_kind": "evidence",
        "subject": {"kind": "repo", "selection": "repo_all_human"},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "definition_version": "d",
            "analysis_scope": "repo",
            "analyzed_commit_sha": "a" * 40,
        },
    }

    def with_join(join: dict) -> dict:
        report = dict(minimal)
        report["actor_directory"] = {
            "observed_count": 0,
            "actors": [],
            "attribution": {"public_join": join},
        }
        return report

    good = with_join(
        {
            "matched": 1,
            "unmatched": 0,
            "ambiguous": 0,
            "public_handle_actors": 1,
            "fetched_login_count": None,
            "commit_login_count": 1,
            "count_note": "fetched_login_count is a legacy unbound account-list count and "
            "is not a commit-author join; production CAS collection leaves it null; "
            "commit_login_count uses CAS commit OID evidence",
        }
    )
    assert not any("public_join" in e for e in validate_report_v2(good))
    bad = with_join(
        {
            "matched": 1,
            "unmatched": 0,
            "ambiguous": 0,
            "public_handle_actors": 1,
            "fetched_login_count": 30,
            "count_note": "whatever",
        }
    )
    errors = validate_report_v2(bad)
    assert any("commit_login_count" in e for e in errors)
    assert any("count_note" in e for e in errors)

    card = {
        "schema_version": "actor-card-v1",
        "report_kind": "actor_card",
        "actor_id": "github:someone",
        "display_name": "someone",
        "display_status": "public_handle",
        "identity_join": {
            "identity_source": "inferred_from_git",
            "join_basis": "commit_sha_to_login",
            "personhood_note": "n",
        },
    }
    assert validate_actor_card(card) == []
    card["identity_join"]["join_basis"] = "guessed_from_name"
    assert validate_actor_card(card) != []


def test_actor_card_alignment_verify_round_trip(tmp_path: Path, capsys) -> None:
    """§3.4: collection cards are formal align inputs and verify back to VERIFIED."""
    repo = _two_authors(tmp_path)
    dest = tmp_path / "col"
    assert main(["repo", str(repo), "--actors", "--format", "both", "--out", str(dest)]) == 0
    capsys.readouterr()
    pout = tmp_path / "proj"
    assert main(["project", str(repo), "--format", "json", "--out", str(pout)]) == 0
    capsys.readouterr()
    align_dir = tmp_path / "align"
    code = main(
        [
            "align",
            "--actor-dir",
            str(dest / "actors"),
            "--actor-id",
            "alice",
            "--project-report",
            str(pout / "project.json"),
            "--format",
            "json",
            "--out",
            str(align_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    card = dest / "actors" / "alice.json"
    code = main(
        [
            "verify",
            str(align_dir / "alignment.json"),
            "--actor-report",
            str(card),
            "--project-report",
            str(pout / "project.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "VERIFIED" in captured.out
