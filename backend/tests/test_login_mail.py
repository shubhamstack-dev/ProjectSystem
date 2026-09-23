"""Adding a person to a customer emails them the sign-in link, their user
name and password; the password is never left in the outbox."""
import smtplib

import pytest
from sqlalchemy import select

from tests.harness import client as c, Testing, make_account, H, ok
from app import models as M
from app.services import mail as MAIL


class FakeSMTP:
    sent, fail = [], False

    def __init__(self, *a, **k):
        if FakeSMTP.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad password")
    def ehlo(self): pass
    def starttls(self, context=None): pass
    def login(self, u, p): pass
    def quit(self): pass
    def send_message(self, m): FakeSMTP.sent.append(m)


@pytest.fixture(scope="module")
def adm():
    _, tok = make_account("lm.admin@aequm.in", "LM Admin", "Member", 1)
    cust = ok(c.post("/api/customers", headers=H(tok), json={"name": "LM Ankit Aerospace"}), 201)
    return tok, cust


def _mail(adm, app_url=""):
    ok(c.put("/api/mail/settings", headers=H(adm[0]), json={
        "smtp_host": "smtp.office365.com", "smtp_port": "587", "smtp_security": "starttls",
        "smtp_user": "alok.jayant@aequmindia.in", "smtp_password": "x",
        "from_address": "alok.jayant@aequmindia.in", "app_url": app_url}))


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    yield
    db = Testing(); db.query(M.AppSetting).delete(); db.commit(); db.close()


def _body(m):
    return m.get_body(preferencelist=("plain",)).get_content()


def test_adding_a_person_emails_link_user_and_password(adm, smtp):
    _mail(adm)
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "Alok", "email": "Alok.New@Ankit.com"}), 201)
    assert r["emailed"] is True and "emailed to alok.new@ankit.com" in r["message"]
    m = FakeSMTP.sent[-1]
    assert m["To"] == "alok.new@ankit.com"
    text = _body(m)
    assert "https://nexdaequmsupport.com/" in text          # default when app_url blank
    assert "User:       alok.new@ankit.com" in text
    assert r["temporary_password"] in text
    # and that password really signs in
    ok(c.post("/api/auth/login", json={"email": "alok.new@ankit.com",
                                        "password": r["temporary_password"]}))


def test_the_password_is_not_left_in_the_outbox(adm, smtp):
    _mail(adm)
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "B", "email": "b@ankit.com"}), 201)
    db = Testing()
    row = db.execute(select(M.EmailOutbox).where(M.EmailOutbox.to_address == "b@ankit.com")).scalar_one()
    assert row.status == "sent" and row.reason == "welcome"
    assert r["temporary_password"] not in row.body_text
    assert r["temporary_password"] not in (row.body_html or "")
    db.close()


def test_a_typed_password_is_the_one_emailed(adm, smtp):
    _mail(adm, "https://nexdaequmsupport.com/")
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "C", "email": "c@ankit.com", "password": "password"}), 201)
    assert r["temporary_password"] is None and r["emailed"]
    assert "Password:   password" in _body(FakeSMTP.sent[-1])


def test_mail_failure_keeps_the_account_and_says_why(adm, smtp):
    _mail(adm)
    FakeSMTP.fail = True
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "D", "email": "d@ankit.com"}), 201)
    assert r["emailed"] is False and "could not be sent" in r["email_note"]
    assert r["temporary_password"]          # still shown so it can be passed on


def test_no_mail_settings_means_no_mail_but_the_account_is_made(adm, smtp):
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "E", "email": "e@ankit.com"}), 201)
    assert r["emailed"] is False and "not set up" in r["email_note"] and not FakeSMTP.sent


def test_unticked_sends_nothing(adm, smtp):
    _mail(adm)
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "F", "email": "f@ankit.com", "send_email": False}), 201)
    assert r["emailed"] is False and not FakeSMTP.sent


def test_reset_password_emails_the_new_one(adm, smtp):
    _mail(adm)
    r = ok(c.post(f"/api/customers/{adm[1]['id']}/users/new", headers=H(adm[0]),
                  json={"display_name": "G", "email": "g@ankit.com", "send_email": False}), 201)
    x = ok(c.post(f"/api/auth/users/{r['user']['id']}/reset-password", headers=H(adm[0]),
                  json={"send_email": True}))
    assert x["emailed"] and x["temporary_password"] in _body(FakeSMTP.sent[-1])
    assert "reset" in FakeSMTP.sent[-1]["Subject"]
