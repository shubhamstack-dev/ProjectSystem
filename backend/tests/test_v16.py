"""v1.6: tickets go through the project manager, mail in and out, the
customer side of phases, and processes that belong to a project."""
import smtplib
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from tests.harness import client as c, Testing, make_account, H, ok
from app import models as M
from app.services import mail as MAIL

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def _staff(tok, email, name, role_id):
    uid, t = make_account(email, name)
    p = ok(c.post("/api/team/people", headers=H(tok),
                  json={"name": name, "email": email, "roleId": role_id}), 201)
    db = Testing(); db.get(M.AppUser, uid).person_id = p["id"]; db.commit(); db.close()
    return {"uid": uid, "tok": t, "pid": p["id"]}


def _guest(admin, cid, email, name):
    made = ok(c.post(f"/api/customers/{cid}/users/new", headers=H(admin),
                     json={"display_name": name, "email": email}), 201)
    tok = ok(c.post("/api/auth/login", json={"email": email,
                                             "password": made["temporary_password"]}))["token"]
    ok(c.post("/api/auth/password", headers=H(tok),
              json={"current": made["temporary_password"], "new": "a-new-password-1"}))
    db = Testing()
    u = db.execute(select(M.AppUser).where(M.AppUser.email == email)).scalar_one()
    out = {"uid": u.id, "tok": tok, "pid": u.person_id}
    db.close()
    return out


@pytest.fixture(scope="module")
def w():
    _, admin = make_account("v16.admin@aequm.in", "V16 Admin", "Member", 1)
    org = ok(c.post("/api/team/organisations", headers=H(admin), json={"name": "V16 Aequm"}), 201)
    role = lambda n: ok(c.post("/api/team/roles", headers=H(admin),
                               json={"name": n, "organisationId": org["id"]}), 201)["id"]
    r_pm, r_fico, r_basis = role("V16 Project Manager"), role("V16 SAP FICO"), role("V16 Basis")
    pm = _staff(admin, "v16.priya@aequm.in", "Priya PM", r_pm)
    tarun = _staff(admin, "v16.tarun@aequm.in", "Tarun FICO", r_fico)
    basil = _staff(admin, "v16.basil@aequm.in", "Basil Basis", r_basis)
    apollo = ok(c.post("/api/customers", headers=H(admin), json={"name": "V16 Apollo"}), 201)
    cipla = ok(c.post("/api/customers", headers=H(admin), json={"name": "V16 Cipla"}), 201)
    p = ok(c.post("/api/projects", headers=H(admin), json={
        "code": "V16-A", "name": "Apollo billing", "plannedStart": "2026-01-05",
        "ownerId": pm["pid"]}), 201)
    orphan = ok(c.post("/api/projects", headers=H(admin), json={
        "code": "V16-N", "name": "No manager yet", "plannedStart": "2026-01-05"}), 201)
    ok(c.put(f"/api/customers/{apollo['id']}/projects", headers=H(admin),
             json={"project_ids": [p["id"], orphan["id"]]}))
    meena = _guest(admin, apollo["id"], "v16.meena@apollo.com", "Meena Apollo")
    ravi = _guest(admin, cipla["id"], "v16.ravi@cipla.com", "Ravi Cipla")
    return dict(admin=admin, pm=pm, tarun=tarun, basil=basil, p=p, orphan=orphan,
                r_fico=r_fico, r_basis=r_basis, meena=meena, ravi=ravi,
                apollo=apollo, cipla=cipla)


def _raise(w, title="Invoice save greyed out", project=None, **extra):
    return ok(c.post("/api/tickets", headers=H(w["meena"]["tok"]),
                     data={"project_id": (project or w["p"])["id"], "title": title,
                           "description": "Happens on every invoice since Monday.", **extra}), 201)


def _route(w, t, tok, role, who=None, code=200):
    return ok(c.post(f"/api/tickets/{t['id']}/route", headers=H(tok),
                     json={"team_role_id": role, "assignee_id": who, "note": "FICO config"}), code)


# ============================================================== triage
def test_a_new_ticket_waits_on_the_project_manager(w):
    t = _raise(w, assignee_id=w["tarun"]["pid"])
    assert t["stage"] == "pm" and t["pmName"] == "Priya PM"
    # allocation while raising is gone, even from an old client that sends it
    assert t["assigneeId"] is None and t["teamRoleId"] is None
    assert t["actions"] == []                     # the customer has nothing to do yet


