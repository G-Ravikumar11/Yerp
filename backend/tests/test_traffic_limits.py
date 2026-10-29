"""Traffic controls for a few hundred people: an office that signs in together is not turned away, and exports, documents and
AI requests are counted for each signed-in browser so a few people cannot slow the rest."""
import pytest

import main
from app.core.middleware import heavy_kind

PASSWORD = "Passw0rdTest"


@pytest.fixture(autouse=True)
def _calm():
    main.rate_limiter._hits.clear()
    yield
    main.rate_limiter._hits.clear()


def test_which_requests_count_as_heavy():
    assert heavy_kind("/api/boqs/12/export.xlsx") == "file" and heavy_kind("/api/costs/by-project.pdf") == "file"
    assert heavy_kind("/api/store/reports/valuation/export") == "file" and heavy_kind("/api/store/inward/grn/4/print") == "file"
    assert heavy_kind("/api/ai/insights") == "ai" and heavy_kind("/api/ai/planning/jobs/3/draft") == "ai"
    assert heavy_kind("/api/ai/status") == ""                        # a cheap status check
    assert heavy_kind("/api/jobs") == "" and heavy_kind("/api/client/me") == "" and heavy_kind("/next/assets/app.js") == ""


def test_an_office_signing_in_together_is_not_turned_away(account):
    """Thirty people behind one address sign in within a minute; ten used to be the most."""
    c, email = account["client"], account["email"]
    codes = [c.post("/api/client/login", json={"email": email, "password": PASSWORD}).status_code for _ in range(30)]
    assert codes.count(429) == 0 and codes.count(200) == 30


def test_the_sign_in_limit_is_a_setting_and_still_stops_a_flood(account, monkeypatch):
    import app.routers.auth as auth
    monkeypatch.setattr(auth, "LOGIN_PER_MINUTE", 5)
    c, email = account["client"], account["email"]
    main.rate_limiter._hits.clear()                                  # the fixture signed in once already
    codes = [c.post("/api/client/login", json={"email": email, "password": PASSWORD}).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429] * 3


def test_exports_are_limited_for_each_person_not_for_everybody(account, second_tenant, monkeypatch):
    monkeypatch.setenv("HEAVY_PER_MINUTE", "4")
    mine = account["client"]
    codes = [mine.get("/api/attendance/export").status_code for _ in range(7)]
    assert codes[4:] == [429] * 3 and 429 not in codes[:4]
    body = mine.get("/api/attendance/export")
    assert body.status_code == 429 and body.json()["code"] == "YE-BUSY-01" and "exports" in body.json()["detail"]
    assert second_tenant.get("/api/attendance/export").status_code != 429      # somebody else has a count of their own
    assert mine.get("/api/client/me").status_code == 200                        # and ordinary screens are never held back


def test_ai_requests_have_their_own_limit(account, monkeypatch):
    monkeypatch.setenv("AI_PER_MINUTE", "3")
    c = account["client"]
    codes = [c.get("/api/ai/status").status_code for _ in range(6)]
    assert 429 not in codes                                                    # the cheap status check is not counted
    codes = [c.get("/api/ai/insights").status_code for _ in range(5)]
    assert codes[3:] == [429, 429] and 429 not in codes[:3]


def test_a_limit_of_zero_turns_it_off(account, monkeypatch):
    monkeypatch.setenv("HEAVY_PER_MINUTE", "0")
    c = account["client"]
    assert 429 not in [c.get("/api/attendance/export").status_code for _ in range(40)]
