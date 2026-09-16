"""Writes the append-only trail. Never updates or deletes an entry."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import AuditEntry, Project


def record(db: Session, who: str, action: str, entity_kind: str, entity_name: str,
           detail: str | None = None, project: Project | None = None,
           activity_id: int | None = None) -> None:
    db.add(AuditEntry(
        timestamp_utc=datetime.now(timezone.utc).replace(tzinfo=None),
        who=who.strip() if who and who.strip() else "Unattributed",
        action=action,
        entity_kind=entity_kind,
        entity_name=entity_name,
        detail=detail,
        project_id=project.id if project else None,
        project_code=project.code if project else None,
        activity_id=activity_id,
    ))


def change(field: str, before, after) -> str | None:
    """'planned start: 2026-01-05 -> 2026-02-02', or None when nothing changed."""
    a = "(blank)" if before is None else str(before)
    b = "(blank)" if after is None else str(after)
    return None if a == b else f"{field}: {a} -> {b}"
