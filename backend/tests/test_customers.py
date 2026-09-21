"""The customer master: a code, a name, and three assignments.

What matters here is not the CRUD but the wall. A customer user must see their
own projects and tickets and nothing else, and a customer user nobody has filed
yet must see nothing at all rather than everything.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models as M  # noqa: E402
from app.main import app  # noqa: E402
from tests.harness import client, Testing, make_account, H as _H, ok as _ok  # noqa: E402
from app.services import auth as A  # noqa: E402

c = client


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content else None


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


_account = make_account


@pytest.fixture(scope="module")
def admin():
    return _account("cust.admin@aequm.in", "Administrator", "Member", 1)[1]


@pytest.fixture(scope="module")
def world(admin):
    """Two customers, a project each, and a guest for the first."""
    apollo = ok(c.post("/api/customers", headers=H(admin),
                       json={"name": "Apollo Pharmacy"}), 201)
    cipla = ok(c.post("/api/customers", headers=H(admin),
                      json={"name": "Cipla"}), 201)
    p1 = ok(c.post("/api/projects", headers=H(admin), json={
        "code": "APL-1", "name": "Apollo rollout", "plannedStart": "2026-01-05"}), 201)
    p2 = ok(c.post("/api/projects", headers=H(admin), json={
        "code": "CIP-1", "name": "Cipla rollout", "plannedStart": "2026-02-02"}), 201)
    ok(c.put(f"/api/customers/{apollo['id']}/projects", headers=H(admin),
             json={"project_ids": [p1["id"]]}))
    ok(c.put(f"/api/customers/{cipla['id']}/projects", headers=H(admin),
             json={"project_ids": [p2["id"]]}))
    guest_id, guest_tok = _account("ops@apollo.com", "Apollo Ops", "Guest")
    ok(c.put(f"/api/customers/{apollo['id']}/users", headers=H(admin),
             json={"user_ids": [guest_id]}))
    return {"apollo": apollo, "cipla": cipla, "p1": p1, "p2": p2,
            "guest_id": guest_id, "guest": guest_tok}


# ------------------------------------------------------- the master

def test_the_code_is_generated_not_typed(admin):
    peek = ok(c.get("/api/customers/next-code", headers=H(admin)))
    assert peek["provisional"] is True
    made = ok(c.post("/api/customers", headers=H(admin), json={"name": "Zydus"}), 201)
    assert made["code"] == peek["code"]
    assert made["code"].startswith("CUST-") and len(made["code"]) == 9


def test_codes_run_on_and_do_not_repeat_after_a_deletion(admin):
    a = ok(c.post("/api/customers", headers=H(admin), json={"name": "Alpha Ltd"}), 201)
    b = ok(c.post("/api/customers", headers=H(admin), json={"name": "Beta Ltd"}), 201)
    assert b["code"] > a["code"]
    ok(c.delete(f"/api/customers/{b['id']}", headers=H(admin)), 204)
    d = ok(c.post("/api/customers", headers=H(admin), json={"name": "Delta Ltd"}), 201)
    # counting rows would have handed back Beta's code and collided
    assert d["code"] != b["code"] and d["code"] > b["code"]


def test_a_customer_needs_only_a_name(admin):
    made = ok(c.post("/api/customers", headers=H(admin), json={"name": "Wockhardt"}), 201)
    assert made["name"] == "Wockhardt" and made["active"] is True
    assert made["project_count"] == 0 and made["user_count"] == 0


def test_the_same_customer_twice_is_refused(admin):
    ok(c.post("/api/customers", headers=H(admin), json={"name": "Lupin"}), 201)
    r = c.post("/api/customers", headers=H(admin), json={"name": "  lupin  "})
    assert r.status_code == 409 and "already exists" in r.text


def test_only_an_administrator_maintains_customers():
    _, plain = _account("cust.plain@aequm.in", "Plain")
    assert c.post("/api/customers", headers=H(plain),
                  json={"name": "Nope"}).status_code == 403


# --------------------------------------------------- assignments

def test_projects_are_assigned_to_a_customer(admin, world):
    got = ok(c.get("/api/customers", headers=H(admin)))
    apollo = [x for x in got if x["id"] == world["apollo"]["id"]][0]
    assert [p["code"] for p in apollo["projects"]] == ["APL-1"]


def test_moving_a_project_between_customers_says_so(admin, world):
    r = ok(c.put(f"/api/customers/{world['cipla']['id']}/projects", headers=H(admin),
                 json={"project_ids": [world["p2"]["id"], world["p1"]["id"]]}))
    assert any("APL-1" in m for m in r["moved"])
    assert "Apollo Pharmacy" in r["message"]
    # put it back for the tests that follow
    ok(c.put(f"/api/customers/{world['apollo']['id']}/projects", headers=H(admin),
             json={"project_ids": [world["p1"]["id"]]}))
    ok(c.put(f"/api/customers/{world['cipla']['id']}/projects", headers=H(admin),
             json={"project_ids": [world["p2"]["id"]]}))


def test_only_a_customer_role_can_be_given_to_a_customer(admin, world):
    org = ok(c.post("/api/team/organisations", headers=H(admin),
                    json={"name": "Delivery"}), 201)
    team_role = ok(c.post("/api/team/roles", headers=H(admin),
                          json={"name": "Engineer", "organisationId": org["id"]}), 201)
    r = c.put(f"/api/customers/{world['apollo']['id']}/roles", headers=H(admin),
              json={"role_ids": [team_role["id"]]})
    assert r.status_code == 409 and "team role" in r.text


def test_a_customer_role_can_be_given_to_a_customer(admin, world):
    role = ok(c.post("/api/team/roles", headers=H(admin),
                     json={"name": "Apollo approver", "isCustomer": True}), 201)
    got = ok(c.put(f"/api/customers/{world['apollo']['id']}/roles", headers=H(admin),
                   json={"role_ids": [role["id"]]}))
    assert [x["name"] for x in got["roles"]] == ["Apollo approver"]


def test_an_internal_account_cannot_be_filed_under_a_customer(admin, world):
    uid, _ = _account("cust.member@aequm.in", "A Member", "Member")
    r = c.put(f"/api/customers/{world['apollo']['id']}/users", headers=H(admin),
              json={"user_ids": [uid]})
    assert r.status_code == 409 and "not a customer one" in r.text


def test_a_customer_with_projects_cannot_be_deleted(admin, world):
    r = c.delete(f"/api/customers/{world['apollo']['id']}", headers=H(admin))
    assert r.status_code == 409 and "inactive instead" in r.text


def test_guests_with_no_customer_are_listed_for_attention(admin):
    uid, _ = _account("loose@customer.com", "Unfiled Guest", "Guest")
    rows = ok(c.get("/api/customers/unassigned", headers=H(admin)))
    assert any(r["id"] == uid for r in rows)


# ------------------------------------------------- what a customer sees

def test_a_customer_user_sees_only_their_own_customer(world):
    got = ok(c.get("/api/customers", headers=H(world["guest"])))
    assert [x["name"] for x in got] == ["Apollo Pharmacy"]


def test_me_says_which_customer_they_are_from(world):
    me = ok(c.get("/api/auth/me", headers=H(world["guest"])))
    assert me["is_customer"] is True
    assert me["customer"]["name"] == "Apollo Pharmacy"


def test_a_customer_user_can_raise_a_ticket_on_their_own_project(admin, world):
    t = ok(c.post("/api/tickets", headers=H(world["guest"]),
                  data={"project_id": world["p1"]["id"],
                        "title": "Invoice output is blank"}), 201)
    assert t["projectCode"] == "APL-1"
    assert t["createdBy"]                       # attributed to the account, not a header


def test_a_customer_user_cannot_raise_one_on_another_customer(world):
    r = c.post("/api/tickets", headers=H(world["guest"]),
               data={"project_id": world["p2"]["id"], "title": "Prying"})
    assert r.status_code == 409 and "does not belong to your organisation" in r.text


def test_a_customer_user_sees_only_their_own_tickets(admin, world):
    ok(c.post("/api/tickets", headers=H(admin),
              data={"project_id": world["p2"]["id"], "title": "Cipla internal"}), 201)
    mine = ok(c.get("/api/tickets", headers=H(world["guest"])))
    assert mine and all(t["projectCode"] == "APL-1" for t in mine)
    everything = ok(c.get("/api/tickets", headers=H(admin)))
    assert len(everything) > len(mine)


def test_another_customers_ticket_is_not_found_rather_than_forbidden(admin, world):
    t = ok(c.post("/api/tickets", headers=H(admin),
                  data={"project_id": world["p2"]["id"], "title": "Cipla only"}), 201)
    # 404 rather than 403: a 403 confirms the ticket exists, which is itself a leak
    assert c.get(f"/api/tickets/{t['id']}", headers=H(world["guest"])).status_code == 404
    assert c.post(f"/api/tickets/{t['id']}/responses", headers=H(world["guest"]),
                  data={"body": "hello"}).status_code == 404


def test_a_customer_user_sees_the_teams_replies(admin, world):
    t = ok(c.post("/api/tickets", headers=H(world["guest"]),
                  data={"project_id": world["p1"]["id"], "title": "Needs an answer"}), 201)
    ok(c.post(f"/api/tickets/{t['id']}/responses", headers=H(admin),
              data={"body": "Looking at it now."}), 201)
    seen = ok(c.get(f"/api/tickets/{t['id']}", headers=H(world["guest"])))
    assert [r["body"] for r in seen["responses"]] == ["Looking at it now."]
    assert seen["status"] == "InProgress"       # progress is visible to them


def test_a_customer_user_can_reply_back(admin, world):
    t = ok(c.post("/api/tickets", headers=H(world["guest"]),
                  data={"project_id": world["p1"]["id"], "title": "Two way"}), 201)
    after = ok(c.post(f"/api/tickets/{t['id']}/responses", headers=H(world["guest"]),
                      data={"body": "Still happening this morning."}), 201)
    assert after["responseCount"] == 1


def test_an_unfiled_customer_user_sees_nothing_rather_than_everything():
    """The safe way round. An account nobody has filed yet must not default to
    seeing every project in the system."""
    _, tok = _account("nobody@customer.com", "Unfiled", "Guest")
    assert ok(c.get("/api/tickets", headers=H(tok))) == []
    assert ok(c.get("/api/customers", headers=H(tok))) == []
    me = ok(c.get("/api/auth/me", headers=H(tok)))
    assert me["customer"] is None
    assert "No customer has been assigned" in me["notice"]


def test_a_customer_user_is_offered_only_their_own_projects(admin, world):
    """The ticket API refuses the others anyway, but a form that fails on save
    reads as a broken product rather than a boundary."""
    mine = ok(c.get("/api/projects", headers=H(world["guest"])))
    assert [p["code"] for p in mine] == ["APL-1"]
    theirs = ok(c.get("/api/projects", headers=H(admin)))
    assert len(theirs) > len(mine)


def test_another_customers_project_is_not_found(admin, world):
    assert c.get(f"/api/projects/{world['p2']['id']}",
                 headers=H(world["guest"])).status_code == 404


def test_an_unfiled_customer_user_is_offered_no_projects():
    _, tok = make_account("nobody2@customer.com", "Unfiled Two", "Guest")
    assert ok(c.get("/api/projects", headers=H(tok))) == []


def test_sign_in_already_names_the_customer(world):
    """The sidebar reads this straight away; it used to say only 'Customer'
    until the next call to /me."""
    r = ok(c.post("/api/auth/login", json={"email": "ops@apollo.com",
                                           "password": "a long password"}))
    assert r["user"]["customer"]["name"] == "Apollo Pharmacy"
