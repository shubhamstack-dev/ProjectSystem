from fastapi import Header


def who(x_acting_as: str | None = Header(default=None, alias="X-Acting-As")) -> str:
    """Who the audit trail attributes a call to. A record, not authentication."""
    return x_acting_as.strip() if x_acting_as and x_acting_as.strip() else "Unattributed"
