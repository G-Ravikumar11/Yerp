"""The fixed lists for contractor compliance."""

DOC_KINDS = {
    "labour_licence": "Contract labour licence",
    "pf": "PF registration",
    "esi": "ESI registration",
    "insurance": "Workmen's compensation policy",
    "bocw": "Construction workers' registration",
    "other": "Other",
}

# A document counts as "expiring" this many days before it runs out.
EXPIRY_WARNING_DAYS = 30

BACK_CHARGE_KINDS = ("Wastage", "Damage", "Clean-up", "Safety", "Other")
RATING_FIELDS = ("quality", "speed", "safety", "discipline")
