"""ADR-0001 R4 (v0.8.1 #4): volume observations disclose how they can be inflated.

The public site says "anyone can produce volume"; the CLI still reports raw
activity counts (report-v1 ``activity``, report-v2 ``change_rhythm.active_days_180d``,
and the ``align`` axis that compares the latter against ``active_days_180d_min``).
These tests require that each of those carries, in ``limitations``, one fixed
sentence saying how the number can be inflated. The sentence is a disclosure,
not a correction: no value is weighted, normalised or capped (norms §7).

Boundary catalogue (written before the implementation; GAP-site-vs-cli row 4)

| boundary                 | touched | how it is covered                                           |
|--------------------------|---------|-------------------------------------------------------------|
| mock <-> real git        | yes     | every report here comes from a real ``git init`` fixture    |
| declaration <-> enforced | yes     | the constant in ``v2_constants`` (declaration) is looked up |
|                          |         | in the emitted JSON *and* Markdown (enforcement); the       |
|                          |         | schema asset ``report_activity.limitations`` is exercised   |
|                          |         | by ``validate_report_v2`` on the emitted payload            |
| verifier itself          | yes     | ``verify`` on this code's own output stays VERIFIED;        |
|                          |         | 0.7.2 output -> this ``verify`` is measured in the PR body  |
| baseline layer (vocab)   | yes     | ``check_forbidden_vocab.violations`` on the sentence        |
| client<->API, env/IAM,   | no      | --                                                          |
| external API, long-lived |         |                                                             |
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core.analyze import analyze_repository
from tep_core.identity import load_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown
from tep_core.schema import validate_report
from tep_core.schema_v2 import validate_alignment, validate_report_v2
from tep_core.v2_constants import ACTIVE_DAYS_INFLATION_LIMITATION

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_forbidden_vocab import violations  # noqa: E402  (scripts/ is added to sys.path above)

CORRECTION_WORDS = ("補正し", "重み", "正規化", "換算", "減点")


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    for index in range(22):
        commit(
            repo,
            email="a@example.com",
            date=f"2026-08-{(index % 20) + 1:02d}",
            message=f"feat: {index}",
            filename="src/app.py",
            name="Alice",
        )
    return repo


def _identity(repo: Path) -> Path:
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True, exist_ok=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    return ident


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project.toml"
    project.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "p"\ntitle = "P"\n\n'
        "[requirements.change_rhythm]\nactive_days_180d_min = 5\nmedian_gap_days_max = 14\n",
        encoding="utf-8",
    )
    return project


def test_inflation_sentence_is_a_disclosure_not_a_correction() -> None:
    assert violations(ACTIVE_DAYS_INFLATION_LIMITATION) == []
    # It must name the path (a commit a day) and must not promise an adjustment.
    assert "commit" in ACTIVE_DAYS_INFLATION_LIMITATION
    for word in CORRECTION_WORDS:
        assert word not in ACTIVE_DAYS_INFLATION_LIMITATION.replace("補正もしません", ""), word


def test_report_v1_activity_discloses_inflation_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    identity = load_identity(_identity(repo))
    report = analyze_repository(repo, identity, Lineage(), scope="tenant")
    activity = report["activity"]
    assert ACTIVE_DAYS_INFLATION_LIMITATION in (report.get("limitations") or []), sorted(report)
    # P0-legacy-activity-parity (tests/fixtures/v060/run_p0_falsify.py) keeps the
    # report-v1 `activity` block byte-identical to v0.5.9, so the disclosure may
    # not live inside it.
    assert "limitations" not in activity, sorted(activity)
    # The raw numbers stay exactly as observed: disclosure, not correction.
    assert activity["active_days"]["value"] == 20
    assert activity["tenant_commits"]["value"] == 22
    assert validate_report(report) == []
    assert ACTIVE_DAYS_INFLATION_LIMITATION in render_markdown(report)


def test_report_v2_rhythm_and_activity_disclose_inflation_path(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    assert main(["repo", str(repo), "--format", "json", "--as-of", "2026-08-29"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert validate_report_v2(payload) == []
    rhythm = payload["change_rhythm"]
    assert ACTIVE_DAYS_INFLATION_LIMITATION in rhythm["limitations"]
    assert rhythm["active_days_180d"]["value"] == 20
    assert ACTIVE_DAYS_INFLATION_LIMITATION in (payload["activity"].get("limitations") or []), (
        sorted(payload["activity"])
    )
    assert main(["repo", str(repo), "--format", "md", "--as-of", "2026-08-29"]) == 0
    assert ACTIVE_DAYS_INFLATION_LIMITATION in capsys.readouterr().out


def test_alignment_active_days_axis_discloses_inflation_path(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    ident = _identity(repo)
    project = _project(tmp_path)
    args = [
        "align",
        "--repo",
        str(repo),
        "--identity",
        str(ident),
        "--actor",
        "alice",
        "--project",
        str(project),
        "--as-of",
        "2026-08-29",
        "--format",
    ]
    assert main([*args, "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert validate_alignment(payload) == []
    by_axis = {axis["axis"]: axis for axis in payload["axes"]}
    active = by_axis["change_rhythm.active_days_180d"]
    assert ACTIVE_DAYS_INFLATION_LIMITATION in active["limitations"]
    # The comparison itself is untouched: 20 observed days >= 5 declared.
    assert active["comparison"] == "overlap"
    assert active["observed"]["value"] == 20
    # Only the volume axis carries the volume disclosure.
    assert (
        ACTIVE_DAYS_INFLATION_LIMITATION
        not in by_axis["change_rhythm.median_gap_days"]["limitations"]
    )
    assert main([*args, "md"]) == 0
    assert ACTIVE_DAYS_INFLATION_LIMITATION in capsys.readouterr().out


def test_actor_reports_disclose_inflation_path_in_both_scopes(tmp_path: Path, capsys) -> None:
    """Both actor populations carry the sentence, not only the repo subject.

    `_actor_cluster_activity` (public inferred actor) and `_tenant_actor_activity`
    (explicit identity) build `activity` separately from the repo path; removing
    the sentence from either passed every earlier test.
    """
    repo = _repo(tmp_path)
    assert main(["actor", "--all", str(repo), "--format", "json", "--as-of", "2026-08-29"]) == 0
    listing = json.loads(capsys.readouterr().out)
    actor_id = listing["actors"][0]["actor_id"]
    assert main(["actor", actor_id, str(repo), "--format", "json", "--as-of", "2026-08-29"]) == 0
    inferred = json.loads(capsys.readouterr().out)
    assert inferred["subject"]["selection"] == "inferred_actor"
    assert inferred["activity"]["scope"] == "actor_cluster"
    assert ACTIVE_DAYS_INFLATION_LIMITATION in inferred["activity"]["limitations"]

    ident = _identity(repo)
    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--identity",
                str(ident),
                "--format",
                "json",
                "--as-of",
                "2026-08-29",
            ]
        )
        == 0
    )
    tenant = json.loads(capsys.readouterr().out)
    assert tenant["activity"]["scope"] == "tenant"
    assert ACTIVE_DAYS_INFLATION_LIMITATION in tenant["activity"]["limitations"]
    assert validate_report_v2(tenant) == []


def test_contribution_withholds_the_report_v1_limitations(tmp_path: Path) -> None:
    """The sentence annotates `activity`, which contribution already withholds."""
    from tep_core.contribute import build_contribution
    from tep_core.identity import empty_identity

    repo = _repo(tmp_path)
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")
    assert ACTIVE_DAYS_INFLATION_LIMITATION in report["limitations"]
    payload = build_contribution(report)
    assert "limitations" not in payload["metrics"]
    assert ACTIVE_DAYS_INFLATION_LIMITATION not in json.dumps(payload, ensure_ascii=False)
