"""commit ゼロの actor でも report-v2 が出ることの反証テスト (v0.7.2)。

0.7.0/0.7.1 では `grift actor <commit ゼロの actor>` が exit 2 になった。
`context_profile.language_composition` は builder 側が
`not_observed(commit_paths_unavailable)` を出しうるのに、契約カタログ側は
`observed` 固定を宣言していた。宣言と強制が食い違ったまま、report 自体が
拒否されていた。norms §1 は「入力不足は理由付き not_observed であって能力
否定ではない」と定めるので、report が消えること自体が規範違反である。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tep_cli.__main__ import main
from tep_core.context_profile import build_context_profile
from tep_core.schema import validate_schema

from git_fixture import commit, init_repo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_forbidden_vocab import violations  # noqa: E402

# The P0 falsification suite reads the same three words out of the CLI output.
# Keep them here so a pytest run catches the regression without the P0 harness.
CAPABILITY_DENIAL_WORDS = ("能力不足", "未経験", "弱い")

ALICE = (
    '[[actors]]\ncanonical_id = "alice"\n'
    'emails = ["alice@example.com"]\nattribution_state = "verified"\n'
)
EMPTY = (
    '[[actors]]\ncanonical_id = "empty"\n'
    'emails = ["empty@example.com"]\nattribution_state = "verified"\n'
)


def _identity(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('schema_version = "identity-v1"\n\n' + body, encoding="utf-8")
    return path


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    for index in range(3):
        commit(
            repo,
            email="alice@example.com",
            date="2026-08-01",
            message=f"feat: {index}",
            filename="src/app.py",
            name="Alice",
        )
    return repo


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _payload(text: str) -> dict:
    """Read the report out of stdout, past the admin notice grift prints first."""
    decoder = json.JSONDecoder()
    return decoder.raw_decode(text[text.index("{") :])[0]


def _sections_reasoned(node: object, reason: str, path: str = "$") -> list[tuple[str, dict]]:
    """Every observation node in the report that names `reason`."""
    found: list[tuple[str, dict]] = []
    if isinstance(node, dict):
        if node.get("reason") == reason and "kind" in node:
            found.append((path, node))
        for key, child in node.items():
            found.extend(_sections_reasoned(child, reason, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            found.extend(_sections_reasoned(child, reason, f"{path}[{index}]"))
    return found


def test_actor_without_commits_emits_a_valid_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(a) rc=0、context_profile が契約を通り、理由付き not_observed が残る。"""
    repo = _repo(tmp_path)
    toml = _identity(tmp_path / "empty.toml", ALICE + "\n" + EMPTY)
    code, out = _run(
        capsys,
        ["actor", "empty", str(repo), "--identity", str(toml), "--format", "json"],
    )
    assert code == 0, out
    report = _payload(out)
    assert validate_schema("report-v2", report) == []
    assert report["change_rhythm"]["kind"] == "not_observed"
    assert report["change_rhythm"]["reason"] == "no_actor_commits"
    profile = report["context_profile"]
    # The context layer is repo-scoped, so selecting an actor with no commits
    # must not blank out what the repository itself demonstrably shows.
    assert profile["kind"] == "observed"
    assert profile["analysis_scope"] == "repo"
    assert profile["language_composition"]["kind"] == "observed"
    assert profile["language_composition"]["value"] == {"py": 1.0}


def test_actor_without_commits_states_no_capability_denial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(b) 観測なしを能力の否定としても、捏造した 0 としても語らない。"""
    repo = _repo(tmp_path)
    toml = _identity(tmp_path / "empty.toml", ALICE + "\n" + EMPTY)
    code, markdown = _run(
        capsys,
        ["actor", "empty", str(repo), "--identity", str(toml), "--format", "md"],
    )
    assert code == 0, markdown
    assert violations(markdown) == []
    assert [word for word in CAPABILITY_DENIAL_WORDS if word in markdown] == []

    code, out = _run(
        capsys,
        ["actor", "empty", str(repo), "--identity", str(toml), "--format", "json"],
    )
    assert code == 0, out
    unmeasured = _sections_reasoned(_payload(out), "no_actor_commits")
    assert unmeasured, "no section attributed the absence to the actor having no commits"
    for path, node in unmeasured:
        assert node["kind"] in {"not_observed", "not_proven"}, (path, node)
        # A reason plus a number would restate the absence as a measurement.
        assert "value" not in node, (path, node)


def test_actor_with_commits_stays_observed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(c) 通常の actor は従来どおり observed のまま。"""
    repo = _repo(tmp_path)
    toml = _identity(tmp_path / "empty.toml", ALICE + "\n" + EMPTY)
    code, out = _run(
        capsys,
        ["actor", "alice", str(repo), "--identity", str(toml), "--format", "json"],
    )
    assert code == 0, out
    report = _payload(out)
    assert validate_schema("report-v2", report) == []
    assert report["change_rhythm"]["kind"] == "observed"
    assert report["context_profile"]["language_composition"]["kind"] == "observed"


def test_repo_without_human_commits_emits_a_valid_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """bot だけの repo も同じ経路。no_human_commits で rc=0。"""
    repo = init_repo(tmp_path / "botrepo")
    for index in range(3):
        commit(
            repo,
            email="bot@users.noreply.github.com",
            date="2026-08-01",
            message=f"chore: {index}",
            filename="src/app.py",
            name="dependabot[bot]",
        )
    toml = _identity(
        tmp_path / "bot.toml",
        '[[actors]]\ncanonical_id = "bot"\n'
        'emails = ["bot@users.noreply.github.com"]\nattribution_state = "bot"\n',
    )
    code, out = _run(
        capsys,
        ["repo", str(repo), "--identity", str(toml), "--format", "json"],
    )
    assert code == 0, out
    report = _payload(out)
    assert validate_schema("report-v2", report) == []
    assert report["change_rhythm"]["reason"] == "no_human_commits"


def test_catalog_accepts_every_language_composition_kind_the_builder_emits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """宣言 ↔ 強制の pair.

    宣言側 = `v060-contracts.schema.json` の `$defs.report_context_profile`。
    強制側 = `context_profile.build_context_profile`。builder が
    `not_observed(commit_paths_unavailable)` を出せるのに catalog が
    `observed` 固定なら、report ごと拒否される (0.7.0 の回帰そのもの)。
    片側だけ変えると、両方の値を挙げてこのテストが落ちる。
    """
    from tep_core.analyze import prepare_inputs
    from tep_core.identity import load_identity
    from tep_core.lineage import Lineage

    repo = _repo(tmp_path)
    toml = _identity(tmp_path / "id.toml", ALICE)
    code, out = _run(
        capsys,
        ["repo", str(repo), "--identity", str(toml), "--format", "json"],
    )
    assert code == 0, out
    report = _payload(out)

    identity = load_identity(toml)
    commits, origin = prepare_inputs(repo, identity, Lineage(), include_files=True)
    observed = build_context_profile(repo, commits, origin)
    assert observed["language_composition"]["kind"] == "observed", observed

    # Same history with the per-commit paths dropped: exactly what a GitError
    # inside _attach_files leaves behind.
    for item in commits:
        item.files = ()
    pathless = build_context_profile(repo, commits, origin)
    assert pathless["language_composition"] == {
        "kind": "not_observed",
        "reason": "commit_paths_unavailable",
    }, pathless["language_composition"]

    for profile in (observed, pathless):
        errors = validate_schema("report-v2", {**report, "context_profile": profile})
        assert errors == [], (
            "builder emits language_composition="
            f"{profile['language_composition']!r}, catalog rejects it: {errors}"
        )
