"""The fixed lists, limits and statuses for boq."""



# What a BOQ off somebody's desk calls its columns. Wider than our own
# template on purpose: the schedule usually arrives as the contractor's own
# quotation with the rates already in it, and retyping two hundred lines to
# make them match a heading is how a rate gets typed wrong.
BOQ_HEADER_ALIASES = {
    "activity_no": ["activityno", "activity", "slno", "sl", "srno", "sr", "sno",
                    "serialno", "itemno", "no"],
    "item_code": ["itemcode", "code", "boqcode", "sku", "erpcode", "productcode"],
    "item_description": ["description", "itemdescription", "productdiscription",
                         "discription", "particulars", "workdescription",
                         "descriptionofwork", "natureofwork", "scopeofwork"],
    "technical_spec": ["specification", "technicalspecification", "technicalspec",
                       "spec", "specs", "remarks", "notes"],
    "uom": ["uom", "unit", "units", "measure", "unitofmeasure", "unitsofmeasure"],
    "quantity": ["qty", "quantity", "volume", "boqqty"],
    "unit_rate": ["rate", "unitrate", "price", "unitprice", "amountperunit"],
}

# THE PROJECT BOQ
#
# The client's bill of quantities for a project, kept once: sections, items and sub-items as their sheet
# numbers them, with revisions (R0 tender, R1 award, R2 after variations). Everything else hangs off it: the
# client's work order is drawn from it, a gang's order takes its lines (each keeps the line's key), and the
# tracker adds it all up per line - what the client pays, what the gangs are given, executed, billed.
#
# Item codes come from the item master's own single series, so a line is matched to the item it already is, or
# issued a new code, and nobody types one.
BOQ_KINDS = ("section", "item", "sub", "note")
BOQ_PRICED = ("item", "sub")
BOQ_NOT_LIVE = ("CANCELLED", "AMENDED", "REJECTED")
BOQ_IMPORT_ALIASES = {
    "sno": ["slno", "sl", "srno", "sr", "sno", "serialno", "itemno", "no", "activityno", "boqno", "refno"],
    "code": ["itemcode", "code", "boqcode", "sku", "productcode", "scheduleitemno"],
    "description": ["description", "itemdescription", "particulars", "descriptionofwork", "descriptionofitem",
                    "workdescription", "natureofwork", "scopeofwork", "itemofwork"],
    "uom": ["uom", "unit", "units", "unitofmeasure", "unitsofmeasure", "measure"],
    "quantity": ["qty", "quantity", "boqqty", "volume", "quantities"],
    "rate": ["rate", "unitrate", "price", "unitprice", "rateinrs", "rates"],
    "amount": ["amount", "totalamount", "amountinrs", "value", "amt", "total"],
    "remarks": ["remarks", "notes", "specification", "spec"],
}

# VARIATIONS TO THE BOQ
#
# Quantities that ran past the BOQ and items it never had, each with a rate, agreed on a route of approvers.
# Approving one moves the BOQ to its next revision with the changes in it - the lines are changed or added, new
# items get their item codes - and any client work order drawn from the BOQ is raised to match.
BV_TRANSITIONS = {
    "DRAFT":     {"SUBMIT": "SUBMITTED", "CANCEL": "CANCELLED"},
    "SUBMITTED": {"APPROVE": "APPROVED", "REJECT": "DRAFT", "CANCEL": "CANCELLED"},
    "APPROVED":  {},
    "CANCELLED": {},
}
