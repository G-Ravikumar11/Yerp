"""The programme's arithmetic: dates, days, dependencies, roll-ups, the critical path and progress. No database.

Mirrored line for line in frontend/src/lib/programme.ts, so the grid answers as the user types; both are run against
the same cases (backend/tests/data/programme_cases.json), so the two cannot drift apart.

The rules, one set for every row:
  - A day counts when it is a working day: not a weekly day off (Sunday unless set otherwise), not a holiday - or every
    day, when the project counts calendar days.
  - Leaf: End = Start moved on Days - 1 working days, so a 1-day job starts and ends the same day. Days are working
    days. With no Days, the Days are the working days from Start to End. In productivity mode,
    Days = CEILING(Quantity / (output per gang per day x gangs)).
  - Start is the latest of what its predecessors allow and its "not earlier than" date. A leaf with no predecessors
    keeps the Start it was given.
      FS+n  starts n working days after the day the predecessor ends   (FS-1: the same day it ends)
      SS+n  starts n working days after the predecessor starts
      FF+n  ends n working days after the predecessor ends
      SF+n  ends n working days after the predecessor starts
  - Parent: Start = earliest child Start, End = latest child End, Days = working days between. Never typed.
  - A loop of dependencies is refused: its links are left out and named, and everything else is still worked out.
  - Critical: no slack - moving it by a working day moves the project's finish.
  - Progress: a leaf is quantity done / quantity (or the percentage given when it has no quantity). A parent is its
    children weighted by amount when every child has one, else by working days.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

LINK_KINDS = ("FS", "SS", "FF", "SF")
SUNDAY = 7                                    # ISO weekday numbers: Monday 1 ... Sunday 7


@dataclass
class Calendar:
    calendar_days: bool = False
    weekly_off: frozenset = frozenset({SUNDAY})
    holidays: frozenset = frozenset()

    def __post_init__(self):
        if not self.calendar_days and len(set(self.weekly_off) & set(range(1, 8))) == 7:
            raise ValueError("A week with no working day cannot be scheduled.")

    def working(self, d):
        return self.calendar_days or (d.isoweekday() not in self.weekly_off and d not in self.holidays)

    def snap(self, d):
        """d, or the next working day after it."""
        while not self.working(d):
            d += timedelta(days=1)
        return d

    def shift(self, d, n):
        """The working day n working days after d (before it when n is negative). n = 0 is d itself, moved on to a
        working day if it is not one."""
        d = self.snap(d)
        step = 1 if n >= 0 else -1
        for _ in range(abs(n)):
            d += timedelta(days=step)
            while not self.working(d):
                d += timedelta(days=step)
        return d

    def span(self, a, b):
        """Working days from a to b, both counted. 0 when b is before a."""
        if a is None or b is None or b < a:
            return 0
        if self.calendar_days:
            return (b - a).days + 1
        n, d = 0, a
        while d <= b:
            n += self.working(d)
            d += timedelta(days=1)
        return n


@dataclass
class Row:
    id: int
    parent_id: int = None
    order: int = 0
    name: str = ""
    start: date = None              # as entered (a leaf's own start)
    end: date = None                # as entered: read only when there are no days
    days: int = None
    not_before: date = None
    milestone: bool = False
    quantity: float = 0.0
    rate: float = 0.0
    amount: float = 0.0
    qty_done: float = 0.0
    percent: float = None           # progress given directly, for a row with no quantity
    productivity: bool = False
    output_per_day: float = 0.0
    gangs: float = 0.0


@dataclass
class Link:
    successor: int
    predecessor: int
    kind: str = "FS"
    lag: int = 0


@dataclass
class Planned:
    start: date = None
    end: date = None
    days: int = None
    level: int = 0
    wbs: str = ""
    summary: bool = False
    critical: bool = False
    float_days: int = None
    percent: float = 0.0
    amount_weight: float = 0.0       # its amount (a parent: its children's), for weighting
    children: list = field(default_factory=list)
    problem: str = ""


@dataclass
class Programme:
    rows: dict
    order: list                      # every row in tree order
    start: date = None
    finish: date = None
    duration: int = 0                # calendar days from start to finish, both counted (the sheet's TIME DURATION IN DAYS)
    errors: list = field(default_factory=list)
    broken_links: list = field(default_factory=list)   # links left out because they made a loop


def leaf_days(r):
    """How many working days a leaf takes, before its dates are known."""
    if r.milestone:
        return 0
    if r.productivity and r.quantity > 0 and r.output_per_day > 0 and r.gangs > 0:
        return max(1, math.ceil(round(r.quantity / (r.output_per_day * r.gangs), 9)))
    if r.days is not None:
        return max(0, int(r.days))
    return None


def _tree(rows):
    """Children by parent, in order; a parent that is missing (or that would make a loop) makes a row top-level."""
    by_id = {r.id: r for r in rows}
    parent = {}
    errors = []
    for r in rows:
        p = r.parent_id if r.parent_id in by_id and r.parent_id != r.id else None
        parent[r.id] = p
    # a row cannot sit under its own descendant
    for r in rows:
        seen, p = {r.id}, parent[r.id]
        while p is not None:
            if p in seen:
                errors.append("%s was under its own sub-item and has been put at the top level." % (r.name or r.id))
                parent[r.id] = None
                break
            seen.add(p)
            p = parent[p]
    children = {}
    for r in sorted(rows, key=lambda x: (x.order, x.id)):
        children.setdefault(parent[r.id], []).append(r.id)
    return parent, children, errors


def _cycle(nodes, edges):
    """One loop among these nodes, as a list of node ids (first repeated at the end), or []."""
    out = {}
    for a, b in edges:
        if a in nodes and b in nodes:
            out.setdefault(a, []).append(b)
    state, stack = {}, []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for m in out.get(n, []):
            if state.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if not state.get(m):
                found = visit(m)
                if found:
                    return found
        stack.pop()
        state[n] = 2
        return []

    for n in sorted(nodes):
        if not state.get(n):
            found = visit(n)
            if found:
                return found
    return []


def _topological(ids, link_edges, tree_edges):
    """Nodes in an order where every predecessor (and every child, before its parent) comes first. Links that make a
    loop are taken out one loop at a time and returned, so the rest can still be worked out."""
    link_edges = list(link_edges)
    removed = []
    while True:
        edges = link_edges + tree_edges
        indeg = {i: 0 for i in ids}
        out = {}
        for a, b in edges:
            indeg[b] += 1
            out.setdefault(a, []).append(b)
        ready = sorted(i for i in ids if indeg[i] == 0)
        order = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m in out.get(n, []):
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if len(order) == len(ids):
            return order, removed
        left = {i for i in ids if indeg[i] > 0}
        loop = _cycle(left, edges)
        pairs = set(zip(loop, loop[1:]))
        cut = [e for e in link_edges if e in pairs]
        if not cut:                                   # cannot happen: the tree itself has no loops
            return order + sorted(left), removed
        removed.append(loop)
        link_edges = [e for e in link_edges if e not in pairs]


def schedule(rows, links, cal=None):
    """Every row's dates, days, level, number, critical flag and progress. Rows and links as given; nothing changed."""
    cal = cal or Calendar()
    rows = list(rows)
    by_id = {r.id: r for r in rows}
    parent, children, errors = _tree(rows)
    out = {r.id: Planned(children=list(children.get(r.id, []))) for r in rows}

    # numbering (1, 1.1, 1.1.1) and tree order
    order = []

    def number(pid, prefix, level):
        for i, cid in enumerate(children.get(pid, []), start=1):
            p = out[cid]
            p.wbs = "%s%d" % (prefix, i)
            p.level = level
            p.summary = bool(children.get(cid))
            order.append(cid)
            number(cid, p.wbs + ".", level + 1)

    number(None, "", 0)

    # links: only between rows that exist; never onto a heading (its dates come from its sub-items)
    good = []
    for ln in links:
        if ln.successor not in by_id or ln.predecessor not in by_id or ln.successor == ln.predecessor:
            continue
        kind = (ln.kind or "FS").upper()
        if kind not in LINK_KINDS:
            out[ln.successor].problem = "Unknown link type %s." % ln.kind
            continue
        if out[ln.successor].summary:
            out[ln.successor].problem = "A heading takes its dates from its sub-items; link a sub-item instead."
            continue
        good.append(Link(ln.successor, ln.predecessor, kind, int(ln.lag or 0)))
    link_edges = [(ln.predecessor, ln.successor) for ln in good]
    tree_edges = [(cid, pid) for cid, pid in parent.items() if pid is not None]
    topo, loops = _topological([r.id for r in rows], link_edges, tree_edges)
    broken = []
    for loop in loops:
        names = " -> ".join("%s %s" % (out[i].wbs, by_id[i].name) for i in loop)
        errors.append("Circular dependency: %s. Those links are left out until one of them is removed." % names)
        pairs = set(zip(loop, loop[1:]))
        broken += [ln for ln in good if (ln.predecessor, ln.successor) in pairs]
    good = [ln for ln in good if ln not in broken]
    incoming = {}
    for ln in good:
        incoming.setdefault(ln.successor, []).append(ln)

    # forward pass
    for rid in topo:
        r, p = by_id[rid], out[rid]
        if p.summary:
            kids = [out[c] for c in p.children if out[c].start is not None]
            if kids:
                p.start, p.end = min(k.start for k in kids), max(k.end for k in kids)
                p.days = cal.span(p.start, p.end)
            continue
        d = leaf_days(r)
        if d is None:
            d = cal.span(cal.snap(r.start), r.end) if (r.start and r.end) else 1
        need = []
        for ln in incoming.get(rid, []):
            q = out[ln.predecessor]
            if q.start is None:
                continue
            if ln.kind == "FS":
                need.append(cal.shift(q.end, 1 + ln.lag))
            elif ln.kind == "SS":
                need.append(cal.shift(q.start, ln.lag))
            elif ln.kind == "FF":
                need.append(cal.shift(cal.shift(q.end, ln.lag), -max(0, d - 1)))
            else:                                                       # SF
                need.append(cal.shift(cal.shift(q.start, ln.lag), -max(0, d - 1)))
        # A Start typed on a linked row holds it back (not earlier than); the links can only push it later.
        base = max(need + ([r.start] if r.start else [])) if need else r.start
        if r.not_before:
            base = max(base, r.not_before) if base else r.not_before
        if base is None:
            continue                                                    # not scheduled yet
        p.start = cal.snap(base)
        p.end = p.start if d == 0 else cal.shift(p.start, d - 1)
        p.days = d

    scheduled = [out[i] for i in children.get(None, []) if out[i].start is not None]
    start = min((s.start for s in scheduled), default=None)
    finish = max((s.end for s in scheduled), default=None)

    # backward pass: how late each leaf could finish without moving the project's finish
    leaves_under = {}

    def leaves(i):
        if i not in leaves_under:
            leaves_under[i] = [i] if not out[i].summary else [x for c in out[i].children for x in leaves(c)]
        return leaves_under[i]

    late = {i: finish for i in by_id if not out[i].summary and out[i].start is not None}
    for rid in reversed(topo):
        p = out[rid]
        if p.summary or p.start is None:
            continue
        lf = late[rid]
        ls = lf if p.days == 0 else cal.shift(lf, -(p.days - 1))
        for ln in incoming.get(rid, []):
            for t in leaves(ln.predecessor):
                q = out[t]
                if q.start is None:
                    continue
                if ln.kind == "FS":
                    bound = cal.shift(ls, -(1 + ln.lag))
                elif ln.kind == "SS":
                    bound = cal.shift(cal.shift(ls, -ln.lag), max(0, q.days - 1))
                elif ln.kind == "FF":
                    bound = cal.shift(lf, -ln.lag)
                else:
                    bound = cal.shift(cal.shift(lf, -ln.lag), max(0, q.days - 1))
                late[t] = min(late[t], bound)
    for rid, lf in late.items():
        p = out[rid]
        p.float_days = cal.span(p.end, lf) - 1 if lf >= p.end else -(cal.span(lf, p.end) - 1)
        p.critical = p.float_days <= 0
    for rid in reversed(order):
        p = out[rid]
        if p.summary:
            p.critical = any(out[c].critical for c in p.children)

    # progress, bottom up
    for rid in reversed(order):
        r, p = by_id[rid], out[rid]
        if not p.summary:
            if r.quantity and r.quantity > 0:
                p.percent = max(0.0, min(100.0, (r.qty_done or 0) / r.quantity * 100))
            else:
                p.percent = max(0.0, min(100.0, r.percent or 0.0))
            p.amount_weight = r.amount if r.amount and r.amount > 0 else (
                r.quantity * r.rate if r.quantity and r.rate and r.quantity > 0 and r.rate > 0 else 0.0)
            continue
        kids = [out[c] for c in p.children]
        p.amount_weight = sum(k.amount_weight for k in kids)
        p.percent = _weighted(kids, [k.percent for k in kids])

    duration = (finish - start).days + 1 if start and finish else 0
    return Programme(rows=out, order=order, start=start, finish=finish, duration=duration, errors=errors,
                     broken_links=broken)


