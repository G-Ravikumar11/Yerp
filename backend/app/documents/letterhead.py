"""The company block, parties' particulars, terms and signatures printed on every document."""
import json
import re

from app import models

from app.core.gst import GST_STATES, state_from_gstin
from app.core.tenant_settings import tenant_setting


def company_address(db, client):
    """The company's address: the record, else what Settings holds (companies
    that saved it there before Settings wrote through to the record)."""
    if client and (client.address or "").strip():
        return client.address
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client.id,
                                             models.DBSettings.key == "company_address").first() if client else None
    return (row.value if row else "") or ""


def our_party(db, client_id):
    c = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not c:
        return {}
    return {"name": c.company_name or "", "gstin": c.gstin or "",
            "address": company_address(db, c), "phone": c.phone_number or "",
            "email": c.email or "", "logo_url": c.logo_url or ""}


DOC_SIGNATORIES = (("prepared", "Prepared By", "QS"), ("proposed", "Proposed By", "GM"),
                   ("recommended", "Recommended By", "Project Coordinator"),
                   ("authorised", "Authorized Signatory", ""))


def doc_signatories(db, client_id):
    """{key: {"role", "name", "title"}} - who signs the company's documents."""
    got = {s.key: s.value or "" for s in db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client_id,
        models.DBSettings.key.like("sig_%")).all()}
    return {key: {"role": role, "name": got.get("sig_%s_name" % key, ""),
                  "title": got.get("sig_%s_title" % key, title),
                  "image": got.get("sig_%s_image" % key, "")}
            for key, role, title in DOC_SIGNATORIES}


def doc_seal(db, client_id):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id,
                                             models.DBSettings.key == "doc_seal_image").first()
    return (row.value or "") if row else ""


def _sig_line(s):
    return " ".join(x for x in (s.get("name", ""), "(%s)" % s["title"] if s.get("title") else "") if x)


def _state_line(gstin):
    code = state_from_gstin(gstin or "")
    return ("%s - %s" % (code, GST_STATES.get(code, ""))).strip(" -") if code else ""


def _company_box(db, unit, client):
    return {"name": unit.get("name") or client.company_name or "",
            "address": unit.get("address") or company_address(db, client),
            "gstin": unit.get("gstin") or client.gstin or "",
            "pan": unit.get("pan") or "", "state": _state_line(unit.get("gstin") or client.gstin),
            "logo_url": unit.get("logo_url") or client.logo_url or ""}


def letterhead(db, client, unit_id=None):
    """The company block at the top of every document: the issuing business
    unit's letterhead where one is named, else the company's own unit, with
    anything left blank on it taken from the company's settings. The PAN is
    read out of the GSTIN when it was not typed separately."""
    units = db.query(models.DBBusinessUnit).filter(models.DBBusinessUnit.client_id == client.id).all()
    unit = next((u for u in units if unit_id and u.id == unit_id), None) or \
        next((u for u in units if norm_name(u.name) == norm_name(client.company_name or "")), None) or \
        (units[0] if len(units) == 1 else None)
    gstin = ((unit.gstin if unit else "") or client.gstin or "").strip().upper()
    pan = ((unit.pan if unit else "") or "").strip().upper() or (gstin[2:12] if len(gstin) == 15 else "")
    return {"name": (unit.name if unit else "") or client.company_name or "",
            "code": (unit.code if unit else "") or "",
            "address": (unit.address if unit else "") or company_address(db, client),
            "gstin": gstin, "pan": pan, "state": _state_line(gstin),
            "logo_url": (unit.logo_url if unit else "") or client.logo_url or ""}


def party_facts(gstin, pan, state=""):
    """PAN, GSTIN and state for a party box, the PAN read from the GSTIN
    when it is not on file separately."""
    gstin = (gstin or "").strip().upper()
    pan = (pan or "").strip().upper() or (gstin[2:12] if len(gstin) == 15 else "")
    code = state_from_gstin(gstin) if gstin else ""
    state = ("%s - %s" % (code, GST_STATES.get(code, ""))).strip(" -") if code else (state or "")
    return [("PAN No", pan), ("GSTIN No.", gstin), ("State", state)]


