"""The calendar lists India's public holidays for a year."""


def test_holidays_for_a_year(tenant):
    rows = tenant.get("/api/calendar/holidays?year=2026").json()
    names = {r["date"]: r["name"] for r in rows}
    assert names["2026-01-26"] == "Republic Day"
    assert names["2026-08-15"] == "Independence Day"
    assert "2026-11-08" in names
    assert [r["date"] for r in rows] == sorted(names)


def test_a_silly_year_is_refused(tenant):
    assert tenant.get("/api/calendar/holidays?year=99999").status_code == 400
