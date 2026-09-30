import { describe, expect, it } from 'vitest'
import { clearRange, coerce, displayValue, fillRange, jump, planPaste, rangeNumbers, rangeText, rowIsBlank, validateRows } from './model'
import type { Column } from './types'

type Line = { code: string; desc: string; uom: string; qty: number | null; rate: number | null; done: boolean }
const blank = (): Line => ({ code: '', desc: '', uom: 'sqm', qty: null, rate: null, done: false })
const line = (over: Partial<Line> = {}): Line => ({ ...blank(), ...over })

const columns: Column<Line>[] = [
  { id: 'code', header: 'Code', readOnly: true, get: (_r, i) => `A-${i + 1}` },
  { id: 'desc', header: 'Description', required: true },
  { id: 'uom', header: 'UoM', type: 'select', options: ['sqm', 'cum', { value: 'MT', label: 'Tonne' }] },
  { id: 'qty', header: 'Qty', type: 'number', decimals: 2, validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null) },
  { id: 'rate', header: 'Rate', type: 'number' },
  { id: 'done', header: 'Done', type: 'checkbox' },
]

describe('blank rows', () => {
  it('is not made used by a pre-set picker, a tick box or a computed column', () => {
    expect(rowIsBlank(columns, blank(), 0)).toBe(true)
    expect(rowIsBlank(columns, line({ done: true, uom: 'cum' }), 0)).toBe(true)
  })

  it('is used once anything is typed', () => {
    expect(rowIsBlank(columns, line({ desc: 'Shuttering' }), 0)).toBe(false)
    expect(rowIsBlank(columns, line({ qty: 0 }), 0)).toBe(false)
  })
})

describe('coerce', () => {
  it('holds numbers as numbers and nothing as null', () => {
    expect(coerce(columns[3], '1,250.5')).toEqual({ ok: true, value: 1250.5 })
    expect(coerce(columns[3], '')).toEqual({ ok: true, value: null })
    expect(coerce(columns[3], 'x')).toMatchObject({ ok: false })
  })

  it('holds a choice by its value, matched by label', () => {
    expect(coerce(columns[2], 'tonne')).toEqual({ ok: true, value: 'MT' })
    expect(coerce(columns[2], 'kg')).toMatchObject({ ok: false })
  })

  it('trims text', () => {
    expect(coerce(columns[1], '  slab  ')).toEqual({ ok: true, value: 'slab' })
  })
})

describe('display', () => {
  it('formats numbers the Indian way and labels choices', () => {
    expect(displayValue(columns[3], line({ qty: 1234567.5 }), 0)).toBe('12,34,567.50')
    expect(displayValue(columns[3], blank(), 0)).toBe('')
    expect(displayValue(columns[2], line({ uom: 'MT' }), 0)).toBe('Tonne')
  })
})

describe('clearing and filling', () => {
  const rows = [line({ desc: 'a', qty: 1 }), line({ desc: 'b', qty: 2 }), line({ desc: 'c', qty: 3 })]

  it('clears editable cells to their empty value and leaves computed ones', () => {
    const out = clearRange(columns, rows, { r0: 0, r1: 1, c0: 0, c1: 3 })
    expect(out[0]).toMatchObject({ desc: '', qty: null })
    expect(out[1]).toMatchObject({ desc: '', qty: null })
    expect(out[2]).toMatchObject({ desc: 'c', qty: 3 })
    expect(rows[0].desc).toBe('a')
  })

  it('fills down from the first row of the range', () => {
    const out = fillRange(columns, rows, { r0: 0, r1: 2, c0: 3, c1: 3 }, 'down')
    expect(out.map((r) => r.qty)).toEqual([1, 1, 1])
  })

  it('fills right only between columns of the same type', () => {
    const r = [line({ qty: 5, rate: 9 })]
    const out = fillRange(columns, r, { r0: 0, r1: 0, c0: 3, c1: 5 }, 'right')
    expect(out[0].rate).toBe(5)
    expect(out[0].done).toBe(false)
  })
})

