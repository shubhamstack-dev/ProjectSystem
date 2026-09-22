"""Tickets raised inside a project (optionally against one of its phases) for a
configured module/tool - within SAP or outside SAP. A ticket carries a priority
(High / Medium / Low), can have documents attached at creation or on any reply,
and can be allocated to a person. Every reply lands on the ticket's thread the
moment it is saved, so the allocated person and the creator see it straight
away (the ticket view refreshes itself).

Configuration lives under /api/tickets/modules: the list of modules that can be
selected while creating a ticket, each flagged SAP or NonSAP.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import Body, Header, Request, APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..services.auth import Caller, current_user
from ..models import (ModuleProcess, Process, ProcessStep, TICKET_PRIORITIES, TICKET_STATUSES, Person, Phase, Project,
                      Ticket, TicketAttachment, TicketModule, TicketResponse, Role)
from ..schemas import (TicketAttachmentOut, TicketModuleIn, TicketModuleOut,
                       TicketOut, TicketResponseOut, TicketUpdateIn)
from ..services import audit
from ..services import mail as MAIL
from ..services.rules import NotFound, RuleViolation, Forbidden
from .common import who

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

from ..services import files as FILES
from .. import config as CFG


# ---- mapping ---------------------------------------------------------------
def _att_out(a: TicketAttachment) -> TicketAttachmentOut:
    # The link is signed for whoever is reading this ticket right now. It is
    # only ever built inside an answer the caller was allowed to receive, so it
    # carries their permission — and expires, rather than becoming a key.
    return TicketAttachmentOut(
        id=a.id, file_name=a.file_name, content_type=a.content_type,
        size_bytes=a.size_bytes, uploaded_by=a.uploaded_by,
        uploaded_at_utc=a.uploaded_at_utc, response_id=a.response_id,
        kind=a.kind or "document",
        url=f"/api/tickets/attachments/{a.id}?{FILES.signed_query(a.id)}")


def _resp_out(r: TicketResponse) -> TicketResponseOut:
    return TicketResponseOut(
        id=r.id, author=r.author, body=r.body, created_at_utc=r.created_at_utc,
        attachments=[_att_out(a) for a in sorted(r.attachments, key=lambda x: x.id)])


def _ticket_out(t: Ticket, full: bool = False) -> TicketOut:
    return TicketOut(
        id=t.id, number=t.number,
        project_id=t.project_id, project_code=t.project.code, project_name=t.project.name,
        phase_id=t.phase_id, phase_name=t.phase.name if t.phase else None,
        module_id=t.module_id, module_name=t.module.name if t.module else None,
        module_type=t.module.module_type if t.module else None,
        process_id=t.process_id, process_name=t.process.name if t.process else None,
        process_step_id=t.process_step_id,
        process_step_name=t.process_step.name if t.process_step else None,
        title=t.title, description=t.description, priority=t.priority, status=t.status,
        assignee_id=t.assignee_id, assignee_name=t.assignee.name if t.assignee else None,
        stage=_stage(t), pm_id=t.pm_id, pm_name=t.pm.name if t.pm else None,
        team_role_id=t.team_role_id, team_name=t.team_role.name if t.team_role else None,
        routed_by=t.routed_by, routed_at_utc=t.routed_at_utc,
        resolution=t.resolution, resolved_by=t.resolved_by, resolved_at_utc=t.resolved_at_utc,
        raised_by_user_id=t.raised_by_user_id,
        created_by=t.created_by, created_at_utc=t.created_at_utc, updated_at_utc=t.updated_at_utc,
        response_count=len(t.responses),
        attachments=[_att_out(a) for a in sorted(t.attachments, key=lambda x: x.id)
                     if a.response_id is None] if full else
                    [_att_out(a) for a in sorted(t.attachments, key=lambda x: x.id)
                     if a.response_id is None],
        responses=[_resp_out(r) for r in t.responses] if full else [])


# ---- v1.6: the triage workflow ------------------------------------------
#
#   raised ──> with the project manager ──route──> with a team ──resolve──> resolved
#                                                      ^                        │
#                                                      └──────── reopen ────────┤
#                                                                             close
#                                                                               v
#                                                                            closed
#
# Who may do what is decided here, once, and the same answer drives both the
# API and the buttons the screen shows — so a button is never offered that the
# server would refuse.

def _stage(t: Ticket) -> str:
    if t.status == "Closed":
        return "closed"
    if t.status == "Resolved":
        return "resolved"
    return "team" if t.team_role_id else "pm"


def _person_of(caller: Caller):
    return caller.db.get(Person, caller.user.person_id) if caller.user.person_id else None


def _is_pm(caller: Caller, t: Ticket) -> bool:
    return bool(t.pm_id) and caller.user.person_id == t.pm_id


def _in_team(caller: Caller, t: Ticket) -> bool:
    if not t.team_role_id:
        return False
    if t.assignee_id and caller.user.person_id == t.assignee_id:
        return True
    p = _person_of(caller)
    return bool(p and p.role_id == t.team_role_id)


def _actions(caller: Caller, t: Ticket) -> list[str]:
    st, admin = _stage(t), caller.is_admin
    raiser = t.raised_by_user_id == caller.user.id
    out = []
    if caller.is_customer:
        if st == "resolved" and raiser:
            out += ["close", "reopen"]
        return out
    # routing: the ticket's project manager. An administrator may too, which is
    # what keeps a project with no manager named from stranding its tickets.
    if st in ("pm", "team") and (_is_pm(caller, t) or admin):
        out.append("route")
    if st == "team" and (_in_team(caller, t) or _is_pm(caller, t) or admin):
        out.append("resolve")
    if st == "resolved" and (raiser or _is_pm(caller, t) or admin):
        out += ["close", "reopen"]
    if st == "closed" and (_is_pm(caller, t) or admin):
        out.append("reopen")
    return out


def _waiting_on(caller: Caller, t: Ticket) -> bool:
    """Is the next move this person's? Narrower than being *able* to act: a
    project manager may still re-route a ticket the team holds, but it is not
    waiting on them.

      with the project manager -> the PM (an administrator, if none is named)
      with a team              -> the people in that team
      resolved                 -> whoever raised it, to confirm or reopen
    """
    st = _stage(t)
    if st == "pm":
        return _is_pm(caller, t) or (caller.is_admin and not t.pm_id)
    if st == "team":
        return _in_team(caller, t)
    if st == "resolved":
        return t.raised_by_user_id == caller.user.id
    return False


def _detail(db: Session, t: Ticket, caller: Caller) -> TicketOut:
    out = _ticket_out(t, full=True)
    out.actions = _actions(caller, t)
    return out


def _require(caller: Caller, t: Ticket, action: str, why: str) -> None:
    if action not in _actions(caller, t):
        raise Forbidden(why)


def _load_ticket(db: Session, ticket_id: int) -> Ticket:
    t = db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
        .options(selectinload(Ticket.project), selectinload(Ticket.phase),
                 selectinload(Ticket.module), selectinload(Ticket.assignee),
                 selectinload(Ticket.responses).selectinload(TicketResponse.attachments),
                 selectinload(Ticket.attachments))
        .execution_options(populate_existing=True)).scalar()
    if t is None:
        raise NotFound(f"Ticket {ticket_id} not found.")
    return t


async def _store_files(db: Session, ticket: Ticket, files: list[UploadFile],
                       actor: str, response_id: int | None = None) -> None:
    """Stream each upload to disk and record it. All or nothing: if any file is
    refused, the ones already written are removed, so a ticket never ends up
    carrying half of what somebody meant to attach."""
    files = [f for f in files if f and (f.filename or "")]
    if len(files) > CFG.MAX_FILES_PER_CALL:
        raise RuleViolation(f"At most {CFG.MAX_FILES_PER_CALL} files can be attached in one go.")
    saved = []
    try:
        for f in files:
            saved.append(await FILES.save_upload(f))
    except FILES.FileRefused as e:
        for m in saved:
            FILES.remove(m["storage_key"])
        raise RuleViolation(str(e))
    except BaseException:
        for m in saved:
            FILES.remove(m["storage_key"])
        raise
    for m in saved:
        db.add(TicketAttachment(
            ticket_id=ticket.id, response_id=response_id,
            file_name=m["file_name"], content_type=m["content_type"], kind=m["kind"],
            size_bytes=m["size_bytes"], storage_key=m["storage_key"], sha256=m["sha256"],
            data=None, uploaded_by=actor, uploaded_at_utc=datetime.utcnow()))


def _check_priority(p: str) -> str:
    if p not in TICKET_PRIORITIES:
        raise RuleViolation(f"Priority must be one of {', '.join(TICKET_PRIORITIES)}.")
    return p


def _check_status(s: str) -> str:
    if s not in TICKET_STATUSES:
        raise RuleViolation(f"Status must be one of {', '.join(TICKET_STATUSES)}.")
    return s


# ---- module configuration (within SAP / outside SAP) -----------------------
@router.get("/modules", response_model=list[TicketModuleOut])
def modules(db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(Ticket.module_id, func.count()).group_by(Ticket.module_id)).all())
    rows = db.execute(select(TicketModule).order_by(TicketModule.module_type, TicketModule.name)).scalars().all()
    return [TicketModuleOut(id=m.id, name=m.name, module_type=m.module_type,
                            description=m.description, active=bool(m.active),
                            ticket_count=counts.get(m.id, 0)) for m in rows]


@router.post("/modules", response_model=TicketModuleOut, status_code=201)
def add_module(req: TicketModuleIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    if req.module_type not in ("SAP", "NonSAP"):
        raise RuleViolation('Module type must be "SAP" (within SAP) or "NonSAP" (outside SAP).')
    name = req.name.strip()
    if not name:
        raise RuleViolation("The module needs a name.")
    if db.execute(select(TicketModule).where(TicketModule.name == name)).scalar():
        raise RuleViolation(f'A module named "{name}" already exists.')
    m = TicketModule(name=name, module_type=req.module_type,
                     description=req.description, active=1 if req.active else 0)
    db.add(m)
    db.flush()
    audit.record(db, actor, "Created", "TicketModule", m.name)
    db.commit()
    return TicketModuleOut(id=m.id, name=m.name, module_type=m.module_type,
                           description=m.description, active=bool(m.active), ticket_count=0)


@router.put("/modules/{module_id}", response_model=TicketModuleOut)
def update_module(module_id: int, req: TicketModuleIn, db: Session = Depends(get_db),
                  actor: str = Depends(who)):
    m = db.get(TicketModule, module_id)
    if m is None:
        raise NotFound(f"Module {module_id} not found.")
    if req.module_type not in ("SAP", "NonSAP"):
        raise RuleViolation('Module type must be "SAP" (within SAP) or "NonSAP" (outside SAP).')
    name = req.name.strip()
    dup = db.execute(select(TicketModule).where(TicketModule.name == name,
                                                TicketModule.id != module_id)).scalar()
    if dup:
        raise RuleViolation(f'A module named "{name}" already exists.')
    m.name, m.module_type = name, req.module_type
    m.description, m.active = req.description, 1 if req.active else 0
    audit.record(db, actor, "Updated", "TicketModule", m.name)
    db.commit()
    count = db.execute(select(func.count()).select_from(Ticket)
                       .where(Ticket.module_id == m.id)).scalar()
    return TicketModuleOut(id=m.id, name=m.name, module_type=m.module_type,
                           description=m.description, active=bool(m.active), ticket_count=count)


@router.delete("/modules/{module_id}", status_code=204)
def delete_module(module_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    m = db.get(TicketModule, module_id)
    if m is None:
        raise NotFound(f"Module {module_id} not found.")
    used = db.execute(select(func.count()).select_from(Ticket)
                      .where(Ticket.module_id == module_id)).scalar()
    if used:
        raise RuleViolation(f'"{m.name}" is used by {used} ticket(s). Deactivate it instead of deleting.',
                            [f"{used} ticket(s) reference this module"])
    audit.record(db, actor, "Deleted", "TicketModule", m.name)
    db.delete(m)
    db.commit()


# ---- tickets ---------------------------------------------------------------
@router.get("", response_model=list[TicketOut])
def tickets(project_id: int | None = None, phase_id: int | None = None,
            status: str | None = None, priority: str | None = None,
            assignee_id: int | None = None, stage: str | None = None,
            waiting_on_me: bool = False, db: Session = Depends(get_db),
            caller: Caller = Depends(current_user)):
    allowed = _customer_projects(caller)
    if allowed is not None and not allowed:
        return []                      # a customer user with no customer yet
    q = (select(Ticket)
         .options(selectinload(Ticket.project), selectinload(Ticket.phase),
                  selectinload(Ticket.module), selectinload(Ticket.assignee),
                  selectinload(Ticket.responses), selectinload(Ticket.attachments))
         .order_by(Ticket.updated_at_utc.desc()))
    if project_id:
        q = q.where(Ticket.project_id == project_id)
    if phase_id:
        q = q.where(Ticket.phase_id == phase_id)
    if status:
        q = q.where(Ticket.status == status)
    if priority:
        q = q.where(Ticket.priority == priority)
    if assignee_id:
        q = q.where(Ticket.assignee_id == assignee_id)
    if allowed is not None:
        q = q.where(Ticket.project_id.in_(allowed))
    rows = db.execute(q).scalars().all()
    if stage:
        rows = [t for t in rows if _stage(t) == stage]
    if waiting_on_me:
        rows = [t for t in rows if _waiting_on(caller, t)]
    return [_ticket_out(t) for t in rows]


def _customer_projects(caller: Caller) -> set[int] | None:
    """Which projects this caller may see, or None for no restriction.

    A member of Aequm India sees everything. A customer user sees the projects
    of their own customer and nothing else — and a customer user who has not
    been given a customer yet sees nothing at all, which is the safe way round:
    an account nobody has filed should not default to seeing every project.
    """
    if not caller.is_customer:
        return None
    if not caller.user.customer_id:
        return set()
    rows = caller.db.execute(select(Project.id).where(
        Project.customer_id == caller.user.customer_id)).all()
    return {r[0] for r in rows}


def _may_touch(caller: Caller, project_id: int) -> bool:
    allowed = _customer_projects(caller)
    return allowed is None or project_id in allowed


def _check_process(db: Session, module_id: int | None,
                   process_id: int | None, step_id: int | None,
                   project_id: int | None = None) -> None:
    """A ticket may name a process and a step, and the chain has to hold.

    The step must belong to the process, and the process must be assigned to
    the ticket's module. Without the second check a ticket can claim a step
    that the module never runs, and every report grouped by module and process
    stops reconciling to the ticket list.
    """
    if step_id and not process_id:
        raise RuleViolation("A process step needs the process it belongs to.")
    if process_id:
        p = db.get(Process, process_id)
        if p is None:
            raise NotFound(f"Process {process_id} not found.")
        if project_id and p.project_id and p.project_id != project_id:
            raise RuleViolation(f"{p.name} is a process of another project.")
        if not module_id:
            raise RuleViolation(
                "A process belongs to a module, so choose the module first.")
        link = db.execute(select(ModuleProcess).where(
            ModuleProcess.process_id == process_id,
            ModuleProcess.module_id == module_id)).scalar_one_or_none()
        if link is None:
            m = db.get(TicketModule, module_id)
            raise RuleViolation(
                f"{p.name} is not one of the processes assigned to "
                f"{m.name if m else 'that module'}.")
    if step_id:
        st = db.get(ProcessStep, step_id)
        if st is None:
            raise NotFound(f"Process step {step_id} not found.")
        if st.process_id != process_id:
            raise RuleViolation("That step belongs to a different process.")


@router.post("", response_model=TicketOut, status_code=201)
async def create_ticket(project_id: int = Form(...), title: str = Form(...),
                        description: str = Form(""), priority: str = Form("Medium"),
                        phase_id: int | None = Form(None), module_id: int | None = Form(None),
                        process_id: int | None = Form(None),
                        process_step_id: int | None = Form(None),
                        assignee_id: int | None = Form(None),
                        files: list[UploadFile] = File(default=[]),
                        db: Session = Depends(get_db), actor: str = Depends(who),
                        caller: Caller = Depends(current_user)):
    """Create a ticket - multipart, so documents can be attached in the same call."""
    project = db.get(Project, project_id)
    if project is None:
        raise NotFound(f"Project {project_id} not found.")
    if not _may_touch(caller, project_id):
        raise RuleViolation("That project does not belong to your organisation.")
    if not title.strip():
        raise RuleViolation("The ticket needs a title.")
    _check_priority(priority)
    if phase_id:
        ph = db.get(Phase, phase_id)
        if ph is None or ph.project_id != project_id:
            raise RuleViolation("The chosen phase does not belong to this project.")
    if module_id and db.get(TicketModule, module_id) is None:
        raise NotFound(f"Module {module_id} not found.")
    _check_process(db, module_id or None, process_id or None, process_step_id or None,
                   project_id=project_id)
    # v1.6: nobody allocates a ticket while raising it. Every ticket goes to the
    # project's manager first, who sends it to the team that should own it. An
    # assignee_id still sent by an older client is ignored, not honoured — the
    # point of the step is that it cannot be skipped.
    now = datetime.utcnow()
    t = Ticket(project_id=project_id, phase_id=phase_id or None, module_id=module_id or None,
               process_id=process_id or None, process_step_id=process_step_id or None,
               title=title.strip(), description=description.strip() or None,
               priority=priority, status="Open", assignee_id=None,
               pm_id=project.owner_id, raised_by_user_id=caller.user.id,
               created_by=actor, created_at_utc=now, updated_at_utc=now)
    db.add(t)
    db.flush()
    await _store_files(db, t, files, actor)
    audit.record(db, actor, "Created", "Ticket", f"{t.number} {t.title}", project=project,
                 detail=f"waiting on {project.owner.name if project.owner else 'a project manager'}")
    db.commit()
    t = _load_ticket(db, t.id)
    MAIL.notify(db, t, "raised", actor=actor, body=t.description or "",
                actor_user_id=caller.user.id)
    db.commit()
    return _detail(db, t, caller)


@router.get("/{ticket_id}", response_model=TicketOut)
def ticket(ticket_id: int, db: Session = Depends(get_db),
           caller: Caller = Depends(current_user)):
    """Full detail: thread of responses and every attachment. The front end
    polls this, so replies from the other side appear automatically."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    return _detail(db, t, caller)


