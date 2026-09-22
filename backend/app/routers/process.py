"""Processes, their ordered steps, and which modules run them.

A process is master data rather than a child of one module. Period-end close is
one process that finance, controlling and treasury all run; nesting it under a
single module would force a copy per module, and the copies drift apart the
first time somebody edits one of them.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..database import get_db
from ..services.audit import record as audit_record
from ..services.auth import Caller, current_user

router = APIRouter(prefix="/api", tags=["process"])


def _step_out(s: M.ProcessStep) -> dict:
    return {"id": s.id, "process_id": s.process_id, "name": s.name,
            "description": s.description, "sort_order": s.sort_order,
            "owner_role_id": s.owner_role_id,
            "owner_role": s.owner_role.name if s.owner_role else None,
            "active": bool(s.active)}


def _proc_out(p: M.Process, module_ids: list[int] | None = None) -> dict:
    return {"id": p.id, "name": p.name, "code": p.code,
            "project_id": p.project_id,
            "project_code": p.project.code if p.project else None,
            "project_name": p.project.name if p.project else None,
            "description": p.description, "active": bool(p.active),
            "steps": [_step_out(s) for s in p.steps],
            "step_count": len(p.steps),
            "module_ids": module_ids if module_ids is not None else []}


def _module_ids(db: Session, process_id: int) -> list[int]:
    return [r.module_id for r in db.execute(
        select(M.ModuleProcess).where(M.ModuleProcess.process_id == process_id)
        .order_by(M.ModuleProcess.sort_order, M.ModuleProcess.id)).scalars()]


# ------------------------------------------------------------------ processes

@router.get("/processes")
def list_processes(module_id: int | None = None, include_inactive: bool = False,
                   project_id: int | None = None,
                   caller: Caller = Depends(current_user)):
    """Every process, or only those assigned to one module."""
    db = caller.db
    q = select(M.Process)
    if not include_inactive:
        q = q.where(M.Process.active == 1)
    if project_id is not None:
        q = q.where(M.Process.project_id == project_id)
    if caller.is_customer:
        # a customer sees the processes of their own projects, no one else's
        mine = [r[0] for r in db.execute(select(M.Project.id).where(
            M.Project.customer_id == caller.user.customer_id)).all()] \
            if caller.user.customer_id else []
        q = q.where(M.Process.project_id.in_(mine or [-1]))
    rows = db.execute(q.order_by(M.Process.name)).scalars().all()
    if module_id is not None:
        assigned = {r.process_id for r in db.execute(
            select(M.ModuleProcess).where(M.ModuleProcess.module_id == module_id)).scalars()}
        rows = [p for p in rows if p.id in assigned]
    return [_proc_out(p, _module_ids(db, p.id)) for p in rows]


@router.post("/processes")
def create_process(body: dict = Body(...), caller: Caller = Depends(current_user)):
    db = caller.db
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "A process needs a name")
    # v1.6: a process is defined for one project, and its name need only be
    # unique there — two projects may each run their own "Period-end close".
    project = db.get(M.Project, int(body.get("project_id") or 0))
    if project is None:
        raise HTTPException(422, "Choose the project this process belongs to")
    if db.execute(select(M.Process).where(M.Process.name == name,
                  M.Process.project_id == project.id)).scalar_one_or_none():
        raise HTTPException(409, f"{project.code} already has a process called {name}")
    p = M.Process(name=name, project_id=project.id,
                  code=(body.get("code") or "").strip() or None,
                  description=body.get("description"),
                  active=1 if body.get("active", True) else 0)
    db.add(p)
    db.flush()

    # Steps may arrive with the process, which is how people actually think
    # about it: a process is the list of its steps.
    for i, s in enumerate(body.get("steps") or []):
        nm = (s.get("name") or "").strip()
        if not nm:
            continue
        db.add(M.ProcessStep(process_id=p.id, name=nm,
                             description=s.get("description"),
                             sort_order=s.get("sort_order", i + 1),
                             owner_role_id=s.get("owner_role_id")))
    for mid in body.get("module_ids") or []:
        _assign(db, p.id, int(mid))
    db.commit()
    audit_record(db, caller.actor, "Create", "Process", p.name,
                 f"{len(p.steps)} step(s)")
    db.commit()
    db.refresh(p)
    return _proc_out(p, _module_ids(db, p.id))


@router.put("/processes/{pid}")
def update_process(pid: int, body: dict = Body(...), caller: Caller = Depends(current_user)):
    db = caller.db
    p = db.get(M.Process, pid)
    if not p:
        raise HTTPException(404, "No such process")
    if "name" in body:
        nm = (body["name"] or "").strip()
        if not nm:
            raise HTTPException(422, "A process needs a name")
        clash = db.execute(select(M.Process).where(
            M.Process.name == nm, M.Process.id != pid,
            M.Process.project_id == p.project_id)).scalar_one_or_none()
        if clash:
            raise HTTPException(409, f"A process called {nm} already exists")
        p.name = nm
    for f in ("code", "description"):
        if f in body:
            setattr(p, f, (body[f] or "").strip() or None)
    if body.get("project_id") and int(body["project_id"]) != (p.project_id or 0):
        # Only a process made before v1.6, with no project yet, may be given one.
        # Moving a process between projects would strand the tickets raised on it.
        if p.project_id:
            raise HTTPException(409, "A process cannot move to another project. Create it there instead.")
        if not db.get(M.Project, int(body["project_id"])):
            raise HTTPException(422, "No such project")
        p.project_id = int(body["project_id"])
    if "active" in body:
        p.active = 1 if body["active"] else 0
    db.commit()
    audit_record(db, caller.actor, "Update", "Process", p.name)
    db.commit()
    return _proc_out(p, _module_ids(db, p.id))


@router.delete("/processes/{pid}")
def delete_process(pid: int, caller: Caller = Depends(current_user)):
    db = caller.db
    p = db.get(M.Process, pid)
    if not p:
        raise HTTPException(404, "No such process")
    used = db.execute(select(M.Ticket).where(M.Ticket.process_id == pid)).first()
    if used:
        raise HTTPException(409,
            "Tickets refer to this process. Mark it inactive instead, so those "
            "tickets keep saying what they were raised against.")
    name = p.name
    db.delete(p)
    db.commit()
    audit_record(db, caller.actor, "Delete", "Process", name)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- steps

@router.post("/processes/{pid}/steps")
def add_step(pid: int, body: dict = Body(...), caller: Caller = Depends(current_user)):
    db = caller.db
    p = db.get(M.Process, pid)
    if not p:
        raise HTTPException(404, "No such process")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "A step needs a name")
    if any(s.name.lower() == name.lower() for s in p.steps):
        raise HTTPException(409, f"{p.name} already has a step called {name}")
    order = body.get("sort_order")
    if order is None:
        order = (max([s.sort_order for s in p.steps], default=0) + 1)
    s = M.ProcessStep(process_id=pid, name=name, description=body.get("description"),
                      sort_order=order, owner_role_id=body.get("owner_role_id"),
                      active=1 if body.get("active", True) else 0)
    db.add(s)
    db.commit()
    audit_record(db, caller.actor, "Create", "ProcessStep", f"{p.name} / {name}")
    db.commit()
    return _step_out(s)


@router.put("/steps/{sid}")
def update_step(sid: int, body: dict = Body(...), caller: Caller = Depends(current_user)):
    db = caller.db
    s = db.get(M.ProcessStep, sid)
    if not s:
        raise HTTPException(404, "No such step")
    if "name" in body:
        nm = (body["name"] or "").strip()
        if not nm:
            raise HTTPException(422, "A step needs a name")
        s.name = nm
    for f in ("description",):
        if f in body:
            setattr(s, f, body[f])
    if "sort_order" in body:
        s.sort_order = int(body["sort_order"] or 0)
    if "owner_role_id" in body:
        s.owner_role_id = body["owner_role_id"]
    if "active" in body:
        s.active = 1 if body["active"] else 0
    db.commit()
    return _step_out(s)


@router.delete("/steps/{sid}")
def delete_step(sid: int, caller: Caller = Depends(current_user)):
    db = caller.db
    s = db.get(M.ProcessStep, sid)
    if not s:
        raise HTTPException(404, "No such step")
    if db.execute(select(M.Ticket).where(M.Ticket.process_step_id == sid)).first():
        raise HTTPException(409,
            "Tickets refer to this step. Mark it inactive instead.")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.put("/processes/{pid}/steps/order")
def reorder(pid: int, body: dict = Body(...), caller: Caller = Depends(current_user)):
    """Whole new order in one call, so the list cannot end up half-renumbered."""
    db = caller.db
    p = db.get(M.Process, pid)
    if not p:
        raise HTTPException(404, "No such process")
    ids = body.get("step_ids") or []
    mine = {s.id for s in p.steps}
    if set(ids) != mine:
        raise HTTPException(422,
            "The new order has to list every step of this process exactly once")
    for i, sid in enumerate(ids, start=1):
        db.get(M.ProcessStep, sid).sort_order = i
    db.commit()
    db.refresh(p)
    return _proc_out(p, _module_ids(db, p.id))


# ------------------------------------------------------- assignment to modules

def _assign(db: Session, process_id: int, module_id: int) -> None:
    exists = db.execute(select(M.ModuleProcess).where(
        M.ModuleProcess.process_id == process_id,
        M.ModuleProcess.module_id == module_id)).scalar_one_or_none()
    if not exists:
        db.add(M.ModuleProcess(process_id=process_id, module_id=module_id))


@router.get("/modules/{mid}/processes")
def module_processes(mid: int, caller: Caller = Depends(current_user)):
    db = caller.db
    if not db.get(M.TicketModule, mid):
        raise HTTPException(404, "No such module")
    links = db.execute(select(M.ModuleProcess).where(
        M.ModuleProcess.module_id == mid).order_by(
        M.ModuleProcess.sort_order, M.ModuleProcess.id)).scalars().all()
    out = []
    for l in links:
        p = db.get(M.Process, l.process_id)
        if p:
            out.append(_proc_out(p, _module_ids(db, p.id)))
    return out


@router.put("/modules/{mid}/processes")
def set_module_processes(mid: int, body: dict = Body(...),
                         caller: Caller = Depends(current_user)):
    """Replace the module's whole set of processes.

    A process already named on a ticket cannot be taken off the module —
    otherwise that ticket would point at a step the module no longer runs, and
    the reports built on module and process stop reconciling.
    """
    db = caller.db
    m = db.get(M.TicketModule, mid)
    if not m:
        raise HTTPException(404, "No such module")
    want = {int(x) for x in (body.get("process_ids") or [])}
    have = {l.process_id: l for l in db.execute(select(M.ModuleProcess).where(
        M.ModuleProcess.module_id == mid)).scalars()}

    blocked = []
    for pid, link in have.items():
        if pid in want:
            continue
        t = db.execute(select(M.Ticket).where(
            M.Ticket.module_id == mid, M.Ticket.process_id == pid)).first()
        if t:
            p = db.get(M.Process, pid)
            blocked.append(p.name if p else str(pid))
            continue
        db.delete(link)
    for pid in want - set(have):
        if not db.get(M.Process, pid):
            raise HTTPException(422, f"No process with id {pid}")
        _assign(db, pid, mid)
    db.commit()
    audit_record(db, caller.actor, "Update", "Module", m.name,
                 f"{len(want)} process(es) assigned")
    db.commit()
    result = module_processes(mid, caller)
    if blocked:
        return {"processes": result, "kept": blocked,
                "message": ("Kept " + ", ".join(blocked) +
                            " because tickets on this module refer to them.")}
    return {"processes": result, "kept": [], "message": "Saved."}
