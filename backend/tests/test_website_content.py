"""The website's content in the database (Settings -> Website): one row per section, a draft and a published version,
seeded from the text the site was built with; visitors see only what is published; every publishing kept and an earlier
one put back; what is saved checked; pictures uploaded and kept private until published; projects' cards and photos; the
preview; and the "Manage website" right."""
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import main
from app import db as database, models
from app.core.permissions import PERMISSION_ROLES, PORTAL_PERMISSIONS
from app.routers import website
from app.routers.hr import MASTER_ONLY_RIGHTS
from app.services import website_content
from tests.conftest import make_employee


@pytest.fixture
def ours(account, monkeypatch):
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient.id).filter(models.DBClient.email == account["email"]).scalar()
    monkeypatch.setattr(website, "_company", lambda db: db.get(models.DBClient, cid))
    return cid


def _rows(cid):
    with database.SessionLocal() as s:
        S = models.DBWebsiteSection
        return {r.key: r for r in s.query(S).filter(S.client_id == cid).all()}


def _public(seed):
    return {k: v for k, v in seed.items() if k not in website_content.PRIVATE_KEYS}


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def _png(colour="red"):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), colour).save(out, "PNG")
    return out.getvalue()


def test_the_seed_has_every_section_and_the_site_as_it_was_built():
    seed = website_content.seed()
    assert list(seed) == list(website_content.SECTION_KEYS)
    assert seed["company"]["name"] == "Yalavarti Infra Projects"
    assert seed["hero"]["title"] == "Building homes, townships and the infrastructure around them"
    assert [c["id"] for c in seed["capabilities"]][:3] == ["house", "apartment", "township"]
    assert [s["id"] for s in seed["layout"]] == list(website_content.PAGE_SECTIONS) and all(s["shown"] for s in seed["layout"])
    assert seed["projects"] == {}


def test_before_anything_is_saved_visitors_see_the_first_content(client, ours):
    assert _rows(ours) == {}
    assert client.get("/api/public/site").json()["content"] == _public(website_content.seed())


def test_start_up_gives_every_set_up_company_its_sections_and_never_overwrites_one(ours):
    with database.SessionLocal() as s:
        s.get(models.DBClient, ours).is_onboarded = True
        s.add(models.DBWebsiteSection(client_id=ours, key="lead", draft='"Ours"', published='"Ours"'))
        s.commit()
        website_content.seed_all(s)
        website_content.seed_all(s)                                  # a second start-up adds nothing
    rows = _rows(ours)
    assert sorted(rows) == sorted(website_content.SECTION_KEYS)
    assert rows["lead"].published == '"Ours"'                       # what was there stays
    assert json.loads(rows["hero"].draft) == json.loads(rows["hero"].published) == website_content.seed()["hero"]


def test_visitors_see_the_published_version_never_the_draft(tenant, client, ours):
    sections = ok(tenant.get("/api/website/sections"))["sections"]
    assert [x["key"] for x in sections] == list(website_content.SECTION_KEYS)
    assert not any(x["unpublished_changes"] for x in sections)
    hero = {"title": "Draft title", "sub": "Draft line"}
    ok(tenant.put("/api/website/sections/hero", json={"draft": hero}))
    assert client.get("/api/public/site").json()["content"]["hero"] == website_content.seed()["hero"]
    assert ok(tenant.get("/api/website/preview"))["content"]["hero"] == hero            # the preview shows the draft
    mine = next(x for x in ok(tenant.get("/api/website/sections"))["sections"] if x["key"] == "hero")
    assert mine["unpublished_changes"] and mine["draft"] == hero
    # Version 1 is the website as it stood before; this publishing is version 2.
    assert ok(tenant.post("/api/website/publish", json={}))["version"] == 2
    assert client.get("/api/public/site").json()["content"]["hero"] == hero


def test_a_draft_can_be_thrown_away(tenant, ours):
    ok(tenant.put("/api/website/sections/lead", json={"draft": "Not this"}))
    ok(tenant.post("/api/website/sections/lead/discard"))
    lead = next(x for x in ok(tenant.get("/api/website/sections"))["sections"] if x["key"] == "lead")
    assert not lead["unpublished_changes"] and lead["draft"] == website_content.seed()["lead"]


