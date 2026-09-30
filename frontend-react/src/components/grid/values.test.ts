import { describe, expect, it } from 'vitest'
import { evalArithmetic, formatDate, matchOption, parseBoolean, parseDate, parseNumber, parseTSV, toTSV } from './values'

describe('evalArithmetic', () => {
  it('does the sums an engineer types into a quantity', () => {
    expect(evalArithmetic('12.5*8')).toBe(100)
    expect(evalArithmetic('(4+2)*3.5')).toBe(21)
    expect(evalArithmetic('10/4')).toBe(2.5)
    expect(evalArithmetic('-3+5')).toBe(2)
    expect(evalArithmetic('2*-3')).toBe(-6)
  })

  it('reads x and × between figures as multiply', () => {
    expect(evalArithmetic('12x3.5')).toBe(42)
    expect(evalArithmetic('4 × 2.5')).toBe(10)
  })

  it('does not let float noise through', () => {
    expect(evalArithmetic('0.1+0.2')).toBe(0.3)
  })

  it('refuses anything that is not arithmetic', () => {
    expect(evalArithmetic('alert(1)')).toBeNull()
    expect(evalArithmetic('2**3')).toBeNull()
    expect(evalArithmetic('(2+3')).toBeNull()
    expect(evalArithmetic('5/0')).toBeNull()
    expect(evalArithmetic('')).toBeNull()
    expect(evalArithmetic('1+')).toBeNull()
  })
})

describe('parseNumber', () => {
  it('reads Indian and western grouping, rupees and a leading =', () => {
    expect(parseNumber('1,20,000.50')).toEqual({ ok: true, value: 120000.5 })
    expect(parseNumber('1,200,000')).toEqual({ ok: true, value: 1200000 })
    expect(parseNumber('₹ 4,500')).toEqual({ ok: true, value: 4500 })
    expect(parseNumber('Rs. 75')).toEqual({ ok: true, value: 75 })
    expect(parseNumber('=6*7')).toEqual({ ok: true, value: 42 })
    expect(parseNumber('-0.5')).toEqual({ ok: true, value: -0.5 })
  })

  it('treats empty as nothing, not nought', () => {
    expect(parseNumber('')).toEqual({ ok: true, value: null })
    expect(parseNumber('   ')).toEqual({ ok: true, value: null })
  })

  it('says so when it is not a number', () => {
    expect(parseNumber('abc')).toEqual({ ok: false, error: 'Not a number' })
    expect(parseNumber('12abc')).toEqual({ ok: false, error: 'Not a number' })
  })
})

describe('parseDate', () => {
  it('reads the ways a date is written here', () => {
    for (const s of ['2026-10-01', '01-10-2026', '1/10/2026', '1.10.26', '1 Oct 2026', '01-Oct-2026']) {
      expect(parseDate(s), s).toEqual({ ok: true, value: '2026-10-01' })
    }
  })

  it('refuses a day that does not exist', () => {
    expect(parseDate('31-02-2026').ok).toBe(false)
    expect(parseDate('2026-13-01').ok).toBe(false)
    expect(parseDate('soon').ok).toBe(false)
  })

  it('takes a leap day only in a leap year', () => {
    expect(parseDate('29-02-2028').ok).toBe(true)
    expect(parseDate('29-02-2027').ok).toBe(false)
  })

  it('formats for reading', () => {
    expect(formatDate('2026-10-01')).toBe('01 Oct 2026')
  })
})

describe('options and booleans', () => {
  const options = [{ value: 'sqm', label: 'Sq. metre' }, 'cum', 'MT']

  it('matches by value or label, ignoring case', () => {
    expect(matchOption(options, 'SQM')).toEqual(options[0])
    expect(matchOption(options, 'sq. metre')).toEqual(options[0])
    expect(matchOption(options, 'mt')).toBe('MT')
    expect(matchOption(options, 'kg')).toBeUndefined()
    expect(matchOption(options, '')).toBeUndefined()
  })

  it('reads yes and no', () => {
    expect(parseBoolean('Yes')).toEqual({ ok: true, value: true })
    expect(parseBoolean('x')).toEqual({ ok: true, value: true })
    expect(parseBoolean('')).toEqual({ ok: true, value: false })
    expect(parseBoolean('maybe').ok).toBe(false)
  })
})

describe('clipboard text', () => {
  it('splits what Excel copies into rows and cells', () => {
    expect(parseTSV('a\tb\nc\td\n')).toEqual([
      ['a', 'b'],
      ['c', 'd'],
    ])
  })

  it('keeps empty cells and drops only the trailing line end', () => {
    expect(parseTSV('a\t\tc\n\t\t\n')).toEqual([
      ['a', '', 'c'],
      ['', '', ''],
    ])
  })

  it('reads a quoted cell holding a tab, a line end and a quote', () => {
    expect(parseTSV('"line one\nline two"\t"say ""hi"""\tplain')).toEqual([['line one\nline two', 'say "hi"', 'plain']])
  })

  it('accepts Windows line ends', () => {
    expect(parseTSV('a\r\nb\r\n')).toEqual([['a'], ['b']])
  })

  it('round-trips through toTSV', () => {
    const m = [
      ['plain', 'has\ttab', 'has\nnewline', 'has "quote"'],
      ['', '1.5', '', 'x'],
    ]
    expect(parseTSV(toTSV(m))).toEqual(m)
  })
})