def _weights(kids):
    """Amount when every one has an amount; else working days; else all alike."""
    if kids and all(k.amount_weight > 0 for k in kids):
        return [k.amount_weight for k in kids]
    w = [float(k.days or 0) for k in kids]
    return w if sum(w) > 0 else [1.0] * len(kids)


def _weighted(kids, values):
    if not kids:
        return 0.0
    w = _weights(kids)
    return sum(a * b for a, b in zip(w, values)) / sum(w)


def planned_percent(prog, cal, as_of, baseline=None):
    """How far along each row should be on as_of, from its baseline dates (id -> (start, end, days)) or, with none,
    its current ones; and the whole project, under "project"."""
    cal = cal or Calendar()
    baseline = baseline or {}
    pct = {}
    for rid in reversed(prog.order):
        p = prog.rows[rid]
        if p.summary:
            kids = [prog.rows[c] for c in p.children]
            pct[rid] = _weighted(kids, [pct[c] for c in p.children])
            continue
        s, e, d = baseline.get(rid, (p.start, p.end, p.days))
        if s is None:
            pct[rid] = 0.0
        elif as_of < s:
            pct[rid] = 0.0
        elif as_of >= e:
            pct[rid] = 100.0
        else:
            pct[rid] = min(100.0, cal.span(s, as_of) / max(1, d or cal.span(s, e)) * 100)
    top = [prog.rows[i] for i in prog.order if prog.rows[i].level == 0]
    pct["project"] = _weighted(top, [pct[i] for i in prog.order if prog.rows[i].level == 0]) if top else 0.0
    return pct