@router.put("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, req: TicketUpdateIn, db: Session = Depends(get_db),
                  actor: str = Depends(who),
                  caller: Caller = Depends(current_user)):
    """Change title/description, re-prioritise, move status, re-allocate, or
    re-point at another module or phase."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    changes = []
    # Whatever the request changes, the resulting combination has to hold —
    # moving a ticket to another module can strand a process it already names.
    # Only the combination the caller actually asked for is validated. Naming a
    # process that the chosen module does not run is a mistake and is refused.
    # Moving the module alone is not a mistake — it is a decision — so the
    # process that no longer applies is cleared below and said so in the reply,
    # rather than the whole move being blocked.
    if req.process_id is not None or req.process_step_id is not None:
        _check_process(db,
                       (req.module_id if req.module_id is not None else t.module_id) or None,
                       (req.process_id if req.process_id is not None else t.process_id) or None,
                       (req.process_step_id if req.process_step_id is not None
                        else t.process_step_id) or None)
    if req.title is not None and req.title.strip() and req.title.strip() != t.title:
        changes.append(audit.change("title", t.title, req.title.strip()))
        t.title = req.title.strip()
    if req.description is not None and (req.description.strip() or None) != t.description:
        t.description = req.description.strip() or None
        changes.append("description edited")
    if req.priority is not None and req.priority != t.priority:
        _check_priority(req.priority)
        changes.append(audit.change("priority", t.priority, req.priority))
        t.priority = req.priority
    if req.status is not None and req.status != t.status:
        _check_status(req.status)
        if req.status in ("Resolved", "Closed"):
            raise RuleViolation(
                "Resolve a ticket with its resolution, and close it from the resolved "
                "state — not by changing the status directly.")
        changes.append(audit.change("status", t.status, req.status))
        t.status = req.status
    if req.assignee_id != t.assignee_id:
        new_p = db.get(Person, req.assignee_id) if req.assignee_id else None
        if req.assignee_id and new_p is None:
            raise NotFound(f"Person {req.assignee_id} not found.")
        changes.append(audit.change("allocated to", t.assignee.name if t.assignee else "nobody",
                                    new_p.name if new_p else "nobody"))
        t.assignee_id = req.assignee_id or None
    if req.module_id != t.module_id:
        if req.module_id and db.get(TicketModule, req.module_id) is None:
            raise NotFound(f"Module {req.module_id} not found.")
        t.module_id = req.module_id or None
        changes.append("module changed")
    if req.phase_id != t.phase_id:
        if req.phase_id:
            ph = db.get(Phase, req.phase_id)
            if ph is None or ph.project_id != t.project_id:
                raise RuleViolation("The chosen phase does not belong to this project.")
        t.phase_id = req.phase_id or None
        changes.append("phase changed")
    if req.process_id is not None and req.process_id != t.process_id:
        t.process_id = req.process_id or None
        changes.append("process changed")
    if req.process_step_id is not None and req.process_step_id != t.process_step_id:
        t.process_step_id = req.process_step_id or None
        changes.append("process step changed")
    # Moving to another module can leave a process behind that the new module
    # does not run. Clear it rather than leave the ticket pointing at nothing.
    if t.process_id and t.module_id:
        still = db.execute(select(ModuleProcess).where(
            ModuleProcess.process_id == t.process_id,
            ModuleProcess.module_id == t.module_id)).scalar_one_or_none()
        if still is None:
            t.process_id = None
            t.process_step_id = None
            changes.append("process cleared, the new module does not run it")
    elif t.process_id and not t.module_id:
        t.process_id = None
        t.process_step_id = None
        changes.append("process cleared with the module")
    detail = "; ".join(c for c in changes if c)
    if detail:
        t.updated_at_utc = datetime.utcnow()
        audit.record(db, actor, "Updated", "Ticket", f"{t.number} {t.title}",
                     project=t.project, detail=detail)
    db.commit()
    return _ticket_out(_load_ticket(db, ticket_id), full=True)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    t = _load_ticket(db, ticket_id)
    keys = [a.storage_key for a in db.execute(select(TicketAttachment).where(
        TicketAttachment.ticket_id == t.id)).scalars() if a.storage_key]
    audit.record(db, actor, "Deleted", "Ticket", f"{t.number} {t.title}", project=t.project)
    db.delete(t)
    db.commit()
    # Only once the row is gone: a failed delete must not leave a ticket whose
    # files have already vanished from under it.
    for k in keys:
        FILES.remove(k)


@router.post("/{ticket_id}/responses", response_model=TicketOut, status_code=201)
async def respond(ticket_id: int, caller: Caller = Depends(current_user),
                  body: str = Form(...),
                  files: list[UploadFile] = File(default=[]),
                  db: Session = Depends(get_db), actor: str = Depends(who)):
    """Add a reply (documents welcome). The reply is on the ticket the moment
    this returns - the whole updated ticket comes back, and other viewers pick
    it up on their next poll. First reply on an Open ticket moves it to
    InProgress automatically."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    if not body.strip():
        raise RuleViolation("The response needs some text.")
    if t.status == "Closed":
        raise RuleViolation(f"{t.number} is closed. Reopen it to respond.")
    r = TicketResponse(ticket_id=t.id, author=actor, body=body.strip(),
                       created_at_utc=datetime.utcnow())
    db.add(r)
    db.flush()
    await _store_files(db, t, files, actor, response_id=r.id)
    if t.status == "Open":
        t.status = "InProgress"
    t.updated_at_utc = datetime.utcnow()
    audit.record(db, actor, "Responded", "Ticket", f"{t.number} {t.title}", project=t.project)
    db.commit()
    t = _load_ticket(db, ticket_id)
    MAIL.notify(db, t, "response", actor=actor, body=body.strip(),
                actor_user_id=caller.user.id)
    db.commit()
    return _detail(db, t, caller)


