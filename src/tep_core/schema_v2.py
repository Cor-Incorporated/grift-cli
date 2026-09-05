"""Validators for report-v2, project-v1, and alignment-v1."""

from __future__ import annotations

import re
from typing import Any

from tep_core.actor_basis import actor_analysis_scope
from tep_core.alignment import forbidden_key_hits
from tep_core.attribution import ACTOR_ID_RE
from tep_core.identity import ATTRIBUTION_STATES, CANONICAL_ID_RE
from tep_core.schema import validate_schema
from tep_core.v2_constants import (
    ACTOR_CARD_SCHEMA_VERSION,
    COMPARISONS,
    ROLE_LENSES,
    SUBJECT_KINDS,
    SURFACES,
    WINDOW_BASIS,
)
from tep_core.version import (
    ALIGNMENT_SCHEMA_VERSION,
    COORDINATION_DEFINITION_VERSION,
    PROJECT_SCHEMA_VERSION,
    REPORT_V2_SCHEMA_VERSION,
    RHYTHM_DEFINITION_VERSION,
    SURFACE_DEFINITION_VERSION,
    VERIFICATION_DEFINITION_VERSION,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GENERIC_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)

_PROFILE_VERSIONS = {
    "surface_profile": SURFACE_DEFINITION_VERSION,
    "change_rhythm": RHYTHM_DEFINITION_VERSION,
    "verification_profile": VERIFICATION_DEFINITION_VERSION,
    "coordination_profile": COORDINATION_DEFINITION_VERSION,
}

_REPORT_V2_KEYS = frozenset(
    {
        "schema_version",
        "report_kind",
        "subject",
        "target",
        "provenance",
        "population",
        "window",
        "metrics",
        "repository",
        "identity",
        "lineage",
        "origin",
        "attribution",
        "activity",
        "core_activity_period",
        "test_frameworks",
        "test_cochange",
        "rework",
        "survival",
        "context_profile",
        "surface_profile",
        "change_rhythm",
        "verification_profile",
        "coordination_profile",
        "event_observation",
        "event_rhythm",
        "tracker_lifecycle",
        "role_lens",
        "input_coverage",
        "limitations",
        "notices",
        "interpretation",
        "reference",
        "actor_directory",
        "experience",
        "role_profile",
        "library_context",
        "outcome",
        "actor_index_digest",
    }
)
_REPORT_V2_PROVENANCE_KEYS = frozenset(
    {
        "tool_name",
        "method_name",
        "tool_version",
        "definition_version",
        "origin_definition_version",
        "activity_definition_version",
        "analysis_scope",
        "analyzed_commit_sha",
        "analyzed_at",
        "observation_date",
        "window_basis",
        "identity_digest",
        "vendor_scan",
        "survival",
        "include_local_path",
        "as_of",
        "role_lens",
        "lineage",
        "event_window",
        "git_window",
        "source_format",
        "reference_id",
        "reference_manifest",
        "reference_manifest_digest",
        "input_digests",
        "tagset_digest",
        "public_evidence_digest",
        "target_oid",
        "revision_completeness",
    }
)
_PROFILE_SCALAR_KEYS = {
    "kind",
    "unit",
    "definition_version",
    "value",
    "values",
    "sample_size",
    "population",
    "classification_basis",
    "denominator_definition",
    "limitations",
    "timestamp_basis",
    "window_days",
    "window_population",
    "observation_date",
    "window_basis",
    "ambiguous_count",
    "unclassified_count",
}


class _Ctx:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _observation(ctx: _Ctx, node: Any, path: str, *, require_definition: bool = False) -> None:
    if node is None:
        ctx.err(path, "required")
        return
    if not isinstance(node, dict):
        ctx.err(path, "must be an object")
        return
    kind = node.get("kind")
    if kind in {"not_observed", "not_proven"}:
        reason = node.get("reason")
        if not _is_str(reason) or not _REASON_RE.match(reason):
            ctx.err(f"{path}.reason", "must be snake_case")
        if require_definition and not _is_str(node.get("definition_version")):
            ctx.err(f"{path}.definition_version", "required on profile")
        return
    if kind == "not_declared":
        reason = node.get("reason")
        if not _is_str(reason) or not _REASON_RE.match(reason):
            ctx.err(f"{path}.reason", "must be snake_case")
        return
    if kind == "declared":
        if "value" not in node:
            ctx.err(f"{path}.value", "required")
        if not _is_str(node.get("unit")):
            ctx.err(f"{path}.unit", "required")
        return
    if kind == "display_preset":
        if not _is_str(node.get("unit")):
            ctx.err(f"{path}.unit", "required")
        return
    if kind != "observed":
        ctx.err(f"{path}.kind", "unsupported kind")
        return
    _observed_fields(ctx, node, path, require_definition=require_definition)


