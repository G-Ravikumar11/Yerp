/**
 * The programme's arithmetic, the same as the server's (backend/app/services/programme_engine.py), so the grid answers
 * as the user types. Both run backend/tests/data/programme_cases.json; change one, change the other. The rules are
 * written out at the top of the Python file.
 *
 * Dates go in and come out as "YYYY-MM-DD"; inside, a date is a whole number of days since 1 Jan 1970, so no time zone
 * can move it.
 */

export type LinkKind = 'FS' | 'SS' | 'FF' | 'SF'
export const LINK_KINDS: LinkKind[] = ['FS', 'SS', 'FF', 'SF']

export interface CalendarSpec {
  calendar_days?: boolean
  /** ISO weekdays that are off: Monday 1 ... Sunday 7. Sunday when not given. */
  weekly_off?: number[]
  holidays?: string[]
}

export interface ProgrammeRow {
  id: number
  parent_id?: number | null
  order?: number
  name?: string
  start?: string | null
  end?: string | null
  days?: number | null
  not_before?: string | null
  milestone?: boolean
  quantity?: number
  rate?: number
  amount?: number
  qty_done?: number
  percent?: number | null
  productivity?: boolean
  output_per_day?: number
  gangs?: number
}

export interface ProgrammeLink {
  successor: number
  predecessor: number
  kind?: string
  lag?: number
}

export interface Planned {
  start: string | null
  end: string | null
  days: number | null
  level: number
  wbs: string
  summary: boolean
  critical: boolean
  float_days: number | null
  percent: number
  amount_weight: number
  children: number[]
  problem: string
}

export interface Programme {
  rows: Map<number, Planned>
  order: number[]
  start: string | null
  finish: string | null
  duration: number
  errors: string[]
  broken_links: ProgrammeLink[]
}

const DAY = 86_400_000
export const toDay = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / DAY)
}
export const fromDay = (n: number) => new Date(n * DAY).toISOString().slice(0, 10)
/** 1 Jan 1970 was a Thursday (4). */
const isoWeekday = (n: number) => ((((n + 3) % 7) + 7) % 7) + 1

export class Calendar {
  readonly calendarDays: boolean
  readonly weeklyOff: Set<number>
  readonly holidays: Set<number>

  constructor(spec: CalendarSpec = {}) {
    this.calendarDays = !!spec.calendar_days
    this.weeklyOff = new Set(spec.weekly_off ?? [7])
    this.holidays = new Set((spec.holidays ?? []).map(toDay))
    if (!this.calendarDays && [1, 2, 3, 4, 5, 6, 7].every((w) => this.weeklyOff.has(w))) {
      throw new Error('A week with no working day cannot be scheduled.')
    }
  }

  working(d: number) {
    return this.calendarDays || (!this.weeklyOff.has(isoWeekday(d)) && !this.holidays.has(d))
  }

  /** d, or the next working day after it. */
  snap(d: number) {
    while (!this.working(d)) d += 1
    return d
  }

  /** The working day n working days after d (before it when n is negative); n = 0 is d moved on to a working day. */
  shift(d: number, n: number) {
    d = this.snap(d)
    const step = n >= 0 ? 1 : -1
    for (let i = 0; i < Math.abs(n); i++) {
      d += step
      while (!this.working(d)) d += step
    }
    return d
  }

  /** Working days from a to b, both counted; 0 when b is before a. */
  span(a: number | null, b: number | null) {
    if (a === null || b === null || b < a) return 0
    if (this.calendarDays) return b - a + 1
    let n = 0
    for (let d = a; d <= b; d++) if (this.working(d)) n++
    return n
  }
}

interface Work {
  start: number | null
  end: number | null
  days: number | null
  level: number
  wbs: string
  summary: boolean
  critical: boolean
  float_days: number | null
  percent: number
  amount_weight: number
  children: number[]
  problem: string
}

