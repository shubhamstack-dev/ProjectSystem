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
from .routers import (activities, audit, auth, customer, customers, phases,
                      process, projects, team, tickets)
from .services.rules import NotFound, RuleViolation

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
