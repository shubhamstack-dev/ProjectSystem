"""One gate in front of the whole API.

v1.3 added sign-in by putting a check on each route that was being worked on
at the time. The rest were left open, and v1.4 inherited that: an audit found
40 routes answering with nobody signed in — deleting tickets, editing projects,
reading the audit trail and the team directory, approving another customer's
dates. Per-route checks are how that happens. A route written tomorrow would be
open by default.

So the rule now lives in one place and runs before any route:

* Nothing under /api answers without a valid, unexpired token belonging to an
  active account — apart from a short, named list of public routes.
* A customer account (a directory Guest) may reach only the routes a customer
  needs: their tickets, their projects, the lists a ticket form draws from, and
  their own account. Everything else is refused outright, whatever the route
  would otherwise have done.

Routes that a customer may reach still scope what they return to that
customer's projects. The gate decides *whether* a caller may knock; the route
decides *what* they are shown.
"""
from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse

from .. import models as M
from .auth import read_token

# Reachable with nobody signed in. Kept deliberately short.
PUBLIC = [
    ("GET", r"/api/health"),
    ("GET", r"/api/auth/options"),
    ("POST", r"/api/auth/login"),
    ("GET", r"/api/auth/microsoft/start"),
    ("POST", r"/api/auth/microsoft/callback"),
    # authorises itself: a signed link, or a bearer token checked inside
    ("GET", r"/api/tickets/attachments/\d+"),
]

# What a customer account may do: raise tickets, follow them, reply, and see
# the projects that are theirs. Nothing that edits a plan, a master or a person.
CUSTOMER = [
    ("GET", r"/api/auth/me"),
    ("POST", r"/api/auth/password"),
    ("GET", r"/api/tickets"),
    ("POST", r"/api/tickets"),
    ("GET", r"/api/tickets/\d+"),
    ("POST", r"/api/tickets/\d+/responses"),
    ("POST", r"/api/tickets/\d+/close"),
    ("POST", r"/api/tickets/\d+/reopen"),
    ("GET", r"/api/tickets/modules"),
    ("GET", r"/api/tickets/attachments/\d+"),
    ("GET", r"/api/projects"),
    ("GET", r"/api/projects/\d+"),
    ("GET", r"/api/projects/\d+/phases"),
    ("GET", r"/api/processes"),
    ("GET", r"/api/customers"),
    ("GET", r"/api/customer/projects"),
    ("GET", r"/api/customer/projects/\d+/lines"),
    ("POST", r"/api/customer/lines/\d+/approve"),
    ("POST", r"/api/customer/lines/\d+/reject"),
]

PASSWORD_ONLY = [("GET", r"/api/auth/me"), ("POST", r"/api/auth/password")]

_PUBLIC = [(m, re.compile(p + r"/?$")) for m, p in PUBLIC]
_PASSWORD_ONLY = [(m, re.compile(p + r"/?$")) for m, p in PASSWORD_ONLY]
_CUSTOMER = [(m, re.compile(p + r"/?$")) for m, p in CUSTOMER]


def _match(rules, method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in rules)


def install(app, get_db) -> None:
    """Attach the gate to the app.

    The database session comes from the same dependency the routes use, looked
    up through app.dependency_overrides, so the gate and the routes always see
    the same database — including the test database.
    """

    @app.middleware("http")
    async def api_gate(request: Request, call_next):
        path = request.url.path
        method = request.method
        if not path.startswith("/api/") or method == "OPTIONS" \
                or _match(_PUBLIC, method, path):
            return await call_next(request)

        auth = request.headers.get("authorization") or ""
        payload = read_token(auth.split(" ", 1)[1].strip()) \
            if auth.lower().startswith("bearer ") else None
        if not payload:
            return JSONResponse({"detail": "Sign in to continue"}, status_code=401)

        # Checked against the database on every call, not only at sign-in:
        # deactivating an account has to cut it off now, not when its token
        # happens to expire twelve hours later.
        provider = app.dependency_overrides.get(get_db, get_db)
        gen = provider()
        db = next(gen)
        try:
            user = db.get(M.AppUser, payload.get("uid"))
            active = bool(user and user.active)
            is_guest = bool(user and user.user_type == "Guest")
            must_change = bool(user and getattr(user, "must_change_password", 0))
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
        if not active:
            return JSONResponse({"detail": "That account is no longer active"}, status_code=401)
        # A password somebody else chose, or has seen, is not a secret. Until
        # the holder replaces it, the account can do nothing but replace it —
        # otherwise whoever read the temporary password could use it.
        if must_change and not _match(_PASSWORD_ONLY, method, path):
            return JSONResponse(
                {"detail": "Choose your own password before continuing.",
                 "must_change_password": True}, status_code=403)
        if is_guest and not _match(_CUSTOMER, method, path):
            return JSONResponse(
                {"detail": "That is not available to customer accounts."}, status_code=403)
        return await call_next(request)