def test_every_publishing_is_kept_and_an_earlier_one_can_be_put_back(tenant, client, ours):
    for line in ("First", "Second"):
        ok(tenant.put("/api/website/sections/lead", json={"draft": line}))
        ok(tenant.post("/api/website/publish", json={}))
    history = ok(tenant.get("/api/website/versions"))["versions"]
    assert [v["number"] for v in history] == [3, 2, 1]
    back = ok(tenant.post("/api/website/versions/%d/restore" % history[1]["id"]))
    assert back["version"] == 4
    assert client.get("/api/public/site").json()["content"]["lead"] == "First"
    assert ok(tenant.get("/api/website/versions"))["versions"][0]["note"] == "Restored version 2"


def test_the_website_as_it_was_before_the_first_publishing_can_be_put_back_projects_and_all(tenant, client, ours):
    j = ok(tenant.post("/api/jobs", json={"name": "Vision Anmaya", "customer_name": "Vision", "status": "in_progress"}))
    ok(tenant.put("/api/website/sections/lead", json={"draft": "Changed"}))
    ok(tenant.put("/api/website/sections/projects", json={"draft": {str(j["id"]): {"show": True, "sector": "Residential", "location": "", "scope": ""}}}))
    ok(tenant.post("/api/website/publish", json={}))
    site = client.get("/api/public/site").json()
    assert site["content"]["lead"] == "Changed" and [p["name"] for p in site["projects"]] == ["Vision Anmaya"]
    first = ok(tenant.get("/api/website/versions"))["versions"][-1]
    assert first["number"] == 1 and first["published_by"] == "As built"
    ok(tenant.post("/api/website/versions/%d/restore" % first["id"]))
    site = client.get("/api/public/site").json()
    assert site["content"]["lead"] == website_content.seed()["lead"]
    assert site["projects"] == []                                   # the project is off the website again


def test_sections_are_shown_hidden_and_reordered(tenant, client, ours):
    layout = list(reversed(website_content.seed()["layout"]))
    layout[0]["shown"] = False
    ok(tenant.put("/api/website/sections/layout", json={"draft": layout}))
    ok(tenant.post("/api/website/publish", json={}))
    assert client.get("/api/public/site").json()["content"]["layout"] == layout
    # Every section must still be listed, once.
    res = tenant.put("/api/website/sections/layout", json={"draft": layout[1:]})
    assert res.status_code == 400 and "every section" in res.json()["detail"]


@pytest.mark.parametrize("key,draft,words", [
    ("company", dict(website_content.seed()["company"], group={"name": "x", "url": "javascript:alert(1)", "does": ""}), "web address"),
    ("slides", [{"img": "https://elsewhere.example/a.jpg", "t": "a", "l": "b"}], "picture"),
    ("hero", {"title": 5, "sub": ""}, "text"),
    ("hero", {"title": "x" * 4000, "sub": ""}, "characters"),
    ("about", "not a list", "list"),
    ("hero", {"title": "", "sub": "", "script": "<b>"}, "not one of its fields"),
])
def test_what_is_saved_keeps_its_shape_and_links_and_pictures_stay_safe(tenant, ours, key, draft, words):
    res = tenant.put("/api/website/sections/%s" % key, json={"draft": draft})
    assert res.status_code == 400 and words in res.json()["detail"], res.text


def test_there_is_no_such_section(tenant, ours):
    assert tenant.put("/api/website/sections/nope", json={"draft": ""}).status_code == 404


def test_a_picture_is_public_only_once_it_is_on_the_published_website(tenant, ours):
    up = ok(tenant.post("/api/website/images", data={"place": "hero"}, files={"file": ("a.png", _png(), "image/png")}))
    url = up["path"]
    assert url.startswith("/api/public/site/images/")
    assert tenant.get(url).status_code == 200                  # whoever manages the website sees it (the preview)
    with TestClient(main.app) as visitor:
        assert visitor.get(url).status_code == 404             # nobody else, until it is published
        ok(tenant.put("/api/website/sections/slides", json={"draft": [{"img": url, "t": "Ours", "l": "Our own photo"}]}))
        assert tenant.delete("/api/website/images/%d" % up["id"]).status_code == 409     # used in the draft
        ok(tenant.post("/api/website/publish", json={}))
        assert visitor.get(url).status_code == 200
    images = ok(tenant.get("/api/website/images"))["images"]
    assert images[0]["published"] and images[0]["place"] == "hero"


