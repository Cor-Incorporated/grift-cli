"""Falsify actor/project observed comparison, verify, event windows, schema."""

from __future__ import annotations

import json
from pathlib import Path

from tep_cli.__main__ import main
from tep_cli.options import build_parser
from tep_core.archive_events import ArchiveBundle, ArchiveEvent
from tep_core.event_rhythm import event_rhythm
from tep_core.schema_v2 import validate_alignment
from tep_core.tendency import relationship
from tep_core.v2_constants import MIN_EVENTS_FOR_SHAPE, MIN_WINDOW_DAYS_FOR_SHAPE

from git_fixture import commit, git, init_repo
from tep_core.gitutil import rev_parse

PACK = Path(__file__).resolve().parents[1] / "benchmarks" / "v060"
ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-15"


def _ident(repo: Path) -> Path:
    path = repo / ".tep" / "identity.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\n'
        'canonical_id = "candidate_001"\nemails = ["a@example.com"]\n'
        'attribution_state = "verified"\n',
        encoding="utf-8",
    )
    return path


def _project_toml(path: Path, surfaces: str = '["backend"]') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""schema_version = "tep-project-v1"
project_id = "checkout-api"
[requirements.surfaces]
required = {surfaces}
""",
        encoding="utf-8",
    )
    return path


def _actor_repo(tmp: Path, name: str = "actor") -> Path:
    repo = init_repo(tmp / name)
    (repo / "src" / "api").mkdir(parents=True)
    commit(
        repo, email="a@example.com", date="2026-08-01", message="feat", filename="src/api/app.py"
    )
    commit(
        repo,
        email="a@example.com",
        date="2026-08-01",
        message="ui",
        filename="src/components/Button.tsx",
    )
    _ident(repo)
    return repo


def _project_repo(tmp: Path, name: str = "project") -> Path:
    repo = init_repo(tmp / name)
    (repo / "src" / "api").mkdir(parents=True)
    commit(
        repo, email="p@example.com", date="2026-08-02", message="feat", filename="src/api/svc.py"
    )
    _project_toml(repo / ".tep" / "project.toml")
    git(repo, "remote", "add", "origin", f"https://github.com/acme/{name}.git")
    return repo


def _bound_partial_forge(repo: Path, path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "tep-forge-export-v2",
                "binding": {
                    "provider": "github",
                    "host": "github.com",
                    "project_id": f"R_{repo.name}",
                    "project_path": f"acme/{repo.name}",
                    "target_oid": {"algorithm": "sha1", "value": rev_parse(repo)},
                    "window": {
                        "start": "2024-01-15T00:00:00Z",
                        "end": "2024-01-22T00:00:00Z",
                    },
                    "coverage": {
                        "status": "partial",
                        "observed": 7,
                        "expected": 168,
                        "missing": 161,
                        "unit": "hours",
                    },
                },
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_reports(tmp: Path, capsys, *, extra_actor: list[str] | None = None) -> tuple[Path, Path]:
    actor = _actor_repo(tmp)
    project = _project_repo(tmp)
    # Explicit actor directory output is the strict v0.6 collection.  These
    # alignment tests intentionally exercise the detailed tenant report file
    # compatibility path.
    actor_out = tmp / "actor-report.json"
    project_out = tmp / "project-out"
    actor_cmd = [
        "actor",
        "candidate_001",
        str(actor),
        "--identity",
        str(actor / ".tep" / "identity.toml"),
        "--as-of",
        AS_OF,
        "--format",
        "json",
        "--out",
        str(actor_out),
    ]
    if extra_actor:
        actor_cmd.extend(extra_actor)
    assert main(actor_cmd) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "project",
                str(project),
                "--requirements",
                str(project / ".tep" / "project.toml"),
                "--as-of",
                AS_OF,
                "--format",
                "json",
                "--out",
                str(project_out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    return actor_out, project_out / "project.json"


def _align(capsys, actor: Path, project: Path, extra: list[str] | None = None) -> dict:
    cmd = [
        "align",
        "--actor-report",
        str(actor),
        "--project-report",
        str(project),
        "--format",
        "json",
    ]
    if extra:
        cmd.extend(extra)
    assert main(cmd) == 0, capsys.readouterr().err
    return json.loads(capsys.readouterr().out)


def _axis(payload: dict, name: str) -> dict:
    for axis in payload["axes"]:
        if axis["axis"] == name:
            return axis
    raise AssertionError(name)


def _set_count(path: Path, value: int) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = payload["observed"]["surface_profile"]["surface_commit_counts"]["values"]
    counts["backend"] = value
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_project_observed_changes_relationship(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    first = _align(capsys, actor, project)
    _set_count(project, 99)
    second = _align(capsys, actor, project)
    left = _axis(first, "surfaces.backend")["relationship"]
    right = _axis(second, "surfaces.backend")["relationship"]
    assert (left.get("kind"), left.get("direction")) != (right.get("kind"), right.get("direction"))
    assert first["actor_report_digest"] == second["actor_report_digest"]


def test_actor_observed_changes_relationship(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    first = _align(capsys, actor, project)
    payload = json.loads(actor.read_text(encoding="utf-8"))
    payload["surface_profile"]["surface_commit_counts"]["values"]["backend"] = 99
    actor.write_text(json.dumps(payload), encoding="utf-8")
    second = _align(capsys, actor, project)
    left = _axis(first, "surfaces.backend")["relationship"]
    right = _axis(second, "surfaces.backend")["relationship"]
    assert (left.get("kind"), left.get("direction")) != (right.get("kind"), right.get("direction"))
    assert first["project_report_digest"] == second["project_report_digest"]


def test_declared_change_does_not_rewrite_observed(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    first = _align(capsys, actor, project)
    payload = json.loads(project.read_text(encoding="utf-8"))
    payload["declared"]["surfaces"] = {
        "kind": "declared",
        "value": ["frontend"],
        "unit": "surface_list",
    }
    project.write_text(json.dumps(payload), encoding="utf-8")
    second = _align(capsys, actor, project)
    assert first["actor_observed"] == second["actor_observed"]
    assert (
        first["project_observed"]["surface_profile"]
        == second["project_observed"]["surface_profile"]
    )


def test_n_denominator_source_window_are_split(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    payload = _align(capsys, actor, project)
    axis = _axis(payload, "surfaces.backend")
    assert "actor_n" in axis and "project_n" in axis
    assert "actor_denominator" in axis and "project_denominator" in axis
    assert axis["actor_source"] != [] and axis["project_source"] != []
    assert (axis["actor_basis"] or {}).get("window")
    assert (axis["project_basis"] or {}).get("window")
    capsys.readouterr()
    assert (
        main(
            [
                "align",
                "--actor-report",
                str(actor),
                "--project-report",
                str(project),
                "--format",
                "md",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "actor_n=" in text
    assert "project_n=" in text
    assert "actor_source=" in text
    assert "project_source=" in text


def test_window_mismatch_is_not_comparable() -> None:
    actor = {"kind": "observed", "value": 4, "unit": "commits"}
    project = {"kind": "observed", "value": 4, "unit": "commits"}
    node = relationship(
        actor_node=actor,
        project_node=project,
        declared_node={"kind": "declared", "value": 1, "unit": "commits"},
        windows_comparable=False,
    )
    assert node["kind"] == "not_comparable"
    unit = relationship(
        actor_node=actor,
        project_node={"kind": "observed", "value": 4, "unit": "hours"},
        declared_node={"kind": "not_declared", "reason": "none"},
        windows_comparable=True,
    )
    assert unit["kind"] == "not_comparable"
    assert unit["reason"] == "unit_mismatch"


def test_overlap_markdown_has_no_hire_words(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    assert (
        main(
            [
                "align",
                "--actor-report",
                str(actor),
                "--project-report",
                str(project),
                "--format",
                "md",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    lowered = text.lower()
    for banned in ("採用すべき", "相性スコア", "frontendエンジニアである"):
        assert banned not in lowered
    assert "傾向" in text
    assert "similar_direction は採用" in text or "採用・適合ではない" in text


def test_saved_alignment_verify(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    out = tmp_path / "al"
    payload = _align(capsys, actor, project, extra=["--out", str(out)])
    assert payload["schema_version"] == "alignment-v1"
    capsys.readouterr()
    code = main(
        [
            "verify",
            str(out / "alignment.json"),
            "--actor-report",
            str(actor),
            "--project-report",
            str(project),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "VERIFIED" in captured.out


def test_tampered_actor_report_is_mismatch(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    out = tmp_path / "al"
    _align(capsys, actor, project, extra=["--out", str(out)])
    capsys.readouterr()
    blob = json.loads(actor.read_text(encoding="utf-8"))
    blob["surface_profile"]["unclassified_count"] = 99
    actor.write_text(json.dumps(blob), encoding="utf-8")
    code = main(
        [
            "verify",
            str(out / "alignment.json"),
            "--actor-report",
            str(actor),
            "--project-report",
            str(project),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "MISMATCH" in captured.out


def test_tampered_project_report_is_mismatch(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    out = tmp_path / "al"
    _align(capsys, actor, project, extra=["--out", str(out)])
    capsys.readouterr()
    blob = json.loads(project.read_text(encoding="utf-8"))
    blob["declared"]["title"] = {"kind": "declared", "value": "tampered", "unit": "text"}
    project.write_text(json.dumps(blob), encoding="utf-8")
    code = main(
        [
            "verify",
            str(out / "alignment.json"),
            "--actor-report",
            str(actor),
            "--project-report",
            str(project),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "MISMATCH" in captured.out


def test_custom_manifest_replay_and_mismatch(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(
        tmp_path,
        capsys,
        extra_actor=[
            "--reference",
            "numfocus-2022-to-2024",
            "--reference-manifest",
            str(PACK / "sources.json"),
        ],
    )
    out = tmp_path / "al"
    _align(
        capsys,
        actor,
        project,
        extra=["--out", str(out), "--reference-manifest", str(PACK / "sources.json")],
    )
    capsys.readouterr()
    ok = main(
        [
            "verify",
            str(out / "alignment.json"),
            "--actor-report",
            str(actor),
            "--project-report",
            str(project),
            "--reference-manifest",
            str(PACK / "sources.json"),
        ]
    )
    assert ok == 0, capsys.readouterr().out
    other = tmp_path / "other.json"
    other.write_text('{"pack_id":"other"}\n', encoding="utf-8")
    capsys.readouterr()
    bad = main(
        [
            "verify",
            str(out / "alignment.json"),
            "--actor-report",
            str(actor),
            "--project-report",
            str(project),
            "--reference-manifest",
            str(other),
        ]
    )
    captured = capsys.readouterr()
    assert bad == 1
    assert "MISMATCH" in captured.out


def test_missing_manifest_cannot_verify(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(
        tmp_path,
        capsys,
        extra_actor=[
            "--reference",
            "numfocus-2022-to-2024",
            "--reference-manifest",
            str(PACK / "sources.json"),
        ],
    )
    out = tmp_path / "al"
    _align(
        capsys,
        actor,
        project,
        extra=["--out", str(out), "--reference-manifest", str(PACK / "sources.json")],
    )
    capsys.readouterr()
    alignment_path = out / "alignment.json"
    blob = json.loads(alignment_path.read_text(encoding="utf-8"))
    blob["provenance"]["reference_manifest"] = str(tmp_path / "missing-sources.json")
    alignment_path.write_text(json.dumps(blob), encoding="utf-8")
    code = main(
        [
            "verify",
            str(alignment_path),
            "--actor-report",
            str(actor),
            "--project-report",
            str(project),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "CANNOT_VERIFY: benchmark manifest is unavailable or different" in captured.out


def test_live_align_markdown_notes_missing_project_observed(tmp_path: Path, capsys) -> None:
    actor = _actor_repo(tmp_path)
    project = tmp_path / "p.toml"
    _project_toml(project)
    assert (
        main(
            [
                "align",
                "--repo",
                str(actor),
                "--identity",
                str(actor / ".tep" / "identity.toml"),
                "--actor",
                "candidate_001",
                "--project",
                str(project),
                "--format",
                "md",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "project observedは未提供のため、actorとprojectの実測比較は行っていません。" in text


def test_invalid_alignment_extra_fields_rejected(tmp_path: Path, capsys) -> None:
    actor, project = _write_reports(tmp_path, capsys)
    payload = _align(capsys, actor, project)
    payload["axes"][0]["relationship"]["kind"] = "hire_fit"
    errors = validate_alignment(payload)
    assert errors
    payload["axes"][0]["relationship"]["kind"] = "similar_direction"
    payload["axes"][0]["actor_n"] = -1
    assert validate_alignment(payload)
    payload["axes"][0]["actor_n"] = 1
    payload["axes"][0]["actor_observed"]["unit"] = "hire"
    assert validate_alignment(payload)
    payload["axes"][0]["actor_observed"]["unit"] = "commits"
    payload["axes"][0]["coverage"]["status"] = "excellent"
    assert validate_alignment(payload)


def test_readme_schema_help_sync() -> None:
    help_text = build_parser()._subparsers._group_actions[0].choices["align"].format_help()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    schema = (ROOT / "docs" / "alignment-schema.md").read_text(encoding="utf-8")
    migration = (ROOT / "docs" / "migration-v060.md").read_text(encoding="utf-8")
    assert "--actor-report" in help_text
    assert "--project-report" in help_text
    assert "actor-report.json" in readme
    assert "relationship" in schema
    assert "project observedは未提供" in migration
    verify_help = build_parser()._subparsers._group_actions[0].choices["verify"].format_help()
    assert "--reference-manifest" in verify_help


def _bundle(days: list[str], start: str, end: str) -> ArchiveBundle:
    events = tuple(
        ArchiveEvent(
            event_id=f"e{index}",
            event_type="PushEvent",
            occurred_at=f"{day}T12:00:00Z",
            repository="acme/app",
            action="push",
            timezone_rule="utc_zulu",
        )
        for index, day in enumerate(days)
    )
    return ArchiveBundle(
        events=events,
        digest="fixture",
        window_start=start,
        window_end=end,
        duplicate_count=0,
        duplicate_rate=0.0,
        timezone_rules=("utc_zulu",),
        dropped_duplicate_ids=(),
    )


def test_event_rhythm_small_n_is_not_proven() -> None:
    empty = event_rhythm(_bundle([], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"))
    assert empty["shape_label"]["kind"] in {"not_observed", "not_proven"}
    one = event_rhythm(_bundle(["2026-01-02"], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"))
    assert one["sample_size"] == 1
    assert one["shape_label"]["kind"] == "not_proven"
    assert one["shape_label"].get("value") not in {"constant", "burst"}
    short = event_rhythm(
        _bundle(
            ["2026-01-0" + str(i) for i in range(1, 9)],
            "2026-01-01T00:00:00Z",
            "2026-01-08T00:00:00Z",
        )
    )
    assert short["window_days"] < MIN_WINDOW_DAYS_FOR_SHAPE
    assert short["shape_label"]["kind"] == "not_proven"


def test_event_rhythm_minimum_can_label() -> None:
    days = [f"2026-01-{index:02d}" for index in range(1, MIN_EVENTS_FOR_SHAPE + 3)]
    labeled = event_rhythm(_bundle(days, "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"))
    assert labeled["shape_label"]["kind"] == "observed"
    assert labeled["shape_label"]["value"] in {"constant", "burst"}
    almost = event_rhythm(
        _bundle(days[: MIN_EVENTS_FOR_SHAPE - 1], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z")
    )
    assert almost["shape_label"]["kind"] == "not_proven"


def test_reversed_event_window_is_refused(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    code = main(
        [
            "project",
            str(repo),
            "--event-window",
            "2026-08-02",
            "2026-08-01",
            "--format",
            "json",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "earlier than END" in err


def test_partial_overlap_is_not_observed_true(tmp_path: Path, capsys) -> None:
    repo = _project_repo(tmp_path)
    forge = _bound_partial_forge(repo, tmp_path / "forge-v2.json")
    assert (
        main(
            [
                "project",
                str(repo),
                "--forge-export",
                str(forge),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    alignment = payload["observed"]["input_coverage"]["window_alignment"]
    assert alignment.get("value") is not True
    assert alignment["kind"] in {"not_proven", "not_observed"}
