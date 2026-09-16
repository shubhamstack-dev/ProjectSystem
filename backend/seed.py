"""Loads sample data so the app is not empty on first run.

    python seed.py

Safe to run once; it stops if a project with code DEMO already exists."""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (Activity, ActivityAssignee, ActivityDependency, Holiday, Organisation, Person,  # noqa: E402
                        Project, ProjectTeamMember, Role)
from app.scheduling.engine import wbs_of  # noqa: E402
from app.services import audit  # noqa: E402

TYPES = {"FS": 0, "SS": 1, "FF": 2, "SF": 3}


def main() -> None:
    db = SessionLocal()
    if db.execute(select(Project).where(Project.code == "DEMO")).first():
        print("DEMO project already exists - nothing to do.")
        return

    org = Organisation(name="Engineering", description="Design and build")
    db.add(org)
    db.flush()
    pm = Role(name="Project manager", colour="#2F6F9E", organisation_id=org.id,
              view_access="portfolio,plan,assign,miles,audit,team")
    eng = Role(name="Engineer", colour="#3C8D5A", organisation_id=org.id, view_access="portfolio,plan,assign,miles")
    db.add_all([pm, eng])
    db.flush()
    people = [Person(name="Asha Verma", email="asha@example.com", role_id=pm.id),
              Person(name="Rahul Singh", email="rahul@example.com", role_id=eng.id),
              Person(name="Meera Iyer", email="meera@example.com", role_id=eng.id)]
    db.add_all(people)
    db.flush()

    g = json.loads((Path(__file__).parent / "tests" / "golden.json").read_text())
    project = Project(code="DEMO", name="Pilot fixture line", planned_start=date.fromisoformat(g["start"]),
                      planned_end=date(2026, 4, 3), organisation_id=org.id, owner_id=people[0].id,
                      notes="Sample plan from the golden fixture. Edit freely.")
    for h in g["holidays"]:
        project.holidays.append(Holiday(date=date.fromisoformat(h)))
    for p in people:
        project.team.append(ProjectTeamMember(person_id=p.id))
    db.add(project)
    db.flush()

    acts = []
    for i, r in enumerate(g["rows"]):
        manual = r["mode"] == "manual"
        a = Activity(project_id=project.id, sequence=i, level=r["level"], name=r["name"], duration=r["duration"],
                     mode=1 if manual else 0,
                     planned_start=date.fromisoformat(r["startDate"]) if manual else None,
                     planned_finish=date.fromisoformat(r["finishDate"]) if manual else None,
                     role_id=eng.id if r["level"] > 0 else pm.id)
        acts.append(a)
    db.add_all(acts)
    db.flush()
    wbs = {wbs_of(acts, i): a for i, a in enumerate(acts)}
    for i, r in enumerate(g["rows"]):
        for token in [t.strip() for t in r["pred"].split(",") if t.strip()]:
            m = re.match(r"^(\d+(?:\.\d+)*)\s*(FS|SS|FF|SF)?\s*([+-]\d+)?$", token.upper())
            db.add(ActivityDependency(activity_id=acts[i].id, predecessor_id=wbs[m.group(1)].id,
                                      type=TYPES[m.group(2) or "FS"], lag=int(m.group(3) or 0)))
    for i, a in enumerate(acts):
        if a.level == 2 or (a.level == 1 and i + 1 < len(acts) and acts[i + 1].level <= 1):
            db.add(ActivityAssignee(activity_id=a.id, person_id=people[1 + (i % 2)].id))
    audit.record(db, "seed", "Created", "Project", project.name, f"{len(acts)} rows from golden.json", project)
    db.commit()
    print(f"Seeded organisation, 2 roles, 3 people and project DEMO with {len(acts)} activities.")


if __name__ == "__main__":
    main()