@router.get("/attachments/{attachment_id}")
def download(attachment_id: int, request: Request, exp: int | None = None,
             sig: str | None = None, db: Session = Depends(get_db),
             authorization: str | None = Header(None)):
    """Serve one attachment, to someone entitled to its ticket.

    This endpoint was open until v1.5: anybody who could reach the API could
    walk the ids and read every customer's files. It now accepts either a
    signed link (issued only inside a ticket the caller may see) or a bearer
    token whose holder may see the ticket. Both answer 404 rather than 403
    when the answer is no, so the existence of a file is not itself disclosed.
    """
    a = db.get(TicketAttachment, attachment_id)
    if a is None:
        raise NotFound(f"Attachment {attachment_id} not found.")

    allowed = FILES.signature_ok(attachment_id, exp, sig)
    if not allowed and authorization:
        try:
            caller = current_user(authorization=authorization, db=db)
        except Exception:
            caller = None
        if caller is not None:
            t = db.get(Ticket, a.ticket_id)
            allowed = t is not None and _may_touch(caller, t.project_id)
    if not allowed:
        raise NotFound(f"Attachment {attachment_id} not found.")

    safe = a.file_name.replace('"', "'").replace("\r", "").replace("\n", "")
    inline = (a.kind in FILES.INLINE_KINDS or a.content_type in FILES.INLINE_MIMES) \
        and request.query_params.get("download") != "1"
    headers = {
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{safe}"',
        # never let the browser second-guess the type it was given
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
    }
    if a.storage_key:
        # FileResponse streams from disk and honours Range requests, which a
        # <video> element needs to seek — and which Safari needs to play at all.
        return FileResponse(FILES.path_for(a.storage_key), media_type=a.content_type,
                            headers=headers)
    return Response(content=a.data or b"", media_type=a.content_type, headers=headers)


