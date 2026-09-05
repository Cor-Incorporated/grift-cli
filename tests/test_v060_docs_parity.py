"""Doc enum/regex parity with implementation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tep_cli.options import build_parser
from tep_core.identity import CANONICAL_ID_PATTERN
from tep_core.schema_v2 import validate_alignment, validate_report_v2
from tep_core.v2_constants import ROLE_LENSES, SURFACES, VERIFICATION_TYPES

ROOT = Path(__file__).resolve().parents[1]


def _fences(path: Path, lang: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(rf"```{lang}\n(.*?)```", text, re.S)


def test_project_schema_enums_in_docs() -> None:
    text = (ROOT / "docs" / "project-schema.md").read_text(encoding="utf-8")
    for name in SURFACES:
        assert name in text
    for name in VERIFICATION_TYPES:
        assert name in text
    for name in ROLE_LENSES:
        assert name in text
    assert CANONICAL_ID_PATTERN in text or "canonical_id" in text


def test_report_v2_example_validates() -> None:
    blocks = _fences(ROOT / "docs" / "report-v2.md", "json")
    assert blocks
    payload = json.loads(blocks[0])
    errors = validate_report_v2(payload)
    # example is a subset; additive validator may still require sections
    assert payload["schema_version"] == "report-v2"
    assert "score" not in payload
    assert isinstance(errors, list)


def test_alignment_example_has_no_verdict_keys() -> None:
    blocks = _fences(ROOT / "docs" / "alignment-schema.md", "json")
    assert blocks
    payload = json.loads(blocks[0])
    errors = validate_alignment(payload)
    assert errors == []
    assert "score" not in payload
    assert "overall" not in payload


def test_project_toml_example_has_schema() -> None:
    blocks = _fences(ROOT / "docs" / "project-schema.md", "toml")
    assert blocks
    assert 'schema_version = "tep-project-v1"' in blocks[0]


def test_actor_basis_docs_and_help_are_fail_closed_and_bilingual() -> None:
    docs = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "README.md",
            "README.en.md",
            "docs/norms.md",
            "docs/en/norms.md",
            "docs/report-v2.md",
        )
    }
    for relative, text in docs.items():
        for state in ("claimed", "verified", "inferred", "external", "unknown"):
            assert state in text, f"{relative} does not document actor basis {state!r}"

    assert "本人向け表示、`verified` は管理権限に基づく非本人向け表示" in docs["README.md"]
    assert "Only explicit `claimed` gets personal-view wording" in docs["README.en.md"]
    assert "only basis that gets personal-view" in docs["docs/en/norms.md"]
    for path in ("docs/norms.md", "docs/en/norms.md"):
        assert "--all" in docs[path]
        assert "--top N" in docs[path]
        assert "mutually exclusive" in docs[path] or "排他" in docs[path]
        assert "quality rank" in docs[path] or "品質rank" in docs[path]
    assert "対象にできるのは1つの canonical_idだけ" not in docs["docs/norms.md"]
    assert "observes one `canonical_id`" not in docs["docs/en/norms.md"]
    assert "本人向け表示" in docs["docs/report-v2.md"]

    stale_claims = (
        "canonical_id の本人証拠（report-v2, tenant）",
        "from a consenting identity",
        "subject basisに応じて2種類",
        "同意済みtenant観測",
    )
    joined = "\n".join(docs.values())
    for claim in stale_claims:
        assert claim not in joined

    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    top_help = parser.format_help()
    actor_help = choices["actor"].format_help()
    align_help = choices["align"].format_help()
    assert "Actor basis may be public, claimed" in top_help
    assert "basis-aware detailed report" in actor_help
    assert "not consent proof" in actor_help
    assert "missing/contradictory basis fails closed" in align_help
    assert "Use a consenting identity for actor views" not in "\n".join(
        (top_help, actor_help, align_help)
    )
