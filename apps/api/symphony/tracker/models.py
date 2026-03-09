from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class IssueBlocker:
    id: str | None
    identifier: str | None
    state: str | None


@dataclass(slots=True, frozen=True)
class Issue:
    id: str
    identifier: str
    title: str
    description: str | None
    priority: int | None
    state: str
    branch_name: str | None
    url: str | None
    labels: tuple[str, ...]
    blocked_by: tuple[IssueBlocker, ...]
    created_at: datetime | None
    updated_at: datetime | None
