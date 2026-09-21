"""The customer master, and the three things a customer is assigned to.

A customer row is a code and a name. Nothing else belongs on it, because
everything else — which projects are theirs, which roles their people hold,
which accounts are theirs — is a relationship that changes on its own schedule.

The code is generated rather than typed. A code somebody types is a code
somebody mistypes, and two spellings of the same customer is the one mistake
that cannot be untangled later without re-pointing every project.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select

from .. import models as M
from ..services.audit import record as audit_record
from ..services.auth import Caller, current_user, require_admin

router = APIRouter(prefix="/api/customers", tags=["customers"])

CODE_PREFIX = "CUST-"
_CODE_RE = re.compile(rf"^{CODE_PREFIX}(\d+)$")


COUNTER = "customer"


def code_for(n: int) -> str:
    return f"{CODE_PREFIX}{n:04d}"


def _counter(db) -> M.Counter:
    row = db.get(M.Counter, COUNTER)
    if row is None:
        # An existing database may already hold codes; start above the highest
        # rather than at one, or the first new customer collides with an old.
        highest = 0
        for (code,) in db.execute(select(M.Customer.code)).all():
            m = _CODE_RE.match(code or "")
            if m:
                highest = max(highest, int(m.group(1)))
        row = M.Counter(name=COUNTER, value=highest)
        db.add(row)
        db.flush()
    return row


def take_code(db) -> str:
    """Allocate the next code and move the counter past it.

    The counter never goes back, so a deleted customer's code is retired rather
    than handed to the next one along.
    """
    row = _counter(db)
    row.value += 1
    db.flush()
    return code_for(row.value)


def peek_next(db) -> str:
    """What the next code will be, for the form. Read only."""
    return code_for(_counter(db).value + 1)


def _out(db, c: M.Customer) -> dict:
    projects = db.execute(select(M.Project).where(
        M.Project.customer_id == c.id).order_by(M.Project.code)).scalars().all()
    roles = db.execute(select(M.Role).where(
        M.Role.customer_id == c.id).order_by(M.Role.name)).scalars().all()
    users = db.execute(select(M.AppUser).where(
        M.AppUser.customer_id == c.id).order_by(M.AppUser.display_name)).scalars().all()
    return {
        "id": c.id, "code": c.code, "name": c.name, "active": bool(c.active),
        "projects": [{"id": p.id, "code": p.code, "name": p.name} for p in projects],
        "roles": [{"id": r.id, "name": r.name, "colour": r.colour} for r in roles],
        "users": [{"id": u.id, "display_name": u.display_name, "email": u.email,
                   "active": bool(u.active), "source": u.source} for u in users],
        "project_count": len(projects), "user_count": len(users),
    }


@router.get("")
def list_customers(caller: Caller = Depends(current_user)):
    """A customer user sees only their own customer, and only if assigned one."""
    db = caller.db
    q = select(M.Customer).order_by(M.Customer.code)
    if caller.is_customer:
        if not caller.user.customer_id:
            return []
        q = q.where(M.Customer.id == caller.user.customer_id)
    return [_out(db, c) for c in db.execute(q).scalars()]


@router.get("/next-code")
def peek_code(caller: Caller = Depends(require_admin)):
    """Shown on the form before saving. Provisional: the code is settled from
    the row's own id when it is created."""
    db = caller.db
    code = peek_next(db)
    db.commit()            # the counter row may have just been created
    return {"code": code, "provisional": True}


@router.post("", status_code=201)
def create_customer(body: dict = Body(...), caller: Caller = Depends(require_admin)):
    db = caller.db
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "A customer needs a name")
    clash = db.execute(select(M.Customer).where(
        func.lower(M.Customer.name) == name.lower())).scalar_one_or_none()
    if clash:
        raise HTTPException(409,
            f"{clash.name} already exists as {clash.code}. Two rows for one "
            "customer cannot be untangled once projects point at both.")
    c = M.Customer(code=take_code(db), name=name, active=1)
    db.add(c)
    db.commit()
    audit_record(db, caller.actor, "Create", "Customer", f"{c.code} {c.name}")
    db.commit()
    return _out(db, c)


@router.put("/{cid}")
def update_customer(cid: int, body: dict = Body(...),
                    caller: Caller = Depends(require_admin)):
    db = caller.db
    c = db.get(M.Customer, cid)
    if not c:
        raise HTTPException(404, "No such customer")
    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            raise HTTPException(422, "A customer needs a name")
        clash = db.execute(select(M.Customer).where(
            func.lower(M.Customer.name) == name.lower(),
            M.Customer.id != cid)).scalar_one_or_none()
        if clash:
            raise HTTPException(409, f"{clash.code} is already called {clash.name}")
        c.name = name
    if "active" in body:
        c.active = 1 if body["active"] else 0
    db.commit()
    audit_record(db, caller.actor, "Update", "Customer", f"{c.code} {c.name}")
    db.commit()
    return _out(db, c)


