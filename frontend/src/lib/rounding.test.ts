import { describe, expect, it } from 'vitest'
import { formatRate, roundTo } from '@/lib/utils'
import { dimQty, dimTotal, blankDim } from '@/lib/measure'

describe('rounding', () => {
  it('rounds a half up, where Math.round on a float does not', () => {
    expect(roundTo(1.005)).toBe(1.01)
    expect(roundTo(2.675)).toBe(2.68)
    expect(roundTo(1.0005, 3)).toBe(1.001)
    expect(roundTo(-1.005)).toBe(-1.01)
    expect(roundTo(12.3456, 3)).toBe(12.346)
    expect(roundTo(100)).toBe(100)
  })

  it('shows a rate with the decimals it has, up to four', () => {
    expect(formatRate(12.5)).toBe('₹12.50')
    expect(formatRate(12.2225)).toBe('₹12.2225')
    expect(formatRate(1234.567)).toBe('₹1,234.567')
  })

  it('keeps a measured quantity to three decimals', () => {
    const line = { ...blankDim(), nos: 3, length: 2.345, breadth: 1.755 }
    expect(dimQty(line)).toBe(12.346)
    expect(dimTotal([line, line])).toBe(24.692)
  })
})
