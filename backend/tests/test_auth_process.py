"""v1.3: sign-in, Microsoft Entra ID, and processes beneath a module.

Graph and the Microsoft token endpoint are stubbed. The point of these tests is
the behaviour on this side of the wire — what gets created, what is matched to
what, and what is refused — not whether Microsoft answers.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import config, models as M  # noqa: E402
from app.main import app  # noqa: E402
from tests.harness import client, anon, Testing, make_account, H as _H, ok as _ok  # noqa: E402
from app.services import auth as A, entra as E  # noqa: E402

c = client


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content else None


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture(scope="module")
def admin_token():
    db = Testing()
    u = M.AppUser(email="admin@aequm.in", display_name="Administrator",
                  source="local", user_type="Member",
                  password_hash=A.hash_password("correct horse battery"),
                  is_admin=1, active=1, created_at_utc=_now())
    db.add(u)
    db.commit()
    db.close()
    r = ok(c.post("/api/auth/login", json={"email": "admin@aequm.in",
                                           "password": "correct horse battery"}))
    return r["token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# =========================================================== sign-in

def test_the_api_is_shut_without_a_token():
    """Before this version anybody could call anything. That has to be closed."""
    assert anon.get("/api/processes").status_code == 401
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/tickets").status_code == 401
    assert anon.get("/api/customers").status_code == 401


def test_sign_in_options_are_honest_about_microsoft():
    o = ok(c.get("/api/auth/options"))
    assert o["local"] is True
    # No tenant is configured in the tests, so the button must not be offered
    assert o["microsoft"] is False
    assert "not configured" in o["microsoft_reason"] or "No Entra" in o["microsoft_reason"]


def test_local_sign_in(admin_token):
    me = ok(c.get("/api/auth/me", headers=H(admin_token)))
    assert me["email"] == "admin@aequm.in" and me["is_admin"] is True
    assert me["source"] == "local" and me["is_customer"] is False


def test_a_wrong_password_says_the_same_as_an_unknown_address():
    a = c.post("/api/auth/login", json={"email": "admin@aequm.in", "password": "nope"})
    b = c.post("/api/auth/login", json={"email": "ghost@aequm.in", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_a_tampered_token_is_refused(admin_token):
    body, sig = admin_token.split(".")
    assert c.get("/api/auth/me", headers=H(f"{body}.{sig[:-2]}xx")).status_code == 401
    # and a payload edited to claim admin, signed with nothing
    import base64, json
    bad = base64.urlsafe_b64encode(json.dumps(
        {"uid": 1, "adm": 1, "exp": 9999999999}).encode()).decode().rstrip("=")
    assert c.get("/api/auth/me", headers=H(f"{bad}.{sig}")).status_code == 401


def test_an_expired_token_is_refused():
    import time
    db = Testing()
    u = db.execute(select(M.AppUser).where(M.AppUser.email == "admin@aequm.in")).scalar_one()
    db.close()
    old = config.TOKEN_HOURS
    try:
        config.TOKEN_HOURS = -1          # issued already expired
        tok = A.issue_token(u)
    finally:
        config.TOKEN_HOURS = old
    assert c.get("/api/auth/me", headers=H(tok)).status_code == 401


def test_password_change_is_refused_for_a_directory_account(admin_token):
    db = Testing()
    u = M.AppUser(email="entra.person@aequm.in", display_name="Entra Person",
                  source="entra", entra_oid="oid-pw", user_type="Member",
                  active=1, created_at_utc=_now())
    db.add(u); db.commit()
    tok = A.issue_token(u)
    db.close()
    r = c.post("/api/auth/password", headers=H(tok),
               json={"current": "x", "new": "something long"})
    assert r.status_code == 409 and "managed there" in r.text


# ======================================================= Microsoft sign-in

def test_microsoft_start_is_refused_when_no_tenant_is_configured():
    r = c.get("/api/auth/microsoft/start")
    assert r.status_code == 409 and "ENTRA_TENANT_ID" in r.text


def _configure(monkeypatch):
    monkeypatch.setattr(config, "ENTRA_TENANT_ID", "tenant-123")
    monkeypatch.setattr(config, "ENTRA_CLIENT_ID", "client-abc")
    monkeypatch.setattr(config, "ENTRA_CLIENT_SECRET", "shhh")


def test_microsoft_start_builds_a_pkce_url(monkeypatch):
    _configure(monkeypatch)
    r = ok(c.get("/api/auth/microsoft/start"))
    assert "login.microsoftonline.com/tenant-123" in r["url"]
    assert "code_challenge_method=S256" in r["url"]
    assert "client_id=client-abc" in r["url"]
    assert r["state"] in r["url"]


def test_a_callback_with_an_unknown_state_is_refused(monkeypatch):
    _configure(monkeypatch)
    r = c.post("/api/auth/microsoft/callback",
               json={"code": "abc", "state": "never-issued"})
    assert r.status_code == 400 and "no longer valid" in r.text


def test_the_state_cannot_be_replayed(monkeypatch):
    """A code is good once. Reusing the state must not open a second session."""
    _configure(monkeypatch)
    started = ok(c.get("/api/auth/microsoft/start"))
    monkeypatch.setattr(E, "exchange_code", lambda code, v, uri: {
        "oid": "oid-replay", "preferred_username": "replay@aequm.in",
        "name": "Replay Tester", "tid": "tenant-123"})
    ok(c.post("/api/auth/microsoft/callback",
              json={"code": "c1", "state": started["state"]}))
    again = c.post("/api/auth/microsoft/callback",
                   json={"code": "c1", "state": started["state"]})
    assert again.status_code == 400


def _sign_in_with_microsoft(monkeypatch, claims):
    _configure(monkeypatch)
    started = ok(c.get("/api/auth/microsoft/start"))
    monkeypatch.setattr(E, "exchange_code", lambda code, v, uri: claims)
    return c.post("/api/auth/microsoft/callback",
                  json={"code": "the-code", "state": started["state"]})


def test_a_member_signing_in_gets_an_account_and_a_person(monkeypatch):
    r = ok(_sign_in_with_microsoft(monkeypatch, {
        "oid": "oid-member-1", "preferred_username": "ravi@aequm.in",
        "name": "Ravi Shankar", "tid": "tenant-123"}))
    assert r["user"]["source"] == "entra"
    assert r["user"]["user_type"] == "Member" and r["user"]["is_customer"] is False
    # a Person row is made too, or they cannot be assigned a ticket
    assert r["user"]["person_id"]
    db = Testing()
    p = db.get(M.Person, r["user"]["person_id"])
    assert p.name == "Ravi Shankar" and p.email == "ravi@aequm.in"
    db.close()


def test_a_guest_cannot_let_themselves_in(monkeypatch):
    """A customer who can create their own account can reach another
    customer's tickets. Guests must be imported by an administrator first."""
    r = _sign_in_with_microsoft(monkeypatch, {
        "oid": "oid-guest-new", "preferred_username": "someone@customer.com",
        "name": "Uninvited", "tid": "tenant-123", "acct": 1})
    assert r.status_code == 403 and "import" in r.text.lower()