@router.delete("/{cid}", status_code=204)
def delete_customer(cid: int, caller: Caller = Depends(require_admin)):
    db = caller.db
    c = db.get(M.Customer, cid)
    if not c:
        raise HTTPException(404, "No such customer")
    blockers = []
    n = db.execute(select(func.count()).select_from(M.Project)
                   .where(M.Project.customer_id == cid)).scalar()
    if n:
        blockers.append(f"{n} project{'' if n == 1 else 's'}")
    n = db.execute(select(func.count()).select_from(M.AppUser)
                   .where(M.AppUser.customer_id == cid)).scalar()
    if n:
        blockers.append(f"{n} user{'' if n == 1 else 's'}")
    if blockers:
        raise HTTPException(409,
            f"{c.name} still has " + " and ".join(blockers) +
            ". Mark the customer inactive instead, so the history stays readable.")
    name = f"{c.code} {c.name}"
    db.delete(c)
    db.commit()
    audit_record(db, caller.actor, "Delete", "Customer", name)
    db.commit()


# ----------------------------------------------------------- assignments

@router.put("/{cid}/projects")
def set_projects(cid: int, body: dict = Body(...),
                 caller: Caller = Depends(require_admin)):
    """Replace the set of projects delivered for this customer.

    A project belongs to one customer, so assigning it here takes it off
    whoever had it before — which is said in the reply rather than done quietly.
    """
    db = caller.db
    c = db.get(M.Customer, cid)
    if not c:
        raise HTTPException(404, "No such customer")
    want = {int(x) for x in (body.get("project_ids") or [])}
    moved = []
    for pid in want:
        p = db.get(M.Project, pid)
        if not p:
            raise HTTPException(422, f"No project with id {pid}")
        if p.customer_id and p.customer_id != cid:
            prev = db.get(M.Customer, p.customer_id)
            moved.append(f"{p.code} was {prev.name if prev else 'another customer'}")
        p.customer_id = cid
    for p in db.execute(select(M.Project).where(
            M.Project.customer_id == cid)).scalars().all():
        if p.id not in want:
            p.customer_id = None
    db.commit()
    audit_record(db, caller.actor, "Update", "Customer", f"{c.code} {c.name}",
                 f"{len(want)} project(s) assigned")
    db.commit()
    return {"customer": _out(db, c), "moved": moved,
            "message": ("Saved." if not moved else
                        "Saved. " + "; ".join(moved) + ".")}


@router.put("/{cid}/roles")
def set_roles(cid: int, body: dict = Body(...),
              caller: Caller = Depends(require_admin)):
    """Which customer roles belong to this customer.

    Only roles already marked as customer roles can be attached; an internal
    role given to a customer would hand them the team's screens.
    """
    db = caller.db
    c = db.get(M.Customer, cid)
    if not c:
        raise HTTPException(404, "No such customer")
    want = {int(x) for x in (body.get("role_ids") or [])}
    for rid in want:
        r = db.get(M.Role, rid)
        if not r:
            raise HTTPException(422, f"No role with id {rid}")
        if not r.is_customer:
            raise HTTPException(409,
                f"{r.name} is a team role. Only customer roles can be given to "
                "a customer, or their people would reach the team's screens.")
        r.customer_id = cid
    for r in db.execute(select(M.Role).where(M.Role.customer_id == cid)).scalars().all():
        if r.id not in want:
            r.customer_id = None
    db.commit()
    audit_record(db, caller.actor, "Update", "Customer", f"{c.code} {c.name}",
                 f"{len(want)} role(s) assigned")
    db.commit()
    return _out(db, c)


@router.put("/{cid}/users")
def set_users(cid: int, body: dict = Body(...),
              caller: Caller = Depends(require_admin)):
    """Which accounts belong to this customer.

    Members of Aequm India are refused: a member already sees every project,
    and filing them under a customer would say something untrue about who they
    work for without changing what they can reach.
    """
    db = caller.db
    c = db.get(M.Customer, cid)
    if not c:
        raise HTTPException(404, "No such customer")
    want = {int(x) for x in (body.get("user_ids") or [])}
    for uid in want:
        u = db.get(M.AppUser, uid)
        if not u:
            raise HTTPException(422, f"No account with id {uid}")
        if u.user_type != "Guest":
            raise HTTPException(409,
                f"{u.display_name} is an Aequm India account, not a customer one.")
        u.customer_id = cid
    for u in db.execute(select(M.AppUser).where(
            M.AppUser.customer_id == cid)).scalars().all():
        if u.id not in want:
            u.customer_id = None
    db.commit()
    audit_record(db, caller.actor, "Update", "Customer", f"{c.code} {c.name}",
                 f"{len(want)} user(s) assigned")
    db.commit()
    return _out(db, c)


@router.get("/unassigned")
def unassigned(caller: Caller = Depends(require_admin)):
    """Guests with no customer yet.

    Worth its own list: an imported guest sees nothing at all until somebody
    says which customer they are from, and that is easy to forget.
    """
    db = caller.db
    rows = db.execute(select(M.AppUser).where(
        M.AppUser.user_type == "Guest",
        M.AppUser.customer_id.is_(None),
        M.AppUser.active == 1).order_by(M.AppUser.display_name)).scalars().all()
    return [{"id": u.id, "display_name": u.display_name, "email": u.email,
             "source": u.source} for u in rows]
