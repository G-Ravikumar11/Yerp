import { describe, expect, it } from 'vitest'
import { blankDim, dimQty, dimTotal, type DimLine } from './measure'

const dim = (over: Partial<DimLine>): DimLine => ({ ...blankDim(), ...over })

describe('dimQty', () => {
  it('multiplies the figures that were given', () => {
    expect(dimQty(dim({ nos: 2, nom: 1, length: 12.5, breadth: 8 }))).toBe(200)
  })

  it('does not treat a blank as nought - an area has no depth', () => {
    expect(dimQty(dim({ length: 10, breadth: 4 }))).toBe(40)
  })

  it('does treat a typed nought as nought', () => {
    expect(dimQty(dim({ length: 10, breadth: 0 }))).toBe(0)
  })

  it('takes a deduction away', () => {
    expect(dimQty(dim({ nos: 1, length: 2, breadth: 1.5, deduct: true }))).toBe(-3)
  })

  it('measures nothing for a heading or a line with no figures', () => {
    expect(dimQty(dim({ particulars: 'Living Room', heading: true, length: 5 }))).toBeNull()
    expect(dimQty(dim({ particulars: 'nothing yet' }))).toBeNull()
  })

  it('rounds to three places like the current book', () => {
    expect(dimQty(dim({ length: 1.23456, breadth: 2 }))).toBe(2.469)
  })

  it('never returns a negative zero', () => {
    expect(Object.is(dimQty(dim({ length: 0, deduct: true })), 0)).toBe(true)
  })
})

describe('dimTotal', () => {
  it('adds the lines and takes the deductions off', () => {
    const lines = [
      dim({ particulars: 'Slab', nos: 1, length: 12.5, breadth: 8 }),
      dim({ particulars: 'Beam', nos: 4, length: 6, breadth: 0.6 }),
      dim({ particulars: 'Deductions', heading: true }),
      dim({ particulars: 'Opening', nos: 2, length: 1, breadth: 1.2, deduct: true }),
    ]
    expect(dimTotal(lines)).toBe(100 + 14.4 - 2.4)
  })
})
