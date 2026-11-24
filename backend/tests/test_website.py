"""What the company website reads from the ERP (totals, and the projects ticked for it) and the enquiry it sends back."""
import pytest

from app import db as database, models
from app.routers import website


@pytest.fixture
def ours(account, monkeypatch):
    """This tenant is the company the website is for."""
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient.id).filter(models.DBClient.email == account["email"]).scalar()
    monkeypatch.setattr(website, "_company", lambda db: db.get(models.DBClient, cid))
    return cid


def job(tenant, name, status="in_progress"):
    res = tenant.post("/api/jobs", json={"name": name, "customer_name": "Aniprotech", "status": status, "quoted_value": 4500000})
    assert res.status_code == 200, res.text
    return res.json()


def put_on_website(tenant, job_id, **card):
    """A project's card drafted in Settings -> Website, and published."""
    card = dict({"show": True, "sector": "", "location": "", "scope": ""}, **card)
    res = tenant.put("/api/website/sections/projects", json={"draft": {str(job_id): card}})
    assert res.status_code == 200, res.text
    assert tenant.post("/api/website/publish", json={}).status_code == 200


def test_only_ticked_projects_show_and_only_what_their_card_says(tenant, client, ours):
    shown = job(tenant, "Vanya City STP", status="complete")
    job(tenant, "Not on the website")
    put_on_website(tenant, shown["id"], sector="Water", location="Hyderabad", scope="295 KLD STP")
    assert tenant.get("/api/jobs/%d" % shown["id"]).json()["website"] == {"show": True, "sector": "Water", "location": "Hyderabad", "scope": "295 KLD STP"}

    site = client.get("/api/public/site").json()
    assert [p["name"] for p in site["projects"]] == ["Vanya City STP"]
    card = site["projects"][0]
    assert card["status"] == "Completed" and card["sector"] == "Water" and card["scope"] == "295 KLD STP"
    assert "4500000" not in str(site) and "quoted_value" not in str(site), "no money leaves this way"
    assert site["numbers"]["projects_delivered"] >= 1 and site["numbers"]["ongoing_sites"] >= 1


def test_a_photo_is_served_only_for_a_project_on_the_website(tenant, client, ours):
    on, off = job(tenant, "Shown"), job(tenant, "Hidden")
    put_on_website(tenant, on["id"])
    with database.SessionLocal() as s:
        ids = []
        for j in (on, off):
            f = models.DBFile(client_id=ours, job_id=j["id"], kind="photo", attached_type="job", content_type="image/png", data=b"\x89PNG", name="p.png")
            s.add(f)
            s.flush()
            ids.append(f.id)
        s.commit()
    assert client.get("/api/public/site").json()["projects"][0]["photos"] == ["/api/public/site/photos/%d" % ids[0]]
    assert client.get("/api/public/site/photos/%d" % ids[0]).status_code == 200
    assert client.get("/api/public/site/photos/%d" % ids[1]).status_code == 404


def test_an_enquiry_becomes_a_new_lead_in_the_tender_pipeline(tenant, client, ours):
    res = client.post("/api/public/enquiry", json={"name": "Ravi Kumar", "company": "Vanya Developers", "phone": "9800000000",
                                                   "city": "Hyderabad", "project_type": "Township or layout", "scopes": ["Roads", "Drainage"],
                                                   "message": "Plotted layout, 12 acres."})
    assert res.status_code == 200, res.text
    with database.SessionLocal() as s:
        lead = s.query(models.DBLead).filter(models.DBLead.client_id == ours).order_by(models.DBLead.id.desc()).first()
        assert lead.source == "Website enquiry" and lead.status == "NEW" and lead.customer_name == "Vanya Developers"
        assert lead.title == "Website enquiry: Township or layout, Hyderabad" and "Roads, Drainage" in lead.notes
        assert s.query(models.DBAlert).filter(models.DBAlert.client_id == ours, models.DBAlert.kind == "website_enquiry").count() == 1


