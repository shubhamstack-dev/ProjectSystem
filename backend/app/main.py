"""ProjectSystem API - FastAPI + SQLAlchemy + MySQL.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import CORS_ORIGINS
from sqlalchemy import text

from .database import Base, engine
from .routers import (activities, audit, auth, customer, customers, mail, phases,
                      process, projects, team, tickets)
from .services.rules import NotFound, RuleViolation, Forbidden

app = FastAPI(title="ProjectSystem API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RuleViolation)
async def rule_violation(_: Request, exc: RuleViolation):
    """A refused operation is a 409 with the reason and the rows that block it."""
    return JSONResponse(status_code=409, content={"message": exc.message, "blockers": exc.blockers})


@app.exception_handler(Forbidden)
async def forbidden(_: Request, exc: Forbidden):
    return JSONResponse(status_code=403, content={"message": str(exc), "blockers": []})


@app.exception_handler(NotFound)
async def not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"message": str(exc), "blockers": []})


@app.get("/api/health")
def health():
    return {"ok": True}


# One gate in front of every route: signed in, active, and customer accounts
# kept to the routes a customer needs. See services/gate.py for why.
from .services import gate as _gate
from .database import get_db as _get_db
_gate.install(app, _get_db)

app.include_router(projects.router)
app.include_router(activities.router)
app.include_router(team.router)
app.include_router(audit.router)
app.include_router(phases.router)
app.include_router(customer.router)
app.include_router(tickets.router)
app.include_router(auth.router)
app.include_router(process.router)
app.include_router(customers.router)
app.include_router(mail.router)

# ---- lightweight startup migration
Base.metadata.create_all(engine)          # creates any table that is not there yet

# Columns added to tables that already exist. Each runs on its own and is
# allowed to fail: a second start finds the column already there.
_ADDITIONS = [
    "ALTER TABLE role ADD COLUMN IsCustomer TINYINT NOT NULL DEFAULT 0",
    "ALTER TABLE ticket ADD COLUMN ProcessId INT NULL",
    "ALTER TABLE ticket ADD COLUMN ProcessStepId INT NULL",
    "ALTER TABLE project ADD COLUMN CustomerId INT NULL",
    "ALTER TABLE role ADD COLUMN CustomerId INT NULL",
    "ALTER TABLE app_user ADD COLUMN CustomerId INT NULL",
    "ALTER TABLE app_user ADD COLUMN MustChangePassword TINYINT NOT NULL DEFAULT 0",
    "ALTER TABLE ticket_attachment ADD COLUMN StorageKey VARCHAR(200) NULL",
    "ALTER TABLE ticket_attachment ADD COLUMN Sha256 CHAR(64) NULL",
    "ALTER TABLE ticket_attachment ADD COLUMN Kind VARCHAR(12) NOT NULL DEFAULT 'document'",
    # new rows keep their bytes on disk, so the old column must allow empty
    "ALTER TABLE ticket_attachment MODIFY Data MEDIUMBLOB NULL",
    # v1.6 triage
    "ALTER TABLE ticket ADD COLUMN RaisedByUserId INT NULL",
    "ALTER TABLE ticket ADD COLUMN PmId INT NULL",
    "ALTER TABLE ticket ADD COLUMN TeamRoleId INT NULL",
    "ALTER TABLE ticket ADD COLUMN RoutedBy VARCHAR(120) NULL",
    "ALTER TABLE ticket ADD COLUMN RoutedAtUtc DATETIME NULL",
    "ALTER TABLE ticket ADD COLUMN Resolution TEXT NULL",
    "ALTER TABLE ticket ADD COLUMN ResolvedBy VARCHAR(120) NULL",
    "ALTER TABLE ticket ADD COLUMN ResolvedAtUtc DATETIME NULL",
    # v1.6 processes belong to a project; a name is unique within one project only.
    # MySQL named the old unique index after its column.
    "ALTER TABLE process ADD COLUMN ProjectId INT NULL",
    "ALTER TABLE process DROP INDEX Name",
    "ALTER TABLE process ADD UNIQUE KEY uq_process_project_name (ProjectId, Name)",
]
for _sql in _ADDITIONS:
    try:
        with engine.begin() as cn:
            cn.execute(text(_sql))
    except Exception:
        pass

# First run with no accounts at all gets one administrator, so there is a way in.
try:
    from .database import SessionLocal
    from .services.auth import bootstrap_admin
    _db = SessionLocal()
    try:
        bootstrap_admin(_db)
    finally:
        _db.close()
except Exception as _e:                    # never stop the API booting over this
    print(f"[startup] could not check for an administrator account: {_e}")


# ---- the mail worker: sends the outbox and reads the mailbox in the background.
# Off in tests (MAIL_WORKER=0); a second API process is harmless, because each
# outbox row is claimed before it is sent and each inbound Message-ID is unique.
import os as _os
if _os.getenv("MAIL_WORKER", "1") != "0":
    try:
        from .database import SessionLocal as _SL
        from .services import mail as _mail
        _mail.start_worker(_SL)
    except Exception as _e:
        print(f"[startup] mail worker not started: {_e}", flush=True)
