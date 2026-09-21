"""v1.5: one API gate, files on disk with video, and customer users.

The files tests use real byte signatures rather than names, because the point
of the upload check is that a name and a Content-Type prove nothing.
"""
import os
import re
import tempfile
import time

import pytest
from sqlalchemy import select

from tests.harness import client as c, anon, Testing, make_account, H, ok
from app import config, models as M
from app.main import app
from app.services import files as FILES

config.ATTACHMENT_DIR = tempfile.mkdtemp(prefix="ps-att-")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 5000
MOV = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 3000
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 3000
PDF = b"%PDF-1.4\n" + b"x" * 300
DOCX = b"PK\x03\x04" + b"\x00" * 300
EXE = b"MZ\x90\x00" + b"\x00" * 300
HTML = b"<html><script>alert(1)</script></html>"


@pytest.fixture(scope="module")
def world():
    _, admin = make_account("v15.admin@aequm.in", "V15 Admin", "Member", 1)
    cust = ok(c.post("/api/customers", headers=H(admin), json={"name": "V15 Apollo"}), 201)
    other = ok(c.post("/api/customers", headers=H(admin), json={"name": "V15 Cipla"}), 201)
    p1 = ok(c.post("/api/projects", headers=H(admin), json={
        "code": "V15-A", "name": "Apollo portal", "plannedStart": "2026-01-05"}), 201)
    p2 = ok(c.post("/api/projects", headers=H(admin), json={
        "code": "V15-C", "name": "Cipla portal", "plannedStart": "2026-01-05"}), 201)
    ok(c.put(f"/api/customers/{cust['id']}/projects", headers=H(admin),
             json={"project_ids": [p1["id"]]}))
    ok(c.put(f"/api/customers/{other['id']}/projects", headers=H(admin),
             json={"project_ids": [p2["id"]]}))
    made = ok(c.post(f"/api/customers/{cust['id']}/users/new", headers=H(admin),
                     json={"display_name": "Apollo Ops", "email": "v15.ops@apollo.com"}), 201)
    tok = ok(c.post("/api/auth/login", json={"email": "v15.ops@apollo.com",
                                             "password": made["temporary_password"]}))["token"]
    ok(c.post("/api/auth/password", headers=H(tok),
              json={"current": made["temporary_password"], "new": "apollo-ops-2026"}))
    return {"admin": admin, "cust": cust, "other": other, "p1": p1, "p2": p2,
            "made": made, "guest": tok}


def _ticket(tok, project_id, files=(), title="Screen freezes on save"):
    return c.post("/api/tickets", headers=H(tok),
                  data={"project_id": project_id, "title": title},
                  files=[("files", (n, b, "application/octet-stream")) for n, b in files])


# ================================================================ the gate
def test_nothing_under_api_answers_without_a_sign_in():
    """v1.4 had 40 routes that did. This walks every one."""
    public = {("GET", "/api/health"), ("GET", "/api/auth/options"),
              ("POST", "/api/auth/login"), ("GET", "/api/auth/microsoft/start"),
              ("POST", "/api/auth/microsoft/callback"),
              ("GET", "/api/tickets/attachments/{attachment_id}")}
    open_ = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if (method.upper(), path) in public:
                continue
            r = anon.request(method.upper(), re.sub(r"\{[^}]+\}", "1", path), json={})
            if r.status_code != 401:
                open_.append((method.upper(), path, r.status_code))
    assert open_ == [], open_


def test_a_customer_account_is_kept_to_the_customer_routes(world):
    g = world["guest"]
    for m, u in [("GET", "/api/team/people"), ("GET", "/api/audit"),
                 ("POST", "/api/projects"), ("GET", "/api/team/workload"),
                 ("POST", "/api/tickets/modules"), ("GET", "/api/auth/users")]:
        assert c.request(m, u, headers=H(g), json={}).status_code == 403, (m, u)


