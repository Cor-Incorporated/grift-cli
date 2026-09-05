#!/usr/bin/env python3
"""Write golden/coverage.md from the current expected files (matrix source of truth).

Run after adding pins / expected files:  python3 scripts/gen_coverage_table.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from coverage_matrix import (  # noqa: E402
    FIELD_ROWS,
    STATUS_HOLE,
    compute_matrix,
    pin_ids,
    row_status,
)

HEADER = """# Golden coverage matrix — 観測フィールド x golden repo（v2 wave 1）

自動生成: `scripts/gen_coverage_table.py`（`tests/coverage_matrix.py` が計算ロジックの単一実装）。
**手書き編集禁止** — テスト `tests/test_coverage.py` がこの表と expected ファイルの突合を行う。

記号: `o` = observed（励起。0 も合法な観測値）/ `x` = not_observed / `-` = 期待値に未ピン。
要件: `excited` = o>=1 / `both` = o>=1 かつ x>=1（public golden対象の新観測）/
`synthetic` = actor exactnessをpublic goldenではなくexact synthetic testsで固定。
HOLE 行は機械検出された穴。**穴は静かに放置しない** — 表の HOLE と issue 番号の対応を
tests/test_coverage.py の KNOWN_HOLES が強制する。

**v0.6 supersession（2026-08-31）**: 公開OSS goldenはreport-v1回帰とrepo-level
detectorを固定する。wave 2のcontext v2はこのpublic-golden laneに残る。第三者public
actorまたはidentityなしrepoのexperience / role_profileは
`not_observed(consenting_actor_required)`であり、公開OSSにidentityを推測して励起しない。
wave 3のactor行は`synthetic`、`-`は意図した非適用である。決定論・境界・fail-closedは
exact synthetic tests、実在repoでの現実妥当性はblind pilotで検証する。既存expectedを
再生成してこの境界を迂回せず、synthetic greenをblind pilotの代替にしない。
"""


def main() -> int:
    ids = pin_ids()
    matrix = compute_matrix()
    with (ROOT / "golden" / "pins.toml").open("rb") as handle:
        pins = {p["id"]: p for p in tomllib.load(handle)["repos"]}
    lines: list[str] = [
        HEADER,
        "",
        "| field | wave | req | " + " | ".join(ids) + " | status | note |",
        "|---|---|---|" + "---|" * len(ids) + "---|---|",
    ]
    holes: list[str] = []
    for row in FIELD_ROWS:
        cells = matrix[row.path]
        status = row_status(row, cells)
        if status == STATUS_HOLE:
            holes.append(row.path)
        lines.append(
            f"| {row.label} | {row.wave} | {row.requirement} | "
            + " | ".join(cells[i] for i in ids)
            + f" | {status} | {row.note} |"
        )
    lines += ["", f"pins: {len(ids)} / 上限 13（master §3-1）", ""]
    if holes:
        lines.append("## 機検出された HOLE（issue トラック必須）")
        lines += [f"- {h}" for h in holes]
        lines.append("")
    lines.append("## 実行時間証跡（受入⑥・週次 CI 予算）")
    lines.append("")
    lines.append(
        "- 2026-08-22 wave 1: 13 repos, warm cache: 14.6s wall (`TEP_GOLDEN=1 pytest -m golden`; clone 済み .golden-cache)。コールド clone 込みは pins 追加時の `gen_golden_expected.py` 実行で別計上"
    )
    lines.append("")
    tags_rows = [
        "| pin | collaboration | lifecycle | era | ecosystem | questions | reason(抜粋) |",
        "|---|---|---|---|---|---|---|",
    ]
    for pin_id in ids:
        pin = pins[pin_id]
        tags = pin.get("tags", {})
        reason = (pin.get("reason", {}) or {}).get("text", "")
        tags_rows.append(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                pin_id,
                tags.get("collaboration", "-"),
                tags.get("lifecycle", "-"),
                tags.get("era", "-"),
                tags.get("ecosystem", "-"),
                tags.get("persona_questions", "-"),
                reason[:80],
            )
        )
    lines += tags_rows
    (ROOT / "golden" / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote golden/coverage.md ({len(ids)} pins, {len(FIELD_ROWS)} rows, {len(holes)} holes: {holes})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
