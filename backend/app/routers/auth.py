"""Sign-in, Microsoft Entra ID, and importing users from the directory."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models as M
from ..database import get_db
from ..services import entra as E
from ..services.auth import (Caller, current_user, hash_password, issue_token,
                             require_admin, verify_password)
from ..services.audit import record as audit_record

router = APIRouter(prefix="/api/auth", tags=["auth"])

# state -> (verifier, created_at). In one process and short-lived on purpose;
# a multi-worker deployment wants this in Redis or a signed cookie instead.
_PENDING: dict[str, tuple[str, float]] = {}
_STATE_TTL = 600


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sweep() -> None:
    cutoff = time.time() - _STATE_TTL
    for k in [k for k, (_, t) in _PENDING.items() if t < cutoff]:
        _PENDING.pop(k, None)


def _user_out(u: M.AppUser, db: Session | None = None) -> dict:
    """The account as the UI needs it.

    The customer is part of it, because the sidebar names it and the sign-in
    response is what the UI holds until the next /me. Leaving it out here made
    the sidebar say only "Customer" straight after signing in and the real name
    only after a refresh.
    """
    return {"id": u.id, "email": u.email, "display_name": u.display_name,
            "source": u.source, "user_type": u.user_type,
            "is_admin": bool(u.is_admin), "is_customer": u.user_type == "Guest",
            "person_id": u.person_id,
            "customer_id": u.customer_id,
            "customer": _customer_brief(db, u),
            "last_login_utc": u.last_login_utc}


def _customer_brief(db, u: M.AppUser) -> dict | None:
    if not db or not u.customer_id:
        return None
    c = db.get(M.Customer, u.customer_id)
    return {"id": c.id, "code": c.code, "name": c.name} if c else None


# ------------------------------------------------------------------ options

@router.get("/options")
def options():
    """What the sign-in screen should offer. Called before anyone is signed in."""
    return {
        "local": True,
        "microsoft": E.configured(),
        "microsoft_reason": None if E.configured() else
            "No Entra tenant is configured on this server",
        "directory_import": E.can_import(),
    }


# -------------------------------------------------------------- local sign-in

@router.post("/login")
def login(body: dict = Body(...), db: Session = Depends(get_db)):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    u = db.execute(select(M.AppUser).where(M.AppUser.email == email)).scalar_one_or_none()
    # The same message either way. Saying "no such account" tells an attacker
    # which addresses are worth guessing passwords for.
    if not u or not u.active or u.source != "local" or not verify_password(password, u.password_hash):
        raise HTTPException(401, "That email and password do not match an account")
    u.last_login_utc = _now()
    db.commit()
    return {"token": issue_token(u), "user": _user_out(u, db)}


@router.get("/me")
def me(caller: Caller = Depends(current_user)):
    out = _user_out(caller.user, caller.db)
    if not out["customer"]:
        if caller.is_customer:
            # Worth saying out loud: the screens will be empty and it is not a bug.
            out["notice"] = ("No customer has been assigned to this account yet, "
                             "so no projects are visible. Ask Aequm India to assign one.")
    return out


@router.post("/password")
def change_password(body: dict = Body(...), caller: Caller = Depends(current_user)):
    u = caller.user
    if u.source != "local":
        raise HTTPException(409,
            "This account signs in through Microsoft, so its password is managed there")
    if not verify_password(body.get("current") or "", u.password_hash):
        raise HTTPException(401, "The current password is not right")
    try:
        u.password_hash = hash_password(body.get("new") or "")
    except ValueError as e:
        raise HTTPException(422, str(e))
    caller.db.commit()
    return {"ok": True}


# ---------------------------------------------------------- Microsoft sign-in

@router.get("/microsoft/start")
def microsoft_start(redirect_uri: str | None = None):
    """Hand the browser the Microsoft URL to go to."""
    if not E.configured():
        raise HTTPException(409,
            "Microsoft sign-in is not set up on this server. Add ENTRA_TENANT_ID "
            "and ENTRA_CLIENT_ID to the backend .env and restart the API.")
    _sweep()
    state = secrets.token_urlsafe(24)
    verifier, challenge = E.new_pkce()
    _PENDING[state] = (verifier, time.time())
    uri = redirect_uri or config.ENTRA_REDIRECT_URI
    return {"url": E.authorize_url(state, challenge, uri), "state": state}


@router.post("/microsoft/callback")
def microsoft_callback(body: dict = Body(...), db: Session = Depends(get_db)):
    """Swap the code Microsoft sent back for a session on this product."""
    code = (body.get("code") or "").strip()
    state = (body.get("state") or "").strip()
    redirect_uri = body.get("redirect_uri") or config.ENTRA_REDIRECT_URI
    if not code or not state:
        raise HTTPException(422, "Microsoft did not return a code")
    _sweep()
    pending = _PENDING.pop(state, None)
    if not pending:
        # Either a replay, or the user sat on the Microsoft page too long.
        raise HTTPException(400,
            "That sign-in attempt is no longer valid. Start again from the sign-in screen.")
    verifier, _ = pending

    try:
        claims = E.exchange_code(code, verifier, redirect_uri)
    except (E.EntraNotConfigured, E.EntraError) as e:
        raise HTTPException(502, str(e))

    oid = claims.get("oid") or claims.get("sub")
    email = (claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    name = claims.get("name") or email
    # Entra sets this claim only on guests, so its absence means member.
    user_type = "Guest" if claims.get("acct") == 1 else "Member"
    if not oid:
        raise HTTPException(502, "Microsoft returned no object id for that account")

    u = db.execute(select(M.AppUser).where(M.AppUser.entra_oid == oid)).scalar_one_or_none()
    if u is None:
        # An account matched on address alone could be someone else entirely.
        # It is only adopted when it has no Entra identity of its own yet.
        by_email = db.execute(select(M.AppUser).where(
            M.AppUser.email == email)).scalar_one_or_none() if email else None
        if by_email and by_email.entra_oid and by_email.entra_oid != oid:
            raise HTTPException(409,
                f"{email} is already linked to a different Microsoft account")
        allowed = (config.ENTRA_AUTO_PROVISION_GUESTS if user_type == "Guest"
                   else config.ENTRA_AUTO_PROVISION_MEMBERS)
        if by_email is None and not allowed:
            raise HTTPException(403,
                "That account has not been given access to this system yet. "
                "Ask Aequm India to import you from the directory first.")
        u = by_email or M.AppUser(email=email or f"{oid}@entra",
                                  display_name=name, created_at_utc=_now())
        u.source = "entra"
        u.entra_oid = oid
        u.tenant_id = claims.get("tid")
        u.user_type = user_type
        u.display_name = name or u.display_name
        if email:
            u.email = email
        db.add(u)
        db.flush()
    else:
        # The directory is the source of truth for name and address. Somebody
        # who marries, changes surname and keeps the account would otherwise
        # stay under the old name here for ever, while their colleagues see the
        # new one everywhere else.
        u.display_name = name or u.display_name
        if email and email != u.email:
            clash = db.execute(select(M.AppUser).where(
                M.AppUser.email == email, M.AppUser.id != u.id)).scalar_one_or_none()
            if not clash:
                u.email = email
        u.user_type = user_type
        u.tenant_id = claims.get("tid") or u.tenant_id
    _ensure_person(db, u, None, None)
    if not u.active:
        raise HTTPException(403, "That account has been deactivated here")

    u.last_login_utc = _now()
    db.commit()
    audit_record(db, u.display_name, "SignIn", "Account", u.email,
                 "Signed in with Microsoft")
    db.commit()
    return {"token": issue_token(u), "user": _user_out(u, db)}


# ------------------------------------------------------ directory import

def _org_and_role(db: Session, user_type: str) -> tuple[M.Organisation, M.Role]:
    """The organisation and role an imported user is filed under, made if absent."""
    is_guest = user_type == "Guest"
    org_name = config.ENTRA_GUEST_ORG if is_guest else config.ENTRA_MEMBER_ORG
    role_name = config.ENTRA_GUEST_ROLE if is_guest else config.ENTRA_MEMBER_ROLE

    org = db.execute(select(M.Organisation).where(
        M.Organisation.name == org_name)).scalar_one_or_none()
    if org is None:
        org = M.Organisation(name=org_name,
                             description="Created by the directory import")
        db.add(org)
        db.flush()
    role = db.execute(select(M.Role).where(
        M.Role.name == role_name, M.Role.organisation_id == org.id)).scalar_one_or_none()
    if role is None:
        role = M.Role(name=role_name, organisation_id=org.id,
                      responsibilities="Set by the directory import",
                      colour="#8A63D2" if is_guest else "#2F6F9E",
                      view_access="tickets" if is_guest else "portfolio,plan,assign,miles,tickets",
                      is_customer=1 if is_guest else 0)
        db.add(role)
        db.flush()
    return org, role


def _ensure_person(db: Session, u: M.AppUser, job: str | None, dept: str | None) -> M.Person:
    """Every signed-in account needs a Person row to be assignable work."""
    if u.person_id:
        p = db.get(M.Person, u.person_id)
        if p:
            p.name = u.display_name or p.name
            if u.email:
                p.email = u.email
            return p
    p = db.execute(select(M.Person).where(
        M.Person.email == u.email)).scalar_one_or_none() if u.email else None
    if p is None:
        p = M.Person(name=u.display_name or u.email, email=u.email)
        db.add(p)
        db.flush()
    if p.role_id is None:
        _, role = _org_and_role(db, u.user_type)
        p.role_id = role.id
    u.person_id = p.id
    return p


@router.get("/directory/users")
def directory_users(search: str | None = None, limit: int = 200,
                    caller: Caller = Depends(require_admin)):
    """Read the tenant without importing anything, so it can be looked at first."""
    try:
        users = E.fetch_users(limit=limit, search=search)
    except E.EntraNotConfigured as e:
        raise HTTPException(409, str(e))
    except E.EntraError as e:
        raise HTTPException(502, str(e))

    db = caller.db
    known = {u.entra_oid for u in db.execute(
        select(M.AppUser).where(M.AppUser.entra_oid.is_not(None))).scalars()}
    for u in users:
        u["already_here"] = u["oid"] in known
    members = sum(1 for u in users if u["user_type"] != "Guest")
    return {"users": users, "count": len(users),
            "members": members, "guests": len(users) - members,
            "already_here": sum(1 for u in users if u["already_here"])}


@router.post("/directory/import")
def directory_import(body: dict = Body(default={}),
                     caller: Caller = Depends(require_admin)):
    """Create or refresh accounts from the directory.

    Matching is on the Entra object id, never on the address. People change
    surname and keep the account; matching on mail would import them a second
    time and orphan everything assigned to the first row.
    """
    db = caller.db
    oids = body.get("oids")
    try:
        users = E.fetch_users(limit=int(body.get("limit", 500)),
                              search=body.get("search"))
    except E.EntraNotConfigured as e:
        raise HTTPException(409, str(e))
    except E.EntraError as e:
        raise HTTPException(502, str(e))

    if oids:
        want = set(oids)
        users = [u for u in users if u["oid"] in want]

    created = updated = skipped = 0
    notes: list[str] = []
    for g in users:
        if not g["oid"]:
            skipped += 1
            continue
        if not g["enabled"]:
            skipped += 1
            notes.append(f"{g['display_name']}: disabled in the directory")
            continue
        u = db.execute(select(M.AppUser).where(
            M.AppUser.entra_oid == g["oid"])).scalar_one_or_none()
        if u is None and g["email"]:
            u = db.execute(select(M.AppUser).where(
                M.AppUser.email == g["email"])).scalar_one_or_none()
            if u is not None and u.entra_oid and u.entra_oid != g["oid"]:
                skipped += 1
                notes.append(f"{g['email']}: already linked to another Microsoft account")
                continue
        if u is None:
            u = M.AppUser(email=g["email"] or f"{g['oid']}@entra",
                          display_name=g["display_name"], created_at_utc=_now())
            db.add(u)
            created += 1
        else:
            updated += 1
        u.source = "entra"
        u.entra_oid = g["oid"]
        u.tenant_id = config.ENTRA_TENANT_ID
        u.user_type = g["user_type"]
        u.display_name = g["display_name"] or u.display_name
        if g["email"]:
            u.email = g["email"]
        u.active = 1
        db.flush()
        _ensure_person(db, u, g.get("job_title"), g.get("department"))

    run = M.DirectorySync(run_by=caller.actor, run_at_utc=_now(),
                          fetched=len(users), created=created, updated=updated,
                          skipped=skipped, detail="\n".join(notes[:50]) or None)
    db.add(run)
    db.commit()
    audit_record(db, caller.actor, "Import", "Directory",
                 f"Entra run #{run.id}",
                 f"Fetched {len(users)}, created {created}, "
                 f"updated {updated}, skipped {skipped}")
    db.commit()
    return {"fetched": len(users), "created": created, "updated": updated,
            "skipped": skipped, "notes": notes[:50],
            "message": (f"{created} created, {updated} refreshed"
                        + (f", {skipped} skipped" if skipped else "")
                        + " from the directory.")}


@router.get("/directory/history")
def directory_history(caller: Caller = Depends(require_admin)):
    rows = caller.db.execute(select(M.DirectorySync).order_by(
        M.DirectorySync.id.desc()).limit(25)).scalars().all()
    return [{"id": r.id, "run_by": r.run_by, "run_at_utc": r.run_at_utc,
             "fetched": r.fetched, "created": r.created, "updated": r.updated,
             "skipped": r.skipped, "detail": r.detail} for r in rows]


# ------------------------------------------------------------------- accounts

@router.get("/users")
def list_users(caller: Caller = Depends(require_admin)):
    rows = caller.db.execute(select(M.AppUser).order_by(M.AppUser.display_name)).scalars().all()
    return [_user_out(u) for u in rows]


@router.post("/users")
def create_local_user(body: dict = Body(...), caller: Caller = Depends(require_admin)):
    """A local account, for people who are not in the directory at all."""
    db = caller.db
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(422, "An email address is required")
    if db.execute(select(M.AppUser).where(M.AppUser.email == email)).scalar_one_or_none():
        raise HTTPException(409, f"{email} already has an account")
    try:
        pw = hash_password(body.get("password") or "")
    except ValueError as e:
        raise HTTPException(422, str(e))
    u = M.AppUser(email=email, display_name=(body.get("display_name") or email).strip(),
                  source="local", user_type=body.get("user_type") or "Member",
                  password_hash=pw, is_admin=1 if body.get("is_admin") else 0,
                  active=1, created_at_utc=_now())
    db.add(u)
    db.flush()
    _ensure_person(db, u, None, None)
    db.commit()
    return _user_out(u)


@router.put("/users/{uid}")
def update_user(uid: int, body: dict = Body(...), caller: Caller = Depends(require_admin)):
    db = caller.db
    u = db.get(M.AppUser, uid)
    if not u:
        raise HTTPException(404, "No such account")
    if "is_admin" in body:
        if u.id == caller.user.id and not body["is_admin"]:
            # Otherwise the last administrator can lock the whole product.
            others = db.execute(select(M.AppUser).where(
                M.AppUser.is_admin == 1, M.AppUser.id != u.id,
                M.AppUser.active == 1)).first()
            if not others:
                raise HTTPException(409,
                    "You are the only administrator. Make somebody else one first.")
        u.is_admin = 1 if body["is_admin"] else 0
    if "active" in body:
        u.active = 1 if body["active"] else 0
    if "display_name" in body and body["display_name"]:
        u.display_name = body["display_name"].strip()
    db.commit()
    return _user_out(u)
