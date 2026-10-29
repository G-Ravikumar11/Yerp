"""Every error the server sends has a stable code and a reference that is also in the log."""
import re

from fastapi.testclient import TestClient

import main

REF = re.compile(r"^[0-9A-F]{8}$")


def test_a_missing_record_says_ye_data_01_with_a_ref(tenant):
    res = tenant.get("/api/drawings/987654")
    assert res.status_code == 404
    body = res.json()
    assert body["code"] == "YE-DATA-01" and REF.match(body["ref"]) and body["detail"]
    assert res.headers["X-Error-Code"] == "YE-DATA-01" and res.headers["X-Error-Ref"] == body["ref"]


def test_bad_input_keeps_its_field_list_and_says_ye_data_04(tenant):
    res = tenant.post("/api/workers", json={"name": "No job or trade"})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "YE-DATA-04" and isinstance(body["detail"], list) and REF.match(body["ref"])


def test_an_unexpected_fault_says_ye_srv_01_logs_the_ref_and_hides_the_internals(caplog):
    def boom():
        raise RuntimeError("secret internals: password=hunter2")
    main.app.add_api_route("/api/__test_boom", boom, methods=["GET"])
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        res = client.get("/api/__test_boom")
    finally:
        main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != "/api/__test_boom"]
    assert res.status_code == 500
    body = res.json()
    assert body["code"] == "YE-SRV-01" and REF.match(body["ref"])
    assert "hunter2" not in res.text and body["detail"] == "An unexpected error occurred."
    assert any(body["ref"] in r.getMessage() for r in caplog.records)


def test_a_wrong_password_says_ye_auth_01(client):
    res = client.post("/api/client/login", json={"email": "nobody@example.com", "password": "wrong-one"})
    assert res.status_code == 401 and res.json()["code"] == "YE-AUTH-01"


def test_each_situation_has_its_own_code():
    from app.core.errors import CODES, error_code
    cases = {
        (401, "Invalid credentials"): "YE-AUTH-01",
        (403, "Account disabled"): "YE-AUTH-02",
        (429, "Too many login attempts. Try again later."): "YE-AUTH-03",
        (401, "Not signed in"): "YE-AUTH-04",
        (401, "Your access has been removed"): "YE-AUTH-05",
        (401, "Password not set. Contact your administrator."): "YE-AUTH-06",
        (400, "That reset link is invalid or has expired"): "YE-AUTH-07",
        (400, "Email already registered"): "YE-AUTH-08",
        (428, "Please confirm you are a person: complete the check below and try again."): "YE-AUTH-09",
        (429, "This account is locked for 15 minutes after too many wrong passwords."): "YE-AUTH-10",
        (403, "Not allowed"): "YE-ACCESS-01",
        (403, "This link has expired. Open the file again from the app."): "YE-ACCESS-02",
        (404, "Drawing not found"): "YE-DATA-01",
        (409, "That record conflicts with one that already exists."): "YE-DATA-02",
        (409, "That photo is on a signed-off diary day."): "YE-DATA-03",
        (400, "The worker's name."): "YE-DATA-04",
        (413, "That is too large to send."): "YE-FILE-01",
        (400, "A photo, a PDF, a drawing (DWG/DXF) or an Excel or Word file."): "YE-FILE-02",
        (400, "The file is empty."): "YE-FILE-03",
        (429, "Slow down"): "YE-BUSY-01",
        (503, "Restarting"): "YE-BUSY-02",
        (504, "Gateway timeout"): "YE-BUSY-03",
        (500, "An unexpected error occurred."): "YE-SRV-01",
    }
    for (status, detail), code in cases.items():
        assert error_code(status, detail) == code, (status, detail)
    assert set(cases.values()) == set(CODES)          # every code is reachable, and none is left undescribed
