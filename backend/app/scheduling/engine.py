"""Forward pass, summary rollup and CPM backward pass.

Faithful port of the C# engine (itself a port of the browser engine). The two
steps are iterated rather than done once because a dependency may point at a
summary, whose dates are themselves derived from its children.

The engine works on any objects that carry these attributes:
    id, level, mode (0 auto / 1 manual), duration, planned_start, planned_finish,
    percent_complete, dependencies -> list of objects with predecessor_id, type, lag
and it fills these in place:
    computed_start, computed_finish, total_float, is_critical, is_summary, wbs,
    computed_start_date, computed_finish_date
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from .work_calendar import WorkCalendar

MAX_PASSES = 30

# DependencyType
FS, SS, FF, SF = 0, 1, 2, 3
# ScheduleMode
AUTO, MANUAL = 0, 1


def round_away(x: float) -> int:
    """C# Math.Round(x, MidpointRounding.AwayFromZero) for non-negative x."""
    return int(math.floor(x + 0.5))


@dataclass
class ScheduleResult:
    has_cycle: bool
    message: str | None
    project_end: int
    project_end_date: date


@dataclass
class _Link:
    predecessor: Any
    type: int
    lag: int


# ---------------------------------------------------------------------------
#  Outline helpers - identical rules to the original outline grid
# ---------------------------------------------------------------------------
def is_summary(a: Sequence[Any], i: int) -> bool:
    return i + 1 < len(a) and a[i + 1].level > a[i].level


def descendants(a: Sequence[Any], i: int) -> list[int]:
    level = a[i].level
    out = []
    j = i + 1
    while j < len(a) and a[j].level > level:
        out.append(j)
        j += 1
    return out


def wbs_of(a: Sequence[Any], i: int) -> str:
    parts: list[int] = []
    level = a[i].level
    j = i
    while j >= 0:
        if a[j].level == level:
            n = 1
            k = j - 1
            while k >= 0:
                if a[k].level < level:
                    break
                if a[k].level == level:
                    n += 1
                k -= 1
            parts.insert(0, n)
            if level == 0:
                break
            level -= 1
        j -= 1
    return ".".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
def _build_predecessor_map(a: Sequence[Any], by_id: dict[int, Any]) -> list[list[_Link]]:
    result: list[list[_Link]] = []
    for act in a:
        links: list[_Link] = []
        for d in act.dependencies:
            pred = by_id.get(d.predecessor_id)
            if pred is not None:
                links.append(_Link(pred, int(d.type), int(d.lag)))
        result.append(links)
    return result


def _has_cycle(a: Sequence[Any], preds: list[list[_Link]]) -> bool:
    index = {act.id: i for i, act in enumerate(a)}
    state = [0] * len(a)  # 0 unseen, 1 on stack, 2 done
    cyclic = False

    def visit(i: int) -> None:
        nonlocal cyclic
        if cyclic:
            return
        if state[i] == 1:
            cyclic = True
            return
        if state[i] == 2:
            return
        state[i] = 1
        for link in preds[i]:
            pi = index.get(link.predecessor.id)
            if pi is not None:
                visit(pi)
        state[i] = 2

    for i in range(len(a)):
        if cyclic:
            break
        visit(i)
    return cyclic