def test_a_customer_cannot_delete_or_edit_a_ticket(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"]), 201)
    assert c.delete(f"/api/tickets/{t['id']}", headers=H(world["guest"])).status_code == 403
    assert c.put(f"/api/tickets/{t['id']}", headers=H(world["guest"]),
                 json={"title": "x", "priority": "Low", "status": "Closed"}).status_code == 403


def test_deactivating_an_account_cuts_it_off_at_once(world):
    uid, tok = make_account("v15.leaver@aequm.in", "Leaver")
    assert c.get("/api/projects", headers=H(tok)).status_code == 200
    db = Testing(); db.get(M.AppUser, uid).active = 0; db.commit(); db.close()
    # the token has not expired; the account has
    assert c.get("/api/projects", headers=H(tok)).status_code == 401


def test_the_audit_trail_records_the_token_not_the_header(world):
    ok(c.post("/api/tickets", headers={**H(world["admin"]), "X-Acting-As": "Somebody Else"},
              data={"project_id": world["p1"]["id"], "title": "Attribution check"}), 201)
    rows = ok(c.get("/api/audit", headers=H(world["admin"])))
    rows = rows if isinstance(rows, list) else rows.get("entries", rows.get("items", []))
    mine = [r for r in rows if "Attribution check" in str(r)]
    assert mine and all("Somebody Else" not in str(r) for r in mine)
    assert any("V15 Admin" in str(r) for r in mine)


# ============================================================ attachments
def test_images_documents_and_video_are_accepted(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"], files=[
        ("screen.png", PNG), ("photo.jpg", JPG), ("repro.mp4", MP4),
        ("iphone.mov", MOV), ("clip.webm", WEBM), ("log.pdf", PDF), ("notes.docx", DOCX)]), 201)
    kinds = {a["fileName"]: a["kind"] for a in t["attachments"]}
    assert kinds["screen.png"] == "image" and kinds["repro.mp4"] == "video"
    assert kinds["iphone.mov"] == "video" and kinds["clip.webm"] == "video"
    assert kinds["log.pdf"] == "document" and kinds["notes.docx"] == "document"


