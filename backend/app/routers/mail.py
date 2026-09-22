"""Mail settings, and what the mail worker has done. Administrators only."""
from __future__ import annotations

import imaplib
import ssl

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select

from .. import models as M
from ..services import mail as MAIL
from ..services.audit import record as audit_record
from ..services.auth import Caller, require_admin

router = APIRouter(prefix="/api/mail", tags=["mail"])


def _status(s: dict) -> dict:
    return {"sending_ready": MAIL.sending_ready(s), "receiving_ready": MAIL.receiving_ready(s)}


@router.get("/settings")
def settings(caller: Caller = Depends(require_admin)):
    """Passwords come back only as 'set' or 'not set' — never the value."""
    s = MAIL.get_settings(caller.db)
    return {"settings": s, **_status(s)}


@router.put("/settings")
def save(body: dict = Body(...), caller: Caller = Depends(require_admin)):
    port = str(body.get("smtp_port") or "587")
    if not port.isdigit():
        raise HTTPException(422, "The SMTP port is a number, usually 587 or 465")
    if body.get("from_address") and "@" not in body["from_address"]:
        raise HTTPException(422, "The From address is not an email address")
    MAIL.save_settings(caller.db, body)
    audit_record(caller.db, caller.actor, "Update", "Mail settings", "SMTP / IMAP",
                 "passwords changed" if body.get("smtp_password") or body.get("imap_password") else None)
    caller.db.commit()
    s = MAIL.get_settings(caller.db)
    return {"settings": s, **_status(s)}


@router.post("/test")
def test_send(body: dict = Body(...), caller: Caller = Depends(require_admin)):
    """Send one message now, so a wrong password shows here, not in a queue."""
    to = (body.get("to") or caller.user.email or "").strip()
    try:
        return {"message": MAIL.test_connection(caller.db, to)}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.post("/test-imap")
def test_imap(caller: Caller = Depends(require_admin)):
    """Sign in to the mailbox and count what is unread, without reading it."""
    s = MAIL.get_settings(caller.db, reveal=True)
    if not (s.get("imap_host") and s.get("imap_user")):
        raise HTTPException(409, "Set the IMAP server and mailbox user first.")
    try:
        box = imaplib.IMAP4_SSL(s["imap_host"], int(s.get("imap_port") or 993),
                                ssl_context=ssl.create_default_context())
        try:
            box.login(s["imap_user"], s.get("imap_password") or "")
            typ, _ = box.select(s.get("imap_folder") or "INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError(f"The folder {s.get('imap_folder')} does not exist")
            _, data = box.search(None, "UNSEEN")
            unseen = len(data[0].split()) if data and data[0] else 0
        finally:
            try:
                box.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as e:
        raise HTTPException(502, "The mailbox refused the user name or password. Microsoft 365 "
                                 f"and Gmail usually need an app password. ({e})")
    except Exception as e:
        raise HTTPException(502, f"Could not open the mailbox: {type(e).__name__}: {e}")
    return {"message": f"Signed in. {unseen} unread message{'' if unseen == 1 else 's'} in "
                       f"{s.get('imap_folder') or 'INBOX'}."}


@router.post("/poll")
def poll_now(caller: Caller = Depends(require_admin)):
    try:
        return MAIL.poll_inbox(caller.db)
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@router.post("/send-now")
def send_now(caller: Caller = Depends(require_admin)):
    return MAIL.send_due(caller.db)


@router.get("/outbox")
def outbox(limit: int = 50, caller: Caller = Depends(require_admin)):
    rows = caller.db.execute(select(M.EmailOutbox).order_by(M.EmailOutbox.id.desc())
                             .limit(min(limit, 200))).scalars().all()
    return [{"id": r.id, "to": r.to_address, "subject": r.subject, "reason": r.reason,
             "status": r.status, "attempts": r.attempts, "last_error": r.last_error,
             "created_at_utc": r.created_at_utc, "sent_at_utc": r.sent_at_utc,
             "ticket_id": r.ticket_id} for r in rows]


@router.get("/inbound")
def inbound(limit: int = 50, caller: Caller = Depends(require_admin)):
    rows = caller.db.execute(select(M.EmailInbound).order_by(M.EmailInbound.id.desc())
                             .limit(min(limit, 200))).scalars().all()
    return [{"id": r.id, "from": r.from_address, "subject": r.subject, "outcome": r.outcome,
             "note": r.note, "ticket_id": r.ticket_id, "received_at_utc": r.received_at_utc}
            for r in rows]
