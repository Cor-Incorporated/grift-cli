"""Offline integrity and contract tests for the v0.6 benchmark pack."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


ROOT = Path(__file__).parents[1]
PACK = ROOT / "benchmarks" / "v060"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_manifest_and_json_fixtures_are_valid_json() -> None:
    manifest = json.loads((PACK / "sources.json").read_text(encoding="utf-8"))
    for relative_path, expected_hash in manifest["local_artifact_sha256"].items():
        digest = hashlib.sha256((PACK / relative_path).read_bytes()).hexdigest()
        assert digest == expected_hash, relative_path

    for path in [
        PACK / "sources.json",
        PACK / "schemas" / "event-observation.schema.json",
        PACK / "schemas" / "role-validation.schema.json",
        PACK / "schemas" / "benchmark-manifest.schema.json",
        PACK / "expected" / "tracker_fixture_expected.json",
    ]:
        json.loads(path.read_text(encoding="utf-8"))

    for line in (PACK / "data" / "alignment_cases.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_gharchive_fixture_has_expected_shape_and_window() -> None:
    path = PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    allowed = {
        "event_id",
        "event_type",
        "occurred_at",
        "repository",
        "action",
        "ref",
        "object_number",
        "release_tag",
        "push_id",
    }
    event_types = {
        "PushEvent",
        "IssuesEvent",
        "IssueCommentEvent",
        "PullRequestEvent",
        "PullRequestReviewEvent",
        "PullRequestReviewCommentEvent",
        "ReleaseEvent",
    }

    assert len(rows) == 554
    assert len({row["event_id"] for row in rows}) == len(rows)
    assert all(set(row) <= allowed for row in rows)
    assert all(row["event_type"] in event_types for row in rows)
    assert all("actor" not in row and "payload" not in row for row in rows)
    assert all(
        datetime(2024, 1, 15, tzinfo=timezone.utc)
        <= _dt(row["occurred_at"])
        < datetime(2024, 1, 22, tzinfo=timezone.utc)
        for row in rows
    )


def test_gharchive_summaries_reconcile_to_fixture() -> None:
    event_path = PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson"
    summary_path = PACK / "data" / "gharchive_repository_summary.csv"
    rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    with summary_path.open(newline="", encoding="utf-8") as handle:
        summaries = list(csv.DictReader(handle))

    assert sum(int(row["event_count"]) for row in summaries) == len(rows)
    assert {row["repository"] for row in summaries} == {row["repository"] for row in rows}


def test_role_sample_has_balanced_labeled_validation_rows() -> None:
    path = PACK / "data" / "role_ground_truth_sample.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    counts = Counter(row["role_label"] for row in rows)

    assert len(rows) == 40
    assert counts == {
        "Backend": 8,
        "Frontend": 8,
        "Mobile": 8,
        "DevOps": 8,
        "DataScientist": 8,
    }


def test_tracker_contract_matches_expected_values() -> None:
    data_path = PACK / "data" / "tracker_lifecycle_fixture.csv"
    expected_path = PACK / "expected" / "tracker_fixture_expected.json"
    with data_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["project_id"]].append(row)

    for project_id, project_expected in expected.items():
        if project_id == "fixture_kind" or project_id == "must_not_emit":
            continue
        project_rows = grouped[project_id]
        active_days = {
            _dt(row[field]).date()
            for row in project_rows
            for field in (
                "created_at",
                "in_progress_at",
                "first_review_at",
                "merged_at",
                "closed_at",
                "release_at",
            )
            if row[field]
        }
        issue_hours = [
            (_dt(row["closed_at"]) - _dt(row["created_at"])).total_seconds() / 3600
            for row in project_rows
            if row["record_type"] == "issue" and row["closed_at"]
        ]
        pr_hours = [
            (_dt(row["merged_at"]) - _dt(row["created_at"])).total_seconds() / 3600
            for row in project_rows
            if row["record_type"] == "pull_request" and row["merged_at"]
        ]
        release_count = sum(row["record_type"] == "release" for row in project_rows)

        assert len(active_days) == project_expected["active_days"]
        assert median(issue_hours) == project_expected["issue_to_close_median_hours"]
        assert median(pr_hours) == project_expected["pr_to_merge_median_hours"]
        assert release_count == project_expected["release_count"]


CLAIM_PHRASES = (
    "高速開発です",
    "developer_speed",
    "Change Lead Time",
    "生産性スコア",
    "優秀な",
    "PM適合",
    "Frontend Engineerです",
    "overall_alignment_score",
    "pm_fit_score",
)


def _ndjson(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _base_event(**overrides: object) -> dict:
    row = {
        "event_id": "1",
        "event_type": "PushEvent",
        "occurred_at": "2024-01-15T00:01:00Z",
        "repository": "numpy/numpy",
        "action": None,
        "ref": None,
        "object_number": None,
        "release_tag": None,
        "push_id": 1,
    }
    row.update(overrides)
    return row


def test_unknown_event_type_is_not_silently_counted(tmp_path: Path) -> None:
    from tep_core.archive_events import load_archive_events
    from tep_core.secrets_guard import InputValidationError

    path = _ndjson(tmp_path / "e.ndjson", [_base_event(event_type="WikiEvent")])
    try:
        load_archive_events(path)
    except InputValidationError as exc:
        assert "unknown_event_type" in str(exc)
        return
    raise AssertionError("unknown event type must not be aggregated")


def test_outside_window_is_rejected(tmp_path: Path) -> None:
    from tep_core.archive_events import load_archive_events
    from tep_core.secrets_guard import InputValidationError

    path = _ndjson(tmp_path / "e.ndjson", [_base_event(occurred_at="2023-01-01T00:00:00Z")])
    try:
        load_archive_events(path)
    except InputValidationError as exc:
        assert "outside" in str(exc)
        return
    raise AssertionError("out-of-window events must be refused")


def test_duplicate_event_id_is_reported(tmp_path: Path) -> None:
    from tep_core.archive_events import load_archive_events, summarize_archive

    path = _ndjson(
        tmp_path / "e.ndjson",
        [
            _base_event(event_id="dup"),
            _base_event(event_id="dup", occurred_at="2024-01-15T00:02:00Z"),
        ],
    )
    bundle = load_archive_events(path)
    assert bundle.duplicate_count == 1
    summary = summarize_archive(bundle)
    assert summary["duplicate_count"]["value"] == 1
    assert summary["duplicate_rate"]["value"] > 0


def test_release_only_is_not_fast_development(tmp_path: Path) -> None:
    from tep_core.archive_events import load_archive_events, summarize_archive
    from tep_core.event_rhythm import event_rhythm
    from tep_core.report_v2 import render_evidence_markdown

    path = _ndjson(
        tmp_path / "e.ndjson",
        [
            _base_event(
                event_id="r1", event_type="ReleaseEvent", occurred_at="2024-01-15T00:01:00Z"
            ),
            _base_event(
                event_id="r2", event_type="ReleaseEvent", occurred_at="2024-01-16T00:01:00Z"
            ),
        ],
    )
    bundle = load_archive_events(path)
    blob = json.dumps(summarize_archive(bundle)) + json.dumps(event_rhythm(bundle))
    blob += render_evidence_markdown(
        {
            "schema_version": "report-v2",
            "subject": {"kind": "repo", "selection": "repo_all_human"},
            "provenance": {"observation_date": "2024-01-21", "window_basis": "explicit_as_of"},
            "event_observation": summarize_archive(bundle),
            "event_rhythm": event_rhythm(bundle),
            "role_lens": {},
            "input_coverage": {},
        }
    )
    for phrase in CLAIM_PHRASES:
        assert phrase not in blob


def test_push_time_is_not_dora_lead_time() -> None:
    from tep_core.archive_events import load_archive_events, summarize_archive

    path = PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson"
    notes = " ".join(summarize_archive(load_archive_events(path)).get("limitations") or [])
    assert "lead time" in notes.lower() or "DORA" in notes
    assert "not DORA" in notes or "not DORA" in notes.replace("  ", " ")


def test_role_sample_is_classifier_validation_not_actor_label() -> None:
    from tep_core.role_validation import validate_role_sample

    payload = validate_role_sample(PACK / "data" / "role_ground_truth_sample.csv")
    assert payload["sample_size"] == 40
    assert payload["sample_size_warning"]
    assert payload["class_support"]["Frontend"] == 8
    text = json.dumps(payload, ensure_ascii=False)
    assert "Frontendラベルに対する分類器の検証結果" in text
    assert "Frontend Engineerです" not in text


def test_role_sample_cannot_join_actor_identity() -> None:
    from tep_core.role_validation import refuse_actor_join
    from tep_core.secrets_guard import InputValidationError

    try:
        refuse_actor_join()
    except InputValidationError as exc:
        assert "cannot be joined" in str(exc)
        return
    raise AssertionError("role sample join must be refused")


def test_tracker_fixture_is_synthetic_and_deterministic() -> None:
    from tep_core.tracker_lifecycle import load_tracker_lifecycle, summarize_lifecycle

    path = PACK / "data" / "tracker_lifecycle_fixture.csv"
    first = summarize_lifecycle(load_tracker_lifecycle(path))
    second = summarize_lifecycle(load_tracker_lifecycle(path))
    assert first == second
    assert first["fixture_kind"] == "synthetic_contract"
    expected = json.loads(
        (PACK / "expected" / "tracker_fixture_expected.json").read_text(encoding="utf-8")
    )
    constant = first["projects"]["project_constant"]
    assert constant["active_days"]["value"] == expected["project_constant"]["active_days"]
    assert (
        constant["issue_to_close_median_hours"]
        == expected["project_constant"]["issue_to_close_median_hours"]
    )


def test_tracker_row_order_does_not_change_result(tmp_path: Path) -> None:
    from tep_core.tracker_lifecycle import load_tracker_lifecycle, summarize_lifecycle

    source = (PACK / "data" / "tracker_lifecycle_fixture.csv").read_text(encoding="utf-8")
    lines = source.splitlines()
    header, body = lines[0], lines[1:]
    reversed_csv = tmp_path / "rev.csv"
    reversed_csv.write_text("\n".join([header, *body[::-1]]) + "\n", encoding="utf-8")
    left = summarize_lifecycle(
        load_tracker_lifecycle(PACK / "data" / "tracker_lifecycle_fixture.csv")
    )
    right = summarize_lifecycle(load_tracker_lifecycle(reversed_csv))
    assert left["projects"] == right["projects"]


def test_alignment_cases_have_required_columns_and_no_overall() -> None:
    from tep_cli.benchmark_cmd import _alignment_rows
    from tep_core.benchmark import load_manifest

    rows = _alignment_rows(load_manifest(PACK / "sources.json"))
    assert rows
    for row in rows:
        for key in (
            "axis",
            "requirement",
            "observed",
            "unit",
            "source",
            "n",
            "coverage",
            "limitations",
        ):
            assert key in row
        assert "score" not in row
        assert "rank" not in row


def test_manifest_validate_and_hash_mutation(tmp_path: Path) -> None:
    from tep_core.benchmark import validate_manifest
    from tep_core.secrets_guard import InputValidationError

    ok = validate_manifest(PACK / "sources.json")
    assert ok["ok"] is True
    pack = tmp_path / "pack"
    (pack / "data").mkdir(parents=True)
    blob = b"fixture-bytes"
    (pack / "data" / "x.txt").write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    manifest = {
        "pack_id": "mini",
        "pack_version": "1",
        "as_of": "2026-08-29",
        "purpose": "hash mutation",
        "policy": {
            "offline_core": True,
            "raw_external_datasets_bundled": False,
            "individual_ranking": False,
            "role_or_fit_truth": False,
            "required_report_fields": ["source"],
        },
        "artifacts": [
            {
                "id": "mini",
                "kind": "acquired_derived_event_snapshot",
                "source_url": "https://example.invalid",
                "source_version": "1",
                "as_of": "2026-08-29",
                "window": "n/a",
                "n": 1,
                "denominator": "1",
                "coverage": "local",
                "use_for": ["hash"],
                "do_not_use_for": ["ranking"],
                "limitations": ["test"],
                "quality_notes": ["test"],
            }
        ],
        "local_artifact_sha256": {"data/x.txt": digest},
    }
    (pack / "sources.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_manifest(pack / "sources.json")["ok"] is True
    manifest["local_artifact_sha256"]["data/x.txt"] = "0" + digest[1:]
    (pack / "sources.json").write_text(json.dumps(manifest), encoding="utf-8")
    try:
        validate_manifest(pack / "sources.json")
    except InputValidationError as exc:
        assert "hash mismatch" in str(exc)
        return
    raise AssertionError("mutated hash must fail validate")


def test_unregistered_path_is_refused(tmp_path: Path) -> None:
    from tep_core.benchmark import assert_registered_file, load_manifest
    from tep_core.secrets_guard import InputValidationError

    manifest = load_manifest(PACK / "sources.json")
    outsider = tmp_path / "sneak.ndjson"
    outsider.write_text("{}\n", encoding="utf-8")
    try:
        assert_registered_file(manifest, outsider)
    except InputValidationError as exc:
        assert "unregistered" in str(exc)
        return
    raise AssertionError("unregistered fixture must be refused")


def test_offline_fixture_tests_survive_socket_block(monkeypatch) -> None:
    import socket

    def blocked(*_args, **_kwargs):
        raise OSError("network disabled")

    monkeypatch.setattr(socket, "socket", blocked)
    from tep_core.archive_events import load_archive_events
    from tep_core.benchmark import validate_manifest

    validate_manifest(PACK / "sources.json")
    bundle = load_archive_events(PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson")
    assert len(bundle.events) == 554


def test_cli_benchmark_list_inspect_validate(capsys, monkeypatch) -> None:
    from tep_cli.__main__ import main

    monkeypatch.setenv("GRIFT_BENCHMARK_PACK", str(PACK / "sources.json"))
    assert main(["benchmark", "validate", str(PACK / "sources.json")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert main(["benchmark", "list", str(PACK / "sources.json")]) == 0
    listed = json.loads(capsys.readouterr().out)
    ids = {item["id"] for item in listed["artifacts"]}
    assert "gharchive-2024-01-15-to-21-selected-repos" in ids
    assert (
        main(
            [
                "benchmark",
                "inspect",
                "gharchive-2024-01-15-to-21-selected-repos",
                "--manifest",
                str(PACK / "sources.json"),
            ]
        )
        == 0
    )
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["event_observation"]["sample_size"] == 554
    assert inspected["event_observation"]["repository_event_counts"]["values"]
    total = sum(inspected["event_observation"]["repository_event_counts"]["values"].values())
    assert total == 554


def test_cli_benchmark_role_inspect(capsys, monkeypatch) -> None:
    from tep_cli.__main__ import main

    monkeypatch.setenv("GRIFT_BENCHMARK_PACK", str(PACK / "sources.json"))
    assert (
        main(
            [
                "benchmark",
                "inspect",
                "technical-role-ground-truth-zenodo-3986172",
                "--manifest",
                str(PACK / "sources.json"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["role_validation"]["sample_size"] == 40
    assert "sample_size_warning" in payload["role_validation"]


def test_project_without_forge_review_is_not_zero(tmp_path: Path, capsys) -> None:
    from tep_cli.__main__ import main
    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="app.py")
    assert main(["project", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    review = payload["observed"]["coordination_profile"]["review"]
    assert review["kind"] == "not_observed"
    assert review.get("value") != 0
    md_code = main(["project", str(repo), "--format", "md"])
    assert md_code == 0
    text = capsys.readouterr().out
    assert "0 件" not in text.split("review")[-1][:80] or "未観測" in text
    assert "not_observed" in text or "未観測" in text


def test_project_rejects_unbound_benchmark_exports(tmp_path: Path, capsys, monkeypatch) -> None:
    from tep_cli.__main__ import main
    from git_fixture import commit, init_repo

    monkeypatch.setenv("GRIFT_BENCHMARK_PACK", str(PACK / "sources.json"))
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="app.py")
    code = main(
        [
            "project",
            str(repo),
            "--forge-export",
            str(PACK / "data" / "gharchive_events_2024-01-15_to_21.ndjson"),
            "--tracker-export",
            str(PACK / "data" / "tracker_lifecycle_fixture.csv"),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "benchmark collection, not a target-bound subject export" in captured.err


def test_actor_does_not_ingest_role_sample(tmp_path: Path, capsys, monkeypatch) -> None:
    from tep_cli.__main__ import main
    from git_fixture import commit, init_repo

    monkeypatch.setenv("GRIFT_BENCHMARK_PACK", str(PACK / "sources.json"))
    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="src/app.py")
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    code = main(
        [
            "actor",
            "candidate_001",
            str(repo),
            "--identity",
            str(ident),
            "--reference",
            "technical-role-ground-truth-zenodo-3986172",
            "--format",
            "json",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "cannot be joined" in err or "role" in err.lower()


def test_alignment_missing_axis_has_no_overall(tmp_path: Path, capsys) -> None:
    from tep_cli.__main__ import main
    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    commit(repo, email="a@example.com", date="2026-08-01", message="feat", filename="src/app.py")
    ident = repo / ".tep" / "identity.toml"
    ident.parent.mkdir(parents=True)
    ident.write_text(
        'schema_version = "identity-v1"\n\n[[actors]]\ncanonical_id = "candidate_001"\n'
        'emails = ["a@example.com"]\nattribution_state = "verified"\n',
        encoding="utf-8",
    )
    project = tmp_path / "p.toml"
    project.write_text('schema_version = "tep-project-v1"\nproject_id = "x"\n', encoding="utf-8")
    assert (
        main(
            [
                "align",
                "--repo",
                str(repo),
                "--identity",
                str(ident),
                "--actor",
                "candidate_001",
                "--project",
                str(project),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert "overall" not in payload
    assert "score" not in payload
    assert payload["missing_axes"]
    assert payload["coverage"]["status"] == "partial"


def test_event_rhythm_denominator_changes_digest(tmp_path: Path) -> None:
    from tep_core.archive_events import load_archive_events
    from tep_core.event_rhythm import event_rhythm

    path = _ndjson(
        tmp_path / "e.ndjson",
        [_base_event(event_id="a"), _base_event(event_id="b", occurred_at="2024-01-16T00:00:00Z")],
    )
    bundle = load_archive_events(path)
    left = event_rhythm(bundle, window_days=7)
    right = event_rhythm(bundle, window_days=14)
    assert left["active_day_share"]["denominator"] == 7
    assert right["active_day_share"]["denominator"] == 14
    assert left["digest"] != right["digest"]


def test_timezone_offset_is_not_silently_equated(tmp_path: Path) -> None:
    from tep_core.archive_events import load_archive_events

    path = _ndjson(
        tmp_path / "e.ndjson",
        [_base_event(occurred_at="2024-01-15T09:00:00+09:00")],
    )
    bundle = load_archive_events(path)
    assert any("normalized_to_utc_from" in rule for rule in bundle.timezone_rules)
    assert bundle.events[0].occurred_at.endswith("Z")
    assert bundle.events[0].occurred_at != "2024-01-15T09:00:00Z"


def test_catalog_entries_have_required_fields() -> None:
    from tep_core.benchmark import catalog, load_manifest

    entries = catalog(load_manifest(PACK / "sources.json"))
    for entry in entries:
        for key in (
            "id",
            "kind",
            "source_url",
            "source_version",
            "use_for",
            "do_not_use_for",
            "quality_notes",
        ):
            assert key in entry
        assert entry["sha256"] or entry["sha256_unavailable_reason"]


def test_reference_n_below_30_has_no_quantile_or_verdict() -> None:
    node = {
        "kind": "not_proven",
        "reason": "reference_too_small",
        "n": 29,
    }
    blob = json.dumps(node)
    assert "percentile" not in blob
    assert "quantile" not in blob
    assert "rank" not in blob
    assert "pass" not in blob
    assert node["kind"] != "observed"


def test_help_lists_benchmark(capsys) -> None:
    import pytest
    from tep_cli.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "benchmark" in capsys.readouterr().out
