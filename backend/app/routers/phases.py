"""Project phases, and the roles & responsibilities table assigned to team
members per phase. A phase (Design, Build, Commissioning ...) belongs to one
project; each assignment row says: during this phase, this role - with the
responsibilities defined on the role - is carried by this person."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Person, Phase, PhaseAssignment, Project, Role
from ..schemas import PhaseAssignmentIn, PhaseAssignmentOut, PhaseIn, PhaseOut
from ..services import audit
from ..services.rules import NotFound, RuleViolation
from ..services.auth import Caller, current_user
from .common import who

router = APIRouter(prefix="/api", tags=["phases"])


def _assign_out(a: PhaseAssignment) -> PhaseAssignmentOut:
    return PhaseAssignmentOut(
        id=a.id, role_id=a.role_id, role_name=a.role.name, role_colour=a.role.colour,
        responsibilities=a.role.responsibilities,
        person_id=a.person_id, person_name=a.person.name, notes=a.notes)


def _phase_out(p: Phase) -> PhaseOut:
    return PhaseOut(id=p.id, project_id=p.project_id, sequence=p.sequence, name=p.name,
                    start_date=p.start_date, end_date=p.end_date, colour=p.colour,
                    assignments=[_assign_out(a) for a in
                                 sorted(p.assignments, key=lambda x: (x.role.name, x.person.name))])


def customer_of_person(db: Session, person: Person) -> int | None:
    """Which customer a person is from: their account says so, or failing that
    a customer role that belongs to one customer."""
    from ..models import AppUser
    u = db.execute(select(AppUser).where(AppUser.person_id == person.id)).scalars().first()
    if u and u.customer_id:
        return u.customer_id
    if person.role and person.role.is_customer and person.role.customer_id:
        return person.role.customer_id
    return None


def _check_side(db: Session, phase: Phase, role: Role, person: Person) -> None:
    """A phase has two sides: Aequm's team and the customer's people.

    A customer role can be filled only by someone from this project's own
    customer — never by a colleague at Aequm, and never by another customer's
    contact, who would then be named on a plan they have no business seeing.
    A team role, likewise, is not given to a customer's person.
    """
    project = phase.project
    if role.is_customer:
        if not project.customer_id:
            raise RuleViolation(
                "This project has no customer yet. Assign it to a customer on the "
                "Customers screen before naming the customer's people on its phases.")
        if role.customer_id and role.customer_id != project.customer_id:
            raise RuleViolation(f"'{role.name}' belongs to another customer.")
        theirs = customer_of_person(db, person)
        if theirs != project.customer_id:
            raise RuleViolation(
                f"{person.name} is not one of this project's customer contacts, so cannot "
                f"hold the customer role '{role.name}'.")
    else:
        if customer_of_person(db, person) is not None:
            raise RuleViolation(
                f"{person.name} is a customer contact. Team roles are held by Aequm people.")


def _load_phase(db: Session, phase_id: int) -> Phase:
    p = db.get(Phase, phase_id)
    if p is None:
        raise NotFound(f"Phase {phase_id} not found.")
    return p


@router.get("/projects/{project_id}/phases", response_model=list[PhaseOut])
def phases(project_id: int, db: Session = Depends(get_db),
           caller: Caller = Depends(current_user)):
    if caller.is_customer:
        p = db.get(Project, project_id)
        if p is None or p.customer_id != caller.user.customer_id:
            raise NotFound(f"Project {project_id} not found.")
    if db.get(Project, project_id) is None:
        raise NotFound(f"Project {project_id} not found.")
    rows = db.execute(
        select(Phase).where(Phase.project_id == project_id)
        .options(selectinload(Phase.assignments).selectinload(PhaseAssignment.role),
                 selectinload(Phase.assignments).selectinload(PhaseAssignment.person))
        .order_by(Phase.sequence, Phase.id)).scalars().all()
    return [_phase_out(p) for p in rows]


@router.post("/projects/{project_id}/phases", response_model=PhaseOut, status_code=201)
def add_phase(project_id: int, req: PhaseIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    project = db.get(Project, project_id)
    if project is None:
        raise NotFound(f"Project {project_id} not found.")
    if req.start_date and req.end_date and req.start_date > req.end_date:
        raise RuleViolation("The phase ends before it starts.")
    last = db.execute(select(Phase.sequence).where(Phase.project_id == project_id)
                      .order_by(Phase.sequence.desc()).limit(1)).scalar()
    p = Phase(project_id=project_id, sequence=(last or 0) + 1, name=req.name.strip(),
              start_date=req.start_date, end_date=req.end_date, colour=req.colour)
    db.add(p)
    db.flush()
    audit.record(db, actor, "Created", "Phase", p.name, project=project)
    db.commit()
    db.refresh(p)
    return _phase_out(p)


@router.put("/phases/{phase_id}", response_model=PhaseOut)
def update_phase(phase_id: int, req: PhaseIn, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = _load_phase(db, phase_id)
    if req.start_date and req.end_date and req.start_date > req.end_date:
        raise RuleViolation("The phase ends before it starts.")
    detail = "; ".join(c for c in [
        audit.change("name", p.name, req.name), audit.change("start", p.start_date, req.start_date),
        audit.change("end", p.end_date, req.end_date), audit.change("colour", p.colour, req.colour)] if c)
    p.name, p.start_date, p.end_date, p.colour = req.name.strip(), req.start_date, req.end_date, req.colour
    if detail:
        audit.record(db, actor, "Edited", "Phase", p.name, detail, project=p.project)
    db.commit()
    db.refresh(p)
    return _phase_out(p)


@router.delete("/phases/{phase_id}", status_code=204)
def delete_phase(phase_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    p = _load_phase(db, phase_id)
    audit.record(db, actor, "Deleted", "Phase", p.name,
                 f"{len(p.assignments)} assignment(s) removed", project=p.project)
    db.delete(p)
    db.commit()


@router.post("/phases/{phase_id}/move", status_code=204)
def move_phase(phase_id: int, req: dict, db: Session = Depends(get_db), actor: str = Depends(who)):
    """Swap the phase with its neighbour: body {"direction": "up"|"down"}."""
    p = _load_phase(db, phase_id)
    rows = db.execute(select(Phase).where(Phase.project_id == p.project_id)
                      .order_by(Phase.sequence, Phase.id)).scalars().all()
    i = next(n for n, x in enumerate(rows) if x.id == p.id)
    j = i - 1 if req.get("direction") == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i].sequence, rows[j].sequence = rows[j].sequence, rows[i].sequence
        db.commit()


# ---- assignments: the roles & responsibilities rows -------------------------

@router.post("/phases/{phase_id}/assignments", response_model=PhaseAssignmentOut, status_code=201)
def add_assignment(phase_id: int, req: PhaseAssignmentIn,
                   db: Session = Depends(get_db), actor: str = Depends(who)):
    p = _load_phase(db, phase_id)
    role = db.get(Role, req.role_id)
    person = db.get(Person, req.person_id)
    if role is None:
        raise NotFound(f"Role {req.role_id} not found.")
    if person is None:
        raise NotFound(f"Person {req.person_id} not found.")
    _check_side(db, p, role, person)
    dup = db.execute(select(PhaseAssignment).where(
        PhaseAssignment.phase_id == phase_id, PhaseAssignment.role_id == req.role_id,
        PhaseAssignment.person_id == req.person_id)).first()
    if dup:
        raise RuleViolation(f"{person.name} already carries '{role.name}' in this phase.")
    a = PhaseAssignment(phase_id=phase_id, role_id=req.role_id,
                        person_id=req.person_id, notes=req.notes)
    db.add(a)
    db.flush()
    audit.record(db, actor, "Assigned", "Phase role", f"{role.name} → {person.name}",
                 f"phase '{p.name}'", project=p.project)
    db.commit()
    db.refresh(a)
    return _assign_out(a)


@router.delete("/phases/assignments/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: int, db: Session = Depends(get_db), actor: str = Depends(who)):
    a = db.get(PhaseAssignment, assignment_id)
    if a is None:
        raise NotFound(f"Assignment {assignment_id} not found.")
    audit.record(db, actor, "Unassigned", "Phase role", f"{a.role.name} → {a.person.name}",
                 f"phase '{a.phase.name}'", project=a.phase.project)
    db.delete(a)
    db.commit()
