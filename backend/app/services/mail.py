"""Email: sending notifications over SMTP, and reading replies back over IMAP.

SMTP only sends. Receiving mail is a different protocol — IMAP — against a
mailbox, so the two are configured separately even when they are the same
account on the same provider.

*Sending* never happens inside a request. A message is written to the outbox
and a worker sends it, retrying with back-off. A mail server that is slow or
down must not make raising a ticket slow or make it fail, and the outbox row is
the record of what was sent to whom.

*Receiving* reads unseen messages from one mailbox. A message whose subject
carries a ticket number, e.g. "Re: [TCK-00012] Save greyed out", from an
address belonging to an active account that may see that ticket, becomes a
reply on it — quoted history trimmed, attachments stored under the same rules
as uploads. Anything else is logged and left alone. Keyed on Message-ID, so
reading the mailbox twice never posts a reply twice.
"""
from __future__ import annotations

import base64
import email
import email.policy
import hashlib
import html
import imaplib
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update

from .. import config, models as M

SECRET_KEYS = {"smtp_password", "imap_password", "oauth_client_secret"}
DEFAULTS = {
    "smtp_host": "", "smtp_port": "587", "smtp_security": "starttls",
    "smtp_user": "", "smtp_password": "", "smtp_auth": "password",
    "from_address": "", "from_name": "Aequm ProjectSystem", "reply_to": "",
    "imap_enabled": "0", "imap_host": "", "imap_port": "993",
    "imap_user": "", "imap_password": "", "imap_folder": "INBOX", "imap_auth": "password",
    "poll_minutes": "2", "app_url": "",
    # Microsoft 365 OAuth (XOAUTH2). Blank = reuse the ENTRA_* sign-in app from .env.
    "oauth_tenant_id": "", "oauth_client_id": "", "oauth_client_secret": "",
}
MAX_ATTEMPTS = 6
TICKET_RX = re.compile(r"\[(TCK-\d{3,})\]")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -------------------------------------------------------------- settings
def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("mail:" + config.SECRET_KEY).encode()).digest())
    return Fernet(key)


def get_settings(db, reveal: bool = False) -> dict:
    """All mail settings. Secrets are decrypted only when the sender needs
    them; the screen is told only whether one is set."""
    rows = {r.key: r.value for r in db.execute(select(M.AppSetting)).scalars()}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if rows.get(k) is not None:
            out[k] = rows[k]
    for k in SECRET_KEYS:
        raw = out.get(k) or ""
        if not reveal:
            out[k] = bool(raw)
            continue
        try:
            out[k] = _fernet().decrypt(raw.encode()).decode() if raw else ""
        except InvalidToken:
            # SECRET_KEY has changed since this was saved; it cannot be read back
            out[k] = ""
    return out


def save_settings(db, values: dict) -> None:
    for k, v in values.items():
        if k not in DEFAULTS:
            continue
        if k in SECRET_KEYS:
            if v is None or v == "":
                continue          # blank means "leave the stored one alone"
            v = _fernet().encrypt(str(v).encode()).decode()
        row = db.get(M.AppSetting, k)
        if row is None:
            db.add(M.AppSetting(key=k, value=str(v)))
        else:
            row.value = str(v)
    db.commit()


def sending_ready(s: dict) -> bool:
    return bool(s.get("smtp_host") and s.get("from_address"))


def receiving_ready(s: dict) -> bool:
    return s.get("imap_enabled") in ("1", "true", True) and bool(
        s.get("imap_host") and s.get("imap_user"))


# ----------------------------------------------------------------- queue
def queue(db, to: str, subject: str, text: str, *, ticket_id: int | None = None,
          reason: str = "", html_body: str | None = None) -> M.EmailOutbox | None:
    """Put a message in the outbox. Nothing is sent from here."""
    to = (to or "").strip()
    if not to or "@" not in to or to.endswith("@entra"):
        return None
    subject = " ".join((subject or "").split())       # no CR/LF in a header
    row = M.EmailOutbox(to_address=to, subject=subject[:300], body_text=text,
                        body_html=html_body, ticket_id=ticket_id, reason=reason[:40],
                        status="queued", attempts=0, created_at_utc=_now(),
                        next_try_utc=_now())
    db.add(row)
    return row



# --------------------------------------------------- Microsoft 365 OAuth
# Exchange Online no longer accepts a password for IMAP, and is retiring it for
# SMTP AUTH. XOAUTH2 with an app-only token (client credentials) works for both.
# The app registration needs Office 365 Exchange Online application permissions
# IMAP.AccessAsApp and/or SMTP.SendAsApp, admin consent, and the mailbox granted
# to the app's Exchange service principal (see SERVER-STEPS.md).
_TOKEN: dict = {}
_TOKEN_LOCK = threading.Lock()
_OUTLOOK_SCOPE = "https://outlook.office365.com/.default"


