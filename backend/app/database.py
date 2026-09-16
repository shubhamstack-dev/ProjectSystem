"""One SQLAlchemy session per request - the Python equivalent of the C#
PlanFactory: every unit of work gets a fresh, short-lived context."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    # allows the engine's non-persisted attributes to be declared on Activity
    __allow_unmapped__ = True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