def test_only_the_project_manager_routes(w):
    t = _raise(w)
    r = c.post(f"/api/tickets/{t['id']}/route", headers=H(w["tarun"]["tok"]),
               json={"team_role_id": w["r_fico"]})
    assert r.status_code == 403 and "project manager" in r.text
    assert c.post(f"/api/tickets/{t['id']}/route", headers=H(w["meena"]["tok"]),
                  json={"team_role_id": w["r_fico"]}).status_code == 403
    d = _route(w, t, w["pm"]["tok"], w["r_fico"], w["tarun"]["pid"])
    assert d["stage"] == "team" and d["teamName"] == "V16 SAP FICO"
    assert d["assigneeName"] == "Tarun FICO" and d["routedBy"] == "Priya PM"
    assert any("Sent to V16 SAP FICO" in r["body"] for r in d["responses"])


def test_a_ticket_goes_to_an_aequm_team_and_a_person_in_it(w):
    t = _raise(w)
    cust_role = ok(c.post("/api/team/roles", headers=H(w["admin"]),
                          json={"name": "V16 Approver", "isCustomer": True}), 201)["id"]
    r = c.post(f"/api/tickets/{t['id']}/route", headers=H(w["pm"]["tok"]),
               json={"team_role_id": cust_role})
    assert r.status_code == 409 and "customer role" in r.text
    r = c.post(f"/api/tickets/{t['id']}/route", headers=H(w["pm"]["tok"]),
               json={"team_role_id": w["r_fico"], "assignee_id": w["basil"]["pid"]})
    assert r.status_code == 409 and "not in the team" in r.text


def test_each_queue_shows_what_waits_on_its_owner(w):
    t1 = _raise(w, title="Queue: for the PM")
    t2 = _raise(w, title="Queue: for FICO")
    _route(w, t2, w["pm"]["tok"], w["r_fico"])
    pmq = {x["id"] for x in ok(c.get("/api/tickets?waiting_on_me=true", headers=H(w["pm"]["tok"])))}
    fq = {x["id"] for x in ok(c.get("/api/tickets?waiting_on_me=true", headers=H(w["tarun"]["tok"])))}
    assert t1["id"] in pmq and t2["id"] not in pmq
    assert t2["id"] in fq and t1["id"] not in fq


def test_the_team_resolves_and_nobody_else(w):
    t = _raise(w)
    _route(w, t, w["pm"]["tok"], w["r_fico"])
    r = c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["basil"]["tok"]),
               json={"resolution": "Not my team but trying anyway."})
    assert r.status_code == 403
    assert c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["meena"]["tok"]),
                  json={"resolution": "Customers cannot resolve."}).status_code == 403
    r = c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["tarun"]["tok"]),
               json={"resolution": "fixed"})
    assert r.status_code == 409 and "Describe the resolution" in r.text
    d = ok(c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["tarun"]["tok"]),
                  json={"resolution": "Posting period 09 was closed in OB52; reopened it."}))
    assert d["stage"] == "resolved" and d["resolvedBy"] == "Tarun FICO"


def test_status_cannot_be_forced_to_resolved(w):
    t = _raise(w)
    r = c.put(f"/api/tickets/{t['id']}", headers=H(w["admin"]),
              json={"title": t["title"], "priority": "High", "status": "Resolved"})
    assert r.status_code == 409 and "resolution" in r.text


def test_the_raiser_reopens_then_closes(w):
    t = _raise(w)
    _route(w, t, w["pm"]["tok"], w["r_fico"])
    ok(c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["tarun"]["tok"]),
              json={"resolution": "Cleared the browser cache on the terminal."}))
    seen = ok(c.get(f"/api/tickets/{t['id']}", headers=H(w["meena"]["tok"])))
    assert sorted(seen["actions"]) == ["close", "reopen"]
    back = ok(c.post(f"/api/tickets/{t['id']}/reopen", headers=H(w["meena"]["tok"]),
                     json={"reason": "Still greyed out this morning."}))
    assert back["stage"] == "team" and back["status"] == "InProgress" and back["resolution"] is None
    assert any("Earlier resolution: Cleared the browser cache" in r["body"] for r in back["responses"])
    ok(c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["tarun"]["tok"]),
              json={"resolution": "Role was missing F_BKPF_BUK for company code 1000."}))
    done = ok(c.post(f"/api/tickets/{t['id']}/close", headers=H(w["meena"]["tok"])))
    assert done["stage"] == "closed" and done["actions"] == []


