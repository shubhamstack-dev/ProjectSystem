from fastapi import Header

from ..services.auth import read_token


def who(authorization: str | None = Header(default=None),
        x_acting_as: str | None = Header(default=None, alias="X-Acting-As")) -> str:
    """Who the audit trail attributes a call to.

    The name comes from the signed token. X-Acting-As used to be the only
    source, and it is a header the caller writes: anyone could record their
    change under someone else's name. It is kept only as a fallback for a call
    that carries no token at all, which the API gate no longer lets through.
    """
    if authorization and authorization.lower().startswith("bearer "):
        payload = read_token(authorization.split(" ", 1)[1].strip())
        if payload:
            return (payload.get("nam") or payload.get("eml") or "Unattributed")[:120]
    return x_acting_as.strip() if x_acting_as and x_acting_as.strip() else "Unattributed"