def test_files_are_stored_on_disk_not_in_the_database(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"], files=[("repro.mp4", MP4)]), 201)
    db = Testing()
    a = db.get(M.TicketAttachment, t["attachments"][0]["id"])
    assert a.data is None and a.storage_key and len(a.sha256) == 64
    assert os.path.getsize(FILES.path_for(a.storage_key)) == len(MP4)
    db.close()


def test_the_contents_decide_the_type_not_the_name(world):
    """An .exe renamed to .png, and a web page renamed to .txt, are refused."""
    for name, blob in [("holiday.png", EXE), ("readme.txt", HTML), ("invoice.pdf", HTML)]:
        r = _ticket(world["guest"], world["p1"]["id"], files=[(name, blob)])
        assert r.status_code == 409 and "not a type that can be attached" in r.text, name


def test_video_has_a_higher_limit_than_images(world, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_MB", 0)       # every image is too big
    r = _ticket(world["guest"], world["p1"]["id"], files=[("big.png", PNG)])
    assert r.status_code == 409 and "larger than" in r.text
    ok(_ticket(world["guest"], world["p1"]["id"], files=[("fine.mp4", MP4)]), 201)


def test_a_refused_file_takes_the_others_with_it(world):
    """All or nothing: a ticket never ends up with half of what was attached."""
    before = set(_all_stored())
    r = _ticket(world["guest"], world["p1"]["id"],
                files=[("ok.png", PNG), ("bad.png", EXE)], title="Half attached")
    assert r.status_code == 409
    assert set(_all_stored()) == before
    everything = ok(c.get("/api/tickets", headers=H(world["admin"])))
    assert not any(t["title"] == "Half attached" for t in everything)


def _all_stored():
    for root, _, fs in os.walk(config.ATTACHMENT_DIR):
        for f in fs:
            yield os.path.join(root, f)


def test_a_signed_link_works_without_a_sign_in(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"], files=[("s.png", PNG)]), 201)
    url = t["attachments"][0]["url"]
    r = anon.get(url)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("inline")


def test_a_tampered_or_expired_link_is_refused(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"], files=[("s.png", PNG)]), 201)
    a = t["attachments"][0]
    assert anon.get(a["url"][:-2] + "00").status_code == 404
    assert anon.get(f"/api/tickets/attachments/{a['id']}").status_code == 404
    old = int(time.time()) - 5
    assert anon.get(f"/api/tickets/attachments/{a['id']}?exp={old}&sig={FILES._sig(a['id'], old)}"
                    ).status_code == 404
    # a valid signature for one file does not open another
    exp, sig = re.search(r"exp=(\d+)&sig=(\w+)", a["url"]).groups()
    assert anon.get(f"/api/tickets/attachments/{a['id'] + 1}?exp={exp}&sig={sig}").status_code == 404


def test_another_customers_file_is_not_found_even_when_signed_in(world):
    t = ok(_ticket(world["admin"], world["p2"]["id"], files=[("cipla.png", PNG)]), 201)
    aid = t["attachments"][0]["id"]
    assert c.get(f"/api/tickets/attachments/{aid}", headers=H(world["guest"])).status_code == 404
    assert c.get(f"/api/tickets/attachments/{aid}", headers=H(world["admin"])).status_code == 200


def test_video_can_be_seeked(world):
    """Browsers fetch video in ranges to seek, and Safari will not play without."""
    t = ok(_ticket(world["guest"], world["p1"]["id"], files=[("seek.mp4", MP4)]), 201)
    r = anon.get(t["attachments"][0]["url"], headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == MP4[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(MP4)}"


def test_documents_download_rather_than_render(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"], files=[("n.docx", DOCX)]), 201)
    r = anon.get(t["attachments"][0]["url"])
    assert r.headers["content-disposition"].startswith("attachment")


def test_a_reply_can_carry_files_too(world):
    t = ok(_ticket(world["guest"], world["p1"]["id"]), 201)
    after = ok(c.post(f"/api/tickets/{t['id']}/responses", headers=H(world["admin"]),
                      data={"body": "Here is the fix in action."},
                      files=[("files", ("fixed.mp4", MP4, "video/mp4"))]), 201)
    assert after["responses"][0]["attachments"][0]["kind"] == "video"


def test_deleting_a_ticket_deletes_its_files(world):
    t = ok(_ticket(world["admin"], world["p1"]["id"], files=[("gone.png", PNG)]), 201)
    db = Testing(); key = db.get(M.TicketAttachment, t["attachments"][0]["id"]).storage_key; db.close()
    path = FILES.path_for(key)
    assert os.path.exists(path)
    ok(c.delete(f"/api/tickets/{t['id']}", headers=H(world["admin"])), 204)
    assert not os.path.exists(path)


def test_files_stored_before_this_version_still_open(world):
    t = ok(_ticket(world["admin"], world["p1"]["id"]), 201)
    db = Testing()
    db.add(M.TicketAttachment(ticket_id=t["id"], file_name="old.pdf",
           content_type="application/pdf", size_bytes=len(PDF), data=PDF, kind="document",
           uploaded_by="legacy", uploaded_at_utc=M.datetime.utcnow() if hasattr(M, "datetime") else __import__("datetime").datetime.utcnow()))
    db.commit(); db.close()
    full = ok(c.get(f"/api/tickets/{t['id']}", headers=H(world["admin"])))
    r = anon.get(full["attachments"][0]["url"])
    assert r.status_code == 200 and r.content == PDF


# ============================================================ customer users
def test_a_user_is_created_on_the_customer(world):
    m = world["made"]
    assert m["temporary_password"] and re.fullmatch(r"\w{4}-\w{4}-\w{4}", m["temporary_password"])
    names = [u["display_name"] for u in m["customer"]["users"]]
    assert "Apollo Ops" in names


def test_the_new_user_must_choose_their_own_password(world):
    made = ok(c.post(f"/api/customers/{world['cust']['id']}/users/new", headers=H(world["admin"]),
                     json={"display_name": "Apollo Buyer", "email": "v15.buyer@apollo.com"}), 201)
    temp = made["temporary_password"]
    tok = ok(c.post("/api/auth/login", json={"email": "v15.buyer@apollo.com",
                                             "password": temp}))["token"]
    me = ok(c.get("/api/auth/me", headers=H(tok)))
    assert me["must_change_password"] is True and me["is_customer"] is True

    # until they do, the account can do nothing else — not even raise a ticket
    blocked = _ticket(tok, world["p1"]["id"])
    assert blocked.status_code == 403 and "Choose your own password" in blocked.text

    r = c.post("/api/auth/password", headers=H(tok), json={"current": temp, "new": temp})
    assert r.status_code == 422 and "different" in r.text
    done = ok(c.post("/api/auth/password", headers=H(tok),
                     json={"current": temp, "new": "apollo-buyer-2026"}))
    assert done["user"]["must_change_password"] is False
    ok(_ticket(tok, world["p1"]["id"]), 201)


def test_the_temporary_password_is_not_stored_in_clear(world):
    made = ok(c.post(f"/api/customers/{world['cust']['id']}/users/new", headers=H(world["admin"]),
                     json={"display_name": "Apollo Audit", "email": "v15.audit@apollo.com"}), 201)
    db = Testing()
    u = db.execute(select(M.AppUser).where(M.AppUser.email == "v15.audit@apollo.com")).scalar_one()
    assert made["temporary_password"] not in (u.password_hash or "")
    assert u.password_hash.startswith("pbkdf2$")
    db.close()


def test_the_customer_user_raises_follows_and_replies(world):
    g = world["guest"]
    t = ok(_ticket(g, world["p1"]["id"], files=[("freeze.mp4", MP4), ("screen.png", PNG)]), 201)
    ok(c.post(f"/api/tickets/{t['id']}/responses", headers=H(world["admin"]),
              data={"body": "Can you send the browser console?"}), 201)
    seen = ok(c.get(f"/api/tickets/{t['id']}", headers=H(g)))
    assert seen["responses"][0]["body"] == "Can you send the browser console?"
    back = ok(c.post(f"/api/tickets/{t['id']}/responses", headers=H(g),
                     data={"body": "Attached."},
                     files=[("files", ("console.txt", b"TypeError at line 40", "text/plain"))]), 201)
    assert back["responseCount"] == 2


def test_the_customer_user_cannot_reach_another_customer(world):
    r = _ticket(world["guest"], world["p2"]["id"])
    assert r.status_code == 409 and "does not belong to your organisation" in r.text
    assert c.get(f"/api/projects/{world['p2']['id']}/phases",
                 headers=H(world["guest"])).status_code == 404


def test_an_administrator_can_reset_the_password(world):
    uid = [u for u in ok(c.get("/api/customers", headers=H(world["admin"])))
           if u["name"] == "V15 Apollo"][0]["users"][0]["id"]
    r = ok(c.post(f"/api/auth/users/{uid}/reset-password", headers=H(world["admin"])))
    assert r["temporary_password"] and r["user"]["must_change_password"] is True


def test_a_duplicate_address_says_where_it_already_is(world):
    r = c.post(f"/api/customers/{world['other']['id']}/users/new", headers=H(world["admin"]),
               json={"display_name": "Same person", "email": "v15.ops@apollo.com"})
    assert r.status_code == 409 and "V15 Apollo" in r.text


def test_a_team_role_cannot_be_given_to_a_customer_user(world):
    org = ok(c.post("/api/team/organisations", headers=H(world["admin"]),
                    json={"name": "V15 Delivery"}), 201)
    team = ok(c.post("/api/team/roles", headers=H(world["admin"]),
                     json={"name": "V15 Engineer", "organisationId": org["id"]}), 201)
    r = c.post(f"/api/customers/{world['cust']['id']}/users/new", headers=H(world["admin"]),
               json={"display_name": "X", "email": "v15.x@apollo.com", "role_id": team["id"]})
    assert r.status_code == 422 and "customer roles" in r.text


def test_an_inactive_customer_takes_no_new_users(world):
    z = ok(c.post("/api/customers", headers=H(world["admin"]), json={"name": "V15 Dormant"}), 201)
    ok(c.put(f"/api/customers/{z['id']}", headers=H(world["admin"]), json={"active": False}))
    r = c.post(f"/api/customers/{z['id']}/users/new", headers=H(world["admin"]),
               json={"display_name": "Y", "email": "v15.y@dormant.com"})
    assert r.status_code == 409 and "inactive" in r.text