def _observed_fields(
    ctx: _Ctx, node: dict[str, Any], path: str, *, require_definition: bool
) -> None:
    unit = node.get("unit")
    if not _is_str(unit):
        ctx.err(f"{path}.unit", "required on observed")
    if require_definition and not _is_str(node.get("definition_version")):
        ctx.err(f"{path}.definition_version", "required on profile")
    has_value = "value" in node
    has_values = "values" in node
    if unit == "profile":
        nested = _nested_observations(ctx, node, path)
        if require_definition and nested == 0 and not has_value and not has_values:
            ctx.err(path, "profile needs nested observations")
        return
    if not has_value and not has_values:
        ctx.err(f"{path}.value", "observed node needs value or values")
        return
    if unit == "ratio" and _is_num(node.get("value")):
        number = float(node["value"])
        if number < 0 or number > 1:
            ctx.err(f"{path}.value", "ratio must be 0.0..1.0")
    sample = node.get("sample_size")
    if sample is not None and not (_is_int(sample) and sample >= 0):
        ctx.err(f"{path}.sample_size", "must be integer >= 0")
    population = node.get("population")
    if (
        population is not None
        and sample is not None
        and _is_int(population)
        and _is_int(sample)
        and sample > population > 0
    ):
        ctx.err(f"{path}.sample_size", "sample_size exceeds population")


def _nested_observations(ctx: _Ctx, node: dict[str, Any], path: str) -> int:
    found = 0
    for key, value in node.items():
        if key in _PROFILE_SCALAR_KEYS:
            continue
        if isinstance(value, dict) and "kind" in value:
            found += 1
            _observation(ctx, value, f"{path}.{key}")
            continue
        if not isinstance(value, dict):
            continue
        for inner_key, inner in value.items():
            if isinstance(inner, dict) and "kind" in inner:
                found += 1
                _observation(ctx, inner, f"{path}.{key}.{inner_key}")
    return found


def _surface_values(ctx: _Ctx, node: Any, path: str) -> None:
    if not isinstance(node, dict) or node.get("kind") != "observed":
        return
    values = node.get("values")
    if not isinstance(values, dict):
        ctx.err(f"{path}.values", "required map")
        return
    for key in values:
        if key not in SURFACES:
            ctx.err(f"{path}.values.{key}", "unknown surface")
        if not _is_int(values[key]) or values[key] < 0:
            ctx.err(f"{path}.values.{key}", "must be integer >= 0")
    for name in SURFACES:
        if name not in values:
            ctx.err(f"{path}.values.{name}", "missing surface")


def _forbid(ctx: _Ctx, node: Any) -> None:
    for path in forbidden_key_hits(node):
        ctx.err(path, "forbidden verdict key")


