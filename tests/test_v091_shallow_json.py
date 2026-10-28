"""0.9.1 J3 and J4: what the JSON says about a shallow clone.

J3: project-v1 now records `provenance.revision_completeness` when it observed a
repository (the same shape as report-v2), so the project Markdown calls a
proven-complete history 「全履歴」 and keeps the note for a shallow or unknown one.
A saved project-v1 without the key still loads and renders as unknown.

J4: on a shallow clone report-v2 said "repository-wide counts, spans and actor
totals are reported as not_observed", while surface_profile, change_rhythm and an
actor's own activity were observed from the fetched commits. The limitation now
names what is not_observed and what was counted from the fetched commits; every
case below runs `git clone --depth` and checks each named path's `kind`.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core import trait_tables as tables
from tep_core.report import render_markdown
from tep_core.schema_v2 import validate_project

AS_OF = "2026-08-31"
DEPTH = 22
COMPLETE = {"shallow": False, "promisor": False, "complete": True}
SHALLOW = {"shallow": True, "promisor": False, "complete": False}
TRUNCATED = "The commit graph is truncated"
_SENTENCE = re.compile(
    r"^The commit graph is truncated \(shallow clone\)\. "
    r"Reported as not_observed \(history_incomplete\): (?P<missing>.+?)\. "
    r"Every other value in these blocks counts only the fetched commits: (?P<counted>.+)\.$"
)
# Blocks that hold plain counts and no `kind` node of their own.
_PLAIN_COUNT_BLOCKS = {"population"}
# Blocks, or parts of one, that do not count commits: files at HEAD, which inputs
# were given, bound forge/tracker exports, owner declarations, a display preset, and
# the catalog placement of the forge event rhythm (review M2-M4).
_NOT_FROM_COMMITS = {
    "test_frameworks",
    "input_coverage",
    "event_observation",
    "event_rhythm",
    "tracker_lifecycle",
    "outcome",
    "role_lens",
    "reference",
    "coordination_profile.review",
    "coordination_profile.tracker",
}


class Clones(NamedTuple):
    full: Path
    shallow: Path
    identity: Path
    forge_shallow: Path
    forge_export: Path


def _identity_text() -> str:
    return "\n".join(
        [
            'schema_version = "identity-v2"',
            "",
            "[[actors]]",
            'canonical_id = "alice"',
            'emails = ["alice@example.com"]',
            'attribution_state = "claimed"',
            'consent = "recorded-explicit-consent"',
            'authority = "subject-authorization"',
            "",
        ]
    )


@pytest.fixture(scope="module")
def clones(tmp_path_factory: pytest.TempPathFactory) -> Clones:
    base = tmp_path_factory.mktemp("v091-shallow")
    source = init_repo(base / "full")
    for index in range(30):
        who = "alice" if index % 2 == 0 else "bob"
        commit(
            source,
            email=f"{who}@example.com",
            date=f"2026-06-{index + 1:02d}",
            message=f"feat: change {index}",
            filename="tests/test_svc.py" if index % 3 == 0 else "src/api/svc.py",
            name=who.title(),
        )
    shallow = base / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", str(DEPTH), f"file://{source}", str(shallow)],
        check=True,
    )
    identity = base / "identity.toml"
    identity.write_text(_identity_text(), encoding="utf-8")
    forge_shallow = base / "forge-shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", str(DEPTH), f"file://{source}", str(forge_shallow)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(forge_shallow), "remote", "set-url", "origin", FORGE_ORIGIN],
        check=True,
    )
    export = _forge_export(base / "forge-export.json", forge_shallow)
    return Clones(source, shallow, identity, forge_shallow, export)


FORGE_ORIGIN = "https://github.com/acme/shallow-json.git"


def _forge_export(path: Path, repo: Path) -> Path:
    """A bound forge export of six review events (review M2: review counts come from it)."""
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    binding = {
        "provider": "github",
        "host": "github.com",
        "project_id": "R_shallow_json_1",
        "project_path": "acme/shallow-json",
        "target_oid": {"algorithm": "sha1", "value": head},
        "window": {"start": "2026-06-01T00:00:00Z", "end": "2026-07-01T00:00:00Z"},
        "coverage": {
            "status": "complete",
            "observed": 30,
            "expected": 30,
            "missing": 0,
            "unit": "days",
        },
    }
    events = [
        {
            "event_id": f"review-{index}",
            "kind": "pull_request_review",
            "timestamp": f"2026-06-{index + 10:02d}T00:00:00Z",
            "actor_canonical_id": "alice",
            "project_id": binding["project_id"],
            "project_path": binding["project_path"],
            "pr_number": index + 1,
            "commit_sha": head,
        }
        for index in range(6)
    ]
    payload = {"schema_version": "tep-forge-export-v2", "binding": binding, "events": events}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue() + err.getvalue()


def _cli(argv: list[str]) -> str:
    code, text = _run(argv)
    assert code == 0, (argv[0], text)
    return text


def _json(argv: list[str]) -> dict[str, Any]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main([*argv, "--as-of", AS_OF, "--format", "json"])
    assert code == 0, argv
    return json.loads(out.getvalue())


def _project(repo: Path) -> dict[str, Any]:
    return _json(["project", str(repo)])


def _project_md(repo: Path) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["project", str(repo), "--as-of", AS_OF, "--format", "md"])
    assert code == 0
    return out.getvalue()


def _evidence_rows(markdown: str) -> list[str]:
    """Rows of the opening section's 「根拠」 table (before the 0.8.0 detail layer)."""
    start = markdown.index(tables.HEADINGS["evidence"])
    rows = []
    for line in markdown[start:].splitlines()[1:]:
        if line.startswith("#"):
            break
        if line.startswith("| ") and not line.startswith("|---"):
            rows.append(line)
    return rows[1:]