/** How many working days a leaf takes, before its dates are known. */
export function leafDays(r: ProgrammeRow): number | null {
  if (r.milestone) return 0
  const q = r.quantity ?? 0
  const o = r.output_per_day ?? 0
  const g = r.gangs ?? 0
  if (r.productivity && q > 0 && o > 0 && g > 0) return Math.max(1, Math.ceil(Number((q / (o * g)).toFixed(9))))
  if (r.days !== null && r.days !== undefined) return Math.max(0, Math.trunc(r.days))
  return null
}

function findCycle(nodes: Set<number>, edges: [number, number][]): number[] {
  const out = new Map<number, number[]>()
  for (const [a, b] of edges) if (nodes.has(a) && nodes.has(b)) out.set(a, [...(out.get(a) ?? []), b])
  const state = new Map<number, number>()
  const stack: number[] = []
  const visit = (n: number): number[] => {
    state.set(n, 1)
    stack.push(n)
    for (const m of out.get(n) ?? []) {
      if (state.get(m) === 1) return [...stack.slice(stack.indexOf(m)), m]
      if (!state.get(m)) {
        const found = visit(m)
        if (found.length) return found
      }
    }
    stack.pop()
    state.set(n, 2)
    return []
  }
  for (const n of [...nodes].sort((a, b) => a - b)) {
    if (!state.get(n)) {
      const found = visit(n)
      if (found.length) return found
    }
  }
  return []
}

function topological(ids: number[], linkEdgesIn: [number, number][], treeEdges: [number, number][]) {
  let linkEdges = [...linkEdgesIn]
  const removed: number[][] = []
  for (;;) {
    const edges = [...linkEdges, ...treeEdges]
    const indeg = new Map(ids.map((i) => [i, 0]))
    const out = new Map<number, number[]>()
    for (const [a, b] of edges) {
      indeg.set(b, (indeg.get(b) ?? 0) + 1)
      out.set(a, [...(out.get(a) ?? []), b])
    }
    const ready = ids.filter((i) => indeg.get(i) === 0).sort((a, b) => a - b)
    const order: number[] = []
    while (ready.length) {
      const n = ready.shift()!
      order.push(n)
      for (const m of out.get(n) ?? []) {
        indeg.set(m, indeg.get(m)! - 1)
        if (indeg.get(m) === 0) ready.push(m)
      }
    }
    if (order.length === ids.length) return { order, removed }
    const left = new Set(ids.filter((i) => indeg.get(i)! > 0))
    const loop = findCycle(left, edges)
    const pairs = new Set(loop.slice(0, -1).map((a, k) => `${a}>${loop[k + 1]}`))
    if (!linkEdges.some(([a, b]) => pairs.has(`${a}>${b}`))) return { order: [...order, ...[...left].sort((a, b) => a - b)], removed }
    removed.push(loop)
    linkEdges = linkEdges.filter(([a, b]) => !pairs.has(`${a}>${b}`))
  }
}

