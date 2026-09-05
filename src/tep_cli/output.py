"""Shared stdout / --out writing. json stdout is one JSON object."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tep_core.v2_constants import ARTIFACT_NAMES

_FILE_SUFFIXES = {".md", ".json", ".toml"}


def encode_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _is_dir_target(path: Path) -> bool:
    if path.exists():
        return path.is_dir()
    return path.suffix.lower() not in _FILE_SUFFIXES


def write_stdout(*, markdown: str, encoded: str, fmt: str) -> None:
    if fmt in {"md", "both"}:
        sys.stdout.write(markdown)
        if fmt == "both":
            sys.stdout.write("\n")
    if fmt in {"json", "both"}:
        sys.stdout.write(encoded)


def write_out(
    *,
    markdown: str,
    encoded: str,
    fmt: str,
    out: Path,
    artifact: str,
) -> None:
    md_name, json_name = ARTIFACT_NAMES[artifact]
    if _is_dir_target(out):
        out.mkdir(parents=True, exist_ok=True)
        if fmt in {"md", "both"}:
            (out / md_name).write_text(markdown, encoding="utf-8")
        if fmt in {"json", "both"}:
            (out / json_name).write_text(encoded, encoding="utf-8")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        out.write_text(markdown, encoding="utf-8")
        return
    if fmt == "json":
        out.write_text(encoded, encoding="utf-8")
        return
    suffix = out.suffix.lower()
    md_path = out if suffix == ".md" else out.with_suffix(".md")
    json_path = out if suffix == ".json" else out.with_suffix(".json")
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(encoded, encoding="utf-8")


def emit(
    *,
    markdown: str,
    payload: dict[str, Any],
    fmt: str,
    out: Path | None,
    artifact: str,
) -> None:
    encoded = encode_json(payload)
    if out is not None:
        write_out(markdown=markdown, encoded=encoded, fmt=fmt, out=out, artifact=artifact)
    write_stdout(markdown=markdown, encoded=encoded, fmt=fmt)
