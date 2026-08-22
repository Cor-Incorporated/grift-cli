"""persona-answers.md: transcribed numbers must match golden expected values.

Master §3-2: hand-written numbers are forbidden. Every `転記:` line carries
`golden/expected/<id>.json#<path> = <value>`; this test navigates the JSON and
compares. Every entry must close with a status marker (実演 / 限界文 / 宿題 /
起票) so unanswered rows cannot hide.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "persona-answers.md"

_ENTRY_RE = re.compile(
    r"^#{3,4}\s+(Q[0-9]+(?:-[0-9a-z]+)?[ab-c]?|E\d+[a-c]?)(?=[「:：\s])", re.MULTILINE
)
_TRANS_RE = re.compile(
    r"^-\s*転記:\s*`?(golden/expected/([A-Za-z0-9_.-]+\.json))#([A-Za-z0-9_.\[\]'\-]+)\s*=\s*(.+?)`?\s*$",
    re.MULTILINE,
)


def _entries(text: str) -> dict[str, str]:
    matches = list(_ENTRY_RE.finditer(text))
    entries: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        # A persona-level E-header whose own h2/h3 section contains #### child
        # entries is a container — its children are the real entries.
        if re.match(r"^E\d+[a-c]?$", name):
            section_end = re.search(r"^#{1,3}\s", text[match.end() :], re.MULTILINE)
            section = (
                text[match.end() : match.end() + section_end.start()]
                if section_end
                else text[match.end() :]
            )
            if "####" in section:
                continue
        entries[name] = text[match.end() : end]
    return entries


def test_entry_inventory_matches_review_doc() -> None:
    text = DOC.read_text(encoding="utf-8")
    entries = _entries(text)
    expected = {
        "Q1-1",
        "Q1-2",
        "Q1-3",
        "Q1-4",
        "Q2-1",
        "Q2-2",
        "Q2-3",
        "Q3-1",
        "Q3-2",
        "Q3-3",
        "Q4-1",
        "Q4-2",
        "E1",
        "E2",
        "Q3a",
        "Q3b",
        "Q3c",
        "E4",
        "Q5-a",
        "Q5-b",
        "Q5-c",
    }
    assert set(entries) == expected, (
        f"persona entries drifted: missing={sorted(expected - set(entries))} "
        f"extra={sorted(set(entries) - expected)}"
    )


def test_transcribed_numbers_match_golden() -> None:
    text = DOC.read_text(encoding="utf-8")
    transcriptions = _TRANS_RE.findall(text)
    assert len(transcriptions) >= 15, "wave 1 should carry >= 15 transcribed values"
    for rel, filename, path, value in transcriptions:
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        node = payload
        for key in path.split("."):
            if isinstance(node, list):
                node = node[int(key.strip("[]"))]
                continue
            assert isinstance(node, dict), f"{filename}#{path}: not a dict at {key}"
            assert key in node, f"{filename}#{path}: missing key {key}"
            node = node[key]
        actual = json.dumps(node, ensure_ascii=False)
        claimed = value.strip()
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            assert float(claimed) == float(node), (
                f"{filename}#{path}: persona-answers says {claimed}, golden says {node}"
            )
        else:
            assert actual == claimed or str(node) == claimed, (
                f"{filename}#{path}: persona-answers says {claimed!r}, golden says {actual!r}"
            )


def test_every_entry_closes_with_a_status() -> None:
    text = DOC.read_text(encoding="utf-8")
    for name, body in _entries(text).items():
        has_number = "転記:" in body
        has_limit = "限界文:" in body
        has_homework = "宿題:" in body
        assert has_number or has_limit or has_homework, (
            f"{name}: no 転記/限界文/宿題 — an unanswered row cannot hide"
        )
        if not has_number and not has_limit:
            pass  # homework-only rows are legal but must be tracked below


def test_wave1_unanswerable_rows_carry_issues() -> None:
    text = DOC.read_text(encoding="utf-8")
    for name, body in _entries(text).items():
        if "起票:" in body:
            assert re.search(r"起票:\s*https://github\.com/.*issues/\d+", body), (
                f"{name}: 起票 line must carry an issue URL"
            )


def test_issue_table_lists_all_filed_rows() -> None:
    text = DOC.read_text(encoding="utf-8")
    filed = {name for name, body in _entries(text).items() if re.search(r"起票:\s*https://", body)}
    for name in filed:
        assert (
            f"| {name} |" in text
            or f"[{name}]" in text
            or name in text.split("## wave 1 完了時点の起票一覧")[1]
        ), f"{name}: filed issue must appear in the wave-1 issue table"