/** Every row's dates, days, level, number, critical flag and progress. Nothing given is changed. */
export function schedule(rows: ProgrammeRow[], links: ProgrammeLink[], cal: Calendar = new Calendar()): Programme {
  const byId = new Map(rows.map((r) => [r.id, r]))
  const errors: string[] = []

  // the tree: a missing parent, or one that would make a loop, puts a row at the top level
  const parent = new Map<number, number | null>()
  for (const r of rows) {
    const p = r.parent_id ?? null
    parent.set(r.id, p !== null && byId.has(p) && p !== r.id ? p : null)
  }
  for (const r of rows) {
    const seen = new Set([r.id])
    let p = parent.get(r.id) ?? null
    while (p !== null) {
      if (seen.has(p)) {
        errors.push(`${r.name || r.id} was under its own sub-item and has been put at the top level.`)
        parent.set(r.id, null)
        break
      }
      seen.add(p)
      p = parent.get(p) ?? null
    }
  }
  const children = new Map<number | null, number[]>()
  for (const r of [...rows].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id - b.id)) {
    const p = parent.get(r.id) ?? null
    children.set(p, [...(children.get(p) ?? []), r.id])
  }
  const out = new Map<number, Work>(rows.map((r) => [r.id, {
    start: null, end: null, days: null, level: 0, wbs: '', summary: false, critical: false, float_days: null,
    percent: 0, amount_weight: 0, children: [...(children.get(r.id) ?? [])], problem: '',
  }]))
  const order: number[] = []
  const number = (pid: number | null, prefix: string, level: number) => {
    ;(children.get(pid) ?? []).forEach((cid, i) => {
      const p = out.get(cid)!
      p.wbs = `${prefix}${i + 1}`
      p.level = level
      p.summary = (children.get(cid) ?? []).length > 0
      order.push(cid)
      number(cid, `${p.wbs}.`, level + 1)
    })
  }
  number(null, '', 0)

  // links: only between rows that exist; never onto a heading
  let good: Required<ProgrammeLink>[] = []
  for (const ln of links) {
    if (!byId.has(ln.successor) || !byId.has(ln.predecessor) || ln.successor === ln.predecessor) continue
    const kind = (ln.kind || 'FS').toUpperCase()
    if (!LINK_KINDS.includes(kind as LinkKind)) {
      out.get(ln.successor)!.problem = `Unknown link type ${ln.kind}.`
      continue
    }
    if (out.get(ln.successor)!.summary) {
      out.get(ln.successor)!.problem = 'A heading takes its dates from its sub-items; link a sub-item instead.'
      continue
    }
    good.push({ successor: ln.successor, predecessor: ln.predecessor, kind, lag: Math.trunc(ln.lag ?? 0) })
  }
  const linkEdges: [number, number][] = good.map((l) => [l.predecessor, l.successor])
  const treeEdges: [number, number][] = [...parent.entries()].filter(([, p]) => p !== null).map(([c, p]) => [c, p as number])
  const { order: topo, removed } = topological(rows.map((r) => r.id), linkEdges, treeEdges)
  const broken: Required<ProgrammeLink>[] = []
  for (const loop of removed) {
    const names = loop.map((i) => `${out.get(i)!.wbs} ${byId.get(i)!.name ?? ''}`).join(' -> ')
    errors.push(`Circular dependency: ${names}. Those links are left out until one of them is removed.`)
    const pairs = new Set(loop.slice(0, -1).map((a, k) => `${a}>${loop[k + 1]}`))
    broken.push(...good.filter((l) => pairs.has(`${l.predecessor}>${l.successor}`)))
  }
  good = good.filter((l) => !broken.includes(l))
  const incoming = new Map<number, Required<ProgrammeLink>[]>()
  for (const l of good) incoming.set(l.successor, [...(incoming.get(l.successor) ?? []), l])

  // forward pass
  for (const rid of topo) {
    const r = byId.get(rid)!
    const p = out.get(rid)!
    if (p.summary) {
      const kids = p.children.map((c) => out.get(c)!).filter((k) => k.start !== null)
      if (kids.length) {
        p.start = Math.min(...kids.map((k) => k.start!))
        p.end = Math.max(...kids.map((k) => k.end!))
        p.days = cal.span(p.start, p.end)
      }
      continue
    }
    let d = leafDays(r)
    if (d === null) d = r.start && r.end ? cal.span(cal.snap(toDay(r.start)), toDay(r.end)) : 1
    const need: number[] = []
    for (const ln of incoming.get(rid) ?? []) {
      const q = out.get(ln.predecessor)!
      if (q.start === null) continue
      if (ln.kind === 'FS') need.push(cal.shift(q.end!, 1 + ln.lag))
      else if (ln.kind === 'SS') need.push(cal.shift(q.start, ln.lag))
      else if (ln.kind === 'FF') need.push(cal.shift(cal.shift(q.end!, ln.lag), -Math.max(0, d - 1)))
      else need.push(cal.shift(cal.shift(q.start, ln.lag), -Math.max(0, d - 1)))
    }
    let base: number | null = need.length ? Math.max(...need) : r.start ? toDay(r.start) : null
    if (r.not_before) base = base !== null ? Math.max(base, toDay(r.not_before)) : toDay(r.not_before)
    if (base === null) continue
    p.start = cal.snap(base)
    p.end = d === 0 ? p.start : cal.shift(p.start, d - 1)
    p.days = d
  }

  const top = (children.get(null) ?? []).map((i) => out.get(i)!).filter((s) => s.start !== null)
  const start = top.length ? Math.min(...top.map((s) => s.start!)) : null
  const finish = top.length ? Math.max(...top.map((s) => s.end!)) : null

  // backward pass
  const leavesUnder = new Map<number, number[]>()
  const leaves = (i: number): number[] => {
    if (!leavesUnder.has(i)) leavesUnder.set(i, out.get(i)!.summary ? out.get(i)!.children.flatMap(leaves) : [i])
    return leavesUnder.get(i)!
  }
  const late = new Map<number, number>()
  for (const [i, p] of out) if (!p.summary && p.start !== null && finish !== null) late.set(i, finish)
  for (const rid of [...topo].reverse()) {
    const p = out.get(rid)!
    if (p.summary || p.start === null) continue
    const lf = late.get(rid)!
    const ls = p.days === 0 ? lf : cal.shift(lf, -(p.days! - 1))
    for (const ln of incoming.get(rid) ?? []) {
      for (const t of leaves(ln.predecessor)) {
        const q = out.get(t)!
        if (q.start === null) continue
        let bound: number
        if (ln.kind === 'FS') bound = cal.shift(ls, -(1 + ln.lag))
        else if (ln.kind === 'SS') bound = cal.shift(cal.shift(ls, -ln.lag), Math.max(0, q.days! - 1))
        else if (ln.kind === 'FF') bound = cal.shift(lf, -ln.lag)
        else bound = cal.shift(cal.shift(lf, -ln.lag), Math.max(0, q.days! - 1))
        late.set(t, Math.min(late.get(t)!, bound))
      }
    }
  }
  for (const [rid, lf] of late) {
    const p = out.get(rid)!
    p.float_days = lf >= p.end! ? cal.span(p.end, lf) - 1 : -(cal.span(lf, p.end) - 1)
    p.critical = p.float_days <= 0
  }
  for (const rid of [...order].reverse()) {
    const p = out.get(rid)!
    if (p.summary) p.critical = p.children.some((c) => out.get(c)!.critical)
  }

  // progress, bottom up
  for (const rid of [...order].reverse()) {
    const r = byId.get(rid)!
    const p = out.get(rid)!
    if (!p.summary) {
      const q = r.quantity ?? 0
      p.percent = q > 0 ? Math.max(0, Math.min(100, ((r.qty_done ?? 0) / q) * 100)) : Math.max(0, Math.min(100, r.percent ?? 0))
      const rate = r.rate ?? 0
      p.amount_weight = (r.amount ?? 0) > 0 ? r.amount! : q > 0 && rate > 0 ? q * rate : 0
      continue
    }
    const kids = p.children.map((c) => out.get(c)!)
    p.amount_weight = kids.reduce((s, k) => s + k.amount_weight, 0)
    p.percent = weighted(kids, kids.map((k) => k.percent))
  }

  const rowsOut = new Map<number, Planned>()
  for (const [i, p] of out) {
    rowsOut.set(i, { ...p, start: p.start === null ? null : fromDay(p.start), end: p.end === null ? null : fromDay(p.end) })
  }
  return {
    rows: rowsOut, order,
    start: start === null ? null : fromDay(start),
    finish: finish === null ? null : fromDay(finish),
    duration: start !== null && finish !== null ? finish - start + 1 : 0,
    errors, broken_links: broken,
  }
}

