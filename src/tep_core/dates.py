"""Date helpers shared by v0.6 observation windows."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

# Git stores the author timezone verbatim, so a broken client can leave an
# offset outside the +/-24h that `datetime.timezone` accepts — `requests`
# carries `2011-09-08T02:38:50+518:00`. The instant is still recorded exactly:
# `%aI` prints the author's local clock with its offset, so UTC is that clock
# minus the offset. Resolve it by arithmetic instead of aborting the run.
_OUT_OF_RANGE_OFFSET_RE = re.compile(r"^(?P<naive>.+?)(?P<sign>[+-])(?P<h>\d{1,3}):?(?P<m>\d{2})$")


def parse_day(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def _parse_out_of_range_offset(text: str) -> datetime:
    match = _OUT_OF_RANGE_OFFSET_RE.match(text)
    if match is None:
        raise ValueError(f"Invalid isoformat string: {text!r}")
    naive = datetime.fromisoformat(match.group("naive"))
    if naive.tzinfo is not None:
        raise ValueError(f"Invalid isoformat string: {text!r}")
    offset = timedelta(hours=int(match.group("h")), minutes=int(match.group("m")))
    if match.group("sign") == "-":
        offset = -offset
    return (naive - offset).replace(tzinfo=timezone.utc)


def parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _parse_out_of_range_offset(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_to_day(value: str) -> str:
    return parse_iso_utc(value).date().isoformat()
