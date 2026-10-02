import { readFileSync, writeFileSync } from 'node:fs'
const f = 'main.py'
const crlf = readFileSync(f, 'utf8').includes('\r\n')
let s = readFileSync(f, 'utf8').split('\r\n').join('\n')
const rep = (a, b) => { if (!s.includes(a)) throw new Error('missing ' + a.slice(0, 80)); s = s.replace(a, b) }
rep(`def mb_match_item(items, description):
    """The order's item a section of the book is for, by its description:
    the same words first, then one inside the other, then the most words in
    common. None when nothing is close enough to say."""
    want = re.sub(r"[^a-z0-9]+", " ", (description or "").lower()).strip()
    if not want:
        return None`, `def mb_item_label(it):
    """An item as it is named when somebody has to choose it: code, activity number, then the words."""
    return " ".join(x for x in ((it.item_code or "").strip(), (it.activity_no or "").strip(),
                                (it.item_description or "").split("\n")[0].strip()) if x)


def mb_match_item(items, description, sno=""):
    """The order's item a section of the book is for. By code first - the section's number or a
    code written in its heading, against the item's code or activity number - then by its
    description: the same words, one inside the other, then the most words in common.
    None when nothing is close enough to say."""
    def squash(t):
        return re.sub(r"[^a-z0-9]+", "", (t or "").lower())
    coded = [(it, {squash(it.item_code), squash(it.activity_no)} - {""}) for it in items]
    key = squash(sno)
    if key:
        hit = [it for it, codes in coded if key in codes]
        if len(hit) == 1:
            return hit[0]
    heading = set(re.sub(r"[^a-z0-9]+", " ", (description or "").lower()).split())
    hit = [it for it, codes in coded if codes and any(c in {squash(w) for w in heading} for c in codes if len(c) >= 3)]
    if len(hit) == 1:
        return hit[0]
    want = re.sub(r"[^a-z0-9]+", " ", (description or "").lower()).strip()
    if not want:
        return None`)
rep(`item = by_id.get(chosen[i]) if i in chosen else mb_match_item(items, sec["description"])`, `item = by_id.get(chosen[i]) if i in chosen else mb_match_item(items, sec["description"], sec.get("sno") or "")`)
rep(`                         "item": ("%s %s" % (item.activity_no or "", (item.item_description or "").split("\n")[0])).strip()
                                 if item else "",`, `                         "item": mb_item_label(item) if item else "",`)
rep(`               "items": [{"id": it.id, "label": ("%s %s" % (it.activity_no or "", (it.item_description or "").split("\n")[0])).strip(),
                          "uom": it.uom or ""} for it in items]}`, `               "items": [{"id": it.id, "label": mb_item_label(it), "uom": it.uom or ""} for it in items]}`)
writeFileSync(f, crlf ? s.split('\n').join('\r\n') : s)
