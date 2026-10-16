import type { RfqLine, RfqSupplier, Statement } from '@/api/rfq'

/** More columns than this and a buyer stops reading across and starts scrolling. */
const MAX_COMPARE = 6
/** A rate this far over the lowest in its row is worth a second look. */
const OUTLIER_OVER = 0.25

const key = (name: string) => name.trim().toLowerCase()

/** Cheapest landed first among those who quoted every line, then the part-quotes, most lines first. */
export function byLanded(sups: RfqSupplier[]): RfqSupplier[] {
  return [...sups].sort((a, b) => Number(b.complete) - Number(a.complete) || (a.complete ? 0 : b.lines_quoted - a.lines_quoted) || a.landed - b.landed)
}

/** Everybody when there are six or fewer; otherwise the six cheapest landed. */
export function defaultCompare(sups: RfqSupplier[]): string[] {
  return byLanded(sups).slice(0, MAX_COMPARE).map((s) => s.supplier_name)
}

/** Shortest lead time first; a quote that gave no delivery days goes last, and ties go to the cheaper landed. */
export function fastest(sups: RfqSupplier[], n = 3): string[] {
  const days = (s: RfqSupplier) => s.delivery_days || Number.POSITIVE_INFINITY
  return [...sups].sort((a, b) => days(a) - days(b) || a.landed - b.landed).slice(0, n).map((s) => s.supplier_name)
}

/**
 * `compare=A,B,C` back into the suppliers' own names. A name may itself hold a comma ("Sharma, Pune"), so the
 * longest run of pieces that makes a known name wins. Unknown names are dropped, repeats ignored, six at most.
 */
export function parseCompare(raw: string | null, names: string[]): string[] {
  if (!raw) return []
  const known = new Map(names.map((n) => [key(n), n]))
  const parts = raw.split(',')
  const out: string[] = []
  for (let i = 0; i < parts.length; ) {
    let j = parts.length
    for (; j > i; j--) if (known.has(key(parts.slice(i, j).join(',')))) break
    if (j === i) { i++; continue }
    const name = known.get(key(parts.slice(i, j).join(',')))!
    if (!out.includes(name)) out.push(name)
    i = j
  }
  return out.slice(0, MAX_COMPARE)
}

export type Toggle = { ok: true; next: string[] } | { ok: false; reason: 'max' | 'min' }

/** Add or take away one supplier, keeping between two (when there are two to compare) and six. */
export function toggleVendor(selected: string[], name: string, available: number): Toggle {
  if (selected.includes(name)) {
    if (selected.length <= Math.min(2, available)) return { ok: false, reason: 'min' }
    return { ok: true, next: selected.filter((n) => n !== name) }
  }
  if (selected.length >= MAX_COMPARE) return { ok: false, reason: 'max' }
  return { ok: true, next: [...selected, name] }
}

export interface Comparison {
  /** The suppliers being compared, cheapest landed first. */
  suppliers: RfqSupplier[]
  /** L1, L2… among those compared; only a supplier who quoted every line is ranked. */
  rank: Map<string, string>
  l1: RfqSupplier | null
  savingVsL2: number
  /** The lowest rate in each line among those compared. */
  lowest: Map<number, number>
  /** Each line to whoever quoted it lowest among those compared. */
  split: { basic: number; winners: Map<number, string>; vendors: number; uncovered: RfqLine[] }
  /** L1's basic less the split's: what splitting the order saves before tax and freight. */
  splitSaving: number
}

export function compare(d: Statement, selected: string[]): Comparison {
  const picked = new Set(selected.map(key))
  const suppliers = byLanded(d.suppliers.filter((s) => picked.has(key(s.supplier_name))))
  const ranked = suppliers.filter((s) => s.complete)
  const rank = new Map(ranked.map((s, i) => [s.supplier_name, `L${i + 1}`]))
  const l1 = ranked[0] ?? null
  const lowest = new Map<number, number>()
  const winners = new Map<number, string>()
  const uncovered: RfqLine[] = []
  let basic = 0
  for (const l of d.lines) {
    // In the statement's order with a strict "less than", so a tie goes to the same supplier the server picks.
    let best: { supplier_name: string; rate: number; amount: number } | null = null
    for (const o of l.offers) if (picked.has(key(o.supplier_name)) && (!best || o.rate < best.rate)) best = o
    if (!best) { uncovered.push(l); continue }
    lowest.set(l.rfq_line_id, best.rate)
    winners.set(l.rfq_line_id, best.supplier_name)
    basic += best.amount
  }
  const vendors = new Set(winners.values()).size
  return {
    suppliers, rank, l1,
    savingVsL2: ranked.length > 1 ? ranked[1].landed - ranked[0].landed : 0,
    lowest,
    split: { basic, winners, vendors, uncovered },
    splitSaving: l1 && !uncovered.length ? Math.max(0, l1.basic - basic) : 0,
  }
}

/** best: the lowest in its row among those compared. high: more than 25% over it. */
export function cellTone(rate: number, low: number | undefined): 'best' | 'high' | '' {
  if (low === undefined) return ''
  if (rate <= low + 0.0001) return 'best'
  return low > 0 && rate > low * (1 + OUTLIER_OVER) ? 'high' : ''
}

export type DocFormat = 'pdf' | 'xlsx'

/** The link to the document: every supplier chosen is named in the query, and when all are chosen none needs naming. */
export function comparisonUrl(id: number, format: DocFormat, chosen: string[], everyone: number) {
  const q = chosen.length && chosen.length < everyone ? '?' + chosen.map((n) => `supplier=${encodeURIComponent(n)}`).join('&') : ''
  return `/api/rfqs/${id}/comparison.${format}${q}`
}
