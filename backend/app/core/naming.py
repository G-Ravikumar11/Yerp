"""Names for things, taken from the long text a client's sheet writes about them."""
import re

# The contract's opening verbs; not the ones that name the work itself (filling, painting, dismantling ...).
_LEAD_VERBS = ("providing", "supplying", "laying", "fixing", "applying", "erecting", "making", "constructing", "placing",
               "installing", "carrying out", "transporting", "compacting", "finishing", "testing", "commissioning",
               "preparing", "mixing", "batching", "spreading", "levelling", "leveling", "doing", "executing", "furnishing",
               "designing")
_LEAD = re.compile(r"^(?:(?:%s)\s*(?:,|and|&)?\s*)+(?:of\s+)?" % "|".join(re.escape(v) for v in _LEAD_VERBS), re.I)
# Where a long description stops being the name of the work and starts being its specification.
_CUT = re.compile(r"[;:(\[]|,\s|\.\s|\.$|\s-\s|\s(?:including|complete|as per|as directed|in all|with|for all|"
                  r"conforming|confirming|according|using all|etc)\b", re.I)


def short_name(text, limit=60):
    """A BOQ description is a paragraph; the programme wants what the work is called. The opening verbs go
    ("Providing and laying"), and it stops where the specification starts. Editable afterwards; the whole text stays
    as the row's description."""
    first = re.sub(r"\s+", " ", (text or "").strip().split("\n")[0]).strip(" .,").rstrip(" -")
    if not first:
        return ""
    name = _LEAD.sub("", first).strip(" ,") or first
    for m in _CUT.finditer(name, 12):
        if name[:m.start()].count("(") <= name[:m.start()].count(")"):     # never inside brackets
            name = name[:m.start()]
            break
    name = name.strip(" ,.").rstrip(" -")
    if len(name) > limit:
        name = name[:limit].rsplit(" ", 1)[0]
        name = re.sub(r"(\s+(?:for|of|in|to|the|and|with|at|on|by|a|an|&|or))+$", "", name, flags=re.I)   # no dangling "for"
    if len(name) < 4:
        name = first[:limit]
    return name[:1].upper() + name[1:]