# ---- v1.6 actions ---------------------------------------------------------
@router.post("/{ticket_id}/route", response_model=TicketOut)
def route(ticket_id: int, body: dict = Body(...), db: Session = Depends(get_db),
          actor: str = Depends(who), caller: Caller = Depends(current_user)):
    """The project manager sends the ticket to the team that should own it.

    A team is a team role. Naming a person within it is optional; the whole
    team hears about it either way. Sending it again to another team is how a
    ticket that landed in the wrong place is moved on.
    """
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    _require(caller, t, "route", "Only the project manager for this project can route its tickets.")
    role = db.get(Role, int(body.get("team_role_id") or 0))
    if role is None:
        raise RuleViolation("Choose the team this ticket should go to.")
    if role.is_customer:
        raise RuleViolation(f"{role.name} is a customer role. Tickets go to a team at Aequm.")
    person = None
    if body.get("assignee_id"):
        person = db.get(Person, int(body["assignee_id"]))
        if person is None or person.role_id != role.id:
            raise RuleViolation("That person is not in the team you chose.")
    before = t.team_role.name if t.team_role else None
    t.team_role_id, t.assignee_id = role.id, person.id if person else None
    t.routed_by, t.routed_at_utc = actor, datetime.utcnow()
    t.updated_at_utc = datetime.utcnow()
    note = (body.get("note") or "").strip()
    if note:
        db.add(TicketResponse(ticket_id=t.id, author=actor,
                              body=f"Sent to {role.name}: {note}", created_at_utc=datetime.utcnow()))
    audit.record(db, actor, "Routed", "Ticket", f"{t.number} {t.title}", project=t.project,
                 detail=(f"{before} → " if before else "to ") + role.name
                 + (f", {person.name}" if person else ""))
    db.commit()
    t = _load_ticket(db, ticket_id)
    MAIL.notify(db, t, "routed", actor=actor, body=note, actor_user_id=caller.user.id)
    db.commit()
    return _detail(db, t, caller)


