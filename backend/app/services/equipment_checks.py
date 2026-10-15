"""The rules behind the equipment, extinguisher and electrical safety checklists."""
import json
from datetime import date, datetime

from fastapi import HTTPException

from app.constants.equipment_checks import ANSWERS, EQUIPMENT_CHECKS

SOON_DAYS = 7           # an inspection falling due within a week is flagged


def template_of(form_type):
    tpl = EQUIPMENT_CHECKS.get(form_type or "")
    if not tpl:
        raise HTTPException(400, "Which checklist: " + ", ".join(t["label"] for t in EQUIPMENT_CHECKS.values()))
    return tpl


def forms_catalogue():
    """The forms as the screen needs them: the items to answer, the readings and the sign-offs."""
    return [dict(tpl, key=key) for key, tpl in EQUIPMENT_CHECKS.items()]


def _day(text, what):
    try:
        return datetime.strptime((text or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s: a date as year-month-day." % what)


def clean_items(tpl, rows):
    """Every item answered Yes, No or N/A - except the optional ones - and nothing that is not on the form."""
    given = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("key") is not None:
            given[str(r["key"])] = r
    known = {i["key"] for i in tpl["items"]}
    extra = [k for k in given if k not in known]
    if extra:
        raise HTTPException(400, "Not on this checklist: %s." % ", ".join(extra))
    out, missing = [], []
    for item in tpl["items"]:
        r = given.get(item["key"]) or {}
        answer = (r.get("answer") or "").strip().lower()
        if answer and answer not in ANSWERS:
            raise HTTPException(400, "Item %s: answer Yes, No or N/A." % item["key"])
        if not answer and not item["optional"]:
            missing.append(item["key"])
        out.append({"key": item["key"], "answer": answer, "remarks": (r.get("remarks") or "").strip()[:300]})
    if missing:
        raise HTTPException(400, "Answer every item (Yes, No or N/A). Not answered: %s." % ", ".join(missing))
    return out


def clean_readings(tpl, readings):
    out = {}
    readings = readings if isinstance(readings, dict) else {}
    for spec in tpl["readings"]:
        raw = readings.get(spec["key"])
        try:
            value = float(raw) if raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            raise HTTPException(400, "%s: a number." % spec["label"])
        if value < 0:
            raise HTTPException(400, "%s cannot be negative." % spec["label"])
        out[spec["key"]] = value
    if tpl is EQUIPMENT_CHECKS["grinder"] and not (out["wheel_rpm"] > 0 and out["machine_rpm"] > 0):
        raise HTTPException(400, "Write down the rpm of the wheel and of the machine.")
    return out


def clean_signoffs(tpl, signoffs):
    roles = {s["role"] for s in tpl["signoffs"]}
    out = {}
    for role, v in (signoffs if isinstance(signoffs, dict) else {}).items():
        if role not in roles:
            raise HTTPException(400, "No such sign-off on this checklist: %s." % role)
        name = ((v or {}).get("name") or "").strip()[:120]
        if name:
            on = ((v or {}).get("date") or date.today().isoformat())[:10]
            _day(on, "Sign-off date")
            out[role] = {"name": name, "date": on}
    return out


def evaluate(tpl, items, readings):
    """What was found wrong: an item answered the faulty way, and a wheel rated slower than the machine that drives it."""
    by_key = {i["key"]: i for i in tpl["items"]}
    failed = []
    for r in items:
        spec = by_key.get(r["key"])
        if not spec or not r["answer"] or r["answer"] == "na":
            continue
        if (r["answer"] == "yes") == bool(spec["bad_if_yes"]):
            failed.append(r["key"])
    rpm_wrong = bool(readings.get("wheel_rpm") and readings.get("machine_rpm")
                     and readings["wheel_rpm"] < readings["machine_rpm"])
    return {"failed": failed, "rpm_wrong": rpm_wrong, "result": "fail" if failed or rpm_wrong else "pass"}


def _json(text, default):
    try:
        got = json.loads(text or "")
        return got if isinstance(got, type(default)) else default
    except (TypeError, ValueError):
        return default


def latest_ids(rows):
    """The newest inspection of each piece of equipment: a later one replaces an earlier when it comes to due dates."""
    newest = {}
    for c in rows:
        key = (c.job_id, c.form_type, (c.equipment_no or "").strip().lower())
        best = newest.get(key)
        if best is None or (c.inspection_date or "", c.id) > (best.inspection_date or "", best.id):
            newest[key] = c
    return {c.id for c in newest.values()}


def check_dict(c, files=(), current=False, project=""):
    tpl = EQUIPMENT_CHECKS.get(c.form_type) or {"items": [], "readings": [], "signoffs": [], "review": None,
                                                  "label": c.form_type, "title": c.form_type, "doc_ref": ""}
    answers = {r.get("key"): r for r in _json(c.items, [])}
    readings = _json(c.readings, {})
    items = []
    for spec in tpl["items"]:
        r = answers.get(spec["key"]) or {}
        photos = [{"id": f.id, "url": "/api/files/%d" % f.id, "thumb_url": "/api/files/%d/thumb" % f.id}
                  for f in files if f.attached_id == c.id and (f.caption or "") == "item:" + spec["key"]]
        items.append({"key": spec["key"], "label": spec["label"], "section": spec.get("section", ""),
                      "bad_if_yes": spec["bad_if_yes"], "optional": spec["optional"],
                      "answer": r.get("answer", ""), "remarks": r.get("remarks", ""), "photos": photos})
    ev = evaluate(tpl, [{"key": i["key"], "answer": i["answer"]} for i in items], readings)
    today = date.today()
    due_in, due_state = None, ""
    if c.next_inspection_date:
        try:
            due_in = (datetime.strptime(c.next_inspection_date[:10], "%Y-%m-%d").date() - today).days
        except ValueError:
            due_in = None
    if current and due_in is not None:
        due_state = "overdue" if due_in < 0 else ("soon" if due_in <= SOON_DAYS else "ok")
    return {"id": c.id, "job_id": c.job_id, "project": project, "number": c.number or "", "form_type": c.form_type,
            "form_label": tpl["label"], "doc_ref": tpl["doc_ref"], "equipment_no": c.equipment_no or "",
            "specs": c.specs or "", "location": c.location or "", "extinguisher_type": c.extinguisher_type or "",
            "board_type": c.board_type or "", "contractor_name": c.contractor_name or "",
            "inspection_date": c.inspection_date or "", "next_inspection_date": c.next_inspection_date or "",
            "items": items, "readings": readings, "signoffs": _json(c.signoffs, {}),
            "has_review": bool(tpl["review"]), "decision": c.decision or "", "decision_by": c.decision_by or "",
            "decision_on": c.decision_on or "", "recorded_by": c.recorded_by or "",
            "result": ev["result"], "failed": ev["failed"], "rpm_wrong": ev["rpm_wrong"],
            "photo_count": sum(len(i["photos"]) for i in items),
            "current": current, "due_in_days": due_in, "due_state": due_state}


def summarise(checks):
    current = [c for c in checks if c["current"]]
    return {"total": len(checks), "equipment": len(current),
            "failed": len([c for c in current if c["result"] == "fail"]),
            "overdue": len([c for c in current if c["due_state"] == "overdue"]),
            "due_soon": len([c for c in current if c["due_state"] == "soon"]),
            "awaiting_review": len([c for c in checks if c["has_review"] and not c["decision"]])}
