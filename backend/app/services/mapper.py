"""Turns a scheduled project into the shapes the UI consumes."""
from __future__ import annotations

from datetime import date

from ..models import Activity, Project
from ..scheduling import engine
from ..scheduling.engine import round_away
from ..scheduling.graph import successors
from ..scheduling.work_calendar import WorkCalendar
from ..schemas import ActivityOut, DependencyOut, PersonOut, ProjectSummary
from .rules import is_locked


def person_out(p) -> PersonOut:
    return PersonOut(id=p.id, name=p.name, email=p.email, role_id=p.role_id,
                     role_name=p.role.name if p.role else None)


def status_of(a: Activity, acts: list[Activity], index: int) -> str:
    today = date.today()
    if a.level == 0:
        kids = [acts[j] for j in engine.descendants(acts, index) if not acts[j].is_summary]
        pool = kids if kids else [a]
        if all(x.actual_finish is not None or x.percent_complete >= 100 for x in pool):
            return "Achieved"
        if a.target_date is not None and a.computed_finish_date > a.target_date:
            return "Past target"
        if a.computed_finish_date < today:
            return "Overdue"
        return "In progress" if any(x.actual_start is not None for x in pool) or a.percent_complete > 0 else "Not started"
    if a.is_summary:
        return "-"
    if a.actual_finish is not None or a.percent_complete >= 100:
        return "Done"
    if a.computed_finish_date < today:
        return "Late"
    if a.actual_start is not None or a.percent_complete > 0:
        return "Active"
    return "Due" if a.computed_start_date <= today else "Open"


def to_activity_dtos(acts: list[Activity], cal: WorkCalendar) -> list[ActivityOut]:
    out = []
    for i, a in enumerate(acts):
        succ = len(successors(acts, a))
        target_var = (a.computed_finish - cal.index_of(a.target_date)) if (a.level == 0 and a.target_date) else None
        finish_var = (cal.index_of(a.actual_finish) - a.computed_finish) if a.actual_finish else None
        deps = []
        for d in a.dependencies:
            pi = next((k for k, x in enumerate(acts) if x.id == d.predecessor_id), -1)
            deps.append(DependencyOut(
                id=d.id or 0, predecessor_id=d.predecessor_id,
                predecessor_wbs=acts[pi].wbs if pi >= 0 else "?",
                predecessor_name=acts[pi].name if pi >= 0 else "(missing)",
                type=d.type, lag=d.lag))
        out.append(ActivityOut(
            id=a.id, project_id=a.project_id, sequence=a.sequence, level=a.level, wbs=a.wbs,
            kind=a.kind_name, name=a.name, notes=a.notes, mode=a.mode, duration=a.duration,
            planned_start=a.computed_start_date, planned_finish=a.computed_finish_date,
            target_date=a.target_date, target_variance_days=target_var,
            actual_start=a.actual_start, actual_finish=a.actual_finish, finish_variance_days=finish_var,
            percent_complete=a.percent_complete, total_float=a.total_float, is_critical=a.is_critical,
            is_summary=a.is_summary, is_locked=is_locked(acts, i),
            is_independent=len(a.dependencies) == 0 and succ == 0,
            predecessor_count=len(a.dependencies), successor_count=succ,
            role_id=a.role_id, role_name=a.role.name if a.role else None,
            assignees=[person_out(x.person) for x in a.assignees if x.person is not None],
            dependencies=deps,
            baseline_start=a.baseline_start, baseline_finish=a.baseline_finish,
            status=status_of(a, acts, i),
        ))
    return out


def to_summary(p: Project, acts: list[Activity], result: engine.ScheduleResult) -> ProjectSummary:
    leaves = [a for a in acts if not a.is_summary]
    today = date.today()
    weight = sum(max(1, a.duration) for a in leaves)
    pct = 0 if weight == 0 else round_away(sum(float(a.percent_complete) * max(1, a.duration) for a in leaves) / weight)
    started = [a.actual_start for a in leaves if a.actual_start is not None]
    all_done = bool(leaves) and all(a.actual_finish is not None for a in leaves)
    finishes = [a.actual_finish for a in leaves if a.actual_finish is not None]
    return ProjectSummary(
        id=p.id, code=p.code, name=p.name, status=p.status,
        planned_start=p.planned_start, planned_end=p.planned_end,
        forecast_finish=result.project_end_date if acts else None,
        end_variance_days=(result.project_end_date - p.planned_end).days if (p.planned_end and acts) else None,
        actual_start=min(started) if started else None,
        actual_finish=max(finishes) if (all_done and finishes) else None,
        owner_name=p.owner.name if p.owner else None, owner_id=p.owner_id,
        organisation_name=p.organisation.name if p.organisation else None, organisation_id=p.organisation_id,
        team_size=len(p.team), team_ids=[t.person_id for t in p.team],
        holidays=sorted(h.date for h in p.holidays), notes=p.notes,
        milestone_count=sum(1 for a in acts if a.level == 0),
        activity_count=len(leaves),
        percent_complete=pct,
        late_count=sum(1 for a in leaves if a.computed_finish_date < today and a.actual_finish is None and a.percent_complete < 100),
        critical_count=sum(1 for a in leaves if a.is_critical),
        working_days=sum(max(0, a.duration) for a in leaves),
    )


def share_of(a: Activity) -> float:
    """A shared activity contributes only its fair share of days to each holder."""
    return a.duration / len(a.assignees) if len(a.assignees) > 1 else float(a.duration)