def _oauth_creds(s: dict) -> tuple[str, str, str]:
    tenant = (s.get("oauth_tenant_id") or config.ENTRA_TENANT_ID or "").strip()
    client = (s.get("oauth_client_id") or config.ENTRA_CLIENT_ID or "").strip()
    secret = (s.get("oauth_client_secret") or config.ENTRA_CLIENT_SECRET or "").strip()
    if not (tenant and client and secret):
        raise RuntimeError("Microsoft 365 OAuth needs a tenant id, client id and client secret. "
                           "Fill them on this screen, or set ENTRA_TENANT_ID / ENTRA_CLIENT_ID / "
                           "ENTRA_CLIENT_SECRET in .env.")
    return tenant, client, secret


def oauth_token(s: dict) -> str:
    """App-only access token for outlook.office365.com, cached until 5 minutes
    before it expires."""
    import json
    import urllib.parse
    import urllib.request
    tenant, client, secret = _oauth_creds(s)
    key = (tenant, client)
    with _TOKEN_LOCK:
        cached = _TOKEN.get(key)
        if cached and cached[1] > time.time() + 300:
            return cached[0]
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": client,
            "client_secret": secret, "scope": _OUTLOOK_SCOPE}).encode()
        req = urllib.request.Request(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                tok = json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            detail = ""
            if hasattr(e, "read"):
                try:
                    detail = json.loads(e.read().decode()).get("error_description", "")[:300]
                except Exception:
                    detail = ""
            raise RuntimeError("Microsoft refused to issue a mail token. " + (detail or str(e)))
        _TOKEN[key] = (tok["access_token"], time.time() + int(tok.get("expires_in", 3600)))
        return tok["access_token"]


def xoauth2_string(user: str, token: str) -> str:
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def imap_connect(s: dict):
    """Open and sign in to the IMAP mailbox with whichever method is configured."""
    port = int(s.get("imap_port") or 993)
    box = imaplib.IMAP4_SSL(s["imap_host"], port, ssl_context=ssl.create_default_context())
    if (s.get("imap_auth") or "password") == "oauth":
        token = oauth_token(s)
        box.authenticate("XOAUTH2", lambda _: xoauth2_string(s["imap_user"], token).encode())
    else:
        box.login(s["imap_user"], s.get("imap_password") or "")
    return box


def _smtp(s: dict):
    port = int(s.get("smtp_port") or 587)
    mode = (s.get("smtp_security") or "starttls").lower()
    ctx = ssl.create_default_context()
    if mode == "ssl":
        conn = smtplib.SMTP_SSL(s["smtp_host"], port, timeout=30, context=ctx)
    else:
        conn = smtplib.SMTP(s["smtp_host"], port, timeout=30)
        conn.ehlo()
        if mode == "starttls":
            conn.starttls(context=ctx)
            conn.ehlo()
    if (s.get("smtp_auth") or "password") == "oauth":
        token = oauth_token(s)
        conn.auth("XOAUTH2", lambda challenge=None: xoauth2_string(s["smtp_user"], token),
                  initial_response_ok=True)
    elif s.get("smtp_user"):
        conn.login(s["smtp_user"], s.get("smtp_password") or "")
    return conn


def _message(s: dict, row: M.EmailOutbox) -> EmailMessage:
    m = EmailMessage()
    m["From"] = f'{s.get("from_name") or "ProjectSystem"} <{s["from_address"]}>'
    m["To"] = row.to_address
    m["Subject"] = row.subject
    if s.get("reply_to"):
        m["Reply-To"] = s["reply_to"]
    domain = s["from_address"].split("@")[-1]
    m["Message-ID"] = make_msgid(domain=domain)
    m.set_content(row.body_text)
    if row.body_html:
        m.add_alternative(row.body_html, subtype="html")
    return m


def send_due(db, limit: int = 25) -> dict:
    """Send what is due. Each row is claimed first, so two workers never send
    the same message."""
    s = get_settings(db, reveal=True)
    if not sending_ready(s):
        return {"sent": 0, "failed": 0, "skipped": "not configured"}
    due = db.execute(select(M.EmailOutbox.id).where(
        M.EmailOutbox.status == "queued", M.EmailOutbox.next_try_utc <= _now())
        .order_by(M.EmailOutbox.id).limit(limit)).scalars().all()
    sent = failed = 0
    conn = None
    try:
        for oid in due:
            claimed = db.execute(update(M.EmailOutbox).where(
                M.EmailOutbox.id == oid, M.EmailOutbox.status == "queued")
                .values(status="sending")).rowcount
            db.commit()
            if not claimed:
                continue
            row = db.get(M.EmailOutbox, oid)
            try:
                if conn is None:
                    conn = _smtp(s)
                conn.send_message(_message(s, row))
                row.status, row.sent_at_utc, row.last_error = "sent", _now(), None
                sent += 1
            except Exception as e:           # one bad address must not stop the rest
                row.attempts += 1
                row.last_error = f"{type(e).__name__}: {e}"[:500]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                else:
                    row.status = "queued"
                    row.next_try_utc = _now() + timedelta(minutes=2 ** row.attempts)
                failed += 1
                if isinstance(e, (smtplib.SMTPServerDisconnected, OSError)):
                    conn = None
            db.commit()
    finally:
        if conn is not None:
            try:
                conn.quit()
            except Exception:
                pass
    return {"sent": sent, "failed": failed}


def test_connection(db, to: str) -> str:
    """Send one message straight away, so a wrong password shows up on the
    settings screen rather than as a queue of silent failures."""
    s = get_settings(db, reveal=True)
    if not sending_ready(s):
        raise RuntimeError("Set the SMTP server and the From address first.")
    row = M.EmailOutbox(to_address=to, subject="ProjectSystem: test message",
                        body_text="This is a test from ProjectSystem. If you can read it, "
                                  "outgoing mail is set up correctly.",
                        reason="test", status="sending", attempts=1, created_at_utc=_now())
    db.add(row)
    db.commit()
    try:
        conn = _smtp(s)
        try:
            conn.send_message(_message(s, row))
        finally:
            conn.quit()
    except Exception as e:
        row.status, row.last_error = "failed", f"{type(e).__name__}: {e}"[:500]
        db.commit()
        raise RuntimeError(_explain(e))
    row.status, row.sent_at_utc = "sent", _now()
    db.commit()
    return f"Sent to {to}."


def _explain(e: Exception) -> str:
    """The failures people actually hit, in words they can act on."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        if "XOAUTH2" in str(e) or "5.7.3" in str(e):
            return ("Microsoft accepted the token but the mailbox refused it. Check that the "
                    "app has SMTP.SendAsApp permission with admin consent and that the mailbox "
                    "was granted to the app's Exchange service principal (SERVER-STEPS.md).")
        return ("The mail server refused the user name or password. For Microsoft 365 "
                "and Gmail this usually needs an app password, and SMTP AUTH switched on "
                "for the mailbox. If Microsoft says basic authentication is disabled, switch "
                "Authentication to Microsoft 365 (OAuth).")
    if isinstance(e, (TimeoutError, ConnectionRefusedError)) or "timed out" in str(e):
        return ("Could not reach the mail server. Check the host and port, and that "
                "the server's firewall allows outgoing connections on that port.")
    if isinstance(e, ssl.SSLError):
        return ("The secure connection failed. Port 587 normally wants STARTTLS; "
                "port 465 wants SSL.")
    return f"{type(e).__name__}: {e}"


# ------------------------------------------------------- what gets sent
def _link(s: dict, t: M.Ticket) -> str:
    base = (s.get("app_url") or "").rstrip("/")
    return f"{base}/tickets?open={t.id}" if base else ""


def _wrap(s: dict, t: M.Ticket, lead: str, body: str, reply_hint: bool) -> tuple[str, str]:
    link = _link(s, t)
    hint = ("Reply to this email to add a response to the ticket. Keep the "
            f"[{t.number}] in the subject.") if reply_hint else ""
    text = "\n\n".join(x for x in [lead, body, link and f"Open the ticket: {link}", hint] if x)
    esc = lambda x: html.escape(x).replace("\n", "<br>")
    html_body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1A1B3A;max-width:620px">
<div style="border-bottom:3px solid #F15A29;padding-bottom:8px;margin-bottom:14px;font-weight:600;color:#2B3990">
Aequm ProjectSystem · {html.escape(t.number)}</div>
<p style="margin:0 0 12px">{esc(lead)}</p>
{f'<div style="background:#F4F4F9;border-left:3px solid #2B3990;padding:10px 12px;margin:0 0 14px">{esc(body)}</div>' if body else ''}
{f'<p><a href="{html.escape(link)}" style="color:#2B3990">Open the ticket</a></p>' if link else ''}
{f'<p style="color:#6b7280;font-size:12px">{esc(hint)}</p>' if hint else ''}
</div>"""
    return text, html_body


def _subject(t: M.Ticket, what: str) -> str:
    title = " ".join((t.title or "").split())
    return f"[{t.number}] {what}: {title}"[:300]


def _people_emails(db, person_ids) -> list[str]:
    out = []
    for pid in {p for p in person_ids if p}:
        p = db.get(M.Person, pid)
        if p and p.email:
            out.append(p.email)
    return out


def _raiser_email(db, t: M.Ticket) -> str | None:
    u = db.get(M.AppUser, t.raised_by_user_id) if t.raised_by_user_id else None
    return u.email if u and u.active else None


def _team_emails(db, t: M.Ticket) -> list[str]:
    if not t.team_role_id:
        return []
    people = db.execute(select(M.Person).where(M.Person.role_id == t.team_role_id)).scalars()
    return [p.email for p in people if p.email]


def notify(db, t: M.Ticket, event: str, *, actor: str = "", body: str = "",
           actor_user_id: int | None = None) -> int:
    """Queue the messages for one thing that happened to a ticket.

    Who hears about what:
      raised   -> the project manager, and an acknowledgement to the raiser
      routed   -> the team it was sent to, and the person named if any
      response -> the raiser if the team replied; the PM and team if the raiser did
      resolved -> the raiser
    Nobody is told about their own action.
    """
    s = get_settings(db)
    if not sending_ready(s):
        return 0
    raiser = _raiser_email(db, t)
    au = db.get(M.AppUser, actor_user_id) if actor_user_id else None
    actor_emails = {au.email.lower()} if au else set()
    msgs: list[tuple[str, str, str, bool]] = []   # to, lead, what, reply_hint
    # Sent even though raising was the raiser's own action: it is the first
    # email carrying the [TCK-…] number, which is what lets them reply by email.
    always = set()

    if event == "raised":
        for e in _people_emails(db, [t.pm_id]):
            msgs.append((e, f"A new ticket on {t.project.code} is waiting for you to route "
                            f"it to a team. Raised by {t.created_by}.", "New ticket", True))
        if raiser:
            msgs.append((raiser, "We have your ticket. The project manager will send it "
                                 "to the right team.", "Received", True))
            always.add(raiser.lower())
    elif event == "routed":
        team = t.team_role.name if t.team_role else "the team"
        for e in set(_team_emails(db, t) + _people_emails(db, [t.assignee_id])):
            msgs.append((e, f"{actor} has sent this ticket to {team}.", "Assigned to your team", True))
    elif event == "response":
        from_raiser = bool(actor_user_id) and actor_user_id == t.raised_by_user_id
        targets = (_people_emails(db, [t.pm_id, t.assignee_id]) + _team_emails(db, t)) \
            if from_raiser else ([raiser] if raiser else [])
        for e in set(targets):
            msgs.append((e, f"{actor} replied on {t.number}.", "New reply", True))
    elif event == "resolved":
        if raiser:
            msgs.append((raiser, f"{actor} has resolved your ticket.", "Resolved", True))

    n = 0
    for to, lead, what, hint in msgs:
        if to.lower() in actor_emails and to.lower() not in always:
            continue
        text, html_body = _wrap(s, t, lead, body, hint)
        if queue(db, to, _subject(t, what), text, ticket_id=t.id, reason=event,
                 html_body=html_body):
            n += 1
    return n


# ------------------------------------------------------------ receiving
_QUOTE_START = re.compile(
    r"^(On .{0,200} wrote:|-----\s*Original Message\s*-----|From:\s.+|Sent from my )",
    re.I | re.M)


def strip_quoted(text: str) -> str:
    """Keep what the person wrote, not the thread they replied under."""
    text = text.replace("\r\n", "\n")
    m = _QUOTE_START.search(text)
    if m:
        text = text[:m.start()]
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def _plain_body(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        content = re.sub(r"<(br|/p|/div)[^>]*>", "\n", content, flags=re.I)
        content = html.unescape(re.sub(r"<[^>]+>", "", content))
    return content


def handle_message(db, raw: bytes) -> M.EmailInbound:
    """Turn one raw message into a reply, or record why not."""
    from . import files as FILES
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    mid = (msg.get("Message-ID") or "").strip() or \
        "<sha:" + hashlib.sha256(raw).hexdigest()[:40] + ">"
    seen = db.execute(select(M.EmailInbound).where(
        M.EmailInbound.message_id == mid)).scalar_one_or_none()
    if seen:
        return seen
    sender = parseaddr(msg.get("From", ""))[1].strip().lower()
    subject = str(msg.get("Subject", ""))[:300]

    def log(outcome, note, ticket_id=None):
        row = M.EmailInbound(message_id=mid[:300], from_address=sender[:200] or "?",
                             subject=subject, ticket_id=ticket_id, outcome=outcome,
                             note=(note or "")[:500], received_at_utc=_now())
        db.add(row)
        db.commit()
        return row

    auto = (msg.get("Auto-Submitted", "no").lower() != "no") or \
        msg.get("X-Autoreply") or msg.get("X-Autorespond") or \
        "mailer-daemon" in sender or "postmaster" in sender
    if auto:
        return log("ignored", "Automatic reply or bounce")

    m = TICKET_RX.search(subject)
    if not m:
        return log("ignored", "No ticket number in the subject")
    # the number is derived from the id (TCK-00012 is ticket 12), not stored
    t = db.get(M.Ticket, int(m.group(1).split("-")[1]))
    if t is None:
        return log("ignored", f"{m.group(1)} does not exist")

    # The sender must be an active account allowed to see this ticket. The
    # From address can be forged, so this is not authentication — it only
    # stops a stranger's message landing on somebody's ticket. Mailbox-side
    # SPF/DMARC checking is what makes the From address worth trusting.
    u = db.execute(select(M.AppUser).where(M.AppUser.email == sender)).scalar_one_or_none()
    if u is None or not u.active:
        return log("refused", "Sender is not an active account", t.id)
    if u.user_type == "Guest":
        p = db.get(M.Project, t.project_id)
        if not u.customer_id or not p or p.customer_id != u.customer_id:
            return log("refused", "Sender's customer does not own this ticket", t.id)

    body = strip_quoted(_plain_body(msg))
    atts = [a for a in msg.iter_attachments()]
    if not body and not atts:
        return log("ignored", "Empty reply", t.id)

    actor = u.display_name or u.email
    r = M.TicketResponse(ticket_id=t.id, author=actor, body=body or "(attachments by email)",
                         created_at_utc=_now())
    db.add(r)
    db.flush()
    refused = []
    for a in atts:
        try:
            meta = FILES.save_bytes(a.get_filename() or "attachment", a.get_content()
                                    if isinstance(a.get_content(), bytes)
                                    else a.get_payload(decode=True) or b"")
        except FILES.FileRefused as e:
            refused.append(str(e))
            continue
        db.add(M.TicketAttachment(
            ticket_id=t.id, response_id=r.id, file_name=meta["file_name"],
            content_type=meta["content_type"], kind=meta["kind"], size_bytes=meta["size_bytes"],
            storage_key=meta["storage_key"], sha256=meta["sha256"], data=None,
            uploaded_by=actor, uploaded_at_utc=_now()))
    t.updated_at_utc = _now()
    db.commit()
    notify(db, t, "response", actor=actor, body=body, actor_user_id=u.id)
    db.commit()
    return log("posted", "; ".join(refused) or f"Reply by {actor}", t.id)


def poll_inbox(db) -> dict:
    s = get_settings(db, reveal=True)
    if not receiving_ready(s):
        return {"read": 0, "skipped": "not configured"}
    box = imap_connect(s)
    counts = {"read": 0, "posted": 0, "ignored": 0, "refused": 0}
    try:
        box.select(s.get("imap_folder") or "INBOX")
        typ, data = box.search(None, "UNSEEN")
        for num in (data[0].split() if data and data[0] else [])[:50]:
            typ, parts = box.fetch(num, "(RFC822)")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if not raw:
                continue
            row = handle_message(db, raw)
            counts["read"] += 1
            counts[row.outcome] = counts.get(row.outcome, 0) + 1
            box.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return counts


# --------------------------------------------------------------- worker
_stop = threading.Event()


def start_worker(session_factory) -> None:
    """One background thread: send what is due every 20 seconds, read the
    mailbox every few minutes. Errors are logged and the loop carries on."""
    def loop():
        last_poll = 0.0
        while not _stop.wait(20):
            db = session_factory()
            try:
                send_due(db)
                s = get_settings(db)
                every = max(1, int(s.get("poll_minutes") or 2)) * 60
                if receiving_ready(s) and time.time() - last_poll >= every:
                    last_poll = time.time()
                    poll_inbox(db)
            except Exception as e:
                print(f"[mail] {type(e).__name__}: {e}", flush=True)
            finally:
                db.close()
    threading.Thread(target=loop, name="mail-worker", daemon=True).start()
