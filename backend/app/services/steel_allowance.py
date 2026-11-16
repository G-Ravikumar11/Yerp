"""Steel wastage: a project may draw its approved bar bending schedule's steel, diameter by diameter, plus an allowance
(2% unless the company sets another). An issue that takes a diameter past that is not refused - the site may need it - but
it cannot go straight out: it waits for approval by the Master or an engineer who signs off the schedule, who says why.

    allowed  = BBS weight (approved entries, kg) x (1 + allowance %)
    issued   = steel issued to the project, net of returns: the Store Hub's ledger and the old store's movements
    wastage  = issued - BBS weight, in kg and as a share of the BBS

Steel items are recognised from the item master by name: TMT, rebar, reinforcement, steel or Fe-grade with a diameter in mm
(8, 10, 12, 16 ...), or by an item category that says steel.

Every steel quantity becomes kilograms in ONE place, `weigh`:
    kg, kgs, kilogram ...   the quantity as it is
    MT, tonne, quintal ...  the quantity x 1000 (x 100), once
    Numbers (Nos, pcs ...)  the number of pieces x the item's weight per piece (Item Master, kg per piece)
A steel item that cannot be turned into kilograms - counted in numbers with no weight per piece (or a zero or negative one), or in
a unit with no weight - is never skipped and never assumed: it is reported, by name, id and unit, as a problem, a store issue
carrying it is refused, and the schedule cannot be approved while steel issued to the project cannot be weighed. A project with no
approved schedule is not checked: there is nothing to check against, and the reconciliation says so.
"""
import re
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app import models
from app.core.tenant_settings import tenant_setting
from app.core.units import canonical_unit

SETTING = "steel_wastage_pct"
DEFAULT_PCT = 2.0
DIAMETERS = (6, 8, 10, 12, 16, 20, 25, 28, 32, 36, 40)
STEEL_WORDS = re.compile(r"\b(tmt|rebar|reinforce\w*|steel|fe\s?-?\s?\d{3}\w*|tor\s?steel|hysd|bar|bars)\b", re.I)
DIA = re.compile(r"(?<!\d)(\d{1,2})\s*(?:mm|ø|dia\b|#)", re.I)
TO_KG = {"kg": 1.0, "kgs": 1.0, "kilogram": 1.0, "kilograms": 1.0, "mt": 1000.0, "t": 1000.0, "ton": 1000.0, "tons": 1000.0,
         "tonne": 1000.0, "tonnes": 1000.0, "metric ton": 1000.0, "qtl": 100.0, "quintal": 100.0, "quintals": 100.0}
APPROVE_RIGHT = "site.signoff"          # who signs off a bar bending schedule

# What a steel item's weight can be: how `weigh` ended.
WEIGHED, MISSING_WEIGHT, UNSUPPORTED_UNIT, CALC_ERROR = "WEIGHED", "MISSING_WEIGHT_PER_PIECE", "UNSUPPORTED_UNIT", "WEIGHT_CALCULATION_ERROR"
STATUS_LABEL = {WEIGHED: "Weighed", MISSING_WEIGHT: "Missing weight per piece", UNSUPPORTED_UNIT: "Unsupported unit", CALC_ERROR: "Weight calculation error"}
MAX_PIECE_KG = Decimal("100000")        # one piece of steel above this is a slip of the pen, not a bar
MISSING_TEXT = "Weight per piece is missing for this steel item. Update the item master to continue BBS weight validation."


def allowance_pct(db, client_id) -> float:
    try:
        return max(0.0, float(tenant_setting(db, client_id, SETTING, str(DEFAULT_PCT)) or DEFAULT_PCT))
    except (TypeError, ValueError):
        return DEFAULT_PCT


def diameter_of(item) -> int:
    """The bar diameter of a steel item, 0 when it is not reinforcement steel."""
    text = " ".join(x or "" for x in (item.item_name, item.description, item.segment, getattr(item, "category", "")))
    if not STEEL_WORDS.search(text):
        return 0
    for m in DIA.finditer(text):
        d = int(m.group(1))
        if d in DIAMETERS:
            return d
    return 0