def _scan_email(ctx: _Ctx, node: Any, path: str) -> None:
    if isinstance(node, str) and _EMAIL_RE.search(node):
        ctx.err(path, "raw email is not allowed")
    elif isinstance(node, dict):
        for key, value in node.items():
            _scan_email(ctx, value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _scan_email(ctx, value, f"{path}[{index}]")


def _public_join(ctx: _Ctx, join: Any) -> None:
    """F-01 declaration side: list-size and SHA-join counts stay separate keys."""
    if not isinstance(join, dict):
        ctx.err("$.attribution.public_join", "must be an object")
        return
    for key in ("matched", "unmatched", "ambiguous", "public_handle_actors"):
        if not isinstance(join.get(key), int):
            ctx.err(f"$.attribution.public_join.{key}", "must be an integer")
    fetched = join.get("fetched_login_count")
    if fetched is not None and not isinstance(fetched, int):
        ctx.err("$.attribution.public_join.fetched_login_count", "must be an integer or null")
    if not isinstance(join.get("commit_login_count"), int):
        ctx.err("$.attribution.public_join.commit_login_count", "must be an integer")
    if not _is_str(join.get("count_note")) or "not a commit-author join" not in str(
        join.get("count_note")
    ):
        ctx.err("$.attribution.public_join.count_note", "must state list size is not a join")


def validate_actor_card(card: Any) -> list[str]:
    ctx = _Ctx()
    if not isinstance(card, dict):
        return ["card must be an object"]
    _forbid(ctx, card)
    if card.get("schema_version") != ACTOR_CARD_SCHEMA_VERSION:
        ctx.err("$.schema_version", "must be actor-card-v1")
    if card.get("report_kind") != "actor_card":
        ctx.err("$.report_kind", "must be actor_card")
    if not _is_str(card.get("actor_id")) or not ACTOR_ID_RE.fullmatch(str(card.get("actor_id"))):
        ctx.err("$.actor_id", "invalid")
    if card.get("display_status") not in {
        "public_handle",
        "identity_alias",
        "git_author_name",
        "stable_hash",
        "actor_unknown",
    }:
        ctx.err("$.display_status", "invalid")
    identity_join = card.get("identity_join")
    if not isinstance(identity_join, dict):
        ctx.err("$.identity_join", "required object")
    else:
        if identity_join.get("identity_source") not in {
            "declared_identity_toml",
            "inferred_from_git",
        }:
            ctx.err("$.identity_join.identity_source", "invalid")
        basis = identity_join.get("join_basis")
        if basis not in {
            "identity_declared",
            "commit_sha_to_login",
            "identity_declared+commit_sha_to_login",
            "git_author_name_or_stable_hash",
            "unattributed",
        }:
            ctx.err("$.identity_join.join_basis", "invalid")
    _scan_email(ctx, card, "$")
    return ctx.errors


def validate_report_v2(report: Any) -> list[str]:
    ctx = _Ctx()
    if not isinstance(report, dict):
        return ["$: report must be an object"]
    _forbid(ctx, report)
    if report.get("schema_version") != REPORT_V2_SCHEMA_VERSION:
        ctx.err("$.schema_version", "must be report-v2")
    if report.get("report_kind") != "evidence":
        ctx.err("$.report_kind", "must be evidence")
    subject = report.get("subject")
    if not isinstance(subject, dict):
        ctx.err("$.subject", "required object")
    else:
        if subject.get("kind") not in SUBJECT_KINDS:
            ctx.err("$.subject.kind", "must be repo or actor")
        if subject.get("kind") == "actor":
            cid = subject.get("canonical_id")
            if not (
                _is_str(cid) and (ACTOR_ID_RE.fullmatch(cid) or CANONICAL_ID_RE.fullmatch(cid))
            ):
                ctx.err("$.subject.canonical_id", "invalid")
            if subject.get("selection") not in {"explicit_actor", "inferred_actor"}:
                ctx.err("$.subject.selection", "must be explicit_actor or inferred_actor")
            if "actor_id" in subject and subject.get("actor_id") != cid:
                ctx.err("$.subject.actor_id", "must equal canonical_id")
            if "attribution_state" in subject and subject.get("attribution_state") not in {
                "verified",
                "claimed",
                "inferred",
                "unresolved",
                "external",
                "bot",
            }:
                ctx.err("$.subject.attribution_state", "must use a registered identity state")
            if subject.get("selection") == "inferred_actor" and "attribution_state" in subject:
                ctx.err(
                    "$.subject.attribution_state",
                    "only an explicit identity selection may carry attribution_state",
                )
        elif subject.get("kind") == "repo" and subject.get("selection") != "repo_all_human":
            ctx.err("$.subject.selection", "must be repo_all_human")
    prov = report.get("provenance")
    if not isinstance(prov, dict):
        ctx.err("$.provenance", "required object")
    else:
        if prov.get("tool_name") != "grift":
            ctx.err("$.provenance.tool_name", "must be grift")
        if not (
            _is_str(prov.get("tool_version")) and _SEMVER_RE.match(str(prov.get("tool_version")))
        ):
            ctx.err("$.provenance.tool_version", "must be SEMVER")
        scope = prov.get("analysis_scope")
        if scope not in {"repo", "tenant", "actor_cluster"}:
            ctx.err(
                "$.provenance.analysis_scope",
                "must be repo, tenant, or actor_cluster",
            )
        sha = prov.get("analyzed_commit_sha")
        if not (_is_str(sha) and _GENERIC_SHA_RE.fullmatch(sha)):
            ctx.err("$.provenance.analyzed_commit_sha", "must be a 40/64-char Git OID")
        target_oid = prov.get("target_oid")
        if target_oid is not None:
            if not isinstance(target_oid, dict):
                ctx.err("$.provenance.target_oid", "must be an object")
            else:
                algorithm = target_oid.get("algorithm")
                value = target_oid.get("value")
                expected = 40 if algorithm == "sha1" else 64 if algorithm == "sha256" else 0
                if expected == 0:
                    ctx.err("$.provenance.target_oid.algorithm", "must be sha1 or sha256")
                if not (
                    _is_str(value) and len(value) == expected and re.fullmatch(r"[0-9a-f]+", value)
                ):
                    ctx.err("$.provenance.target_oid.value", "length must match object algorithm")
        completeness = prov.get("revision_completeness")
        if completeness is not None:
            if not isinstance(completeness, dict) or set(completeness) != {
                "shallow",
                "promisor",
                "complete",
            }:
                ctx.err(
                    "$.provenance.revision_completeness",
                    "must contain exactly shallow/promisor/complete",
                )
            elif any(not isinstance(completeness.get(key), bool) for key in completeness):
                ctx.err("$.provenance.revision_completeness", "values must be booleans")
            elif completeness["complete"] != (
                not completeness["shallow"] and not completeness["promisor"]
            ):
                ctx.err("$.provenance.revision_completeness.complete", "inconsistent")
        if not (_is_str(prov.get("analyzed_at")) and _TS_RE.match(str(prov.get("analyzed_at")))):
            ctx.err("$.provenance.analyzed_at", "must be UTC timestamp")
        if not (
            _is_str(prov.get("observation_date"))
            and _DATE_RE.match(str(prov.get("observation_date")))
        ):
            ctx.err("$.provenance.observation_date", "must be YYYY-MM-DD")
        if prov.get("window_basis") not in WINDOW_BASIS:
            ctx.err("$.provenance.window_basis", "invalid")
        digest = prov.get("identity_digest")
        if digest is not None and not (_is_str(digest) and len(digest) == 64):
            ctx.err("$.provenance.identity_digest", "must be 64-hex or null")
        digests = prov.get("input_digests")
        if not isinstance(digests, dict):
            ctx.err("$.provenance.input_digests", "required object")
        else:
            tagset_digest = prov.get("tagset_digest")
            input_tagset = digests.get("tagset")
            if not (_is_str(tagset_digest) and re.fullmatch(r"[0-9a-f]{64}", str(tagset_digest))):
                ctx.err(
                    "$.provenance.tagset_digest",
                    "must be a lowercase SHA-256 string",
                )
            elif input_tagset != tagset_digest:
                ctx.err(
                    "$.provenance.input_digests.tagset",
                    "must equal provenance.tagset_digest",
                )
        provenance_extra = set(prov) - _REPORT_V2_PROVENANCE_KEYS
        if provenance_extra:
            ctx.err(
                "$.provenance",
                "unknown keys " + ",".join(sorted(provenance_extra)),
            )
    for key, expected_version in _PROFILE_VERSIONS.items():
        node = report.get(key)
        _observation(ctx, node, f"$.{key}", require_definition=True)
        if isinstance(node, dict) and node.get("kind") == "observed":
            version = node.get("definition_version")
            if version and version != expected_version:
                ctx.err(f"$.{key}.definition_version", f"must be {expected_version}")
    surface = report.get("surface_profile")
    if isinstance(surface, dict) and surface.get("kind") == "observed":
        _surface_values(
            ctx, surface.get("surface_commit_counts"), "$.surface_profile.surface_commit_counts"
        )
        share = surface.get("surface_commit_share")
        if isinstance(share, dict) and share.get("kind") == "observed":
            values = share.get("values") or {}
            for name, number in values.items():
                if _is_num(number) and (float(number) < 0 or float(number) > 1):
                    ctx.err(f"$.surface_profile.surface_commit_share.values.{name}", "ratio 0..1")
    coverage = report.get("input_coverage")
    if not isinstance(coverage, dict):
        ctx.err("$.input_coverage", "required object")
    else:
        for name in ("git", "forge", "tracker"):
            _observation(ctx, coverage.get(name), f"$.input_coverage.{name}")
    lens = report.get("role_lens")
    if lens is not None:
        if not isinstance(lens, dict):
            ctx.err("$.role_lens", "must be object or null")
        elif lens.get("name") not in ROLE_LENSES:
            ctx.err("$.role_lens.name", "unknown lens")
        elif lens.get("classifies_role") is True:
            ctx.err("$.role_lens.classifies_role", "must be false")
    if subject and subject.get("kind") == "actor":
        scope = prov.get("analysis_scope") if isinstance(prov, dict) else None
        expected_scope = actor_analysis_scope(
            subject.get("selection"),
            subject.get("attribution_state"),
        )
        if scope != expected_scope:
            ctx.err(
                "$.provenance.analysis_scope",
                f"must be {expected_scope} for this actor basis",
            )
        if subject.get("selection") == "inferred_actor" and isinstance(prov, dict):
            if prov.get("identity_digest") is not None:
                ctx.err(
                    "$.provenance.identity_digest",
                    "inferred actor selector is not an identity input and must be null",
                )
        activity = report.get("activity")
        if expected_scope == "actor_cluster":
            if not isinstance(activity, dict):
                ctx.err("$.activity", "required actor_cluster activity object")
            else:
                if activity.get("scope") != "actor_cluster":
                    ctx.err("$.activity.scope", "must be actor_cluster")
                if activity.get("population") != "repo_local_git_primary_author_cluster":
                    ctx.err(
                        "$.activity.population",
                        "must be repo_local_git_primary_author_cluster",
                    )
                if activity.get("tenant_commits") is not None:
                    ctx.err("$.activity.tenant_commits", "must be null for actor_cluster")
                _observation(
                    ctx,
                    activity.get("actor_cluster_commits"),
                    "$.activity.actor_cluster_commits",
                )
            for key in ("experience", "role_profile"):
                node = report.get(key)
                if not isinstance(node, dict) or node.get("kind") != "not_observed":
                    ctx.err(f"$.{key}", "actor_cluster requires not_observed")
        elif not isinstance(activity, dict):
            ctx.err("$.activity", "required tenant activity object")
        else:
            if activity.get("scope") != "tenant":
                ctx.err("$.activity.scope", "must be tenant")
            if activity.get("population") != "explicit_identity_nonmerge":
                ctx.err("$.activity.population", "must be explicit_identity_nonmerge")
            _observation(ctx, activity.get("tenant_commits"), "$.activity.tenant_commits")
            if "actor_cluster_commits" in activity:
                ctx.err(
                    "$.activity.actor_cluster_commits",
                    "tenant scope must not carry actor_cluster population",
                )
        if "interpretation" in report:
            ctx.err("$.interpretation", "actor view must not include repo reference interpretation")
        if report.get("role_validation") or report.get("role_ground_truth"):
            ctx.err("$.role_validation", "actor view must not include role sample validation")
        for key in ("identity", "subject", "notices", "limitations", "role_lens"):
            _scan_email(ctx, report.get(key), f"$.{key}")
    reference = report.get("reference")
    if reference is not None:
        _forbid(ctx, reference)
    if subject and subject.get("kind") == "repo":
        if isinstance(prov, dict) and prov.get("analysis_scope") != "repo":
            ctx.err("$.provenance.analysis_scope", "repo subject requires repo scope")
        directory = report.get("actor_directory")
        if not isinstance(directory, dict) or "observed_count" not in directory:
            ctx.err("$.actor_directory", "required")
        elif not isinstance(directory.get("actors"), list):
            ctx.err("$.actor_directory.actors", "must be an array")
        else:
            attr = directory.get("attribution") or report.get("attribution") or {}
            resolved = (
                (report.get("context_profile") or {}).get("resolved_human_actors") or {}
            ).get("value")
            if (
                resolved is not None
                and directory.get("observed_count") != resolved
                and directory.get("observed_count") != attr.get("observed_actor_count")
            ):
                ctx.err("$.actor_directory.observed_count", "must match attribution actor count")
            join = attr.get("public_join")
            if join is not None:
                _public_join(ctx, join)
    extra = set(report) - _REPORT_V2_KEYS
    if extra:
        ctx.err("$", "unknown keys " + ",".join(sorted(extra)))
    # Legacy actor-card adapters intentionally expose a report-v2-compatible
    # projection without the strict population envelope.  New CLI producers
    # always carry all four keys and must pass the closed Draft 2020-12 schema.
    strict_envelope = {"target", "population", "window", "metrics"}
    if strict_envelope.issubset(report):
        ctx.errors.extend(validate_schema("report-v2", report))
    return ctx.errors


def validate_project(report: Any) -> list[str]:
    ctx = _Ctx()
    if not isinstance(report, dict):
        return ["$: project must be an object"]
    _forbid(ctx, report)
    if report.get("schema_version") != PROJECT_SCHEMA_VERSION:
        ctx.err("$.schema_version", "must be project-v1")
    if report.get("report_kind") != "project":
        ctx.err("$.report_kind", "must be project")
    declared = report.get("declared")
    if not isinstance(declared, dict):
        ctx.err("$.declared", "required")
    else:
        for key in ("change_rhythm", "surfaces", "verification", "inputs"):
            if key not in declared:
                ctx.err(f"$.declared.{key}", "required")
        for key in ("project_id", "title", "surfaces", "verification", "inputs", "role_lens"):
            node = declared.get(key)
            if isinstance(node, dict) and "kind" in node:
                _observation(ctx, node, f"$.declared.{key}")
        rhythm = declared.get("change_rhythm")
        if isinstance(rhythm, dict):
            for key, value in rhythm.items():
                if isinstance(value, dict) and "kind" in value:
                    _observation(ctx, value, f"$.declared.change_rhythm.{key}")
    observed = report.get("observed")
    if observed is None:
        return ctx.errors
    if not isinstance(observed, dict):
        ctx.err("$.observed", "must be object or omitted")
        return ctx.errors
    _observation(
        ctx,
        observed,
        "$.observed",
        require_definition=observed.get("kind") == "observed",
    )
    return ctx.errors


def validate_alignment(report: Any) -> list[str]:
    ctx = _Ctx()
    if not isinstance(report, dict):
        return ["$: alignment must be an object"]
    _forbid(ctx, report)
    if report.get("schema_version") != ALIGNMENT_SCHEMA_VERSION:
        ctx.err("$.schema_version", "must be alignment-v1")
    if report.get("report_kind") != "alignment":
        ctx.err("$.report_kind", "must be alignment")
    subject = report.get("subject")
    if not isinstance(subject, dict):
        ctx.err("$.subject", "required object")
    else:
        allowed_subject_keys = {
            "kind",
            "actor_canonical_id",
            "actor_selection",
            "actor_attribution_state",
            "project_id",
            "mode",
        }
        unknown_subject_keys = sorted(set(subject) - allowed_subject_keys)
        if unknown_subject_keys:
            ctx.err("$.subject", "unknown keys " + ",".join(unknown_subject_keys))
        for key in ("kind", "actor_canonical_id", "actor_selection", "project_id"):
            if key not in subject:
                ctx.err(f"$.subject.{key}", "required")
        if subject.get("kind") != "alignment":
            ctx.err("$.subject.kind", "must be alignment")
        actor_id = subject.get("actor_canonical_id")
        if not (_is_str(actor_id) and CANONICAL_ID_RE.fullmatch(actor_id)):
            ctx.err("$.subject.actor_canonical_id", "invalid")
        selection = subject.get("actor_selection")
        if selection not in {"explicit_actor", "inferred_actor"}:
            ctx.err(
                "$.subject.actor_selection",
                "must be explicit_actor or inferred_actor",
            )
        state = subject.get("actor_attribution_state")
        if "actor_attribution_state" in subject and state not in ATTRIBUTION_STATES:
            ctx.err(
                "$.subject.actor_attribution_state",
                "must use a registered identity state",
            )
        if selection == "inferred_actor" and "actor_attribution_state" in subject:
            ctx.err(
                "$.subject.actor_attribution_state",
                "inferred_actor must not carry an attribution state",
            )
        project_id = subject.get("project_id")
        if project_id is not None and not (_is_str(project_id) and project_id.strip()):
            ctx.err("$.subject.project_id", "must be a non-empty string or null")
        if "mode" in subject and not (
            _is_str(subject.get("mode")) and str(subject.get("mode")).strip()
        ):
            ctx.err("$.subject.mode", "must be a non-empty string")
        expected_actor_scope = actor_analysis_scope(selection, state)
        for provenance_key in ("provenance", "actor_provenance"):
            provenance = report.get(provenance_key)
            if (
                isinstance(provenance, dict)
                and provenance.get("analysis_scope") != expected_actor_scope
            ):
                ctx.err(
                    f"$.{provenance_key}.analysis_scope",
                    f"must be {expected_actor_scope} for this actor basis",
                )
    axes = report.get("axes")
    if not isinstance(axes, list) or not axes:
        ctx.err("$.axes", "must be a non-empty array")
        return ctx.errors
    for index, axis in enumerate(axes):
        path = f"$.axes[{index}]"
        if not isinstance(axis, dict):
            ctx.err(path, "must be an object")
            continue
        if axis.get("comparison") not in COMPARISONS:
            ctx.err(f"{path}.comparison", "invalid")
        for key in (
            "declared",
            "observed",
            "evidence_paths",
            "limitations",
            "axis",
            "actor_observed",
            "project_observed",
            "project_declared",
            "actor_n",
            "project_n",
            "actor_denominator",
            "project_denominator",
            "actor_source",
            "project_source",
            "actor_basis",
            "project_basis",
            "actor_tendency",
            "project_tendency",
            "relationship",
            "coverage",
            "incomparable_reason",
            "actor_window",
            "project_window",
            "definition_version",
        ):
            if key not in axis:
                ctx.err(f"{path}.{key}", "required")
        declared = axis.get("declared")
        observed = axis.get("observed")
        if isinstance(declared, dict):
            _observation(ctx, declared, f"{path}.declared")
        if isinstance(observed, dict):
            _observation(ctx, observed, f"{path}.observed")
        for node_key in ("actor_observed", "project_observed", "project_declared"):
            node = axis.get(node_key)
            if isinstance(node, dict) and node.get("kind"):
                _observation(ctx, node, f"{path}.{node_key}")
        _alignment_axis_types(ctx, axis, path)
    for extra in (
        "actor_observed",
        "project_observed",
        "project_declared",
        "actor_provenance",
        "project_provenance",
        "actor_report_digest",
        "project_report_digest",
    ):
        if extra not in report:
            ctx.err(f"$.{extra}", "required")
    return ctx.errors


def _alignment_axis_types(ctx: _Ctx, axis: dict[str, Any], path: str) -> None:
    from tep_core.v2_constants import CONFIDENCE_LEVELS, FORBIDDEN_UNITS, RELATIONSHIPS

    for n_key in ("actor_n", "project_n"):
        value = axis.get(n_key)
        if value is not None and not (_is_int(value) and value >= 0):
            ctx.err(f"{path}.{n_key}", "must be integer >= 0 or null")
    for src_key in ("actor_source", "project_source"):
        if not isinstance(axis.get(src_key), list):
            ctx.err(f"{path}.{src_key}", "must be an array")
    for node_key in ("actor_observed", "project_observed", "project_declared"):
        unit = (
            (axis.get(node_key) or {}).get("unit") if isinstance(axis.get(node_key), dict) else None
        )
        if isinstance(unit, str) and unit in FORBIDDEN_UNITS:
            ctx.err(f"{path}.{node_key}.unit", "invalid")
    relationship = axis.get("relationship")
    if isinstance(relationship, dict):
        kind = relationship.get("kind")
        if kind not in RELATIONSHIPS:
            ctx.err(f"{path}.relationship.kind", "invalid")
        conf = relationship.get("confidence")
        if conf is not None and conf not in CONFIDENCE_LEVELS:
            ctx.err(f"{path}.relationship.confidence", "invalid")
    coverage = axis.get("coverage")
    if isinstance(coverage, dict) and coverage.get("status") not in {"present", "partial", None}:
        ctx.err(f"{path}.coverage.status", "invalid")
    for tend_key in ("actor_tendency", "project_tendency"):
        node = axis.get(tend_key)
        if not isinstance(node, dict):
            continue
        if node.get("kind") not in {"directional", "not_proven", "not_observed", "not_comparable"}:
            ctx.err(f"{path}.{tend_key}.kind", "invalid")
        conf = node.get("confidence")
        if conf is not None and conf not in CONFIDENCE_LEVELS:
            ctx.err(f"{path}.{tend_key}.confidence", "invalid")
