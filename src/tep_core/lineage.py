"""Lineage: has_upstream_lineage = is_fork OR bool(parent)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lineage:
    is_fork: bool = False
    parent: str | None = None

    @property
    def has_upstream_lineage(self) -> bool:
        return self.is_fork or bool(self.parent)

    def to_dict(self) -> dict[str, object]:
        return {
            "is_fork": self.is_fork,
            "parent": self.parent,
            "has_upstream_lineage": self.has_upstream_lineage,
        }