/** Amount when every one has an amount; else working days; else all alike. */
function weightsOf(kids: { amount_weight: number; days: number | null }[]) {
  if (kids.length && kids.every((k) => k.amount_weight > 0)) return kids.map((k) => k.amount_weight)
  const w = kids.map((k) => k.days ?? 0)
  return w.reduce((a, b) => a + b, 0) > 0 ? w : kids.map(() => 1)
}

function weighted(kids: { amount_weight: number; days: number | null }[], values: number[]) {
  if (!kids.length) return 0
  const w = weightsOf(kids)
  return w.reduce((s, x, i) => s + x * values[i], 0) / w.reduce((a, b) => a + b, 0)
}

/** How far along each row should be on asOf, from its baseline dates (id -> [start, end, days]) or its current ones;
 * the whole project under "project". */
export function plannedPercent(prog: Programme, cal: Calendar, asOf: string, baseline: Map<number, [string, string, number]> = new Map()) {
  const pct = new Map<number | 'project', number>()
  const at = toDay(asOf)
  for (const rid of [...prog.order].reverse()) {
    const p = prog.rows.get(rid)!
    if (p.summary) {
      const kids = p.children.map((c) => prog.rows.get(c)!)
      pct.set(rid, weighted(kids, p.children.map((c) => pct.get(c)!)))
      continue
    }
    const [s, e, d] = baseline.get(rid) ?? [p.start, p.end, p.days]
    if (!s || !e) pct.set(rid, 0)
    else if (at < toDay(s)) pct.set(rid, 0)
    else if (at >= toDay(e)) pct.set(rid, 100)
    else pct.set(rid, Math.min(100, (cal.span(toDay(s), at) / Math.max(1, d || cal.span(toDay(s), toDay(e)))) * 100))
  }
  const top = prog.order.filter((i) => prog.rows.get(i)!.level === 0)
  pct.set('project', top.length ? weighted(top.map((i) => prog.rows.get(i)!), top.map((i) => pct.get(i)!)) : 0)
  return pct
}

