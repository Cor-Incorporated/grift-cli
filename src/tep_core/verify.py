"""`grift verify <report.json>` — recompute under the recorded provenance and
diff every field (P1g). Exit codes: 0 VERIFIED / 1 MISMATCH / 2 CANNOT_VERIFY.

Falsifiable tamper detection: one modified field must surface as a MISMATCH
line, never as a crash. Definition-version drift is reported honestly as
CANNOT_VERIFY (historical reproduction is a future feature).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tep_core.analyze import analyze_repository
from tep_core.gitutil import GitError, rev_parse
from tep_core.identity import IdentityConfig, discover_identity, load_identity
from tep_core.lineage import Lineage

VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
CANNOT_VERIFY = "CANNOT_VERIFY"

# Fields that legitimately differ between runs and are excluded from diff.
VOLATILE_PATHS = {"provenance.analyzed_at"}


@dataclass
class VerifyResult:
    status: str
    differences: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(value, path))
    else:
        flat[prefix] = node
    return flat


def verify_report(
    report_path: Path,
    repo: Path | None,
    identity_path: Path | None = None,
) -> VerifyResult:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifyResult(CANNOT_VERIFY, notes=[f"report unreadable: {exc}"])

    provenance = report.get("provenance") or {}
    sha = provenance.get("analyzed_commit_sha")
    definition_version = provenance.get("definition_version")
    scope = provenance.get("analysis_scope") or "tenant"

    if not sha or not isinstance(sha, str) or len(sha) != 40:
        return VerifyResult(CANNOT_VERIFY, notes=["provenance.analyzed_commit_sha missing/invalid"])
    if not definition_version:
        return VerifyResult(CANNOT_VERIFY, notes=["provenance.definition_version missing"])

    from tep_core.version import DEFINITION_VERSION

    if definition_version != DEFINITION_VERSION:
        return VerifyResult(
            CANNOT_VERIFY,
            notes=[
                f"definition version {definition_version!r} is not the current "
                f"{DEFINITION_VERSION!r} — historical versions cannot be "
                "reproduced yet (compatibility table: docs/report-schema.md)"
            ],
        )

    if repo is None:
        return VerifyResult(CANNOT_VERIFY, notes=["target repository not provided"])
    if not (repo / ".git").exists():
        return VerifyResult(CANNOT_VERIFY, notes=[f"not a git repository: {repo}"])

    try:
        head = rev_parse(repo, "HEAD")
    except GitError as exc:
        return VerifyResult(CANNOT_VERIFY, notes=[f"git unavailable: {exc}"])
    if head != sha:
        # Try to check out the recorded SHA for exact recomputation.
        import subprocess

        checkout = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(repo), "checkout", "--force", sha],
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            return VerifyResult(
                CANNOT_VERIFY,
                notes=[f"recorded SHA {sha[:8]} not reachable in {repo}"],
            )

    lineage = Lineage(
        is_fork=bool(report.get("lineage", {}).get("is_fork")),
        parent=report.get("lineage", {}).get("parent"),
    )
    identity: IdentityConfig
    if identity_path is not None:
        try:
            identity = load_identity(identity_path)
        except Exception as exc:  # noqa: BLE001
            return VerifyResult(CANNOT_VERIFY, notes=[f"identity load failed: {exc}"])
    else:
        identity = discover_identity(repo, None)

    try:
        recomputed = analyze_repository(repo, identity, lineage, scope=scope)
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(CANNOT_VERIFY, notes=[f"recomputation failed: {exc}"])

    left = _flatten(report)
    right = _flatten(recomputed)
    differences: list[str] = []
    for key in sorted(set(left) | set(right)):
        if any(key == volatile or key.startswith(volatile + ".") for volatile in VOLATILE_PATHS):
            continue
        # analyzed_commit_sha may differ if we checked out the recorded SHA
        # (then equal) — keep it in the diff; it must match.
        if left.get(key) != right.get(key):
            differences.append(f"{key}: report={left.get(key)!r} recomputed={right.get(key)!r}")
    if differences:
        return VerifyResult(MISMATCH, differences=differences)
    return VerifyResult(VERIFIED)
