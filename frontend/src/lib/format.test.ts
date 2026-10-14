import { describe, expect, it } from 'vitest'
import { formatDate, formatPercent, formatQty, plural, today } from './format'

describe('formatDate', () => {
  it('writes an ISO date the way people read it', () => {
    expect(formatDate('2026-10-01')).toBe('01 Oct 2026')
  })
  it('accepts a datetime', () => {
    expect(formatDate('2026-12-31T23:59:00')).toBe('31 Dec 2026')
  })
  it('leaves blanks and non-dates alone', () => {
    expect(formatDate(null)).toBe('')
    expect(formatDate(undefined)).toBe('')
    expect(formatDate('soon')).toBe('soon')
  })
})

describe('formatQty', () => {
  it('uses Indian grouping and drops trailing noughts', () => {
    expect(formatQty(1234567.5)).toBe('12,34,567.5')
  })
  it('rounds to the given places', () => {
    expect(formatQty(1.23456, 2)).toBe('1.23')
  })
  it('keeps zero but blanks a missing value', () => {
    expect(formatQty(0)).toBe('0')
    expect(formatQty(null)).toBe('')
  })
})

describe('formatPercent', () => {
  it('shows a dash for zero or missing', () => {
    expect(formatPercent(0)).toBe('-')
    expect(formatPercent(null)).toBe('-')
    expect(formatPercent(18)).toBe('18%')
  })
})

describe('plural', () => {
  it('chooses singular only for exactly one', () => {
    expect(plural(1, 'bill')).toBe('1 bill')
    expect(plural(0, 'bill')).toBe('0 bills')
    expect(plural(2, 'entry', 'entries')).toBe('2 entries')
  })
})

describe('today', () => {
  it('is yyyy-mm-dd', () => {
    expect(today()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
