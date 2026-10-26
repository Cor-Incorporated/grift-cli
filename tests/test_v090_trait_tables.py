"""v0.9.0 (b): the decision tables are declared twice, in docs and in code.

ADR-0002 T6 publishes the tables that pick every trait sentence and interview
question. docs/trait-profile.md and docs/en/trait-profile.md carry them for
readers; src/tep_core/trait_tables.py carries them for the renderer. These
tests read both documents and compare every row with the constants, both ways,
and name both values when one side moves (trait-profile design §6.3, 宣言 ↔ 実機).

The vocabulary gates of norms §2 and §7 read every template here too: no
ranking or comparison words, no good/bad words, no type names (T2, T4, T7).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tep_core import trait_tables

ROOT = Path(__file__).resolve().parents[1]
DOCS = (ROOT / "docs" / "trait-profile.md", ROOT / "docs" / "en" / "trait-profile.md")
TABLES = (
    "THRESHOLDS",
    "PLACE_NAMES",
    "TEST_TYPE_NAMES",
    "TEST_TYPE_SHORT_NAMES",
    "INPUT_NAMES",
    "RHYTHM_ITEM_NAMES",
    "SENTENCES",
    "QUESTIONS",
    "ALIGNMENT_TEXTS",
    "PLAIN_REASONS",
    "NOT_SHOWN",
    "LIMIT_NOTES",
    "HEADINGS",
    "SECTION_TEXTS",
    "EVIDENCE_ROWS",
    "DECLARED_TEXTS",
    "DECLARED_ITEM_NAMES",
    "VERDICT_NAMES",
)
SINGLE_TEXTS = ("NOT_SHOWN_TEMPLATE", "NOT_SHOWN_SHALLOW_TEMPLATE", "PLAIN_REASON_FALLBACK")
_ROW = re.compile(r"^\|\s*`(?P<id>[A-Za-z0-9_]+)`\s*\|(?:.*\|)?\s*(?P<last>[^|]*?)\s*\|\s*$")


def _tables(path: Path) -> dict[str, dict[str, str]]:
    """Rows under each heading that names a constant in backticks."""

    found: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            names = [name for name in re.findall(r"`([A-Z_]+)`", line) if name in TABLES]
            current = names[0] if names else (None if line.startswith("## ") else current)
            if current is not None:
                found.setdefault(current, {})
            continue
        match = _ROW.match(line)
        if current is not None and match:
            found[current][match.group("id")] = match.group("last")
    return found


def _declared(name: str) -> dict[str, str]:
    value = getattr(trait_tables, name)
    return {
        key: (f"{item:g}" if isinstance(item, float) else str(item)) for key, item in value.items()
    }


@pytest.mark.parametrize("path", DOCS, ids=lambda path: path.relative_to(ROOT).as_posix())
@pytest.mark.parametrize("name", TABLES)
def test_docs_table_and_constants_are_the_same_rows(path: Path, name: str) -> None:
    documented = _tables(path).get(name)
    assert documented is not None, (path.name, name, "table missing from the document")
    declared = _declared(name)
    diffs = [
        (key, documented.get(key), declared.get(key))
        for key in sorted(set(documented) | set(declared))
        if documented.get(key) != declared.get(key)
    ]
    assert not diffs, (path.relative_to(ROOT).as_posix(), name, "(id, docs, code)", diffs)


def test_single_sentences_are_documented_in_both_languages() -> None:
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for name in SINGLE_TEXTS:
            assert getattr(trait_tables, name) in text, (path.relative_to(ROOT).as_posix(), name)


# The modules whose not_observed reasons reach the trait sections and the
# alignment questions. A new reason there without a plain row fails here.
REASON_SOURCES = (
    "surface_profile",
    "rhythm",
    "verification_profile",
    "cochange",
    "role_profile",
    "analyze",
    "analyze_v2",
    "alignment",
    "local_inputs",
    "project",
    "coordination",
    "tendency",
    "experience",
)
_REASON = re.compile(
    r'(?:NotObserved|_not_proven)\(\s*"([a-z_]+)"|"reason": "([a-z_]+)"'
    r'|reason = "([a-z_]+)"|_reason = "([a-z_]+)"|reason: str = "([a-z_]+)"'
)


def test_every_reason_the_producers_emit_has_a_plain_sentence() -> None:
    found: dict[str, str] = {}
    for module in REASON_SOURCES:
        text = (ROOT / "src" / "tep_core" / f"{module}.py").read_text(encoding="utf-8")
        for match in _REASON.finditer(text):
            reason = next(group for group in match.groups() if group)
            found.setdefault(reason, module)
    found.update({"history_incomplete": "analyze", "experience_collection_timeout": "analyze"})
    missing = sorted(
        (reason, module)
        for reason, module in found.items()
        if reason not in trait_tables.PLAIN_REASONS
    )
    assert not missing, ("(reason, module) without a PLAIN_REASONS row", missing)


def test_unknown_reasons_never_print_as_a_bare_internal_name() -> None:
    from tep_core.trait_profile import plain_reason

    text = plain_reason("brand_new_reason")
    assert text == trait_tables.PLAIN_REASON_FALLBACK.format(reason="brand_new_reason")
    assert text != "brand_new_reason"


def _templates() -> list[tuple[str, str]]:
    texts = [(name, getattr(trait_tables, name)) for name in SINGLE_TEXTS]
    for name in TABLES[1:]:
        texts += [(f"{name}.{key}", value) for key, value in getattr(trait_tables, name).items()]
    return texts


# Words that place a person against others or a distribution (T2, ADR-0001 R3).
COMPARISON_WORDS = (
    "上位",
    "下位",
    "平均",
    "ほかの人より",
    "他の人より",
    "順位",
    "十分位",
    "パーセンタイル",
    "偏差",
    "参照分布",
)
# Words that fold the axes into a type (T4).
TYPE_WORDS = ("タイプ", "型の", "系エンジニア", "人物像", "まとめると", "総合")
# These sentences name a comparison or a rank in order to deny it. Only the
# exact sentence is allowed: a new template that uses the word fails.
_DENIALS = ("ほかの人やほかのリポジトリとは比べていません", "点数・順位・合否は出しません")


def test_templates_carry_no_comparison_ranking_or_type_words() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_forbidden_vocab import violations
    from test_gloss_gates import NORMATIVE
    from test_v070_complementarity import _ORDER_WORDS

    offenders = []
    for name, text in _templates():
        plain = text
        for denial in _DENIALS:
            plain = plain.replace(denial, "")
        offenders += [(name, hit) for hit in violations(text)]
        offenders += [(name, word) for word in NORMATIVE if word in text]
        offenders += [(name, word) for word in COMPARISON_WORDS + TYPE_WORDS if word in plain]
        tokens = set(re.findall(r"[a-z_]+", text.lower()))
        offenders += [(name, word) for word in tokens & _ORDER_WORDS]
    assert not offenders, offenders


def test_every_place_and_test_type_has_a_plain_name() -> None:
    from tep_core.v2_constants import SURFACES, VERIFICATION_TYPES

    assert tuple(trait_tables.PLACE_NAMES) == SURFACES
    assert tuple(trait_tables.TEST_TYPE_NAMES) == VERIFICATION_TYPES
    assert tuple(trait_tables.TEST_TYPE_SHORT_NAMES) == VERIFICATION_TYPES
    assert trait_tables.THRESHOLDS["min_population"] == 20
