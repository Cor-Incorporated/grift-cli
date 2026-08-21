"""Observed vs not_observed. Zero is a legal observed value."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Observed:
    value: Any
    unit: str
    sample_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "observed",
            "value": self.value,
            "unit": self.unit,
        }
        if self.sample_size is not None:
            payload["sample_size"] = self.sample_size
        return payload


@dataclass(frozen=True)
class NotObserved:
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "not_observed", "reason": self.reason}


Observation = Observed | NotObserved
