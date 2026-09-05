"""Content digests for provenance. Never store absolute paths."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
