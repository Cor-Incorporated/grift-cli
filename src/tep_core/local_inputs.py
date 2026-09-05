"""Dispatch local forge/tracker files. JSON v1, GH Archive ndjson, or CSV."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tep_core.archive_events import ArchiveBundle, load_archive_events
from tep_core.forge import ForgeExport, load_forge_export
from tep_core.secrets_guard import InputValidationError
from tep_core.source_binding import SourceBinding, assert_binding_matches
from tep_core.tracker import TrackerExport, load_tracker_export
from tep_core.tracker_lifecycle import LifecycleBundle, load_tracker_lifecycle


@dataclass(frozen=True)
class ForgeInput:
    digest: str
    export: ForgeExport | None = None
    archive: ArchiveBundle | None = None
    source_format: str = "tep-forge-export-v1"


@dataclass(frozen=True)
class TrackerInput:
    digest: str
    export: TrackerExport | None = None
    lifecycle: LifecycleBundle | None = None
    source_format: str = "tep-tracker-export-v1"
    fixture_kind: str | None = None


def _first_nonempty_line(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                return text
    return ""


def _window_bounds(event_window: tuple[str, str] | None) -> tuple[datetime, datetime] | None:
    if event_window is None:
        return None
    start_text, end_text = event_window
    start = datetime.fromisoformat(start_text + "T00:00:00+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_text + "T00:00:00+00:00").astimezone(timezone.utc)
    if start >= end:
        raise InputValidationError("--event-window START must be earlier than END")
    return start, end


def load_forge_input(
    path: Path | None,
    *,
    event_window: tuple[str, str] | None = None,
    expected_binding: SourceBinding | None = None,
    require_bound: bool = False,
) -> ForgeInput | None:
    if path is None:
        return None
    if not path.is_file():
        raise InputValidationError("forge-export file not found")
    head = _first_nonempty_line(path)
    if '"event_type"' in head or path.suffix == ".ndjson":
        if require_bound or expected_binding is not None:
            raise InputValidationError(
                "GH Archive NDJSON is a benchmark collection, not a target-bound subject export"
            )
        bounds = _window_bounds(event_window)
        if bounds is None:
            archive = load_archive_events(path)
        else:
            archive = load_archive_events(path, window_start=bounds[0], window_end=bounds[1])
        return ForgeInput(
            digest=archive.digest,
            archive=archive,
            source_format="event-observation-ndjson",
        )
    export = load_forge_export(path)
    if require_bound and export.binding is None:
        raise InputValidationError("forge export is unbound; tep-forge-export-v2 is required")
    if expected_binding is not None:
        assert_binding_matches(export.binding, expected_binding)
    return ForgeInput(digest=export.digest, export=export, source_format=export.schema_version)


def load_tracker_input(
    path: Path | None,
    *,
    event_window: tuple[str, str] | None = None,
    expected_binding: SourceBinding | None = None,
    require_bound: bool = False,
) -> TrackerInput | None:
    if path is None:
        return None
    if not path.is_file():
        raise InputValidationError("tracker-export file not found")
    head = _first_nonempty_line(path)
    if path.suffix == ".csv" or head.startswith("fixture_kind"):
        if require_bound or expected_binding is not None:
            raise InputValidationError(
                "tracker lifecycle CSV is a synthetic benchmark, not a target-bound subject export"
            )
        lifecycle = load_tracker_lifecycle(path, event_window=_window_bounds(event_window))
        return TrackerInput(
            digest=lifecycle.digest,
            lifecycle=lifecycle,
            source_format="tracker-lifecycle-csv",
            fixture_kind=lifecycle.fixture_kind,
        )
    export = load_tracker_export(path)
    if require_bound and export.binding is None:
        raise InputValidationError("tracker export is unbound; tep-tracker-export-v2 is required")
    if expected_binding is not None:
        assert_binding_matches(export.binding, expected_binding)
    return TrackerInput(digest=export.digest, export=export, source_format=export.schema_version)
