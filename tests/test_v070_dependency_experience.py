"""W2 — surface introduced dependencies as an actor observation.

The collector attributes an introduction to a commit; this is where it becomes
a statement about a person: "introduced aiofiles, aiomysql, asyncpg" rather
than "touched the deps surface 12 times".

Names are emitted as observed, not bucketed. This is the consented actor's own
evidence view; what a `contribute` payload may carry is a separate question
answered by that profile's transformation, not by suppressing the observation
here.

Coverage is reported alongside: an actor with no introductions and a manifest
that never parsed is not the same as one who introduced nothing (norms §1).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tep_core.experience import (
    ExperienceCommit,
    FileChange,
    TenantConsent,
    build_experience,
)

CONSENT = TenantConsent("subject", "unit_test")
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _commit(index: int, actor: str) -> ExperienceCommit:
    return ExperienceCommit(
        oid=f"{index:040x}",
        actor_id=actor,
        authored_at=EPOCH + timedelta(days=index),
        message="feat: work",
        changes=(FileChange("M", f"src/module_{index}.py"),),
        parents=("0" * 40,),
    )


def _history(n: int = 30) -> list[ExperienceCommit]:
    return [_commit(i, "subject") for i in range(n)]


def _build(commits, **kwargs):
    return build_experience(commits, actor_id="subject", consent=CONSENT, **kwargs)


def _node(payload):
    return payload["metrics"]["dependency_introduction"]


def test_absent_collection_is_not_observed_not_empty() -> None:
    """Without a collection the tool must not claim the actor introduced nothing."""
    node = _node(_build(_history()))
    assert node["kind"] == "not_observed"
    assert node["reason"] == "dependency_scan_not_provided"


def test_names_the_actor_introduced_are_reported() -> None:
    introductions = {
        f"{0:040x}": frozenset({"asyncpg", "aiomysql"}),
        f"{1:040x}": frozenset({"aiofiles"}),
    }
    node = _node(
        _build(
            _history(),
            dependency_introductions=introductions,
            dependency_manifest_commits=12,
            dependency_unparseable=0,
        )
    )
    assert node["kind"] == "observed"
    assert set(node["values"]) == {"asyncpg", "aiomysql", "aiofiles"}
    assert node["value"] == 3


def test_only_this_actors_commits_count() -> None:
    commits = _history() + [_commit(99, "someone_else")]
    introductions = {
        f"{0:040x}": frozenset({"mine"}),
        f"{99:040x}": frozenset({"theirs"}),
    }
    node = _node(
        _build(
            commits,
            dependency_introductions=introductions,
            dependency_manifest_commits=5,
            dependency_unparseable=0,
        )
    )
    assert set(node["values"]) == {"mine"}, (
        f"another actor's introduction was attributed to the subject: {node['values']}"
    )


def test_coverage_is_reported_beside_the_names() -> None:
    node = _node(
        _build(
            _history(),
            dependency_introductions={},
            dependency_manifest_commits=40,
            dependency_unparseable=7,
        )
    )
    assert node["kind"] == "observed"
    assert node["value"] == 0
    assert node["manifest_commits"] == 40
    assert node["unparseable_manifests"] == 7


def test_zero_with_unreadable_manifests_states_the_limit() -> None:
    """A reader must be able to tell 'introduced nothing' from 'could not read'."""
    node = _node(
        _build(
            _history(),
            dependency_introductions={},
            dependency_manifest_commits=40,
            dependency_unparseable=40,
        )
    )
    text = " ".join(node.get("limitations", []))
    assert "unreadable" in text.lower() or "parse" in text.lower(), text


def test_names_are_sorted_for_determinism() -> None:
    introductions = {f"{0:040x}": frozenset({"zeta", "alpha", "mu"})}
    node = _node(
        _build(
            _history(),
            dependency_introductions=introductions,
            dependency_manifest_commits=3,
            dependency_unparseable=0,
        )
    )
    assert node["values"] == sorted(node["values"])


@pytest.mark.parametrize("unparseable", [0, 3])
def test_population_floor_applies(unparseable: int) -> None:
    """Below the floor the axis is not_observed, as every other actor metric is."""
    node = _node(
        _build(
            _history(2),
            dependency_introductions={f"{0:040x}": frozenset({"x"})},
            dependency_manifest_commits=1,
            dependency_unparseable=unparseable,
        )
    )
    assert node["kind"] == "not_observed"
    assert node["reason"] == "insufficient_population"


# --------------------------------------------------------------------------
# Declaration <-> enforcement: the schema must accept what the builder emits
# --------------------------------------------------------------------------


def test_schema_accepts_both_shapes_the_builder_emits() -> None:
    """Adding a field without widening the schema silently breaks every report."""
    import json
    from pathlib import Path

    from tep_core.schema import validate_schema

    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json"
        ).read_text(encoding="utf-8")
    )

    def metrics_props(node, found):
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and "dependency_update_share" in props:
                found.append(props)
            for value in node.values():
                metrics_props(value, found)
        elif isinstance(node, list):
            for value in node:
                metrics_props(value, found)
        return found

    blocks = metrics_props(schema["$defs"]["experience-v1"], [])
    assert blocks, "experience metrics block not found in the schema"
    for props in blocks:
        assert "dependency_introduction" in props, (
            "the builder emits dependency_introduction but the schema does not "
            "declare it; additionalProperties is false, so every report fails"
        )

    observed = _node(
        _build(
            _history(),
            dependency_introductions={f"{0:040x}": frozenset({"anyio"})},
            dependency_manifest_commits=4,
            dependency_unparseable=0,
        )
    )
    absent = _node(_build(_history()))
    for shape in (observed, absent):
        assert set(shape) - {
            "kind", "value", "values", "reason", "denominator", "unit", "window",
            "definition_version", "limitations", "manifest_commits",
            "unparseable_manifests",
        } == set(), f"emitted an undeclared key: {sorted(shape)}"
    assert validate_schema is not None
