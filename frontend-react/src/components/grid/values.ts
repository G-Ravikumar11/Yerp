import type { CellValue, Option } from './types'

/* ==========================================================================
   Turning what was typed, or pasted from Excel, into what a cell holds.
   Nothing here touches the DOM, so all of it can be tested on its own.
   ========================================================================== */

export type Parsed<V> = { ok: true; value: V } | { ok: false; error: string }

const round = (n: number) => Math.round(n * 1e6) / 1e6

/**
 * +, -, *, / and brackets over plain numbers - "12.5*8", "(4+2)*3.5". Written
 * by hand rather than handed to eval: what is typed into a cell is data.
 * `x` and `×` between figures mean multiply, as a site engineer writes it.
 */
export function evalArithmetic(source: string): number | null {
  const s = source.replace(/\s+/g, '').replace(/(?<=[\d.)])[x×](?=[\d.(])/gi, '*')
  if (!s || /[^\d.+\-*/()]/.test(s)) return null
  let i = 0

  const fail = () => {
    throw new Error('bad expression')
  }
  const factor = (): number => {
    const ch = s[i]
    if (ch === '-') {
      i++
      return -factor()
    }
    if (ch === '+') {
      i++
      return factor()
    }
    if (ch === '(') {
      i++
      const v = expr()
      if (s[i++] !== ')') fail()
      return v
    }
    const m = /^(\d+\.?\d*|\.\d+)/.exec(s.slice(i))
    if (!m) return fail() as never
    i += m[0].length
    return parseFloat(m[0])
  }
  const term = (): number => {
    let v = factor()
    while (s[i] === '*' || s[i] === '/') {
      const op = s[i++]
      const r = factor()
      if (op === '/' && r === 0) fail()
      v = op === '*' ? v * r : v / r
    }
    return v
  }
  const expr = (): number => {
    let v = term()
    while (s[i] === '+' || s[i] === '-') {
      const op = s[i++]
      const r = term()
      v = op === '+' ? v + r : v - r
    }
    return v
  }

  try {
    const v = expr()
    return i === s.length && Number.isFinite(v) ? round(v) : null
  } catch {
    return null
  }
}

/**
 * A number the way people write it: 1,20,000.50 or 1,200,000 or ₹ 4500 or
 * 12.5*8. Empty is nothing, not nought.
 */
export function parseNumber(raw: string): Parsed<number | null> {
  let s = String(raw).trim().replace(/^=/, '')
  if (!s) return { ok: true, value: null }
  s = s.replace(/₹|rs\.?/gi, '').replace(/,/g, '').replace(/\s+/g, '')
  if (/^[+-]?(\d+\.?\d*|\.\d+)$/.test(s)) return { ok: true, value: parseFloat(s) }
  const v = evalArithmetic(s)
  return v === null ? { ok: false, error: 'Not a number' } : { ok: true, value: v }
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const pad = (n: number) => String(n).padStart(2, '0')

function iso(y: number, m: number, d: number): string | null {
  if (y < 1900 || y > 2200 || m < 1 || m > 12 || d < 1) return null
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return d > last ? null : `${y}-${pad(m)}-${pad(d)}`
}

/** 2026-10-01, 01-10-2026, 1/10/26, 1.10.2026 or 1 Oct 2026 - as an ISO date. */
export function parseDate(raw: string): Parsed<string> {
  const s = String(raw).trim()
  if (!s) return { ok: true, value: '' }
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(s)
  let out: string | null = null
  if (m) out = iso(+m[1], +m[2], +m[3])
  else if ((m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$/.exec(s))) {
    const year = m[3].length === 2 ? 2000 + +m[3] : +m[3]
    out = iso(year, +m[2], +m[1])
  } else if ((m = /^(\d{1,2})[\s-]+([a-z]{3})[a-z]*[\s,-]+(\d{2}|\d{4})$/i.exec(s))) {
    const mi = MONTHS.indexOf(m[2].toLowerCase())
    const year = m[3].length === 2 ? 2000 + +m[3] : +m[3]
    if (mi >= 0) out = iso(year, mi + 1, +m[1])
  }
  return out ? { ok: true, value: out } : { ok: false, error: 'Not a date - try 01-10-2026' }
}

export function formatDate(isoDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate)
  if (!m) return isoDate
  return `${m[3]} ${MONTHS[+m[2] - 1][0].toUpperCase()}${MONTHS[+m[2] - 1].slice(1)} ${m[1]}`
}

export const optionValue = (o: Option) => (typeof o === 'string' ? o : o.value)
export const optionLabel = (o: Option) => (typeof o === 'string' ? o : o.label)

/** The option meant by a typed or pasted word: by value or label, ignoring case. */
export function matchOption(options: readonly Option[] | undefined, raw: string): Option | undefined {
  const w = String(raw).trim().toLowerCase()
  if (!w) return undefined
  return options?.find((o) => optionValue(o).toLowerCase() === w || optionLabel(o).toLowerCase() === w)
}

export function parseBoolean(raw: string): Parsed<boolean> {
  const w = String(raw).trim().toLowerCase()
  if (['true', 'yes', 'y', '1', 'x', '✓', 'on'].includes(w)) return { ok: true, value: true }
  if (['false', 'no', 'n', '0', '', 'off'].includes(w)) return { ok: true, value: false }
  return { ok: false, error: 'Yes or no' }
}

export function isEmptyValue(v: CellValue): boolean {
  return v === null || v === undefined || v === '' || v === false
}

/* --- Clipboard text ------------------------------------------------------ */

/**
 * Tab-separated text as Excel puts it on the clipboard: cells split on tabs,
 * rows on line ends, and a cell that holds a tab, a line end or a quote is
 * wrapped in quotes with its own quotes doubled. Excel always ends the block
 * with a line end, which is not a row.
 */
export function parseTSV(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  let i = 0
  const t = text.replace(/\r\n?/g, '\n')

  while (i < t.length) {
    const ch = t[i]
    if (quoted) {
      if (ch === '"') {
        if (t[i + 1] === '"') {
          cell += '"'
          i++
        } else quoted = false
      } else cell += ch
    } else if (ch === '"' && cell === '') quoted = true
    else if (ch === '\t') {
      row.push(cell)
      cell = ''
    } else if (ch === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else cell += ch
    i++
  }
  if (cell !== '' || row.length) {
    row.push(cell)
    rows.push(row)
  }
  return rows
}

export function toTSV(matrix: string[][]): string {
  const esc = (s: string) => (/[\t\n\r"]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)
  return matrix.map((r) => r.map(esc).join('\t')).join('\n')
}
