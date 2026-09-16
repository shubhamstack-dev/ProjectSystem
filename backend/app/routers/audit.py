from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditEntry
from ..schemas import AuditOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def get_audit(project_id: int | None = None, kind: str | None = None, q: str | None = None,
              take: int = 500, db: Session = Depends(get_db)):
    """Newest first. Read-only by design: the trail is append-only."""
    stmt = select(AuditEntry)
    if project_id is not None:
        stmt = stmt.where(AuditEntry.project_id == project_id)
    if kind:
        stmt = stmt.where(AuditEntry.entity_kind == kind)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditEntry.entity_name.like(like), AuditEntry.detail.like(like), AuditEntry.who.like(like)))
    rows = db.execute(stmt.order_by(AuditEntry.id.desc()).limit(max(1, min(take, 5000)))).scalars().all()
    return [AuditOut.model_validate(r) for r in rows]