@router.post("/{ticket_id}/resolve", response_model=TicketOut)
def resolve(ticket_id: int, body: dict = Body(...), db: Session = Depends(get_db),
            actor: str = Depends(who), caller: Caller = Depends(current_user)):
    """The team records what was done. The resolution is what the raiser reads
    when deciding whether to close the ticket, so it has to say something."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    _require(caller, t, "resolve", "Only the team the ticket was sent to can resolve it.")
    text = (body.get("resolution") or "").strip()
    if len(text) < 10:
        raise RuleViolation("Describe the resolution — what was wrong and what was done.")
    t.status, t.resolution = "Resolved", text
    t.resolved_by, t.resolved_at_utc = actor, datetime.utcnow()
    t.updated_at_utc = datetime.utcnow()
    audit.record(db, actor, "Resolved", "Ticket", f"{t.number} {t.title}", project=t.project)
    db.commit()
    t = _load_ticket(db, ticket_id)
    MAIL.notify(db, t, "resolved", actor=actor, body=text, actor_user_id=caller.user.id)
    db.commit()
    return _detail(db, t, caller)


@router.post("/{ticket_id}/close", response_model=TicketOut)
def close(ticket_id: int, db: Session = Depends(get_db), actor: str = Depends(who),
          caller: Caller = Depends(current_user)):
    """The raiser confirms the resolution worked."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    _require(caller, t, "close", "Only whoever raised the ticket, or its project manager, can close it.")
    t.status, t.updated_at_utc = "Closed", datetime.utcnow()
    audit.record(db, actor, "Closed", "Ticket", f"{t.number} {t.title}", project=t.project)
    db.commit()
    return _detail(db, _load_ticket(db, ticket_id), caller)


