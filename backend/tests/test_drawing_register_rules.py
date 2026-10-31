"""The drawing register: the current revision is the latest by name, every status change is logged, and a drawing
ever released Good for construction is never deleted."""
import io

from app.services.drawing_rules import revision_key
from test_project_files import PDF, job


def drawing(tenant, number="STR-201"):
    j = job(tenant)
    return tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": number, "title": "Raft"}).json()["drawing"]


def revise(tenant, d, rev, status="For information"):
    res = tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("%s.pdf" % rev, io.BytesIO(PDF + rev.encode()), "application/pdf")},
                      data={"revision": rev, "status": status})
    assert res.status_code == 200, res.text
    return res.json()


def test_revisions_order_by_their_own_names():
    assert revision_key("R2") < revision_key("R10")
    assert revision_key("A") < revision_key("B") < revision_key("Z") < revision_key("AA")
    assert revision_key("P01") < revision_key("P02")


def test_a_late_recorded_r1_does_not_replace_r2(tenant):
    d = drawing(tenant)
    revise(tenant, d, "R0")
    revise(tenant, d, "R2", "Approved")
    out = revise(tenant, d, "R1", "Good for construction")
    assert "R2 stays current" in out["message"]
    got = tenant.get("/api/drawings/%d" % d["id"]).json()["drawing"]
    assert (got["current_revision"], got["status"]) == ("R2", "Approved")


def test_a_status_is_set_on_the_current_revision_and_every_change_is_logged(tenant):
    d = drawing(tenant)
    revise(tenant, d, "R0", "For approval")
    revise(tenant, d, "R2", "For approval")
    revise(tenant, d, "R1")                                            # late; R2 stays current
    assert tenant.post("/api/drawings/%d/status" % d["id"], json={"status": "Approved"}).status_code == 200
    got = tenant.get("/api/drawings/%d" % d["id"]).json()["drawing"]
    assert got["status"] == "Approved" and got["current_revision"] == "R2"
    changes = [s["change"] for s in got["status_log"]]
    # R0 arrives for approval; R2 (also for approval) and the late R1 change nothing; then R2 is approved.
    assert changes == ["rev R0: For information -> For approval", "rev R2: For approval -> Approved"]


def test_a_drawing_ever_good_for_construction_cannot_be_deleted(tenant):
    d = drawing(tenant)
    revise(tenant, d, "R0", "Good for construction")
    revise(tenant, d, "R1")                                            # superseded since: still once released
    assert tenant.get("/api/drawings/%d" % d["id"]).json()["drawing"]["deletable"] is False
    res = tenant.delete("/api/drawings/%d" % d["id"])
    assert res.status_code == 409 and "Good for construction" in res.json()["detail"]
    assert tenant.delete("/api/master/drawing/%d" % d["id"]).status_code in (403, 404, 409)


def test_a_drawing_never_released_can_still_be_deleted(tenant):
    d = drawing(tenant, "ARC-9")
    revise(tenant, d, "R0", "For approval")
    assert tenant.delete("/api/drawings/%d" % d["id"]).status_code == 200
