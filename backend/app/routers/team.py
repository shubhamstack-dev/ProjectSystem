"""Organisations, roles, people - full create / read / update / delete - and the
cross-project workload view."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Organisation, Person, Project, Role
from ..schemas import (OrganisationIn, OrganisationOut, PersonIn, PersonOut, RoleIn, RoleOut, WorkloadOut)
from ..scheduling.engine import round_away
from ..services import audit, mapper, plan
from ..services.rules import NotFound, RuleViolation
from .common import who

router = APIRouter(prefix="/api/team", tags=["team"])


def _get(db: Session, model, id_: int, label: str):
    row = db.get(model, id_)
    if row is None:
        raise NotFound(f"{label} {id_} not found.")
    return row


# ---- organisations ----------------------------------------------------------
def _org_out(db: Session, o: Organisation) -> OrganisationOut:
    people = db.execute(select(func.count(Person.id)).join(Role).where(Role.organisation_id == o.id)).scalar() or 0
    return OrganisationOut(id=o.id, name=o.name, description=o.description,
                           role_count=len(o.roles), people_count=people, project_count=len(o.projects))


@router.get("/organisations", response_model=list[OrganisationOut])
def organisations(db: Session = Depends(get_db)):
    rows = db.execute(select(Organisation).options(selectinload(Organisation.roles), selectinload(Organisation.projects))
                      .order_by(Organisation.name)).scalars().all()
    return [_org_out(db, o) for o in rows]


@router.post("/organisations", response_model=OrganisationOut, status_code=201)
def add_organisation(req: OrganisationIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    if db.execute(select(Organisation).where(Organisation.name == req.name.strip())).first():
        raise RuleViolation(f"An organisation called '{req.name}' already exists.")
    o = Organisation(name=req.name.strip(), description=req.description)
    db.add(o)
    db.flush()
    audit.record(db, actor, "Created", "Organisation", o.name)
    db.commit()
    return _org_out(db, o)


@router.put("/organisations/{org_id}", response_model=OrganisationOut)
def update_organisation(org_id: int, req: OrganisationIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    o = _get(db, Organisation, org_id, "Organisation")
    detail = "; ".join(c for c in [audit.change("name", o.name, req.name),
                                    audit.change("description", o.description, req.description)] if c)
    o.name, o.description = req.name.strip(), req.description
    if detail:
        audit.record(db, actor, "Edited", "Organisation", o.name, detail)
    db.commit()
    return _org_out(db, o)


@router.delete("/organisations/{org_id}", status_code=204)
def delete_organisation(org_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    o = _get(db, Organisation, org_id, "Organisation")
    audit.record(db, actor, "Deleted", "Organisation", o.name,
                 f"{len(o.roles)} role(s) and {len(o.projects)} project(s) detached")
    db.delete(o)  # roles/projects keep existing; their OrganisationId becomes NULL
    db.commit()


# ---- roles ------------------------------------------------------------------
def _role_out(r: Role) -> RoleOut:
    return RoleOut(id=r.id, customer_id=getattr(r, "customer_id", None), name=r.name, responsibilities=r.responsibilities, colour=r.colour,
                   organisation_id=r.organisation_id,
                   organisation_name=r.organisation.name if r.organisation else None,
                   views=[v for v in r.view_access.split(",") if v], people_count=len(r.people),
                   is_customer=bool(r.is_customer))


@router.get("/roles", response_model=list[RoleOut])
def roles(db: Session = Depends(get_db)):
    rows = db.execute(select(Role).options(selectinload(Role.organisation), selectinload(Role.people))
                      .order_by(Role.name)).scalars().all()
    return [_role_out(r) for r in rows]


@router.post("/roles", response_model=RoleOut, status_code=201)
def add_role(req: RoleIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    r = Role(name=req.name.strip(), responsibilities=req.responsibilities, colour=req.colour,
             view_access=",".join(req.views), organisation_id=req.organisation_id,
             is_customer=1 if req.is_customer else 0)
    db.add(r)
    db.flush()
    audit.record(db, actor, "Created", "Role", r.name, "views: " + r.view_access)
    db.commit()
    db.refresh(r)
    return _role_out(r)


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: int, req: RoleIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    r = _get(db, Role, role_id, "Role")
    views = ",".join(req.views)
    detail = "; ".join(c for c in [
        audit.change("name", r.name, req.name), audit.change("responsibilities", r.responsibilities, req.responsibilities),
        audit.change("colour", r.colour, req.colour), audit.change("views", r.view_access, views),
        audit.change("organisation", r.organisation_id, req.organisation_id)] if c)
    r.name, r.responsibilities, r.colour, r.view_access, r.organisation_id = \
        req.name.strip(), req.responsibilities, req.colour, views, req.organisation_id
    r.is_customer = 1 if req.is_customer else 0
    if detail:
        audit.record(db, actor, "Edited", "Role", r.name, detail)
    db.commit()
    db.refresh(r)
    return _role_out(r)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    r = _get(db, Role, role_id, "Role")
    audit.record(db, actor, "Deleted", "Role", r.name, f"{len(r.people)} person(s) left without a role")
    db.delete(r)
    db.commit()


# ---- people -----------------------------------------------------------------
@router.get("/people", response_model=list[PersonOut])
def people(db: Session = Depends(get_db)):
    rows = db.execute(select(Person).options(selectinload(Person.role)).order_by(Person.name)).scalars().all()
    return [mapper.person_out(p) for p in rows]


@router.post("/people", response_model=PersonOut, status_code=201)
def add_person(req: PersonIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = Person(name=req.name.strip(), email=req.email, role_id=req.role_id)
    db.add(p)
    db.flush()
    audit.record(db, actor, "Created", "Person", p.name)
    db.commit()
    db.refresh(p)
    return mapper.person_out(p)


@router.put("/people/{person_id}", response_model=PersonOut)
def update_person(person_id: int, req: PersonIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = _get(db, Person, person_id, "Person")
    detail = "; ".join(c for c in [audit.change("name", p.name, req.name), audit.change("email", p.email, req.email),
                                    audit.change("role", p.role_id, req.role_id)] if c)
    p.name, p.email, p.role_id = req.name.strip(), req.email, req.role_id
    if detail:
        audit.record(db, actor, "Edited", "Person", p.name, detail)
    db.commit()
    db.refresh(p)
    return mapper.person_out(p)


@router.delete("/people/{person_id}", status_code=204)
def delete_person(person_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = _get(db, Person, person_id, "Person")
    owned = db.execute(select(func.count(Project.id)).where(Project.owner_id == p.id)).scalar() or 0
    audit.record(db, actor, "Deleted", "Person", p.name,
                 f"removed from assignments and teams; {owned} project(s) left without an owner")
    db.delete(p)
    db.commit()


# ---- workload ---------------------------------------------------------------
@router.get("/workload", response_model=list[WorkloadOut])
def workload(db: Session = Depends(get_db)):
    """Workload for every person across every project. Shared activities split their days."""
    persons = db.execute(select(Person).options(selectinload(Person.role)).order_by(Person.name)).scalars().all()
    rows = {p.id: [] for p in persons}
    for pid in db.execute(select(Project.id)).scalars().all():
        project = plan.load(db, pid)
        if not project:
            continue
        acts, _ = plan.schedule(project)
        for a in acts:
            if a.is_summary:
                continue
            for x in a.assignees:
                if x.person_id in rows:
                    rows[x.person_id].append(a)
    today = date.today()
    out = []
    for p in persons:
        acts = rows[p.id]
        weight = sum(max(1, a.duration) for a in acts)
        out.append(WorkloadOut(
            person_id=p.id, name=p.name, role_name=p.role.name if p.role else None,
            projects=len({a.project_id for a in acts}), activities=len(acts),
            working_days=round(sum(mapper.share_of(a) for a in acts), 1),
            percent_complete=0 if weight == 0 else round_away(
                sum(float(a.percent_complete) * max(1, a.duration) for a in acts) / weight),
            late_count=sum(1 for a in acts if a.computed_finish_date < today and a.actual_finish is None and a.percent_complete < 100),
            shared_count=sum(1 for a in acts if len(a.assignees) > 1)))
    return out
