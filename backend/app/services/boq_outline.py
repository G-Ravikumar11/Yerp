"""The project BOQ as a work order takes it: the headings over every line, the text that goes with a heading, the grade,
and a contractor rate to start from - and the schedule laid out the way the sheet is.

A client's sheet nests its headings: PLAIN CEMENT CONCRETE, then REINFORCED CEMENT CONCRETE with Basement-02,
Basement-01 and Stilt under it. Where the sheet numbers its lines (I, 1, 2.1) the numbers say how deep a heading is.
Where it does not, the sheet's own habits do: a heading straight after another heading is under it, and a heading after
some priced lines is beside the heading above that is written the same way (in capitals, or not).
"""
import re

from app import models
from app.constants.boq import BOQ_PRICED, BOQ_NOT_LIVE
from app.core.currency import money, unit_rate
from app.services.boq import boq_of_job, boq_items_naming, boq_shares_of

NUMBERED = re.compile(r"^\d+(\.\d+)*$")
ROMAN = re.compile(r"^[IVXLC]+$")
# A grade as a BOQ writes it: a concrete grade (M10, M 25, M-60), a steel grade (Fe500, Fe 550D), or a mix (1:3:6).
CONCRETE_GRADE = re.compile(r"\bM\s?-?\s?(\d{2,3})\b")
STEEL_GRADE = re.compile(r"\bFe\s?-?\s?(\d{3}\s?D?)\b", re.I)
MIX = re.compile(r"\b(1\s?:\s?\d+(?:\.\d+)?\s?:\s?\d+(?:\.\d+)?)\b")
# Orders whose rates were agreed: a draft's rate is still somebody's guess.
COMMITTED = ("PROVISIONAL", "APPROVED", "EXECUTED", "CLOSED")


def boq_current_lines(db, client_id, job_id):
    """Every line of the project's BOQ as it stands - headings, notes and priced lines - in the sheet's order."""
    boq = boq_of_job(db, client_id, job_id) if job_id else None
    if boq is None:
        return []
    rev = db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq.id,
                                                models.DBBoqRevision.rev_no == boq.current_rev).first()
    if rev is None:
        return []
    return db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(
        models.DBBoqLine.display_order, models.DBBoqLine.id).all()


