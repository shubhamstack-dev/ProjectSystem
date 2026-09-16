"""Loading, scheduling and mutating a plan. Every write goes through here so the
lock rules and the audit trail cannot be bypassed by a router."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (Activity, ActivityAssignee, ActivityDependency, DEP_TYPE_NAMES, MODE_NAMES,
                      Person, Project, ProjectTeamMember)
from ..scheduling import engine
from ..scheduling.graph import dependent_closure
from ..scheduling.work_calendar import WorkCalendar
from ..schemas import ActivityCreate, ActivityUpdate, DependencyIn
from . import audit
from .rules import NotFound, RuleViolation, is_locked, started_under

AUTO, MANUAL = 0, 1


# ---------------------------------------------------------------------------
#  Loading and scheduling
# ---------------------------------------------------------------------------
def load(db: Session, project_id: int) -> Project | None:
    return db.execute(
        select(Project)
        .options(
            selectinload(Project.holidays),
            selectinload(Project.owner),
            selectinload(Project.organisation),
            selectinload(Project.team).selectinload(ProjectTeamMember.person),
            selectinload(Project.activities).selectinload(Activity.dependencies),
            selectinload(Project.activities).selectinload(Activity.assignees)
                .selectinload(ActivityAssignee.person).selectinload(Person.role),
            selectinload(Project.activities).selectinload(Activity.role),
        )
        .where(Project.id == project_id)
    ).scalar_one_or_none()


def load_required(db: Session, project_id: int) -> Project:
    p = load(db, project_id)
    if p is None:
        raise NotFound(f"Project {project_id} not found.")
    return p


def ordered(p: Project) -> list[Activity]:
    return sorted(p.activities, key=lambda a: a.sequence)


def calendar_for(p: Project) -> WorkCalendar:
    return WorkCalendar(p.planned_start, [h.date for h in p.holidays])


def schedule(p: Project) -> tuple[list[Activity], engine.ScheduleResult]:
    """Schedules in memory and returns the ordered activities with computed fields filled."""
    acts = ordered(p)
    result = engine.schedule(acts, calendar_for(p))
    return acts, result


def _resequence(acts: list[Activity]) -> None:
    for i, a in enumerate(acts):
        a.sequence = i


# ---------------------------------------------------------------------------
#  Create
# ---------------------------------------------------------------------------
def _resolve_insert_position(acts: list[Activity], after_id: int | None, level: int) -> int:
    if not acts:
        return 0
    at = next((i for i, a in enumerate(acts) if a.id == after_id), -1) if after_id is not None else len(acts) - 1
    if at < 0:
        at = len(acts) - 1

    if level == 0:
        top = at
        while top > 0 and acts[top].level > 0:
            top -= 1
        return top + 1 + len(engine.descendants(acts, top))
    if acts[at].level < level:
        return at + 1 + len(engine.descendants(acts, at))
    sib = at
    while sib > 0 and acts[sib].level > level:
        sib -= 1
    return sib + 1 + len(engine.descendants(acts, sib))


def add_activity(db: Session, req: ActivityCreate, who: str) -> Activity:
    project = load_required(db, req.project_id)
    acts = ordered(project)
    level = max(0, min(2, req.level))

    if level > 0 and not acts:
        raise RuleViolation("A task must sit under a milestone. Add a milestone to this project first.")

    insert_at = _resolve_insert_position(acts, req.after_activity_id, level)

    activity = Activity(
        project_id=project.id,
        level=level,
        name=req.name.strip() if req.name and req.name.strip() else "New " + ["Milestone", "Task", "Subtask"][level],
        duration=max(0, req.duration),
        notes=req.notes,
        role_id=req.role_id,
        target_date=req.target_date if level == 0 else None,
        mode=MANUAL if req.planned_start else AUTO,
        planned_start=req.planned_start,
        planned_finish=req.planned_finish,
    )
    for a in acts[insert_at:]:
        a.sequence += 1
    activity.sequence = insert_at

    db.add(activity)
    db.flush()  # gives activity.id

    for pid in dict.fromkeys(req.assignee_ids or []):
        db.add(ActivityAssignee(activity_id=activity.id, person_id=pid))

    acts.insert(insert_at, activity)
    for d in req.dependencies or []:
        _add_dependency_checked(db, acts, activity, d)

    parts = [
        f"planned {req.planned_start} -> {req.planned_finish}" if req.planned_start else f"duration {activity.duration} wd",
        f"{len(req.dependencies)} dependency(s)" if req.dependencies else None,
        f"target {req.target_date}" if req.target_date else None,
    ]
    audit.record(db, who, "Created", activity.kind_name, activity.name,
                 "; ".join(p for p in parts if p), project, activity.id)
    db.commit()
    return activity


# ---------------------------------------------------------------------------
#  Update - honours the lock
# ---------------------------------------------------------------------------
def update_activity(db: Session, activity_id: int, req: ActivityUpdate, who: str) -> Activity:
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise NotFound(f"Activity {activity_id} not found.")
    project = load_required(db, activity.project_id)
    acts = ordered(project)
    index = next(i for i, a in enumerate(acts) if a.id == activity_id)
    activity = acts[index]
    locked = is_locked(acts, index)
    had_actuals = activity.has_actuals
    changes: list[str | None] = []

    if req.name is not None and req.name != activity.name:
        changes.append(audit.change("name", activity.name, req.name))
        activity.name = req.name

    # ---- plan fields: refused outright once work has started ----
    wants_plan_change = (req.mode is not None or req.duration is not None or req.planned_start is not None
                         or req.planned_finish is not None or req.target_date is not None
                         or req.dependencies is not None)
    if wants_plan_change and locked:
        blockers = [x.name for x in started_under(acts, index)]
        audit.record(db, who, "EditRefused", activity.kind_name, activity.name,
                     "plan locked; work recorded on " + ", ".join(blockers), project, activity.id)
        db.commit()
        raise RuleViolation(
            f"'{activity.name}' has recorded work, so its planned dates, duration and dependencies are locked. "
            "Clear the actual dates first if it genuinely needs replanning.", blockers)

    if not locked:
        if req.mode is not None and req.mode != activity.mode:
            changes.append(audit.change("scheduling", MODE_NAMES[activity.mode], MODE_NAMES[req.mode]))
            activity.mode = req.mode
            if activity.mode == AUTO:
                activity.planned_start = None
                activity.planned_finish = None
        if req.planned_start is not None:
            changes.append(audit.change("planned start", activity.planned_start, req.planned_start))
            activity.planned_start = req.planned_start
            activity.mode = MANUAL
        if req.planned_finish is not None:
            pf = req.planned_finish
            if activity.planned_start is not None and pf < activity.planned_start:
                pf = activity.planned_start
            changes.append(audit.change("planned finish", activity.planned_finish, pf))
            activity.planned_finish = pf
            activity.mode = MANUAL
        if req.duration is not None:
            changes.append(audit.change("duration", activity.duration, req.duration))
            activity.duration = max(0, req.duration)
        if req.target_date is not None and activity.level == 0:
            changes.append(audit.change("target", activity.target_date, req.target_date))
            activity.target_date = req.target_date
        if req.dependencies is not None:
            before = _describe_dependencies(acts, activity)
            for d in list(activity.dependencies):
                db.delete(d)
            activity.dependencies.clear()
            db.flush()
            for d in req.dependencies:
                _add_dependency_checked(db, acts, activity, d)
            changes.append(audit.change("depends on", before, _describe_dependencies(acts, activity)))

    # ---- actuals are always editable: they are the record of what happened ----
    new_start = None if req.clear_actual_start else (req.actual_start if req.actual_start is not None else activity.actual_start)
    new_finish = None if req.clear_actual_finish else (req.actual_finish if req.actual_finish is not None else activity.actual_finish)
    if new_start != activity.actual_start:
        changes.append(audit.change("actual start", activity.actual_start, new_start))
        activity.actual_start = new_start
    if new_finish != activity.actual_finish:
        changes.append(audit.change("actual finish", activity.actual_finish, new_finish))
        activity.actual_finish = new_finish
        if activity.actual_finish is not None:
            activity.percent_complete = 100
            if activity.actual_start is None:
                activity.actual_start = activity.actual_finish
    if req.percent_complete is not None and activity.actual_finish is None:
        changes.append(audit.change("progress", f"{activity.percent_complete}%", f"{req.percent_complete}%"))
        activity.percent_complete = max(0, min(100, req.percent_complete))

    if req.notes is not None and req.notes != (activity.notes or ""):
        changes.append("note added" if activity.notes is None else "note edited")
        activity.notes = req.notes

    new_role = None if req.clear_role else (req.role_id if req.role_id is not None else activity.role_id)
    if new_role != activity.role_id:
        changes.append(audit.change("role", activity.role_id, new_role))
        activity.role_id = new_role

    if req.assignee_ids is not None:
        before = ", ".join(str(x.person_id) for x in activity.assignees)
        for x in list(activity.assignees):
            db.delete(x)
        activity.assignees.clear()
        db.flush()
        for pid in dict.fromkeys(req.assignee_ids):
            db.add(ActivityAssignee(activity_id=activity.id, person_id=pid))
        changes.append(audit.change("assigned to", before, ", ".join(str(x) for x in req.assignee_ids)))

    # The first actual pins an auto activity to where it currently sits, so an
    # upstream change cannot move work that has already begun.
    if not had_actuals and activity.has_actuals and activity.mode == AUTO:
        sched, _ = schedule(project)
        me = next(a for a in sched if a.id == activity.id)
        activity.mode = MANUAL
        activity.planned_start = me.computed_start_date
        activity.planned_finish = me.computed_finish_date
        audit.record(db, who, "PlanLocked", activity.kind_name, activity.name,
                     f"pinned to {activity.planned_start} -> {activity.planned_finish}", project, activity.id)

    detail = "; ".join(c for c in changes if c)
    if detail:
        audit.record(db, who, "Edited", activity.kind_name, activity.name, detail, project, activity.id)
    db.commit()
    return activity


# ---------------------------------------------------------------------------
#  Delete - refused where work has started
# ---------------------------------------------------------------------------
def delete_activity(db: Session, activity_id: int, who: str) -> None:
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise NotFound(f"Activity {activity_id} not found.")
    project = load_required(db, activity.project_id)
    acts = ordered(project)
    index = next(i for i, a in enumerate(acts) if a.id == activity_id)
    activity = acts[index]

    started = started_under(acts, index)
    if started:
        audit.record(db, who, "DeleteRefused", activity.kind_name, activity.name,
                     f"work recorded on {len(started)} item(s)", project, activity.id)
        db.commit()
        raise RuleViolation(
            f"'{activity.name}' cannot be deleted: work has been recorded against it or something beneath it. "
            "Deleting it would destroy the record of that work.",
            [f"{x.name} (started {x.actual_start})" for x in started])

    subtree = [activity] + [acts[j] for j in engine.descendants(acts, index)]
    ids = {a.id for a in subtree}
    incoming = db.execute(
        select(ActivityDependency).where(
            ActivityDependency.predecessor_id.in_(ids), ActivityDependency.activity_id.not_in(ids))
    ).scalars().all()
    if incoming:
        raise RuleViolation(f"'{activity.name}' still drives {len(incoming)} other activity(s). Remove those links first.")

    for a in subtree:
        db.delete(a)
    remaining = [a for a in acts if a.id not in ids]
    _resequence(remaining)
    audit.record(db, who, "Deleted", activity.kind_name, activity.name,
                 f"with {len(subtree) - 1} item(s) beneath it" if len(subtree) > 1 else None, project, None)
    db.commit()


# ---------------------------------------------------------------------------
#  Move - reorder and re-parent (was 'not ported yet' in the C# version)
# ---------------------------------------------------------------------------
def move_activity(db: Session, activity_id: int, direction: str, who: str) -> None:
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise NotFound(f"Activity {activity_id} not found.")
    project = load_required(db, activity.project_id)
    acts = ordered(project)
    i = next(k for k, a in enumerate(acts) if a.id == activity_id)
    activity = acts[i]

    started = started_under(acts, i)
    if started:
        audit.record(db, who, "MoveRefused", activity.kind_name, activity.name,
                     f"work recorded on {len(started)} item(s)", project, activity.id)
        db.commit()
        raise RuleViolation(f"'{activity.name}' has recorded work beneath it, so it cannot be moved.",
                            [x.name for x in started])

    block = [activity] + [acts[j] for j in engine.descendants(acts, i)]
    rest = acts[:i] + acts[i + len(block):]
    level = activity.level

    if direction == "up":
        # previous sibling at the same level (skip over deeper rows)
        k = i - 1
        while k >= 0 and acts[k].level > level:
            k -= 1
        if k < 0 or acts[k].level < level:
            raise RuleViolation("Already the first item at this level.")
        new = acts[:k] + block + acts[k:i] + acts[i + len(block):]
    elif direction == "down":
        j = i + len(block)
        if j >= len(acts) or acts[j].level != level:
            raise RuleViolation("Already the last item at this level.")
        next_block = [acts[j]] + [acts[m] for m in engine.descendants(acts, j)]
        new = acts[:i] + next_block + block + acts[j + len(next_block):]
    elif direction == "indent":
        if level >= 2:
            raise RuleViolation("Subtasks are the deepest level.")
        if max(a.level for a in block) >= 2:
            raise RuleViolation("This task has subtasks, so it cannot go any deeper.")
        if i == 0 or acts[i - 1].level < level:
            raise RuleViolation("Nothing above to indent under.")
        for a in block:
            a.level += 1
        new = acts
    elif direction == "outdent":
        if level <= 0:
            raise RuleViolation("Milestones are the top level.")
        # find the parent, then place the block after the parent's subtree
        parent = i - 1
        while parent >= 0 and acts[parent].level >= level:
            parent -= 1
        end_of_parent = parent + 1 + len(engine.descendants(acts, parent))
        for a in block:
            a.level -= 1
        tail = acts[i + len(block):end_of_parent]
        new = acts[:i] + tail + block + acts[end_of_parent:]
    else:
        raise RuleViolation("direction must be up, down, indent or outdent.")

    _resequence(new)
    audit.record(db, who, "Moved", activity.kind_name, activity.name, direction, project, activity.id)
    db.commit()


# ---------------------------------------------------------------------------
#  Dependencies
# ---------------------------------------------------------------------------
def _add_dependency_checked(db: Session, acts: list[Activity], activity: Activity, d: DependencyIn) -> None:
    if d.predecessor_id == activity.id:
        raise RuleViolation("An activity cannot depend on itself.")
    pred = next((a for a in acts if a.id == d.predecessor_id), None)
    if pred is None:
        raise RuleViolation(f"Predecessor {d.predecessor_id} is not in this project.")
    if d.predecessor_id in dependent_closure(acts, activity):
        raise RuleViolation(f"'{pred.name}' already waits on '{activity.name}', so this link would create a loop.")
    link = ActivityDependency(activity_id=activity.id, predecessor_id=d.predecessor_id, type=d.type, lag=d.lag)
    db.add(link)
    activity.dependencies.append(link)


def _describe_dependencies(acts: list[Activity], a: Activity) -> str:
    if not a.dependencies:
        return "(none)"
    out = []
    for d in a.dependencies:
        i = next((k for k, x in enumerate(acts) if x.id == d.predecessor_id), -1)
        wbs = engine.wbs_of(acts, i) if i >= 0 else str(d.predecessor_id)
        lag = "" if d.lag == 0 else (f"+{d.lag}" if d.lag > 0 else str(d.lag))
        out.append(f"{wbs}{'' if d.type == 0 else DEP_TYPE_NAMES[d.type]}{lag}")
    return ", ".join(out)


# ---------------------------------------------------------------------------
#  Baseline
# ---------------------------------------------------------------------------
def set_baseline(db: Session, project_id: int, who: str) -> None:
    project = load_required(db, project_id)
    acts, _ = schedule(project)
    for a in acts:
        a.baseline_start = a.computed_start
        a.baseline_finish = a.computed_finish
    audit.record(db, who, "BaselineSet", "Project", project.name, f"{len(acts)} rows frozen", project)
    db.commit()
