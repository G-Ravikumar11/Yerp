"""Settings > Error log: errors are kept with their code, ref, page and person, for the Master to see."""


def test_errors_are_kept_for_the_master_with_code_ref_and_who(account, portal):
    tenant = account["client"]
    bad = tenant.post("/api/workers", json={"name": "No job or trade"})            # YE-DATA-04
    assert bad.status_code == 422
    missing = tenant.get("/api/drawings/987654")                                    # YE-DATA-01: not kept
    assert missing.status_code == 404
    wrong = portal.post("/api/client/login", json={"email": account["email"], "password": "not-it"})
    assert wrong.json()["code"] == "YE-AUTH-01"                                     # filed under this company
    crash = tenant.post("/api/errors/report", json={"ref": "abc12345", "path": "/projects/safety",
                                                     "message": "Cannot read properties of undefined", "stack": "at X"})
    assert crash.json()["kept"] is True

    log = tenant.get("/api/errors").json()
    by_code = {e["code"]: e for e in log["errors"]}
    assert by_code["YE-DATA-04"]["ref"] == bad.json()["ref"] and by_code["YE-DATA-04"]["path"] == "/api/workers"
    assert by_code["YE-AUTH-01"]["who"] == account["email"] and by_code["YE-AUTH-01"]["title"] == "Wrong email or password"
    assert by_code["YE-APP"]["ref"] == "ABC12345" and by_code["YE-APP"]["path"] == "/projects/safety"
    assert "YE-DATA-01" not in by_code                                               # everyday "not found" stays out
    assert log["summary"]["by_area"]["AUTH"] == 1 and log["summary"]["total"] == len(log["errors"])

    only_sign_in = tenant.get("/api/errors?area=AUTH").json()["errors"]
    assert [e["code"] for e in only_sign_in] == ["YE-AUTH-01"]
    assert tenant.get("/api/errors?q=%s" % bad.json()["ref"]).json()["errors"][0]["code"] == "YE-DATA-04"


def test_a_staff_sign_in_tried_as_owner_first_is_not_a_wrong_password(account, portal):
    portal.post("/api/client/login", json={"email": "someone-new@example.com", "password": "x"})
    assert not [e for e in account["client"].get("/api/errors").json()["errors"] if e["code"] == "YE-AUTH-01"]


def test_another_company_never_sees_these_errors(account, second_tenant):
    account["client"].post("/api/workers", json={"name": "No job"})
    assert second_tenant.get("/api/errors").json()["errors"] == []
