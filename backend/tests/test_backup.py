"""A full backup: everything the company owns, in one file the owner keeps -
with no password, token or key in it, and nothing of another company's."""
import io
import json
import zipfile

from conftest import make_employee
from test_measurement_and_ra_bills import placed_order, measure, line_of, raise_bill

PASSWORD = "Crew1234"


def backup(tenant, **params):
    res = tenant.get("/api/backup", params=params)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(res.content))


def table(z, name):
    return json.loads(z.read("data/%s.json" % name))


def test_the_backup_holds_the_business_down_to_the_lines(tenant):
    wo = placed_order(tenant, qty=100, rate=50)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 40)
    bill = raise_bill(tenant, wo["id"]).json()["bill"]
    z = backup(tenant)
    names = set(z.namelist())
    assert {"manifest.json", "README.txt", "data/jobs.json", "data/ra_bills.json",
            "data/ra_bill_lines.json", "sheets/ra_bills.csv"} <= names
    assert [b["number"] for b in table(z, "ra_bills")] == [bill["number"]]
    # A line has no company of its own; it is found through its bill.
    lines = table(z, "ra_bill_lines")
    assert lines and all(l["ra_bill_id"] == bill["id"] for l in lines)
    m = json.loads(z.read("manifest.json"))
    assert m["tables"]["ra_bills"] == 1 and not m["files_included"]


def test_no_secret_leaves_in_it(tenant):
    make_employee(tenant, password=PASSWORD)
    tenant.post("/api/settings", json={"WHATSAPP_ACCESS_TOKEN": "EAAG-very-secret"})
    z = backup(tenant)
    everything = b"".join(z.read(n) for n in z.namelist())
    assert b"EAAG-very-secret" not in everything
    me = table(z, "clients")[0]
    assert me["password_hash"] == "[removed]"
    assert all(e["password_hash"] in ("[removed]", None, "") for e in table(z, "employees"))
    # No stored password, in the salt:hash form they are kept in, survives.
    import re
    assert not re.search(rb"[0-9a-f]{64}:[0-9a-f]{64}", everything)
    kept = [r for r in table(z, "settings") if r["key"] == "WHATSAPP_ACCESS_TOKEN"]
    assert kept and kept[0]["value"] == "[removed]", "the token was planted, and is blanked"


def test_photos_come_only_when_asked_for(tenant):
    job = tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()
    up = tenant.post("/api/files", data={"attached_type": "job", "attached_id": str(job["id"])},
                     files={"file": ("site.jpg", b"\xff\xd8\xff\xe0jpegbytes", "image/jpeg")})
    assert up.status_code == 200, up.text
    lean = backup(tenant)
    assert not [n for n in lean.namelist() if n.startswith("files/")]
    assert table(lean, "project_files")[0]["data"] is None
    full = backup(tenant, files=1)
    got = [n for n in full.namelist() if n.startswith("files/")]
    assert len(got) == 1 and full.read(got[0]) == b"\xff\xd8\xff\xe0jpegbytes"
    assert table(full, "project_files")[0]["file"] == got[0]


def test_another_companys_data_is_never_in_it(tenant, second_tenant):
    second_tenant.post("/api/jobs", json={"name": "Their secret project", "customer_name": "Them"})
    tenant.post("/api/jobs", json={"name": "Ours", "customer_name": "Us"})
    z = backup(tenant)
    assert [j["name"] for j in table(z, "jobs")] == ["Ours"]
    assert b"Their secret project" not in b"".join(z.read(n) for n in z.namelist())
    assert len(table(z, "clients")) == 1


def test_only_the_account_holder_takes_one(tenant, portal):
    e = make_employee(tenant, permission_role="supervisor", password=PASSWORD)
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD})
    assert portal.get("/api/backup").status_code in (401, 403)
    assert portal.get("/api/backup/info").status_code in (401, 403)


def test_the_last_backup_is_remembered(tenant):
    assert tenant.get("/api/backup/info").json()["last_backup"] == ""
    backup(tenant)
    info = tenant.get("/api/backup/info").json()
    assert info["last_backup"] and "data only" in info["last_backup_details"] and info["rows"] > 0
