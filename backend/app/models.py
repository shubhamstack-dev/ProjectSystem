"""ORM mapping of schema.sql. Table and column names match the SQL exactly so
the same database works for this backend and the earlier C# one.

Computed values (computed_start, total_float, is_critical, wbs ...) are plain
Python attributes filled by the scheduling engine - never stored."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Date, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# enums kept as ints, exactly as the schema stores them
KIND_NAMES = {0: "Milestone", 1: "Task", 2: "Subtask"}
DEP_TYPE_NAMES = {0: "FS", 1: "SS", 2: "FF", 3: "SF"}
MODE_NAMES = {0: "Auto", 1: "Manual"}
STATUS_NAMES = {0: "Active", 1: "OnHold", 2: "Done"}


class Organisation(Base):
    __tablename__ = "organisation"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column("Description", String(600))

    roles: Mapped[list["Role"]] = relationship(back_populates="organisation")
    projects: Mapped[list["Project"]] = relationship(back_populates="organisation")


class Role(Base):
    __tablename__ = "role"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    responsibilities: Mapped[str | None] = mapped_column("Responsibilities", String(1000))
    colour: Mapped[str] = mapped_column("Colour", String(9), nullable=False, default="#2F6F9E")
    view_access: Mapped[str] = mapped_column("ViewAccess", String(200), nullable=False,
                                             default="portfolio,plan,assign,miles")
    organisation_id: Mapped[int | None] = mapped_column("OrganisationId", ForeignKey("organisation.Id", ondelete="SET NULL"))

    organisation: Mapped[Organisation | None] = relationship(back_populates="roles")
    people: Mapped[list["Person"]] = relationship(back_populates="role")


class Person(Base):
    __tablename__ = "person"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    email: Mapped[str | None] = mapped_column("Email", String(200))
    role_id: Mapped[int | None] = mapped_column("RoleId", ForeignKey("role.Id", ondelete="SET NULL"))

    role: Mapped[Role | None] = relationship(back_populates="people")


class Project(Base):
    __tablename__ = "project"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column("Code", String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column("Name", String(200), nullable=False)
    planned_start: Mapped[date] = mapped_column("PlannedStart", Date, nullable=False)
    planned_end: Mapped[date | None] = mapped_column("PlannedEnd", Date)
    status: Mapped[int] = mapped_column("Status", Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column("Notes", Text)
    organisation_id: Mapped[int | None] = mapped_column("OrganisationId", ForeignKey("organisation.Id", ondelete="SET NULL"))
    owner_id: Mapped[int | None] = mapped_column("OwnerId", ForeignKey("person.Id", ondelete="SET NULL"))

    organisation: Mapped[Organisation | None] = relationship(back_populates="projects")
    owner: Mapped[Person | None] = relationship(foreign_keys=[owner_id])
    team: Mapped[list["ProjectTeamMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    holidays: Mapped[list["Holiday"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    activities: Mapped[list["Activity"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectTeamMember(Base):
    __tablename__ = "project_team"
    project_id: Mapped[int] = mapped_column("ProjectId", ForeignKey("project.Id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column("PersonId", ForeignKey("person.Id", ondelete="CASCADE"), primary_key=True)

    project: Mapped[Project] = relationship(back_populates="team")
    person: Mapped[Person] = relationship()


class Holiday(Base):
    __tablename__ = "holiday"
    __table_args__ = (UniqueConstraint("ProjectId", "Date", name="ux_holiday"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column("ProjectId", ForeignKey("project.Id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False)

    project: Mapped[Project] = relationship(back_populates="holidays")


class Activity(Base):
    __tablename__ = "activity"
    __table_args__ = (Index("ix_activity_seq", "ProjectId", "Sequence"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column("ProjectId", ForeignKey("project.Id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column("Sequence", Integer, nullable=False)
    level: Mapped[int] = mapped_column("Level", Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column("Name", String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column("Notes", Text)
    mode: Mapped[int] = mapped_column("Mode", Integer, nullable=False, default=0)
    duration: Mapped[int] = mapped_column("Duration", Integer, nullable=False, default=0)
    planned_start: Mapped[date | None] = mapped_column("PlannedStart", Date)
    planned_finish: Mapped[date | None] = mapped_column("PlannedFinish", Date)
    target_date: Mapped[date | None] = mapped_column("TargetDate", Date)
    actual_start: Mapped[date | None] = mapped_column("ActualStart", Date)
    actual_finish: Mapped[date | None] = mapped_column("ActualFinish", Date)
    percent_complete: Mapped[int] = mapped_column("PercentComplete", Integer, nullable=False, default=0)
    role_id: Mapped[int | None] = mapped_column("RoleId", ForeignKey("role.Id", ondelete="SET NULL"))
    baseline_start: Mapped[int | None] = mapped_column("BaselineStart", Integer)
    baseline_finish: Mapped[int | None] = mapped_column("BaselineFinish", Integer)

    project: Mapped[Project] = relationship(back_populates="activities")
    role: Mapped[Role | None] = relationship()
    dependencies: Mapped[list["ActivityDependency"]] = relationship(
        back_populates="activity", foreign_keys="ActivityDependency.activity_id", cascade="all, delete-orphan")
    assignees: Mapped[list["ActivityAssignee"]] = relationship(back_populates="activity", cascade="all, delete-orphan")

    # ---- filled by the scheduling engine, not persisted ----
    computed_start: int = 0
    computed_finish: int = 0
    total_float: int = 0
    is_critical: bool = False
    is_summary: bool = False
    wbs: str = ""
    computed_start_date: date | None = None
    computed_finish_date: date | None = None

    @property
    def kind(self) -> int:
        return min(2, max(0, self.level))

    @property
    def kind_name(self) -> str:
        return KIND_NAMES[self.kind]

    @property
    def has_actuals(self) -> bool:
        return self.actual_start is not None or self.actual_finish is not None


class ActivityDependency(Base):
    __tablename__ = "activity_dependency"
    __table_args__ = (UniqueConstraint("ActivityId", "PredecessorId", name="ux_dep"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column("ActivityId", ForeignKey("activity.Id", ondelete="CASCADE"), nullable=False)
    predecessor_id: Mapped[int] = mapped_column("PredecessorId", ForeignKey("activity.Id", ondelete="RESTRICT"), nullable=False)
    type: Mapped[int] = mapped_column("Type", Integer, nullable=False, default=0)
    lag: Mapped[int] = mapped_column("Lag", Integer, nullable=False, default=0)

    activity: Mapped[Activity] = relationship(back_populates="dependencies", foreign_keys=[activity_id])


class ActivityAssignee(Base):
    __tablename__ = "activity_assignee"
    activity_id: Mapped[int] = mapped_column("ActivityId", ForeignKey("activity.Id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column("PersonId", ForeignKey("person.Id", ondelete="CASCADE"), primary_key=True)

    activity: Mapped[Activity] = relationship(back_populates="assignees")
    person: Mapped[Person] = relationship()


class AuditEntry(Base):
    __tablename__ = "audit_entry"
    __table_args__ = (Index("ix_audit_time", "TimestampUtc"), Index("ix_audit_project", "ProjectId"))
    id: Mapped[int] = mapped_column("Id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    timestamp_utc: Mapped[datetime] = mapped_column("TimestampUtc", DateTime, nullable=False)
    who: Mapped[str] = mapped_column("Who", String(120), nullable=False)
    action: Mapped[str] = mapped_column("Action", String(40), nullable=False)
    entity_kind: Mapped[str] = mapped_column("EntityKind", String(40), nullable=False)
    entity_name: Mapped[str] = mapped_column("EntityName", String(200), nullable=False)
    project_code: Mapped[str | None] = mapped_column("ProjectCode", String(30))
    project_id: Mapped[int | None] = mapped_column("ProjectId", Integer)
    activity_id: Mapped[int | None] = mapped_column("ActivityId", Integer)
    detail: Mapped[str | None] = mapped_column("Detail", Text)