@router.post("/{ticket_id}/reopen", response_model=TicketOut)
def reopen(ticket_id: int, body: dict = Body(...), db: Session = Depends(get_db),
           actor: str = Depends(who), caller: Caller = Depends(current_user)):
    """Not fixed. It goes back to the same team, with the reason on the thread,
    and the earlier resolution is kept there too rather than overwritten."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    _require(caller, t, "reopen", "Only whoever raised the ticket, or its project manager, can reopen it.")
    why = (body.get("reason") or "").strip()
    if len(why) < 5:
        raise RuleViolation("Say what is still wrong, so the team knows where to look.")
    earlier = t.resolution
    db.add(TicketResponse(ticket_id=t.id, author=actor, created_at_utc=datetime.utcnow(),
                          body=f"Reopened: {why}" + (f"\n\nEarlier resolution: {earlier}" if earlier else "")))
    # back to the team if it had one, otherwise back to the project manager
    t.status = "InProgress" if t.team_role_id else "Open"
    t.resolution = t.resolved_by = t.resolved_at_utc = None
    t.updated_at_utc = datetime.utcnow()
    audit.record(db, actor, "Reopened", "Ticket", f"{t.number} {t.title}", project=t.project, detail=why)
    db.commit()
    t = _load_ticket(db, ticket_id)
    MAIL.notify(db, t, "response", actor=actor, body=f"Reopened: {why}",
                actor_user_id=caller.user.id)
    db.commit()
    return _detail(db, t, caller)
