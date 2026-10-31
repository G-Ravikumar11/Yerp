import { describe, expect, it } from 'vitest'
import { ageing, monthLabel, withLabels } from './cashflow'

describe('the cash chart months', () => {
  it('labels a month the way the chart shows it, across a year end too', () => {
    expect(monthLabel('2026-09')).toBe('Sep 26')
    expect(monthLabel('2025-12')).toBe('Dec 25')
  })

  it('keeps the server figures as they are', () => {
    const [row] = withLabels([{ month: '2026-10', received: 1500.5, paid: 400, net: 1100.5, running: 251100.5 }])
    expect(row).toEqual({ month: '2026-10', label: 'Oct 26', received: 1500.5, paid: 400, net: 1100.5, running: 251100.5 })
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
