"""Synthetic tracker lifecycle fixture. Not external measurement."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from tep_core.dates import parse_iso_utc
from tep_core.digest import file_digest
from tep_core.observation import Observed
from tep_core.secrets_guard import InputValidationError

FIXTURE_KIND = "synthetic_contract"
_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)
_RECORD_TYPES = frozenset({"issue", "pull_request", "release"})
_STATUSES = {
    "issue": frozenset({"open", "in_progress", "closed"}),
    "pull_request": frozenset({"open", "review", "merged", "closed"}),
    "release": frozenset({"released"}),
}
_KNOWN_COLUMNS = frozenset(
    {
        "fixture_kind",
        "record_type",
        "record_id",
        "project_id",
        "created_at",
        "in_progress_at",
        "first_review_at",
        "merged_at",
        "closed_at",
        "release_at",
        "status",
        "linked_record_id",
        "notes",
    }
)


@dataclass(frozen=True)
class LifecycleRow:
    fixture_kind: str
    record_type: str
    record_id: str
    project_id: str
    created_at: datetime | None
    in_progress_at: datetime | None
    first_review_at: datetime | None
    merged_at: datetime | None
    closed_at: datetime | None
    release_at: datetime | None
    status: str
    linked_record_id: str


@dataclass(frozen=True)
class LifecycleBundle:
    rows: tuple[LifecycleRow, ...]
    digest: str
    fixture_kind: str = FIXTURE_KIND


def _parse_time(value: str, *, path: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", text):
        raise InputValidationError(f"{path}: must include an explicit timezone")
    try:
        return parse_iso_utc(text)
    except ValueError as exc:
        raise InputValidationError(f"{path}: must be ISO-8601 with timezone") from exc


def _hours(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600.0


def load_tracker_lifecycle(
    path: Path, *, event_window: tuple[datetime, datetime] | None = None
) -> LifecycleBundle:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        if columns != _KNOWN_COLUMNS:
            missing_columns = sorted(_KNOWN_COLUMNS - columns)
            extra_columns = sorted(columns - _KNOWN_COLUMNS)
            raise InputValidationError(
                "tracker lifecycle: columns mismatch "
                f"missing={missing_columns}, extra={extra_columns}"
            )
        rows = list(reader)
    if not rows:
        raise InputValidationError("tracker lifecycle fixture is empty")
    parsed: list[LifecycleRow] = []
    for index, row in enumerate(rows):
        kind = (row.get("fixture_kind") or "").strip()
        if kind != FIXTURE_KIND:
            raise InputValidationError(
                f"tracker_lifecycle[{index}]: fixture_kind must be {FIXTURE_KIND}"
            )
        record_type = (row.get("record_type") or "").strip()
        record_id = (row.get("record_id") or "").strip()
        project_id = (row.get("project_id") or "").strip()
        status = (row.get("status") or "").strip()
        if record_type not in _RECORD_TYPES:
            raise InputValidationError(f"tracker_lifecycle[{index}]: unknown record_type")
        if not record_id or not project_id:
            raise InputValidationError(
                f"tracker_lifecycle[{index}]: record_id and project_id are required"
            )
        if status not in _STATUSES[record_type]:
            raise InputValidationError(
                f"tracker_lifecycle[{index}]: status is invalid for {record_type}"
            )
        item = LifecycleRow(
            fixture_kind=kind,
            record_type=record_type,
            record_id=record_id,
            project_id=project_id,
            created_at=_parse_time(
                row.get("created_at") or "", path=f"tracker_lifecycle[{index}].created_at"
            ),
            in_progress_at=_parse_time(
                row.get("in_progress_at") or "",
                path=f"tracker_lifecycle[{index}].in_progress_at",
            ),
            first_review_at=_parse_time(
                row.get("first_review_at") or "",
                path=f"tracker_lifecycle[{index}].first_review_at",
            ),
            merged_at=_parse_time(
                row.get("merged_at") or "", path=f"tracker_lifecycle[{index}].merged_at"
            ),
            closed_at=_parse_time(
                row.get("closed_at") or "", path=f"tracker_lifecycle[{index}].closed_at"
            ),
            release_at=_parse_time(
                row.get("release_at") or "", path=f"tracker_lifecycle[{index}].release_at"
            ),
            status=status,
            linked_record_id=(row.get("linked_record_id") or "").strip(),
        )
        _validate_lifecycle_row(item, index=index)
        if event_window is not None:
            start, end = event_window
            for stamp in _row_timestamps(item):
                if stamp < start or stamp >= end:
                    raise InputValidationError(
                        f"tracker_lifecycle[{index}]: timestamp outside event window "
                        f"({start.date().isoformat()} / {end.date().isoformat()})"
                    )
        parsed.append(item)
    _validate_links(parsed)
    ordered = tuple(
        sorted(
            parsed,
            key=lambda item: (
                item.project_id,
                (item.created_at or _EPOCH),
                item.record_id,
            ),
        )
    )
    return LifecycleBundle(rows=ordered, digest=file_digest(path), fixture_kind=FIXTURE_KIND)


def _row_timestamps(item: LifecycleRow) -> tuple[datetime, ...]:
    return tuple(
        value
        for value in (
            item.created_at,
            item.in_progress_at,
            item.first_review_at,
            item.merged_at,
            item.closed_at,
            item.release_at,
        )
        if value is not None
    )


def _ordered_non_null(values: tuple[datetime | None, ...], *, path: str) -> None:
    present = [value for value in values if value is not None]
    if any(right < left for left, right in zip(present, present[1:])):
        raise InputValidationError(f"{path}: timestamps are out of order (negative duration)")


def _validate_lifecycle_row(item: LifecycleRow, *, index: int) -> None:
    path = f"tracker_lifecycle[{index}]"
    if item.created_at is None:
        raise InputValidationError(f"{path}: created_at is required")
    if item.record_type == "issue":
        if any((item.first_review_at, item.merged_at, item.release_at)):
            raise InputValidationError(f"{path}: issue contains incompatible timestamps")
        if item.status == "closed" and item.closed_at is None:
            raise InputValidationError(f"{path}: closed issue requires closed_at")
        if item.status == "in_progress" and item.in_progress_at is None:
            raise InputValidationError(f"{path}: in_progress issue requires in_progress_at")
        if item.status == "open" and any((item.in_progress_at, item.closed_at)):
            raise InputValidationError(f"{path}: open issue contains terminal timestamps")
        if item.status == "in_progress" and item.closed_at is not None:
            raise InputValidationError(f"{path}: in_progress issue contains closed_at")
        _ordered_non_null((item.created_at, item.in_progress_at, item.closed_at), path=path)
    elif item.record_type == "pull_request":
        if item.in_progress_at is not None or item.release_at is not None:
            raise InputValidationError(f"{path}: pull_request contains incompatible timestamps")
        if item.status == "merged" and item.merged_at is None:
            raise InputValidationError(f"{path}: merged pull_request requires merged_at")
        if item.status == "review" and item.first_review_at is None:
            raise InputValidationError(f"{path}: review pull_request requires first_review_at")
        if item.status == "open" and any((item.first_review_at, item.merged_at, item.closed_at)):
            raise InputValidationError(f"{path}: open pull_request contains later timestamps")
        if item.status == "review" and any((item.merged_at, item.closed_at)):
            raise InputValidationError(f"{path}: review pull_request contains terminal timestamps")
        if item.status == "closed":
            if item.closed_at is None:
                raise InputValidationError(f"{path}: closed pull_request requires closed_at")
            if item.merged_at is not None:
                raise InputValidationError(f"{path}: closed pull_request contains merged_at")
        _ordered_non_null(
            (item.created_at, item.first_review_at, item.merged_at, item.closed_at), path=path
        )
    else:
        if (
            any((item.in_progress_at, item.first_review_at, item.merged_at, item.closed_at))
            or item.release_at is None
        ):
            raise InputValidationError(f"{path}: release requires only created_at/release_at")
        _ordered_non_null((item.created_at, item.release_at), path=path)


def _validate_links(rows: list[LifecycleRow]) -> None:
    by_key: dict[tuple[str, str], LifecycleRow] = {}
    for row in rows:
        key = (row.project_id, row.record_id)
        if key in by_key:
            raise InputValidationError(
                f"tracker lifecycle: duplicate record_id {row.project_id}/{row.record_id}"
            )
        by_key[key] = row
    for row in rows:
        if not row.linked_record_id:
            continue
        target = by_key.get((row.project_id, row.linked_record_id))
        if target is None:
            raise InputValidationError(
                f"tracker lifecycle: broken linked_record_id {row.linked_record_id}"
            )
        if {row.record_type, target.record_type} != {"issue", "pull_request"}:
            raise InputValidationError(
                "tracker lifecycle: links must connect an issue and pull_request in one project"
            )


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def summarize_lifecycle(bundle: LifecycleBundle) -> dict[str, Any]:
    grouped: dict[str, list[LifecycleRow]] = defaultdict(list)
    for row in bundle.rows:
        grouped[row.project_id].append(row)
    projects: dict[str, Any] = {}
    for project_id, rows in grouped.items():
        projects[project_id] = _project_metrics(rows)
    return {
        "kind": "observed",
        "unit": "profile",
        "fixture_kind": FIXTURE_KIND,
        "digest": bundle.digest,
        "sample_size": len(bundle.rows),
        "projects": projects,
        "limitations": [
            "synthetic_contract fixture. Not an external observation.",
            "Not PM suitability, delivery speed, or production DORA.",
        ],
    }


def _project_metrics(rows: list[LifecycleRow]) -> dict[str, Any]:
    active_days = {
        value.date()
        for row in rows
        for value in (
            row.created_at,
            row.in_progress_at,
            row.first_review_at,
            row.merged_at,
            row.closed_at,
            row.release_at,
        )
        if value is not None
    }
    issues = [row for row in rows if row.record_type == "issue"]
    prs = [row for row in rows if row.record_type == "pull_request"]
    releases = [row for row in rows if row.record_type == "release"]
    issue_to_progress = [
        hours
        for hours in (_hours(row.created_at, row.in_progress_at) for row in issues)
        if hours is not None
    ]
    issue_to_close = [
        hours
        for hours in (_hours(row.created_at, row.closed_at) for row in issues)
        if hours is not None
    ]
    pr_to_review = [
        hours
        for hours in (_hours(row.created_at, row.first_review_at) for row in prs)
        if hours is not None
    ]
    pr_to_merge = [
        hours
        for hours in (_hours(row.created_at, row.merged_at) for row in prs)
        if hours is not None
    ]
    linked_issues = sum(1 for row in issues if row.linked_record_id)
    linked_prs = sum(1 for row in prs if row.linked_record_id)
    release_times = sorted(row.release_at for row in releases if row.release_at is not None)
    release_interval: dict[str, Any]
    if len(release_times) < 2:
        release_interval = {
            "kind": "not_proven",
            "reason": "fewer_than_two_releases",
            "n": len(release_times),
        }
    else:
        gaps = [
            (release_times[index + 1] - release_times[index]).total_seconds() / 86400
            for index in range(len(release_times) - 1)
        ]
        release_interval = Observed(round(median(gaps), 4), "days", sample_size=len(gaps)).to_dict()
    return {
        "active_days": Observed(len(active_days), "days").to_dict(),
        "issue_created_to_in_progress_median_hours": _maybe_hours(issue_to_progress),
        "issue_created_to_closed_median_hours": _maybe_hours(issue_to_close),
        "pr_created_to_first_review_median_hours": _maybe_hours(pr_to_review),
        "pr_created_to_merged_median_hours": _maybe_hours(pr_to_merge),
        "release_count": Observed(len(releases), "releases").to_dict(),
        "release_interval_days": release_interval,
        "linked_issue_share": Observed(
            round(linked_issues / len(issues), 4) if issues else 0.0,
            "ratio",
            sample_size=len(issues),
        ).to_dict(),
        "linked_pr_share": Observed(
            round(linked_prs / len(prs), 4) if prs else 0.0,
            "ratio",
            sample_size=len(prs),
        ).to_dict(),
        "issue_to_close_median_hours": _maybe_hours(issue_to_close)["value"]
        if issue_to_close
        else None,
        "pr_to_merge_median_hours": _maybe_hours(pr_to_merge)["value"] if pr_to_merge else None,
    }


def _maybe_hours(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"kind": "not_observed", "reason": "timestamp_absent"}
    return Observed(float(median(values)), "hours", sample_size=len(values)).to_dict()
