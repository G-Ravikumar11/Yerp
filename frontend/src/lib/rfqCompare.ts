import type { RfqInvite, RfqLine, RfqRow, RfqSupplier, Statement } from '@/api/rfq'

const key = (name: string) => name.trim().toLowerCase()

/** Cheapest landed first among those who quoted every line, then the part-quotes, most lines first. */
export function byLanded(sups: RfqSupplier[]): RfqSupplier[] {
  return [...sups].sort((a, b) => Number(b.complete) - Number(a.complete) || (a.complete ? 0 : b.lines_quoted - a.lines_quoted) || a.landed - b.landed)
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

/** One purchase order an award would make: who, how many items, and what it comes to with GST and transport. */
export interface PlannedOrder { supplier_name: string; items: number; basic: number; tax: number; freight: number; total: number }

const round2 = (n: number) => Math.round(n * 100) / 100

/**
 * The draft orders an award makes, worked out the way the server makes them: one per supplier, at the rates
 * quoted, and a supplier's transport charge carried in proportion to the share of his quote he is given.
 */
export function plannedOrders(d: Statement, choice: Map<number, string>): PlannedOrder[] {
  const quotes = new Map(d.suppliers.map((s) => [key(s.supplier_name), s]))
  const by = new Map<string, PlannedOrder>()
  for (const l of d.lines) {
    const name = choice.get(l.rfq_line_id)
    const o = name ? l.offers.find((x) => key(x.supplier_name) === key(name)) : undefined
    if (!o) continue
    const p = by.get(key(o.supplier_name)) ?? { supplier_name: o.supplier_name, items: 0, basic: 0, tax: 0, freight: 0, total: 0 }
    p.items += 1
    p.basic += o.amount
    p.tax += (o.amount * (o.tax_percent || 0)) / 100
    by.set(key(o.supplier_name), p)
  }
  return [...by.values()].map((p) => {
    const q = quotes.get(key(p.supplier_name))
    const freight = q && q.basic ? q.freight * (p.basic / q.basic) : 0
    return { ...p, basic: round2(p.basic), tax: round2(p.tax), freight: round2(freight), total: round2(p.basic + p.tax + freight) }
  })
}

/** Every line to one supplier. */
export const allTo = (d: Statement, supplier: string) => new Map(d.lines.map((l) => [l.rfq_line_id, supplier]))

/** Lines that would go to somebody other than the lowest quote for them: these need a reason on the file. */
export function passedOver(d: Statement, choice: Map<number, string>): RfqLine[] {
  return d.lines.filter((l) => {
    const o = l.offers.find((x) => key(x.supplier_name) === key(choice.get(l.rfq_line_id) ?? ''))
    return !!o && o.rate > l.lowest_rate + 0.0001
  })
}

/** A supplier on this enquiry: asked through a link, quoted, or both. */
export interface SupplierRow { name: string; quote: RfqSupplier | null; invite: RfqInvite | null }

/** Everyone on the enquiry once: those who quoted, cheapest first, then those still to answer, in the order asked. */
export function supplierRows(d: Statement): SupplierRow[] {
  const invites = new Map((d.invites ?? []).map((i) => [key(i.supplier_name), i]))
  const quoted = byLanded(d.suppliers).map((q) => ({ name: q.supplier_name, quote: q, invite: invites.get(key(q.supplier_name)) ?? null }))
  const seen = new Set(quoted.map((r) => key(r.name)))
  return [...quoted, ...(d.invites ?? []).filter((i) => !seen.has(key(i.supplier_name))).map((i) => ({ name: i.supplier_name, quote: null, invite: i }))]
}

export type StageKey = 'ask' | 'waiting' | 'compare' | 'awarded' | 'cancelled'

/** Where an enquiry has got, in a word or two, and what it waits on. */
export function stage(r: Pick<RfqRow, 'status' | 'quotes'> & { asked?: number }): { key: StageKey; label: string; tone: 'neutral' | 'warning' | 'info' | 'success' | 'ember' } {
  if (r.status === 'AWARDED') return { key: 'awarded', label: 'Awarded', tone: 'success' }
  if (r.status !== 'OPEN') return { key: 'cancelled', label: 'Cancelled', tone: 'neutral' }
  if (r.quotes > 0) return { key: 'compare', label: 'Ready to compare', tone: 'ember' }
  if ((r.asked ?? 0) > 0) return { key: 'waiting', label: 'Waiting for quotes', tone: 'info' }
  return { key: 'ask', label: 'Ask suppliers', tone: 'warning' }
}

export type DocFormat = 'pdf' | 'xlsx'

/** The link to the document: every supplier chosen is named in the query, and when all are chosen none needs naming. */
export function comparisonUrl(id: number, format: DocFormat, chosen: string[], everyone: number) {
  const q = chosen.length && chosen.length < everyone ? '?' + chosen.map((n) => `supplier=${encodeURIComponent(n)}`).join('&') : ''
  return `/api/rfqs/${id}/comparison.${format}${q}`
}

/* --- Across enquiries ---------------------------------------------------------------------------------------------- */

/** One supplier's price for an item, and the enquiry it was quoted on. */
export interface PooledOffer { supplier_name: string; rfq_id: number; rfq_number: string; rate: number; tax_percent: number; delivery_days: number }

/** An item asked for on one or more of the enquiries, with every price for it, cheapest first. */
export interface PooledItem { key: string; item_code: string; description: string; uom: string; enquiries: string[]; offers: PooledOffer[]; best: PooledOffer | null; next: PooledOffer | null }

/** Who came out cheapest on how many items. */
export interface SupplierTally { supplier_name: string; cheapest: number; quoted: number }

export interface Pooled { items: PooledItem[]; suppliers: SupplierTally[]; best: SupplierTally | null; unpriced: number }

/** The same item on two enquiries: by its code from the master, or else by what it is called and its unit. */
const itemKey = (l: RfqLine) => (l.item_code ? `code:${l.item_code.trim().toLowerCase()}` : `text:${key(l.description)}|${key(l.uom)}`)

/**
 * Every quote from the enquiries given, pooled by item: for each item the cheapest supplier whichever enquiry the
 * price came in on. Rates are compared per unit before GST; a tie goes to the quicker delivery. A supplier who
 * priced the item on two enquiries is listed at his lower rate only.
 */
export function pooledComparison(statements: Statement[]): Pooled {
  const items = new Map<string, PooledItem>()
  for (const d of statements) {
    const days = new Map(d.suppliers.map((s) => [key(s.supplier_name), s.delivery_days || 0]))
    for (const l of d.lines) {
      const k = itemKey(l)
      const it = items.get(k) ?? { key: k, item_code: l.item_code, description: l.description, uom: l.uom, enquiries: [], offers: [], best: null, next: null }
      if (!it.enquiries.includes(d.rfq.number)) it.enquiries.push(d.rfq.number)
      for (const o of l.offers) {
        const offer = { supplier_name: o.supplier_name, rfq_id: d.rfq.id, rfq_number: d.rfq.number, rate: o.rate, tax_percent: o.tax_percent, delivery_days: days.get(key(o.supplier_name)) ?? 0 }
        const at = it.offers.findIndex((x) => key(x.supplier_name) === key(o.supplier_name))
        if (at < 0) it.offers.push(offer)
        else if (o.rate < it.offers[at].rate) it.offers[at] = offer
      }
      items.set(k, it)
    }
  }
  // An unknown delivery time does not win a tie against a known one.
  const days = (o: PooledOffer) => o.delivery_days || Number.POSITIVE_INFINITY
  const tally = new Map<string, SupplierTally>()
  for (const it of items.values()) {
    it.offers.sort((a, b) => a.rate - b.rate || days(a) - days(b))
    it.best = it.offers[0] ?? null
    it.next = it.offers[1] ?? null
    for (const o of it.offers) {
      const t = tally.get(key(o.supplier_name)) ?? { supplier_name: o.supplier_name, cheapest: 0, quoted: 0 }
      t.quoted++
      if (o === it.best) t.cheapest++
      tally.set(key(o.supplier_name), t)
    }
  }
  const suppliers = [...tally.values()].sort((a, b) => b.cheapest - a.cheapest || b.quoted - a.quoted)
  const list = [...items.values()]
  return { items: list, suppliers, best: suppliers[0]?.cheapest ? suppliers[0] : null, unpriced: list.filter((i) => !i.best).length }
}
