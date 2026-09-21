from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Holiday, Project, ProjectTeamMember
from ..schemas import ProjectDetail, ProjectIn, ProjectSummary
from ..services import audit, mapper, plan
from ..services.rules import NotFound, RuleViolation, project_has_actuals
from .common import who
from ..services.auth import Caller, current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db),
                  caller: Caller = Depends(current_user)):
    q = select(Project.id).order_by(Project.code)
    # A customer user is offered only their own projects. The ticket API refuses
    # the others anyway, but offering them produces a form that fails on save,
    # which reads as a broken product rather than a boundary.
    if caller.is_customer:
        if not caller.user.customer_id:
            return []
        q = q.where(Project.customer_id == caller.user.customer_id)
    ids = db.execute(q).scalars().all()
    out = []
    for pid in ids:
        p = plan.load(db, pid)
        if p:
            acts, result = plan.schedule(p)
            out.append(mapper.to_summary(p, acts, result))
    return out


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db),
                caller: Caller = Depends(current_user)):
    p = plan.load_required(db, project_id)
    if caller.is_customer and p.customer_id != caller.user.customer_id:
        raise NotFound(f"Project {project_id} not found.")
    acts, result = plan.schedule(p)
    return ProjectDetail(
        project=mapper.to_summary(p, acts, result),
        activities=mapper.to_activity_dtos(acts, plan.calendar_for(p)),
        holidays=sorted(h.date for h in p.holidays),
        schedule_warning=result.message,
    )


@router.post("", response_model=ProjectSummary, status_code=201)
def create_project(req: ProjectIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    if db.execute(select(Project).where(Project.code == req.code)).first():
        raise RuleViolation(f"Project code '{req.code}' is already in use.")
    p = Project(code=req.code.strip(), name=req.name.strip(), planned_start=req.planned_start,
                planned_end=req.planned_end, status=req.status, organisation_id=req.organisation_id,
                owner_id=req.owner_id, notes=req.notes)
    for d in sorted(set(req.holidays)):
        p.holidays.append(Holiday(date=d))
    for pid in dict.fromkeys(req.team_ids):
        p.team.append(ProjectTeamMember(person_id=pid))
    db.add(p)
    db.flush()
    audit.record(db, actor, "Created", "Project", p.name,
                 f"planned {p.planned_start} -> {p.planned_end or '(no end)'}", p)
    db.commit()
    loaded = plan.load_required(db, p.id)
    acts, result = plan.schedule(loaded)
    return mapper.to_summary(loaded, acts, result)


@router.put("/{project_id}", response_model=ProjectSummary)
def update_project(project_id: int, req: ProjectIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = plan.load_required(db, project_id)
    clash = db.execute(select(Project).where(Project.code == req.code, Project.id != project_id)).first()
    if clash:
        raise RuleViolation(f"Project code '{req.code}' is already in use.")

    changes = [
        audit.change("code", p.code, req.code), audit.change("name", p.name, req.name),
        audit.change("planned start", p.planned_start, req.planned_start),
        audit.change("planned end", p.planned_end, req.planned_end),
        audit.change("status", p.status, req.status),
        audit.change("owner", p.owner_id, req.owner_id),
        audit.change("organisation", p.organisation_id, req.organisation_id),
        audit.change("team", sorted(t.person_id for t in p.team), sorted(set(req.team_ids))),
        audit.change("holidays", [str(h.date) for h in sorted(p.holidays, key=lambda h: h.date)],
                     [str(d) for d in sorted(set(req.holidays))]),
        "notes edited" if (req.notes or "") != (p.notes or "") else None,
    ]
    p.code, p.name, p.planned_start, p.planned_end = req.code.strip(), req.name.strip(), req.planned_start, req.planned_end
    p.status, p.organisation_id, p.owner_id, p.notes = req.status, req.organisation_id, req.owner_id, req.notes
    p.holidays.clear()
    p.team.clear()
    db.flush()  # deletes go first, so re-saving the same date / person does not collide
    for d in sorted(set(req.holidays)):
        p.holidays.append(Holiday(date=d))
    for pid in dict.fromkeys(req.team_ids):
        p.team.append(ProjectTeamMember(person_id=pid))
    detail = "; ".join(c for c in changes if c)
    if detail:
        audit.record(db, actor, "Edited", "Project", p.name, detail, p)
    db.commit()
    loaded = plan.load_required(db, p.id)
    acts, result = plan.schedule(loaded)
    return mapper.to_summary(loaded, acts, result)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = plan.load_required(db, project_id)
    if project_has_actuals(p):
        n = sum(1 for a in p.activities if a.has_actuals)
        audit.record(db, actor, "DeleteRefused", "Project", p.name, f"{n} item(s) with recorded work", p)
        db.commit()
        raise RuleViolation(f"'{p.name}' has actual dates recorded against {n} item(s). "
                            "Deleting it would destroy that record - set the status to On hold or Done instead.")
    audit.record(db, actor, "Deleted", "Project", p.name, f"{len(p.activities)} rows", p)
    db.delete(p)
    db.commit()


@router.post("/{project_id}/baseline", status_code=204)
def baseline(project_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    plan.set_baseline(db, project_id, actor)