describe('pasting', () => {
  const at = (r: number, c: number, r1 = r, c1 = c) => ({ r0: r, r1, c0: c, c1 })

  it('drops a block at the cursor and grows the sheet to fit', () => {
    const res = planPaste(columns, [line()], [['Slab', 'cum', '10', '500'], ['Beam', 'sqm', '4', '650'], ['Wall', 'MT', '', '']], at(0, 1), blank)!
    expect(res.rows).toHaveLength(3)
    expect(res.added).toBe(2)
    expect(res.rows[0]).toMatchObject({ desc: 'Slab', uom: 'cum', qty: 10, rate: 500 })
    expect(res.rows[2]).toMatchObject({ desc: 'Wall', uom: 'MT' })
    expect(res.pasted).toBe(10)
  })

  it('skips computed columns and cells that will not take the value, and counts them', () => {
    const res = planPaste(columns, [line()], [['X-9', 'Slab', 'kg', 'lots']], at(0, 0), blank)!
    expect(res.rows[0]).toMatchObject({ desc: 'Slab', uom: 'sqm', qty: null })
    expect(res.skipped).toBe(3)
    expect(res.pasted).toBe(1)
  })

  it('does not wipe the cells under a hole in the block', () => {
    const res = planPaste(columns, [line({ desc: 'keep', qty: 7 })], [['', '', '']], at(0, 1), blank)!
    expect(res.rows[0]).toMatchObject({ desc: 'keep', qty: 7 })
  })

  it('paints one value over the whole selection', () => {
    const rows = [line(), line(), line()]
    const res = planPaste(columns, rows, [['5']], at(0, 3, 2, 4), blank)!
    expect(res.rows.map((r) => r.qty)).toEqual([5, 5, 5])
    expect(res.rows.map((r) => r.rate)).toEqual([5, 5, 5])
    expect(res.added).toBe(0)
  })

  it('cuts a block off at the last column', () => {
    const res = planPaste(columns, [line()], [['1', 'yes', '3', '4']], at(0, 4), blank)!
    expect(res.rows[0].rate).toBe(1)
    expect(res.skipped).toBe(2)
  })

  it('does nothing for an empty clipboard', () => {
    expect(planPaste(columns, [line()], [], at(0, 0), blank)).toBeNull()
  })
})

describe('copying', () => {
  it('writes unformatted text with a tab between cells and a line between rows', () => {
    const rows = [line({ desc: 'a', qty: 1234.5, uom: 'MT' }), line({ desc: 'b', done: true })]
    expect(rangeText(columns, rows, { r0: 0, r1: 1, c0: 1, c1: 5 })).toBe('a\tTonne\t1234.5\t\tFALSE\nb\tsqm\t\t\tTRUE')
  })
})

describe('Ctrl+Arrow', () => {
  const rows = [line({ desc: 'a' }), line({ desc: 'b' }), line({ desc: 'c' }), line(), line(), line({ desc: 'f' })]
  const total = 8

  it('runs to the end of a block of filled cells', () => {
    expect(jump(columns, rows, { r: 0, c: 1 }, 1, 0, total)).toEqual({ r: 2, c: 1 })
  })

  it('crosses a gap to the next filled cell', () => {
    expect(jump(columns, rows, { r: 2, c: 1 }, 1, 0, total)).toEqual({ r: 5, c: 1 })
  })

  it('goes to the edge when nothing further is filled', () => {
    expect(jump(columns, rows, { r: 5, c: 1 }, 1, 0, total)).toEqual({ r: 7, c: 1 })
    expect(jump(columns, rows, { r: 0, c: 1 }, -1, 0, total)).toEqual({ r: 0, c: 1 })
  })
})

describe('validation', () => {
  it('checks only rows that have been started', () => {
    const rows = [line(), line({ desc: 'x', qty: -2 }), line({ qty: 3 })]
    const out = validateRows(columns, rows)
    expect(out.has(0)).toBe(false)
    expect(out.get(1)).toEqual({ qty: 'Cannot be negative' })
    expect(out.get(2)).toEqual({ desc: 'Required' })
  })

  it('reads numbers out of a range for the status bar', () => {
    expect(rangeNumbers(columns, [line({ qty: 2, rate: 3 }), line({ qty: 4 })], { r0: 0, r1: 1, c0: 3, c1: 4 })).toEqual([2, 3, 4])
  })
})

describe('a pick column that also takes what is typed', () => {
  const col = { id: 'uom', header: 'Unit', type: 'select' as const, options: ['cum', 'sqm'], freeText: true }
  it('keeps a unit nobody listed, tidied', () => {
    expect(coerce(col, '  Lump sum ')).toEqual({ ok: true, value: 'Lump sum' })
  })
  it('still matches a listed unit whatever its case', () => {
    expect(coerce(col, 'SQM')).toEqual({ ok: true, value: 'sqm' })
  })
  it('refuses an unlisted one when the column is not free', () => {
    expect(coerce({ ...col, freeText: false }, 'Lump sum')).toEqual({ ok: false, error: 'Not one of the choices' })
  })
})
