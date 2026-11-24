"""A client's sheet that heads a factor column "Material" (0.028, 0.0357 ...) does not give the BOQ those numbers as grades."""
from app import db as database
from app import models
from app.constants.boq import boq_grade
from app.core.lifecycle import clear_number_grades


def test_a_bare_decimal_is_not_a_grade_but_a_real_one_is_kept():
    for number in ("0.028", " 0.0357 ", ".5", "0.03%", "-0.1"):
        assert boq_grade(number) == "", number
    for grade in ("M25", "Fe500", "OPC 53", "1:2:4", "M 7.5", "43", "  M30  "):
        assert boq_grade(grade) == grade.strip(), grade


def test_numbers_already_kept_as_grades_are_cleared_and_real_grades_stay(tenant):
    job = tenant.post("/api/jobs", json={"name": "Grade test", "customer_name": "L&T"}).json()
    boq = tenant.post("/api/boqs", json={"job_id": job["id"]})
    assert boq.status_code == 200, boq.text
    boq_id = boq.json().get("id") or boq.json()["boq"]["id"]
    with database.SessionLocal() as db:
        rev = db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq_id).first()
        for i, (key, grade) in enumerate((("a", "0.028"), ("b", "M25"), ("c", " Fe500 "))):
            db.add(models.DBBoqLine(boq_id=boq_id, revision_id=rev.id if rev else None, key=key, kind="item",
                                    description="Line " + key, uom="cum", quantity=1, rate=1, amount=1,
                                    material=grade, display_order=i))
        db.commit()
    clear_number_grades()
    with database.SessionLocal() as db:
        got = {l.key: l.material for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.boq_id == boq_id).all()}
    assert got == {"a": "", "b": "M25", "c": " Fe500 "}
