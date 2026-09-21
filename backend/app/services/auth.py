"""Sign-in for ProjectSystem.

Before this, the product had no authentication at all: X-Acting-As was a name
typed into a box and anybody could be anybody. That is fine for a plan nobody
outside the room can reach, and not fine once customers raise tickets on it.

Two ways in, on purpose:

*Microsoft Entra ID* for Aequm India and for customers invited into the tenant.
The browser talks to Microsoft, this API never sees a password.

*Local accounts* so the product still starts, and still has an administrator,
on a machine with no Azure application registered. Without that fallback a
misconfigured tenant locks everyone out of their own system.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from .. import config
from ..database import get_db

# ------------------------------------------------------------------ passwords

_ROUNDS = 240_000


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("A password needs at least 8 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ROUNDS)
    return f"pbkdf2${_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Returns False rather than raising on a malformed
    hash, so a corrupt row cannot be told apart from a wrong password."""
    if not stored:
        return False
    try:
        scheme, rounds, salt_hex, want = stored.split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(dk.hex(), want)
    except Exception:
        return False


# --------------------------------------------------------------------- tokens

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def issue_token(user: M.AppUser) -> str:
    """A signed bearer token. The signature is over the whole payload, so the
    user id, the expiry and the flags cannot be edited by the holder."""
    payload = {"uid": user.id, "eml": user.email,
               "adm": int(user.is_admin), "typ": user.user_type,
               "exp": int(time.time()) + config.TOKEN_HOURS * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
    except ValueError:
        return None
    want = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ------------------------------------------------------------- request context

class Caller:
    """Who is making this request, and what they are allowed to reach."""

    def __init__(self, user: M.AppUser, db: Session):
        self.user = user
        self.db = db

    @property
    def is_admin(self) -> bool:
        return bool(self.user.is_admin)

    @property
    def is_customer(self) -> bool:
        return self.user.user_type == "Guest"

    @property
    def actor(self) -> str:
        """The name written to the audit trail. Taken from the signed token,
        never from a header the caller controls."""
        return self.user.display_name or self.user.email


def current_user(authorization: str | None = Header(None),
                 db: Session = Depends(get_db)) -> Caller:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue")
    payload = read_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(401, "That session has expired. Sign in again.")
    user = db.get(M.AppUser, payload["uid"])
    if not user or not user.active:
        raise HTTPException(401, "That account is no longer active")
    return Caller(user, db)


def require_admin(caller: Caller = Depends(current_user)) -> Caller:
    if not caller.is_admin:
        raise HTTPException(403, "Only an administrator can do that")
    return caller


def bootstrap_admin(db: Session) -> None:
    """Create the first local administrator if there is no account at all.

    The password is read from the environment when set, and otherwise generated
    and printed once. It is never written to a file: a default password baked
    into a product is the same as no password.
    """
    if db.execute(select(M.AppUser).limit(1)).first():
        return
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@aequm.in").strip().lower()
    pw = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    u = M.AppUser(email=email, display_name="Administrator", source="local",
                  user_type="Member", password_hash=hash_password(pw),
                  is_admin=1, active=1,
                  created_at_utc=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(u)
    db.commit()
    if not os.getenv("BOOTSTRAP_ADMIN_PASSWORD"):
        print("\n" + "=" * 68)
        print(f"  First run. Administrator created: {email}")
        print(f"  Password (shown once, not stored anywhere): {pw}")
        print("=" * 68 + "\n", flush=True)
