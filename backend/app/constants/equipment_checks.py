"""The company's safety inspection forms for tools, extinguishers and electrical boards.

Each form is the paper form, item for item, with the same document reference. An item is answered Yes, No or N/A.
`bad_if_yes` marks the few items worded the other way round ("Is the extinguisher corroded"), where Yes is the fault.
An `optional` item may be left blank. The sign-offs are the signature boxes at the foot of the paper form.
"""

ANSWERS = ("yes", "no", "na")


def _items(*rows):
    out = []
    for key, label, *flags in rows:
        out.append({"key": key, "label": label, "bad_if_yes": "bad" in flags, "optional": "optional" in flags})
    return out


_CONTRACTOR = {"role": "contractor_officer", "label": "Checked by Contractor Safety Officer"}
_ELECTRICIAN = {"role": "client_electrician", "label": "Checked by Client Electrician"}

_ELECTRICAL_SECTIONS = (
    ("A. Availability", [("A", "Electrical engineer / safety officer available?"),
                         ("B", "Licensed electrician available at site?")]),
    ("C. Power panel", [("C1", "Check operation of each feeder."), ("C2", "Fuses of proper rating present."),
                        ("C3", "Tightening of bus bar made."), ("C4", "Tightening of earth connection checked."),
                        ("C5", "Cleaning of panel."), ("C6", "Spare holes / opening closed."),
                        ("C7", "DCP / CO2 fire extinguisher installed / checked.")]),
    ("D. Distribution panel", [("D1", "Fuse rating of incoming & outgoing feeder checked / recorded ok."),
                               ("D2", "Operation of each feeder switch checked / recorded ok."),
                               ("D3", "Tightening of earth connection to DB and all switches checked."),
                               ("D4", "Tightening of power cable of incoming and outgoing feeders checked."),
                               ("D5", "Operation of ELCB checked and recorded."),
                               ("D6", "Spare holes / opening closed."), ("D7", "Proper outgoing of DBs.")]),
    # The paper form numbers these 1, 2 and 5: items 3 and 4 are not on it.
    ("E. Cables", [("E1", "All flexible cables and cable joints are above ground level."),
                   ("E2", "Cable markers are in proper position."),
                   ("E5", "Cables used are correctly rated.")]),
    ("F. Earthing", [("F1", "Earthing connection with all electrical equipment checked."),
                     ("F2", "Tightening of earthing checked."),
                     ("F3", "Earthing resistance value checked and recorded.")]),
    ("G. Lighting", [("G1", "Power connection to fixtures with 3-core flexible wire made."),
                     ("G2", "Condition of protective glass covers for halogens in place / in good condition."),
                     ("G3", "Rigid framework of lighting fixture pole at site."),
                     ("G4", "Protective insulation of cables is ok.")]),
    ("H. Miscellaneous", [("H1", "Rain protection for power panel / DBs / plug sockets, welding machine and DG set arranged."),
                          ("H2", "Easy access to all electrical power panels, DBs, welding machines and DG sets at site."),
                          ("H3", "Switch operation for welding machine in right order."),
                          ("H4", "Welding cables and electrical cables are separately laid."),
                          ("H5", "Danger board / caution notice displayed."),
                          ("H6", "Use of good and insulated tools checked and recorded.")]),
)

_REVIEW_TOOLS = {"label": "Client / PMC reviewed", "signoff_label": "Checked by Client / PMC"}