def schedule(activities: Sequence[Any], calendar: WorkCalendar) -> ScheduleResult:
    """Schedules a project in place. `activities` must be in outline order (by sequence)."""
    n = len(activities)
    if n == 0:
        return ScheduleResult(False, None, 0, calendar.date_of(0))

    for i in range(n):
        activities[i].is_summary = is_summary(activities, i)
        activities[i].wbs = wbs_of(activities, i)
        for name in ("computed_start", "computed_finish", "total_float"):
            if not hasattr(activities[i], name):
                setattr(activities[i], name, 0)
        if not hasattr(activities[i], "is_critical"):
            activities[i].is_critical = False

    by_id = {a.id: a for a in activities}
    preds = _build_predecessor_map(activities, by_id)
    has_cycle = _has_cycle(activities, preds)

    for _pass in range(MAX_PASSES):
        moved = False

        # ---- leaves ----
        for i in range(n):
            t = activities[i]
            if t.is_summary:
                continue
            dur = max(0, int(t.duration))

            # A manually planned activity sits where its typed dates put it.
            if int(t.mode) == MANUAL and t.planned_start is not None:
                ms = calendar.index_of(t.planned_start)
                if t.planned_finish is not None:
                    mf = max(ms, calendar.index_of(t.planned_finish))
                else:
                    mf = ms + max(0, dur - 1)
                if t.computed_start != ms or t.computed_finish != mf:
                    t.computed_start, t.computed_finish, moved = ms, mf, True
                if t.planned_finish is not None:
                    t.duration = mf - ms + 1
                continue

            s = 0
            for link in preds[i]:
                q = link.predecessor
                q_fin = q.computed_finish
                if link.type == SS:
                    candidate = q.computed_start + link.lag
                elif link.type == FF:
                    candidate = q_fin + link.lag - max(0, dur - 1)
                elif link.type == SF:
                    candidate = q.computed_start + link.lag - max(0, dur - 1)
                else:  # FS
                    candidate = q_fin + 1 + link.lag
                if candidate > s:
                    s = candidate
            if s < 0:
                s = 0
            f = s + max(0, dur - 1)
            if t.computed_start != s or t.computed_finish != f:
                t.computed_start, t.computed_finish, moved = s, f, True

        # ---- summaries, deepest first ----
        for i in range(n - 1, -1, -1):
            t = activities[i]
            if not t.is_summary:
                continue
            kids = [j for j in descendants(activities, i) if not activities[j].is_summary]
            if not kids:
                continue
            s = min(activities[j].computed_start for j in kids)
            f = max(activities[j].computed_finish for j in kids)
            if t.computed_start != s or t.computed_finish != f:
                t.computed_start, t.computed_finish, moved = s, f, True
            t.duration = f - s + 1

            weight = sum(max(1, int(activities[j].duration)) for j in kids)
            t.percent_complete = 0 if weight == 0 else round_away(
                sum(float(activities[j].percent_complete) * max(1, int(activities[j].duration)) for j in kids) / weight
            )

        if not moved:
            break

    _critical_path(activities, preds)

    for a in activities:
        a.computed_start_date = calendar.date_of(a.computed_start)
        a.computed_finish_date = calendar.date_of(a.computed_finish)

    end = max(a.computed_finish for a in activities)
    return ScheduleResult(
        has_cycle=has_cycle,
        message="Circular dependency - dates are unreliable until the loop is broken." if has_cycle else None,
        project_end=end,
        project_end_date=calendar.date_of(end),
    )


# ---------------------------------------------------------------------------
#  Backward pass: late dates, total float, therefore the critical path
# ---------------------------------------------------------------------------
def _critical_path(a: Sequence[Any], preds: list[list[_Link]]) -> None:
    n = len(a)
    leaves = [i for i in range(n) if not a[i].is_summary]
    if not leaves:
        return

    end = max(a[i].computed_finish for i in leaves)
    late_finish = [end] * n
    INF = float("inf")

    successors: list[list[tuple[int, int, int]]] = [[] for _ in range(n)]
    index_of = {a[i].id: i for i in range(n)}
    for i in range(n):
        for link in preds[i]:
            pi = index_of.get(link.predecessor.id)
            if pi is not None:
                successors[pi].append((i, link.type, link.lag))

    for _pass in range(MAX_PASSES):
        changed = False
        for i in range(n - 1, -1, -1):
            if a[i].is_summary:
                continue
            lf: float = end if not successors[i] else INF
            for (si, stype, slag) in successors[i]:
                succ = a[si]
                dur = max(0, int(succ.duration))
                ls = late_finish[si] - max(0, dur - 1)
                own = max(0, int(a[i].duration) - 1)
                if stype == SS:
                    candidate = ls - slag + own
                elif stype == FF:
                    candidate = late_finish[si] - slag
                elif stype == SF:
                    candidate = ls - slag + own
                else:
                    candidate = ls - 1 - slag
                if candidate < lf:
                    lf = candidate
            if lf == INF:
                lf = end
            lf = int(lf)
            if late_finish[i] != lf:
                late_finish[i] = lf
                changed = True
        if not changed:
            break

    for i in range(n):
        t = a[i]
        if t.is_summary:
            t.total_float = 0
            t.is_critical = False
            continue
        t.total_float = late_finish[i] - t.computed_finish
        t.is_critical = t.total_float <= 0
