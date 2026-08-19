"""Schema updates run non-fatally at boot, so a step that failed and a step
that succeeded used to look identical. These cover the reporting that makes the
difference visible."""
import pytest

import database
import main


@pytest.fixture
def superadmin(client):
    main.rate_limiter._hits.clear()
    res = client.post("/api/superadmin/login", json={
        "identifier": "hello@billing.com", "password": "TestSuper123",
    })
    assert res.status_code == 200, res.text
    return client


@pytest.fixture(autouse=True)
def _clean_migration_errors():
    saved = list(database.MIGRATION_ERRORS)
    database.MIGRATION_ERRORS.clear()
    yield
    database.MIGRATION_ERRORS[:] = saved


def test_health_is_plain_ok_when_no_migration_failed(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "migration_warnings" not in body


def test_health_flags_a_failed_migration(client):
    database.MIGRATION_ERRORS.append("migration step 3: relation does not exist")
    body = client.get("/api/health").json()
    assert body["status"] == "ok_with_warnings"
    assert body["migration_warnings"] == 1
    # The database itself is still fine; this must not read as an outage.
    assert body["database"] == "ok"


def test_health_does_not_leak_the_message(client):
    """/api/health is public and the messages name tables and columns."""
    database.MIGRATION_ERRORS.append("migration step 3: column employees.ssn")
    assert "ssn" not in client.get("/api/health").text


def test_operator_can_read_the_actual_failures(superadmin):
    database.MIGRATION_ERRORS.append("migration step 3: column employees.ssn")
    body = superadmin.get("/api/superadmin/migration-warnings").json()
    assert body["count"] == 1
    assert body["warnings"] == ["migration step 3: column employees.ssn"]


def test_migration_warnings_require_an_operator(client):
    database.MIGRATION_ERRORS.append("migration step 3: something failed")
    assert client.get("/api/superadmin/migration-warnings").status_code == 401


def test_report_is_a_copy(client):
    """Callers must not be able to clear the record by mutating what they get."""
    database.MIGRATION_ERRORS.append("migration step 1: boom")
    database.migration_report().clear()
    assert len(database.MIGRATION_ERRORS) == 1