def test_another_customer_cannot_touch_the_ticket(w):
    t = _raise(w)
    assert c.post(f"/api/tickets/{t['id']}/close", headers=H(w["ravi"]["tok"])).status_code == 404


def test_a_project_with_no_manager_does_not_strand_its_tickets(w):
    t = _raise(w, project=w["orphan"])
    assert t["pmId"] is None and t["stage"] == "pm"
    full = ok(c.get(f"/api/tickets/{t['id']}", headers=H(w["admin"])))
    assert "route" in full["actions"]              # an administrator can route it
    _route(w, t, w["admin"], w["r_basis"])


# ================================================================ mail
class FakeSMTP:
    sent, fail_next = [], 0

    def __init__(self, *a, **k): pass
    def ehlo(self): pass
    def starttls(self, context=None): pass
    def login(self, u, p): FakeSMTP.login_as = (u, p)
    def quit(self): pass

    def send_message(self, m):
        if FakeSMTP.fail_next:
            FakeSMTP.fail_next -= 1
            raise smtplib.SMTPRecipientsRefused({m["To"]: (550, b"no such user")})
        FakeSMTP.sent.append(m)


@pytest.fixture
def mailon(w, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail_next = [], 0
    ok(c.put("/api/mail/settings", headers=H(w["admin"]), json={
        "smtp_host": "smtp.office365.com", "smtp_port": "587", "smtp_security": "starttls",
        "smtp_user": "tickets@aequm.in", "smtp_password": "app-password-123",
        "from_address": "tickets@aequm.in", "app_url": "https://ps.aequm.in"}))
    db = Testing(); db.query(M.EmailOutbox).delete(); db.commit(); db.close()
    yield
    db = Testing(); db.query(M.AppSetting).delete(); db.commit(); db.close()


def _outbox():
    db = Testing()
    rows = [(r.to_address, r.reason, r.subject, r.status) for r in
            db.execute(select(M.EmailOutbox).order_by(M.EmailOutbox.id)).scalars()]
    db.close()
    return rows


def test_the_mail_password_is_never_shown_and_never_stored_plain(w, mailon):
    s = ok(c.get("/api/mail/settings", headers=H(w["admin"])))
    assert s["settings"]["smtp_password"] is True and s["sending_ready"] is True
    db = Testing(); raw = db.get(M.AppSetting, "smtp_password").value; db.close()
    assert "app-password-123" not in raw
    # saving with the password left blank keeps the stored one
    ok(c.put("/api/mail/settings", headers=H(w["admin"]), json={"from_name": "Aequm", "smtp_password": ""}))
    db = Testing(); assert db.get(M.AppSetting, "smtp_password").value == raw; db.close()


def test_mail_settings_are_for_administrators(w):
    assert c.get("/api/mail/settings", headers=H(w["pm"]["tok"])).status_code == 403
    assert c.get("/api/mail/settings", headers=H(w["meena"]["tok"])).status_code == 403


def test_raising_tells_the_pm_and_acknowledges_the_raiser(w, mailon):
    _raise(w, title="Mail: new ticket")
    got = _outbox()
    assert ("v16.priya@aequm.in", "raised") in [(a, b) for a, b, _, _ in got]
    assert ("v16.meena@apollo.com", "raised") in [(a, b) for a, b, _, _ in got]
    assert all(s.startswith("[TCK-") for _, _, s, _ in got)


def test_routing_tells_the_team_but_not_the_pm_who_did_it(w, mailon):
    t = _raise(w, title="Mail: route")
    db = Testing(); db.query(M.EmailOutbox).delete(); db.commit(); db.close()
    _route(w, t, w["pm"]["tok"], w["r_fico"])
    to = [a for a, *_ in _outbox()]
    assert "v16.tarun@aequm.in" in to and "v16.priya@aequm.in" not in to


def test_the_worker_sends_and_retries(w, mailon):
    _raise(w, title="Mail: send")
    FakeSMTP.fail_next = 1
    db = Testing(); r = MAIL.send_due(db); db.close()
    assert r["sent"] >= 1 and r["failed"] == 1
    db = Testing()
    failed = db.execute(select(M.EmailOutbox).where(M.EmailOutbox.attempts == 1)).scalars().one()
    assert failed.status == "queued" and failed.next_try_utc > failed.created_at_utc
    assert "no such user" in failed.last_error
    db.close()
    assert FakeSMTP.login_as == ("tickets@aequm.in", "app-password-123")  # decrypted to send


def test_a_line_break_in_a_title_cannot_break_the_subject(w, mailon):
    _raise(w, title="Two\nlines")
    assert all("\n" not in s for _, _, s, _ in _outbox())
    db = Testing(); MAIL.send_due(db); db.close()
    assert FakeSMTP.sent and all("\n" not in m["Subject"] for m in FakeSMTP.sent)


def _email(frm, subject, body, msgid, attach=None, auto=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = frm, "tickets@aequm.in", subject, msgid
    if auto:
        m["Auto-Submitted"] = "auto-replied"
    m.set_content(body)
    if attach:
        m.add_attachment(attach[1], maintype="image", subtype="png", filename=attach[0])
    return m.as_bytes()


def test_an_email_reply_lands_on_the_ticket_once(w):
    t = _raise(w, title="Mail: inbound")
    raw = _email("Meena Apollo <v16.meena@apollo.com>", f"Re: [{t['number']}] Received: x",
                 "Still happening, screenshot attached.\n\nOn Mon, Tickets wrote:\n> old stuff",
                 "<abc@apollo.com>", attach=("still.png", PNG))
    db = Testing()
    assert MAIL.handle_message(db, raw).outcome == "posted"
    assert MAIL.handle_message(db, raw).outcome == "posted"      # same row, not a second post
    db.close()
    full = ok(c.get(f"/api/tickets/{t['id']}", headers=H(w["admin"])))
    mine = [r for r in full["responses"] if r["body"].startswith("Still happening")]
    assert len(mine) == 1 and "old stuff" not in mine[0]["body"]
    assert mine[0]["attachments"][0]["kind"] == "image"


def test_mail_from_strangers_other_customers_and_robots_is_refused(w):
    t = _raise(w, title="Mail: refusals")
    db = Testing()
    assert MAIL.handle_message(db, _email("x@evil.com", f"[{t['number']}]", "hi", "<1@e>")).outcome == "refused"
    assert MAIL.handle_message(db, _email("v16.ravi@cipla.com", f"[{t['number']}]", "hi", "<2@c>")).outcome == "refused"
    assert MAIL.handle_message(db, _email("v16.meena@apollo.com", f"[{t['number']}]", "Out of office",
                                          "<3@a>", auto=True)).outcome == "ignored"
    assert MAIL.handle_message(db, _email("v16.meena@apollo.com", "no number", "hi", "<4@a>")).outcome == "ignored"
    db.close()


# ============================================== the customer side of phases
@pytest.fixture(scope="module")
def phase(w):
    return ok(c.post(f"/api/projects/{w['p']['id']}/phases", headers=H(w["admin"]),
                     json={"name": "Blueprint"}), 201)


def _croles(w):
    return ok(c.post("/api/team/roles", headers=H(w["admin"]),
                     json={"name": f"V16 Key user {id(w)%997}", "isCustomer": True}), 201)["id"]


def test_a_customer_role_is_filled_by_the_projects_customer(w, phase):
    r = _croles(w)
    a = ok(c.post(f"/api/phases/{phase['id']}/assignments", headers=H(w["admin"]),
                  json={"roleId": r, "personId": w["meena"]["pid"]}), 201)
    assert a["personId"] == w["meena"]["pid"]


def test_not_by_aequm_staff_nor_another_customer(w, phase):
    r = ok(c.post("/api/team/roles", headers=H(w["admin"]),
                  json={"name": "V16 Process owner", "isCustomer": True}), 201)["id"]
    x = c.post(f"/api/phases/{phase['id']}/assignments", headers=H(w["admin"]),
               json={"roleId": r, "personId": w["tarun"]["pid"]})
    assert x.status_code == 409 and "customer contacts" in x.text
    x = c.post(f"/api/phases/{phase['id']}/assignments", headers=H(w["admin"]),
               json={"roleId": r, "personId": w["ravi"]["pid"]})
    assert x.status_code == 409


def test_a_team_role_is_not_given_to_a_customer_contact(w, phase):
    x = c.post(f"/api/phases/{phase['id']}/assignments", headers=H(w["admin"]),
               json={"roleId": w["r_fico"], "personId": w["meena"]["pid"]})
    assert x.status_code == 409 and "Aequm people" in x.text


def test_a_project_without_a_customer_has_no_customer_side(w):
    lone = ok(c.post("/api/projects", headers=H(w["admin"]), json={
        "code": "V16-L", "name": "Internal", "plannedStart": "2026-01-05"}), 201)
    ph = ok(c.post(f"/api/projects/{lone['id']}/phases", headers=H(w["admin"]),
                   json={"name": "Build"}), 201)
    r = ok(c.post("/api/team/roles", headers=H(w["admin"]),
                  json={"name": "V16 Sponsor", "isCustomer": True}), 201)["id"]
    x = c.post(f"/api/phases/{ph['id']}/assignments", headers=H(w["admin"]),
               json={"roleId": r, "personId": w["meena"]["pid"]})
    assert x.status_code == 409 and "no customer yet" in x.text


# ====================================================== project processes
def test_a_process_needs_a_project(w):
    r = c.post("/api/processes", headers=H(w["admin"]), json={"name": "Orphan process"})
    assert r.status_code == 422 and "project" in r.text


def test_the_same_name_may_exist_in_two_projects(w):
    a = ok(c.post("/api/processes", headers=H(w["admin"]),
                  json={"project_id": w["p"]["id"], "name": "Month-end close", "steps": [{"name": "Freeze"}]}))
    b = ok(c.post("/api/processes", headers=H(w["admin"]),
                  json={"project_id": w["orphan"]["id"], "name": "Month-end close"}))
    assert a["projectCode"] if "projectCode" in a else a["project_code"] == "V16-A"
    assert b["project_id"] == w["orphan"]["id"]
    dup = c.post("/api/processes", headers=H(w["admin"]),
                 json={"project_id": w["p"]["id"], "name": "Month-end close"})
    assert dup.status_code == 409 and "V16-A already has" in dup.text


def test_a_ticket_cannot_use_another_projects_process(w):
    m = ok(c.post("/api/tickets/modules", headers=H(w["admin"]),
                  json={"name": "V16 Finance", "moduleType": "SAP"}), 201)
    other = ok(c.post("/api/processes", headers=H(w["admin"]),
                      json={"project_id": w["orphan"]["id"], "name": "Vendor payments",
                            "module_ids": [m["id"]]}))
    r = c.post("/api/tickets", headers=H(w["meena"]["tok"]),
               data={"project_id": w["p"]["id"], "title": "Wrong process",
                     "module_id": m["id"], "process_id": other["id"]})
    assert r.status_code == 409 and "another project" in r.text


def test_a_customer_sees_only_their_projects_processes(w):
    ok(c.post("/api/processes", headers=H(w["admin"]),
              json={"project_id": w["p"]["id"], "name": "Apollo only"}))
    lone = ok(c.post("/api/projects", headers=H(w["admin"]), json={
        "code": "V16-X", "name": "Someone else", "plannedStart": "2026-01-05"}), 201)
    ok(c.post("/api/processes", headers=H(w["admin"]), json={"project_id": lone["id"], "name": "Hidden"}))
    names = [p["name"] for p in ok(c.get("/api/processes", headers=H(w["meena"]["tok"])))]
    assert "Apollo only" in names and "Hidden" not in names


def test_an_old_process_is_given_a_project_once(w):
    db = Testing()
    old = M.Process(name="Pre-v1.6 process", active=1); db.add(old); db.commit(); pid = old.id; db.close()
    ok(c.put(f"/api/processes/{pid}", headers=H(w["admin"]), json={"project_id": w["p"]["id"]}))
    r = c.put(f"/api/processes/{pid}", headers=H(w["admin"]), json={"project_id": w["orphan"]["id"]})
    assert r.status_code == 409 and "cannot move" in r.text


def test_a_customer_is_waiting_on_to_confirm_a_resolution(w):
    t = _raise(w, title="Queue: confirm")
    _route(w, t, w["pm"]["tok"], w["r_fico"])
    ok(c.post(f"/api/tickets/{t['id']}/resolve", headers=H(w["tarun"]["tok"]),
              json={"resolution": "Printer mapping corrected for the invoice form."}))
    mine = {x["id"] for x in ok(c.get("/api/tickets?waiting_on_me=true", headers=H(w["meena"]["tok"])))}
    assert t["id"] in mine