EQUIPMENT_CHECKS = {
    "grinder": {
        "label": "Portable grinding machine",
        "title": "CHECKLIST FOR PORTABLE GRINDING MACHINE",
        "doc_ref": "YIP-03/HSE/REV00/Dec-2024",
        "equipment_label": "Equipment No.", "specs_label": "Equipment specs.",
        "fields": ["equipment_no", "specs", "location"],
        "items": _items(
            ("1", "Fore handle without damage."), ("2", "Wheel guard (covering 3/4th area) provided."),
            ("3", "Grinding wheel without any crack."), ("4", "Rear handle without any damage."),
            ("5", "Presence of cord strain reliever (glands)."), ("6", "Trigger switch without damage."),
            ("7", "Switch lock in working condition."), ("8", "Electric cable without cuts and joints."),
            ("9", "Industrial plug top used.")),
        "readings": [{"key": "wheel_rpm", "label": "Wheel rpm", "unit": "rpm"},
                     {"key": "machine_rpm", "label": "Machine rpm", "unit": "rpm"}],
        "signoffs": [_CONTRACTOR, _ELECTRICIAN],
        "review": _REVIEW_TOOLS,
    },
    "breaking": {
        "label": "Portable breaking machine",
        "title": "CHECKLIST FOR PORTABLE BREAKING MACHINE",
        "doc_ref": "YIP-07/HSE/REV00/Dec-2022",
        "equipment_label": "Equipment No.", "specs_label": "Equipment specs.",
        "fields": ["equipment_no", "specs", "location"],
        "items": _items(
            ("1", "Fore handle without damage."), ("2", "Chisel in damaged condition.", "bad"),
            ("3", "Chisel holder without any damage."), ("4", "Speed limit switch available."),
            ("5", "Presence of cord strain reliever (glands)."), ("6", "Trigger switch without damage."),
            ("7", "All body in good condition."), ("8", "Electric cable without cuts and joints."),
            ("9", "Presence of industrial plug top."), ("10", "Other", "optional")),
        "readings": [],
        "signoffs": [_CONTRACTOR, _ELECTRICIAN],
        "review": _REVIEW_TOOLS,
    },
    "drill": {
        "label": "Hammering drill machine",
        "title": "CHECKLIST FOR HAMMERING DRILL MACHINE",
        "doc_ref": "YIP-02/HSE/REV00/Dec-2024",
        "equipment_label": "Equipment No.", "specs_label": "Equipment specs.",
        "fields": ["equipment_no", "specs", "location"],
        "items": _items(
            ("1", "Equipment double insulated (written on the machine body)."),
            ("2", "Equipment free from any defect like broken handle, broken parts etc."),
            ("3", "Electrical cable free from defects."), ("4", "Industrial plug top available and in working condition."),
            ("5", "Drilling bit without any damage."), ("6", "Drilling bit holder is available and in working condition."),
            ("7", "Switch in working condition.")),
        "readings": [],
        "signoffs": [_CONTRACTOR, _ELECTRICIAN],
        "review": _REVIEW_TOOLS,
    },
    "extinguisher": {
        "label": "Fire extinguisher",
        "title": "CHECK LIST FOR FIRE EXTINGUISHER",
        "doc_ref": "YIP-01-2024",
        "equipment_label": "Extinguisher No.", "specs_label": "Extinguisher specifications",
        "fields": ["equipment_no", "specs", "extinguisher_type", "location"],
        "extinguisher_types": ["ABC type", "Water type", "CO2 type"],
        "default_interval_days": 90,          # the HSE plan: inspected once a quarter by the manufacturer or distributor
        "items": _items(
            ("1", "Condition of the extinguisher (clean and tidy)."), ("2", "Is the extinguisher corroded.", "bad"),
            ("3", "Safety pin is in locking position."), ("4", "Condition of discharge nozzle (any blockage / damage)."),
            ("5", "Condition of hose (any leakage / broken)."),
            ("6", "Weight of the extinguisher (should match the actual weight written on the body)."),
            ("7", "Availability of visual board."), ("8", "All the indicator gauges (where fitted) in green segment (not red)."),
            ("9", "Extinguisher is expired or refilled before refill date.", "bad"), ("10", "Others", "optional")),
        "readings": [],
        "signoffs": [_CONTRACTOR],
        "review": {"label": "PMC reviewed", "signoff_label": "Checked by PMC / Client"},
    },
    "electrical": {
        "label": "Electrical safety (DB / panel)",
        "title": "ELECTRICAL SAFETY INSPECTION CHECKLIST",
        "doc_ref": "YIP-05/HSE/REV00/Dec-2024",
        "equipment_label": "Identification No.", "specs_label": "",
        "fields": ["equipment_no", "board_type", "location"],
        "items": [dict(item, section=section) for section, rows in _ELECTRICAL_SECTIONS for item in _items(*rows)],
        "readings": [{"key": "earth_resistance", "label": "Earthing resistance (item F3)", "unit": "ohm"}],
        "signoffs": [{"role": "inspected_by", "label": "Inspected by"}, {"role": "reviewed_by", "label": "Reviewed by"}],
        "review": None,
    },
}
