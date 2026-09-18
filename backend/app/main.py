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
from .routers import activities, audit, customer, phases, projects, team
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


app.include_router(projects.router)
app.include_router(activities.router)
app.include_router(team.router)
app.include_router(audit.router)
app.include_router(phases.router)
app.include_router(customer.router)

# ---- lightweight startup migration (v1.1: customer roles, phases, approvals)
Base.metadata.create_all(engine)          # creates phase / phase_assignment / date_approval
try:
    with engine.begin() as cn:            # existing installs: add the customer flag
        cn.execute(text("ALTER TABLE role ADD COLUMN IsCustomer TINYINT NOT NULL DEFAULT 0"))
except Exception:
    pass                                   # column already exists
