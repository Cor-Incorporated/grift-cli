"""0.9.6: signature-presence observation, usage terms and disclosure level (#23, #27)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from v096_fixture import AS_OF, signed_pattern_repo

from tep_cli.__main__ import main
from tep_core.schema_v2 import validate_report_v2
from tep_core.usage_terms import (
    DISCLOSURE_LEVELS,
    LEVEL_SECTIONS,
    DisclosureLevelError,
    shown_sections,
    usage_terms_payload,
    validate_disclosure_level,
)
from tep_core.v2_constants import FORBIDDEN_VERDICT_KEYS

SCHEMA = Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json"


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue() + err.getvalue()


def _json(argv: list[str]) -> dict[str, Any]:
    code, text = _run([*argv, "--as-of", AS_OF, "--format", "json"])
    assert code == 0, text
    return json.loads(text)


def _markdown(argv: list[str]) -> str:
    code, text = _run([*argv, "--as-of", AS_OF, "--format", "md"])
    assert code == 0, text
    return text


def _keys(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


@pytest.fixture(scope="module")
def signed_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, int]:
    return signed_pattern_repo(tmp_path_factory.mktemp("signed") / "repo")


# --- signature observation (#23) -------------------------------------------


def test_signature_observation_counts_header_presence(signed_repo: tuple[Path, int]) -> None:
    repo, signed = signed_repo
    report = _json(["repo", str(repo)])
    observation = report["signature_observation"]
    assert observation["kind"] == "observed"
    assert observation["count"] == signed
    assert observation["sample_size"] == 24
    assert observation["value"] == round(signed / 24, 4)
    assert observation["unit"] == "ratio"
    assert any("validity is not checked" in note for note in observation["limitations"])


@pytest.mark.parametrize("level", DISCLOSURE_LEVELS)
def test_report_passes_both_schema_checks(signed_repo: tuple[Path, int], level: str) -> None:
    repo, _ = signed_repo
    report = _json(["repo", str(repo), "--disclosure-level", level])
    assert validate_report_v2(report) == []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    wrapper = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/report-v2"}
    jsonschema.Draft202012Validator(wrapper).validate(report)


def test_schema_rejects_a_forged_extra_key_in_usage_terms(
    signed_repo: tuple[Path, int],
) -> None:
    repo, _ = signed_repo
    report = _json(["repo", str(repo)])
    report["usage_terms"]["score"] = 1
    assert validate_report_v2(report) != []


def test_signature_observation_adds_no_verdict_key(signed_repo: tuple[Path, int]) -> None:
    repo, _ = signed_repo
    report = _json(["repo", str(repo)])
    assert not (_keys(report["signature_observation"]) & set(FORBIDDEN_VERDICT_KEYS))
    assert not (_keys(report["usage_terms"]) & set(FORBIDDEN_VERDICT_KEYS))


def test_unsigned_history_observes_zero_not_a_verdict(tmp_path: Path) -> None:
    repo, _ = signed_pattern_repo(tmp_path / "plain", signed_every=None)
    report = _json(["repo", str(repo)])
    observation = report["signature_observation"]
    assert observation["kind"] == "observed"
    assert observation["count"] == 0
    assert observation["value"] == 0.0
    assert not (_keys(observation) & set(FORBIDDEN_VERDICT_KEYS))


def test_small_history_is_not_observed(tmp_path: Path) -> None:
    repo, _ = signed_pattern_repo(tmp_path / "tiny", total=5)
    observation = _json(["repo", str(repo)])["signature_observation"]
    assert observation["kind"] == "not_observed"
    assert observation["reason"] == "insufficient_population"
    assert observation["population"] == 5


def test_verify_replays_the_signature_observation(
    signed_repo: tuple[Path, int], tmp_path: Path
) -> None:
    repo, _ = signed_repo
    report = tmp_path / "report.json"
    code, text = _run(["repo", str(repo), "--as-of", AS_OF, "--format", "json"])
    assert code == 0
    report.write_text(text, encoding="utf-8")
    code, verdict = _run(["verify", str(report), "--repo", str(repo)])
    assert code == 0, verdict
    assert verdict.startswith("VERIFIED"), verdict


def test_verify_rejects_an_edited_signature_count(
    signed_repo: tuple[Path, int], tmp_path: Path
) -> None:
    repo, _ = signed_repo
    _, text = _run(["repo", str(repo), "--as-of", AS_OF, "--format", "json"])
    edited = json.loads(text)
    edited["signature_observation"]["count"] = 24
    edited["signature_observation"]["value"] = 1.0
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(edited), encoding="utf-8")
    code, verdict = _run(["verify", str(path), "--repo", str(repo)])
    assert code != 0
    assert not verdict.startswith("VERIFIED"), verdict


# --- usage terms and disclosure level (#27) --------------------------------


def test_default_level_keeps_the_whole_detail_layer(signed_repo: tuple[Path, int]) -> None:
    repo, _ = signed_repo
    terms = _json(["repo", str(repo)])["usage_terms"]
    assert terms["disclosure_level"] == "full"
    assert terms["withheld_from_markdown"] == []
    assert terms["binding"] == "declaration_only"
    assert terms["json_retains_all_observations"] is True
    assert terms["norms_ref"] == "docs/norms.md"
    ids = {item["id"] for item in terms["prohibited_uses"]}
    assert "weighting_or_conversion" in ids
    assert all(isinstance(item["norms_article"], int) for item in terms["prohibited_uses"])


@pytest.mark.parametrize("level", DISCLOSURE_LEVELS)
def test_level_is_recorded_in_json_and_provenance(
    signed_repo: tuple[Path, int], level: str
) -> None:
    repo, _ = signed_repo
    report = _json(["repo", str(repo), "--disclosure-level", level])
    assert report["usage_terms"]["disclosure_level"] == level
    assert report["provenance"]["disclosure_level"] == level
    assert report["usage_terms"]["markdown_sections"] == list(LEVEL_SECTIONS[level])


def test_the_json_keeps_every_observation_at_every_level(
    signed_repo: tuple[Path, int],
) -> None:
    repo, _ = signed_repo
    full = _json(["repo", str(repo)])
    minimal = _json(["repo", str(repo), "--disclosure-level", "minimal"])
    for key in ("change_rhythm", "coordination_profile", "surface_profile"):
        assert minimal[key] == full[key], key


def test_minimal_markdown_withholds_the_rhythm_sections(signed_repo: tuple[Path, int]) -> None:
    repo, _ = signed_repo
    full = _markdown(["repo", str(repo)])
    minimal = _markdown(["repo", str(repo), "--disclosure-level", "minimal"])
    assert "変更リズム" in full or "リズム" in full
    assert "リズム" not in minimal.split("## 共有するときの条件")[0]
    assert "## 共有するときの条件" in minimal
    assert "minimal" in minimal


def test_markdown_states_the_terms_are_a_declaration(signed_repo: tuple[Path, int]) -> None:
    repo, _ = signed_repo
    text = _markdown(["repo", str(repo)])
    assert "## 共有するときの条件" in text
    assert "技術では止められません" in text


def test_unknown_level_is_rejected_before_any_report(signed_repo: tuple[Path, int]) -> None:
    repo, _ = signed_repo
    with pytest.raises(SystemExit) as raised:
        _run(["repo", str(repo), "--disclosure-level", "everything"])
    assert raised.value.code == 2


def test_validate_disclosure_level() -> None:
    assert validate_disclosure_level(None) == "full"
    for level in DISCLOSURE_LEVELS:
        assert validate_disclosure_level(level) == level
    with pytest.raises(DisclosureLevelError):
        validate_disclosure_level("partial")


def test_levels_nest() -> None:
    assert set(shown_sections("minimal")) < set(shown_sections("standard"))
    assert set(shown_sections("standard")) < set(shown_sections("full"))


def test_usage_terms_payload_names_no_score_or_rank() -> None:
    payload = usage_terms_payload("standard")
    assert not (_keys(payload) & set(FORBIDDEN_VERDICT_KEYS))
    assert payload["withheld_from_markdown"] == [
        "change_rhythm",
        "event_rhythm",
        "tracker_lifecycle",
    ]


def test_verify_replays_the_level(signed_repo: tuple[Path, int], tmp_path: Path) -> None:
    repo, _ = signed_repo
    _, text = _run(
        ["repo", str(repo), "--as-of", AS_OF, "--format", "json", "--disclosure-level", "minimal"]
    )
    path = tmp_path / "minimal.json"
    path.write_text(text, encoding="utf-8")
    code, verdict = _run(["verify", str(path), "--repo", str(repo)])
    assert code == 0, verdict
    edited = json.loads(text)
    edited["usage_terms"]["disclosure_level"] = "full"
    edited["provenance"]["disclosure_level"] = "full"
    path.write_text(json.dumps(edited), encoding="utf-8")
    code, verdict = _run(["verify", str(path), "--repo", str(repo)])
    assert code != 0, verdict