# --- J3: project-v1 records revision_completeness -------------------------------


def test_project_records_whether_its_repository_is_a_shallow_clone(clones: Clones) -> None:
    full = _project(clones.full)
    shallow = _project(clones.shallow)
    assert full["provenance"].get("revision_completeness") == COMPLETE, full["provenance"]
    assert shallow["provenance"].get("revision_completeness") == SHALLOW, shallow["provenance"]
    # The same value the repo report of the same clone records.
    repo = _json(["repo", str(clones.shallow)])
    assert repo["provenance"]["revision_completeness"] == SHALLOW
    assert validate_project(full) == []
    assert validate_project(shallow) == []


def test_a_declared_only_project_records_no_revision_completeness(tmp_path: Path) -> None:
    requirements = tmp_path / "project.toml"
    requirements.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "payments-api"\n', encoding="utf-8"
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["project", "--requirements", str(requirements), "--format", "json"])
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["observed"]["kind"] == "not_observed"
    assert "revision_completeness" not in payload["provenance"]


@pytest.mark.parametrize(
    ("value", "observed"),
    [
        ({**COMPLETE, "partial": False}, True),
        ({"shallow": "no", "promisor": False, "complete": True}, True),
        ({"shallow": True, "promisor": False, "complete": True}, True),
        ({"shallow": False, "promisor": True, "complete": True}, True),
        ("complete", True),
        (COMPLETE, False),
    ],
    ids=[
        "extra-key",
        "not-boolean",
        "shallow-but-complete",
        "promisor-but-complete",
        "string",
        "without-a-repository",
    ],
)
def test_validate_project_refuses_a_broken_revision_completeness(
    clones: Clones, value: Any, observed: bool
) -> None:
    report = _project(clones.full)
    report["provenance"]["revision_completeness"] = value
    if not observed:
        report["observed"] = {"kind": "not_observed", "reason": "repository_not_provided"}
    errors = validate_project(report)
    assert any(error.startswith("$.provenance.revision_completeness") for error in errors), errors


def test_project_markdown_calls_a_proven_complete_history_whole(clones: Clones) -> None:
    markdown = _project_md(clones.full)
    whole = tables.SECTION_TEXTS["history"].format(end=AS_OF)
    counted = [row for row in _evidence_rows(markdown) if "〜" not in row]
    assert counted, markdown
    same = tables.SECTION_TEXTS["same_period"]
    assert all(row.endswith((f"| {whole} |", f"| {same} |")) for row in counted), counted
    assert any(row.endswith(f"| {whole} |") for row in counted), counted
    assert tables.LIMIT_NOTES["shallow_repo"] not in markdown
    assert tables.LIMIT_NOTES["shallow_repo_recorded"] not in markdown


def test_project_markdown_keeps_the_note_for_a_shallow_clone(clones: Clones) -> None:
    markdown = _project_md(clones.shallow)
    part = tables.SECTION_TEXTS["history_repo"].format(end=AS_OF)
    whole = tables.SECTION_TEXTS["history"].format(end=AS_OF)
    rows = _evidence_rows(markdown)
    assert any(row.endswith(f"| {part} |") for row in rows), rows
    assert not any(whole in row for row in rows), rows
    assert tables.LIMIT_NOTES["shallow_repo_recorded"] in markdown
    # The JSON now says the clone is shallow; the "not recorded" note would be untrue.
    assert tables.LIMIT_NOTES["shallow_repo"] not in markdown