def is_steel(item) -> bool:
    """A material that is steel: reinforcement steel with a bar diameter, or filed under a category that says steel. A work item (FG) is
    never a stock of steel, whatever it is called."""
    if getattr(item, "kind", "RM") != "RM":
        return False
    return bool(diameter_of(item)) or "steel" in (getattr(item, "item_category", "") or "").lower()


def kg_per(uom) -> float:
    return TO_KG.get((uom or "").strip().lower().rstrip("."), 0.0)


def is_piece_unit(uom) -> bool:
    """Counted in numbers: Nos, Numbers, pcs, each ... as the unit list spells it."""
    return canonical_unit(uom, "") == "Nos"


def clean_piece_weight(value):
    """(weight, problem) for a weight per piece as entered: a number above zero and not absurd, kept to four places. Nothing entered is (None, '')."""
    if value is None or str(value).strip() == "":
        return None, ""
    try:
        w = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None, "Weight per piece is not a number."
    if not w.is_finite():
        return None, "Weight per piece is not a number."
    if w <= 0:
        return None, "Weight per piece must be more than zero."
    if w > MAX_PIECE_KG:
        return None, "Weight per piece is more than 100,000 kg."
    w = w.quantize(Decimal("0.0001"))
    if w <= 0:
        return None, "Weight per piece is too small: at least 0.0001 kg."
    return w, ""


def piece_weight(item):
    """The item's weight per piece as a Decimal above zero, or None when it has none (or one that makes no sense)."""
    w, why = clean_piece_weight(getattr(item, "weight_per_piece_kg", None))
    return None if why else w


def weigh(item, qty, uom):
    """(kilograms as a Decimal or None, status, why) for `qty` of a steel item counted in `uom`.
    Never guesses: what cannot be turned into kilograms comes back as None with the reason, never as zero."""
    try:
        q = Decimal(str(qty if qty is not None else 0))
    except (InvalidOperation, ValueError):
        return None, CALC_ERROR, "The quantity %r is not a number." % (qty,)
    if not q.is_finite():
        return None, CALC_ERROR, "The quantity %r is not a number." % (qty,)
    unit = (uom or "").strip()
    factor = kg_per(unit)
    if factor:
        return q * Decimal(str(factor)), WEIGHED, ""
    if is_piece_unit(unit):
        w = piece_weight(item)
        if w is None:
            raw = getattr(item, "weight_per_piece_kg", None)
            return None, MISSING_WEIGHT, MISSING_TEXT if raw is None else "Weight per piece (%s kg) is not above zero. Update the item master to continue BBS weight validation." % raw
        return q * w, WEIGHED, ""
    return None, UNSUPPORTED_UNIT, "The unit %s cannot be turned into kilograms: use kg or MT, or Numbers with a weight per piece set in the item master." % (unit or "(none)")


def kg_of(item, qty, uom):
    """Kilograms as a float for the places that add weights up, or None when it cannot be weighed."""
    kg, _status, _why = weigh(item, qty, uom)
    return None if kg is None else float(kg)


def bbs_kg(db, client_id, job_id):
    """{diameter: kg} on the project's approved schedule."""
    out = {}
    for e in db.query(models.DBBbsEntry).filter(models.DBBbsEntry.client_id == client_id, models.DBBbsEntry.job_id == job_id,
                                                models.DBBbsEntry.status == "Approved").all():
        d = int(round(e.diameter_mm or 0))
        out[d] = out.get(d, 0.0) + (e.num_bars or 0) * (e.cutting_length_mm or 0) / 1000.0 * (e.diameter_mm or 0) ** 2 / 162.0
    return out


def _base_uoms(db, ids):
    from app.models.store_core import DBStoreItemSettings
    return {s.item_id: s.base_uom for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(list(ids) or [0])).all()}