export function projectPercent(prog: Programme) {
  const top = prog.order.filter((i) => prog.rows.get(i)!.level === 0).map((i) => prog.rows.get(i)!)
  return top.length ? weighted(top, top.map((t) => t.percent)) : 0
}

/* --- predecessors written as text: "1.1.2FS+1, 1.1.3SS+2" ---------------------------------------------------------- */

const PRED = /^\s*([0-9]+(?:\.[0-9]+)*)\s*(FS|SS|FF|SF)?\s*(?:([+-])\s*(\d+)\s*d?)?\s*$/i

/** Links from text such as "1.1.2FS+1, 1.1.3SS+2": [predecessor id, kind, lag] and what could not be read. */
export function parsePredecessors(text: string, wbsToId: Record<string, number>) {
  const links: [number, LinkKind, number][] = []
  const problems: string[] = []
  for (const part of (text || '').split(/[,;]/).filter((p) => p.trim())) {
    const m = PRED.exec(part)
    if (!m) {
      problems.push(`'${part.trim()}' is not a predecessor. Write it as 1.2, 1.2FS+1 or 1.2SS-2.`)
      continue
    }
    const [, ref, kind, sign, n] = m
    if (!(ref in wbsToId)) {
      problems.push(`There is no row ${ref}.`)
      continue
    }
    links.push([wbsToId[ref], ((kind || 'FS').toUpperCase()) as LinkKind, Number(n || 0) * (sign === '-' ? -1 : 1)])
  }
  return { links, problems }
}

/** The other way: "1.1.2FS+1, 1.1.3SS+2"; a plain FS with no lag is just its number. */
export function formatPredecessors(links: [number, string, number][], idToWbs: Record<number, string>) {
  return links
    .filter(([pred]) => idToWbs[pred])
    .map(([pred, kind, lag]) => (kind === 'FS' && !lag ? idToWbs[pred] : `${idToWbs[pred]}${kind}${lag ? (lag > 0 ? `+${lag}` : `${lag}`) : ''}`))
    .join(', ')
}
