"""Privacy-profiled ``tep-contribution-v2`` payload construction.

The public payload and the controlled provenance sidecar are deliberately
different artifacts.  Public profiles cannot carry a repository fingerprint;
controlled profiles retain enough source context for reproducible research
without putting the HMAC key in either artifact.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

from tep_core.secrets_guard import HIGH_CONFIDENCE_CREDENTIAL_RE, artifact_leaks

CONTRIBUTION_V2 = "tep-contribution-v2"
CONTROLLED_SIDECAR_V1 = "tep-controlled-sidecar-v1"
# Purpose binding, v0.7.
#
# Until v0.6 a submission carried one fixed purpose, which meant the project --
# not the person submitting -- decided what their data was for. Widening that to
# "any purpose" would have removed the binding; instead the submitter chooses
# from an enumerated set at submission time and the choice is recorded in the
# payload. The recipient is bound to the recorded purpose, so the binding is
# per-submission and strictly narrower than a blanket licence.
#
# The set is closed on purpose. Adding an entry is a norms change, and
# `test_v070_norms_link` fails until docs/norms.md and docs/en/norms.md carry
# the same id and wording.
PURPOSES: dict[str, str] = {
    "reference-distributions": "TEP Report 集計と参照分布 vNext",
    "outcome-linkage": "提出者が選択した成果連携の検証",
}

# What a submission means when it says nothing: the v0.6 behaviour, unchanged.
PURPOSE = PURPOSES["reference-distributions"]


def resolve_purpose(purpose: str | None) -> str:
    """The recorded purpose for a submission, or a refusal naming the choices."""
    if purpose is None:
        return PURPOSE
    if purpose in PURPOSES:
        return PURPOSES[purpose]
    if purpose in PURPOSES.values():
        return purpose
    raise ValueError(
        f"unknown contribution purpose {purpose!r}; declared purposes are: "
        + ", ".join(sorted(PURPOSES))
    )

PUBLIC_PROFILES = frozenset({"aggregate", "named-public"})
CONTROLLED_PROFILES = frozenset({"masked", "raw"})
_MAX_PERCENT_DECODE_PASSES = 16
_MAX_PSEUDONYM_KEY_BYTES = 4096
_ACTOR_IDENTIFIER_FIELDS = frozenset(
    {
        "actor_canonical_id",
        "actor_id",
        "actor_ids",
        "canonical_id",
        "internal_actor_id",
        "resolution_seed",
        "source_actor_id",
        "subject_actor_id",
    }
)
PROFILES = PUBLIC_PROFILES | CONTROLLED_PROFILES
DOORS = frozenset({"local", "controlled", "public-pr"})
# Which doors each purpose can actually reach today.
#
# The public intake repository validates `purpose` against its own schema, and
# that schema is a separate enforcement point in a separate repository. When
# v0.7.0 widened the purpose set, the intake still pinned the single v0.6.0
# value, so a payload built with `outcome-linkage` and sent through `public-pr`
# would be built, disclosed, confirmed by the submitter -- and then bounced.
#
# Refusing here spends the submitter's time instead of the reviewer's, and says
# why. This is a statement about the intake as it stands, not about the norms:
# `outcome-linkage` is a legitimate purpose and works through `local`. Widen
# this the day the intake schema accepts it; `test_v070_intake_contract` reads
# the sibling repository when it is present and fails if the two disagree.
PURPOSE_DOORS = {
    "reference-distributions": frozenset({"local", "controlled", "public-pr"}),
    "outcome-linkage": frozenset({"local", "controlled"}),
}

PUBLIC_INTAKE_UNSUPPORTED_PURPOSE = (
    "purpose {purpose!r} cannot use door {door!r}: the public intake schema "
    "accepts only {accepted}. Build it with --door local, or submit under a "
    "purpose the intake accepts."
)

PROFILE_DOORS = {
    "aggregate": frozenset({"local", "public-pr"}),
    "named-public": frozenset({"local", "public-pr"}),
    "masked": frozenset({"local", "controlled"}),
    "raw": frozenset({"local", "controlled"}),
}

_SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_RECEIPT_RE = re.compile(r"^receipt_[a-z2-7]{26}$")
_PID_RE = re.compile(r"^pa_[a-z2-7]{26}$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_PATH_RE = re.compile(r"^[^/@\s][^@\s]*/[^/@\s][^@\s]*$")
_PUBLIC_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PUBLIC_HANDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PUBLIC_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")
# Public account linkage is provider-specific evidence, not a generic login
# assertion.  GitHub documents the stable top-level commit ``author.id``;
# GitLab's commits API does not document an equivalent account binding.  Keep
# the table explicit so another provider can be enabled only with a registered
# primary-evidence basis and matching receiver contract.
_PUBLIC_ACCOUNT_EVIDENCE_BY_PROVIDER = {
    "github": frozenset({"commit.author.id"}),
    "gitlab": frozenset(),
}
_PUBLIC_ACCOUNT_COVERAGE = frozenset({"complete", "partial"})
_NAMED_AUTHORITY_BASIS = "account_holder_explicit"
_NAMED_AUTHORITY_SCOPE = "project_and_account"
_NAMED_AUTHORITY_ASSERTION = "authorized_for_public_research_contribution"
_CONTROLLED_AUTHORITY = frozenset({"repository-owner-authorization"})
_CONTROLLED_CONSENT = frozenset({"recorded-explicit-consent"})
_CONTROLLED_WITHDRAWAL = frozenset({"contact-controller-before-publication"})
_CONTROLLED_ACCESS_CLASS = frozenset({"named-research-team"})
_CONTROLLED_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_RETENTION_RE = re.compile(r"^until-\d{4}-\d{2}-\d{2}$")
_EXACT_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)
_MEASUREMENT_SECTIONS = (
    "activity",
    "attribution",
    "context_profile",
    "surface_profile",
    "change_rhythm",
    "verification_profile",
    "coordination_profile",
    "event_observation",
    "event_rhythm",
    "tracker_lifecycle",
    "role_lens",
    "experience",
    "role_profile",
)
_SENSITIVE_KEYS = frozenset(
    {
        "actor",
        "actors",
        "actor_id",
        "actor_pid",
        "internal_actor_id",
        "canonical_id",
        "canonical_emails",
        "identity",
        "email",
        "emails",
        "name",
        "display_name",
        "repository",
        "repo",
        "remote",
        "project",
        "project_id",
        "project_path",
        "path",
        "paths",
        "url",
        "profile_url",
        "host",
        "provider",
        "account",
        "account_id",
        "author",
        "author_email",
        "author_name",
        "correspondence",
        "github_login",
        "gitlab_login",
        "login",
        "handle",
        "owner",
        "principal",
        "resolution_seed",
        "subject",
        "subject_id",
        "user",
        "username",
        "oid",
        "sha",
        "digest",
        "timestamp",
        "date",
        "window_start",
        "window_end",
        "source",
    }
)
_SENSITIVE_SUFFIXES = (
    "_actor_id",
    "_canonical_id",
    "_email",
    "_emails",
    "_remote",
    "_project_id",
    "_project_path",
    "_url",
    "_oid",
    "_sha",
    "_digest",
    "_timestamp",
    "_date",
)
_AGGREGATE_TEXT_VALUES = {
    "kind": frozenset(
        {
            "declared",
            "directional",
            "display_preset",
            "mixed",
            "not_comparable",
            "not_declared",
            "not_observed",
            "not_proven",
            "observed",
            "suppressed",
        }
    ),
    "unit": frozenset(
        {
            "boolean",
            "commit-pairs",
            "commit_share",
            "commits",
            "coverage_status",
            "date-range",
            "days",
            "dimensionless",
            "events",
            "file-changes",
            "files",
            "hours",
            "input",
            "label",
            "lens",
            "lines",
            "month-range",
            "path_touch_share",
            "profile",
            "ratio",
            "surface",
            "target_commits",
            "utc_date_range",
            "verification-type",
        }
    ),
    "classification_basis": frozenset({"path_pattern_and_extension_heuristic"}),
    "status": frozenset(
        {
            "complete",
            "insufficient_population",
            "not_available",
            "not_observed",
            "not_proven",
            "partial",
            "unknown",
            "unsupported",
        }
    ),
    "window_basis": frozenset({"explicit_as_of", "fixed_oid", "legacy_head_date"}),
    "analysis_scope": frozenset({"repo"}),
    "fixture_kind": frozenset({"synthetic_contract"}),
}

# Public aggregate field names are a closed producer contract.  Unknown keys
# are omitted and represented only by a generic suppression marker; otherwise
# a repository codename can leak merely by being used as a JSON property name.
_AGGREGATE_FIELD_KEYS = frozenset(
    {
        "account_conflict_count",
        "active_days",
        "active_days_13w",
        "active_days_180d",
        "active_span_days",
        "actor_turnover",
        "ambiguous",
        "ambiguous_count",
        "analysis_scope",
        "attributed_commit_count",
        "attribution_coverage",
        "attribution_human_including_merges",
        "attribution_unresolved_commit_count",
        "backend",
        "bot",
        "bot_count",
        "burst_share_le_2d",
        "classification_basis",
        "coauthored_count",
        "collaboration_class",
        "commit_count",
        "commit_login_count",
        "commits_per_active_day",
        "commits_per_active_day_median",
        "conventional_commit_share",
        "count",
        "cross_surface_cochange",
        "days_since_last_human_commit",
        "dependency_manifests",
        "docs_share",
        "event_count",
        "fetched_login_count",
        "first_commit",
        "fix_with_test_pairing",
        "git",
        "history_outside_window_commit_count",
        "human_commit_count",
        "human_commits",
        "interval_sample_size",
        "issue_link_count",
        "issue_link_density",
        "issue_link_share",
        "kind",
        "language_composition",
        "last_commit",
        "lifecycle_stage",
        "long_gap_share_ge_30d",
        "mailmap_present",
        "matched",
        "median_gap_days",
        "merge_commit_count",
        "merge_count",
        "merge_share",
        "module_breadth",
        "monorepo_markers",
        "n",
        "narrate_rate",
        "numerator",
        "denominator",
        "observation_date",
        "observed_actor_count",
        "origin_unresolved_commit_count",
        "p90_gap_days",
        "platform",
        "population",
        "provided",
        "pr_flow_share",
        "public_handle_actors",
        "public_join",
        "reason",
        "release_cadence",
        "repo_active_days",
        "repo_age_days",
        "repo_commits",
        "repo_human_nonmerge_commits",
        "resolved_human_actors",
        "review",
        "sample_size",
        "scale",
        "scope",
        "status",
        "surface_commit_counts",
        "surface_commit_share",
        "surface_file_counts",
        "surface_file_share",
        "surface_line_counts",
        "surface_line_share",
        "surface_pair_counts",
        "surface_pair_share",
        "test_file_ratio",
        "test_only_commit_count",
        "test_touch_count",
        "test_touch_share",
        "test_type_distribution",
        "timestamp_basis",
        "top_actor_share",
        "top_level_dirs",
        "top_module_share",
        "tracker",
        "unclassified_count",
        "unit",
        "unmatched",
        "unresolved_commit_count",
        "unspecified",
        "value",
        "values",
        "window_basis",
        "window_days",
        "window_population",
        "with_test_count",
        "without_test_count",
        "fixture_kind",
    }
)
_AGGREGATE_VALUE_LABELS = frozenset(
    {
        "backend",
        "ci_cd",
        "config",
        "contract",
        "data",
        "docs",
        "e2e",
        "frontend",
        "generated_vendor",
        "infra",
        "integration",
        "observability",
        "other",
        "platform",
        "test",
        "unit",
        "unspecified",
    }
)
_AGGREGATE_REASONS = frozenset(
    {
        "card_coordination_not_computed",
        "card_rhythm_not_computed",
        "card_surface_not_computed",
        "card_verification_not_computed",
        "consenting_actor_required",
        "coverage_absent",
        "distribution_not_bundled",
        "event_window_not_provided",
        "fewer_than_two_releases",
        "forge_export_not_provided",
        "history_incomplete",
        "insufficient_population",
        "mixed_repository_collection",
        "no_declared_ai_commits",
        "no_events",
        "numstat_unavailable",
        "partial_hour_coverage",
        "public_evidence_not_provided",
        "reference_too_small",
        "source_hour_coverage_unspecified",
        "synthetic_contract_not_actor_evidence",
        "timestamp_absent",
        "tracker_export_not_provided",
        "tracker_timestamps_missing",
        "unregistered_reason",
        "unregistered_source",
        "unregistered_text",
        "unspecified",
        "windows_not_equivalent",
    }
)
_AGGREGATE_COVERAGE_SOURCES = frozenset(
    {
        "event_window",
        "forge",
        "forge_tracker_window_alignment",
        "git",
        "git_window",
        "public_forge",
        "report",
        "tracker",
        "tracker_window",
        "window_alignment",
    }
)
_COUNT_BUCKETS = frozenset({"0", "1-4", "5-19", "20-99", "100-499", "500-1999", "2000+"})
_RATIO_BUCKET_RE = re.compile(
    r"^(?:00-10|10-20|20-30|30-40|40-50|50-60|60-70|70-80|80-90|90-100)%$"
)
_CREDENTIAL_WORDS = frozenset(
    {
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "csrf",
        "jwt",
        "pat",
        "passcode",
        "passphrase",
        "passwd",
        "password",
        "pwd",
        "secret",
        "token",
    }
)
_CREDENTIAL_COMPOUNDS = frozenset(
    {
        "accesskey",
        "apikey",
        "authkey",
        "clientsecret",
        "keymaterial",
        "privatekey",
        "privatepassword",
        "privatetoken",
        "secretkey",
    }
)
_NETWORK_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_SCP_REMOTE_RE = re.compile(r"^(?P<userinfo>[^@/\s]+)@(?P<host>\[[^\]]+\]|[^:/\s]+):(?P<path>.+)$")
_EMBEDDED_NETWORK_URL_RE = re.compile(r"(?:(?:https?|ssh|git)://|//)[^\s<>\"']+")
_EMBEDDED_SCP_REMOTE_RE = re.compile(r"(?:^|[\s=])[^@/\s]+@(?:\[[^\]]+\]|[^:/\s]+):[^\s<>\"']+")
_SAFE_RAW_QUERY_FIELDS = frozenset(
    {
        "order",
        "page",
        "pagination",
        "per_page",
        "ref",
        "ref_name",
        "sha",
        "since",
        "sort",
        "until",
    }
)
_AUTHORIZATION_VALUE_RE = re.compile(
    r"(?i)(?:^|\s)(?:authorization\s*:\s*)?(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+"
)
_CREDENTIAL_HEADER_VALUE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Za-z0-9_-]*(?:authorization|authentication|cookie|"
    r"credential|csrf|passcode|passphrase|password|passwd|pwd|secret|session|token|"
    r"api[-_]?key)[A-Za-z0-9_-]*|auth[-_]?code|(?:x[-_]?)?auth)"
    r"['\"]?\s*[:=]\s*['\"]?\S+"
)
_CREDENTIAL_SPACE_VALUE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:auth[-_ ]?code|passcode|passphrase|password|passwd|pwd|"
    r"secret[-_ ]?access[-_ ]?key)\s+(?:is\s+)?\S+"
)
_PRIVATE_KEY_VALUE_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
# Single source: tep_core.secrets_guard owns the provider credential formats.
_HIGH_CONFIDENCE_TOKEN_RE = HIGH_CONFIDENCE_CREDENTIAL_RE
_GOVERNANCE_REQUIRED = (
    "controller",
    "authority",
    "consent",
    "study_id",
    "retention",
    "withdrawal",
    "access_class",
)

_AGGREGATE_TRANSFORMATION_SPEC = {
    "id": "tep-contribution-aggregate-exact-population-v2",
    "measurement_sections": sorted(_MEASUREMENT_SECTIONS),
    "field_allowlist": sorted(_AGGREGATE_FIELD_KEYS),
    "text_allowlist": {
        key: sorted(values) for key, values in sorted(_AGGREGATE_TEXT_VALUES.items())
    },
    "reason_allowlist": sorted(_AGGREGATE_REASONS),
    "value_label_allowlist": sorted(_AGGREGATE_VALUE_LABELS),
    "coverage_source_allowlist": sorted(_AGGREGATE_COVERAGE_SOURCES),
    "count_buckets": sorted(_COUNT_BUCKETS),
    "ratio_bucket_width": 0.1,
    "population": ["n", "denominator"],
    "drops": [
        "actor rows and identifiers",
        "repository and remote identifiers",
        "Git object identifiers",
        "exact timestamps",
        "source and artifact digests",
        "unregistered fields and free-form text",
    ],
}
_TRANSFORMATION_SPECS = {
    "aggregate": _AGGREGATE_TRANSFORMATION_SPEC,
    "named-public": {
        "id": "tep-contribution-named-public-v2",
        "shared_public_observation_spec": _AGGREGATE_TRANSFORMATION_SPEC,
        "authority": {
            "basis": _NAMED_AUTHORITY_BASIS,
            "scope": _NAMED_AUTHORITY_SCOPE,
            "assertion": _NAMED_AUTHORITY_ASSERTION,
            "binding": ["provider", "host", "project_id", "account_id"],
        },
        "account_evidence_by_provider": {
            provider: sorted(bases)
            for provider, bases in sorted(_PUBLIC_ACCOUNT_EVIDENCE_BY_PROVIDER.items())
        },
        "coverage_statuses": sorted(_PUBLIC_ACCOUNT_COVERAGE),
        "actor_measurements": [
            "linked_commit_count_bucket",
            "actor_commit_count_bucket",
            "linkage_coverage_bucket",
            "commit_count_basis",
        ],
    },
    "masked": {
        "id": "tep-contribution-masked-precise-v2",
        "pseudonym": "repo-scoped-hmac-sha256-128",
        "measurement_sections": sorted(_MEASUREMENT_SECTIONS),
        "field_allowlist": sorted(_AGGREGATE_FIELD_KEYS),
        "text_allowlist": {
            key: sorted(values) for key, values in sorted(_AGGREGATE_TEXT_VALUES.items())
        },
        "precision": "finite numbers and schema-valid experience/role structures retained",
        "population": ["n", "denominator", "basis"],
        "source_replay": "source-report-plus-key-and-controlled-sidecar",
        "sidecar_correspondence": ["actor_pid", "source_actor_field", "source_actor_id"],
    },
    "raw": {
        "id": "tep-contribution-raw-controlled-v2",
        "payload": "explicit raw_material retained once in controlled payload",
        "credential_filter": "recursive credential rejection with closed safe query allowlist",
        "safe_query_fields": sorted(_SAFE_RAW_QUERY_FIELDS),
        "source_replay": "controlled-sidecar",
    },
}


def _transformation_spec_digest(spec: Mapping[str, Any]) -> str:
    encoded = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


TRANSFORMATION_SPEC_DIGESTS = {
    profile: _transformation_spec_digest(spec) for profile, spec in _TRANSFORMATION_SPECS.items()
}
# Backward-compatible aggregate alias for callers which imported the former
# single digest.  Validation is profile-specific through the mapping above.
TRANSFORMATION_SPEC_DIGEST = TRANSFORMATION_SPEC_DIGESTS["aggregate"]
SOURCE_REPLAY_BY_PROFILE = {
    "aggregate": "unavailable_from_public_payload",
    "named-public": "public_api_recollect_required",
    "masked": "controlled_sidecar_available",
    "raw": "controlled_sidecar_available",
}


@dataclass(frozen=True)
class ContributionBundle:
    """A payload plus its optional non-public provenance sidecar."""

    payload: dict[str, Any]
    controlled_sidecar: dict[str, Any] | None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _opaque(prefix: str, raw: bytes) -> str:
    return prefix + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def new_receipt_id() -> str:
    return _opaque("receipt_", secrets.token_bytes(16))


def _count_bucket(value: int | float) -> str:
    number = max(0, int(value))
    if number == 0:
        return "0"
    if number < 5:
        return "1-4"
    if number < 20:
        return "5-19"
    if number < 100:
        return "20-99"
    if number < 500:
        return "100-499"
    if number < 2000:
        return "500-1999"
    return "2000+"


def _ratio_bucket(value: int | float) -> str:
    number = min(1.0, max(0.0, float(value)))
    lower = min(90, int(number * 10) * 10)
    if number >= 1.0:
        lower = 90
    return f"{lower:02d}-{lower + 10:02d}%"


def _key_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_KEYS or lowered.endswith(_SENSITIVE_SUFFIXES)


def _safe_text(key: str, value: str) -> str | None:
    text = value.strip()
    allowed = _AGGREGATE_TEXT_VALUES.get(key)
    if allowed is None or text not in allowed:
        return None
    return text


def _safe_reason(value: Any) -> str:
    if isinstance(value, str) and value in _AGGREGATE_REASONS:
        return value
    return "unregistered_reason"


def _bucket_observations(value: Any, *, parent_unit: str | None = None) -> Any:
    """Keep only bucketed observation structure, never source identifiers."""

    if not isinstance(value, dict):
        return None
    unit = value.get("unit") if isinstance(value.get("unit"), str) else parent_unit
    result: dict[str, Any] = {}
    for raw_key, item in sorted(value.items()):
        key = str(raw_key)
        if _key_sensitive(key) or key not in _AGGREGATE_FIELD_KEYS:
            continue
        if isinstance(item, bool):
            if key in {"provided", "narrate_rate"}:
                result[key] = item
            continue
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if key == "value" and unit == "ratio":
                result["value_bucket"] = _ratio_bucket(item)
            else:
                suffix = "bucket" if key.endswith("_bucket") else f"{key}_bucket"
                result[suffix] = _count_bucket(item)
            continue
        if isinstance(item, str):
            safe = _safe_text(key, item)
            if safe is not None:
                result[key] = safe
            continue
        if isinstance(item, dict):
            if key == "values":
                values: dict[str, Any] = {}
                for label, number in sorted(item.items()):
                    label_text = str(label)
                    if label_text not in _AGGREGATE_VALUE_LABELS:
                        continue
                    if isinstance(number, (int, float)) and not isinstance(number, bool):
                        values[label_text] = (
                            _ratio_bucket(number) if unit == "ratio" else _count_bucket(number)
                        )
                if values:
                    result["value_buckets"] = values
                continue
            nested = _bucket_observations(item, parent_unit=unit)
            if nested:
                result[key] = nested
    return result or None


def _measurements(report: Mapping[str, Any]) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    for key in _MEASUREMENT_SECTIONS:
        reduced = _bucket_observations(report.get(key))
        if reduced:
            sections[key] = reduced
    return sections


def _precise_observations(value: Any, *, parent_unit: str | None = None) -> Any:
    """Retain controlled exact observations while closing identity and text vocabularies."""

    if not isinstance(value, Mapping):
        return None
    unit = value.get("unit") if isinstance(value.get("unit"), str) else parent_unit
    result: dict[str, Any] = {}
    for raw_key, item in sorted(value.items()):
        key = str(raw_key)
        if _key_sensitive(key) or key not in _AGGREGATE_FIELD_KEYS:
            continue
        if isinstance(item, bool):
            if key in {"provided", "narrate_rate"}:
                result[key] = item
            continue
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if math.isfinite(float(item)):
                result[key] = item
            continue
        if isinstance(item, str):
            safe = _safe_text(key, item)
            if safe is not None:
                result[key] = safe
            continue
        if isinstance(item, Mapping):
            if key == "values":
                values = {
                    str(label): number
                    for label, number in sorted(item.items())
                    if str(label) in _AGGREGATE_VALUE_LABELS
                    and isinstance(number, (int, float))
                    and not isinstance(number, bool)
                    and math.isfinite(float(number))
                }
                if values:
                    result["values"] = values
                continue
            nested = _precise_observations(item, parent_unit=unit)
            if nested:
                result[key] = nested
    return result or None


def _precise_structured_observations(value: Any, *, field: str | None = None) -> Any:
    """Retain report-schema-validated experience/role structure for controlled research.

    These two sections contain closed arrays and dynamic period/category maps
    which the public aggregate allowlist intentionally suppresses.  Masked is
    a controlled profile, so exact finite values, windows, categories, and
    limitations are retained.  Direct identity/source fields remain removed,
    and credential-like free text is never copied.
    """

    if field is not None and _key_sensitive(field):
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if math.isfinite(float(value)) else None
    if isinstance(value, str):
        if _unsafe_credential_value(value) or artifact_leaks(json.dumps(value, ensure_ascii=False)):
            return None
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key = str(raw_key)
            if _key_sensitive(key):
                continue
            reduced = _precise_structured_observations(item, field=key)
            if reduced is not None:
                result[key] = reduced
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            reduced = _precise_structured_observations(item)
            if reduced is not None:
                result.append(reduced)
        return result
    return None


def _string_contains_forbidden_identifier(value: str, forbidden: frozenset[str]) -> bool:
    folded = value.casefold()
    return any(identifier.casefold() in folded for identifier in forbidden)


def _scrub_forbidden_string_values(node: Any, forbidden: frozenset[str]) -> Any:
    """Remove source identifiers from every controlled measurement string."""

    if isinstance(node, str):
        return None if _string_contains_forbidden_identifier(node, forbidden) else node
    if isinstance(node, Mapping):
        result: dict[str, Any] = {}
        for raw_key, value in node.items():
            key = str(raw_key)
            reduced = _scrub_forbidden_string_values(value, forbidden)
            if reduced is not None:
                result[key] = reduced
        return result
    if isinstance(node, list):
        result = []
        for value in node:
            reduced = _scrub_forbidden_string_values(value, forbidden)
            if reduced is not None:
                result.append(reduced)
        return result
    return node


def _precise_measurements(
    report: Mapping[str, Any], *, forbidden_strings: frozenset[str] = frozenset()
) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    for key in _MEASUREMENT_SECTIONS:
        reduced = (
            _precise_structured_observations(report.get(key))
            if key in {"experience", "role_profile"}
            else _precise_observations(report.get(key))
        )
        if reduced:
            scrubbed = _scrub_forbidden_string_values(reduced, forbidden_strings)
            if scrubbed:
                sections[key] = scrubbed
    return sections


def _missingness(report: Mapping[str, Any]) -> list[dict[str, str]]:
    found: set[tuple[str, str, str]] = set()

    def record(path: str, kind: str, reason: str) -> None:
        found.add((path, kind, reason))

    def walk(node: Any, section: str) -> None:
        if isinstance(node, dict):
            kind = node.get("kind")
            reason = node.get("reason")
            if kind in {"not_observed", "not_proven", "not_declared"}:
                record(section, str(kind), _safe_reason(reason))
                return
            for key, value in sorted(node.items()):
                key_text = str(key)
                if _key_sensitive(key_text):
                    continue
                if key_text not in _AGGREGATE_FIELD_KEYS:
                    record(section, "suppressed", "unregistered_text")
                    continue
                if key_text == "values" and isinstance(value, Mapping):
                    if any(str(label) not in _AGGREGATE_VALUE_LABELS for label in value):
                        record(section, "suppressed", "unregistered_text")
                    continue
                if isinstance(value, str) and not _EXACT_TIME_RE.fullmatch(value):
                    if key_text == "reason" and value not in _AGGREGATE_REASONS:
                        record(section, "suppressed", "unregistered_reason")
                    elif _safe_text(key_text, value) is None:
                        record(section, "suppressed", "unregistered_text")
                    continue
                walk(value, section)
        elif isinstance(node, list):
            # Array positions and contents are deliberately omitted; either can
            # fingerprint a source.  Record only a closed suppression token.
            if node:
                record(section, "suppressed", "unregistered_text")
            return
        elif isinstance(node, str):
            return

    for section in _MEASUREMENT_SECTIONS:
        walk(report.get(section), section)

    coverage = report.get("input_coverage")
    if isinstance(coverage, Mapping):
        for source, node in coverage.items():
            if str(source) not in _AGGREGATE_COVERAGE_SOURCES:
                record("input_coverage", "suppressed", "unregistered_source")
                continue
            if isinstance(node, Mapping):
                reason = node.get("reason")
                if isinstance(reason, str) and reason not in _AGGREGATE_REASONS:
                    record("input_coverage", "suppressed", "unregistered_reason")

    return [{"path": path, "kind": kind, "reason": reason} for path, kind, reason in sorted(found)]


def _coverage(report: Mapping[str, Any]) -> dict[str, Any]:
    coverage = report.get("input_coverage")
    if not isinstance(coverage, dict):
        return {"report": {"kind": "not_observed", "reason": "coverage_absent"}}
    result: dict[str, Any] = {}
    for source, node in sorted(coverage.items()):
        if str(source) not in _AGGREGATE_COVERAGE_SOURCES or not isinstance(node, dict):
            continue
        item: dict[str, Any] = {}
        if node.get("kind") in {"observed", "not_observed", "not_proven"}:
            item["kind"] = node["kind"]
        if isinstance(node.get("provided"), bool):
            item["provided"] = node["provided"]
        if isinstance(node.get("reason"), str):
            item["reason"] = _safe_reason(node["reason"])
        if item:
            result[str(source)] = item
    return result or {"report": {"kind": "not_observed", "reason": "coverage_absent"}}


def _population(report: Mapping[str, Any]) -> dict[str, int]:
    population = report.get("population")
    if isinstance(population, Mapping):
        actor_n = population.get("actor_count")
        commit_n = population.get("human_commit_count")
        if (
            isinstance(actor_n, int)
            and not isinstance(actor_n, bool)
            and isinstance(commit_n, int)
            and not isinstance(commit_n, bool)
        ):
            return {
                "n": actor_n,
                "denominator": commit_n,
            }
    attribution = report.get("attribution")
    activity = report.get("activity")
    actor_n: int | float = 0
    commit_n: int | float = 0
    if isinstance(attribution, dict):
        value = attribution.get("observed_actor_count")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            actor_n = value
    if isinstance(activity, dict):
        node = activity.get("repo_human_nonmerge_commits")
        if isinstance(node, dict):
            value = node.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                commit_n = value
    return {"n": int(actor_n), "denominator": int(commit_n)}


def _validate_profile_door(profile: str, door: str) -> None:
    if profile not in PROFILES:
        raise ValueError("privacy must be aggregate, named-public, masked, or raw")
    if door not in DOORS:
        raise ValueError("door must be local, controlled, or public-pr")
    if door not in PROFILE_DOORS[profile]:
        raise ValueError(f"privacy={profile} cannot use door={door}")


def _validate_purpose_door(purpose: str | None, door: str) -> None:
    """Refuse a purpose the chosen door cannot actually deliver."""
    for name, value in PURPOSES.items():
        if purpose in (None, name, value):
            allowed = PURPOSE_DOORS[name] if purpose is not None else PURPOSE_DOORS[
                "reference-distributions"
            ]
            if door not in allowed:
                raise ValueError(
                    PUBLIC_INTAKE_UNSUPPORTED_PURPOSE.format(
                        purpose=name, door=door, accepted=", ".join(sorted(allowed))
                    )
                )
            return


def _validate_report(report: Mapping[str, Any]) -> None:
    if not isinstance(report, Mapping):
        raise ValueError("contribution-v2 report must be an object")
    if report.get("schema_version") != "report-v2":
        raise ValueError("contribution-v2 requires report-v2")
    if (report.get("subject") or {}).get("kind") == "actor":
        raise ValueError("contribution-v2 refuses actor reports")
    if (report.get("provenance") or {}).get("analysis_scope") != "repo":
        raise ValueError("contribution-v2 requires a repo-scope report-v2")
    errors = _schema_errors("report-v2", report)
    if errors:
        raise ValueError("contribution-v2 requires a schema-valid report-v2: " + "; ".join(errors))


def _base_payload(
    profile: str, door: str, receipt_id: str, purpose: str | None = None
) -> dict[str, Any]:
    if not _RECEIPT_RE.fullmatch(receipt_id):
        raise ValueError("provenance receipt id must be an opaque 128-bit receipt")
    return {
        "contribution_schema": CONTRIBUTION_V2,
        "privacy_profile": profile,
        "door": door,
        "purpose": resolve_purpose(purpose),
        "provenance_receipt_id": receipt_id,
        "transformation_spec_digest": TRANSFORMATION_SPEC_DIGESTS[profile],
        "policy": {
            "access_class": "public" if door == "public-pr" else "controlled_local",
            "public_payload": bool(door == "public-pr"),
            "source_replay": SOURCE_REPLAY_BY_PROFILE[profile],
        },
    }


def _aggregate_data(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "population": _population(report),
        "measurements": _measurements(report),
        "coverage": _coverage(report),
        "missingness": _missingness(report),
    }


def _validate_public_project(project: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(project, Mapping):
        raise ValueError("named-public requires an explicit provider-neutral public_project")
    required = ("provider", "host", "project_id", "project_path")
    result: dict[str, str] = {}
    for key in required:
        value = project.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"named-public public_project.{key} is required")
        result[key] = value.strip()
    result["provider"] = result["provider"].lower()
    result["host"] = result["host"].lower()
    if not _SAFE_NAME_RE.fullmatch(result["provider"]):
        raise ValueError("named-public provider is invalid")
    if not _valid_host(result["host"]):
        raise ValueError("named-public host is invalid")
    if (
        len(result["project_id"]) > 255
        or "@" in result["project_id"]
        or any(character.isspace() or ord(character) < 0x20 for character in result["project_id"])
        or (
            _NETWORK_URL_RE.match(result["project_id"])
            and not result["project_id"].startswith("gid://")
        )
        or _unsafe_credential_value(result["project_id"])
    ):
        raise ValueError("named-public project_id is invalid")
    project_segments = result["project_path"].split("/")
    if (
        not _PROJECT_PATH_RE.fullmatch(result["project_path"])
        or len(project_segments) < 2
        or any(not _PUBLIC_PATH_SEGMENT_RE.fullmatch(segment) for segment in project_segments)
    ):
        raise ValueError("named-public project_path is invalid")
    return result


def _account_from_node(node: Any, *, require_coverage: bool = True) -> dict[str, Any] | None:
    if not isinstance(node, Mapping):
        return None
    required = ("provider", "host", "account_id", "handle")
    account: dict[str, Any] = {}
    for key in required:
        value = node.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        account[key] = value.strip()
    account["provider"] = account["provider"].lower()
    account["host"] = account["host"].lower()
    if (
        not _SAFE_NAME_RE.fullmatch(account["provider"])
        or not _valid_host(account["host"])
        or not _PUBLIC_ACCOUNT_ID_RE.fullmatch(account["account_id"])
        or account["account_id"].startswith("legacy-login:")
        or _unsafe_credential_value(account["account_id"])
        or not _PUBLIC_HANDLE_RE.fullmatch(account["handle"])
    ):
        return None
    profile_url = node.get("profile_url")
    if not isinstance(profile_url, str) or not profile_url.startswith("https://"):
        return None
    split = urlsplit(profile_url)
    expected = urlsplit("//" + account["host"])
    try:
        actual_port = split.port
        expected_port = expected.port
    except ValueError:
        return None
    if (
        split.scheme != "https"
        or split.username
        or split.password
        or split.query
        or split.fragment
        or (split.hostname or "").lower() != (expected.hostname or "").lower()
        or actual_port != expected_port
        or expected_port == 443
        or split.netloc != account["host"]
        or not _canonical_public_profile_path(split.path, handle=account["handle"])
        or profile_url != urlunsplit(("https", account["host"], split.path, "", ""))
    ):
        return None
    account["profile_url"] = profile_url
    evidence = node.get("evidence")
    if isinstance(evidence, Mapping):
        safe_evidence = {
            str(key): value
            for key, value in evidence.items()
            if str(key) in {"basis", "coverage_status", "account_match_status"}
            and isinstance(value, str)
            and len(value) <= 80
        }
    else:
        safe_evidence = {}
    if (
        safe_evidence.get("basis")
        not in _PUBLIC_ACCOUNT_EVIDENCE_BY_PROVIDER.get(account["provider"], frozenset())
        or safe_evidence.get("account_match_status") != "linked"
        or (require_coverage and "coverage_status" not in safe_evidence)
        or (
            "coverage_status" in safe_evidence
            and safe_evidence["coverage_status"] not in _PUBLIC_ACCOUNT_COVERAGE
        )
    ):
        return None
    account["evidence"] = safe_evidence
    return account


def _valid_host(value: str) -> bool:
    if (
        any(character in value for character in "/@?#\\")
        or any(character.isspace() for character in value)
        or value.startswith(("http://", "https://"))
    ):
        return False
    try:
        parsed = urlsplit("//" + value)
        _ = parsed.port
    except ValueError:
        return False
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc != value
    ):
        return False
    hostname = parsed.hostname
    try:
        if ":" in hostname:
            canonical_hostname = f"[{ipaddress.IPv6Address(hostname).compressed}]"
        elif re.fullmatch(r"[0-9.]+", hostname):
            canonical_hostname = str(ipaddress.IPv4Address(hostname))
        else:
            labels = hostname.split(".")
            if len(hostname) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            ):
                return False
            canonical_hostname = hostname
    except ipaddress.AddressValueError:
        return False
    canonical = canonical_hostname
    if parsed.port is not None:
        canonical += f":{parsed.port}"
    return value == canonical


def _canonical_public_profile_path(path: str, *, handle: str) -> bool:
    return path == f"/{quote(handle, safe='')}"


def _named_accounts(
    report: Mapping[str, Any],
    *,
    project: Mapping[str, str],
    authority_claims: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not _PUBLIC_ACCOUNT_EVIDENCE_BY_PROVIDER.get(project["provider"]):
        raise ValueError("named-public account linkage is unsupported for this provider")
    directory = report.get("actor_directory")
    rows = directory.get("actors") if isinstance(directory, Mapping) else None
    if not isinstance(rows, list):
        return []
    if len(authority_claims) != 1:
        raise ValueError(
            "named-public currently requires exactly one report-proven account population"
        )
    attributed = report.get("attribution")
    public_join = attributed.get("public_join") if isinstance(attributed, Mapping) else None
    if not isinstance(public_join, Mapping):
        raise ValueError("named-public requires report public_join evidence")
    account_nodes = [
        account
        for actor in rows
        if isinstance(actor, Mapping)
        for account in (
            [actor.get("public_accounts")]
            if isinstance(actor.get("public_accounts"), Mapping)
            else actor.get("public_accounts") or actor.get("accounts") or []
        )
    ]
    if not account_nodes:
        if any(
            public_join.get(key) != 0
            for key in ("matched", "public_handle_actors", "commit_login_count")
        ):
            raise ValueError("named-public report public account population is inconsistent")
        return []
    linked_count = public_join.get("matched")
    if (
        not isinstance(linked_count, int)
        or isinstance(linked_count, bool)
        or linked_count < 1
        or public_join.get("ambiguous") != 0
        or public_join.get("public_handle_actors") != 1
        or public_join.get("commit_login_count") != 1
        or public_join.get("account_conflict_count") != 0
    ):
        raise ValueError("named-public linked population is not isolated to one proven account")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for actor in rows:
        if not isinstance(actor, Mapping):
            continue
        accounts = actor.get("public_accounts") or actor.get("accounts")
        if isinstance(accounts, Mapping):
            accounts = [accounts]
        if not isinstance(accounts, list):
            continue
        for raw_account in accounts:
            account = _account_from_node(raw_account, require_coverage=False)
            raw_identity = (
                (
                    str(raw_account.get("provider") or "").lower(),
                    str(raw_account.get("host") or "").lower(),
                    str(raw_account.get("account_id") or ""),
                )
                if isinstance(raw_account, Mapping)
                else ("", "", "")
            )
            if account is None:
                if raw_identity not in authority_claims:
                    raise ValueError(
                        "named-public linked population includes an unauthorized or conflicting account"
                    )
                continue
            identity = (account["provider"], account["host"], account["account_id"])
            claim = authority_claims.get(identity)
            if claim is None:
                continue
            if identity in seen:
                raise ValueError(
                    "named-public authority account is ambiguous across actor clusters"
                )
            if account["provider"] != project["provider"] or account["host"] != project["host"]:
                raise ValueError("named-public account provider/host must match public_project")
            count = actor.get("commit_count")
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or actor.get("commit_count_includes_merges") is not True
            ):
                raise ValueError("named-public report actor population is not exact")
            if linked_count > count:
                raise ValueError(
                    "named-public linked_commit_count cannot exceed actor_commit_count"
                )
            coverage_status = "complete" if linked_count == count else "partial"
            seen.add(identity)
            account["evidence"]["coverage_status"] = coverage_status
            result.append(
                {
                    "account": account,
                    "measurements": {
                        "linked_commit_count_bucket": _count_bucket(linked_count),
                        "actor_commit_count_bucket": _count_bucket(count),
                        "linkage_coverage_bucket": _ratio_bucket(linked_count / count),
                        "commit_count_basis": "git_primary_author_cluster_including_merges",
                    },
                }
            )
    missing = set(authority_claims) - seen
    if missing:
        raise ValueError(
            "named-public authority does not bind every account to a linked report actor"
        )
    return sorted(
        result,
        key=lambda item: (
            item["account"]["provider"],
            item["account"]["host"],
            item["account"]["account_id"],
        ),
    )


def _public_authority(
    authority: Mapping[str, Any] | None,
    *,
    project: Mapping[str, str],
) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
    if not isinstance(authority, Mapping):
        raise ValueError("named-public requires explicit public_authority")
    if set(authority) != {"accounts"} or not isinstance(authority.get("accounts"), list):
        raise ValueError("named-public public_authority must contain only an accounts list")
    rows = authority["accounts"]
    if not rows:
        raise ValueError("named-public authority requires at least one authorized account")
    required = {
        "provider",
        "host",
        "project_id",
        "account_id",
        "basis",
        "scope",
        "assertion",
    }
    claims: dict[tuple[str, str, str], dict[str, Any]] = {}
    public_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != required:
            raise ValueError("named-public authority account fields are not closed")
        provider = row.get("provider")
        host = row.get("host")
        account_id = row.get("account_id")
        project_id = row.get("project_id")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (provider, host, account_id, project_id)
        ):
            raise ValueError("named-public authority account binding is incomplete")
        provider = str(provider).strip().lower()
        host = str(host).strip().lower()
        account_id = str(account_id).strip()
        project_id = str(project_id).strip()
        if (
            not _SAFE_NAME_RE.fullmatch(provider)
            or not _valid_host(host)
            or not _PUBLIC_ACCOUNT_ID_RE.fullmatch(account_id)
            or account_id.startswith("legacy-login:")
            or _unsafe_credential_value(account_id)
        ):
            raise ValueError("named-public authority account binding is invalid")
        if provider != project["provider"] or host != project["host"]:
            raise ValueError("named-public authority provider/host must match public_project")
        if project_id != project["project_id"]:
            raise ValueError("named-public authority project_id must match public_project")
        if row.get("basis") != _NAMED_AUTHORITY_BASIS:
            raise ValueError("named-public authority basis must be account_holder_explicit")
        if row.get("scope") != _NAMED_AUTHORITY_SCOPE:
            raise ValueError("named-public authority scope must be project_and_account")
        if row.get("assertion") != _NAMED_AUTHORITY_ASSERTION:
            raise ValueError("named-public authority assertion is not registered")
        identity = (provider, host, account_id)
        if identity in claims:
            raise ValueError("named-public authority account binding is duplicated")
        claims[identity] = {}
        public_rows.append(
            {
                "provider": provider,
                "host": host,
                "project_id": project_id,
                "account_id": account_id,
                "basis": _NAMED_AUTHORITY_BASIS,
                "scope": _NAMED_AUTHORITY_SCOPE,
                "assertion": _NAMED_AUTHORITY_ASSERTION,
            }
        )
    public_rows.sort(key=lambda item: (item["provider"], item["host"], item["account_id"]))
    return {"accounts": public_rows}, claims


def _governance(
    context: Mapping[str, Any] | None, *, masked: bool, purpose: str | None = None
) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise ValueError("controlled contribution requires governance context")
    allowed = set(_GOVERNANCE_REQUIRED) | {"key_id", "epoch", "repo_subject_id"}
    if set(context) - allowed:
        raise ValueError("controlled governance contains an unregistered field")
    # The sidecar must name the same purpose as the payload; a controlled
    # submission governed under one purpose and delivered under another would
    # make the binding unenforceable.
    result: dict[str, Any] = {"purpose": resolve_purpose(purpose)}
    for key in _GOVERNANCE_REQUIRED:
        value = context.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"controlled governance.{key} is required")
        result[key] = value.strip()
    if masked:
        for key in ("key_id", "epoch"):
            value = context.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"masked governance.{key} is required")
            result[key] = value.strip()
    repo_subject = context.get("repo_subject_id")
    if repo_subject is not None:
        if not isinstance(repo_subject, str) or not repo_subject.strip():
            raise ValueError("repo_subject_id must be a non-empty opaque identifier")
        result["repo_subject_id"] = repo_subject.strip()
    for key in ("controller", "study_id", "key_id", "epoch", "repo_subject_id"):
        value = result.get(key)
        if value is not None and not _CONTROLLED_ID_RE.fullmatch(value):
            raise ValueError(f"controlled governance.{key} must be a closed opaque identifier")
    if result["authority"] not in _CONTROLLED_AUTHORITY:
        raise ValueError("controlled governance.authority is not registered")
    if result["consent"] not in _CONTROLLED_CONSENT:
        raise ValueError("controlled governance.consent is not registered")
    if result["withdrawal"] not in _CONTROLLED_WITHDRAWAL:
        raise ValueError("controlled governance.withdrawal is not registered")
    if result["access_class"] not in _CONTROLLED_ACCESS_CLASS:
        raise ValueError("controlled governance.access_class is not registered")
    if not _RETENTION_RE.fullmatch(result["retention"]):
        raise ValueError("controlled governance.retention must be until-YYYY-MM-DD")
    try:
        date.fromisoformat(result["retention"].removeprefix("until-"))
    except ValueError as exc:
        raise ValueError("controlled governance.retention date is invalid") from exc
    text = json.dumps(result, ensure_ascii=False)
    if artifact_leaks(text):
        raise ValueError("controlled governance contains a secret, email, or absolute path")
    return result


def _validate_key_descriptor(info: os.stat_result, *, label: str) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"pseudonym key {label} must be regular")
    getuid = getattr(os, "getuid", None)
    if getuid is None or info.st_uid != getuid():
        raise ValueError(f"pseudonym key {label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
        raise ValueError(f"pseudonym key {label} permissions must be 0400 or 0600")
    if info.st_nlink != 1:
        raise ValueError(f"pseudonym key {label} must have exactly one link")
    if info.st_size > _MAX_PSEUDONYM_KEY_BYTES:
        raise ValueError("pseudonym key material is too large")


def _read_key_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblock is None:
        raise ValueError("pseudonym key file requires safe descriptor support")
    flags |= nofollow | nonblock
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise ValueError("pseudonym key file is unreadable") from exc
    try:
        info = os.fstat(fd)
        _validate_key_descriptor(info, label="file")
        chunks: list[bytes] = []
        remaining = _MAX_PSEUDONYM_KEY_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_PSEUDONYM_KEY_BYTES:
            raise ValueError("pseudonym key material is too large")
        _validate_key_descriptor(os.fstat(fd), label="file")
    except OSError as exc:
        raise ValueError("pseudonym key file is unreadable") from exc
    finally:
        os.close(fd)
    return _normalize_key(raw)


def _read_key_fd(fd: int) -> bytes:
    if not isinstance(fd, int) or isinstance(fd, bool) or fd < 0:
        raise ValueError("pseudonym key fd is invalid")
    try:
        info = os.fstat(fd)
        _validate_key_descriptor(info, label="fd")
        duplicate = os.dup(fd)
        with os.fdopen(duplicate, "rb", closefd=True) as handle:
            raw = handle.read(4097)
        _validate_key_descriptor(os.fstat(fd), label="fd")
    except OSError as exc:
        raise ValueError("pseudonym key fd is unreadable") from exc
    if len(raw) > 4096:
        raise ValueError("pseudonym key material is too large")
    return _normalize_key(raw)


def _normalize_key(raw: bytes) -> bytes:
    material = raw.strip()
    if len(material) == 64 and re.fullmatch(rb"[0-9a-fA-F]{64}", material):
        material = bytes.fromhex(material.decode("ascii"))
    if len(material) < 32:
        raise ValueError("pseudonym key must contain at least 32 bytes")
    return material


def load_pseudonym_key(*, key_file: Path | None = None, key_fd: int | None = None) -> bytes:
    if (key_file is None) == (key_fd is None):
        raise ValueError("masked privacy requires exactly one key file or key fd")
    return _read_key_file(key_file) if key_file is not None else _read_key_fd(int(key_fd))


def _scope_context(report: Mapping[str, Any], governance: Mapping[str, Any]) -> str:
    explicit = governance.get("repo_subject_id")
    if isinstance(explicit, str):
        return "controlled-subject\0" + explicit
    attribution = report.get("attribution")
    partition = attribution.get("actor_partition") if isinstance(attribution, Mapping) else None
    scope = partition.get("repo_scope_digest") if isinstance(partition, Mapping) else None
    provenance = report.get("provenance")
    if isinstance(provenance, Mapping):
        scope = scope or provenance.get("repo_scope_digest")
    if not isinstance(scope, str) or not scope:
        scope = _sha256(report)
    return "repo-local\0" + scope


def _masked_scope_key(
    report: Mapping[str, Any], governance: Mapping[str, Any], key: bytes
) -> bytes:
    context = _scope_context(report, governance).encode("utf-8")
    return hmac.new(key, b"tep-contribution-v2:scope\0" + context, hashlib.sha256).digest()


def _actor_seed(actor: Mapping[str, Any]) -> tuple[str, str] | None:
    for field in ("resolution_seed", "internal_actor_id", "actor_id"):
        value = actor.get(field)
        if isinstance(value, str) and value:
            return field, value
    return None


def _masked_actor_pid(scope_key: bytes, source_actor_id: str) -> str:
    return _opaque(
        "pa_",
        hmac.new(
            scope_key,
            b"tep-actor-v1\0" + source_actor_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()[:16],
    )


def _masked_actor_correspondence(
    report: Mapping[str, Any], *, key: bytes, governance: Mapping[str, Any]
) -> list[dict[str, str]]:
    directory = report.get("actor_directory")
    actor_rows = directory.get("actors") if isinstance(directory, Mapping) else None
    scope_key = _masked_scope_key(report, governance, key)
    rows: list[dict[str, str]] = []
    if isinstance(actor_rows, list):
        for actor in actor_rows:
            if not isinstance(actor, Mapping):
                continue
            seed = _actor_seed(actor)
            if seed is None:
                continue
            source_field, source_actor_id = seed
            rows.append(
                {
                    "actor_pid": _masked_actor_pid(scope_key, source_actor_id),
                    "source_actor_field": source_field,
                    "source_actor_id": source_actor_id,
                }
            )
    return sorted(rows, key=lambda item: item["actor_pid"])


def _source_actor_identifiers(report: Mapping[str, Any]) -> frozenset[str]:
    identifiers: set[str] = set()

    def add_values(value: Any) -> None:
        if isinstance(value, str) and value:
            identifiers.add(value)
        elif isinstance(value, list):
            for item in value:
                add_values(item)

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for raw_key, value in node.items():
                key = str(raw_key).casefold()
                if key in _ACTOR_IDENTIFIER_FIELDS or key.endswith("_actor_id"):
                    add_values(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(report)
    return frozenset(identifiers)


def _contains_forbidden_string_value(node: Any, forbidden: frozenset[str]) -> bool:
    if isinstance(node, str):
        return _string_contains_forbidden_identifier(node, forbidden)
    if isinstance(node, Mapping):
        return any(_contains_forbidden_string_value(value, forbidden) for value in node.values())
    if isinstance(node, list):
        return any(_contains_forbidden_string_value(value, forbidden) for value in node)
    return False


def _masked_data(
    report: Mapping[str, Any], *, key: bytes, governance: Mapping[str, Any]
) -> dict[str, Any]:
    scope_key = _masked_scope_key(report, governance, key)
    directory = report.get("actor_directory")
    actor_rows = directory.get("actors") if isinstance(directory, Mapping) else None
    population = report.get("population")
    population_n = population.get("actor_count") if isinstance(population, Mapping) else None
    population_denominator = (
        population.get("human_commit_count") if isinstance(population, Mapping) else None
    )
    population_basis = population.get("basis") if isinstance(population, Mapping) else None
    if (
        not isinstance(population_n, int)
        or isinstance(population_n, bool)
        or not isinstance(population_denominator, int)
        or isinstance(population_denominator, bool)
        or population_basis != "git_primary_author_cluster"
    ):
        raise ValueError("masked contribution requires an exact report population")
    actors: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(actor_rows, list):
        for actor in actor_rows:
            if not isinstance(actor, Mapping):
                continue
            seed = _actor_seed(actor)
            if seed is None:
                continue
            _source_field, source_actor_id = seed
            pid = _masked_actor_pid(scope_key, source_actor_id)
            if pid in seen:
                raise ValueError("masked contribution pseudonym collision is not representable")
            seen.add(pid)
            count = actor.get("commit_count")
            nonmerge = actor.get("commit_count_nonmerge")
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or not isinstance(nonmerge, int)
                or isinstance(nonmerge, bool)
                or nonmerge > count
                or actor.get("commit_count_includes_merges") is not True
            ):
                raise ValueError("masked contribution actor population is not exact")
            actors.append(
                {
                    "actor_pid": pid,
                    "measurements": {
                        "n": count,
                        "denominator": population_denominator,
                        "basis": "git_primary_author_cluster",
                        "commit_count_includes_merges": True,
                        "nonmerge_n": nonmerge,
                        "merge_n": count - nonmerge,
                    },
                }
            )
    if len(actors) != population_n:
        raise ValueError("masked contribution actor rows do not cover the report population")
    if sum(item["measurements"]["n"] for item in actors) != population_denominator:
        raise ValueError("masked contribution actor n does not equal the report denominator")
    source_actor_identifiers = _source_actor_identifiers(report)
    result = {
        "actors": sorted(actors, key=lambda item: item["actor_pid"]),
        "population": {
            "n": population_n,
            "denominator": population_denominator,
            "basis": "git_primary_author_cluster",
        },
        "measurements": _precise_measurements(report, forbidden_strings=source_actor_identifiers),
        "coverage": _coverage(report),
        "missingness": _missingness(report),
        "research": {
            "key_id": governance["key_id"],
            "epoch": governance["epoch"],
            "study_id": governance["study_id"],
        },
    }
    if _contains_forbidden_string_value(result["measurements"], source_actor_identifiers):
        raise ValueError("masked contribution contains a source actor identifier")
    return result


def _credential_field_name(value: Any) -> bool:
    raw = str(value)
    split_acronyms = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", raw)
    split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", split_acronyms)
    words = [re.sub(r"\d+$", "", word.lower()) for word in re.findall(r"[A-Za-z0-9]+", split_camel)]
    if not words:
        return False
    if any(word in _CREDENTIAL_WORDS for word in words):
        return True
    collapsed = "".join(words)
    credential_substrings = (
        "authorization",
        "authcode",
        "bearer",
        "credential",
        "csrf",
        "jwt",
        "password",
        "passcode",
        "passphrase",
        "passwd",
        "pwd",
        "secret",
        "token",
    )
    return (
        "key" in words
        or any(marker in collapsed for marker in credential_substrings)
        or collapsed in {"auth", "authentication", "cookie", "oauth", "session", "setcookie"}
        or collapsed in _CREDENTIAL_COMPOUNDS
        or collapsed.startswith(("accesskey", "apikey", "authkey", "keymaterial", "privatekey"))
        or collapsed.startswith(("bearer", "csrf", "jwt"))
        or collapsed.endswith(
            (
                "accesskey",
                "apikey",
                "authorization",
                "authkey",
                "cookie",
                "credential",
                "password",
                "passwd",
                "privatekey",
                "secret",
                "secretkey",
                "token",
            )
        )
        or collapsed.startswith(
            (
                "authcode",
                "authcredential",
                "authsecret",
                "authtoken",
                "cookieheader",
                "cookiejar",
                "cookievalue",
                "oauthcode",
                "oauthcredential",
                "oauthkey",
                "oauthsecret",
                "oauthtoken",
                "sessioncookie",
                "sessionid",
                "sessionkey",
                "sessionsecret",
                "sessiontoken",
                "sessionvalue",
            )
        )
        or collapsed.startswith(("patcredential", "patid", "pattoken", "patvalue"))
    )


def _bounded_percent_decode(value: str, guard: Any) -> tuple[str, bool]:
    """Run a guard after every decode and fail closed beyond the fixed bound."""

    current = value
    if guard(current):
        return current, True
    for _ in range(_MAX_PERCENT_DECODE_PASSES):
        decoded = unquote(current)
        if decoded == current:
            return current, False
        current = decoded
        if guard(current):
            return current, True
    return current, unquote(current) != current


def _bounded_percent_decode_is_unsafe(value: str, guard: Any) -> bool:
    return _bounded_percent_decode(value, guard)[1]


def _unsafe_credential_value_once(value: str) -> bool:
    text = value.strip()
    if (
        _AUTHORIZATION_VALUE_RE.search(text)
        or _CREDENTIAL_HEADER_VALUE_RE.search(text)
        or _CREDENTIAL_SPACE_VALUE_RE.search(text)
        or _PRIVATE_KEY_VALUE_RE.search(text)
        or _HIGH_CONFIDENCE_TOKEN_RE.search(text)
    ):
        return True
    candidates = _EMBEDDED_NETWORK_URL_RE.findall(text)
    if any(_unsafe_url_candidate(candidate) for candidate in candidates):
        return True
    return bool(_SCP_REMOTE_RE.match(text) or _EMBEDDED_SCP_REMOTE_RE.search(text))


def _unsafe_credential_value(value: str) -> bool:
    return _bounded_percent_decode_is_unsafe(value, _unsafe_credential_value_once)


def _unsafe_url_candidate(candidate: str) -> bool:
    if _NETWORK_URL_RE.match(candidate) or candidate.startswith("//"):
        try:
            split = urlsplit(candidate)
            _ = split.port
        except ValueError:
            return True

        def unsafe_path(path: str) -> bool:
            return bool(
                any(
                    _credential_field_name(segment)
                    for segment in re.split(r"[/;]", path)
                    if segment
                )
                or _HIGH_CONFIDENCE_TOKEN_RE.search(path)
            )

        path_has_credential = _bounded_percent_decode_is_unsafe(split.path, unsafe_path)
        try:
            parse_qsl(split.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            return True
        query_items: list[tuple[str, str, bool]] = []
        for pair in split.query.split("&") if split.query else []:
            if "=" not in pair:
                return True
            raw_key, raw_value = pair.split("=", 1)
            decoded_key, key_unsafe = _bounded_percent_decode(raw_key, _credential_field_name)
            query_items.append((decoded_key, raw_value, key_unsafe))
        query_has_credential = any(
            key_unsafe or key.lower() not in _SAFE_RAW_QUERY_FIELDS or _unsafe_query_value(value)
            for key, value, key_unsafe in query_items
        )
        return bool(
            split.username
            or split.password
            or split.fragment
            or path_has_credential
            or query_has_credential
        )
    return False


def _unsafe_query_value(value: str) -> bool:
    """Reject credential material without recursively reparsing the parent URL."""

    def unsafe_once(candidate: str) -> bool:
        text = candidate.strip()
        return bool(
            _AUTHORIZATION_VALUE_RE.search(text)
            or _CREDENTIAL_HEADER_VALUE_RE.search(text)
            or _CREDENTIAL_SPACE_VALUE_RE.search(text)
            or _PRIVATE_KEY_VALUE_RE.search(text)
            or _HIGH_CONFIDENCE_TOKEN_RE.search(text)
            or _SCP_REMOTE_RE.match(text)
            or _EMBEDDED_SCP_REMOTE_RE.search(text)
            or _EMBEDDED_NETWORK_URL_RE.search(text)
        )

    return _bounded_percent_decode_is_unsafe(value, unsafe_once)


def _assert_no_key_material(node: Any) -> None:
    """Reject credentials at every depth without echoing user material."""

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if _bounded_percent_decode_is_unsafe(str(key), _credential_field_name):
                    raise ValueError("raw material contains forbidden secret field")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and _unsafe_credential_value(value):
            raise ValueError("raw material contains unsafe credential-bearing URL or value")

    walk(node)


def _controlled_sidecar(
    *,
    payload: Mapping[str, Any],
    report: Mapping[str, Any],
    profile: str,
    governance: Mapping[str, Any],
    pseudonym_key: bytes | None = None,
) -> dict[str, Any]:
    attribution = report.get("attribution")
    actor_partition = (
        copy.deepcopy(attribution.get("actor_partition"))
        if isinstance(attribution, Mapping)
        and isinstance(attribution.get("actor_partition"), Mapping)
        else None
    )
    source: dict[str, Any] = {
        "report_sha256": _sha256(report),
        "provenance": copy.deepcopy(report.get("provenance") or {}),
        "repository": _sanitize_controlled_repository(report.get("repository")),
        "identity": copy.deepcopy(report.get("identity") or {}),
        "actor_partition": actor_partition,
        "actor_correspondence": (
            _masked_actor_correspondence(report, key=pseudonym_key, governance=governance)
            if profile == "masked" and pseudonym_key is not None
            else []
        ),
    }
    _assert_no_key_material(source)
    return {
        "schema_version": CONTROLLED_SIDECAR_V1,
        "receipt_id": payload["provenance_receipt_id"],
        "privacy_profile": profile,
        "payload_sha256": _sha256(payload),
        "source": source,
        "governance": dict(governance),
    }


def _sanitize_controlled_repository(node: Any) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        return {}
    result = copy.deepcopy(dict(node))
    remote = result.get("remote")
    if isinstance(remote, str):
        result["remote"] = _sanitize_repository_remote(remote)
    return result


def _sanitize_repository_remote(remote: str) -> str:
    """Remove all URL credential surfaces from controlled provenance."""

    text = remote.strip()
    if not text:
        return text
    if _NETWORK_URL_RE.match(text):
        try:
            split = urlsplit(text)
            port = split.port
        except ValueError as exc:
            raise ValueError("controlled repository remote is invalid") from exc
        if split.scheme.lower() not in {"git", "http", "https", "ssh"} or not split.hostname:
            raise ValueError("controlled repository remote is invalid")
        host = split.hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if port is not None:
            host += f":{port}"
        return urlunsplit((split.scheme.lower(), host, split.path, "", ""))

    scp = _SCP_REMOTE_RE.match(text)
    if scp:
        host = scp.group("host").lower()
        path = scp.group("path").split("#", 1)[0].split("?", 1)[0].lstrip("/")
        if not path:
            raise ValueError("controlled repository remote is invalid")
        return f"ssh://{host}/{path}"

    # Legacy report-v2 stores canonical remotes as host/path without a scheme.
    # Remove accidental URL suffixes and any userinfo before retaining it.
    sanitized = text.split("#", 1)[0].split("?", 1)[0]
    first_slash = sanitized.find("/")
    at = sanitized.find("@")
    if at >= 0 and (first_slash < 0 or at < first_slash):
        sanitized = sanitized[at + 1 :]
    if not sanitized:
        raise ValueError("controlled repository remote is invalid")
    return sanitized


def build_contribution_bundle(
    report: Mapping[str, Any],
    *,
    privacy: str,
    door: str = "local",
    receipt_id: str | None = None,
    public_project: Mapping[str, Any] | None = None,
    public_authority: Mapping[str, Any] | None = None,
    key_file: Path | None = None,
    key_fd: int | None = None,
    controlled_context: Mapping[str, Any] | None = None,
    raw_material: Mapping[str, Any] | None = None,
    purpose: str | None = None,
) -> ContributionBundle:
    """Build a strict v2 payload and, for controlled modes, a sidecar.

    Key material is accepted only by permission-checked file or descriptor.  It
    is never serialized, logged, or included in exception messages.
    """

    _validate_report(report)
    profile = privacy.strip().lower()
    chosen_door = door.strip().lower()
    _validate_profile_door(profile, chosen_door)
    _validate_purpose_door(purpose, chosen_door)
    payload = _base_payload(profile, chosen_door, receipt_id or new_receipt_id(), purpose)
    sidecar: dict[str, Any] | None = None
    if profile == "aggregate":
        payload["data"] = _aggregate_data(report)
    elif profile == "named-public":
        project = _validate_public_project(public_project)
        authority, authority_claims = _public_authority(public_authority, project=project)
        actors = _named_accounts(
            report,
            project=project,
            authority_claims=authority_claims,
        )
        if not actors:
            raise ValueError("named-public is not_available: no authorized stable public accounts")
        payload["data"] = {
            "project": project,
            "authority": authority,
            "actors": actors,
            "measurements": _measurements(report),
            "coverage": _coverage(report),
            "missingness": _missingness(report),
        }
    elif profile == "masked":
        governance = _governance(controlled_context, masked=True, purpose=purpose)
        key = load_pseudonym_key(key_file=key_file, key_fd=key_fd)
        payload["data"] = _masked_data(report, key=key, governance=governance)
        sidecar = _controlled_sidecar(
            payload=payload,
            report=report,
            profile=profile,
            governance=governance,
            pseudonym_key=key,
        )
    else:
        governance = _governance(controlled_context, masked=False, purpose=purpose)
        if not isinstance(raw_material, Mapping):
            raise ValueError("raw privacy requires explicit raw_material")
        _assert_no_key_material(raw_material)
        payload["data"] = {
            "raw_material": copy.deepcopy(raw_material),
            "research": {"study_id": governance["study_id"]},
        }
        sidecar = _controlled_sidecar(
            payload=payload,
            report=report,
            profile=profile,
            governance=governance,
        )
    schema_errors = _schema_errors("contribution-v2", payload)
    if schema_errors:
        raise ValueError("contribution-v2 schema violation: " + "; ".join(schema_errors))
    if sidecar is not None:
        bundle_errors = validate_controlled_bundle(
            payload,
            sidecar,
            report=report,
            _pseudonym_key=key if profile == "masked" else None,
        )
        if bundle_errors:
            raise ValueError(
                "controlled contribution bundle violation: " + "; ".join(bundle_errors)
            )
    return ContributionBundle(payload=payload, controlled_sidecar=sidecar)


def _schema_errors(name: str, payload: Mapping[str, Any]) -> list[str]:
    """Validate generated artifacts against the packaged v0.6 contracts.

    The import stays local so the privacy transformer remains usable while the
    schema catalog is being loaded, without creating a module import cycle.
    """

    from tep_core.schema import validate_schema

    return validate_schema(name, dict(payload))


def _aggregate_output_problems(data: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(data, Mapping):
        return ["aggregate data must be an object"]

    allowed_data = {"coverage", "measurements", "missingness", "population"}
    for key in data:
        if str(key) not in allowed_data:
            problems.append("aggregate contains an unregistered data field")

    measurements = data.get("measurements")
    if isinstance(measurements, Mapping):
        for section, tree in measurements.items():
            if str(section) not in _MEASUREMENT_SECTIONS:
                problems.append("aggregate contains an unregistered measurement section")
                continue
            _check_aggregate_bucket_tree(tree, problems)

    population = data.get("population")
    if isinstance(population, Mapping):
        if set(population) != {"denominator", "n"}:
            problems.append("aggregate contains an unregistered population field")
        for value in population.values():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                problems.append("aggregate population counts must be integers >= 0")
        n = population.get("n")
        denominator = population.get("denominator")
        if (
            isinstance(n, int)
            and not isinstance(n, bool)
            and isinstance(denominator, int)
            and not isinstance(denominator, bool)
            and n >= 0
            and denominator >= 0
            and n > denominator
        ):
            problems.append("aggregate population n cannot exceed denominator")

    coverage = data.get("coverage")
    if isinstance(coverage, Mapping):
        for source, node in coverage.items():
            if str(source) not in _AGGREGATE_COVERAGE_SOURCES:
                problems.append("aggregate contains an unregistered coverage source")
                continue
            if not isinstance(node, Mapping):
                continue
            for key, value in node.items():
                if key == "kind" and value not in {"observed", "not_observed", "not_proven"}:
                    problems.append("aggregate contains an unregistered coverage kind")
                elif key == "reason" and value not in _AGGREGATE_REASONS:
                    problems.append("aggregate contains an unregistered coverage reason")
                elif key not in {"kind", "provided", "reason"}:
                    problems.append("aggregate contains an unregistered coverage field")

    missingness = data.get("missingness")
    if isinstance(missingness, list):
        for item in missingness:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path")
            kind = item.get("kind")
            reason = item.get("reason")
            if not isinstance(path, str) or path not in set(_MEASUREMENT_SECTIONS) | {
                "input_coverage"
            }:
                problems.append("aggregate contains an unregistered missingness path")
            if not isinstance(kind, str) or kind not in {
                "not_declared",
                "not_observed",
                "not_proven",
                "suppressed",
            }:
                problems.append("aggregate contains an unregistered missingness kind")
            if not isinstance(reason, str) or reason not in _AGGREGATE_REASONS:
                problems.append("aggregate contains an unregistered missingness reason")
    return problems


def _registered_bucket(value: Any) -> bool:
    return isinstance(value, str) and (
        value in _COUNT_BUCKETS or _RATIO_BUCKET_RE.fullmatch(value) is not None
    )


def _check_aggregate_bucket_tree(node: Any, problems: list[str]) -> None:
    if not isinstance(node, Mapping):
        return
    for raw_key, value in node.items():
        key = str(raw_key)
        if key == "value_buckets":
            if not isinstance(value, Mapping):
                continue
            for label, bucket in value.items():
                if str(label) not in _AGGREGATE_VALUE_LABELS:
                    problems.append("aggregate contains an unregistered bucket label")
                if not _registered_bucket(bucket):
                    problems.append("aggregate contains an unregistered bucket value")
            continue
        if key.endswith("_bucket"):
            source_key = key[: -len("_bucket")]
            if source_key not in _AGGREGATE_FIELD_KEYS:
                problems.append("aggregate contains an unregistered bucket field")
            if not _registered_bucket(value):
                problems.append("aggregate contains an unregistered bucket value")
            continue
        if key not in _AGGREGATE_FIELD_KEYS:
            problems.append("aggregate contains an unregistered measurement field")
            continue
        if isinstance(value, Mapping):
            _check_aggregate_bucket_tree(value, problems)
        elif isinstance(value, str):
            if _safe_text(key, value) is None:
                problems.append("aggregate contains unregistered measurement text")
        elif not isinstance(value, bool):
            problems.append("aggregate contains an invalid measurement value")


def _named_output_problems(data: Any) -> list[str]:
    if not isinstance(data, Mapping):
        return ["named-public data must be an object"]
    problems = _aggregate_output_problems(
        {
            "measurements": data.get("measurements"),
            "coverage": data.get("coverage"),
            "missingness": data.get("missingness"),
        }
    )
    project = data.get("project")
    project_provider = project.get("provider") if isinstance(project, Mapping) else None
    project_host = project.get("host") if isinstance(project, Mapping) else None
    project_id = project.get("project_id") if isinstance(project, Mapping) else None
    actors = data.get("actors")
    actor_bindings: set[tuple[Any, Any, Any]] = set()
    if not _PUBLIC_ACCOUNT_EVIDENCE_BY_PROVIDER.get(str(project_provider)):
        problems.append("named-public account linkage is unsupported for this provider")
    if not isinstance(actors, list):
        problems.append("named-public actors must be a list")
    else:
        for actor in actors:
            if not isinstance(actor, Mapping):
                problems.append("named-public actor must be an object")
                continue
            account = actor.get("account")
            if not isinstance(account, Mapping):
                problems.append("named-public account must be an object")
                continue
            binding = (account.get("provider"), account.get("host"), account.get("account_id"))
            if binding in actor_bindings:
                problems.append("named-public account binding is duplicated")
            actor_bindings.add(binding)
            if account.get("provider") != project_provider or account.get("host") != project_host:
                problems.append("named-public account provider/host does not match project")
            evidence = account.get("evidence")
            allowed_evidence = _PUBLIC_ACCOUNT_EVIDENCE_BY_PROVIDER.get(
                str(account.get("provider")), frozenset()
            )
            if not isinstance(evidence, Mapping) or evidence.get("basis") not in allowed_evidence:
                problems.append("named-public account evidence is unsupported for provider")
            measurements = actor.get("measurements")
            expected = {
                "linked_commit_count_bucket",
                "actor_commit_count_bucket",
                "linkage_coverage_bucket",
                "commit_count_basis",
            }
            if not isinstance(measurements, Mapping) or set(measurements) != expected:
                problems.append("named-public actor measurements are not closed")
                continue
            for key in (
                "linked_commit_count_bucket",
                "actor_commit_count_bucket",
                "linkage_coverage_bucket",
            ):
                if not _registered_bucket(measurements.get(key)):
                    problems.append("named-public actor contains an unregistered bucket")
            if (
                measurements.get("commit_count_basis")
                != "git_primary_author_cluster_including_merges"
            ):
                problems.append("named-public actor contains an unregistered commit basis")
    authority = data.get("authority")
    authority_rows = authority.get("accounts") if isinstance(authority, Mapping) else None
    authority_bindings: set[tuple[Any, Any, Any]] = set()
    if not isinstance(authority_rows, list):
        problems.append("named-public authority accounts must be a list")
    else:
        for row in authority_rows:
            if not isinstance(row, Mapping):
                problems.append("named-public authority account must be an object")
                continue
            binding = (row.get("provider"), row.get("host"), row.get("account_id"))
            if binding in authority_bindings:
                problems.append("named-public authority binding is duplicated")
            authority_bindings.add(binding)
            if (
                row.get("provider") != project_provider
                or row.get("host") != project_host
                or row.get("project_id") != project_id
            ):
                problems.append("named-public authority binding does not match project")
            if (
                row.get("basis") != _NAMED_AUTHORITY_BASIS
                or row.get("scope") != _NAMED_AUTHORITY_SCOPE
                or row.get("assertion") != _NAMED_AUTHORITY_ASSERTION
            ):
                problems.append("named-public authority vocabulary is not registered")
    if actor_bindings != authority_bindings:
        problems.append("named-public authority must bind exactly the emitted accounts")
    return problems


def _masked_output_problems(data: Any) -> list[str]:
    """Reject identifiers reintroduced into the otherwise permissive precise tree."""

    if not isinstance(data, Mapping):
        return ["masked data must be an object"]
    measurements = data.get("measurements")
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for raw_key, value in node.items():
                key = str(raw_key)
                child = f"{path}.{key}"
                if _key_sensitive(key):
                    problems.append(f"masked measurements contain identifying key {child}")
                walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(measurements, "data.measurements")
    try:
        serialized = json.dumps(measurements, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        problems.append("masked measurements must be canonical finite JSON")
    else:
        if artifact_leaks(serialized):
            problems.append("masked measurements contain source-identifying material")
    return problems


def public_payload_leaks(payload: Mapping[str, Any]) -> list[str]:
    """Mode-aware disclosure checks used before public PR construction."""

    problems = artifact_leaks(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    profile = payload.get("privacy_profile")
    if profile not in PUBLIC_PROFILES:
        problems.append("controlled privacy profile cannot enter public intake")
        return sorted(set(problems))
    if payload.get("door") != "public-pr":
        problems.append("public intake requires door=public-pr")
    if profile == "aggregate":
        problems.extend(_aggregate_output_problems(payload.get("data")))
    elif profile == "named-public":
        data = payload.get("data")
        problems.extend(_named_output_problems(data))
        actors = data.get("actors") if isinstance(data, Mapping) else None
        if not isinstance(actors, list):
            problems.append("named-public actors must be a list")
        else:
            for actor in actors:
                account = actor.get("account") if isinstance(actor, Mapping) else None
                if _account_from_node(account) is None:
                    problems.append("named-public account URL/evidence is not canonical")

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for raw_key, value in node.items():
                key = str(raw_key).lower()
                child = f"{path}.{key}"
                if profile == "aggregate" and (
                    (
                        _key_sensitive(key)
                        and not (key == "path" and path.startswith("data.missingness["))
                    )
                    or key in {"actors", "accounts", "raw_material", "payload_sha256"}
                ):
                    problems.append(f"aggregate contains identifying key {child}")
                if profile == "named-public" and key in {
                    "actor_id",
                    "internal_actor_id",
                    "actor_pid",
                    "canonical_id",
                    "email",
                    "emails",
                    "raw_material",
                    "payload_sha256",
                }:
                    problems.append(f"named-public contains forbidden key {child}")
                walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif profile == "aggregate" and isinstance(node, str):
            if _EXACT_TIME_RE.fullmatch(node) or node.startswith(("http://", "https://", "git@")):
                problems.append(f"aggregate contains exact source value {path}")

    walk(payload.get("data"), "data")
    return sorted(set(problems))


def validate_v2_payload(payload: Mapping[str, Any], *, for_public_intake: bool) -> list[str]:
    violations: list[str] = _schema_errors("contribution-v2", payload)
    allowed_root = {
        "contribution_schema",
        "privacy_profile",
        "door",
        "purpose",
        "provenance_receipt_id",
        "transformation_spec_digest",
        "policy",
        "data",
    }
    extra = set(payload) - allowed_root
    if extra:
        violations.append(f"unknown contribution-v2 keys: {sorted(extra)}")
    profile = payload.get("privacy_profile")
    door = payload.get("door")
    if profile not in PROFILES:
        violations.append("invalid privacy_profile")
    if door not in DOORS:
        violations.append("invalid door")
    elif profile in PROFILES and door not in PROFILE_DOORS[str(profile)]:
        violations.append("privacy_profile and door are incompatible")
    receipt = payload.get("provenance_receipt_id")
    if not isinstance(receipt, str) or not _RECEIPT_RE.fullmatch(receipt):
        violations.append("invalid provenance_receipt_id")
    digest = payload.get("transformation_spec_digest")
    expected_digest = TRANSFORMATION_SPEC_DIGESTS.get(str(profile))
    if expected_digest is None or digest != expected_digest:
        violations.append("unexpected transformation_spec_digest")
    if payload.get("purpose") not in PURPOSES.values():
        violations.append("unexpected purpose")
    if not isinstance(payload.get("policy"), Mapping) or not isinstance(
        payload.get("data"), Mapping
    ):
        violations.append("policy and data must be objects")
    if profile == "aggregate":
        violations.extend(_aggregate_output_problems(payload.get("data")))
    elif profile == "named-public":
        violations.extend(_named_output_problems(payload.get("data")))
    elif profile == "masked":
        violations.extend(_masked_output_problems(payload.get("data")))
    if profile == "raw" and isinstance(payload.get("data"), Mapping):
        raw_material = payload["data"].get("raw_material")
        try:
            _assert_no_key_material(raw_material)
        except ValueError:
            violations.append("raw contribution contains credential material")
    if for_public_intake:
        violations.extend(public_payload_leaks(payload))
    return sorted(set(violations))


def validate_controlled_bundle(
    payload: object,
    sidecar: object,
    *,
    report: object | None = None,
    key_file: Path | None = None,
    key_fd: int | None = None,
    _pseudonym_key: bytes | None = None,
) -> list[str]:
    """Validate the controlled payload/sidecar pair and optional source report.

    Schema-valid files are insufficient when their receipt, profile, study, or
    digest bindings disagree.  The optional report check reconstructs the
    entire sidecar from the source report and recipient governance so a
    coordinated one-file edit cannot silently detach research provenance.
    """

    if not isinstance(payload, Mapping):
        return ["controlled payload must be an object"]
    if not isinstance(sidecar, Mapping):
        return ["controlled sidecar must be an object"]

    violations = validate_v2_payload(payload, for_public_intake=False)
    violations.extend(_schema_errors("controlled-sidecar-v1", sidecar))
    profile = payload.get("privacy_profile")
    if profile not in CONTROLLED_PROFILES:
        violations.append("controlled bundle requires masked or raw privacy_profile")
    if payload.get("door") not in PROFILE_DOORS.get(str(profile), frozenset()):
        violations.append("controlled bundle door is incompatible with privacy_profile")
    if sidecar.get("receipt_id") != payload.get("provenance_receipt_id"):
        violations.append("controlled sidecar receipt does not match payload")
    if sidecar.get("privacy_profile") != profile:
        violations.append("controlled sidecar profile does not match payload")
    if profile == "masked":
        source = sidecar.get("source")
        correspondence = source.get("actor_correspondence") if isinstance(source, Mapping) else None
        source_actor_ids = (
            frozenset(
                str(row.get("source_actor_id"))
                for row in correspondence
                if isinstance(row, Mapping)
                and isinstance(row.get("source_actor_id"), str)
                and row.get("source_actor_id")
            )
            if isinstance(correspondence, list)
            else frozenset()
        )
        data = payload.get("data")
        measurements = data.get("measurements") if isinstance(data, Mapping) else None
        if _contains_forbidden_string_value(measurements, source_actor_ids):
            violations.append("controlled masked payload contains a source actor identifier")
    try:
        _assert_no_key_material(sidecar.get("source"))
    except ValueError:
        violations.append("controlled sidecar source contains credential material")
    try:
        payload_digest = _sha256(payload)
    except (TypeError, ValueError):
        violations.append("controlled payload is not canonical finite JSON")
    else:
        if sidecar.get("payload_sha256") != payload_digest:
            violations.append("controlled sidecar payload digest does not match payload")

    governance = sidecar.get("governance")
    data = payload.get("data")
    research = data.get("research") if isinstance(data, Mapping) else None
    if isinstance(governance, Mapping) and isinstance(research, Mapping):
        if research.get("study_id") != governance.get("study_id"):
            violations.append("controlled study binding does not match governance")
        if profile == "masked":
            for key in ("key_id", "epoch"):
                if research.get(key) != governance.get(key):
                    violations.append(f"controlled masked {key} does not match governance")

    replay_key: bytes | None = None
    if profile == "masked" and report is not None:
        try:
            if _pseudonym_key is not None:
                if key_file is not None or key_fd is not None:
                    raise ValueError("masked replay key source is ambiguous")
                replay_key = _normalize_key(_pseudonym_key)
            else:
                replay_key = load_pseudonym_key(key_file=key_file, key_fd=key_fd)
        except (OSError, ValueError):
            violations.append("controlled masked replay requires one valid private key source")

    if report is not None:
        if not isinstance(report, Mapping):
            violations.append("controlled source report must be an object")
        elif profile in CONTROLLED_PROFILES and isinstance(governance, Mapping):
            try:
                _validate_report(report)
                if profile == "masked":
                    if replay_key is None:
                        raise ValueError("masked replay key is unavailable")
                    expected_data = _masked_data(report, key=replay_key, governance=governance)
                    if payload.get("data") != expected_data:
                        violations.append(
                            "controlled masked payload does not replay from source report and key"
                        )
                expected = _controlled_sidecar(
                    payload=payload,
                    report=report,
                    profile=str(profile),
                    governance=governance,
                    pseudonym_key=replay_key,
                )
            except (TypeError, ValueError):
                violations.append("controlled source report cannot reproduce the sidecar")
            else:
                if dict(sidecar) != expected:
                    violations.append("controlled sidecar does not match payload and source report")
    return sorted(set(violations))
