import { describe, expect, it } from 'vitest'
import type { RfqLine, RfqSupplier, Statement } from '@/api/rfq'
import { allTo, byLanded, compare, comparisonUrl, passedOver, plannedOrders, stage, supplierRows } from './rfqCompare'

const sup = (name: string, landed: number, extra: Partial<RfqSupplier> = {}): RfqSupplier => ({ quote_id: landed, supplier_name: name, quote_ref: '', quote_date: '', is_l1: false, basic: landed, tax: 0, freight: 0, landed, delivery_days: 0, payment_terms: '', valid_until: '', notes: '', complete: true, lines_quoted: 2, ...extra })
const line = (id: number, qty: number, offers: [string, number][]): RfqLine => {
  const low = offers.reduce<[string, number] | null>((b, o) => (!b || o[1] < b[1] ? o : b), null)
  return { rfq_line_id: id, description: `Line ${id}`, item_code: '', uom: 'Nos', qty, spread_percent: 0, awarded_supplier: '', awarded_rate: 0, po_id: null, po_number: '', lowest: low?.[0] ?? '', lowest_rate: low?.[1] ?? 0, offers: offers.map(([supplier_name, rate]) => ({ supplier_name, rate, amount: rate * qty, tax_percent: 18 })) }
}
const statement = (suppliers: RfqSupplier[], lines: RfqLine[]) => ({ suppliers, lines }) as unknown as Statement

describe('the comparison', () => {
  const d = statement(
    [sup('A', 1200, { basic: 1000 }), sup('B', 1100, { basic: 950 }), sup('C', 1500, { basic: 1300 }), sup('P', 300, { basic: 300, complete: false, lines_quoted: 1 })],
    [line(1, 10, [['A', 40], ['B', 45], ['C', 60], ['P', 30]]), line(2, 10, [['A', 60], ['B', 50], ['C', 70]])],
  )
  it('ranks part-quotes after every full quote, however cheap they look', () => {
    expect(byLanded([sup('Full', 900), sup('Part', 100, { complete: false, lines_quoted: 1 })]).map((s) => s.supplier_name)).toEqual(['Full', 'Part'])
  })
  it('ranks only within the vendors compared', () => {
    const c = compare(d, ['A', 'C'])
    expect([...c.rank]).toEqual([['A', 'L1'], ['C', 'L2']])
    expect(c.l1?.supplier_name).toBe('A')
    expect(c.savingVsL2).toBe(300)
  })
  it('splits each line to its lowest among those compared and says what that saves over L1', () => {
    const c = compare(d, ['A', 'B'])
    expect(c.split.basic).toBe(400 + 500)
    expect([...c.split.winners]).toEqual([[1, 'A'], [2, 'B']])
    expect(c.split.vendors).toBe(2)
    expect(c.splitSaving).toBe(50)
  })
  it('leaves an unranked part-quote out of L1 but lets it win the lines it quoted', () => {
    const c = compare(d, ['P', 'C'])
    expect(c.rank.has('P')).toBe(false)
    expect(c.l1?.supplier_name).toBe('C')
    expect(c.split.winners.get(1)).toBe('P')
  })
  it('names the lines nobody compared has quoted, and claims no saving then', () => {
    const c = compare(d, ['P'])
    expect(c.split.uncovered.map((l) => l.rfq_line_id)).toEqual([2])
    expect(c.splitSaving).toBe(0)
  })
})

describe('the orders an award makes', () => {
  const d = statement(
    [sup('A', 0, { basic: 1000, freight: 100 }), sup('B', 0, { basic: 950, freight: 0 })],
    [line(1, 10, [['A', 40], ['B', 45]]), line(2, 10, [['A', 60], ['B', 50]])],
  )
  it('is one order for everything given to one supplier, his transport with it', () => {
    expect(plannedOrders(d, allTo(d, 'A'))).toEqual([{ supplier_name: 'A', items: 2, basic: 1000, tax: 180, freight: 100, total: 1280 }])
  })
  it('is one order per supplier when split, transport shared by the part of his quote he gets', () => {
    const split = compare(d, ['A', 'B']).split.winners
    expect(plannedOrders(d, split)).toEqual([
      { supplier_name: 'A', items: 1, basic: 400, tax: 72, freight: 40, total: 512 },
      { supplier_name: 'B', items: 1, basic: 500, tax: 90, freight: 0, total: 590 },
    ])
  })
  it('names the items going to someone dearer than the lowest', () => {
    expect(passedOver(d, allTo(d, 'A')).map((l) => l.rfq_line_id)).toEqual([2])
    expect(passedOver(d, compare(d, ['A', 'B']).split.winners)).toEqual([])
  })
})

describe('the suppliers on an enquiry', () => {
  it('lists each once: quotes cheapest first, joined to their link, then those still to answer', () => {
    const inv = (id: number, supplier_name: string) => ({ id, supplier_name, status: 'sent' }) as never
    const d = { ...statement([sup('Dear', 900), sup('Cheap', 500)], []), invites: [inv(1, 'cheap '), inv(2, 'Waiting Co')] } as Statement
    const rows = supplierRows(d)
    expect(rows.map((r) => [r.name, !!r.quote, !!r.invite])).toEqual([['Cheap', true, true], ['Dear', true, false], ['Waiting Co', false, true]])
  })
})

describe('where an enquiry has got', () => {
  it('says what it waits on', () => {
    expect(stage({ status: 'OPEN', quotes: 0, asked: 0 }).key).toBe('ask')
    expect(stage({ status: 'OPEN', quotes: 0, asked: 2 }).key).toBe('waiting')
    expect(stage({ status: 'OPEN', quotes: 1, asked: 2 }).key).toBe('compare')
    expect(stage({ status: 'AWARDED', quotes: 3 }).label).toBe('Awarded')
    expect(stage({ status: 'CANCELLED', quotes: 0 }).key).toBe('cancelled')
  })
})

describe('the document link', () => {
  it('names each supplier chosen, commas and all, and none when everybody is in', () => {
    expect(comparisonUrl(7, 'pdf', ['A', 'Sharma, Pune'], 3)).toBe('/api/rfqs/7/comparison.pdf?supplier=A&supplier=Sharma%2C%20Pune')
    expect(comparisonUrl(7, 'xlsx', ['A', 'B', 'C'], 3)).toBe('/api/rfqs/7/comparison.xlsx')
  })
})