def test_a_saved_project_report_without_the_key_loads_and_renders_as_unknown(
    clones: Clones, tmp_path: Path
) -> None:
    saved = _project(clones.full)
    saved["provenance"].pop("revision_completeness", None)
    assert validate_project(saved) == []
    markdown = render_markdown(saved)
    part = tables.SECTION_TEXTS["history_repo"].format(end=AS_OF)
    assert any(row.endswith(f"| {part} |") for row in _evidence_rows(markdown))
    assert "までの全履歴" not in markdown
    assert tables.LIMIT_NOTES["shallow_repo"] in markdown
    # `grift align` still reads it.
    project_json = tmp_path / "project.json"
    project_json.write_text(json.dumps(saved), encoding="utf-8")
    actor_json = tmp_path / "actor.json"
    actor_json.write_text(json.dumps(_json(["actor", "alice", str(clones.full)])), encoding="utf-8")
    out = io.StringIO()
    align = ["align", "--actor-report", str(actor_json), "--project-report", str(project_json)]
    with contextlib.redirect_stdout(out):
        assert main([*align, "--format", "json"]) == 0
    assert json.loads(out.getvalue())["schema_version"] == "alignment-v1"


@pytest.mark.parametrize("which", ["full", "shallow"])
def test_verify_recomputes_the_revision_completeness_of_a_project_report(
    clones: Clones, tmp_path: Path, which: str
) -> None:
    repo = getattr(clones, which)
    out = tmp_path / "out"
    _cli(["project", str(repo), "--as-of", AS_OF, "--format", "json", "--out", str(out)])
    report_path = out / "project.json"
    code, text = _run(["verify", str(report_path), "--repo", str(repo)])
    assert code == 0, text
    tampered = json.loads(report_path.read_text(encoding="utf-8"))
    tampered["provenance"]["revision_completeness"] = SHALLOW if which == "full" else COMPLETE
    report_path.write_text(json.dumps(tampered), encoding="utf-8")
    code, text = _run(["verify", str(report_path), "--repo", str(repo)])
    assert code == 1, text
    # The difference names both values (review L2).
    recorded = SHALLOW if which == "full" else COMPLETE
    recomputed = COMPLETE if which == "full" else SHALLOW
    expected = f"provenance.revision_completeness: report={recorded!r} recomputed={recomputed!r}"
    assert expected in text, text


def test_verify_accepts_a_saved_project_report_without_the_key(
    clones: Clones, tmp_path: Path
) -> None:
    """Review M4a: a project-v1 saved before 0.9.1 has no key and still verifies."""
    out = tmp_path / "out"
    _cli(["project", str(clones.shallow), "--as-of", AS_OF, "--format", "json", "--out", str(out)])
    report_path = out / "project.json"
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    del saved["provenance"]["revision_completeness"]
    report_path.write_text(json.dumps(saved), encoding="utf-8")
    code, text = _run(["verify", str(report_path), "--repo", str(clones.shallow)])
    assert code == 0, text
    assert text.startswith("VERIFIED"), text


# --- J4: the shallow limitation names exactly what it did ----------------------