def issued_detail(db, client_id, job_id):
    """({diameter: kg} issued to the project net of returns, [one line per steel item and unit]). A line: item_id, item_code, item_name,
    diameter_mm, unit, quantity, weight_per_piece_kg (for a count), total_kg (None when it cannot be weighed), status, reason."""
    from app.services.store_integration import material_cost_rows
    hub = {}
    for _p, _h, _w, _b, item_id, qty, _v in material_cost_rows(db, client_id, project_id=job_id):
        hub[item_id] = hub.get(item_id, Decimal(0)) + qty
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(hub) or [0])).all()}
    base = _base_uoms(db, hub)
    out, lines = {}, {}

    def take(it, qty, unit):
        d = diameter_of(it)
        if not d:
            return
        kg, status, why = weigh(it, qty, unit)
        line = lines.setdefault((it.id, unit), {"item_id": it.id, "item_code": it.item_code, "item_name": it.item_name, "diameter_mm": d, "unit": unit,
                                                "quantity": 0.0, "weight_per_piece_kg": float(piece_weight(it)) if piece_weight(it) is not None and is_piece_unit(unit) else None,
                                                "total_kg": 0.0, "status": WEIGHED, "reason": ""})
        line["quantity"] += float(qty)
        if kg is None:
            line["status"], line["reason"], line["total_kg"] = status, why, None
        else:
            if line["total_kg"] is not None:
                line["total_kg"] += float(kg)
            out[d] = out.get(d, 0.0) + float(kg)
    for item_id, qty in hub.items():
        it = items.get(item_id)
        if it is not None:
            take(it, qty, base.get(item_id) or it.units_of_measure)
    # The old store, before it was moved into the Hub: issues are written as negative quantities, returns positive.
    by_code = {}
    for code, qty in db.query(models.DBStockMovement.item_code, models.DBStockMovement.quantity).filter(
            models.DBStockMovement.client_id == client_id, models.DBStockMovement.job_id == job_id,
            models.DBStockMovement.kind.in_(("ISSUE", "RETURN"))).all():
        by_code[code] = by_code.get(code, 0.0) - (qty or 0)
    for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.item_code.in_(list(by_code) or [""])).all():
        take(it, by_code.get(it.item_code, 0.0), it.units_of_measure)
    # A steel item issued and sent all back has nothing to weigh and nothing to correct.
    lines = [l for l in lines.values() if l["quantity"] != 0 or l["status"] == WEIGHED]
    return out, sorted(lines, key=lambda l: (l["diameter_mm"], l["item_name"] or ""))


def weight_problems(db, client_id, job_id):
    """The steel issued to the project (net of returns) that cannot be weighed, each with what is wrong: the reason an issue of it is refused and the schedule is
    not approved. [] when every steel item issued can be weighed."""
    _kg, lines = issued_detail(db, client_id, job_id)
    return [l for l in lines if l["status"] != WEIGHED and l["quantity"] > 0]


def problem_words(l) -> str:
    return "%s (item %s, %s, unit %s): %s" % (l["item_name"], l["item_id"], l["item_code"], l["unit"] or "none", l["reason"])


def issued_kg(db, client_id, job_id):
    """({diameter: kg} issued to the project net of returns, [names of steel items that could not be weighed])."""
    out, lines = issued_detail(db, client_id, job_id)
    return out, sorted({l["item_name"] for l in lines if l["status"] != WEIGHED and l["quantity"] > 0})


