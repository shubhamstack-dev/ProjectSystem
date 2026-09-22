"""One throwaway database shared by every test module.

Each test file used to build its own engine and call
``app.dependency_overrides[get_db] = ...``. There is only one FastAPI app, so
the last module imported won, and the others silently ran against a database
that had none of their rows in it. One harness, imported by all of them.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("MAIL_WORKER", "0")   # tests drive the mail functions directly

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import database, models as M  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth as A  # noqa: E402

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)


@event.listens_for(engine, "connect")
def _fk_on(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")


database.Base.metadata.create_all(engine)
Testing = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_db():
    db = Testing()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[database.get_db] = override_db
client = TestClient(app)
# Deliberately header-free: the shared client carries a token, and a test that
# checks the API is shut must not be holding the key.
anon = TestClient(app)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_account(email, name, user_type="Member", admin=0):
    """An account and its token, created straight in the database."""
    db = Testing()
    u = M.AppUser(email=email, display_name=name, source="local",
                  user_type=user_type, password_hash=A.hash_password("a long password"),
                  is_admin=admin, active=1, created_at_utc=now())
    db.add(u)
    db.commit()
    tok = A.issue_token(u)
    uid = u.id
    db.close()
    return uid, tok


def H(token):
    return {"Authorization": f"Bearer {token}"}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content else None