def test_a_picture_nobody_uses_can_be_removed_and_a_non_photo_is_refused(tenant, ours):
    up = ok(tenant.post("/api/website/images", data={"place": "section"}, files={"file": ("a.png", _png(), "image/png")}))
    ok(tenant.delete("/api/website/images/%d" % up["id"]))
    res = tenant.post("/api/website/images", data={"place": "hero"}, files={"file": ("a.svg", b"<svg/>", "image/svg+xml")})
    assert res.status_code == 400


def test_project_cards_and_their_photos_change_only_when_published(tenant, client, ours):
    j = ok(tenant.post("/api/jobs", json={"name": "Vision Arusha", "customer_name": "Vision", "status": "in_progress"}))
    ids = [ok(tenant.post("/api/website/images", data={"place": "project", "job_id": str(j["id"])},
                          files={"file": ("p%d.png" % i, _png(c), "image/png")}))["id"]
           for i, c in enumerate(("red", "blue", "green"))]
    card = {"show": True, "sector": "Residential", "location": "Hyderabad", "scope": "Towers", "photos": [ids[2], ids[0]]}
    ok(tenant.put("/api/website/sections/projects", json={"draft": {str(j["id"]): card}}))
    assert client.get("/api/public/site").json()["projects"] == []                  # not until it is published
    preview = ok(tenant.get("/api/website/preview"))["projects"]
    assert [p["name"] for p in preview] == ["Vision Arusha"]
    assert preview[0]["photos"] == ["/api/website/images/%d" % ids[2], "/api/website/images/%d" % ids[0]]
    ok(tenant.post("/api/website/publish", json={}))
    site = client.get("/api/public/site").json()["projects"]
    assert site[0]["sector"] == "Residential"
    assert site[0]["photos"] == ["/api/public/site/photos/%d" % ids[2], "/api/public/site/photos/%d" % ids[0]]
    listed = next(p for p in ok(tenant.get("/api/website/projects"))["projects"] if p["id"] == j["id"])
    assert listed["published"]["show"] and sorted(listed["photos"]) == sorted(ids)


def test_a_card_can_only_use_its_own_projects_photos(tenant, ours):
    a = ok(tenant.post("/api/jobs", json={"name": "A", "customer_name": "x", "status": "in_progress"}))
    b = ok(tenant.post("/api/jobs", json={"name": "B", "customer_name": "x", "status": "in_progress"}))
    pid = ok(tenant.post("/api/website/images", data={"place": "project", "job_id": str(b["id"])},
                         files={"file": ("p.png", _png(), "image/png")}))["id"]
    res = tenant.put("/api/website/sections/projects", json={"draft": {str(a["id"]): {"show": True, "photos": [pid]}}})
    assert res.status_code == 400


def test_the_website_panel_is_not_public(client):
    for url in ("/api/website/sections", "/api/website/preview", "/api/website/projects", "/api/website/images"):
        assert client.get(url).status_code in (401, 403), url
    assert client.post("/api/website/publish", json={}).status_code in (401, 403)


def test_manage_website_is_the_masters_and_given_person_by_person(account):
    assert next(p for p in PORTAL_PERMISSIONS if p["key"] == "website.manage")["label"] == "Manage website"
    holders = [r["code"] for r in PERMISSION_ROLES if "website.manage" in r["permissions"]]
    assert holders == ["owner"]                                     # no access level brings it with a job title
    assert "website.manage" in MASTER_ONLY_RIGHTS                    # and HR cannot hand it out

    t, tag = account["client"], uuid.uuid4().hex[:6]
    email = "web-%s@example.com" % tag
    emp = make_employee(t, email=email, password="Crew1234", permission_role="md", status="active")
    with TestClient(main.app) as c:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        assert c.get("/api/website/sections").status_code == 403    # not even the MD, until it is given
        assert c.put("/api/website/sections/lead", json={"draft": "x"}).status_code == 403
        assert t.put("/api/employees/%d" % emp["id"], json={"extra_permissions": "website.manage"}).status_code == 200
        assert c.get("/api/website/sections").status_code == 200
        assert c.put("/api/website/sections/lead", json={"draft": "From staff"}).status_code == 200
        assert c.post("/api/website/publish", json={}).status_code == 200


