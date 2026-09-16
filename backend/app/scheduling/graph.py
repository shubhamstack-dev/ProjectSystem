"""Queries over the link graph. An activity is dependent if anything drives it,
a driver if anything waits on it, and independent when neither is true."""
from __future__ import annotations

from typing import Any, Sequence

from .engine import descendants


def successors(all_: Sequence[Any], a: Any) -> list[Any]:
    return [x for x in all_ if any(d.predecessor_id == a.id for d in x.dependencies)]


def is_independent(all_: Sequence[Any], a: Any) -> bool:
    return len(a.dependencies) == 0 and not successors(all_, a)


def dependent_closure(all_: Sequence[Any], a: Any) -> set[int]:
    """Everything that transitively waits on this activity, including itself."""
    seen = {a.id}
    stack = [a.id]
    while stack:
        current = stack.pop()
        for s in all_:
            if any(d.predecessor_id == current for d in s.dependencies):
                if s.id not in seen:
                    seen.add(s.id)
                    stack.append(s.id)
    return seen


def eligible_predecessors(all_: Sequence[Any], a: Any) -> list[Any]:
    """Activities that may legally become predecessors of `a`: everything except
    itself, its own subtree, and anything already waiting on it."""
    blocked = dependent_closure(all_, a)
    idx = next((i for i, x in enumerate(all_) if x.id == a.id), -1)
    if idx >= 0:
        for j in descendants(all_, idx):
            blocked.add(all_[j].id)
    already = {d.predecessor_id for d in a.dependencies}
    return [x for x in all_ if x.id not in blocked and x.id not in already]
