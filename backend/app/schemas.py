"""Request and response shapes. JSON uses camelCase (same names the C# API used)
so the front end talks the same language whichever backend runs."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---- team -------------------------------------------------------------------
class OrganisationIn(Camel):
    name: str
    description: Optional[str] = None


class OrganisationOut(Camel):
    id: int
    name: str
    description: Optional[str]
    role_count: int
    people_count: int
    project_count: int


class RoleIn(Camel):
    name: str
    responsibilities: Optional[str] = None
    colour: str = "#2F6F9E"
    views: list[str] = Field(default_factory=lambda: ["portfolio", "plan", "assign", "miles"])
    organisation_id: Optional[int] = None


class RoleOut(Camel):
    id: int
    name: str
    responsibilities: Optional[str]
    colour: str
    organisation_id: Optional[int]
    organisation_name: Optional[str]
    views: list[str]
    people_count: int


class PersonIn(Camel):
    name: str
    email: Optional[str] = None
    role_id: Optional[int] = None


class PersonOut(Camel):
    id: int
    name: str
    email: Optional[str]
    role_id: Optional[int]
    role_name: Optional[str]


class WorkloadOut(Camel):
    person_id: int
    name: str
    role_name: Optional[str]
    projects: int
    activities: int
    working_days: float
    percent_complete: int
    late_count: int
    shared_count: int


# ---- projects ---------------------------------------------------------------
class ProjectIn(Camel):
    code: str
    name: str
    planned_start: date
    planned_end: Optional[date] = None
    status: int = 0
    organisation_id: Optional[int] = None
    owner_id: Optional[int] = None
    team_ids: list[int] = Field(default_factory=list)
    holidays: list[date] = Field(default_factory=list)
    notes: Optional[str] = None


class ProjectSummary(Camel):
    id: int
    code: str
    name: str
    status: int
    planned_start: date
    planned_end: Optional[date]
    forecast_finish: Optional[date]
    end_variance_days: Optional[int]
    actual_start: Optional[date]
    actual_finish: Optional[date]
    owner_name: Optional[str]
    owner_id: Optional[int]
    organisation_name: Optional[str]
    organisation_id: Optional[int]
    team_size: int
    team_ids: list[int]
    holidays: list[date]
    notes: Optional[str]
    milestone_count: int
    activity_count: int
    percent_complete: int
    late_count: int
    critical_count: int
    working_days: int


# ---- activities -------------------------------------------------------------
class DependencyIn(Camel):
    predecessor_id: int
    type: int = 0
    lag: int = 0


class DependencyOut(Camel):
    id: int
    predecessor_id: int
    predecessor_wbs: str
    predecessor_name: str
    type: int
    lag: int


class ActivityCreate(Camel):
    project_id: int
    level: int = 1
    name: str = ""
    duration: int = 1
    after_activity_id: Optional[int] = None
    planned_start: Optional[date] = None
    planned_finish: Optional[date] = None
    target_date: Optional[date] = None
    notes: Optional[str] = None
    role_id: Optional[int] = None
    assignee_ids: Optional[list[int]] = None
    dependencies: Optional[list[DependencyIn]] = None


class ActivityUpdate(Camel):
    """Every field optional: only what is sent is changed. Actuals use `clear_actual_*`
    to explicitly blank a date, since 'not sent' must mean 'leave alone'."""
    name: Optional[str] = None
    mode: Optional[int] = None
    duration: Optional[int] = None
    planned_start: Optional[date] = None
    planned_finish: Optional[date] = None
    target_date: Optional[date] = None
    actual_start: Optional[date] = None
    actual_finish: Optional[date] = None
    clear_actual_start: bool = False
    clear_actual_finish: bool = False
    percent_complete: Optional[int] = None
    notes: Optional[str] = None
    role_id: Optional[int] = None
    clear_role: bool = False
    assignee_ids: Optional[list[int]] = None
    dependencies: Optional[list[DependencyIn]] = None


class ActivityOut(Camel):
    id: int
    project_id: int
    sequence: int
    level: int
    wbs: str
    kind: str
    name: str
    notes: Optional[str]
    mode: int
    duration: int
    planned_start: date
    planned_finish: date
    target_date: Optional[date]
    target_variance_days: Optional[int]
    actual_start: Optional[date]
    actual_finish: Optional[date]
    finish_variance_days: Optional[int]
    percent_complete: int
    total_float: int
    is_critical: bool
    is_summary: bool
    is_locked: bool
    is_independent: bool
    predecessor_count: int
    successor_count: int
    role_id: Optional[int]
    role_name: Optional[str]
    assignees: list[PersonOut]
    dependencies: list[DependencyOut]
    baseline_start: Optional[int]
    baseline_finish: Optional[int]
    status: str


class ProjectDetail(Camel):
    project: ProjectSummary
    activities: list[ActivityOut]
    holidays: list[date]
    schedule_warning: Optional[str]


class EligibleOut(Camel):
    id: int
    wbs: str
    name: str
    kind: str


class MoveIn(Camel):
    """Reorder / re-parent: direction is 'up', 'down', 'indent' or 'outdent'."""
    direction: str


# ---- audit ------------------------------------------------------------------
class AuditOut(Camel):
    id: int
    timestamp_utc: datetime
    who: str
    action: str
    entity_kind: str
    entity_name: str
    project_code: Optional[str]
    project_id: Optional[int]
    detail: Optional[str]
