"""0.9.6 docs: the verify guarantees page exists, is linked, and says what it must (#23)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JA = ROOT / "docs" / "verify-guarantees.md"
EN = ROOT / "docs" / "en" / "verify-guarantees.md"


def test_readmes_link_the_guarantee_page() -> None:
    assert "docs/verify-guarantees.md" in (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "blob/main/docs/en/verify-guarantees.md" in english


@pytest.mark.parametrize(
    ("path", "fragments"),
    [
        (JA, ("report と repo の一貫性", "本物かどうか", "攻撃木", "署名ヘッダ", "手間を増やす")),
        (
            EN,
            (
                "consistency between the report and the repository",
                "genuine",
                "attack tree",
                "signature header",
                "raises",
            ),
        ),
    ],
)
def test_guarantee_page_states_the_scope(path: Path, fragments: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    assert not missing, missing


def test_guarantee_page_does_not_promise_tamper_proofing() -> None:
    ja = JA.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "改ざんできない」とは書きません" in ja
    assert "cannot be tampered with" in en and "never says" in en
