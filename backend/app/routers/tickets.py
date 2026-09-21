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

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..services.auth import Caller, current_user
from ..models import (ModuleProcess, Process, ProcessStep, TICKET_PRIORITIES, TICKET_STATUSES, Person, Phase, Project,
                      Ticket, TicketAttachment, TicketModule, TicketResponse)
from ..schemas import (TicketAttachmentOut, TicketModuleIn, TicketModuleOut,
                       TicketOut, TicketResponseOut, TicketUpdateIn)
from ..services import audit
from ..services.rules import NotFound, RuleViolation
from .common import who

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024   # 10 MB per file
MAX_FILES_PER_CALL = 10


# ---- mapping ---------------------------------------------------------------
def _att_out(a: TicketAttachment) -> TicketAttachmentOut:
    return TicketAttachmentOut(
        id=a.id, file_name=a.file_name, content_type=a.content_type,
        size_bytes=a.size_bytes, uploaded_by=a.uploaded_by,
        uploaded_at_utc=a.uploaded_at_utc, response_id=a.response_id)


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
        created_by=t.created_by, created_at_utc=t.created_at_utc, updated_at_utc=t.updated_at_utc,
        response_count=len(t.responses),
        attachments=[_att_out(a) for a in sorted(t.attachments, key=lambda x: x.id)
                     if a.response_id is None] if full else
                    [_att_out(a) for a in sorted(t.attachments, key=lambda x: x.id)
                     if a.response_id is None],
        responses=[_resp_out(r) for r in t.responses] if full else [])


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
    if len(files) > MAX_FILES_PER_CALL:
        raise RuleViolation(f"At most {MAX_FILES_PER_CALL} files can be attached in one go.")
    for f in files:
        blob = await f.read()
        if not blob:
            continue
        if len(blob) > MAX_ATTACHMENT_BYTES:
            raise RuleViolation(f'"{f.filename}" is larger than 10 MB.')
        db.add(TicketAttachment(
            ticket_id=ticket.id, response_id=response_id,
            file_name=(f.filename or "attachment")[:255],
            content_type=f.content_type or "application/octet-stream",
            size_bytes=len(blob), data=blob, uploaded_by=actor,
            uploaded_at_utc=datetime.utcnow()))


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
            assignee_id: int | None = None, db: Session = Depends(get_db),
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
    return [_ticket_out(t) for t in db.execute(q).scalars().all()]


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
                   process_id: int | None, step_id: int | None) -> None:
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
    _check_process(db, module_id or None, process_id or None, process_step_id or None)
    if assignee_id and db.get(Person, assignee_id) is None:
        raise NotFound(f"Person {assignee_id} not found.")

    now = datetime.utcnow()
    t = Ticket(project_id=project_id, phase_id=phase_id or None, module_id=module_id or None,
               process_id=process_id or None, process_step_id=process_step_id or None,
               title=title.strip(), description=description.strip() or None,
               priority=priority, status="Open", assignee_id=assignee_id or None,
               created_by=actor, created_at_utc=now, updated_at_utc=now)
    db.add(t)
    db.flush()
    await _store_files(db, t, files, actor)
    audit.record(db, actor, "Created", "Ticket", f"{t.number} {t.title}", project=project)
    db.commit()
    return _ticket_out(_load_ticket(db, t.id), full=True)


@router.get("/{ticket_id}", response_model=TicketOut)
def ticket(ticket_id: int, db: Session = Depends(get_db),
           caller: Caller = Depends(current_user)):
    """Full detail: thread of responses and every attachment. The front end
    polls this, so replies from the other side appear automatically."""
    t = _load_ticket(db, ticket_id)
    if not _may_touch(caller, t.project_id):
        raise NotFound(f"Ticket {ticket_id} not found.")
    return _ticket_out(t, full=True)


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
    audit.record(db, actor, "Deleted", "Ticket", f"{t.number} {t.title}", project=t.project)
    db.delete(t)
    db.commit()


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
    return _ticket_out(_load_ticket(db, ticket_id), full=True)


@router.get("/attachments/{attachment_id}")
def download(attachment_id: int, db: Session = Depends(get_db)):
    a = db.get(TicketAttachment, attachment_id)
    if a is None:
        raise NotFound(f"Attachment {attachment_id} not found.")
    safe = a.file_name.replace('"', "'")
    return Response(content=a.data, media_type=a.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})
