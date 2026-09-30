import { describe, expect, it } from 'vitest'
import { ageing, cashFlow } from './cashflow'

const today = new Date(2026, 8, 30) // 30 September 2026

describe('cashFlow', () => {
  it('shows every one of the last months, quiet ones as nought', () => {
    const rows = cashFlow([], 6, today)
    expect(rows.map((r) => r.month)).toEqual(['2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09'])
    expect(rows.every((r) => r.received === 0 && r.paid === 0)).toBe(true)
    expect(rows.at(-1)?.label).toBe('Sep 26')
  })

  it('reaches back across a year end', () => {
    const rows = cashFlow([], 4, new Date(2026, 1, 10))
    expect(rows.map((r) => r.month)).toEqual(['2025-11', '2025-12', '2026-01', '2026-02'])
  })

  it('adds money in and money out per month', () => {
    const rows = cashFlow(
      [
        { direction: 'IN', amount: 1000, paid_on: '2026-09-02' },
        { direction: 'IN', amount: 500.5, paid_on: '2026-09-28' },
        { direction: 'OUT', amount: 400, paid_on: '2026-09-10' },
        { direction: 'OUT', amount: 250, paid_on: '2026-08-15' },
      ],
      3,
      today,
    )
    const [jul, aug, sep] = rows
    expect(jul.net).toBe(0)
    expect(aug).toMatchObject({ received: 0, paid: 250, net: -250 })
    expect(sep).toMatchObject({ received: 1500.5, paid: 400, net: 1100.5 })
  })

  it('leaves out an entry that was voided', () => {
    const rows = cashFlow([{ direction: 'IN', amount: 9999, paid_on: '2026-09-02', voided: true }], 2, today)
    expect(rows.at(-1)?.received).toBe(0)
  })

  it('ignores anything outside the months shown', () => {
    const rows = cashFlow([{ direction: 'IN', amount: 100, paid_on: '2020-01-01' }, { direction: 'IN', amount: 100, paid_on: '' }], 3, today)
    expect(rows.every((r) => r.received === 0)).toBe(true)
  })

  it('keeps a running balance across the months', () => {
    const rows = cashFlow(
      [
        { direction: 'IN', amount: 300, paid_on: '2026-07-01' },
        { direction: 'OUT', amount: 100, paid_on: '2026-08-01' },
        { direction: 'IN', amount: 50, paid_on: '2026-09-01' },
      ],
      3,
      today,
    )
    expect(rows.map((r) => r.running)).toEqual([300, 200, 250])
  })

  it('does not let float noise into the totals', () => {
    const rows = cashFlow([{ direction: 'IN', amount: 0.1, paid_on: '2026-09-01' }, { direction: 'IN', amount: 0.2, paid_on: '2026-09-02' }], 1, today)
    expect(rows[0].received).toBe(0.3)
  })
})

describe('ageing', () => {
  it('lines the two sides up bucket by bucket, in age order', () => {
    const rows = ageing({ 'Not due': 5, '0-30': 10, '90+': 1 }, { '0-30': 7 })
    expect(rows.map((r) => r.bucket)).toEqual(['Not yet due', '0-30 days', '31-60 days', '61-90 days', '90+ days'])
    expect(rows[1]).toEqual({ bucket: '0-30 days', receivable: 10, payable: 7 })
    expect(rows[2]).toEqual({ bucket: '31-60 days', receivable: 0, payable: 0 })
  })
})
