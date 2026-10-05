"""Renames the words people read - "owner" to "Master", "gang" to "contractor" - in the server's messages and the
text it prints on documents. Only string literals that read as words (they hold a space, or are one of the label
words) are touched, and never docstrings: identifiers, keys and stored values stay as they are.

    python scripts_rename_words.py [--check] main.py sheet_forms.py ...
"""
import io
import re
import sys
import tokenize

LABELS = {"Owner", "Owners", "Gang", "Gangs", "OWNER", "GANG"}


def replace_words(text):
    text = re.sub(r"\b([Aa])n (owner|Owner)\b", lambda m: "%s Master" % m.group(1), text)
    text = re.sub(r"\bOWNERS\b", "MASTERS", text)
    text = re.sub(r"\bOWNER\b", "MASTER", text)
    text = re.sub(r"\b[Oo]wner(s?)('s|s')?(?![A-Za-z])", lambda m: "Master%s%s" % (m.group(1), m.group(2) or ""), text)
    text = re.sub(r"\bGANGS\b", "CONTRACTORS", text)
    text = re.sub(r"\bGANG\b", "CONTRACTOR", text)
    text = re.sub(r"\bGang(s?)('s|s')?(?![A-Za-z])", lambda m: "Contractor%s%s" % (m.group(1), m.group(2) or ""), text)
    text = re.sub(r"\bgang(s?)('s|s')?(?![A-Za-z])", lambda m: "contractor%s%s" % (m.group(1), m.group(2) or ""), text)
    return text


def inner_of(tok):
    s = tok.string
    m = re.match(r"^[rRbBuUfF]*('''|\"\"\"|'|\")", s)
    q = m.group(1) if m else ""
    return s[len(m.group(0)):-len(q)] if m and len(s) >= len(m.group(0)) + len(q) else s


def rename(path, check=False):
    src = open(path, encoding="utf8", newline="").read()
    lines = src.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    edits = []
    SKIP = {tokenize.NL, tokenize.COMMENT, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}
    # The significant token before and after each one, found once rather than searched for every string.
    sig = [i for i, t in enumerate(toks) if t.type not in (tokenize.NL, tokenize.COMMENT)]
    pos = {i: n for n, i in enumerate(sig)}
    for i, tok in enumerate(toks):
        is_middle = tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1)
        if tok.type != tokenize.STRING and not is_middle:
            continue
        if tok.type == tokenize.STRING:
            n = pos[i]
            prev = toks[sig[n - 1]] if n > 0 else None
            after = toks[sig[n + 1]] if n + 1 < len(sig) else None
            if (prev is None or prev.type in SKIP) and (after is None or after.type in (tokenize.NEWLINE, tokenize.ENDMARKER)):
                continue        # a docstring: the code's own notes, not something anybody is shown
            body = inner_of(tok)
        else:
            body = tok.string
        if not re.search(r"\s", body.strip()) and body.strip() not in LABELS:
            continue
        start = offsets[tok.start[0] - 1] + tok.start[1]
        end = offsets[tok.end[0] - 1] + tok.end[1]
        piece = src[start:end]
        new = replace_words(piece)
        if new != piece:
            edits.append((start, end, new, piece))
    if not edits:
        return 0
    out = src
    for start, end, new, _ in sorted(edits, key=lambda e: -e[0]):
        out = out[:start] + new + out[end:]
    if not check:
        open(path, "w", encoding="utf8", newline="").write(out)
    return len(edits)


if __name__ == "__main__":
    check = "--check" in sys.argv
    for p in [a for a in sys.argv[1:] if not a.startswith("--")]:
        print(p, rename(p, check))
