"""The app must start even when the database will not answer.

Production went down with a 502 on every page. The cause was not a bad
query: start-up called ensure_super_admin() outside the try that guarded
the other steps, so a database that could not be reached raised there, the
lifespan never finished, the server never began listening, and the platform
had nothing to route to. Nothing on the page said why.

Start-up is now survivable step by step. The process listens, static pages
serve, and the health check says plainly that the database is the problem -
which is what takes the instance out of rotation and what somebody reads
when they go looking.
"""
import main


def test_every_start_up_step_is_survivable():
    """No step may take the process down - including the last one."""
    def explode():
        raise RuntimeError("database is asleep")
    assert main._boot_step("super admin", explode) is False
    assert "super admin" in main.DB_READY["error"]
    assert "asleep" in main.DB_READY["error"]


def test_a_step_that_works_reports_so():
    assert main._boot_step("create tables", lambda: None) is True


def test_the_health_check_takes_no_database_dependency():
    """The one endpoint whose job is to report the database is down must not
    be the one endpoint the database takes down with it."""
    import inspect
    assert not inspect.signature(main.health_check).parameters


def test_the_health_check_answers_503_when_the_database_is_unreachable(client, monkeypatch):
    from sqlalchemy import create_engine
    dead = create_engine("postgresql://nobody:nothing@127.0.0.1:1/none")
    monkeypatch.setattr(main, "engine", dead)
    res = client.get("/api/health")
    assert res.status_code == 503
    assert res.json()["database"] == "unavailable"
    assert res.json()["detail"]


def test_the_health_check_is_ok_when_the_database_answers(client):
    main.DB_READY["ok"] = True
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["database"] == "ok"


def test_a_half_finished_start_up_is_not_healthy(client):
    """Reachable is not the same as ready."""
    main.DB_READY["ok"] = False
    main.DB_READY["error"] = "admin user: boom"
    try:
        res = client.get("/api/health")
        assert res.status_code == 503
        assert "start-up did not finish" in res.json()["database"]
    finally:
        main.DB_READY["ok"] = True
        main.DB_READY["error"] = ""
