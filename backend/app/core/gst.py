"""GST states, places of supply and the tax split between them."""
import re

from app import models

from app.core.currency import money


# MEASUREMENT AND RUNNING ACCOUNT BILLS
#
# Work is measured on site, the measurements accumulate, and each bill claims
# the difference between what has been measured to date and what has already
# been claimed. That subtraction is the arithmetic a site office gets wrong by
# hand every month, and it is the whole reason this exists.
# GST, DONE THE WAY THE RETURN NEEDS IT
#
# The bills carried a flat tax percentage. A return does not: it wants to
# know whether the supply was inside our state - CGST and SGST, half each -
# or across a border - all of it IGST - and it wants that per rate, per
# month, with the HSN or SAC against every line. For a works contract the
# place of supply is where the property is, not where the client's head
# office sits, so the site's state is what the split is decided on.
# GST state codes: the first two digits of every GSTIN.
GST_STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
# Works contract services under GST.
WORKS_CONTRACT_SAC = "9954"


def state_from_gstin(gstin):
    g = (gstin or "").strip().upper()
    return g[:2] if len(g) >= 2 and g[:2].isdigit() and g[:2] in GST_STATES else ""


def split_gst(taxable, rate_percent, our_state, supply_state):
    """The one place the CGST/SGST-or-IGST decision is made.

    Same state: half and half. Different states, or either unknown: IGST -
    because a wrong IGST is a reconciliation, and a wrong CGST/SGST across a
    border is a penalty.
    """
    total = money((taxable or 0) * (rate_percent or 0) / 100.0)
    if our_state and supply_state and our_state == supply_state:
        half = money(total / 2.0)
        return {"cgst": half, "sgst": money(total - half), "igst": 0.0,
                "total": total, "intra_state": True}
    return {"cgst": 0.0, "sgst": 0.0, "igst": total, "total": total,
            "intra_state": False}


def our_state(db, client_id):
    c = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not c:
        return ""
    return (c.state_code or "").strip() or state_from_gstin(c.gstin)


# The first digits of a PIN code and the GST state they lie in - only where
# the postal circle and the state are the same thing. Where a circle spans two
# states (605 is Puducherry and Tamil Nadu, 24x is Uttar Pradesh and
# Uttarakhand) nothing is guessed and the project's state has to be picked.
PIN_STATES = {"11": "07", "30": "08", "31": "08", "32": "08", "33": "08", "34": "08",
              "36": "24", "37": "24", "38": "24", "39": "24",
              "40": "27", "41": "27", "42": "27", "43": "27", "44": "27",
              "50": "36", "51": "37", "52": "37", "53": "37",
              "56": "29", "57": "29", "58": "29", "59": "29",
              "60": "33", "61": "33", "62": "33", "63": "33", "64": "33",
              "67": "32", "68": "32", "69": "32"}
PIN_EXCEPTIONS = {"403": "30", "605": ""}


def state_from_pin(text):
    """The GST state of an address, from its six-digit PIN, when that is
    certain; "" when there is no PIN or its circle crosses a state line."""
    m = re.search(r"\b(\d{6})\b", text or "")
    if not m:
        return ""
    pin = m.group(1)
    if pin[:3] in PIN_EXCEPTIONS:
        return PIN_EXCEPTIONS[pin[:3]]
    return PIN_STATES.get(pin[:2], "")


def supply_state_for_job(db, job_id):
    """Where a project's work is supplied, for the GST split.

    Projects raised from the quick-add box, or before the state could be set,
    had none - and every bill on them went out as IGST, even for a site in
    the contractor's own city. The site address usually carries a PIN that
    settles it; only when it does not is the state left unknown (and IGST,
    the safe side, applies)."""
    if not job_id:
        return ""
    j = db.query(models.DBJob).filter(models.DBJob.id == job_id).first()
    if not j:
        return ""
    return (j.state_code or "").strip() or state_from_pin(j.site_address)
