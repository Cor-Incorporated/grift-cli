"""Text helpers shared by the report-v2, project-v1 and alignment-v1 Markdown."""

from __future__ import annotations

from typing import Any

from tep_core.v2_constants import HISTORY_WINDOW_BASIS, HISTORY_WINDOW_PREFIX


def _history_end_text(end: Any) -> str:
    # Not 「全履歴」: a shallow clone holds only the fetched slice (follow-up of #85).
    # The detail layer keeps one wording for every report; a project-v1 saved before
    # 0.9.1 does not record whether the clone was shallow. The opening section says
    # 全履歴 when the report proves it is not (tep_core.trait_evidence.history_text).
    return f"{end} までの履歴" if end else "—"


def _window_text(node: Any) -> str:
    if isinstance(node, str) and node.startswith(HISTORY_WINDOW_PREFIX):
        return _history_end_text(node[len(HISTORY_WINDOW_PREFIX) :])
    if not isinstance(node, dict):
        return str(node or "—")
    if node.get("kind") in {"not_observed", "not_proven"}:
        return _obs(node)
    if node.get("basis") == HISTORY_WINDOW_BASIS:
        return _history_end_text(node.get("end"))
    start = node.get("start")
    end = node.get("end")
    if start and end:
        return f"{start}〜{end}"
    return "—"


def _display_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return "複合値"
    return str(value)


# Unit names that only say what kind of value was declared. 0.8.0 glued them to
# the value ("payments-api id", "backend, data surface-names"), trait-profile
# design §1.4 row 6. JSON keeps them; Markdown shows the value alone.
_DECLARED_KIND_UNITS = frozenset(
    {
        "id",
        "surface",
        "surface-names",
        "surface_list",
        "verification-type",
        "verification-types",
        "input",
        "input-kinds",
        "lens",
    }
)


def _title_text(node: Any) -> str:
    """A title is a label, not a requirement: no not_declared boilerplate."""
    if isinstance(node, dict) and node.get("kind") == "declared" and node.get("value"):
        return _display_value(node.get("value"))
    return "案件側が書いていません"


def _obs(node: Any) -> str:
    if not isinstance(node, dict):
        return "未観測"
    kind = node.get("kind")
    if kind == "not_observed":
        reason = node.get("reason", "unspecified")
        return f"未観測（not_observed。測定できなかった。実績がないことではない）理由: {reason}"
    if kind == "not_proven":
        reason = node.get("reason", "unspecified")
        return f"未証明（not_proven。確認できない。0件ではない）理由: {reason}"
    if kind == "not_declared":
        reason = node.get("reason", "requirement_not_provided")
        return f"未宣言（not_declared。案件側が書いていない。不足ではない）理由: {reason}"
    unit = node.get("unit") or ""
    if kind == "declared":
        shown_unit = "" if unit in _DECLARED_KIND_UNITS else unit
        return f"{_display_value(node.get('value'))} {shown_unit}".strip()
    sample = node.get("sample_size")
    value = node.get("value")
    if value is None:
        return f"観測あり（単位 {unit or 'profile'}、n={sample if sample is not None else '—'}）"
    extra = f"（母数 n={sample}）" if sample is not None else ""
    return f"{_display_value(value)} {unit}{extra}".strip()


def _unique(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for note in notes:
        if note and note not in seen:
            seen.add(note)
            ordered.append(note)
    return ordered
