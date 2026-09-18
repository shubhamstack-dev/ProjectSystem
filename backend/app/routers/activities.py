from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Activity, DateApproval
from ..schemas import ActivityCreate, ActivityUpdate, EligibleOut, MoveIn
from ..scheduling.graph import eligible_predecessors
from ..services import plan
from ..services.rules import NotFound
from .common import who

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.post("", status_code=201)
def create(req: ActivityCreate, db: Session = Depends(get_db), actor: str = Depends(who)):
    a = plan.add_activity(db, req, actor)
    return {"id": a.id, "name": a.name, "level": a.level, "sequence": a.sequence}


@router.put("/{activity_id}")
def update(activity_id: int, req: ActivityUpdate, db: Session = Depends(get_db), actor: str = Depends(who)):
    before = db.get(Activity, activity_id)
    prev = (before.actual_start, before.actual_finish) if before else (None, None)
    a = plan.update_activity(db, activity_id, req, actor)
    _submit_for_approval(db, a, prev, actor)
    return {"id": a.id, "name": a.name, "mode": a.mode, "plannedStart": a.planned_start,
            "plannedFinish": a.planned_finish, "actualStart": a.actual_start, "actualFinish": a.actual_finish}


def _submit_for_approval(db: Session, a: Activity, prev: tuple, actor: str) -> None:
    """Whenever an employee enters or changes an actual date, the line item
    goes to the customer as Pending; clearing both dates withdraws it."""
    if (a.actual_start, a.actual_finish) == prev:
        return
    ap = db.execute(select(DateApproval)
                    .where(DateApproval.activity_id == a.id)).scalar_one_or_none()
    if a.actual_start is None and a.actual_finish is None:
        if ap is not None:
            db.delete(ap)
            db.commit()
        return
    if ap is None:
        ap = DateApproval(activity_id=a.id)
        db.add(ap)
    ap.actual_start, ap.actual_finish = a.actual_start, a.actual_finish
    ap.status, ap.comment = "Pending", None
    ap.decided_by, ap.decided_at_utc = None, None
    ap.submitted_by = actor.strip() or "Unattributed"
    ap.submitted_at_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


@router.delete("/{activity_id}", status_code=204)
def delete(activity_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    plan.delete_activity(db, activity_id, actor)


@router.post("/{activity_id}/move", status_code=204)
def move(activity_id: int, req: MoveIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    plan.move_activity(db, activity_id, req.direction, actor)


@router.get("/{activity_id}/eligible-predecessors", response_model=list[EligibleOut])
def eligible(activity_id: int, db: Session = Depends(get_db)):
    a = db.get(Activity, activity_id)
    if a is None:
        raise NotFound(f"Activity {activity_id} not found.")
    p = plan.load_required(db, a.project_id)
    acts, _ = plan.schedule(p)
    me = next(x for x in acts if x.id == activity_id)
    return [EligibleOut(id=x.id, wbs=x.wbs, name=x.name, kind=x.kind_name) for x in eligible_predecessors(acts, me)]
