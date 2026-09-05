"""Strict, privacy-bounded actor collection artifacts.

The collection deliberately separates the full repository population from the
selected actor cards.  Public provider data may decorate cards, but it does not
participate in either the partition or population digest.  The writer stages a
complete directory beside the destination and verifies it before publishing it
with a rename.

``collection-manifest.json`` is the root of trust for the directory.  Every
other regular file is registered by path, byte length and SHA-256.  The
manifest cannot contain its own digest without recursion, so it is the one
implicitly registered member.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import unquote

from tep_core.attribution import AttributionIndex, InferredActor, PublicAccount, attribution_payload
from tep_core.forge_public import canonical_account_profile_url
from tep_core.schema import validate_schema
from tep_core.version import __version__


MANIFEST_NAME = "collection-manifest.json"
MANIFEST_SCHEMA_VERSION = "actor-artifact-manifest-v1"
PARTITION_BASIS = "git_primary_author_cluster"
_ACTOR_ID_RE = re.compile(r"^(?:[a-z0-9][a-z0-9._-]{0,63}|actor_[0-9a-f]{12,32}|actor_unknown)$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
_PRIVATE_KEYS = frozenset(
    {
        "email",
        "emails",
        "raw_email",
        "raw_emails",
        "canonical_email",
        "canonical_emails",
        "internal_actor_id",
    }
)
_CARD_STATUSES = frozenset(
    {
        "not_requested",
        "unsupported",
        "unavailable",
        "unmatched",
        "matched",
        "ambiguous",
        "conflict",
    }
)


class ActorArtifactError(ValueError):
    """The collection cannot be produced or independently verified."""


@dataclass(frozen=True)
class ActorArtifactSet:
    repo_report: dict[str, Any]
    actor_index: dict[str, Any]
    cards: tuple[dict[str, Any], ...]
    repo_markdown: str
    index_markdown: str
    card_markdown: Mapping[str, str]
    population_digest: dict[str, str]
    actor_index_digest: dict[str, str]
    selection_digest: dict[str, str]


@dataclass(frozen=True)
class VerifiedActorArtifacts:
    root: Path
    full_actor_count: int
    selected_actor_count: int
    member_count: int
    population_digest: str
    actor_index_digest: str
    selection_digest: str


def _prepare_artifact_directory(path: Path, *, create_parents: bool) -> Path:
    """Return a lexical absolute path after rejecting every symlink ancestor.

    ``Path.mkdir(parents=True)`` and later file operations follow a symlink in
    any parent component.  Actor collections must stay below the path selected
    by the caller, so validation deliberately uses ``lstat`` and never
    canonicalises through a symlink.
    """

    candidate = Path(os.path.abspath(Path(path).expanduser()))
    components = list(reversed((candidate, *candidate.parents)))
    for index, component in enumerate(components):
        is_leaf = index == len(components) - 1
        try:
            metadata = component.lstat()
            mode = metadata.st_mode
        except FileNotFoundError:
            if is_leaf or not create_parents:
                continue
            try:
                component.mkdir(mode=0o700)
            except FileExistsError:
                pass
            try:
                metadata = component.lstat()
                mode = metadata.st_mode
            except OSError as exc:
                raise ActorArtifactError("actor artifact parent is unavailable") from exc
        except OSError as exc:
            raise ActorArtifactError("actor artifact path is unavailable") from exc
        if stat.S_ISLNK(mode):
            root = Path(component.anchor)
            root_metadata = root.lstat()
            trusted_system_alias = (
                component.parent == root
                and metadata.st_uid == 0
                and root_metadata.st_uid == 0
                and not root_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            )
            if trusted_system_alias:
                continue
            if is_leaf:
                raise ActorArtifactError("actor artifact destination must not be a symlink")
            raise ActorArtifactError(
                f"actor artifact path must not traverse a symlink: {component}"
            )
        if not stat.S_ISDIR(mode):
            if is_leaf:
                return candidate
            raise ActorArtifactError(f"actor artifact parent must be a directory: {component}")
    return candidate


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> dict[str, str]:
    return {"algorithm": "sha256", "value": _sha256_bytes(_canonical_bytes(value))}


def _population_digest(
    *,
    actor_count: int,
    human_commit_count: int,
    nonmerge_commit_count: int,
    merge_commit_count: int,
    partition_digest: Mapping[str, str],
) -> dict[str, str]:
    """Use the report-v2 population digest domain enforced by the schema."""

    body = {
        "actor_count": actor_count,
        "human_commit_count": human_commit_count,
        "nonmerge_commit_count": nonmerge_commit_count,
        "merge_commit_count": merge_commit_count,
        "basis": PARTITION_BASIS,
        "partition_digest": dict(partition_digest),
    }
    encoded = b"tep-population-v1\0" + _canonical_bytes(body)
    return {"algorithm": "sha256", "value": _sha256_bytes(encoded)}


def _require_digest(value: Any, *, label: str) -> dict[str, str]:
    if isinstance(value, str):
        raw = value.removeprefix("sha256:")
        result = {"algorithm": "sha256", "value": raw}
    elif isinstance(value, Mapping):
        result = {
            "algorithm": str(value.get("algorithm") or ""),
            "value": str(value.get("value") or ""),
        }
    else:
        raise ActorArtifactError(f"{label} must be a SHA-256 digest")
    if result["algorithm"] != "sha256" or not _HEX64_RE.fullmatch(result["value"]):
        raise ActorArtifactError(f"{label} must be a lowercase SHA-256 digest")
    return result


def _target_oid(report: Mapping[str, Any]) -> dict[str, str]:
    target: Any = (report.get("target") or {}).get("oid")
    provenance = report.get("provenance") or {}
    if target is None:
        target = provenance.get("target_oid")
    if target is None and provenance.get("analyzed_commit_sha"):
        value = str(provenance["analyzed_commit_sha"])
        target = {"algorithm": "sha1" if len(value) == 40 else "sha256", "value": value}
    if not isinstance(target, Mapping):
        raise ActorArtifactError("report target OID is required")
    algorithm = str(target.get("algorithm") or "")
    value = str(target.get("value") or "")
    expected = 40 if algorithm == "sha1" else 64 if algorithm == "sha256" else 0
    if expected == 0 or len(value) != expected or re.fullmatch(r"[0-9a-f]+", value) is None:
        raise ActorArtifactError("report target OID must match its Git object algorithm")
    return {"algorithm": algorithm, "value": value}


def _window(report: Mapping[str, Any]) -> dict[str, Any]:
    source: Any = report.get("window")
    if not isinstance(source, Mapping):
        source = (report.get("provenance") or {}).get("git_window")
    if not isinstance(source, Mapping) or "start" not in source or "end" not in source:
        raise ActorArtifactError("report window with start and end is required")
    start = source.get("start")
    end = source.get("end")
    if start is not None and not isinstance(start, str):
        raise ActorArtifactError("window start must be a string or null")
    if end is not None and not isinstance(end, str):
        raise ActorArtifactError("window end must be a string or null")
    result: dict[str, Any] = {"start": start, "end": end}
    unit = source.get("unit")
    if unit in {"date-range", "datetime-range"}:
        result["unit"] = unit
    elif isinstance(start, str) and isinstance(end, str):
        result["unit"] = "datetime-range" if "T" in start or "T" in end else "date-range"
    basis = source.get("basis")
    if isinstance(basis, str) and basis:
        result["basis"] = basis
    return result


def _actor_summaries(index: AttributionIndex) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for actor in sorted(index.actors, key=lambda item: (-len(item.commit_shas), item.actor_id)):
        if not _ACTOR_ID_RE.fullmatch(actor.actor_id):
            raise ActorArtifactError(
                f"actor id is not safe for a public artifact: {actor.actor_id!r}"
            )
        if actor.actor_id in seen:
            raise ActorArtifactError(f"duplicate actor id: {actor.actor_id}")
        seen.add(actor.actor_id)
        commit_count = len(actor.commit_shas)
        if actor.nonmerge_count < 0 or actor.merge_count < 0:
            raise ActorArtifactError(f"negative actor count: {actor.actor_id}")
        if actor.nonmerge_count + actor.merge_count != commit_count:
            raise ActorArtifactError(
                f"actor arithmetic mismatch for {actor.actor_id}: "
                "nonmerge + merge must equal commit count"
            )
        rows.append(
            {
                "actor_id": actor.actor_id,
                "commit_count": commit_count,
                "nonmerge_commit_count": actor.nonmerge_count,
                "merge_commit_count": actor.merge_count,
            }
        )
    return rows


def _selection(
    summaries: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    top: int | None,
    actor_ids: Sequence[str] | None,
) -> list[str]:
    available = [str(row["actor_id"]) for row in summaries]
    requested = list(actor_ids or ())
    if mode not in {"all", "top", "explicit"}:
        raise ActorArtifactError("selection mode must be all, top, or explicit")
    if mode == "all":
        if top is not None or requested:
            raise ActorArtifactError("all selection cannot include top or explicit actor IDs")
        return available
    if mode == "top":
        if not isinstance(top, int) or isinstance(top, bool) or top < 1:
            raise ActorArtifactError("top selection requires an integer >= 1")
        if requested:
            raise ActorArtifactError("top selection cannot include explicit actor IDs")
        return available[:top]
    if top is not None or not requested:
        raise ActorArtifactError("explicit selection requires actor IDs and forbids top")
    if len(set(requested)) != len(requested):
        raise ActorArtifactError("explicit actor IDs must be unique")
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ActorArtifactError("unknown explicit actor IDs: " + ", ".join(unknown))
    requested_set = set(requested)
    return [actor_id for actor_id in available if actor_id in requested_set]


def _account_key(account: PublicAccount) -> str:
    return "|".join((account.provider, account.host, account.account_id))


def _normalize_evidence_oid(value: Any, *, algorithm: str) -> dict[str, str]:
    if isinstance(value, Mapping):
        oid_algorithm = str(value.get("algorithm") or "")
        oid_value = str(value.get("value") or "")
    else:
        oid_algorithm = algorithm
        oid_value = str(value)
    expected = 40 if oid_algorithm == "sha1" else 64 if oid_algorithm == "sha256" else 0
    if expected == 0 or len(oid_value) != expected or re.fullmatch(r"[0-9a-f]+", oid_value) is None:
        raise ActorArtifactError("account evidence contains an invalid Git OID")
    return {"algorithm": oid_algorithm, "value": oid_value}


def _account_rows(
    actor: InferredActor,
    *,
    target_algorithm: str,
    account_evidence: Mapping[str, Sequence[Any]],
    status_override: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    mapped_status = {
        "not_requested": "not_requested",
        "unlinked": "unmatched",
        "linked": "matched",
        "ambiguous": "ambiguous",
        "conflict": "conflict",
    }.get(actor.public_account_status, actor.public_account_status)
    status = status_override or mapped_status
    if status not in _CARD_STATUSES:
        raise ActorArtifactError(f"invalid account status for {actor.actor_id}: {status!r}")
    accounts = tuple(sorted(actor.public_accounts, key=lambda item: item.key))
    if status in {"not_requested", "unsupported", "unavailable", "unmatched"}:
        if accounts:
            raise ActorArtifactError(
                f"{actor.actor_id} has attached accounts while status is {status}"
            )
        return status, []
    if status == "matched" and len(accounts) != 1:
        raise ActorArtifactError(f"matched actor {actor.actor_id} must have exactly one account")
    if status == "ambiguous" and len(accounts) < 2:
        raise ActorArtifactError(f"ambiguous actor {actor.actor_id} needs at least two accounts")
    if not accounts:
        raise ActorArtifactError(f"{status} actor {actor.actor_id} has no account evidence")

    actor_oids = {item.lower() for item in actor.commit_shas}
    rows: list[dict[str, Any]] = []
    for account in accounts:
        if account.provider not in {"github", "gitlab"}:
            raise ActorArtifactError(f"unsupported actor-card provider: {account.provider}")
        if not account.handle or not account.profile_url:
            raise ActorArtifactError(
                f"account {_account_key(account)!r} needs a handle and profile URL"
            )
        canonical_profile = canonical_account_profile_url(
            provider=account.provider,
            host=account.host,
            handle=account.handle,
            value=account.profile_url,
        )
        if canonical_profile is None or canonical_profile != account.profile_url:
            raise ActorArtifactError(
                f"account {_account_key(account)!r} needs a canonical credential-free HTTPS "
                "profile URL on the exact account host"
            )
        raw_oids = account_evidence.get(_account_key(account))
        if not raw_oids:
            raise ActorArtifactError(
                f"account {_account_key(account)!r} is missing exact commit evidence"
            )
        evidence: list[dict[str, Any]] = []
        evidence_basis = account.evidence or ""
        kind = (
            "declared_identity"
            if "identity_declared" in evidence_basis or "declared_identity" in evidence_basis
            else "commit_account_link"
        )
        normalized_oids: list[dict[str, str]] = []
        for raw_oid in raw_oids:
            oid = _normalize_evidence_oid(raw_oid, algorithm=target_algorithm)
            if oid["algorithm"] != target_algorithm:
                raise ActorArtifactError("account evidence object format differs from target")
            normalized_oids.append(oid)
        if status == "conflict":
            normalized_oids = [oid for oid in normalized_oids if oid["value"] in actor_oids]
            if not normalized_oids:
                raise ActorArtifactError(
                    f"conflicted account has no evidence for actor {actor.actor_id}"
                )
        elif any(oid["value"] not in actor_oids for oid in normalized_oids):
            raise ActorArtifactError(
                f"account evidence OID is not a member of actor {actor.actor_id}"
            )
        seen: set[str] = set()
        for oid in normalized_oids:
            marker = f"{kind}:{oid['value']}"
            if marker in seen:
                continue
            seen.add(marker)
            evidence.append({"kind": kind, "commit_oid": oid})
        evidence.sort(key=lambda item: (item["kind"], item["commit_oid"]["value"]))
        rows.append(
            {
                "provider": account.provider,
                "host": account.host,
                "account_id": account.account_id,
                "handle": account.handle,
                "profile_url": account.profile_url,
                "evidence": evidence,
            }
        )
    return status, rows


def _normalize_input_digests(provenance: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    source = provenance.get("input_digests")
    if not isinstance(source, Mapping):
        return result
    for key, value in source.items():
        if not isinstance(key, str) or re.fullmatch(r"[a-z][a-z0-9_.-]*", key) is None:
            raise ActorArtifactError(f"invalid provenance digest key: {key!r}")
        result[key] = (
            None if value is None else _require_digest(value, label=f"input_digests.{key}")
        )
    return result


def _strict_repo_report(
    report: Mapping[str, Any],
    *,
    index: AttributionIndex,
    target: Mapping[str, str],
    window: Mapping[str, Any],
    summaries: Sequence[Mapping[str, Any]],
    population_digest: Mapping[str, str],
    actor_index_digest: Mapping[str, str],
) -> dict[str, Any]:
    provenance = report.get("provenance") or {}
    if not isinstance(provenance, Mapping):
        raise ActorArtifactError("report provenance must be an object")
    analyzed_at = provenance.get("analyzed_at")
    definition_version = provenance.get("definition_version")
    completeness = provenance.get("revision_completeness")
    if not isinstance(analyzed_at, str) or not analyzed_at:
        raise ActorArtifactError("report provenance analyzed_at is required")
    if not isinstance(definition_version, str) or not definition_version:
        raise ActorArtifactError("report provenance definition_version is required")
    if not isinstance(completeness, Mapping):
        raise ActorArtifactError("report revision completeness is required")
    revision = {key: completeness.get(key) for key in ("shallow", "promisor", "complete")}
    if any(not isinstance(value, bool) for value in revision.values()):
        raise ActorArtifactError("revision completeness values must be booleans")
    if revision["complete"] != (not revision["shallow"] and not revision["promisor"]):
        raise ActorArtifactError("revision completeness is inconsistent")

    attributed_nonmerge = sum(int(row["nonmerge_commit_count"]) for row in summaries)
    attributed_merges = sum(int(row["merge_commit_count"]) for row in summaries)
    attributed_total = attributed_nonmerge + attributed_merges
    all_human_total = attributed_total + len(index.unresolved_shas)
    all_human_nonmerge = all_human_total - index.merge_count
    if all_human_nonmerge < 0:
        raise ActorArtifactError("attribution merge count exceeds the human population")
    attribution = attribution_payload(index, all_human_nonmerge)
    limitations = list(report.get("limitations") or ())
    limitations.extend(
        [
            "Actor IDs are repo-local Git primary-author clusters, not verified people.",
            "Provider enrichment is display evidence and cannot change the actor partition.",
        ]
    )
    if index.unresolved_shas:
        limitations.append(
            "Unresolved commits remain in attribution coverage but are excluded from actor cards."
        )
    limitations = list(dict.fromkeys(str(item) for item in limitations if str(item)))
    notices = list(report.get("notices") or ())
    notices.append("Evidence, not a score, rank, hiring decision, or personhood claim.")
    notices = list(dict.fromkeys(str(item) for item in notices if str(item)))
    source_input_digests = provenance.get("input_digests")
    raw_tagset = provenance.get("tagset_digest")
    source_tagset = (
        source_input_digests.get("tagset") if isinstance(source_input_digests, Mapping) else None
    )
    if not isinstance(raw_tagset, str) or not _HEX64_RE.fullmatch(raw_tagset):
        raise ActorArtifactError("tagset_digest must be a lowercase SHA-256 string")
    if source_tagset != raw_tagset:
        raise ActorArtifactError("provenance tagset_digest must equal input_digests.tagset")
    input_digests = _normalize_input_digests(provenance)
    input_digests["tagset"] = raw_tagset
    tagset_digest = raw_tagset
    strict_provenance: dict[str, Any] = {
        "tool_name": "grift",
        "tool_version": str(provenance.get("tool_version") or __version__),
        "definition_version": definition_version,
        "analysis_scope": "repo",
        "analyzed_at": analyzed_at,
        "input_digests": input_digests,
        "tagset_digest": tagset_digest,
        "target_oid": dict(target),
        "revision_completeness": revision,
    }
    analyzed_sha = provenance.get("analyzed_commit_sha")
    if analyzed_sha is not None:
        if str(analyzed_sha) != target["value"]:
            raise ActorArtifactError("analyzed commit SHA differs from target OID")
        strict_provenance["analyzed_commit_sha"] = str(analyzed_sha)
    public_digest = provenance.get("public_evidence_digest")
    if public_digest is not None:
        strict_provenance["public_evidence_digest"] = _require_digest(
            public_digest, label="public_evidence_digest"
        )

    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
    result: dict[str, Any] = {
        "schema_version": "report-v2",
        "report_kind": "evidence",
        "subject": {"kind": "repo", "selection": "repo_all_human"},
        "target": {"oid": dict(target)},
        "provenance": strict_provenance,
        "population": {
            "actor_count": len(summaries),
            "human_commit_count": all_human_total,
            "nonmerge_commit_count": all_human_nonmerge,
            "merge_commit_count": index.merge_count,
            "basis": PARTITION_BASIS,
            "partition_digest": {
                "algorithm": "sha256",
                "value": index.partition_digest,
            },
            "population_digest": dict(population_digest),
        },
        "attribution": attribution,
        "window": dict(window),
        "metrics": deepcopy(dict(metrics)),
        "input_coverage": deepcopy(dict(report.get("input_coverage") or {})),
        "actor_index_digest": dict(actor_index_digest),
        "limitations": limitations,
        "notices": notices,
    }
    errors = validate_schema("report-v2", result)
    if errors:
        raise ActorArtifactError("repo report validation failed: " + "; ".join(errors))
    return result


def _assert_no_private_data(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in _PRIVATE_KEYS:
                raise ActorArtifactError(f"private actor field is forbidden at {path}.{key}")
            _assert_no_private_data(child, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_private_data(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _EMAIL_RE.search(unquote(value)):
        raise ActorArtifactError(f"email-like value is forbidden at {path}")


def build_actor_artifacts(
    index: AttributionIndex,
    report: Mapping[str, Any],
    *,
    selection_mode: str = "all",
    top: int | None = None,
    actor_ids: Sequence[str] | None = None,
    account_evidence: Mapping[str, Sequence[Any]] | None = None,
    account_status_overrides: Mapping[str, str] | None = None,
    actor_details: Mapping[str, Mapping[str, Any]] | None = None,
) -> ActorArtifactSet:
    """Build schema-valid repo, index and selected-card payloads.

    ``account_evidence`` is keyed by ``provider|host|stable_account_id``.  The
    exact commit OIDs are required because an ``AttributionIndex`` intentionally
    does not retain a provider response body or invent evidence after the join.
    """

    target = _target_oid(report)
    window = _window(report)
    partition = _require_digest(index.partition_digest, label="partition_digest")
    summaries = _actor_summaries(index)
    selected_ids = _selection(
        summaries,
        mode=selection_mode,
        top=top,
        actor_ids=actor_ids,
    )
    details = actor_details or {}
    if details and selection_mode != "explicit":
        raise ActorArtifactError("actor details are allowed only for explicit selection")
    unknown_details = sorted(set(details) - set(selected_ids))
    if unknown_details:
        raise ActorArtifactError(
            "actor details include unselected actor IDs: " + ", ".join(unknown_details)
        )
    attributed_total = sum(int(row["commit_count"]) for row in summaries)
    full_human_total = attributed_total + len(index.unresolved_shas)
    full_nonmerge_total = full_human_total - index.merge_count
    if full_nonmerge_total < 0:
        raise ActorArtifactError("attribution merge count exceeds the human population")
    population_digest = _population_digest(
        actor_count=len(summaries),
        human_commit_count=full_human_total,
        nonmerge_commit_count=full_nonmerge_total,
        merge_commit_count=index.merge_count,
        partition_digest=partition,
    )
    actor_index: dict[str, Any] = {
        "schema_version": "actor-index-v1",
        "report_kind": "actor_index",
        "target": {"oid": target},
        "partition_digest": partition,
        "population_digest": population_digest,
        "population": {
            "actor_count": len(summaries),
            "human_commit_count": attributed_total,
            "basis": PARTITION_BASIS,
            "window": window,
        },
        "actors": summaries,
        "selection": {
            "mode": selection_mode,
            "selected_count": len(selected_ids),
            "actor_ids": selected_ids,
        },
        "limitations": [
            "Actor IDs are repo-local Git primary-author clusters, not verified people.",
            "Top selection is observed commit-count extraction, never a quality rank.",
        ],
    }
    errors = validate_schema("actor-index-v1", actor_index)
    if errors:
        raise ActorArtifactError("actor index validation failed: " + "; ".join(errors))
    actor_index_digest = _digest(actor_index)

    actor_map = {actor.actor_id: actor for actor in index.actors}
    evidence = account_evidence or {}
    overrides = account_status_overrides or {}
    cards: list[dict[str, Any]] = []
    for actor_id in selected_ids:
        actor = actor_map[actor_id]
        status, accounts = _account_rows(
            actor,
            target_algorithm=target["algorithm"],
            account_evidence=evidence,
            status_override=overrides.get(actor_id),
        )
        card: dict[str, Any] = {
            "schema_version": "actor-card-v1",
            "report_kind": "actor_card",
            "actor_id": actor_id,
            "target": {"oid": target},
            "partition_digest": partition,
            "population_digest": population_digest,
            "n": len(actor.commit_shas),
            "denominator": attributed_total,
            "window": window,
            "basis": PARTITION_BASIS,
            "account_status": status,
            "accounts": accounts,
            "metrics": {},
            "limitations": [
                "This card describes one repo-local cluster and is not a person or quality score."
            ],
            "notices": ["Provider accounts are display evidence only."],
        }
        detail = details.get(actor_id)
        if detail is not None:
            for key in ("experience", "role_profile"):
                value = detail.get(key)
                if not isinstance(value, Mapping):
                    raise ActorArtifactError(
                        f"explicit actor detail for {actor_id} is missing {key}"
                    )
                card[key] = deepcopy(value)
        card_errors = validate_schema("actor-card-v1", card)
        if card_errors:
            raise ActorArtifactError(
                f"actor card validation failed for {actor_id}: " + "; ".join(card_errors)
            )
        cards.append(card)

    selected_payload = {
        "domain": "tep-actor-selection-v1",
        "mode": selection_mode,
        "actor_ids": selected_ids,
        "cards": [{"actor_id": card["actor_id"], "digest": _digest(card)} for card in cards],
    }
    selection_digest = _digest(selected_payload)
    repo_report = _strict_repo_report(
        report,
        index=index,
        target=target,
        window=window,
        summaries=summaries,
        population_digest=population_digest,
        actor_index_digest=actor_index_digest,
    )
    repo_markdown = _render_repo_markdown(
        repo_report, actor_index, actor_index_digest, selection_digest
    )
    index_markdown = _render_index_markdown(actor_index, actor_index_digest, selection_digest)
    card_markdown = {card["actor_id"]: _render_card_markdown(card) for card in cards}
    for payload in (repo_report, actor_index, *cards):
        _assert_no_private_data(payload)
    for name, markdown in {
        "repo-report.md": repo_markdown,
        "actor-index.md": index_markdown,
        **{f"actors/{key}.md": value for key, value in card_markdown.items()},
    }.items():
        _assert_no_private_data(markdown, path=name)
    return ActorArtifactSet(
        repo_report=repo_report,
        actor_index=actor_index,
        cards=tuple(cards),
        repo_markdown=repo_markdown,
        index_markdown=index_markdown,
        card_markdown=card_markdown,
        population_digest=population_digest,
        actor_index_digest=actor_index_digest,
        selection_digest=selection_digest,
    )


def _render_repo_markdown(
    report: Mapping[str, Any],
    actor_index: Mapping[str, Any],
    actor_index_digest: Mapping[str, str],
    selection_digest: Mapping[str, str],
) -> str:
    target = report["target"]["oid"]
    population = actor_index["population"]
    selection = actor_index["selection"]
    coverage = report.get("input_coverage") or {}
    public_forge = coverage.get("public_forge") if isinstance(coverage, Mapping) else None
    license_evidence = (
        public_forge.get("repository_license") if isinstance(public_forge, Mapping) else None
    )
    lines = [
        "# Repository actor evidence",
        "",
        "> Evidence only. Actor clusters are not people, scores, or ranks.",
        "",
        f"- Target: `{target['algorithm']}:{target['value']}`",
        f"- Partition digest: `{actor_index['partition_digest']['value']}`",
        f"- Population digest: `{actor_index['population_digest']['value']}`",
        f"- Full actors: {population['actor_count']}",
        f"- Full attributed commits: {population['human_commit_count']}",
        f"- Selected actors: {selection['selected_count']}",
        f"- Actor index digest: `{actor_index_digest['value']}`",
        f"- Selection digest: `{selection_digest['value']}`",
        "- Index: [actor-index.md](actor-index.md)",
        "- Machine report: [repo-report.json](repo-report.json)",
    ]
    if isinstance(license_evidence, Mapping):
        license_digest = license_evidence.get("digest") or {}
        license_target = license_evidence.get("target_oid") or {}
        files = license_evidence.get("files") or []
        lines.extend(
            [
                f"- Root license files at fixed target: {len(files)}",
                f"- License target: `{license_target.get('algorithm')}:{license_target.get('value')}`",
                f"- License evidence digest: `{license_digest.get('value')}` (API terms separate)",
            ]
        )
        for item in files:
            if not isinstance(item, Mapping):
                continue
            blob = item.get("blob_oid") or {}
            lines.append(
                f"- License `{item.get('path')}`: blob "
                f"`{blob.get('algorithm')}:{blob.get('value')}`, "
                f"SHA-256 `{item.get('sha256')}`, {item.get('bytes')} bytes (body omitted)"
            )
    lines.append("")
    return "\n".join(lines)


def _render_index_markdown(
    actor_index: Mapping[str, Any],
    actor_index_digest: Mapping[str, str],
    selection_digest: Mapping[str, str],
) -> str:
    selected = set(actor_index["selection"]["actor_ids"])
    lines = [
        "# Actor index",
        "",
        "> Commit-count extraction only; this is not a quality ranking.",
        "",
        f"- Full actors: {actor_index['population']['actor_count']}",
        f"- Full attributed commits: {actor_index['population']['human_commit_count']}",
        f"- Population digest: `{actor_index['population_digest']['value']}`",
        f"- Selection mode: `{actor_index['selection']['mode']}`",
        f"- Selected actors: {actor_index['selection']['selected_count']}",
        f"- Actor index digest: `{actor_index_digest['value']}`",
        f"- Selection digest: `{selection_digest['value']}`",
        "",
        "| Actor | Commits | Non-merge | Merge | Selected card |",
        "|---|---:|---:|---:|---|",
    ]
    for actor in actor_index["actors"]:
        actor_id = actor["actor_id"]
        link = (
            f"[JSON](actors/{actor_id}.json) / [Markdown](actors/{actor_id}.md)"
            if actor_id in selected
            else "—"
        )
        lines.append(
            f"| `{actor_id}` | {actor['commit_count']} | "
            f"{actor['nonmerge_commit_count']} | {actor['merge_commit_count']} | {link} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_card_markdown(card: Mapping[str, Any]) -> str:
    lines = [
        f"# Actor `{card['actor_id']}`",
        "",
        "> Repo-local primary-author cluster; not a personhood or quality claim.",
        "",
        f"- Target: `{card['target']['oid']['algorithm']}:{card['target']['oid']['value']}`",
        f"- Partition digest: `{card['partition_digest']['value']}`",
        f"- Population digest: `{card['population_digest']['value']}`",
        f"- Observed commits: {card['n']} / {card['denominator']}",
        f"- Account status: `{card.get('account_status', 'not_requested')}`",
    ]
    for account in card["accounts"]:
        lines.append(
            f"- Account: [{account['provider']}:{account['handle']}]({account['profile_url']}) "
            f"on `{account['host']}` (stable id `{account['account_id']}`)"
        )
    for key, label in (("experience", "Experience"), ("role_profile", "Role profile")):
        detail = card.get(key)
        if not isinstance(detail, Mapping):
            continue
        suffix = (
            f"; reason `{detail['reason']}`"
            if detail.get("kind") == "not_observed" and detail.get("reason")
            else ""
        )
        lines.append(
            f"- {label}: `{detail.get('kind')}` "
            f"(definition `{detail.get('definition_version')}`{suffix}; structured values in JSON)"
        )
    lines.append("")
    return "\n".join(lines)


def _artifact_files(artifacts: ActorArtifactSet) -> dict[str, bytes]:
    files: dict[str, bytes] = {
        "repo-report.json": _json_bytes(artifacts.repo_report),
        "repo-report.md": artifacts.repo_markdown.encode("utf-8"),
        "actor-index.json": _json_bytes(artifacts.actor_index),
        "actor-index.md": artifacts.index_markdown.encode("utf-8"),
    }
    for card in artifacts.cards:
        actor_id = str(card["actor_id"])
        files[f"actors/{actor_id}.json"] = _json_bytes(card)
        files[f"actors/{actor_id}.md"] = artifacts.card_markdown[actor_id].encode("utf-8")
    return files


def _manifest(artifacts: ActorArtifactSet, files: Mapping[str, bytes]) -> dict[str, Any]:
    selection = artifacts.actor_index["selection"]
    members = [
        {
            "path": path,
            "sha256": _sha256_bytes(files[path]),
            "bytes": len(files[path]),
            "media_type": "application/json" if path.endswith(".json") else "text/markdown",
        }
        for path in sorted(files)
    ]
    links = [
        {
            "actor_id": actor_id,
            "json": f"actors/{actor_id}.json",
            "markdown": f"actors/{actor_id}.md",
        }
        for actor_id in selection["actor_ids"]
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "target": deepcopy(artifacts.actor_index["target"]),
        "partition_digest": deepcopy(artifacts.actor_index["partition_digest"]),
        "population_digest": deepcopy(artifacts.population_digest),
        "actor_index_digest": deepcopy(artifacts.actor_index_digest),
        "full": {
            "actor_count": artifacts.actor_index["population"]["actor_count"],
            "human_commit_count": artifacts.repo_report["population"]["human_commit_count"],
            "digest": deepcopy(artifacts.population_digest),
            "links": {
                "repo_json": "repo-report.json",
                "repo_markdown": "repo-report.md",
                "index_json": "actor-index.json",
                "index_markdown": "actor-index.md",
            },
        },
        "selection": {
            "mode": selection["mode"],
            "actor_count": selection["selected_count"],
            "digest": deepcopy(artifacts.selection_digest),
            "actor_ids": list(selection["actor_ids"]),
            "links": links,
        },
        "members": members,
    }


def write_actor_artifacts(
    destination: Path,
    artifacts: ActorArtifactSet,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Verify, stage, and publish one complete actor artifact directory."""

    destination = _prepare_artifact_directory(destination, create_parents=True)
    if destination.name in {"", ".", ".."}:
        raise ActorArtifactError("actor artifact destination must name a directory")
    if destination.is_symlink():
        raise ActorArtifactError("actor artifact destination must not be a symlink")
    if destination.exists() and not destination.is_dir():
        raise ActorArtifactError("actor artifact destination must be a directory")
    parent = destination.parent
    files = _artifact_files(artifacts)
    manifest = _manifest(artifacts, files)
    _validate_manifest_shape(manifest)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=parent))
    backup: Path | None = None
    try:
        for relative, content in files.items():
            target = _safe_member(staging, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (staging / MANIFEST_NAME).write_bytes(_json_bytes(manifest))
        verify_actor_artifact_directory(staging)
        if destination.exists():
            if not replace:
                raise ActorArtifactError(f"destination already exists: {destination}")
            backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.old-", dir=parent))
            backup.rmdir()
            os.replace(destination, backup)
        try:
            os.replace(staging, destination)
        except Exception:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists():
            if not destination.exists():
                os.replace(backup, destination)
            else:
                shutil.rmtree(backup)


def _safe_member(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ActorArtifactError("manifest member path must be a non-empty string")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ActorArtifactError(f"unsafe manifest member path: {relative!r}")
    if str(pure) != relative or "\\" in relative:
        raise ActorArtifactError(f"non-canonical manifest member path: {relative!r}")
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ActorArtifactError(f"manifest member escapes collection: {relative!r}") from exc
    return candidate


def _validate_manifest_shape(manifest: Any) -> None:
    if not isinstance(manifest, Mapping):
        raise ActorArtifactError("collection manifest must be an object")
    expected = {
        "schema_version",
        "target",
        "partition_digest",
        "population_digest",
        "actor_index_digest",
        "full",
        "selection",
        "members",
    }
    if set(manifest) != expected:
        raise ActorArtifactError("collection manifest has missing or unknown keys")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ActorArtifactError("unsupported actor artifact manifest version")
    _require_digest(manifest.get("partition_digest"), label="manifest partition digest")
    _require_digest(manifest.get("population_digest"), label="manifest population digest")
    _require_digest(manifest.get("actor_index_digest"), label="manifest actor index digest")
    full = manifest.get("full")
    if not isinstance(full, Mapping) or set(full) != {
        "actor_count",
        "human_commit_count",
        "digest",
        "links",
    }:
        raise ActorArtifactError("manifest full population block is not closed")
    if any(
        not isinstance(full.get(key), int) or isinstance(full.get(key), bool) or full[key] < 0
        for key in ("actor_count", "human_commit_count")
    ):
        raise ActorArtifactError("manifest full counts must be non-negative integers")
    _require_digest(full.get("digest"), label="manifest full digest")
    if not isinstance(full.get("links"), Mapping) or set(full["links"]) != {
        "repo_json",
        "repo_markdown",
        "index_json",
        "index_markdown",
    }:
        raise ActorArtifactError("manifest full links block is not closed")
    selection = manifest.get("selection")
    if not isinstance(selection, Mapping) or set(selection) != {
        "mode",
        "actor_count",
        "digest",
        "actor_ids",
        "links",
    }:
        raise ActorArtifactError("manifest selection block is not closed")
    if selection.get("mode") not in {"all", "top", "explicit"}:
        raise ActorArtifactError("manifest selection mode is invalid")
    selected_count = selection.get("actor_count")
    if (
        not isinstance(selected_count, int)
        or isinstance(selected_count, bool)
        or selected_count < 0
    ):
        raise ActorArtifactError("manifest selected count must be a non-negative integer")
    _require_digest(selection.get("digest"), label="manifest selection digest")
    actor_ids = selection.get("actor_ids")
    links = selection.get("links")
    if not isinstance(actor_ids, list) or not isinstance(links, list):
        raise ActorArtifactError("manifest selection IDs and links must be arrays")
    if len(actor_ids) != len(set(actor_ids)) or selection["actor_count"] != len(actor_ids):
        raise ActorArtifactError("manifest selected count/IDs are inconsistent")
    if len(links) != len(actor_ids):
        raise ActorArtifactError("manifest selected links are incomplete")
    members = manifest.get("members")
    if not isinstance(members, list):
        raise ActorArtifactError("manifest members must be an array")
    paths: list[str] = []
    for member in members:
        if not isinstance(member, Mapping) or set(member) != {
            "path",
            "sha256",
            "bytes",
            "media_type",
        }:
            raise ActorArtifactError("manifest member is not closed")
        path = member.get("path")
        if not isinstance(path, str):
            raise ActorArtifactError("manifest member path must be a string")
        _safe_member(Path("/actor-artifact-root"), path)
        paths.append(path)
        if not _HEX64_RE.fullmatch(str(member.get("sha256") or "")):
            raise ActorArtifactError(f"manifest member digest is invalid: {path}")
        byte_count = member.get("bytes")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            raise ActorArtifactError(f"manifest member byte count is invalid: {path}")
        if member.get("media_type") not in {"application/json", "text/markdown"}:
            raise ActorArtifactError(f"manifest member media type is invalid: {path}")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ActorArtifactError("manifest member paths must be sorted and unique")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActorArtifactError(f"cannot parse JSON member: {path.name}") from exc
    if not isinstance(value, dict):
        raise ActorArtifactError(f"JSON member must contain an object: {path.name}")
    return value


def _walk_regular_members(root: Path) -> set[str]:
    found: set[str] = set()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in list(dirnames):
            candidate = directory_path / name
            if candidate.is_symlink():
                relative = candidate.relative_to(root)
                raise ActorArtifactError(f"symlink directory is forbidden: {relative}")
        for name in filenames:
            candidate = directory_path / name
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise ActorArtifactError(f"symlink member is forbidden: {relative}")
            if not candidate.is_file():
                raise ActorArtifactError(f"non-regular member is forbidden: {relative}")
            found.add(relative)
    return found


def _population_digest_from_report(report: Mapping[str, Any]) -> dict[str, str]:
    population = report["population"]
    return _population_digest(
        actor_count=population["actor_count"],
        human_commit_count=population["human_commit_count"],
        nonmerge_commit_count=population["nonmerge_commit_count"],
        merge_commit_count=population["merge_commit_count"],
        partition_digest=population["partition_digest"],
    )


def verify_actor_artifact_directory(root: Path) -> VerifiedActorArtifacts:
    """Offline verification of every byte and cross-artifact invariant."""

    root = _prepare_artifact_directory(root, create_parents=False)
    if root.is_symlink() or not root.is_dir():
        raise ActorArtifactError("actor artifact root must be a real directory")
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ActorArtifactError("collection manifest is missing or is a symlink")
    manifest = _read_json(manifest_path)
    _validate_manifest_shape(manifest)
    _assert_no_private_data(manifest)
    registered = {str(member["path"]) for member in manifest["members"]}
    found = _walk_regular_members(root)
    expected = registered | {MANIFEST_NAME}
    if found != expected:
        unknown = sorted(found - expected)
        missing = sorted(expected - found)
        raise ActorArtifactError(
            "actor artifact inventory mismatch"
            + (f"; unknown={unknown}" if unknown else "")
            + (f"; missing={missing}" if missing else "")
        )
    for member in manifest["members"]:
        relative = str(member["path"])
        path = _safe_member(root, relative)
        if path.is_symlink() or not path.is_file():
            raise ActorArtifactError(f"manifest member is missing or unsafe: {relative}")
        content = path.read_bytes()
        if len(content) != member["bytes"]:
            raise ActorArtifactError(f"member byte count mismatch: {relative}")
        if _sha256_bytes(content) != member["sha256"]:
            raise ActorArtifactError(f"member digest mismatch: {relative}")

    required = {"repo-report.json", "repo-report.md", "actor-index.json", "actor-index.md"}
    if not required.issubset(registered):
        raise ActorArtifactError("required repo/index members are not all registered")
    report = _read_json(root / "repo-report.json")
    index = _read_json(root / "actor-index.json")
    for name, value in (("report-v2", report), ("actor-index-v1", index)):
        errors = validate_schema(name, value)
        if errors:
            raise ActorArtifactError(f"{name} validation failed: " + "; ".join(errors))
        _assert_no_private_data(value)

    index_digest = _digest(index)
    population_digest = _population_digest_from_report(report)
    if manifest["actor_index_digest"] != index_digest:
        raise ActorArtifactError("manifest actor index digest mismatch")
    if manifest["population_digest"] != population_digest:
        raise ActorArtifactError("manifest population digest mismatch")
    if manifest["partition_digest"] != index["partition_digest"]:
        raise ActorArtifactError("manifest partition digest mismatch")
    if index["population_digest"] != population_digest:
        raise ActorArtifactError("actor index population digest mismatch")
    if report["target"] != index["target"]:
        raise ActorArtifactError("repo report and actor index target mismatch")
    if report["population"]["partition_digest"] != index["partition_digest"]:
        raise ActorArtifactError("repo report and actor index partition mismatch")
    if report["population"]["population_digest"] != population_digest:
        raise ActorArtifactError("repo report population digest mismatch")
    if report.get("actor_index_digest") != index_digest:
        raise ActorArtifactError("repo report actor index digest mismatch")
    if report["population"]["actor_count"] != index["population"]["actor_count"]:
        raise ActorArtifactError("repo report and actor index actor counts differ")
    unresolved_count = report["attribution"]["unresolved_commit_count"]
    if report["population"]["human_commit_count"] != (
        index["population"]["human_commit_count"] + unresolved_count
    ):
        raise ActorArtifactError(
            "repo full population must equal attributed actor commits plus unresolved commits"
        )

    selection = index["selection"]
    selected_ids = list(selection["actor_ids"])
    expected_card_paths = {
        path
        for actor_id in selected_ids
        for path in (f"actors/{actor_id}.json", f"actors/{actor_id}.md")
    }
    actual_card_paths = {path for path in registered if path.startswith("actors/")}
    if expected_card_paths != actual_card_paths:
        raise ActorArtifactError("selected actor cards and registered members differ")
    summaries = {row["actor_id"]: row for row in index["actors"]}
    cards: list[dict[str, Any]] = []
    for actor_id in selected_ids:
        card = _read_json(root / f"actors/{actor_id}.json")
        card_errors = validate_schema("actor-card-v1", card)
        if card_errors:
            raise ActorArtifactError(
                f"actor-card-v1 validation failed for {actor_id}: " + "; ".join(card_errors)
            )
        _assert_no_private_data(card)
        summary = summaries[actor_id]
        if card["actor_id"] != actor_id:
            raise ActorArtifactError("actor card ID/filename mismatch")
        if card["target"] != index["target"]:
            raise ActorArtifactError(f"actor card target mismatch: {actor_id}")
        if card["partition_digest"] != index["partition_digest"]:
            raise ActorArtifactError(f"actor card partition mismatch: {actor_id}")
        if card["population_digest"] != population_digest:
            raise ActorArtifactError(f"actor card population mismatch: {actor_id}")
        if card["window"] != index["population"]["window"]:
            raise ActorArtifactError(f"actor card window mismatch: {actor_id}")
        if card["n"] != summary["commit_count"]:
            raise ActorArtifactError(f"actor card numerator mismatch: {actor_id}")
        if card["denominator"] != index["population"]["human_commit_count"]:
            raise ActorArtifactError(f"actor card denominator mismatch: {actor_id}")
        cards.append(card)

    selected_payload = {
        "domain": "tep-actor-selection-v1",
        "mode": selection["mode"],
        "actor_ids": selected_ids,
        "cards": [{"actor_id": card["actor_id"], "digest": _digest(card)} for card in cards],
    }
    selection_digest = _digest(selected_payload)
    manifest_selection = manifest["selection"]
    if manifest_selection["mode"] != selection["mode"]:
        raise ActorArtifactError("manifest/index selection mode mismatch")
    if manifest_selection["actor_ids"] != selected_ids:
        raise ActorArtifactError("manifest/index selected IDs mismatch")
    if manifest_selection["actor_count"] != selection["selected_count"]:
        raise ActorArtifactError("manifest/index selected count mismatch")
    if manifest_selection["digest"] != selection_digest:
        raise ActorArtifactError("manifest selection digest mismatch")
    expected_links = [
        {
            "actor_id": actor_id,
            "json": f"actors/{actor_id}.json",
            "markdown": f"actors/{actor_id}.md",
        }
        for actor_id in selected_ids
    ]
    if manifest_selection["links"] != expected_links:
        raise ActorArtifactError("manifest selection links are not deterministic")
    full = manifest["full"]
    if full["actor_count"] != index["population"]["actor_count"]:
        raise ActorArtifactError("manifest full actor count mismatch")
    if full["human_commit_count"] != report["population"]["human_commit_count"]:
        raise ActorArtifactError("manifest full commit count mismatch")
    if full["digest"] != population_digest:
        raise ActorArtifactError("manifest full digest mismatch")
    if full["links"] != {
        "repo_json": "repo-report.json",
        "repo_markdown": "repo-report.md",
        "index_json": "actor-index.json",
        "index_markdown": "actor-index.md",
    }:
        raise ActorArtifactError("manifest full links are not deterministic")
    expected_repo_markdown = _render_repo_markdown(
        report, index, index_digest, selection_digest
    ).encode("utf-8")
    expected_index_markdown = _render_index_markdown(index, index_digest, selection_digest).encode(
        "utf-8"
    )
    if (root / "repo-report.md").read_bytes() != expected_repo_markdown:
        raise ActorArtifactError("repo Markdown does not match verified JSON")
    if (root / "actor-index.md").read_bytes() != expected_index_markdown:
        raise ActorArtifactError("actor index Markdown does not match verified JSON")
    for card in cards:
        actor_id = card["actor_id"]
        if (root / f"actors/{actor_id}.md").read_bytes() != _render_card_markdown(card).encode(
            "utf-8"
        ):
            raise ActorArtifactError(f"actor Markdown does not match verified JSON: {actor_id}")
    return VerifiedActorArtifacts(
        root=root,
        full_actor_count=index["population"]["actor_count"],
        selected_actor_count=selection["selected_count"],
        member_count=len(registered),
        population_digest=population_digest["value"],
        actor_index_digest=index_digest["value"],
        selection_digest=selection_digest["value"],
    )


__all__ = [
    "ActorArtifactError",
    "ActorArtifactSet",
    "VerifiedActorArtifacts",
    "build_actor_artifacts",
    "verify_actor_artifact_directory",
    "write_actor_artifacts",
]
