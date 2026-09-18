"""The customer portal.

People holding a Customer role see the status of projects and approve or
reject - line item by line item - the actual dates entered by the
organisation's employees. Every decision is written to the audit trail.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Activity, DateApproval, Project, STATUS_NAMES
from ..schemas import ApprovalLineOut, CustomerProjectOut, DecisionIn
from ..services import audit, plan
from ..services.rules import NotFound, RuleViolation
from .common import who

router = APIRouter(prefix="/api/customer", tags=["customer"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/projects", response_model=list[CustomerProjectOut])
def customer_projects(db: Session = Depends(get_db)):
    """Project status as the customer sees it, with how many line items wait
    for their decision."""
    pending = dict(db.execute(
        select(Activity.project_id, func.count(DateApproval.id))
        .join(Activity, Activity.id == DateApproval.activity_id)
        .where(DateApproval.status == "Pending")
        .group_by(Activity.project_id)).all())
    out = []
    for pid in db.execute(select(Project.id).order_by(Project.code)).scalars().all():
        project = plan.load(db, pid)
        if project is None:
            continue
        acts, _ = plan.schedule(project)
        leaves = [a for a in acts if not a.is_summary]
        weight = sum(max(1, a.duration) for a in leaves)
        pct = 0 if weight == 0 else round(
            sum(float(a.percent_complete) * max(1, a.duration) for a in leaves) / weight)
        forecast = max((a.computed_finish_date for a in leaves), default=None)
        variance = (forecast - project.planned_end).days \
            if forecast and project.planned_end else None
        out.append(CustomerProjectOut(
            id=project.id, code=project.code, name=project.name,
            status=STATUS_NAMES.get(project.status, "Active"),
            percent_complete=pct, planned_start=project.planned_start,
            planned_end=project.planned_end, forecast_finish=forecast,
            end_variance_days=variance,
            organisation_name=project.organisation.name if project.organisation else None,
            pending_count=pending.get(project.id, 0)))
    return out


@router.get("/projects/{project_id}/lines", response_model=list[ApprovalLineOut])
def approval_lines(project_id: int, db: Session = Depends(get_db)):
    """Every line item of the project that carries actual dates, with its
    approval state. Items without actuals are not listed - there is nothing
    to sign off yet."""
    project = plan.load(db, project_id)
    if project is None:
        raise NotFound(f"Project {project_id} not found.")
    acts, _ = plan.schedule(project)
    approvals = {ap.activity_id: ap for ap in db.execute(
        select(DateApproval).join(Activity, Activity.id == DateApproval.activity_id)
        .where(Activity.project_id == project_id)).scalars().all()}
    out = []
    for a in acts:
        if a.is_summary or not a.has_actuals:
            continue
        ap = approvals.get(a.id)
        out.append(ApprovalLineOut(
            activity_id=a.id, wbs=a.wbs, kind=a.kind_name, name=a.name,
            planned_start=a.computed_start_date, planned_finish=a.computed_finish_date,
            actual_start=a.actual_start, actual_finish=a.actual_finish,
            percent_complete=a.percent_complete,
            approval_status=ap.status if ap else "Pending",
            comment=ap.comment if ap else None,
            submitted_by=ap.submitted_by if ap else None,
            submitted_at_utc=ap.submitted_at_utc if ap else None,
            decided_by=ap.decided_by if ap else None,
            decided_at_utc=ap.decided_at_utc if ap else None))
    return out


def _decide(db: Session, activity_id: int, actor: str, status: str, comment: str | None):
    a = db.get(Activity, activity_id)
    if a is None:
        raise NotFound(f"Activity {activity_id} not found.")
    if not a.has_actuals:
        raise RuleViolation("This line has no actual dates to decide on.")
    ap = db.execute(select(DateApproval)
                    .where(DateApproval.activity_id == activity_id)).scalar_one_or_none()
    if ap is None:                       # actuals entered before this feature existed
        ap = DateApproval(activity_id=activity_id, submitted_by="",
                          submitted_at_utc=None)
        db.add(ap)
    if ap.status == status:
        raise RuleViolation(f"This line is already {status.lower()}.")
    ap.actual_start, ap.actual_finish = a.actual_start, a.actual_finish
    ap.status, ap.comment = status, (comment.strip() if comment else None)
    ap.decided_by, ap.decided_at_utc = actor.strip() or "Customer", _utcnow()
    audit.record(db, actor, f"Customer {status.lower()}", "Actual dates",
                 a.name, comment, project=a.project, activity_id=a.id)
    db.commit()
    return ap


@router.post("/lines/{activity_id}/approve", response_model=ApprovalLineOut)
def approve(activity_id: int, req: DecisionIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    _decide(db, activity_id, actor, "Approved", req.comment)
    return _line(db, activity_id)


@router.post("/lines/{activity_id}/reject", response_model=ApprovalLineOut)
def reject(activity_id: int, req: DecisionIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    if not req.comment or len(req.comment.strip()) < 3:
        raise RuleViolation("Write a comment so the team knows why the dates are rejected.")
    _decide(db, activity_id, actor, "Rejected", req.comment)
    return _line(db, activity_id)


def _line(db: Session, activity_id: int) -> ApprovalLineOut:
    a = db.get(Activity, activity_id)
    lines = approval_lines(a.project_id, db)
    return next(x for x in lines if x.activity_id == activity_id)
