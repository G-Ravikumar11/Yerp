import { describe, expect, it } from 'vitest'
import type { RfqLine, RfqSupplier, Statement } from '@/api/rfq'
import { byLanded, cellTone, compare, comparisonUrl, defaultCompare, fastest, parseCompare, toggleVendor } from './rfqCompare'

const sup = (name: string, landed: number, extra: Partial<RfqSupplier> = {}): RfqSupplier => ({ quote_id: landed, supplier_name: name, quote_ref: '', quote_date: '', is_l1: false, basic: landed, tax: 0, freight: 0, landed, delivery_days: 0, payment_terms: '', complete: true, lines_quoted: 2, ...extra })
const line = (id: number, qty: number, offers: [string, number][]): RfqLine => ({ rfq_line_id: id, description: `Line ${id}`, item_code: '', uom: 'Nos', qty, spread_percent: 0, awarded_supplier: '', lowest: '', lowest_rate: 0, offers: offers.map(([supplier_name, rate]) => ({ supplier_name, rate, amount: rate * qty, tax_percent: 18 })) })
const statement = (suppliers: RfqSupplier[], lines: RfqLine[]) => ({ suppliers, lines }) as unknown as Statement

describe('choosing who to compare', () => {
  const eight = 'ABCDEFGH'.split('').map((n, i) => sup(n, 1000 - i * 10))
  it('takes the six cheapest landed when there are more than six, and everybody otherwise', () => {
    expect(defaultCompare(eight)).toEqual(['H', 'G', 'F', 'E', 'D', 'C'])
    expect(defaultCompare(eight.slice(0, 3))).toEqual(['C', 'B', 'A'])
  })
  it('ranks part-quotes after every full quote, however cheap they look', () => {
    expect(byLanded([sup('Full', 900), sup('Part', 100, { complete: false, lines_quoted: 1 })]).map((s) => s.supplier_name)).toEqual(['Full', 'Part'])
  })
  it('puts the quickest first and a quote with no delivery days last', () => {
    expect(fastest([sup('None', 1, { delivery_days: 0 }), sup('Slow', 2, { delivery_days: 20 }), sup('Quick', 3, { delivery_days: 3 })], 3)).toEqual(['Quick', 'Slow', 'None'])
  })
  it('stops at six, and keeps two to compare', () => {
    expect(toggleVendor(['A', 'B', 'C', 'D', 'E', 'F'], 'G', 8)).toEqual({ ok: false, reason: 'max' })
    expect(toggleVendor(['A', 'B'], 'B', 8)).toEqual({ ok: false, reason: 'min' })
    expect(toggleVendor(['A', 'B', 'C'], 'B', 8)).toEqual({ ok: true, next: ['A', 'C'] })
    expect(toggleVendor(['A'], 'B', 8)).toEqual({ ok: true, next: ['A', 'B'] })
  })
})

describe('the compare link', () => {
  const names = ['Alpha Traders', 'Sharma, Pune', 'Beta']
  it('reads names back, a comma inside a name included, whatever the case', () => {
    expect(parseCompare('beta,Sharma, Pune,Alpha Traders', names)).toEqual(['Beta', 'Sharma, Pune', 'Alpha Traders'])
  })
  it('drops names it does not know and repeats', () => {
    expect(parseCompare('Gone,Beta,Beta', names)).toEqual(['Beta'])
    expect(parseCompare(null, names)).toEqual([])
  })
})

describe('the comparison', () => {
  const d = statement(
    [sup('A', 1200, { basic: 1000 }), sup('B', 1100, { basic: 950 }), sup('C', 1500, { basic: 1300 }), sup('P', 300, { basic: 300, complete: false, lines_quoted: 1 })],
    [line(1, 10, [['A', 40], ['B', 45], ['C', 60], ['P', 30]]), line(2, 10, [['A', 60], ['B', 50], ['C', 70]])],
  )
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
  it('marks the lowest and anything over 25% above it', () => {
    expect(cellTone(40, 40)).toBe('best')
    expect(cellTone(50, 40)).toBe('')
    expect(cellTone(50.01, 40)).toBe('high')
  })
})

describe('the document link', () => {
  it('names each supplier chosen, commas and all, and none when everybody is in', () => {
    expect(comparisonUrl(7, 'pdf', ['A', 'Sharma, Pune'], 3)).toBe('/api/rfqs/7/comparison.pdf?supplier=A&supplier=Sharma%2C%20Pune')
    expect(comparisonUrl(7, 'xlsx', ['A', 'B', 'C'], 3)).toBe('/api/rfqs/7/comparison.xlsx')
  })
})