def _capitals(text):
    letters = [c for c in text or "" if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def boq_outline(lines):
    """The headings of a BOQ and where every line sits under them.

    Returns (heads, path, place): heads {section key: {key, description, item_no, group_code, level (0 a main heading),
    path (the headings above it), notes (the text written under it)}}, path {line key: [heading keys, outermost
    first]} for every heading and priced line, and place {line key: its position on the sheet}."""
    heads, path, place = {}, {}, {}
    stack = []                       # the headings open at this point, outermost first
    after_heading = False            # nothing priced since the last heading: the next heading is under it
    for at, l in enumerate(lines):
        place[l.key] = at
        if l.kind == "section":
            no = (l.item_no or "").strip().rstrip(".").strip()
            capitals = _capitals(l.description)
            if no and ROMAN.match(no):
                depth = 0
            elif no and NUMBERED.match(no):
                depth = no.count(".") + (1 if any(h["roman"] for h in stack) else 0)
            elif after_heading and stack:
                depth = stack[-1]["depth"] + 1
            elif stack:
                same = next((h for h in reversed(stack) if h["capitals"] == capitals), None)
                depth = same["depth"] if same else (0 if capitals else stack[-1]["depth"])
            else:
                depth = 0
            while stack and stack[-1]["depth"] >= depth:
                stack.pop()
            head = {"key": l.key, "description": (l.description or "").strip(), "item_no": no,
                    "group_code": l.group_code or "", "level": len(stack), "path": [h["key"] for h in stack],
                    "notes": [], "depth": depth, "capitals": capitals, "roman": bool(no and ROMAN.match(no))}
            heads[l.key] = head
            path[l.key] = head["path"]
            stack.append(head)
            after_heading = True
        elif l.kind == "note":
            text = (l.description or "").strip()
            if text and stack:
                stack[-1]["notes"].append(text)
                if not stack[-1]["group_code"] and l.group_code:
                    stack[-1]["group_code"] = l.group_code
        elif l.kind in BOQ_PRICED:
            path[l.key] = [h["key"] for h in stack]
            after_heading = False
    for h in heads.values():
        for k in ("depth", "capitals", "roman"):
            h.pop(k)
    return heads, path, place


def grade_in(text):
    """The grade a piece of BOQ text names, or nothing: M10 before a mix (the sheet says "Mix (1:3:6) or M10 grade")."""
    text = text or ""
    m = CONCRETE_GRADE.search(text)
    if m:
        return "M%s" % m.group(1)
    m = STEEL_GRADE.search(text)
    if m:
        return "Fe%s" % m.group(1).replace(" ", "").upper()
    m = MIX.search(text)
    return m.group(1).replace(" ", "") if m else ""


def line_materials(lines, heads, path):
    """{BOQ key: grade} for every priced line: its own Material, else what its description says, else what the
    nearest heading over it says (its name or the text under it). A line that names no grade anywhere has none."""
    out = {}
    for l in lines:
        if l.kind not in BOQ_PRICED:
            continue
        grade = (l.material or "").strip() or grade_in(l.description)
        for h in reversed(path.get(l.key, [])):
            if grade:
                break
            grade = grade_in(heads[h]["description"]) or grade_in(" ".join(heads[h]["notes"]))
        out[l.key] = grade
    return out


def last_given_rates(db, client_id, keys):
    """{BOQ key: the contractor rate it was last given at}, from orders whose rates were agreed - the newest first."""
    keys = {k for k in keys if k}
    if not keys:
        return {}
    rows = db.query(models.DBSubcontractItem, models.DBSubcontractOrder).join(
        models.DBSubcontractOrder, models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id).filter(
        models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractOrder.status.in_(COMMITTED),
        models.DBSubcontractOrder.status.notin_(BOQ_NOT_LIVE), models.DBSubcontractItem.is_header.isnot(True),
        boq_items_naming(db, keys)).order_by(models.DBSubcontractOrder.id.desc(), models.DBSubcontractItem.id).all()
    out = {}
    for it, _ in rows:
        if not it.unit_rate:
            continue
        for key, _share in boq_shares_of(it):
            if key in keys and key not in out:
                out[key] = unit_rate(it.unit_rate)
    return out


def rate_suggestions(db, client_id, job_id, keys):
    """{BOQ key: (rate, where it came from)} - a contractor rate to start from, which can be changed.

    The project's budget first: what one unit is planned to cost in labour and in plant and other (the part given out to
    a contractor, as against our own material). A line with no budget takes the rate it was last given at."""
    from app.services.budgeting import unit_costs
    keys = {k for k in keys if k}
    costs = unit_costs(db, client_id, job_id) if job_id else {}
    out = {}
    for k in keys:
        c = costs.get(k)
        rate = unit_rate((c["LABOUR"] + c["OTHER"])) if c else 0.0
        if rate > 0:
            out[k] = (rate, "budget")
    for k, rate in last_given_rates(db, client_id, keys - set(out)).items():
        out[k] = (rate, "last given")
    return out


def blended_rate(parts, suggestions):
    """One rate for lines added up as one: their suggested rates weighted by quantity. Nothing when none has one."""
    priced = [(q, suggestions[k][0]) for k, q in parts if k in suggestions and q > 0]
    if not priced:
        return 0.0, ""
    qty = sum(q for q, _ in priced)
    sources = {suggestions[k][1] for k, q in parts if k in suggestions and q > 0}
    return unit_rate(sum(q * r for q, r in priced) / qty), (sources.pop() if len(sources) == 1 else "mixed")


# --- the schedule laid out like the sheet --------------------------------------------------------------------------

def _is_header(r):
    return bool(r.get("is_header"))


def arrange_schedule(rows, heads, path, place, renumber=False, materials=None):
    """A work order's schedule in the BOQ's order, each line under its headings, numbered.

    `rows` are schedule lines as the screen holds them. A line from the BOQ goes where the sheet has it; a heading the
    BOQ has goes where the sheet has it, once, and is put in when a line under it is there without it; a line for a
    whole heading goes where that heading is; a line typed in by hand stays behind the line it was typed under. Blank
    activity numbers are filled in (1, 1.1, 1.1.1 by the headings), or all of them when `renumber` is asked for."""
    rows = [dict(r) for r in rows if (r.get("item_description") or "").strip()]
    for r in rows:                                       # a line from the BOQ with no grade on it takes the BOQ's
        if materials and not _is_header(r) and not (r.get("material") or "").strip():
            grades = {materials.get(p.get("key"), "") for p in r.get("boq_parts") or []} if r.get("boq_parts") else {materials.get(r.get("boq_key") or "", "")}
            r["material"] = grades.pop() if len(grades) == 1 else ""
    have = {r.get("boq_key") for r in rows if _is_header(r) and r.get("boq_key") in heads}
    wanted = []
    for r in rows:
        key = r.get("boq_key") or ""
        if _is_header(r):
            above = path.get(key, [])
        elif r.get("boq_parts"):
            above = heads[key]["path"] if key in heads else []
        else:
            above = path.get(key, [])
        for h in above:
            if h not in have:
                have.add(h)
                wanted.append(h)
    rows += [header_row(heads, h) for h in wanted]

    seen, kept, last = set(), [], -1.0
    for i, r in enumerate(rows):
        key = r.get("boq_key") or ""
        if _is_header(r) and key in heads:
            if key in seen:
                continue                                   # the same heading twice: once is enough
            seen.add(key)
            r["heading_level"] = heads[key]["level"] + 1
            spot = float(place[key])
        elif r.get("boq_parts"):
            spots = [place[p["key"]] for p in r["boq_parts"] if p.get("key") in place]
            spot = place[key] + 0.5 if key in place else (min(spots) - 0.5 if spots else last)
        elif key in place:
            spot = float(place[key])
        else:
            spot = last                                    # typed in by hand: stays behind the line above it
        last = spot
        kept.append((spot, i, r))
    out = [r for _, _, r in sorted(kept, key=lambda x: (x[0], x[1]))]
    # A line for a whole heading stands where that heading would: numbered beside the headings at its depth.
    for r in out:
        if r.get("boq_parts") and not _is_header(r) and (r.get("boq_key") or "") in heads:
            r["_level"] = heads[r["boq_key"]]["level"] + 1
    number_schedule(out, renumber)
    for r in out:
        r.pop("_level", None)
    return out


def make_cumulative(rows, heads, path, level=0, keep_grades=True, materials=None):
    """The schedule on screen with its BOQ lines added up per heading - at the main headings (level 0), the
    sub-headings (1) and so on - into one line each, per unit and (unless they are put together) per grade.

    Each line keeps the BOQ lines it adds up, so what is given against each is still counted; its rate is what the
    lines it replaces came to, divided by the quantity, so the order's value does not move - as an Excel abstract, every
    BOQ line under the heading goes into its line, even where there is only one. A line typed in by hand is left as it
    is. The heading a line now stands for is not repeated as a heading row above it."""
    materials = materials or {}
    out, groups = [], {}
    for r in rows:
        r = dict(r)
        if _is_header(r) or not (r.get("item_description") or "").strip():
            out.append(r)
            continue
        key = r.get("boq_key") or ""
        if r.get("boq_parts"):
            trail = (heads[key]["path"] + [key]) if key in heads else []
            parts = [(p["key"], float(p.get("qty") or 0)) for p in r["boq_parts"] if p.get("key")]
        elif key in path:
            trail = path[key]
            parts = [(key, float(r.get("quantity") or 0))]
        else:
            out.append(r)                                  # typed in by hand: not the BOQ's to add up
            continue
        if not trail:
            out.append(r)
            continue
        anchor = trail[min(level, len(trail) - 1)]
        grade = (r.get("material") or "").strip() or (materials.get(parts[0][0], "") if len(parts) == 1 else "")
        gid = (anchor, (r.get("uom") or "").strip().lower(), grade.lower() if keep_grades else "")
        if gid not in groups:
            groups[gid] = {"rows": [], "at": len(out)}
            out.append(gid)                                # the combined line goes where its first line was
        groups[gid]["rows"].append((r, parts, grade))
    result = []
    for item in out:
        if not isinstance(item, tuple):
            result.append(item)
            continue
        members = groups[item]["rows"]
        anchor, uom, _ = item
        qty = sum(float(r.get("quantity") or 0) for r, _, _ in members)
        value = sum(float(r.get("quantity") or 0) * float(r.get("unit_rate") or 0) for r, _, _ in members)
        merged = {}
        for _, parts, _ in members:
            for k, q in parts:
                merged[k] = merged.get(k, 0.0) + q
        grades = {g for _, _, g in members}
        grade = grades.pop() if len(grades) == 1 else ""
        first = members[0][0]
        budgets = {r.get("budget_id") for r, _, _ in members}
        result.append({
            "is_header": False, "boq_key": anchor, "boq_parts": [{"key": k, "qty": money(q)} for k, q in merged.items()],
            "item_description": heads[anchor]["description"] + ((" - " + grade) if keep_grades and grade else ""),
            "technical_spec": "\n".join(heads[anchor]["notes"]), "material": grade, "uom": first.get("uom") or "",
            "quantity": money(qty), "unit_rate": unit_rate(value / qty) if qty else 0.0, "activity_no": "",
            "item_code": "", "tolerance_percent": first.get("tolerance_percent") or 0,
            "budget_id": budgets.pop() if len(budgets) == 1 else first.get("budget_id"), "heading_level": 0})
    # The heading a line now stands for is not a heading row over it as well, and a BOQ heading with nothing left under
    # it goes too; a heading typed in by hand stays.
    under = {}
    for r in result:
        if not _is_header(r):
            key = r.get("boq_key") or ""
            for h in (heads[key]["path"] if r.get("boq_parts") and key in heads else path.get(key, [])):
                under[h] = under.get(h, 0) + 1
    return [r for r in result if not (_is_header(r) and r.get("boq_key") in heads and not under.get(r.get("boq_key")))]


def split_cumulative(rows, lines_by_key, materials=None):
    """Each line that adds up a heading put back as the BOQ lines it stands for, at its rate, each with its own
    quantity, grade and item code."""
    materials = materials or {}
    out = []
    for r in rows:
        if _is_header(r) or not r.get("boq_parts"):
            out.append(dict(r))
            continue
        for p in r["boq_parts"]:
            l = lines_by_key.get(p.get("key"))
            if l is None:
                continue
            out.append({"is_header": False, "boq_key": l.key, "boq_parts": [], "item_description": l.description,
                        "item_code": l.item_code or "", "activity_no": "", "technical_spec": l.remarks or "",
                        "material": materials.get(l.key, ""), "uom": l.uom or "", "quantity": money(p.get("qty") or 0),
                        "unit_rate": unit_rate(r.get("unit_rate") or 0), "tolerance_percent": r.get("tolerance_percent") or 0,
                        "budget_id": r.get("budget_id"), "heading_level": 0})
    return out


def header_row(heads, key):
    h = heads[key]
    return {"is_header": True, "boq_key": key, "item_description": h["description"], "activity_no": h["item_no"],
            "item_code": "", "technical_spec": "\n".join(h["notes"]), "uom": "", "quantity": 0, "unit_rate": 0,
            "material": "", "heading_level": h["level"] + 1, "boq_parts": []}


def number_schedule(rows, renumber=False):
    """Activity numbers by the headings: 1, 2 for main headings, 1.1 under them, and the lines numbered under the
    heading they are in - a line with no heading over it taking the next number beside the main headings. Only the
    blank ones, unless every line is to be numbered again."""
    counts, open_level = [], 0
    for r in rows:
        if _is_header(r):
            level = max(1, int(r.get("heading_level") or 1))
        elif r.get("_level"):
            level = int(r["_level"])                       # a heading added up as one line
        else:
            level = open_level + 1
        counts = counts[:level]
        while len(counts) < level:
            counts.append(0)
        counts[-1] += 1
        if _is_header(r):
            open_level = level
        elif r.get("_level"):
            open_level = level - 1                         # it closes the headings at its depth and below
        if renumber or not (r.get("activity_no") or "").strip():
            r["activity_no"] = ".".join(str(n) for n in counts)
    return rows


def schedule_row_out(r):
    """A schedule line as the screen takes it back."""
    return {"activity_no": r.get("activity_no") or "", "item_code": r.get("item_code") or "",
            "item_description": r.get("item_description") or "", "technical_spec": r.get("technical_spec") or "",
            "uom": r.get("uom") or "", "quantity": money(r.get("quantity") or 0), "unit_rate": unit_rate(r.get("unit_rate") or 0),
            "tolerance_percent": r.get("tolerance_percent") or 0, "budget_id": r.get("budget_id"),
            "is_header": _is_header(r), "boq_key": r.get("boq_key") or "", "boq_parts": r.get("boq_parts") or [],
            "material": r.get("material") or "", "heading_level": int(r.get("heading_level") or 0),
            "rate_from": r.get("rate_from") or ""}
