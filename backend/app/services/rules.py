"""Once work has actually started on an activity, its plan is history: the
planned dates, duration, predecessors and scheduling mode stop being editable,
and nothing carrying recorded work may be deleted or moved."""
from __future__ import annotations

from typing import Sequence

from ..models import Activity, Project
from ..scheduling.engine import descendants


class RuleViolation(Exception):
    """Thrown when a rule refuses an operation. The API turns this into a 409."""

    def __init__(self, message: str, blockers: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.blockers = blockers or []


class NotFound(Exception):
    pass


def is_locked(ordered: Sequence[Activity], index: int) -> bool:
    """Locked once this row, or anything beneath it, has recorded work."""
    if ordered[index].has_actuals:
        return True
    return any(ordered[j].has_actuals for j in descendants(ordered, index))


def started_under(ordered: Sequence[Activity], index: int) -> list[Activity]:
    """Rows in a subtree that carry recorded work - used to explain a refusal."""
    found = []
    if ordered[index].has_actuals:
        found.append(ordered[index])
    for j in descendants(ordered, index):
        if ordered[j].has_actuals:
            found.append(ordered[j])
    return found


def project_has_actuals(p: Project) -> bool:
    return any(a.has_actuals for a in p.activities)
