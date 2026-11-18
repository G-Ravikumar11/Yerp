import { describe, expect, it } from 'vitest'
import { gstSplit } from './gstSplit'

describe('the tax inside an amount that already includes it', () => {
  it('is IGST at the full rate for a supply from another state', () => {
    expect(gstSplit(11800, 18, 'non_local')).toEqual({ base: 10000, tax: 1800, igst: 1800, cgst: 0, sgst: 0 })
  })
  it('is half CGST and half SGST for a local supply', () => {
    expect(gstSplit(11800, 18, 'local')).toEqual({ base: 10000, tax: 1800, igst: 0, cgst: 900, sgst: 900 })
  })
  it('keeps the paise together when it does not divide evenly', () => {
    const g = gstSplit(1000, 5, 'local')
    expect(g.base + g.tax).toBeCloseTo(1000, 2)
    expect(g.cgst + g.sgst).toBeCloseTo(g.tax, 2)
  })
  it('is nothing at a nil rate', () => {
    expect(gstSplit(500, 0, 'non_local')).toEqual({ base: 500, tax: 0, igst: 0, cgst: 0, sgst: 0 })
  })
})
