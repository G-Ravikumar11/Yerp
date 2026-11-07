"""Steel wastage: a project may draw its approved bar bending schedule's steel, diameter by diameter, plus an allowance
(2% unless the company sets another). An issue that takes a diameter past that is not refused - the site may need it - but
it cannot go straight out: it waits for approval by the Master or an engineer who signs off the schedule, who says why.

    allowed  = BBS weight (approved entries, kg) x (1 + allowance %)
    issued   = steel issued to the project, net of returns: the Store Hub's ledger and the old store's movements
    wastage  = issued - BBS weight, in kg and as a share of the BBS

Steel items are recognised from the item master by name: TMT, rebar, reinforcement, steel or Fe-grade with a diameter in mm
(8, 10, 12, 16 ...). Quantities in tonnes or quintals are turned into kg; a steel item counted in numbers (bars) cannot be
weighed and is said so rather than guessed. A project with no approved schedule is not checked: there is nothing to check
against, and the reconciliation says so.
"""
import re
from decimal import Decimal

from app import models
from app.core.tenant_settings import tenant_setting

SETTING = "steel_wastage_pct"
DEFAULT_PCT = 2.0
DIAMETERS = (6, 8, 10, 12, 16, 20, 25, 28, 32, 36, 40)
STEEL_WORDS = re.compile(r"\b(tmt|rebar|reinforce\w*|steel|fe\s?-?\s?\d{3}\w*|tor\s?steel|hysd|bar|bars)\b", re.I)
DIA = re.compile(r"(?<!\d)(\d{1,2})\s*(?:mm|ø|dia\b|#)", re.I)
TO_KG = {"kg": 1.0, "kgs": 1.0, "kilogram": 1.0, "kilograms": 1.0, "mt": 1000.0, "t": 1000.0, "ton": 1000.0, "tons": 1000.0,
         "tonne": 1000.0, "tonnes": 1000.0, "metric ton": 1000.0, "qtl": 100.0, "quintal": 100.0, "quintals": 100.0}
APPROVE_RIGHT = "site.signoff"          # who signs off a bar bending schedule


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


def kg_per(uom) -> float:
    return TO_KG.get((uom or "").strip().lower().rstrip("."), 0.0)


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


def issued_kg(db, client_id, job_id):
    """({diameter: kg} issued to the project net of returns, [steel items that could not be weighed])."""
    from app.services.store_integration import material_cost_rows
    hub = {}
    for _p, _h, _w, _b, item_id, qty, _v in material_cost_rows(db, client_id, project_id=job_id):
        hub[item_id] = hub.get(item_id, Decimal(0)) + qty
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(hub) or [0])).all()}
    base = _base_uoms(db, hub)
    out, unweighed = {}, set()
    for item_id, qty in hub.items():
        it = items.get(item_id)
        d = diameter_of(it) if it else 0
        if not d:
            continue
        f = kg_per(base.get(item_id) or it.units_of_measure)
        if not f:
            unweighed.add(it.item_name)
            continue
        out[d] = out.get(d, 0.0) + float(qty) * f
    # The old store, before it was moved into the Hub: issues are written as negative quantities, returns positive.
    by_code = {}
    for code, qty in db.query(models.DBStockMovement.item_code, models.DBStockMovement.quantity).filter(
            models.DBStockMovement.client_id == client_id, models.DBStockMovement.job_id == job_id,
            models.DBStockMovement.kind.in_(("ISSUE", "RETURN"))).all():
        by_code[code] = by_code.get(code, 0.0) - (qty or 0)
    for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.item_code.in_(list(by_code) or [""])).all():
        d = diameter_of(it)
        if not d:
            continue
        f = kg_per(it.units_of_measure)
        if not f:
            unweighed.add(it.item_name)
            continue
        out[d] = out.get(d, 0.0) + by_code.get(it.item_code, 0.0) * f
    return out, sorted(unweighed)


def reconciliation(db, client_id, job_id):
    pct = allowance_pct(db, client_id)
    need = bbs_kg(db, client_id, job_id)
    used, unweighed = issued_kg(db, client_id, job_id)
    rows = []
    for d in sorted(set(need) | set(used)):
        b, u = need.get(d, 0.0), used.get(d, 0.0)
        allowed = b * (1 + pct / 100.0)
        rows.append({"diameter_mm": d, "bbs_kg": round(b, 1), "allowed_kg": round(allowed, 1), "issued_kg": round(u, 1),
                     "wastage_kg": round(u - b, 1), "wastage_pct": round((u - b) / b * 100, 2) if b else None,
                     "status": "OVER" if u > allowed + 0.05 else ("NOT_IN_BBS" if not b else "OK")})
    return {"allowance_pct": pct, "checked": bool(need), "rows": rows, "unweighed": unweighed,
            "summary": {"bbs_kg": round(sum(need.values()), 1), "issued_kg": round(sum(used.values()), 1),
                        "wastage_kg": round(sum(used.values()) - sum(need.values()), 1),
                        "over": [r["diameter_mm"] for r in rows if r["status"] == "OVER"]}}


def issue_breaches(db, client_id, issue, lines) -> list:
    """A Store Hub issue: its lines are in each item's base unit."""
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    base = _base_uoms(db, items)
    picks = [(items[l.item_id], float(l.qty or 0), base.get(l.item_id) or items[l.item_id].units_of_measure) for l in lines if l.item_id in items]
    return breaches(db, client_id, issue.project_id, picks)


def breaches(db, client_id, job_id, picks) -> list:
    """What issuing these [(item, quantity, unit)] to the project would take past the allowance, in words, diameter by
    diameter; [] when it stays inside it or the project has no approved schedule to check against. Counted on top of what
    has gone out already, as if this were posted."""
    need = bbs_kg(db, client_id, job_id) if job_id else {}
    if not need:
        return []
    adding = {}
    for it, qty, uom in picks:
        d = diameter_of(it)
        f = kg_per(uom) if d else 0.0
        if d and f:
            adding[d] = adding.get(d, 0.0) + qty * f
    if not adding:
        return []
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
    return out


def _kg(v):
    return "{:,.0f}".format(v) if v >= 100 else "{:,.1f}".format(v)


def may_approve(actor) -> bool:
    """The Master, or an engineer who signs off the bar bending schedule. The storekeeper's own approval is not enough."""
    if actor.employee is None:
        return True
    from app.core.permissions import permissions_for
    return APPROVE_RIGHT in permissions_for(actor.employee)