def test_the_same_person_signing_in_twice_is_one_account(monkeypatch):
    for _ in range(2):
        ok(_sign_in_with_microsoft(monkeypatch, {
            "oid": "oid-twice", "preferred_username": "twice@aequm.in",
            "name": "Twice Over", "tid": "tenant-123"}))
    db = Testing()
    n = len(db.execute(select(M.AppUser).where(
        M.AppUser.entra_oid == "oid-twice")).scalars().all())
    db.close()
    assert n == 1


def test_a_changed_surname_does_not_create_a_second_account(monkeypatch):
    """Matching on the object id, not the address, is the whole point."""
    ok(_sign_in_with_microsoft(monkeypatch, {
        "oid": "oid-married", "preferred_username": "priya.nair@aequm.in",
        "name": "Priya Nair", "tid": "tenant-123"}))
    ok(_sign_in_with_microsoft(monkeypatch, {
        "oid": "oid-married", "preferred_username": "priya.menon@aequm.in",
        "name": "Priya Menon", "tid": "tenant-123"}))
    db = Testing()
    rows = db.execute(select(M.AppUser).where(
        M.AppUser.entra_oid == "oid-married")).scalars().all()
    db.close()
    assert len(rows) == 1
    assert rows[0].email == "priya.menon@aequm.in"
    assert rows[0].display_name == "Priya Menon"


