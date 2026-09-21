"""Drives every endpoint through FastAPI's test client on a throwaway SQLite
database. Proves the CRUD paths, the lock rules and the audit trail work
without needing MySQL. Run: pytest -q"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402
from tests.harness import client, Testing, make_account, H as _H, ok as _ok  # noqa: E402

c = client
c.headers.update({"X-Acting-As": "tester"})

# v1.3 shut the API: every call needs a signed-in account. One administrator is
# made here and its token put on the client, so the rest of this suite reads
# exactly as it did before.
def _sign_in():
    from datetime import datetime, timezone
    from app import models as _M
    from app.services.auth import hash_password as _hp, issue_token as _it
    db = Testing()
    u = _M.AppUser(email="api.tester@aequm.in", display_name="tester", source="local",
                   user_type="Member", password_hash=_hp("a long test password"),
                   is_admin=1, active=1,
                   created_at_utc=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(u); db.commit(); db.close()
    return _it(u)


c.headers.update({"Authorization": f"Bearer {_sign_in()}"})


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content else None


def test_everything():
    # ---- team: create / update / delete -------------------------------------------
    org = ok(c.post("/api/team/organisations", json={"name": "Engineering", "description": "Build things"}), 201)
    ok(c.put(f"/api/team/organisations/{org['id']}", json={"name": "Engineering", "description": "Builds things"}))
    role = ok(c.post("/api/team/roles", json={"name": "Engineer", "organisationId": org["id"], "views": ["portfolio", "plan"]}), 201)
    assert role["views"] == ["portfolio", "plan"]
    ok(c.put(f"/api/team/roles/{role['id']}", json={"name": "Senior engineer", "organisationId": org["id"]}))
    alice = ok(c.post("/api/team/people", json={"name": "Alice", "roleId": role["id"]}), 201)
    bob = ok(c.post("/api/team/people", json={"name": "Bob", "email": "b@x.io"}), 201)
    ok(c.put(f"/api/team/people/{bob['id']}", json={"name": "Bob", "roleId": role["id"]}))
    assert len(ok(c.get("/api/team/people"))) == 2
    assert ok(c.get("/api/team/organisations"))[0]["peopleCount"] == 2

    # ---- project: create / update ---------------------------------------------------
    proj = ok(c.post("/api/projects", json={
        "code": "P1", "name": "Pilot line", "plannedStart": "2026-01-05", "plannedEnd": "2026-04-10",
        "organisationId": org["id"], "ownerId": alice["id"], "teamIds": [alice["id"], bob["id"]],
        "holidays": ["2026-01-26", "2026-03-06"]}), 201)
    assert proj["teamSize"] == 2 and proj["forecastFinish"] is None
    ok(c.post("/api/projects", json={"code": "P1", "name": "dup", "plannedStart": "2026-01-05"}), 409)
    ok(c.put(f"/api/projects/{proj['id']}", json={
        "code": "P1", "name": "Pilot line (rev)", "plannedStart": "2026-01-05", "plannedEnd": "2026-04-10",
        "teamIds": [alice["id"]], "holidays": ["2026-01-26"], "status": 0}))
    assert ok(c.get(f"/api/projects/{proj['id']}"))["project"]["teamSize"] == 1

    # ---- activities: outline ---------------------------------------------------------
    pid = proj["id"]
    ok(c.post("/api/activities", json={"projectId": pid, "level": 1, "name": "orphan"}), 409)  # needs a milestone
    m1 = ok(c.post("/api/activities", json={"projectId": pid, "level": 0, "name": "Design frozen", "duration": 0, "targetDate": "2026-01-20"}), 201)
    t1 = ok(c.post("/api/activities", json={"projectId": pid, "level": 1, "name": "Draft layout", "duration": 4, "assigneeIds": [alice["id"]]}), 201)
    t2 = ok(c.post("/api/activities", json={"projectId": pid, "level": 1, "name": "Detail drawings", "duration": 6,
                                            "dependencies": [{"predecessorId": t1["id"], "type": 0, "lag": 0}],
                                            "assigneeIds": [alice["id"], bob["id"]]}), 201)
    s1 = ok(c.post("/api/activities", json={"projectId": pid, "level": 2, "name": "Check drawings", "duration": 2, "afterActivityId": t2["id"],
                                            "dependencies": [{"predecessorId": t1["id"], "type": 0, "lag": 0}]}), 201)
    d = ok(c.get(f"/api/projects/{pid}"))
    wbs = [a["wbs"] for a in d["activities"]]
    assert wbs == ["1", "1.1", "1.2", "1.2.1"], wbs
    acts = {a["id"]: a for a in d["activities"]}
    assert acts[m1["id"]]["isSummary"] and acts[t2["id"]]["isSummary"]
    assert acts[t1["id"]]["plannedStart"] == "2026-01-05" and acts[t1["id"]]["plannedFinish"] == "2026-01-08"
    assert acts[s1["id"]]["plannedStart"] == "2026-01-09"  # FS after t1
    assert acts[s1["id"]]["isCritical"] and acts[t1["id"]]["isCritical"]
    assert d["project"]["forecastFinish"] == "2026-01-12"

    # eligible predecessors for t1 excludes itself and its dependents (t2 subtree)
    el = ok(c.get(f"/api/activities/{t1['id']}/eligible-predecessors"))
    assert {e["id"] for e in el} == {m1["id"]}
    # a loop is refused
    ok(c.put(f"/api/activities/{t1['id']}", json={"dependencies": [{"predecessorId": s1["id"], "type": 0, "lag": 0}]}), 409)

    # ---- update: plan fields, SS lag, manual pin --------------------------------------
    ok(c.put(f"/api/activities/{s1['id']}", json={"duration": 3, "dependencies": [{"predecessorId": t1["id"], "type": 1, "lag": 1}]}))
    d = ok(c.get(f"/api/projects/{pid}"))
    acts = {a["id"]: a for a in d["activities"]}
    assert acts[s1["id"]]["plannedStart"] == "2026-01-06"  # SS+1 from t1
    ok(c.put(f"/api/activities/{t1['id']}", json={"plannedStart": "2026-01-12", "plannedFinish": "2026-01-14"}))
    acts = {a["id"]: a for a in ok(c.get(f"/api/projects/{pid}"))["activities"]}
    assert acts[t1["id"]]["mode"] == 1 and acts[t1["id"]]["duration"] == 3

    # ---- lock rule: first actual pins + locks the plan --------------------------------
    ok(c.put(f"/api/activities/{s1['id']}", json={"actualStart": "2026-01-06", "percentComplete": 40}))
    acts = {a["id"]: a for a in ok(c.get(f"/api/projects/{pid}"))["activities"]}
    assert acts[s1["id"]]["isLocked"] and acts[s1["id"]]["mode"] == 1 and acts[s1["id"]]["status"] in ("Active", "Late")
    assert acts[t2["id"]]["isLocked"] and acts[m1["id"]]["isLocked"]  # parents lock too
    r = c.put(f"/api/activities/{s1['id']}", json={"duration": 9})
    assert r.status_code == 409 and "Check drawings" in r.json()["blockers"]
    ok(c.put(f"/api/activities/{s1['id']}", json={"notes": "went fine", "percentComplete": 60}))  # notes/actuals still fine
    ok(c.delete(f"/api/activities/{t2['id']}"), 409)                    # subtree has work
    ok(c.delete(f"/api/projects/{pid}"), 409)                           # project has work
    ok(c.post(f"/api/activities/{s1['id']}/move", json={"direction": "outdent"}), 409)
    ok(c.put(f"/api/activities/{s1['id']}", json={"clearActualStart": True, "percentComplete": 0}))
    assert not {a["id"]: a for a in ok(c.get(f"/api/projects/{pid}"))["activities"]}[s1["id"]]["isLocked"]

    # ---- move: outdent / indent / up / down ------------------------------------------
    ok(c.post(f"/api/activities/{s1['id']}/move", json={"direction": "outdent"}), 204)
    assert [a["wbs"] for a in ok(c.get(f"/api/projects/{pid}"))["activities"]] == ["1", "1.1", "1.2", "1.3"]
    ok(c.post(f"/api/activities/{s1['id']}/move", json={"direction": "up"}), 204)
    names = [a["name"] for a in ok(c.get(f"/api/projects/{pid}"))["activities"]]
    assert names == ["Design frozen", "Draft layout", "Check drawings", "Detail drawings"]
    ok(c.post(f"/api/activities/{s1['id']}/move", json={"direction": "indent"}), 204)
    assert [a["wbs"] for a in ok(c.get(f"/api/projects/{pid}"))["activities"]] == ["1", "1.1", "1.1.1", "1.2"]

    # ---- delete: predecessor guard, then cascade ------------------------------------
    ok(c.delete(f"/api/activities/{t1['id']}"), 409)   # t2 still depends on t1's subtree? t1 drives t2 and s1
    ok(c.put(f"/api/activities/{t2['id']}", json={"dependencies": []}))
    ok(c.put(f"/api/activities/{s1['id']}", json={"dependencies": []}))
    ok(c.delete(f"/api/activities/{t1['id']}"), 204)   # takes s1 with it
    assert [a["wbs"] for a in ok(c.get(f"/api/projects/{pid}"))["activities"]] == ["1", "1.1"]

    # ---- baseline, workload, audit -------------------------------------------------
    ok(c.post(f"/api/projects/{pid}/baseline"), 204)
    assert ok(c.get(f"/api/projects/{pid}"))["activities"][1]["baselineStart"] == 0
    wl = {w["name"]: w for w in ok(c.get("/api/team/workload"))}
    assert wl["Alice"]["activities"] == 1 and wl["Alice"]["sharedCount"] == 1 and wl["Alice"]["workingDays"] == 1.5
    trail = ok(c.get("/api/audit", params={"projectId": pid}))
    actions = {t["action"] for t in trail}
    assert {"Created", "Edited", "PlanLocked", "EditRefused", "DeleteRefused", "MoveRefused", "Moved", "Deleted", "BaselineSet"} <= actions
    assert ok(c.get("/api/audit", params={"q": "pinned"}))[0]["action"] == "PlanLocked"

    # ---- team deletes -------------------------------------------------------------
    ok(c.delete(f"/api/team/people/{bob['id']}"), 204)
    ok(c.delete(f"/api/team/roles/{role['id']}"), 204)
    assert ok(c.get("/api/team/people"))[0]["roleName"] is None
    ok(c.delete(f"/api/team/organisations/{org['id']}"), 204)
    assert ok(c.get(f"/api/projects/{pid}"))["project"]["organisationName"] is None

    # ---- project delete once nothing has work ---------------------------------------
    ok(c.delete(f"/api/projects/{pid}"), 204)
    assert ok(c.get("/api/projects")) == []
    ok(c.get(f"/api/projects/{pid}"), 404)