def leaf_weights(prog):
    """Each leaf's share of the whole project, adding up to 1: the roll-up's weights multiplied down the tree. The
    project's % is then the leaves' % times these, the same figure as rolling it up a level at a time - and it holds
    for any day, planned or actual, because the weights do not depend on the progress."""
    out = {}

    def share(ids, part):
        kids = [prog.rows[i] for i in ids]
        if not kids:
            return
        w = _weights(kids)
        total = sum(w)
        for i, k, wi in zip(ids, kids, w):
            s = part * wi / total if total else 0.0
            if k.summary:
                share(k.children, s)
            else:
                out[i] = s

    share([i for i in prog.order if prog.rows[i].level == 0], 1.0)
    return out


def project_percent(prog):
    top = [prog.rows[i] for i in prog.order if prog.rows[i].level == 0]
    return _weighted(top, [t.percent for t in top]) if top else 0.0


# --- predecessors written as text: "1.1.2FS+1, 1.1.3SS+2" ------------------------------------------------------------

_PRED = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)*)\s*(FS|SS|FF|SF)?\s*(?:([+-])\s*(\d+)\s*d?)?\s*$", re.I)


def parse_predecessors(text, wbs_to_id):
    """Links from text such as "1.1.2FS+1, 1.1.3SS+2" (FS when no type is given; the lag in working days, - for a
    lead). Returns (links as (predecessor id, kind, lag), problems)."""
    found, problems = [], []
    for part in [p for p in re.split(r"[,;]", text or "") if p.strip()]:
        m = _PRED.match(part)
        if not m:
            problems.append("'%s' is not a predecessor. Write it as 1.2, 1.2FS+1 or 1.2SS-2." % part.strip())
            continue
        ref, kind, sign, n = m.groups()
        if ref not in wbs_to_id:
            problems.append("There is no row %s." % ref)
            continue
        lag = int(n or 0) * (-1 if sign == "-" else 1)
        found.append((wbs_to_id[ref], (kind or "FS").upper(), lag))
    return found, problems


def format_predecessors(links, id_to_wbs):
    """The other way: "1.1.2FS+1, 1.1.3SS+2"; a plain FS with no lag is just its number."""
    parts = []
    for pred, kind, lag in links:
        ref = id_to_wbs.get(pred)
        if not ref:
            continue
        if kind == "FS" and not lag:
            parts.append(ref)
        else:
            parts.append("%s%s%s" % (ref, kind, ("%+d" % lag) if lag else ""))
    return ", ".join(parts)