def test_a_second_microsoft_account_cannot_steal_an_address(monkeypatch):
    ok(_sign_in_with_microsoft(monkeypatch, {
        "oid": "oid-first", "preferred_username": "shared@aequm.in",
        "name": "First", "tid": "tenant-123"}))
    r = _sign_in_with_microsoft(monkeypatch, {
        "oid": "oid-second", "preferred_username": "shared@aequm.in",
        "name": "Second", "tid": "tenant-123"})
    assert r.status_code == 409 and "different Microsoft account" in r.text


# ==================================================== directory import

GRAPH_PAGE = [
    {"id": "g-1", "displayName": "Meera Krishnan", "mail": "meera@aequm.in",
     "userPrincipalName": "meera@aequm.in", "jobTitle": "Facility Manager",
     "department": "Admin", "accountEnabled": True, "userType": "Member"},
    {"id": "g-2", "displayName": "Sunil Rao", "mail": None,
     "userPrincipalName": "sunil@aequm.in", "jobTitle": "Projects Lead",
     "department": "Projects", "accountEnabled": True, "userType": "Member"},
    {"id": "g-3", "displayName": "Client Contact", "mail": "ops@customer.com",
     "userPrincipalName": "ops_customer.com#EXT#@aequm.onmicrosoft.com",
     "accountEnabled": True, "userType": "Guest"},
    {"id": "g-4", "displayName": "Left The Company", "mail": "gone@aequm.in",
     "userPrincipalName": "gone@aequm.in", "accountEnabled": False,
     "userType": "Member"},
]


def _stub_graph(monkeypatch, page=None):
    _configure(monkeypatch)
    rows = [E.normalise(u) for u in (page if page is not None else GRAPH_PAGE)]
    monkeypatch.setattr(E, "fetch_users", lambda limit=500, search=None: rows)


