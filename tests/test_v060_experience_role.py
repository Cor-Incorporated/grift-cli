"""Pure experience and four-dimensional role-profile falsification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tep_core.experience import (
    ExperienceCommit,
    ExperienceInputError,
    FileChange,
    ReleaseTag,
    TenantConsent,
    build_experience,
    is_production_path,
    trailer_observations,
)
from tep_core.identity import email_identity_sha256
from tep_core.role_profile import build_role_profile, classify_domain

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)
CONSENT = TenantConsent(actor_id="alice", basis="explicit_owner_declaration")


def _commit(
    oid: str,
    day: int,
    actor: str,
    *changes: FileChange,
    message: str = "change",
    merge: bool = False,
    parents: tuple[str, ...] | None = None,
    bot: bool = False,
    sequence: int | None = None,
    repo_commits: int | None = None,
    repo_files: int | None = None,
    repo_lines: int | None = None,
) -> ExperienceCommit:
    return ExperienceCommit(
        oid=oid,
        actor_id=actor,
        authored_at=BASE + timedelta(days=day),
        message=message,
        changes=tuple(changes),
        parents=parents if parents is not None else (("p1", "p2") if merge else ("p1",)),
        is_bot=bot,
        sequence=sequence,
        repository_commit_count_after=repo_commits,
        repository_file_count_after=repo_files,
        repository_line_count_after=repo_lines,
    )


def test_experience_is_fail_closed_without_actor_matched_consent() -> None:
    rows = [_commit("a", 0, "alice", FileChange("A", "src/a.py"))]
    missing = build_experience(rows, actor_id="alice", consent=None)
    wrong = build_experience(
        rows,
        actor_id="alice",
        consent=TenantConsent(actor_id="bob", basis="explicit_owner_declaration"),
    )
    assert missing["reason"] == "consenting_actor_required"
    assert wrong["reason"] == "consenting_actor_required"
    assert "metrics" not in missing


def test_rename_below_m50_must_be_normalized_as_delete_add() -> None:
    with pytest.raises(ExperienceInputError, match=r"D\+A"):
        FileChange("R", "new.py", old_path="old.py", similarity=49)


def test_rename_inherits_copy_and_readd_create_new_delete_is_not_adoption() -> None:
    rows = [
        _commit("a", 0, "alice", FileChange("A", "src/original.py")),
        _commit(
            "b",
            30,
            "bob",
            FileChange("R", "src/renamed.py", old_path="src/original.py", similarity=50),
        ),
        _commit(
            "c",
            32,
            "bob",
            FileChange("C", "src/copy.py", old_path="src/renamed.py", similarity=100),
        ),
        _commit("d", 33, "bob", FileChange("D", "src/renamed.py")),
        _commit("e", 40, "alice", FileChange("A", "src/renamed.py")),
        _commit("f", 75, "bob", FileChange("D", "src/renamed.py")),
    ]
    result = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        observation_end=BASE + timedelta(days=100),
        min_population=1,
    )
    adopted = result["metrics"]["adopted_creations"]
    assert adopted["numerator"] == 1
    assert adopted["denominator"] == 2
    assert adopted["value"] == 0.5


def test_copy_by_another_actor_is_not_modification_or_adoption() -> None:
    rows = [
        _commit("a", 0, "alice", FileChange("A", "src/original.py")),
        _commit(
            "b",
            30,
            "bob",
            FileChange("C", "src/copy.py", old_path="src/original.py", similarity=100),
        ),
    ]
    result = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        observation_end=BASE + timedelta(days=60),
        min_population=1,
    )
    adopted = result["metrics"]["adopted_creations"]
    assert adopted["numerator"] == 0
    assert adopted["denominator"] == 1
    assert adopted["value"] == 0.0


def test_adoption_denominator_requires_thirty_live_observation_days() -> None:
    rows = [
        _commit("early-add", 0, "alice", FileChange("A", "src/early.py")),
        _commit("boundary-add", 0, "alice", FileChange("A", "src/boundary.py")),
        _commit("early-delete", 29, "alice", FileChange("D", "src/early.py")),
        _commit("boundary-adopt", 30, "bob", FileChange("M", "src/boundary.py")),
        _commit("boundary-delete", 31, "bob", FileChange("D", "src/boundary.py")),
    ]

    result = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        observation_end=BASE + timedelta(days=60),
        min_population=1,
    )

    adopted = result["metrics"]["adopted_creations"]
    assert (adopted["numerator"], adopted["denominator"], adopted["value"]) == (1, 1, 1.0)


def test_180_day_return_uses_previous_target_touch_across_rename() -> None:
    rows = [
        _commit("a", 0, "alice", FileChange("A", "src/a.py")),
        _commit("b", 179, "alice", FileChange("M", "src/a.py")),
        _commit(
            "c",
            359,
            "alice",
            FileChange("R", "src/b.py", old_path="src/a.py", similarity=100),
        ),
    ]
    result = build_experience(rows, actor_id="alice", consent=CONSENT, min_population=1)
    returns = result["metrics"]["self_maintenance_returns"]
    assert returns["numerator"] == 1
    assert returns["denominator"] == 2
    assert returns["value"] == 1


def test_cross_author_share_is_commit_based_and_ignores_unknown_creators() -> None:
    rows = [
        _commit("a", 0, "bob", FileChange("A", "src/bob.py")),
        _commit("b", 1, "alice", FileChange("M", "src/bob.py")),
        _commit("c", 2, "alice", FileChange("A", "src/alice.py")),
        _commit(
            "d",
            3,
            "alice",
            FileChange("M", "src/alice.py"),
            FileChange("M", "src/unknown.py"),
        ),
    ]
    result = build_experience(rows, actor_id="alice", consent=CONSENT, min_population=1)
    metric = result["metrics"]["cross_author_modification_share"]
    assert metric["numerator"] == 1
    assert metric["denominator"] == 2
    assert metric["value"] == 0.5


def test_bot_and_unresolved_lineages_are_excluded_from_human_metrics() -> None:
    rows = [
        _commit("bot-add", 0, "build-bot", FileChange("A", "src/bot.py"), bot=True),
        _commit("unknown-add", 1, None, FileChange("A", "src/unknown.py")),
        _commit("bob-add", 2, "bob", FileChange("A", "src/bob.py")),
        _commit("alice-add", 3, "alice", FileChange("A", "src/alice.py")),
        _commit("alice-bot", 4, "alice", FileChange("M", "src/bot.py")),
        _commit("alice-unknown", 5, "alice", FileChange("M", "src/unknown.py")),
        _commit("alice-bob", 6, "alice", FileChange("M", "src/bob.py")),
        _commit("bot-adopt", 40, "build-bot", FileChange("M", "src/alice.py"), bot=True),
    ]
    result = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        observation_end=BASE + timedelta(days=60),
        min_population=1,
    )

    cross_author = result["metrics"]["cross_author_modification_share"]
    assert (cross_author["numerator"], cross_author["denominator"]) == (1, 1)
    adopted = result["metrics"]["adopted_creations"]
    assert (adopted["numerator"], adopted["denominator"]) == (0, 1)


def test_file_lineage_is_invariant_to_sibling_topological_order() -> None:
    templates = {
        "root": _commit("root", 0, "carol", parents=()),
        "alice-add": _commit(
            "alice-add",
            1,
            "alice",
            FileChange("A", "src/shared.py"),
            parents=("root",),
        ),
        "bob-add": _commit(
            "bob-add",
            1,
            "bob",
            FileChange("A", "src/shared.py"),
            parents=("root",),
        ),
        "merge": _commit("merge", 2, "carol", parents=("alice-add", "bob-add")),
        "touch": _commit(
            "touch",
            3,
            "alice",
            FileChange("M", "src/shared.py"),
            parents=("merge",),
        ),
    }

    def metric(order: tuple[str, ...]) -> dict[str, object]:
        rows = []
        for sequence, oid in enumerate(order):
            row = templates[oid]
            rows.append(
                ExperienceCommit(
                    oid=row.oid,
                    actor_id=row.actor_id,
                    authored_at=row.authored_at,
                    message=row.message,
                    changes=row.changes,
                    parents=row.parents,
                    is_bot=row.is_bot,
                    sequence=sequence,
                )
            )
        return build_experience(
            rows,
            actor_id="alice",
            consent=CONSENT,
            min_population=1,
        )["metrics"]["cross_author_modification_share"]

    alice_first = metric(("root", "alice-add", "bob-add", "merge", "touch"))
    bob_first = metric(("root", "bob-add", "alice-add", "merge", "touch"))
    assert alice_first == bob_first
    assert (alice_first["numerator"], alice_first["denominator"]) == (0, 1)


def test_ai_and_human_coauthor_require_explicit_trailers_and_ai_identity() -> None:
    assert trailer_observations(
        "change\n\nCo-authored-by: Tool <ai@example.com>",
        ai_coauthor_email_sha256=[email_identity_sha256("AI@example.com")],
    ) == (True, False)
    assert trailer_observations("change\n\nCo-authored-by: Bob <bob@example.com>") == (
        False,
        True,
    )
    rows = [
        _commit(
            "a",
            0,
            "alice",
            FileChange("M", "src/a.py"),
            FileChange("M", "tests/test_a.py"),
            message="change\n\nAI-Assisted-By: codex",
        ),
        _commit(
            "b",
            1,
            "alice",
            FileChange("M", "src/b.py"),
            message="change\n\nCo-authored-by: Tool <ai@example.com>",
        ),
        _commit(
            "c",
            2,
            "alice",
            FileChange("M", "src/c.py"),
            message="change\n\nAgent-Lane: codex",
        ),
        _commit(
            "d",
            3,
            "alice",
            FileChange("M", "src/d.py"),
            message="change\n\nCo-authored-by: Bob <bob@example.com>",
        ),
    ]
    result = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        ai_coauthor_emails=["ai@example.com"],
        min_population=1,
    )
    metrics = result["metrics"]
    assert metrics["declared_ai_assist_share"]["value"] == 0.75
    assert metrics["declared_ai_test_cochange"]["numerator"] == 1
    assert metrics["declared_ai_test_cochange"]["denominator"] == 3
    assert metrics["human_coauthored_share"]["value"] == 0.25


def test_trailer_like_body_examples_are_not_declarations() -> None:
    body_example = (
        "docs: explain declarations\n\n"
        "Example:\n"
        "Co-authored-by: Tool <ai@example.com>\n"
        "This prose follows the example."
    )
    assert trailer_observations(
        body_example,
        ai_coauthor_emails=["ai@example.com"],
    ) == (False, False)
    assert trailer_observations(
        "feat: declared\n\nCo-authored-by: Tool <ai@example.com>",
        ai_coauthor_emails=["ai@example.com"],
    ) == (True, False)


def test_declared_ai_production_path_uses_existing_cochange_taxonomy() -> None:
    assert is_production_path("src/app.py") is True
    assert is_production_path("README.md") is False
    assert is_production_path("docs/guide.md") is False
    assert is_production_path("LICENSE") is False


def test_no_declared_ai_is_not_interpreted_as_no_ai_use() -> None:
    rows = [
        _commit(str(index), index, "alice", FileChange("M", f"src/{index}.py"))
        for index in range(20)
    ]
    result = build_experience(rows, actor_id="alice", consent=CONSENT)
    declared = result["metrics"]["declared_ai_assist_share"]
    cochange = result["metrics"]["declared_ai_test_cochange"]
    assert declared["kind"] == "observed"
    assert declared["value"] == 0.0
    assert declared["observation_state"] == "no_declared_ai_commits"
    assert cochange["kind"] == "not_observed"
    assert cochange["reason"] == "no_declared_ai_commits"


def test_declared_ai_without_production_paths_is_not_reported_as_no_declaration() -> None:
    rows = [
        _commit(
            str(index),
            index,
            "alice",
            FileChange("M", "docs/guide.md" if index == 0 else f"src/{index}.py"),
            message=("docs: assisted\n\nAgent-Lane: codex" if index == 0 else "change"),
        )
        for index in range(20)
    ]

    result = build_experience(rows, actor_id="alice", consent=CONSENT)
    declared = result["metrics"]["declared_ai_assist_share"]
    cochange = result["metrics"]["declared_ai_test_cochange"]

    assert (declared["numerator"], declared["denominator"], declared["value"]) == (1, 20, 0.05)
    assert cochange["kind"] == "not_observed"
    assert cochange["denominator"] == 0
    assert cochange["reason"] == "insufficient_population"


def test_default_population_gate_hides_numerator_and_value() -> None:
    rows = [
        _commit(str(index), index, "alice", FileChange("A", f"src/{index}.py"))
        for index in range(19)
    ]
    result = build_experience(rows, actor_id="alice", consent=CONSENT)
    for metric in result["metrics"].values():
        if metric["kind"] == "not_observed":
            assert "numerator" not in metric
            assert "value" not in metric
    declared = result["metrics"]["declared_ai_assist_share"]
    assert declared["reason"] == "insufficient_population"
    assert "observation_state" not in declared


def test_dependency_and_post_release_fix_observations() -> None:
    rows = [
        _commit(
            str(index),
            index,
            "alice",
            FileChange("M", "requirements.txt" if index == 1 else f"src/{index}.py"),
            message="fix: regression" if index == 12 else "change",
            parents=() if index == 0 else (str(index - 1),),
        )
        for index in range(20)
    ]
    tag = ReleaseTag("v1.0.0", "10", BASE + timedelta(days=10), annotated=False)
    result = build_experience(rows, actor_id="alice", consent=CONSENT, release_tags=[tag])
    assert result["metrics"]["dependency_update_share"]["value"] == 0.05
    assert result["metrics"]["post_release_fixes"]["value"] == 1


def test_post_release_fix_rejects_sibling_branch_and_accepts_merge_descendant() -> None:
    sibling_rows = [
        _commit("root", 0, "alice", parents=()),
        _commit("tagged", 1, "alice", parents=("root",)),
        _commit("side", 2, "alice", parents=("root",)),
        _commit("sibling-fix", 3, "alice", message="fix: sibling", parents=("side",)),
    ]
    tag = ReleaseTag("v1.0.0", "tagged", BASE + timedelta(days=1), annotated=False)
    sibling = build_experience(
        sibling_rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[tag],
        min_population=1,
    )["metrics"]["post_release_fixes"]
    assert sibling["kind"] == "observed"
    assert sibling["numerator"] == 0
    assert sibling["value"] == 0

    merged_rows = [
        *sibling_rows[:3],
        _commit("merge", 3, "alice", parents=("tagged", "side")),
        _commit("merged-fix", 4, "alice", message="fix: merged", parents=("merge",)),
    ]
    merged = build_experience(
        merged_rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[tag],
        min_population=1,
    )["metrics"]["post_release_fixes"]
    assert merged["kind"] == "observed"
    assert merged["numerator"] == 1
    assert merged["value"] == 1


def test_post_release_fix_uses_inclusive_30_day_boundary() -> None:
    tag_time = BASE + timedelta(days=1)
    rows = [
        _commit("tagged", 1, "alice", parents=()),
        ExperienceCommit(
            oid="on-boundary",
            actor_id="alice",
            authored_at=tag_time + timedelta(days=30),
            message="fix: exact boundary",
            parents=("tagged",),
        ),
        ExperienceCommit(
            oid="after-boundary",
            actor_id="alice",
            authored_at=tag_time + timedelta(days=30, seconds=1),
            message="fix: outside boundary",
            parents=("on-boundary",),
        ),
    ]
    metric = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[ReleaseTag("v1.0.0", "tagged", tag_time, annotated=True)],
        min_population=1,
    )["metrics"]["post_release_fixes"]
    assert metric["numerator"] == 1
    assert metric["value"] == 1


def test_post_release_ancestry_handles_deep_history_without_recursion() -> None:
    rows = [
        ExperienceCommit(
            oid=str(index),
            actor_id="alice",
            authored_at=BASE + timedelta(minutes=index),
            message="fix: deep descendant" if index == 1999 else "change",
            parents=() if index == 0 else (str(index - 1),),
        )
        for index in range(2000)
    ]
    metric = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[ReleaseTag("v1.0.0", "0", BASE, annotated=False)],
        min_population=1,
    )["metrics"]["post_release_fixes"]
    assert metric["numerator"] == 1


@pytest.mark.parametrize(
    ("rows", "tag_target", "reason"),
    [
        (
            [
                _commit("root", 0, "alice", parents=()),
                _commit(
                    "fix",
                    2,
                    "alice",
                    message="fix: unknown tag target",
                    parents=("root",),
                ),
            ],
            "missing",
            "release_tag_target_missing",
        ),
        (
            [
                _commit("tagged", 0, "alice", parents=()),
                _commit(
                    "fix",
                    2,
                    "alice",
                    message="fix: incomplete ancestry",
                    parents=("missing",),
                ),
            ],
            "tagged",
            "commit_ancestry_incomplete",
        ),
        (
            [
                _commit("tagged", 0, "alice", parents=("fix",)),
                _commit(
                    "fix",
                    2,
                    "alice",
                    message="fix: cyclic ancestry",
                    parents=("tagged",),
                ),
            ],
            "tagged",
            "commit_parent_cycle",
        ),
    ],
)
def test_post_release_fix_hides_value_when_ancestry_is_not_proven(
    rows: list[ExperienceCommit], tag_target: str, reason: str
) -> None:
    metric = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[ReleaseTag("v1.0.0", tag_target, BASE + timedelta(days=1), annotated=False)],
        min_population=1,
    )["metrics"]["post_release_fixes"]
    assert metric["kind"] == "not_observed"
    assert metric["reason"] == reason
    assert "numerator" not in metric
    assert "value" not in metric


def test_post_release_ancestry_error_does_not_bypass_population_suppression() -> None:
    rows = [
        _commit(
            str(index),
            index,
            "alice",
            message="fix: small sample" if index == 18 else "change",
            parents=() if index == 0 else (str(index - 1),),
        )
        for index in range(19)
    ]
    metric = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[ReleaseTag("v1.0.0", "missing", BASE, annotated=False)],
    )["metrics"]["post_release_fixes"]
    assert metric["reason"] == "insufficient_population"
    assert metric["denominator"] == 19
    assert "numerator" not in metric
    assert "value" not in metric


def test_timeline_size_founder_scaffold_and_tag_attribution() -> None:
    rows: list[ExperienceCommit] = []
    for index in range(5):
        rows.append(
            _commit(
                f"b{index}",
                index,
                "bob",
                FileChange("A", f"src/bob-{index}.py"),
                sequence=index,
                repo_commits=index + 1,
                repo_files=index + 1,
                repo_lines=(index + 1) * 10,
            )
        )
    for index in range(25):
        total = index + 6
        rows.append(
            _commit(
                f"a{index}",
                index + 5,
                "alice",
                FileChange("A", f"src/alice-{index}.py"),
                sequence=index + 5,
                repo_commits=total,
                repo_files=total,
                repo_lines=total * 10,
            )
        )
    tags = [
        ReleaseTag(
            "v1.0.0",
            "a24",
            BASE + timedelta(days=30),
            annotated=True,
            tagger_actor_id="alice",
        ),
        ReleaseTag(
            "latest",
            "a24",
            BASE + timedelta(days=30),
            annotated=False,
            tagger_actor_id="alice",  # must still remain unattributed
        ),
    ]
    result = build_experience(
        rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=tags,
        observation_end=BASE + timedelta(days=60),
    )
    metrics = result["metrics"]
    timeline = metrics["language_domain_timeline"]
    assert timeline["kind"] == "observed"
    assert timeline["numerator"] == 25
    assert timeline["denominator"] == 25
    assert timeline["periods"][0]["path_touch_commit_n"] == 25
    assert timeline["periods"][0]["languages"]["values"]["python"] == {
        "n": 25,
        "share": 1.0,
    }
    assert timeline["periods"][0]["domains"]["values"]["core"]["share"] == 1.0

    sizes = metrics["repository_size_at_contribution_points"]
    assert sizes["numerator"] == 3
    assert sizes["points"]["first"]["repository_commit_count"] == 6
    assert sizes["points"]["median"]["target_contribution_rank"] == 13
    assert sizes["points"]["median"]["repository_file_count"] == 18
    assert sizes["points"]["last"]["repository_line_count"] == 300

    founder = metrics["founder_timing"]
    assert founder["numerator"] == 5
    assert founder["denominator"] == 30
    assert founder["value"] == 0.1667
    assert founder["days_after_repository_start"] == 5.0

    scaffold = metrics["initial_30d_scaffold_creation_share"]
    assert scaffold["numerator"] == 25
    assert scaffold["denominator"] == 30
    assert scaffold["value"] == 0.8333

    assert metrics["annotated_tag_creation"]["value"] == 1
    lightweight = metrics["lightweight_tag_attribution"]
    assert lightweight["kind"] == "not_observed"
    assert lightweight["reason"] == "lightweight_tag_has_no_tagger"
    assert lightweight["denominator"] == 1
    assert "numerator" not in lightweight
    assert "value" not in lightweight

    cadence = metrics["cadence"]
    assert cadence["numerator"] == 24
    required_envelope = {
        "kind",
        "numerator",
        "denominator",
        "unit",
        "window",
        "definition_version",
        "limitations",
    }
    for metric in metrics.values():
        if metric["kind"] == "observed":
            assert required_envelope <= metric.keys()


def test_repo_size_snapshot_missing_is_explicit_not_proven() -> None:
    rows = [
        _commit(str(index), index, "alice", FileChange("A", f"src/{index}.py"))
        for index in range(20)
    ]
    result = build_experience(rows, actor_id="alice", consent=CONSENT)
    sizes = result["metrics"]["repository_size_at_contribution_points"]
    assert sizes["kind"] == "not_observed"
    assert sizes["reason"] == "repository_size_snapshots_missing"
    assert "points" not in sizes


def test_domain_classifier_is_provider_neutral() -> None:
    assert classify_domain("src/service.py") == "core"
    assert classify_domain("tests/test_service.py") == "test"
    assert classify_domain("docs/guide.md") == "docs"
    assert classify_domain(".github/workflows/ci.yml") == "infra"
    assert classify_domain("package-lock.json") == "deps"
    assert classify_domain("assets/logo.png") == "unclassified"


def test_role_profile_has_four_dimensions_without_score_or_label() -> None:
    rows: list[ExperienceCommit] = []
    for index in range(10):
        rows.append(_commit(f"e{index}", index, "alice", FileChange("A", f"src/{index}.py")))
    for index in range(10):
        path = "package.json" if index == 0 else f"tests/test_{index}.py"
        rows.append(
            _commit(
                f"m{index}",
                35 + index,
                "alice",
                FileChange("M", path),
                message="fix: regression" if index == 1 else "change",
            )
        )
    for index in range(10):
        rows.append(
            _commit(
                f"r{index}",
                70 + index,
                "alice",
                FileChange(
                    "R", f"docs/new-{index}.md", old_path=f"docs/old-{index}.md", similarity=100
                ),
            )
        )
    rows.append(_commit("merge", 80, "alice", merge=True))
    tag = ReleaseTag(
        "v1.0.0",
        "r9",
        BASE + timedelta(days=80),
        annotated=True,
        tagger_actor_id="alice",
    )
    result = build_role_profile(
        rows,
        actor_id="alice",
        consent=CONSENT,
        release_tags=[tag],
        observation_end=BASE + timedelta(days=90),
    )
    assert result["kind"] == "observed"
    assert set(result["dimensions"]) == {
        "domain",
        "work_type",
        "time",
        "process_position",
    }
    assert set(result["dimensions"]["time"]) == {"phase", "calendar_year"}
    assert result["dimensions"]["domain"]["core"]["value"] == 0.3333
    assert result["dimensions"]["domain"]["deps"]["value"] == 0.0333
    assert result["dimensions"]["work_type"]["rename"]["value"] == 0.3333
    assert result["dimensions"]["work_type"]["corrective"]["value"] == 0.0333
    assert result["dimensions"]["time"]["phase"]["early"]["value"] == 0.3333
    assert result["dimensions"]["time"]["phase"]["middle"]["value"] == 0.3333
    assert result["dimensions"]["time"]["phase"]["recent"]["value"] == 0.3333
    assert result["dimensions"]["process_position"]["integrator"]["numerator"] == 1
    assert result["dimensions"]["process_position"]["release"]["numerator"] == 1
    assert result["dimensions"]["process_position"]["release"]["denominator"] == 32

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key).lower() for key in value} | {
                nested for item in value.values() for nested in keys(item)
            }
        if isinstance(value, list):
            return {nested for item in value for nested in keys(item)}
        return set()

    assert {"score", "rank", "job_title"}.isdisjoint(keys(result))


def test_role_profile_population_gate_and_consent_gate() -> None:
    rows = [_commit("a", 0, "alice", FileChange("A", "src/a.py"))]
    gated = build_role_profile(rows, actor_id="alice", consent=CONSENT)
    core = gated["dimensions"]["domain"]["core"]
    assert core["reason"] == "insufficient_population"
    assert "numerator" not in core
    assert "value" not in core
    no_consent = build_role_profile(rows, actor_id="alice", consent=None)
    assert no_consent["reason"] == "consenting_actor_required"
    assert "dimensions" not in no_consent