def test_an_enquiry_needs_a_way_to_reply_and_a_robot_leaves_nothing(tenant, client, ours):
    assert client.post("/api/public/enquiry", json={"name": "Ravi"}).status_code == 400
    assert client.post("/api/public/enquiry", json={"name": "Ravi", "email": "not-an-email"}).status_code == 400
    with database.SessionLocal() as s:
        before = s.query(models.DBLead).filter(models.DBLead.client_id == ours).count()
    assert client.post("/api/public/enquiry", json={"name": "Bot", "email": "b@example.com", "website": "http://spam"}).status_code == 200
    with database.SessionLocal() as s:
        assert s.query(models.DBLead).filter(models.DBLead.client_id == ours).count() == before


def test_search_engines_are_shown_the_front_page_and_not_the_erp(client):
    robots = client.get("/robots.txt").text
    assert "Disallow: /next/" in robots and "Disallow: /api/" in robots and "Sitemap:" in robots
    assert "<loc>http://testserver/</loc>" in client.get("/sitemap.xml").text


def allowed(robots, path):
    """robots.txt as Google reads it: the longest rule that matches the path wins, Allow on a tie; '$' ends a rule."""
    best = (-1, True)
    for line in robots.splitlines():
        kind, _, rule = line.partition(": ")
        if kind not in ("Allow", "Disallow"):
            continue
        exact = rule.endswith("$")
        stem = rule.rstrip("$")
        if (path == stem) if exact else path.startswith(stem):
            if len(rule) > best[0] or (len(rule) == best[0] and kind == "Allow"):
                best = (len(rule), kind == "Allow")
    return best[1]


def test_google_can_fetch_everything_the_front_page_is_drawn_with(client):
    """The front page's words and pictures come from the app's script: blocked, Google sees an empty page and keeps
    showing an old copy. The ERP's own screens and the rest of the API stay closed."""
    robots = client.get("/robots.txt").text
    for path in ("/", "/next/assets/index-CCb_YzMP.js", "/next/assets/index-x.css", "/next/site/img/cat3.jpg",
                 "/next/favicon.svg", "/next/favicon-32.png", "/next/icons/apple-touch-icon.png", "/next/manifest.webmanifest",
                 "/next/jobs", "/api/public/site"):
        assert allowed(robots, path), path
    for path in ("/next/", "/next/projects", "/next/login.html", "/api/jobs", "/api/public/enquiry"):
        assert not allowed(robots, path), path


def test_the_front_page_is_described_as_the_civil_company():
    """What Google and a WhatsApp link preview show: Yalavarti Infra Projects, never the electrical contractor."""
    from app.core import static
    head = static.HOME_TITLE + static.HOME_DESCRIPTION + static.HOME_HEAD
    assert static.HOME_TITLE.startswith("Yalavarti Infra Projects")
    for word in ("Electrical", "33 kV", "PHE", "panels", "YERP"):
        assert word.lower() not in head.lower(), word


def test_the_link_preview_picture_is_a_full_address(client, monkeypatch, tmp_path):
    """WhatsApp shows the picture only when og:image is a full https address, as the visitor reached the site."""
    from app.core import static
    (tmp_path / "index.html").write_text('<html><head><title>Y ERP</title><meta name="description" content="Y ERP - billing">'
                                         '</head><body><noscript><p>Y ERP needs JavaScript to run.</p></noscript></body></html>',
                                         encoding="utf8")
    monkeypatch.setattr(static, "FRONTEND_DIST", str(tmp_path))
    html = client.get("/", headers={"x-forwarded-proto": "https"}).text
    assert "<title>Yalavarti Infra Projects | Homes, Townships &amp; Civil Infrastructure</title>" in html
    assert '<meta property="og:image" content="https://testserver/next/site/img/cat3.jpg">' in html
    # No ERP wording anywhere a visitor or a search engine can see it.
    assert "ERP" not in html and "info@yalavartiinfra.com" in html