def test_only_the_preview_of_the_front_page_may_be_framed_and_only_by_our_own_pages(client):
    assert client.get("/?preview=1").headers["X-Frame-Options"] == "SAMEORIGIN"
    assert client.get("/").headers["X-Frame-Options"] == "DENY"
    assert client.get("/?preview=1").headers["Content-Security-Policy"] == "frame-ancestors 'self'"


# CAREERS: openings posted from the website panel are Recruitment's jobs, and their applications arrive in Recruitment.

def _post(tenant, **o):
    return ok(tenant.post("/api/website/careers", json=dict({"title": "Site Engineer (Civil)", "location": "Ongole",
                                                             "experience": "3-5 years", "description": "Runs a block."}, **o)))


def test_an_opening_posted_from_the_panel_is_on_the_website_with_an_application_form(tenant, client, ours):
    opening = _post(tenant)["opening"]
    assert opening["on_website"] and opening["reference"].startswith("JOB-")
    listed = client.get("/api/public/site").json()["openings"]
    assert [(o["title"], o["location"], o["experience"]) for o in listed] == [("Site Engineer (Civil)", "Ongole", "3-5 years")]
    token = listed[0]["apply_token"]
    form = client.get("/api/recruitment/form/%s" % token).json()
    assert [f["label"] for f in json.loads(form["fields"])][:3] == ["Full name", "Email", "Phone"]
    # An application arrives in Recruitment, against that job.
    res = client.post("/api/recruitment/form/%s/submit" % token, json={
        "answers": json.dumps({"Full name": "Ravi Kumar", "Email": "ravi@example.com", "Phone": "9800000000"}),
        "candidate_name": "Ravi Kumar", "candidate_email": "ravi@example.com", "candidate_phone": "9800000000"})
    assert res.status_code == 200, res.text
    jobs = ok(tenant.get("/api/recruitment/jobs"))
    job = next(j for j in jobs if j["id"] == opening["id"])
    assert job["applicant_count"] == 1 and job["experience"] == "3-5 years"
    assert ok(tenant.get("/api/website/careers"))["openings"][0]["applications"] == 1


def test_an_opening_is_edited_closed_off_the_website_and_reopened(tenant, client, ours):
    oid = _post(tenant)["opening"]["id"]
    ok(tenant.put("/api/website/careers/%d" % oid, json={"title": "Senior Site Engineer", "location": "Ongole", "experience": "6+ years", "description": ""}))
    assert client.get("/api/public/site").json()["openings"][0]["title"] == "Senior Site Engineer"
    closed = ok(tenant.post("/api/website/careers/%d/close" % oid))["opening"]
    assert not closed["on_website"] and closed["status"] == "closed"
    assert client.get("/api/public/site").json()["openings"] == []
    assert ok(tenant.post("/api/website/careers/%d/reopen" % oid))["opening"]["on_website"]
    assert len(client.get("/api/public/site").json()["openings"]) == 1


def test_an_opening_needs_a_title_and_must_be_ours(tenant, ours, second_tenant):
    assert tenant.post("/api/website/careers", json={"title": " "}).status_code == 400
    theirs = ok(second_tenant.post("/api/website/careers", json={"title": "Their job"}))["opening"]["id"]
    assert tenant.post("/api/website/careers/%d/close" % theirs).status_code == 404


def test_openings_posted_in_recruitment_show_too_and_a_draft_one_does_not(tenant, client, ours):
    ok(tenant.post("/api/recruitment/jobs", json={"title": "Surveyor", "status": "open", "experience": "2 years"}))
    ok(tenant.post("/api/recruitment/jobs", json={"title": "Not yet", "status": "draft"}))
    assert [o["title"] for o in client.get("/api/public/site").json()["openings"]] == ["Surveyor"]


def test_careers_need_manage_website(account, ours):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    email = "hr-%s@example.com" % tag
    make_employee(t, email=email, password="Crew1234", permission_role="hr", status="active")
    with TestClient(main.app) as c:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        assert c.get("/api/website/careers").status_code == 403
        assert c.post("/api/website/careers", json={"title": "x"}).status_code == 403
