"""The daily progress report as a PDF on the letterhead: weather, labour and plant, the plan against the day's work, the hindrances,
the photographs, and who signed it off - with changes made after sign-off shown, and no money on it (it goes to the client)."""
import io
from datetime import date, timedelta

from pypdf import PdfReader

from test_project_files import upload


def pdf_text(res):
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(res.content)).pages)


def photo():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 40)).save(buf, "JPEG")
    return buf.getvalue()


def a_day(tenant):
    on = (date.today() - timedelta(days=1)).isoformat()
    job = tenant.post("/api/jobs", json={"name": "Lakeview Towers", "customer_name": "Lakeview Ltd", "site_address": "Gachibowli"}).json()
    act = tenant.post("/api/jobs/%d/schedule/activities" % job["id"], json={
        "name": "Raft concrete", "planned_start": (date.today() - timedelta(days=5)).isoformat(), "planned_finish": (date.today() + timedelta(days=5)).isoformat()})
    aid = act.json()["schedule"]["activities"][0]["id"]
    d = tenant.post("/api/diary", json={
        "job_id": job["id"], "diary_date": on, "weather": "Rain", "rain_hours": 2, "working_hours": 8,
        "work_done": "Raft poured in bay 2", "holdups": "Pump broke down at noon", "visitors": "Client engineer Mr Rao",
        "labour": [{"trade": "Mason", "agency": "Own", "headcount": 6, "hours": 8, "rate": 950}],
        "plant": [{"plant": "Concrete pump", "worked_hours": 4, "idle_hours": 4, "rate": 2500, "remarks": "broke down"}],
        "work_updates": [{"activity_id": aid, "percent": 35}]})
    assert d.status_code == 200, d.text
    did = d.json()["diary"]["id"]
    assert tenant.post("/api/jobs/%d/hindrances" % job["id"], json={"cause": "Plant breakdown", "description": "Pump hydraulic failure",
                                                                     "from_date": on, "responsibility": "Contractor"}).status_code == 200
    assert upload(tenant, "diary", did, data=photo(), name="bay2.jpg", caption="Bay 2 after the pour").status_code == 200
    return job, did, on


def test_the_report_carries_the_day(tenant):
    job, did, on = a_day(tenant)
    text = pdf_text(tenant.get("/api/diary/%d/report.pdf" % did))
    for words in ("DAILY PROGRESS REPORT", "Lakeview Towers", "Lakeview Ltd", "Rain", "Raft poured in bay 2", "Planned against actual",
                  "Raft concrete", "35%", "Mason", "Concrete pump", "Hindrances", "H-001", "Plant breakdown", "Pump broke down at noon",
                  "Client engineer Mr Rao", "Photographs", "Bay 2 after the pour", "Not yet signed off", "DRAFT"):
        assert words in text, words
    # Money stays out: the report goes to the client.
    assert "950" not in text and "2,500" not in text and "Labour cost" not in text


def test_signed_off_and_changed_after(tenant):
    job, did, on = a_day(tenant)
    assert tenant.post("/api/diary/%d/submit" % did).status_code == 200
    text = pdf_text(tenant.get("/api/diary/%d/report.pdf" % did))
    assert "Signed off by" in text and "Not yet signed off" not in text and "DRAFT - NOT SIGNED OFF" not in text
    assert tenant.get("/api/diary/%d" % did).json()["submitted_by_name"]
    assert tenant.post("/api/diary/%d/reopen" % did, json={"reason": "Mandays were wrong"}).status_code == 200
    assert tenant.post("/api/diary/%d/submit" % did).status_code == 200
    text = pdf_text(tenant.get("/api/diary/%d/report.pdf" % did))
    assert "Changed after it was signed off" in text and "Mandays were wrong" in text


def test_a_day_with_little_on_it_still_prints(tenant):
    job = tenant.post("/api/jobs", json={"name": "Quiet site", "customer_name": "X"}).json()
    d = tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": date.today().isoformat(), "work_done": "Cleaning"}).json()["diary"]["id"]
    assert "Cleaning" in pdf_text(tenant.get("/api/diary/%d/report.pdf" % d))


def test_another_sites_report_is_not_served(tenant, portal):
    from test_site_scope import staff_on, two_projects
    a, b = two_projects(tenant)
    d = tenant.post("/api/diary", json={"job_id": b["id"], "diary_date": date.today().isoformat(), "work_done": "x"}).json()["diary"]["id"]
    staff_on(tenant, portal, [a["id"]])
    assert portal.get("/api/diary/%d/report.pdf" % d).status_code == 404