def test_fetching_users_does_not_import_them(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    r = ok(c.get("/api/auth/directory/users", headers=H(admin_token)))
    assert r["count"] == 4 and r["members"] == 3 and r["guests"] == 1
    db = Testing()
    assert db.execute(select(M.AppUser).where(
        M.AppUser.entra_oid == "g-1")).scalar_one_or_none() is None
    db.close()


def test_import_creates_accounts_and_people(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    r = ok(c.post("/api/auth/directory/import", headers=H(admin_token), json={}))
    assert r["created"] == 3          # the disabled account is not one of them
    assert r["skipped"] == 1
    assert any("disabled" in n for n in r["notes"])
    db = Testing()
    u = db.execute(select(M.AppUser).where(M.AppUser.entra_oid == "g-1")).scalar_one()
    assert u.person_id and u.source == "entra"
    # an account with no mail falls back to the userPrincipalName
    u2 = db.execute(select(M.AppUser).where(M.AppUser.entra_oid == "g-2")).scalar_one()
    assert u2.email == "sunil@aequm.in"
    db.close()


def test_members_and_guests_land_on_different_sides(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    ok(c.post("/api/auth/directory/import", headers=H(admin_token), json={}))
    db = Testing()
    member = db.execute(select(M.AppUser).where(M.AppUser.entra_oid == "g-1")).scalar_one()
    guest = db.execute(select(M.AppUser).where(M.AppUser.entra_oid == "g-3")).scalar_one()
    assert member.user_type == "Member" and guest.user_type == "Guest"
    mrole = db.get(M.Person, member.person_id).role
    grole = db.get(M.Person, guest.person_id).role
    assert mrole.is_customer == 0 and grole.is_customer == 1
    assert mrole.organisation.name == config.ENTRA_MEMBER_ORG
    assert grole.organisation.name == config.ENTRA_GUEST_ORG
    db.close()


def test_importing_twice_refreshes_rather_than_duplicates(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    ok(c.post("/api/auth/directory/import", headers=H(admin_token), json={}))
    second = ok(c.post("/api/auth/directory/import", headers=H(admin_token), json={}))
    assert second["created"] == 0 and second["updated"] == 3
    db = Testing()
    n = len(db.execute(select(M.AppUser).where(
        M.AppUser.entra_oid.in_(["g-1", "g-2", "g-3"]))).scalars().all())
    db.close()
    assert n == 3


def test_import_can_be_limited_to_chosen_people(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    r = ok(c.post("/api/auth/directory/import", headers=H(admin_token),
                  json={"oids": ["g-1"]}))
    assert r["fetched"] == 1


def test_after_import_a_guest_can_sign_in(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    ok(c.post("/api/auth/directory/import", headers=H(admin_token), json={}))
    r = ok(_sign_in_with_microsoft(monkeypatch, {
        "oid": "g-3", "preferred_username": "ops@customer.com",
        "name": "Client Contact", "tid": "tenant-123", "acct": 1}))
    assert r["user"]["is_customer"] is True


def test_only_an_administrator_may_import(monkeypatch):
    _stub_graph(monkeypatch)
    db = Testing()
    u = M.AppUser(email="plain@aequm.in", display_name="Plain", source="local",
                  user_type="Member", password_hash=A.hash_password("a long password"),
                  is_admin=0, active=1, created_at_utc=_now())
    db.add(u); db.commit()
    tok = A.issue_token(u)
    db.close()
    assert c.get("/api/auth/directory/users", headers=H(tok)).status_code == 403
    assert c.post("/api/auth/directory/import", headers=H(tok), json={}).status_code == 403


def test_the_import_is_recorded(monkeypatch, admin_token):
    _stub_graph(monkeypatch)
    ok(c.post("/api/auth/directory/import", headers=H(admin_token), json={}))
    hist = ok(c.get("/api/auth/directory/history", headers=H(admin_token)))
    assert hist and hist[0]["fetched"] == 4 and hist[0]["run_by"]


def test_graph_permission_failure_says_what_to_grant(monkeypatch, admin_token):
    _configure(monkeypatch)

    def boom(limit=500, search=None):
        raise E.EntraError("Microsoft refused the directory read. The app "
                           "registration needs User.Read.All as an application "
                           "permission, granted with admin consent.")
    monkeypatch.setattr(E, "fetch_users", boom)
    r = c.get("/api/auth/directory/users", headers=H(admin_token))
    assert r.status_code == 502 and "User.Read.All" in r.text


def test_the_last_administrator_cannot_demote_themselves(admin_token):
    """Otherwise the product can be locked with nobody able to open it."""
    from sqlalchemy import update
    me = ok(c.get("/api/auth/me", headers=H(admin_token)))
    db = Testing()
    others = [u.id for u in db.execute(select(M.AppUser).where(
        M.AppUser.is_admin == 1, M.AppUser.id != me["id"])).scalars()]
    db.execute(update(M.AppUser).where(M.AppUser.id.in_(others))
               .values(is_admin=0))          # make them genuinely the last one
    db.commit(); db.close()
    try:
        r = c.put(f"/api/auth/users/{me['id']}", headers=H(admin_token),
                  json={"is_admin": False})
        assert r.status_code == 409 and "only administrator" in r.text
    finally:
        db = Testing()
        db.execute(update(M.AppUser).where(M.AppUser.id.in_(others))
                   .values(is_admin=1))
        db.commit(); db.close()


# ================================================ processes and steps

_PP = {"id": None}


def _pp(tok):
    """The project these tests' processes belong to — the same one their
    tickets are raised on, since a ticket's process must be its project's."""
    if _PP["id"] is None:
        _PP["id"] = ok(c.post("/api/projects", headers=H(tok), json={
            "code": "PRJ-1", "name": "SAP rollout", "plannedStart": "2026-01-05",
            "calendarDays": False}), 201)["id"]
    return _PP["id"]


@pytest.fixture(scope="module")
def module_id(admin_token):
    m = ok(c.post("/api/tickets/modules", headers=H(admin_token),
                  json={"name": "Finance", "moduleType": "SAP"}), 201)
    return m["id"]


def test_a_process_is_created_with_its_steps(admin_token):
    p = ok(c.post("/api/processes", headers=H(admin_token), json={"project_id": _pp(admin_token), 
        "name": "Period-end close", "code": "FI-CLOSE",
        "description": "Monthly close",
        "steps": [{"name": "Freeze postings"}, {"name": "Run depreciation"},
                  {"name": "Reconcile GR/IR"}, {"name": "Publish results"}]}))
    assert p["step_count"] == 4
    assert [s["name"] for s in p["steps"]][0] == "Freeze postings"
    assert [s["sort_order"] for s in p["steps"]] == [1, 2, 3, 4]


def test_a_duplicate_process_name_is_refused(admin_token):
    r = c.post("/api/processes", headers=H(admin_token),
               json={"project_id": _pp(admin_token), "name": "Period-end close"})
    assert r.status_code == 409


def test_a_duplicate_step_name_inside_one_process_is_refused(admin_token):
    p = ok(c.get("/api/processes", headers=H(admin_token)))[0]
    r = c.post(f"/api/processes/{p['id']}/steps", headers=H(admin_token),
               json={"name": "Freeze postings"})
    assert r.status_code == 409


def test_steps_can_be_reordered_only_as_a_whole(admin_token):
    p = ok(c.get("/api/processes", headers=H(admin_token)))[0]
    ids = [s["id"] for s in p["steps"]]
    # a partial list would leave the numbering half done
    bad = c.put(f"/api/processes/{p['id']}/steps/order", headers=H(admin_token),
                json={"step_ids": ids[:2]})
    assert bad.status_code == 422
    good = ok(c.put(f"/api/processes/{p['id']}/steps/order", headers=H(admin_token),
                    json={"step_ids": list(reversed(ids))}))
    assert [s["id"] for s in good["steps"]] == list(reversed(ids))


def test_a_process_is_assigned_to_a_module(admin_token, module_id):
    p = ok(c.get("/api/processes", headers=H(admin_token)))[0]
    r = ok(c.put(f"/api/modules/{module_id}/processes", headers=H(admin_token),
                 json={"process_ids": [p["id"]]}))
    assert len(r["processes"]) == 1
    mine = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))
    assert [x["id"] for x in mine] == [p["id"]]


def test_one_process_can_serve_several_modules(admin_token, module_id):
    """Period-end close is run by more than one module. Copying it per module
    is how the copies start disagreeing."""
    other = ok(c.post("/api/tickets/modules", headers=H(admin_token),
                      json={"name": "Controlling", "moduleType": "SAP"}), 201)
    p = ok(c.get("/api/processes", headers=H(admin_token)))[0]
    ok(c.put(f"/api/modules/{module_id}/processes", headers=H(admin_token),
             json={"process_ids": [p["id"]]}))
    ok(c.put(f"/api/modules/{other['id']}/processes", headers=H(admin_token),
             json={"process_ids": [p["id"]]}))
    again = ok(c.get("/api/processes", headers=H(admin_token)))[0]
    assert sorted(again["module_ids"]) == sorted([module_id, other["id"]])


# ===================================== tickets against a process and step

@pytest.fixture(scope="module")
def project_id(admin_token):
    _TOKEN["v"] = admin_token
    return _pp(admin_token)


_TOKEN = {"v": None}


def _mk_ticket(project_id, **extra):
    data = {"project_id": project_id, "title": "Depreciation run failed"}
    data.update({k: v for k, v in extra.items() if v is not None})
    return c.post("/api/tickets", data=data, headers=H(_TOKEN["v"]))


def test_a_ticket_can_name_a_process_and_a_step(admin_token, module_id, project_id):
    proc = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    step = proc["steps"][0]
    t = ok(_mk_ticket(project_id, module_id=module_id, process_id=proc["id"],
                      process_step_id=step["id"]), 201)
    assert t["processId"] == proc["id"] and t["processName"] == proc["name"]
    assert t["processStepId"] == step["id"] and t["processStepName"] == step["name"]


def test_a_step_without_its_process_is_refused(admin_token, module_id, project_id):
    proc = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    r = _mk_ticket(project_id, module_id=module_id,
                   process_step_id=proc["steps"][0]["id"])
    assert r.status_code == 409 and "needs the process" in r.text


def test_a_process_the_module_does_not_run_is_refused(admin_token, module_id, project_id):
    other = ok(c.post("/api/processes", headers=H(admin_token),
                      json={"project_id": _pp(admin_token), "name": "Vendor onboarding",
                            "steps": [{"name": "Collect documents"}]}))
    r = _mk_ticket(project_id, module_id=module_id, process_id=other["id"])
    assert r.status_code == 409 and "not one of the processes assigned" in r.text


def test_a_step_from_another_process_is_refused(admin_token, module_id, project_id):
    mine = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    stranger = [p for p in ok(c.get("/api/processes", headers=H(admin_token)))
                if p["id"] != mine["id"] and p["steps"]][0]
    r = _mk_ticket(project_id, module_id=module_id, process_id=mine["id"],
                   process_step_id=stranger["steps"][0]["id"])
    assert r.status_code == 409 and "different process" in r.text


def test_a_process_without_a_module_is_refused(admin_token, project_id):
    proc = ok(c.get("/api/processes", headers=H(admin_token)))[0]
    r = _mk_ticket(project_id, process_id=proc["id"])
    assert r.status_code == 409 and "choose the module first" in r.text


def test_moving_the_ticket_to_another_module_clears_a_stranded_process(
        admin_token, module_id, project_id):
    proc = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    t = ok(_mk_ticket(project_id, module_id=module_id, process_id=proc["id"],
                      process_step_id=proc["steps"][0]["id"]), 201)
    lonely = ok(c.post("/api/tickets/modules", headers=H(admin_token),
                       json={"name": "Basis", "moduleType": "SAP"}), 201)
    after = ok(c.put(f"/api/tickets/{t['id']}", headers=H(admin_token),
                     json={"moduleId": lonely["id"], "title": t["title"],
                           "priority": t["priority"], "status": t["status"]}))
    assert after["moduleId"] == lonely["id"]
    assert after["processId"] is None and after["processStepId"] is None


def test_a_process_named_on_a_ticket_cannot_be_deleted(admin_token, module_id, project_id):
    proc = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    ok(_mk_ticket(project_id, module_id=module_id, process_id=proc["id"]), 201)
    r = c.delete(f"/api/processes/{proc['id']}", headers=H(admin_token))
    assert r.status_code == 409 and "inactive" in r.text


def test_a_process_in_use_is_kept_on_the_module(admin_token, module_id, project_id):
    """Un-assigning it would leave the ticket pointing at a step the module
    no longer runs."""
    proc = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    ok(_mk_ticket(project_id, module_id=module_id, process_id=proc["id"]), 201)
    r = ok(c.put(f"/api/modules/{module_id}/processes", headers=H(admin_token),
                 json={"process_ids": []}))
    assert proc["name"] in r["kept"]
    assert "because tickets" in r["message"]


def test_naming_a_process_the_new_module_does_not_run_is_still_refused(
        admin_token, module_id, project_id):
    """Moving the module alone clears the process. Naming one that does not
    belong there is a mistake, and is refused rather than quietly dropped."""
    proc = ok(c.get(f"/api/processes?module_id={module_id}", headers=H(admin_token)))[0]
    t = ok(_mk_ticket(project_id, module_id=module_id), 201)
    other = ok(c.post("/api/tickets/modules", headers=H(admin_token),
                      json={"name": "Security", "moduleType": "SAP"}), 201)
    r = c.put(f"/api/tickets/{t['id']}", headers=H(admin_token),
              json={"moduleId": other["id"], "processId": proc["id"],
                    "title": t["title"], "priority": t["priority"],
                    "status": t["status"]})
    assert r.status_code == 409 and "not one of the processes assigned" in r.text