def reconciliation(db, client_id, job_id):
    pct = allowance_pct(db, client_id)
    need = bbs_kg(db, client_id, job_id)
    used, lines = issued_detail(db, client_id, job_id)
    problems = [l for l in lines if l["status"] != WEIGHED and l["quantity"] > 0]
    rows = []
    for d in sorted(set(need) | set(used)):
        b, u = need.get(d, 0.0), used.get(d, 0.0)
        allowed = b * (1 + pct / 100.0)
        rows.append({"diameter_mm": d, "bbs_kg": round(b, 1), "allowed_kg": round(allowed, 1), "issued_kg": round(u, 1),
                     "wastage_kg": round(u - b, 1), "wastage_pct": round((u - b) / b * 100, 2) if b else None,
                     "status": "OVER" if u > allowed + 0.05 else ("NOT_IN_BBS" if not b else "OK")})
    return {"allowance_pct": pct, "checked": bool(need), "rows": rows,
            # Steel that cannot be weighed is never left out quietly: `blocked` says the check is incomplete, `problems` says why item by item,
            # and `unweighed` (names only) is what the page showed before.
            "items": lines, "problems": problems, "blocked": bool(problems), "unweighed": sorted({l["item_name"] for l in problems}),
            "summary": {"bbs_kg": round(sum(need.values()), 1), "issued_kg": round(sum(used.values()), 1),
                        "wastage_kg": round(sum(used.values()) - sum(need.values()), 1),
                        "over": [r["diameter_mm"] for r in rows if r["status"] == "OVER"]}}


def refuse_unweighable(db, client_id, job_id, item, qty, uom):
    """A steel item that cannot be weighed does not go to a project whose schedule is approved: its weight would be missing from what the
    schedule is checked against. 409, naming the item, its id and unit and what is missing. Nothing for a project with no approved schedule."""
    if not job_id or not diameter_of(item):
        return
    kg, status, why = weigh(item, qty, uom)
    if kg is not None or not bbs_kg(db, client_id, job_id):
        return
    raise HTTPException(409, "%s (item %s, unit %s) cannot be weighed, so it cannot be issued to a project with an approved bar bending schedule: %s"
                        % (item.item_name, item.id, (uom or item.units_of_measure or "none"), why))


def issue_breaches(db, client_id, issue, lines) -> list:
    """A Store Hub issue: its lines are in each item's base unit."""
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    base = _base_uoms(db, items)
    picks = [(items[l.item_id], float(l.qty or 0), base.get(l.item_id) or items[l.item_id].units_of_measure) for l in lines if l.item_id in items]
    return breaches(db, client_id, issue.project_id, picks)


def breaches(db, client_id, job_id, picks) -> list:
    """What issuing these [(item, quantity, unit)] to the project would take past the allowance, in words, diameter by
    diameter; [] when it stays inside it or the project has no approved schedule to check against. Counted on top of what
    has gone out already, as if this were posted. Steel that cannot be weighed is in the answer too - it cannot be checked, so it cannot pass."""
    need = bbs_kg(db, client_id, job_id) if job_id else {}
    if not need:
        return []
    adding, unweighable = {}, []
    for it, qty, uom in picks:
        d = diameter_of(it)
        if not d:
            continue
        kg, status, why = weigh(it, qty, uom)
        if kg is None:
            unweighable.append("%s (item %s, unit %s) cannot be checked against the BBS: %s" % (it.item_name, it.id, uom or "none", why))
        else:
            adding[d] = adding.get(d, 0.0) + float(kg)
    if not adding:
        return unweighable
    pct = allowance_pct(db, client_id)
    used, _ = issued_kg(db, client_id, job_id)
    out = []
    for d, kg in sorted(adding.items()):
        b = need.get(d, 0.0)
        allowed = b * (1 + pct / 100.0)
        after = used.get(d, 0.0) + kg
        if after > allowed + 0.05:
            if b:
                out.append("%d mm: %s kg with this issue, against %s kg in the BBS + %g%% (%s kg allowed)" % (
                    d, _kg(after), _kg(b), pct, _kg(allowed)))
            else:
                out.append("%d mm: %s kg with this issue, and none of it in the approved BBS" % (d, _kg(after)))
    return unweighable + out


def _kg(v):
    return "{:,.0f}".format(v) if v >= 100 else "{:,.1f}".format(v)


def may_approve(actor) -> bool:
    """The Master, or an engineer who signs off the bar bending schedule. The storekeeper's own approval is not enough."""
    if actor.employee is None:
        return True
    from app.core.permissions import permissions_for
    return APPROVE_RIGHT in permissions_for(actor.employee)
