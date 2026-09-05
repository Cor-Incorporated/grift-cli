"""Blind-pilot inventory/audit/summary must not manufacture human facts."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v060_blind_pilot", ROOT / "scripts" / "v060_blind_pilot.py"
)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pilot
SPEC.loader.exec_module(pilot)


def _pool(path: Path) -> None:
    path.write_text(
        """[[repos]]
dir = "BenevolentDirector"
rights = "company"
reference = true
remote = "https://example.invalid/bd.git"

[[repos]]
dir = "corsweb"
rights = "company"
reference = true
remote = "https://example.invalid/cw.git"

[[repos]]
dir = "outside"
rights = "oss"
""",
        encoding="utf-8",
    )


def _answers(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "dir",
                "立ち上げ",
                "引き継ぎ範囲",
                "現在の状況",
                "AI併用",
                "役割構成の実感・補足",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "dir": "BenevolentDirector",
                "立ち上げ": "一から",
                "引き継ぎ範囲": "一部モジュール",
                "現在の状況": "集中開発",
                "AI併用": "主たる実装手段",
                "役割構成の実感・補足": "実質 solo",
            }
        )


def test_legacy_answer_is_not_silently_mapped_to_identity_or_role(tmp_path: Path) -> None:
    pool_path = tmp_path / "pool.toml"
    answers_path = tmp_path / "answers.csv"
    _pool(pool_path)
    _answers(answers_path)

    audit = pilot.questionnaire_audit(pilot.selected_candidates(pool_path), answers_path)
    row = next(row for row in audit["repos"] if row["directory"] == "BenevolentDirector")
    assert row["answers"]["startup"] == "一から"
    assert row["answers"]["authority"] == pilot.NOT_ANSWERED
    assert row["answers"]["role.domain"] == pilot.NOT_ANSWERED
    assert row["legacy_context_not_mapped_to_role_cells"]["role_free_text"] == "実質 solo"
    assert row["status"] == "BLOCKED"


def test_inventory_rejects_path_escape(tmp_path: Path) -> None:
    try:
        pilot._safe_candidate_path(tmp_path, "../elsewhere")
    except ValueError as exc:
        assert "escapes developer root" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("path escape must fail")


def test_parse_pins_rejects_non_generic_oid() -> None:
    assert pilot.parse_pins(["BenevolentDirector=" + "a" * 40]) == {"BenevolentDirector": "a" * 40}
    try:
        pilot.parse_pins(["BenevolentDirector=not-an-oid"])
    except ValueError as exc:
        assert "40-or-64" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("bad pin must fail")


def test_draw_selection_is_closed_bounded_and_includes_references(tmp_path: Path) -> None:
    draw = tmp_path / "draw.json"
    draw.write_text(
        json.dumps(
            {
                "schema": "pilot-draw-v1",
                "picked": [{"dir": f"repo-{index}"} for index in range(10)],
                "references": ["BenevolentDirector", "corsweb"],
            }
        ),
        encoding="utf-8",
    )
    names = pilot.draw_candidate_names(draw)
    assert len(names) == 12
    assert names[-2:] == ["BenevolentDirector", "corsweb"]

    payload = json.loads(draw.read_text(encoding="utf-8"))
    payload["references"] = ["BenevolentDirector"]
    draw.write_text(json.dumps(payload), encoding="utf-8")
    try:
        pilot.draw_candidate_names(draw)
    except ValueError as exc:
        assert "corsweb" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("mandatory corsweb reference must be enforced")


def test_summary_requires_verify_comparison_and_classification() -> None:
    result = pilot.summarize_results(
        [
            {"repo_id": "R1", "kind": "analyze", "exit_code": 0, "seconds": 12.0},
            {"repo_id": "R1", "kind": "verify", "exit_code": 0, "seconds": 1.0},
            {
                "repo_id": "R1",
                "kind": "compare",
                "exit_code": 0,
                "seconds": 0.1,
                "comparisons": [
                    {"cell": "domain", "expected": "core", "observed": "core"},
                    {
                        "cell": "time",
                        "expected": "early",
                        "observed": "recent",
                        "mismatch_classification": "semantic_mapping",
                        "explanation": "respondent used a different period boundary",
                    },
                ],
            },
        ]
    )
    assert result["comparison"]["comparable_cells"] == 2
    assert result["comparison"]["match_rate_percent"] == 50.0
    assert result["gates"]["verify_all_success"] is True
    assert result["gates"]["all_mismatches_classified"] is True
    assert result["pr_ready"] is False


def test_cli_writes_audit_json(tmp_path: Path) -> None:
    pool_path = tmp_path / "pool.toml"
    answers_path = tmp_path / "answers.csv"
    out = tmp_path / "audit.json"
    _pool(pool_path)
    _answers(answers_path)
    assert (
        pilot.main(
            ["--pool", str(pool_path), "--answers", str(answers_path), "audit", "--out", str(out)]
        )
        == 0
    )
    assert json.loads(out.read_text(encoding="utf-8"))["blocked_count"] == 2
    assert out.stat().st_mode & 0o777 == 0o600


def _structured_response(repo_id: str, oid: str) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "target_oid": oid,
        "authority": "owner",
        "local_measurement_authorized": True,
        "identity_consent": "yes",
        "identity_subject": "alice",
        "disclosure": "local_only",
        "startup": "from_scratch",
        "handoff": "minor",
        "context_note": "recorded before observation",
        "role": {
            "domain": ["core"],
            "work_type": ["create"],
            "time": ["early"],
            "process_position": ["creator"],
        },
        "role_rationale": {
            "domain": "expected product code",
            "work_type": "expected initial creation",
            "time": "expected early activity",
            "process_position": "expected creator activity",
        },
        "ai_primary_method": "yes",
        "ai_trailer_memory": "no",
        "ai_trailer_convention": "",
    }


def test_structured_answers_are_closed_and_can_unlock_without_inference(tmp_path: Path) -> None:
    pool_path = tmp_path / "pool.toml"
    answers_path = tmp_path / "answers.json"
    _pool(pool_path)
    oid = "a" * 40
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": "tep-v060-blind-pilot-answers-v1",
                "responses": [
                    _structured_response("BenevolentDirector", oid),
                    _structured_response("corsweb", oid),
                ],
            }
        ),
        encoding="utf-8",
    )

    audit = pilot.questionnaire_audit(pilot.selected_candidates(pool_path), answers_path)
    assert (audit["ready_count"], audit["blocked_count"]) == (2, 0)
    assert audit["repos"][0]["answer_format"] == "structured-v1"
    assert audit["repos"][0]["answers"]["role.domain"] == ["core"]
    assert "@" not in json.dumps(audit)

    payload = json.loads(answers_path.read_text(encoding="utf-8"))
    payload["responses"][0]["unregistered"] = "must fail"
    answers_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        pilot.structured_answers(answers_path)
    except ValueError as exc:
        assert "unknown=['unregistered']" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown structured answer field must fail")


def test_structured_answer_without_authority_or_consent_remains_blocked(tmp_path: Path) -> None:
    pool_path = tmp_path / "pool.toml"
    answers_path = tmp_path / "answers.json"
    _pool(pool_path)
    first = _structured_response("BenevolentDirector", "a" * 40)
    first["authority"] = "not_authorised"
    second = _structured_response("corsweb", "b" * 40)
    second["identity_consent"] = "no"
    second["identity_subject"] = "DECLINED"
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": "tep-v060-blind-pilot-answers-v1",
                "responses": [first, second],
            }
        ),
        encoding="utf-8",
    )

    audit = pilot.questionnaire_audit(pilot.selected_candidates(pool_path), answers_path)
    assert audit["ready_count"] == 0
    assert audit["blocked_count"] == 2
    reasons = {row["repo_id"]: row["blocking_reasons"] for row in audit["repos"]}
    assert reasons["BenevolentDirector"] == ["repository_authority_not_granted"]
    assert reasons["corsweb"] == ["identity_consent_not_granted"]


def test_role_comparison_never_maps_ai_primary_method_to_git_trailers() -> None:
    answers = {
        "role.domain": ["core"],
        "role.work_type": ["create"],
        "role.time": ["early"],
        "role.process_position": ["creator"],
        "ai_primary_method": "yes",
        "ai_trailer_memory": "no",
    }
    metric = {"numerator": 1, "denominator": 20, "value": 0.05}
    card = {
        "role_profile": {
            "dimensions": {
                "domain": {"core": metric},
                "work_type": {"create": metric},
                "time": {"phase": {"early": metric}},
                "process_position": {"creator": metric},
            }
        },
        "experience": {"metrics": {"declared_ai_assist_share": metric}},
    }
    comparisons = pilot._role_comparisons(answers, card)
    assert {row["cell"] for row in comparisons} == {
        "role.domain.core",
        "role.work_type.create",
        "role.time.early",
        "role.process_position.creator",
        "ai_trailer_memory",
    }
    ai = next(row for row in comparisons if row["cell"] == "ai_trailer_memory")
    assert (ai["expected"], ai["observed"]) == (False, True)
    assert all("ai_primary_method" not in row["cell"] for row in comparisons)


def test_run_inputs_fail_closed_before_measurement_when_answers_are_blocked(
    tmp_path: Path,
) -> None:
    identity = tmp_path / "identity.toml"
    identity.write_text('schema_version = "identity-v2"\n', encoding="utf-8")
    inventory = {
        "schema_version": "tep-v060-blind-pilot-inventory-v1",
        "candidates": [],
    }
    audit = {
        "schema_version": "tep-v060-blind-pilot-answer-audit-v1",
        "ready_count": 0,
        "blocked_count": 1,
        "repos": [],
    }
    try:
        pilot._validate_run_inputs(
            inventory_payload=inventory,
            audit_payload=audit,
            identity_files={},
            developer_root=tmp_path,
        )
    except ValueError as exc:
        assert "blocked until every structured answer is ready" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("blocked answers must stop before any measurement")
