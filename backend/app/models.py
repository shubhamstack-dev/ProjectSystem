"""ORM mapping of schema.sql. Table and column names match the SQL exactly so
the same database works for this backend and the earlier C# one.

Computed values (computed_start, total_float, is_critical, wbs ...) are plain
Python attributes filled by the scheduling engine - never stored."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
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
    is_customer: Mapped[int] = mapped_column("IsCustomer", Integer, nullable=False, default=0)
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


class Phase(Base):
    """A named stage of one project (e.g. Design, Build, Commissioning).
    Roles and their responsibilities are assigned to team members per phase."""
    __tablename__ = "phase"
    __table_args__ = (Index("ix_phase_project", "ProjectId", "Sequence"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column("ProjectId", ForeignKey("project.Id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column("Sequence", Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    start_date: Mapped[date | None] = mapped_column("StartDate", Date)
    end_date: Mapped[date | None] = mapped_column("EndDate", Date)
    colour: Mapped[str] = mapped_column("Colour", String(9), nullable=False, default="#2F6F9E")

    project: Mapped[Project] = relationship()
    assignments: Mapped[list["PhaseAssignment"]] = relationship(
        back_populates="phase", cascade="all, delete-orphan")


class PhaseAssignment(Base):
    """One row of the project's roles & responsibilities table: this role
    (with its responsibilities) is carried by this person during this phase."""
    __tablename__ = "phase_assignment"
    __table_args__ = (UniqueConstraint("PhaseId", "RoleId", "PersonId", name="ux_phase_assign"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column("PhaseId", ForeignKey("phase.Id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column("RoleId", ForeignKey("role.Id", ondelete="CASCADE"), nullable=False)
    person_id: Mapped[int] = mapped_column("PersonId", ForeignKey("person.Id", ondelete="CASCADE"), nullable=False)
    notes: Mapped[str | None] = mapped_column("Notes", String(500))

    phase: Mapped[Phase] = relationship(back_populates="assignments")
    role: Mapped[Role] = relationship()
    person: Mapped[Person] = relationship()


class DateApproval(Base):
    """Customer sign-off of the actual dates on one activity (line item).
    Whenever an organisation employee enters or changes an actual date the row
    (re)enters Pending; a customer then approves or rejects it with a comment."""
    __tablename__ = "date_approval"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column("ActivityId", ForeignKey("activity.Id", ondelete="CASCADE"),
                                             nullable=False, unique=True)
    actual_start: Mapped[date | None] = mapped_column("ActualStart", Date)
    actual_finish: Mapped[date | None] = mapped_column("ActualFinish", Date)
    status: Mapped[str] = mapped_column("Status", String(10), nullable=False, default="Pending")
    comment: Mapped[str | None] = mapped_column("Comment", String(500))
    submitted_by: Mapped[str] = mapped_column("SubmittedBy", String(120), nullable=False, default="")
    submitted_at_utc: Mapped[datetime | None] = mapped_column("SubmittedAtUtc", DateTime)
    decided_by: Mapped[str | None] = mapped_column("DecidedBy", String(120))
    decided_at_utc: Mapped[datetime | None] = mapped_column("DecidedAtUtc", DateTime)

    activity: Mapped[Activity] = relationship()


# ---- v1.2: tickets --------------------------------------------------------
TICKET_PRIORITIES = ("High", "Medium", "Low")
TICKET_STATUSES = ("Open", "InProgress", "Resolved", "Closed")


class TicketModule(Base):
    """Configuration entry: a module/tool a ticket can be raised against.
    module_type says whether it lives within SAP or outside SAP."""
    __tablename__ = "ticket_module"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False, unique=True)
    module_type: Mapped[str] = mapped_column("ModuleType", String(10), nullable=False, default="SAP")  # SAP | NonSAP
    description: Mapped[str | None] = mapped_column("Description", String(600))
    active: Mapped[int] = mapped_column("Active", Integer, nullable=False, default=1)


class Ticket(Base):
    __tablename__ = "ticket"
    __table_args__ = (Index("ix_ticket_project", "ProjectId"),
                      Index("ix_ticket_assignee", "AssigneeId"))
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column("ProjectId", ForeignKey("project.Id", ondelete="CASCADE"), nullable=False)
    phase_id: Mapped[int | None] = mapped_column("PhaseId", ForeignKey("phase.Id", ondelete="SET NULL"))
    module_id: Mapped[int | None] = mapped_column("ModuleId", ForeignKey("ticket_module.Id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column("Title", String(200), nullable=False)
    description: Mapped[str | None] = mapped_column("Description", Text)
    priority: Mapped[str] = mapped_column("Priority", String(10), nullable=False, default="Medium")
    status: Mapped[str] = mapped_column("Status", String(12), nullable=False, default="Open")
    assignee_id: Mapped[int | None] = mapped_column("AssigneeId", ForeignKey("person.Id", ondelete="SET NULL"))
    created_by: Mapped[str] = mapped_column("CreatedBy", String(120), nullable=False, default="")
    created_at_utc: Mapped[datetime] = mapped_column("CreatedAtUtc", DateTime, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column("UpdatedAtUtc", DateTime, nullable=False)

    project: Mapped[Project] = relationship()
    phase: Mapped[Phase | None] = relationship()
    module: Mapped[TicketModule | None] = relationship()
    assignee: Mapped[Person | None] = relationship()
    responses: Mapped[list["TicketResponse"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketResponse.id")
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan")

    @property
    def number(self) -> str:
        return f"TCK-{self.id:05d}"


class TicketResponse(Base):
    """One reply on the ticket's thread. Replies land on the ticket the moment
    they are saved, so whoever the ticket is allocated to (and the creator)
    sees them straight away."""
    __tablename__ = "ticket_response"
    __table_args__ = (Index("ix_ticket_response", "TicketId"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column("TicketId", ForeignKey("ticket.Id", ondelete="CASCADE"), nullable=False)
    author: Mapped[str] = mapped_column("Author", String(120), nullable=False)
    body: Mapped[str] = mapped_column("Body", Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column("CreatedAtUtc", DateTime, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="responses")
    attachments: Mapped[list["TicketAttachment"]] = relationship(back_populates="response")


class TicketAttachment(Base):
    """A document attached either to the ticket itself (at creation) or to one
    of its responses. Content is stored in the database."""
    __tablename__ = "ticket_attachment"
    __table_args__ = (Index("ix_ticket_attachment", "TicketId"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column("TicketId", ForeignKey("ticket.Id", ondelete="CASCADE"), nullable=False)
    response_id: Mapped[int | None] = mapped_column("ResponseId", ForeignKey("ticket_response.Id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column("FileName", String(255), nullable=False)
    content_type: Mapped[str] = mapped_column("ContentType", String(120), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column("SizeBytes", Integer, nullable=False, default=0)
    data: Mapped[bytes] = mapped_column("Data", LargeBinary(length=(2 ** 24) - 1), nullable=False)  # MEDIUMBLOB
    uploaded_by: Mapped[str] = mapped_column("UploadedBy", String(120), nullable=False, default="")
    uploaded_at_utc: Mapped[datetime] = mapped_column("UploadedAtUtc", DateTime, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="attachments")
    response: Mapped[TicketResponse | None] = relationship(back_populates="attachments")
