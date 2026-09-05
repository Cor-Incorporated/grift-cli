"""Regression: public inferred actor must not be presented as personal evidence.

Review (2026-08-31, HIGH): actor reports described every subject as a
「本人証拠ビュー」 and alignment Markdown demanded a consented identity even
for inferred public-actor selections. These tests pin the five presentation
bases (public inferred, self-claimed, admin-authorized, explicit nonconsent,
and fail-closed unknown) across JSON notices, Markdown wording, and stderr.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.actor_basis import ActorBasis, actor_basis_notices, classify_actor_basis
from tep_core.report_v2 import render_alignment_markdown, render_evidence_markdown
from tep_core.schema_v2 import validate_report_v2
from tep_core.v2_constants import (
    ACTOR_ADMIN_NOTICE,
    ACTOR_CLAIMED_NOTICE,
    ACTOR_NONCONSENT_NOTICE,
    ACTOR_CONSENT_NOTICE,
    ACTOR_UNKNOWN_NOTICE,
    ACTOR_VIEW_NOTICE,
    PUBLIC_ACTOR_NOTICE,
)

from git_fixture import commit, init_repo


def _repo_two_authors(tmp: Path) -> Path:
    repo = init_repo(tmp / "repo")
    (repo / "src").mkdir(parents=True)
    for index in range(6):
        commit(
            repo,
            email="a@example.com",
            date="2026-08-01",
            message=f"feat a {index}",
            filename="src/app.py",
            name="Alice",
        )
    for index in range(3):
        commit(
            repo,
            email="b@example.com",
            date="2026-08-02",
            message=f"feat b {index}",
            filename="src/other.py",
            name="Bob",
        )
    return repo


def _identity_file(tmp: Path, state: str) -> Path:
    path = tmp / f"identity-{state}.toml"
    path.write_text(
        'schema_version = "identity-v1"\n\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\n'
        f'attribution_state = "{state}"\n',
        encoding="utf-8",
    )
    return path


def _project_toml(tmp: Path) -> Path:
    path = tmp / "project.toml"
    path.write_text(
        'schema_version = "tep-project-v1"\n'
        'project_id = "demo-project"\n'
        '[[requirements]]\nsurfaces = ["backend"]\n'
        'verification = ["unit"]\n'
        'inputs = ["git"]\n',
        encoding="utf-8",
    )
    return path


PERSONHOOD_CLAIMS = (
    "本人証拠ビュー",
    "本人向け証拠ビュー",
    "本人レポート",
    "本人証拠（actor",
)
PUBLIC_CLUSTER_MARK = "公開Git上のactor cluster観測"
IDENTITY_NOT_PROVEN = "実在人物との同一性は証明していません"


def _run(args: list[str], capsys) -> tuple[int, object]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured


@pytest.mark.parametrize(
    ("selection", "state", "expected"),
    [
        ("inferred_actor", None, ActorBasis.PUBLIC_INFERRED),
        ("explicit_actor", "claimed", ActorBasis.SELF_CLAIMED),
        ("explicit_actor", "verified", ActorBasis.ADMIN_VERIFIED),
        ("explicit_actor", "external", ActorBasis.EXPLICIT_NONCONSENT),
        ("explicit_actor", None, ActorBasis.UNKNOWN),
        ("inferred_actor", "verified", ActorBasis.UNKNOWN),
    ],
)
def test_actor_basis_classifier_fails_closed(
    selection: str, state: str | None, expected: ActorBasis
) -> None:
    assert classify_actor_basis(selection, state) is expected
    assert (ACTOR_VIEW_NOTICE in actor_basis_notices(selection, state)) is (
        expected is ActorBasis.SELF_CLAIMED
    )


def test_inferred_actor_markdown_and_json_disclaim_personhood(tmp_path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    code, captured = _run(["actor", "alice", str(repo), "--format", "json"], capsys)
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["subject"]["selection"] == "inferred_actor"
    assert "attribution_state" not in payload["subject"]
    assert payload["provenance"]["analysis_scope"] == "actor_cluster"
    assert payload["provenance"]["identity_digest"] is None
    assert payload["identity"] == {"pending_attribution": True, "actor_count": 0}
    assert payload["activity"]["scope"] == "actor_cluster"
    assert payload["activity"]["tenant_commits"] is None
    assert payload["activity"]["actor_cluster_commits"]["value"] == 6
    assert payload["rework"]["analysis_scope"] == "actor_cluster"
    assert PUBLIC_ACTOR_NOTICE in payload["notices"]
    assert ACTOR_VIEW_NOTICE not in payload["notices"]
    assert ACTOR_CONSENT_NOTICE not in payload["notices"]
    assert (
        classify_actor_basis(
            payload["subject"]["selection"],
            payload["subject"].get("attribution_state"),
        )
        is ActorBasis.PUBLIC_INFERRED
    )

    code, captured = _run(["actor", "alice", str(repo), "--format", "md"], capsys)
    assert code == 0, captured.err
    markdown = captured.out
    assert PUBLIC_CLUSTER_MARK in markdown
    assert IDENTITY_NOT_PROVEN in markdown
    for claim in PERSONHOOD_CLAIMS:
        assert claim not in markdown, f"inferred actor Markdown must not claim {claim!r}"
    assert ACTOR_CONSENT_NOTICE not in markdown


def test_explicit_claimed_identity_is_personal_but_consent_unproven(tmp_path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    identity = _identity_file(tmp_path, "claimed")
    code, captured = _run(
        ["actor", "alice", str(repo), "--identity", str(identity), "--format", "json"],
        capsys,
    )
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["subject"]["selection"] == "explicit_actor"
    assert payload["subject"]["attribution_state"] == "claimed"
    assert payload["provenance"]["analysis_scope"] == "tenant"
    assert payload["activity"]["scope"] == "tenant"
    assert payload["activity"]["population"] == "explicit_identity_nonmerge"
    assert "actor_cluster_commits" not in payload["activity"]
    assert ACTOR_VIEW_NOTICE in payload["notices"]
    assert ACTOR_CLAIMED_NOTICE in payload["notices"]
    assert PUBLIC_ACTOR_NOTICE not in payload["notices"]
    assert ACTOR_CLAIMED_NOTICE in captured.err

    code, captured = _run(
        ["actor", "alice", str(repo), "--identity", str(identity), "--format", "md"],
        capsys,
    )
    assert code == 0, captured.err
    markdown = captured.out
    assert "attribution_state=claimed と記録された identity に基づく本人向けactor観測" in markdown
    assert "同意済みidentity" not in markdown
    assert ACTOR_CLAIMED_NOTICE in markdown
    assert PUBLIC_CLUSTER_MARK not in markdown


def test_admin_authorized_identity_is_labelled_separately(tmp_path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    identity = _identity_file(tmp_path, "verified")
    code, captured = _run(
        ["actor", "alice", str(repo), "--identity", str(identity), "--format", "md"],
        capsys,
    )
    assert code == 0, captured.err
    markdown = captured.out
    assert (
        "管理対象リポジトリの identity 定義（attribution_state=verified）に基づくactor観測"
        in markdown
    )
    assert ACTOR_ADMIN_NOTICE in markdown
    assert ACTOR_VIEW_NOTICE not in markdown
    assert "同意済みidentity" not in markdown
    assert PUBLIC_CLUSTER_MARK not in markdown

    code, captured = _run(
        ["actor", "alice", str(repo), "--identity", str(identity), "--format", "json"],
        capsys,
    )
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["subject"]["selection"] == "explicit_actor"
    assert payload["subject"]["attribution_state"] == "verified"
    assert payload["provenance"]["analysis_scope"] == "tenant"
    assert payload["activity"]["scope"] == "tenant"
    assert payload["activity"]["population"] == "explicit_identity_nonmerge"
    assert "actor_cluster_commits" not in payload["activity"]
    assert ACTOR_ADMIN_NOTICE in payload["notices"]
    assert ACTOR_VIEW_NOTICE not in payload["notices"]
    assert ACTOR_ADMIN_NOTICE in captured.err


@pytest.mark.parametrize("state", ["inferred", "external", "unresolved", "bot"])
def test_explicit_nonconsenting_identity_never_claims_consent(tmp_path, capsys, state: str) -> None:
    repo = _repo_two_authors(tmp_path)
    identity = _identity_file(tmp_path, state)
    code, captured = _run(
        ["actor", "alice", str(repo), "--identity", str(identity), "--format", "both"],
        capsys,
    )
    assert code == 0, captured.err
    assert ACTOR_NONCONSENT_NOTICE in captured.err
    assert ACTOR_CONSENT_NOTICE not in captured.err
    assert "本人同意または本人性は証明しておらず" in captured.out
    assert ACTOR_VIEW_NOTICE not in captured.out

    payload = json.loads(captured.out[captured.out.index("{") :])
    assert payload["subject"]["selection"] == "explicit_actor"
    assert payload["subject"]["attribution_state"] == state
    assert payload["provenance"]["analysis_scope"] == "actor_cluster"
    assert payload["activity"]["scope"] == "actor_cluster"
    assert payload["activity"]["tenant_commits"] is None
    expected_commits = 0 if state == "bot" else 6
    assert payload["activity"]["actor_cluster_commits"]["value"] == expected_commits
    assert ACTOR_NONCONSENT_NOTICE in payload["notices"]
    assert payload["experience"]["kind"] == "not_observed"
    assert payload["role_profile"]["kind"] == "not_observed"


def test_actor_scope_and_population_mutations_fail_closed(tmp_path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    code, captured = _run(["actor", "alice", str(repo), "--format", "json"], capsys)
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    assert validate_report_v2(payload) == []

    wrong_scope = deepcopy(payload)
    wrong_scope["provenance"]["analysis_scope"] = "tenant"
    assert any("must be actor_cluster" in item for item in validate_report_v2(wrong_scope))

    leaked_tenant_population = deepcopy(payload)
    leaked_tenant_population["activity"]["tenant_commits"] = deepcopy(
        leaked_tenant_population["activity"]["actor_cluster_commits"]
    )
    assert any("tenant_commits" in item for item in validate_report_v2(leaked_tenant_population))

    identity_claim = deepcopy(payload)
    identity_claim["provenance"]["identity_digest"] = "a" * 64
    assert any("identity input" in item for item in validate_report_v2(identity_claim))


def test_missing_explicit_state_fails_closed_in_renderer(tmp_path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    identity = _identity_file(tmp_path, "claimed")
    code, captured = _run(
        ["actor", "alice", str(repo), "--identity", str(identity), "--format", "json"],
        capsys,
    )
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    payload["subject"].pop("attribution_state")

    markdown = render_evidence_markdown(payload)
    assert ACTOR_UNKNOWN_NOTICE in markdown
    assert ACTOR_VIEW_NOTICE not in markdown
    assert "同意済みidentity" not in markdown
    assert classify_actor_basis("explicit_actor", None) is ActorBasis.UNKNOWN


def _alignment_output(tmp_path: Path, capsys, *, fmt: str) -> str:
    """Build an alignment through the formal actor-dir path."""

    repo = _repo_two_authors(tmp_path)
    collection = tmp_path / "collection"
    code = main(
        [
            "repo",
            str(repo),
            "--actors",
            "--format",
            "both",
            "--out",
            str(collection),
        ]
    )
    assert code == 0, capsys.readouterr().err

    requirements = tmp_path / "requirements.toml"
    requirements.write_text(
        'schema_version = "tep-project-v1"\n'
        'project_id = "demo-project"\n'
        '[requirements.surfaces]\nrequired = ["backend"]\n'
        '[requirements.verification]\nrequired = ["unit"]\n'
        '[requirements.inputs]\nrequired = ["git"]\n',
        encoding="utf-8",
    )
    project_out = tmp_path / "project"
    code = main(
        [
            "project",
            str(repo),
            "--requirements",
            str(requirements),
            "--format",
            "json",
            "--out",
            str(project_out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err

    args = [
        "align",
        "--actor-dir",
        str(collection),
        "--actor",
        "alice",
        "--project-report",
        str(project_out / "project.json"),
        "--format",
        fmt,
    ]
    code = main(args)
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return captured.out


def test_alignment_markdown_switches_notice_by_selection(tmp_path, capsys) -> None:
    # Inferred alignment (actor card without identity): public cluster
    # wording, no consent-identity demand.
    markdown = _alignment_output(tmp_path, capsys, fmt="md")
    assert PUBLIC_CLUSTER_MARK in markdown
    assert IDENTITY_NOT_PROVEN in markdown
    assert ACTOR_CONSENT_NOTICE not in markdown
    for claim in PERSONHOOD_CLAIMS:
        assert claim not in markdown, f"inferred alignment must not claim {claim!r}"


def test_inferred_alignment_preserves_actor_cluster_machine_scope(tmp_path, capsys) -> None:
    payload = json.loads(_alignment_output(tmp_path, capsys, fmt="json"))
    assert payload["subject"]["actor_selection"] == "inferred_actor"
    assert payload["provenance"]["analysis_scope"] == "actor_cluster"
    assert payload["actor_provenance"]["analysis_scope"] == "actor_cluster"


@pytest.mark.parametrize(
    ("subject", "notice", "personal"),
    [
        (
            {
                "kind": "alignment",
                "actor_canonical_id": "alice",
                "actor_selection": "explicit_actor",
                "actor_attribution_state": "claimed",
                "project_id": "demo-project",
            },
            ACTOR_CLAIMED_NOTICE,
            True,
        ),
        (
            {
                "kind": "alignment",
                "actor_canonical_id": "alice",
                "actor_selection": "explicit_actor",
                "actor_attribution_state": "verified",
                "project_id": "demo-project",
            },
            ACTOR_ADMIN_NOTICE,
            False,
        ),
        (
            {
                "kind": "alignment",
                "actor_canonical_id": "alice",
                "actor_selection": "explicit_actor",
                "actor_attribution_state": "external",
                "project_id": "demo-project",
            },
            ACTOR_NONCONSENT_NOTICE,
            False,
        ),
        (
            {
                "kind": "alignment",
                "actor_canonical_id": "alice",
                "actor_selection": "explicit_actor",
                "project_id": "demo-project",
            },
            ACTOR_UNKNOWN_NOTICE,
            False,
        ),
    ],
)
def test_alignment_renderer_uses_fail_closed_actor_basis(
    subject: dict[str, object], notice: str, personal: bool
) -> None:
    markdown = render_alignment_markdown(
        {
            "subject": subject,
            "provenance": {},
            "axes": [],
            "limitations": [],
        }
    )
    assert notice in markdown
    assert ("本人向けactor観測" in markdown) is personal
    assert "同意済みidentity" not in markdown


def test_inferred_actor_stderr_uses_public_notice(tmp_path, capsys) -> None:
    repo = _repo_two_authors(tmp_path)
    code, captured = _run(["actor", "alice", str(repo), "--format", "json"], capsys)
    assert code == 0
    assert PUBLIC_ACTOR_NOTICE in captured.err
    assert ACTOR_CONSENT_NOTICE not in captured.err
