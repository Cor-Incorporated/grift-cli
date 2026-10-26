"""v0.9.0 (c): strength and relationship leave the Markdown; JSON keeps them.

ADR-0002 adopted range: `strength` (weak / moderate / strong) reads as a
stronger and a weaker person when two reports sit side by side, and
`relationship` (similar / different direction) reads as fit. 0.9.0 removes
both from every Markdown and keeps the JSON keys, deprecated, until the next
schema version (trait-profile design §3.5, §8 decision 5).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-31"
IDENTITY = """schema_version = "identity-v2"

[[actors]]
canonical_id = "alice"
emails = ["alice@example.com"]
attribution_state = "claimed"
consent = "recorded-explicit-consent"
authority = "subject-authorization"
"""
PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "payments-api"

[requirements.change_rhythm]
median_gap_days_max = 7

[requirements.surfaces]
required = ["backend", "test"]
"""


def _repo(path: Path, email: str, count: int) -> Path:
    repo = init_repo(path)
    start = date(2026, 6, 1)
    for index in range(count):
        day = (start + timedelta(days=index * 2)).isoformat()
        filename = "src/api/svc.py" if index % 3 else f"tests/test_svc_{index}.py"
        commit(repo, email=email, date=day, message=f"feat: {index}", filename=filename, name="A")
    return repo


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    tmp = tmp_path_factory.mktemp("v090c")
    person = _repo(tmp / "person", "alice@example.com", 24)
    team = _repo(tmp / "team", "p@example.com", 30)
    identity = tmp / "identity.toml"
    identity.write_text(IDENTITY, encoding="utf-8")
    requirements = tmp / "requirements.toml"
    requirements.write_text(PROJECT_TOML, encoding="utf-8")
    actor = ["actor", "alice", str(person), "--identity", str(identity), "--as-of", AS_OF]
    actor_json = tmp / "actor.json"
    _cli([*actor, "--format", "json", "--out", str(actor_json)])
    project_dir = tmp / "project-out"
    project = ["project", str(team), "--requirements", str(requirements), "--as-of", AS_OF]
    _cli([*project, "--format", "both", "--out", str(project_dir)])
    align = [
        "align",
        "--actor-report",
        str(actor_json),
        "--project-report",
        str(project_dir / "project.json"),
    ]
    return {
        "actor_md": _cli([*actor, "--format", "md"]),
        "repo_md": _cli(["repo", str(person), "--as-of", AS_OF, "--format", "md"]),
        "project_md": (project_dir / "project.md").read_text(encoding="utf-8"),
        "alignment_md": _cli([*align, "--format", "md"]),
        "alignment_json": _cli([*align, "--format", "json"]),
    }


@pytest.mark.parametrize("name", ["actor_md", "repo_md", "project_md", "alignment_md"])
def test_markdown_carries_no_strength_and_no_relationship(outputs, name: str) -> None:
    text = outputs[name]
    assert "傾向の強さ" not in text, name
    for word in ("weak", "moderate", "strong"):
        assert not re.search(rf"\b{word}\b", text), (name, word)
    assert not re.search(r"^- relationship ", text, re.M), name
    for word in ("similar_direction", "different_direction"):
        assert word not in text, (name, word)
    assert "## 傾向の確からしさ" in text, name


def test_deprecated_strength_is_documented_and_still_in_the_json(outputs) -> None:
    """Deprecated, not removed: the docs say so and a saved 0.9.0 alignment still has it.

    One test holds both sides, so dropping the key without the docs (or the
    docs without the key) fails here with both facts in the message.
    """

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # The release that deprecated the keys; its section stays after later releases.
    release = changelog.split("## [0.9.0]", 1)[1].split("\n## [", 1)[0]
    # Only the Deprecated entries: the Fixed section also names `strength`.
    deprecated = (
        release.split("### Deprecated", 1)[1].split("\n### ", 1)[0]
        if "### Deprecated" in release
        else ""
    )
    schema = (ROOT / "docs" / "alignment-schema.md").read_text(encoding="utf-8")
    payload = json.loads(outputs["alignment_json"])
    backend = next(axis for axis in payload["axes"] if axis["axis"] == "surfaces.backend")
    facts = {
        "changelog_deprecates_strength": "actor_tendency.strength" in deprecated,
        "schema_doc_deprecates_strength": "`strength` は非推奨" in schema,
        "json_strength": backend["actor_tendency"].get("strength"),
        "json_relationship": backend.get("relationship", {}).get("kind"),
    }
    assert facts["changelog_deprecates_strength"], facts
    assert facts["schema_doc_deprecates_strength"], facts
    assert facts["json_strength"] in {"weak", "moderate", "strong"}, facts
    assert facts["json_relationship"] in {
        "similar_direction",
        "different_direction",
        "not_comparable",
    }, facts