def _kind_nodes(node: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        if "kind" in node and path:
            yield path, node
        for key, value in node.items():
            yield from _kind_nodes(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _kind_nodes(value, f"{path}.{index}")


def _at(payload: dict[str, Any], path: str) -> Any:
    node: Any = payload
    for key in path.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + ".")


def _limitation_lists(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    assert payload["provenance"]["revision_completeness"]["shallow"] is True
    truncated = [line for line in payload["limitations"] if line.startswith(TRUNCATED)]
    assert len(truncated) == 1, payload["limitations"]
    match = _SENTENCE.match(truncated[0])
    assert match, truncated[0]
    return match["missing"].split(", "), match["counted"].split(", ")


def _check_missing(nodes: list[tuple[str, dict[str, Any]]], missing: list[str]) -> None:
    incomplete = [path for path, node in nodes if node.get("reason") == "history_incomplete"]
    unnamed = [path for path in incomplete if not any(_under(path, name) for name in missing)]
    assert not unnamed, ("not_observed but not named", unnamed)
    for name in missing:
        inside = [node for path, node in nodes if _under(path, name)]
        assert inside, ("named but absent", name)
        wrong = [
            node
            for node in inside
            if node.get("kind") != "not_observed" or node.get("reason") != "history_incomplete"
        ]
        assert not wrong, ("named not_observed but is not", name, wrong)


def _expected_counted(
    payload: dict[str, Any], nodes: list[tuple[str, dict[str, Any]]], missing: list[str]
) -> set[str]:
    """Every block with an observed value, except what does not count commits; a block
    with an export-fed part is named by its other parts (review M2, M4b)."""

    def observed_under(prefix: str) -> bool:
        return any(n.get("kind") == "observed" for p, n in nodes if _under(p, prefix))

    expected: set[str] = set()
    for name, block in payload.items():
        if name in _NOT_FROM_COMMITS or name in missing:
            continue
        if any(item.startswith(name + ".") for item in _NOT_FROM_COMMITS):
            parts = (f"{name}.{key}" for key in block)
            expected |= {p for p in parts if p not in _NOT_FROM_COMMITS and observed_under(p)}
        elif observed_under(name) or name in _PLAIN_COUNT_BLOCKS:
            expected.add(name)
    return expected


def _check_counted(
    payload: dict[str, Any],
    nodes: list[tuple[str, dict[str, Any]]],
    counted: list[str],
    missing: list[str],
) -> None:
    for name in counted:
        block = _at(payload, name)
        assert isinstance(block, dict), ("named as counted but absent", name)
        assert block.get("kind") != "not_observed", ("named as counted but not_observed", name)
        observed = [n for p, n in nodes if _under(p, name) and n.get("kind") == "observed"]
        assert observed or name in _PLAIN_COUNT_BLOCKS, ("named as counted, nothing observed", name)
    expected = _expected_counted(payload, nodes, missing)
    assert set(counted) == expected, (
        "counted (sentence, expected)",
        sorted(set(counted) - expected),
        sorted(expected - set(counted)),
    )


def _check_against_kinds(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Every named path's kind agrees with the clause it is named in."""
    missing, counted = _limitation_lists(payload)
    nodes = list(_kind_nodes(payload))
    _check_missing(nodes, missing)
    _check_counted(payload, nodes, counted, missing)
    assert not set(missing) & set(counted)
    assert not any("actor totals" in line for line in payload["limitations"])
    return missing, counted


def test_shallow_repo_limitation_matches_each_kind(clones: Clones) -> None:
    payload = _json(["repo", str(clones.shallow)])
    missing, counted = _check_against_kinds(payload)
    expected_missing = {
        "activity",
        "context_profile.scale.first_commit",
        "context_profile.repo_age_days",
    }
    assert expected_missing <= set(missing), missing
    expected_counted = {"surface_profile", "change_rhythm", "verification_profile"}
    assert expected_counted <= set(counted), counted


def test_shallow_actor_limitation_matches_each_kind(clones: Clones) -> None:
    payload = _json(["actor", "alice", str(clones.shallow)])
    missing, counted = _check_against_kinds(payload)
    assert "context_profile.scale.first_commit" in missing, missing
    # An actor's own totals are counted from the fetched commits, not not_observed.
    assert {"activity", "surface_profile", "change_rhythm"} <= set(counted), counted
    assert payload["activity"]["actor_cluster_commits"]["kind"] == "observed"


def test_shallow_consenting_actor_limitation_names_experience_and_role(clones: Clones) -> None:
    payload = _json(["actor", "alice", str(clones.shallow), "--identity", str(clones.identity)])
    missing, counted = _check_against_kinds(payload)
    assert {"experience", "role_profile", "library_context"} <= set(missing), missing
    assert {"activity", "surface_profile"} <= set(counted), counted


def test_shallow_limitation_names_only_the_git_part_of_coordination(clones: Clones) -> None:
    """Review M2/M3: review counts come from the bound forge export, survival from blame
    of the fetched commits, and the sentence is built after the interpretation block."""
    argv = [
        "repo",
        str(clones.forge_shallow),
        "--forge-export",
        str(clones.forge_export),
        "--survival",
        "--reference-version",
        "v2026.11",
    ]
    payload = _json(argv)
    review = payload["coordination_profile"]["review"]
    assert review["kind"] == "observed", review
    assert review["review_event_count"]["value"] == 6, review
    assert payload["event_observation"]["kind"] == "observed"
    assert payload["survival"]["kind"] == "observed"
    assert "interpretation" in payload
    missing, counted = _check_against_kinds(payload)
    assert "coordination_profile" not in counted, counted
    assert {"coordination_profile.git", "survival"} <= set(counted), counted
    assert not {"event_observation", "event_rhythm", "input_coverage"} & set(counted), counted


def test_a_complete_clone_has_no_truncation_limitation(clones: Clones) -> None:
    for argv in (["repo", str(clones.full)], ["actor", "alice", str(clones.full)]):
        payload = _json(argv)
        assert payload["provenance"]["revision_completeness"] == COMPLETE
        assert not [line for line in payload["limitations"] if line.startswith(TRUNCATED)]


def test_verify_recomputes_the_truncation_limitation(clones: Clones, tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    payload = _json(["repo", str(clones.shallow)])
    report.write_text(json.dumps(payload), encoding="utf-8")
    code, text = _run(["verify", str(report), "--repo", str(clones.shallow)])
    assert code == 0, text
    payload["limitations"] = [line for line in payload["limitations"] if TRUNCATED not in line]
    report.write_text(json.dumps(payload), encoding="utf-8")
    code, text = _run(["verify", str(report), "--repo", str(clones.shallow)])
    assert code == 1, text
