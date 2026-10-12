"""The two panels every open screen asks for each minute are remembered until something is saved."""
from sqlalchemy import event

from app import db as database


def queries(client, path):
    seen = [0]

    def count(*_):
        seen[0] += 1
    event.listen(database.engine, "before_cursor_execute", count)
    try:
        res = client.get(path)
    finally:
        event.remove(database.engine, "before_cursor_execute", count)
    assert res.status_code == 200, (path, res.text)
    return seen[0], res.json()


def test_the_approvals_badge_is_remembered_until_something_changes(tenant):
    first, body = queries(tenant, "/api/approvals/inbox")
    again, same = queries(tenant, "/api/approvals/inbox")
    assert again < first, "asked again: %d queries, the first time %d" % (again, first)
    assert same == body
    # a save of any kind throws the remembered answer away
    tenant.post("/api/departments", json={"name": "Roads", "description": "", "color": "#ff0000", "icon": "building"})
    after, _ = queries(tenant, "/api/approvals/inbox")
    assert after >= first, "after a write it is worked out afresh"


def test_head_office_overview_is_remembered_until_something_changes(tenant):
    first, body = queries(tenant, "/api/ho/overview")
    again, same = queries(tenant, "/api/ho/overview")
    assert again < first
    assert same == body


def test_the_money_dashboards_are_remembered_until_something_changes(tenant):
    for path in ("/api/costs/by-project", "/api/jobs-pnl"):
        first, body = queries(tenant, path)
        again, same = queries(tenant, path)
        assert again < first, "%s: %d queries the second time, %d the first" % (path, again, first)
        assert same == body
    tenant.post("/api/jobs", json={"name": "New site", "status": "in_progress"})
    _, fresh = queries(tenant, "/api/jobs-pnl")
    assert any(p["name"] == "New site" for p in fresh["projects"]), "a save shows up at once, not after the timeout"