def party_card(db, client_id, name):
    """Whoever a statement is for, looked up by name among the gangs, the
    suppliers and the customers, with what is on file about them."""
    key = norm_name(name or "")
    for con in db.query(models.DBContractor).filter(models.DBContractor.client_id == client_id).all():
        if norm_name(con.company_name) == key:
            return {"address": con.address or "", "gstin": con.gst_number or "", "pan": con.pan or "",
                    "contact": con.contact_person or "", "phone": con.phone_number or ""}
    for sup in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client_id).all():
        if norm_name(sup.name) == key:
            return {"address": sup.address or "", "gstin": sup.gstin or "", "pan": sup.pan or "",
                    "contact": sup.contact_person or "", "phone": sup.phone or ""}
    for c in db.query(models.DBContact).filter(models.DBContact.client_id == client_id).all():
        if norm_name(c.name) == key:
            return customer_card(c)
    return {}


def customer_card(c):
    if not c:
        return {}
    address = "\n".join(x for x in ((c.address or "").strip(),
                                    ", ".join(y for y in ((c.city or "").strip(), (c.pincode or "").strip()) if y)) if x)
    return {"name": c.name or "", "address": address, "gstin": c.gstin or "", "pan": getattr(c, "pan", "") or "",
            "state": c.state or "", "contact": c.contact_person or "", "phone": c.phone_number or "",
            "email": c.email or ""}


def jurisdiction_city(address, gstin=""):
    """The town the courts are in, read from the letterhead: the place named
    on the line with the PIN code, else the state from the GSTIN."""
    states = {v.lower() for v in GST_STATES.values()}
    for line in (address or "").splitlines()[::-1] + [(address or "").replace("\n", ", ")]:
        m = re.search(r"^(.*?)[\s,\-]*\b\d{3}\s?\d{3}\b", line)
        if not m:
            continue
        # The last place named before the PIN: the town, not the street.
        for part in [p.strip(" .-") for p in m.group(1).split(",")][::-1]:
            if part and part.lower() not in states and not re.search(r"\d", part):
                return part
    code = state_from_gstin(gstin or "")
    return GST_STATES.get(code, "") if code else ""


def fill_terms(text, company):
    """A condition written for any company, made this company's."""
    short = company.get("code") or company.get("name") or "the Company"
    city = jurisdiction_city(company.get("address"), company.get("gstin")) or "the registered office of the Company"
    return (text or "").replace("{company}", short).replace("{city}", city)


def _company_of(db, client):
    return letterhead(db, client)


def company_terms(db, client_id, fallback=True):
    """The company's own general conditions, else the standard list."""
    raw = tenant_setting(db, client_id, "wo_terms_library", "")
    try:
        own = [t for t in json.loads(raw) if (t.get("clause_text") or "").strip()] if raw else []
    except (ValueError, TypeError, AttributeError):
        own = []
    return own or (list(WO_STANDARD_TERMS) if fallback else [])


SIGN_KEYS = {"prepared by": "prepared", "proposed by": "proposed", "recommended by": "recommended",
             "checked by": "recommended", "certified by": "proposed",
             "authorized signatory": "authorised", "authorised signatory": "authorised"}


def sign_boxes(db, client_id, boxes, stage):
    """The signature row with the signatures on it that the paper has earned.

    Nothing is signed on a draft. Once it is sent, the person who prepared it
    has signed; once it is approved or certified, the whole row has, and the
    company's seal goes on the authorised signatory's box. A signature is only
    put above the name it belongs to - where the row names somebody else (the
    person who actually certified a bill), that box is left for a pen.
    """
    if not stage:
        return boxes, ""
    sig = doc_signatories(db, client_id)
    out, seal = [], ""
    for box in boxes:
        role, name = box[0], box[1]
        key = SIGN_KEYS.get((role or "").strip().lower())
        image = ""
        if key and (stage == "approved" or key == "prepared"):
            s = sig.get(key) or {}
            if s.get("image") and s.get("name") and s["name"] in (name or ""):
                image = s["image"]
        out.append((role, name, image))
    if stage == "approved":
        seal = doc_seal(db, client_id)
    return out, seal


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.documents.forms import WO_STANDARD_TERMS
from app.services.crm import norm_name
