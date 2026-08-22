"""export-v1: machine-ingestible per-commit / per-actor export (opt-in).

Contract: docs/export-schema.md (frozen additive-only, same policy as
report-v1). The report stays authoritative for customer-facing narrative;
this layer exists for WP-G1 ingestion parity. Raw emails and raw author
strings never leave this module — canonical_id and null only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tep_core.analyze import prepare_inputs
from tep_core.core_period import compute_core_activity_period
from tep_core.gitutil import rev_parse
from tep_core.identity import IdentityConfig
from tep_core.lineage import Lineage
from tep_core.paths import split_paths
from tep_core.rework import is_corrective_subject
from tep_core.scope import DEFAULT_SCOPE
from tep_core.version import (
    ACTIVITY_DEFINITION_VERSION,
    DEFINITION_VERSION,
    ORIGIN_DEFINITION_VERSION,
    __version__,
)

EXPORT_SCHEMA_VERSION = "tep-export-v1"


def subject_class(subject: str) -> str:
    lowered = subject.lower()
    if lowered.startswith("revert") or "this reverts commit" in lowered:
        return "revert"
    if is_corrective_subject(subject):
        return "fix"
    return "other"


def config_digest(
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    template_provided: bool,
    parent_repo_provided: bool,
    vendor_scan: bool,
    scope: str,
) -> str:
    """sha256 over the canonical JSON of the export configuration.

    Normalization (Grift must replicate exactly to verify):
    json.dumps(payload, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False).encode("utf-8") -> sha256 hexdigest.
    Raw emails participate in the digest but are never written to disk.
    """
    payload = {
        "schema": EXPORT_SCHEMA_VERSION,
        "definition_version": DEFINITION_VERSION,
        "origin_definition_version": ORIGIN_DEFINITION_VERSION,
        "activity_definition_version": ACTIVITY_DEFINITION_VERSION,
        "analysis_scope": scope,
        "lineage": {"is_fork": lineage.is_fork, "parent": lineage.parent},
        "template_provided": template_provided,
        "parent_repo_provided": parent_repo_provided,
        "vendor_scan": vendor_scan,
        "identity": {
            "actors": [
                {
                    "canonical_id": actor.canonical_id,
                    "attribution_state": actor.attribution_state,
                    "emails": sorted(actor.emails),
                    "github_login": actor.github_login,
                }
                for actor in sorted(identity.actors, key=lambda a: a.canonical_id)
            ],
            "email_patterns": sorted(p.pattern for p in identity.email_patterns),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_export(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    *,
    template_provided: bool = False,
    parent_repo_provided: bool = False,
    include_files: bool = False,
    scope: str = DEFAULT_SCOPE,
) -> dict[str, Any]:
    repo = repo.resolve()
    commits, origin = prepare_inputs(
        repo, identity, lineage, include_files=include_files, scope=scope
    )
    rows: list[dict[str, Any]] = []
    for commit in commits:
        klass = origin.classes_by_sha.get(commit.sha, "unresolved")
        actor = identity.actor_for_email(commit.author_email)
        prod, tests, _docs = split_paths(commit.files)
        rows.append(
            {
                "sha": commit.sha,
                "ts": commit.date,
                "origin": klass,
                "actor": actor.canonical_id if actor is not None else None,
                "bot": klass == "bot",
                "is_merge": commit.is_merge,
                "prod_paths_touched": len(prod),
                "test_paths_touched": len(tests),
                "cochange": (len(tests) > 0) if prod else None,
                "subject_class": subject_class(commit.subject),
            }
        )
    return {
        "meta": _meta(
            repo,
            identity,
            lineage,
            rows,
            scope,
            template_provided,
            parent_repo_provided,
            include_files,
        ),
        "actors": _actor_rows(origin, identity, commits),
        "commits": rows,
    }


def _meta(
    repo: Path,
    identity: IdentityConfig,
    lineage: Lineage,
    rows: list[dict[str, Any]],
    scope: str,
    template_provided: bool,
    parent_repo_provided: bool,
    vendor_scan: bool,
) -> dict[str, Any]:
    return {
        "schema": EXPORT_SCHEMA_VERSION,
        "tool_name": "grift",
        "tool_version": __version__,
        "definition_version": DEFINITION_VERSION,
        "origin_definition_version": ORIGIN_DEFINITION_VERSION,
        "activity_definition_version": ACTIVITY_DEFINITION_VERSION,
        "analysis_scope": scope,
        "analyzed_commit_sha": rev_parse(repo),
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_digest": config_digest(
            identity,
            lineage,
            template_provided=template_provided,
            parent_repo_provided=parent_repo_provided,
            vendor_scan=vendor_scan,
            scope=scope,
        ),
        "commit_count": len(rows),
    }


def _actor_rows(origin: Any, identity: IdentityConfig, commits: list) -> list[dict[str, Any]]:
    """Aggregated engagement per canonical_id. Tenant activity only.

    Per-actor quality metrics (per-actor co-change etc.) are forbidden here
    (personal-evaluation rail) and stay forbidden in export-v2.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for commit in commits:
        if origin.classes_by_sha.get(commit.sha) != "tenant_unique":
            continue
        actor = identity.actor_for_email(commit.author_email)
        if actor is None:
            continue
        entry = by_id.setdefault(
            actor.canonical_id,
            {
                "canonical_id": actor.canonical_id,
                "attribution_state": actor.attribution_state,
                "dates": [],
            },
        )
        entry["dates"].append(commit.date)
    rows: list[dict[str, Any]] = []
    for canonical_id in sorted(by_id):
        entry = by_id[canonical_id]
        dates = entry["dates"]
        rows.append(
            {
                "canonical_id": canonical_id,
                "attribution_state": entry["attribution_state"],
                "commits": len(dates),
                "active_days": len(set(dates)),
                "first_ts": min(dates),
                "last_ts": max(dates),
                "core_period": compute_core_activity_period(dates),
            }
        )
    return rows


def write_export(export: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ndjson = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in export["commits"]
    )
    (out_dir / "commits.ndjson").write_text(ndjson, encoding="utf-8")
    (out_dir / "actors.json").write_text(
        json.dumps(export["actors"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "export-meta.json").write_text(
        json.dumps(export["meta"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
