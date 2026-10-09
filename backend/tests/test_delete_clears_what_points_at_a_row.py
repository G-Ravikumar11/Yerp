"""Deleting a person must not leave anything pointing at them.

SQLite lets a pointer to a deleted row stand; Postgres, which the live site runs on, refuses the delete. So these tests
look at the rows left behind rather than at the status code alone: on SQLite a delete that forgot a table still
answers 200, and only the leftovers give it away.
"""
import main
from app import models
from conftest import make_employee


def _db():
    return main.SessionLocal()


def test_deleting_an_employee_removes_their_own_records_and_unnames_them_elsewhere(tenant):
    emp = make_employee(tenant)
    with _db() as db:
        client_id = db.query(models.DBEmployee).get(emp["id"]).client_id
        job = models.DBJob(client_id=client_id, name="Tower C", manager_id=emp["id"])
        request = models.DBDocumentRequest(employee_id=emp["id"], name="PAN card")
        db.add_all([job, request])
        db.commit()
        job_id, request_id = job.id, request.id

    assert tenant.delete("/api/employees/%d" % emp["id"]).status_code == 200

    with _db() as db:
        assert db.query(models.DBDocumentRequest).get(request_id) is None, "a request addressed to them goes with them"
        kept = db.query(models.DBJob).get(job_id)
        assert kept is not None, "the job they managed is history and stays"
        assert kept.manager_id is None, "but it no longer names a person who has gone"


def test_removing_a_team_member_lets_go_of_their_invitations(tenant):
    with _db() as db:
        client_id = db.query(models.DBClient).order_by(models.DBClient.id.desc()).first().id
        member = models.DBTeamMember(client_id=client_id, email="gone@example.com", role="viewer")
        db.add(member)
        db.commit()
        reset = models.DBPasswordReset(member_id=member.id, token_hash="x" * 64, expires_at="2099-01-01 00:00:00", used_at="")
        db.add(reset)
        db.commit()
        member_id, reset_id = member.id, reset.id

    assert tenant.delete("/api/team/%d" % member_id).status_code == 200

    with _db() as db:
        assert db.query(models.DBTeamMember).get(member_id) is None
        left = db.query(models.DBPasswordReset).get(reset_id)
        assert left is None or left.member_id is None, "nothing may still point at the removed member"
        assert left is None or left.used_at, "and an invitation they had must be dead"
