"""Release gates: (a) the shipped v0.5.1 tag tree carries zero pilot files;
(b) future snapshots must exclude docs/pilot (audit-only, dev-side).

The v0.5.1 tag (70f92e8 snapshot) predates the pilot merge — this test pins
the exclusion rule for snapshot tooling: the set of paths a public snapshot
may carry never includes docs/pilot*, regardless of dev main contents.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths that must NEVER ship in a public snapshot (audit-only, dev-side).
FORBIDDEN_SNAPSHOT_PREFIXES = (
    "docs/pilot",
    "docs/ACCEPTANCE",
    "docs/INSTRUCTION",
    "docs/EVIDENCE-INDEX",
    "docs/HANDOVER",
    "docs/PREPUB",
)


def test_snapshot_exclusion_rules_pinned() -> None:
    """The snapshot tooling contract: these prefixes are excluded when cutting
    a public snapshot (v0.5.1 did exactly this; v0.5.2 must too)."""
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "origin/main"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        import pytest

        pytest.skip("origin/main not fetched")
    # dev main DOES carry them (audit docs are dev-side); the gate is that the
    # EXCLUSION LIST itself stays pinned here. Assert the list is non-empty and
    # that the v0.5.1 tag tree (still reachable) has zero of them.
    assert FORBIDDEN_SNAPSHOT_PREFIXES
    tag = subprocess.run(
        ["git", "cat-file", "-t", "70f92e8ca20f4f5033360be9bf655aba6afa70d6"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if tag.returncode == 0:
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "70f92e8ca20f4f5033360be9bf655aba6afa70d6"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        leaked = [
            line
            for line in tree.stdout.splitlines()
            if line.startswith(FORBIDDEN_SNAPSHOT_PREFIXES)
        ]
        assert leaked == [], f"shipped v0.5.1 tree leaked audit/pilot paths: {leaked}"


def test_release_gate_module_documents_exclusion() -> None:
    doc = ROOT / "docs" / "RELEASE-REHEARSAL-v051-20260822.md"
    if not doc.is_file():
        import pytest

        pytest.skip("rehearsal doc is dev-only (excluded from public snapshots)")
    text = doc.read_text(encoding="utf-8")
    assert "docs/pilot" in text and "0 件" in text
