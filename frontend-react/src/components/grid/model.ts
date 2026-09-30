import type { Cell, CellValue, Column, Range } from './types'
import {
  formatDate,
  isEmptyValue,
  matchOption,
  optionLabel,
  optionValue,
  parseBoolean,
  parseDate,
  parseNumber,
  toTSV,
  type Parsed,
} from './values'

/* ==========================================================================
   The grid's rules, with no React in them: what a cell holds, whether a row
   has been started, what a paste or a fill does to the rows. Every function
   takes rows and returns new rows; nothing is changed in place.
   ========================================================================== */

export type Rows<T> = readonly T[]

export function getValue<T>(col: Column<T>, row: T, index: number): CellValue {
  if (col.get) return col.get(row, index)
  return (row as Record<string, CellValue>)[col.id]
}

export function setValue<T>(col: Column<T>, row: T, value: CellValue): T {
  if (col.set) return col.set(row, value)
  return { ...row, [col.id]: value }
}

export function isReadOnly<T>(col: Column<T>, row: T, index: number): boolean {
  return typeof col.readOnly === 'function' ? col.readOnly(row, index) : !!col.readOnly
}

/** A pre-set picker or a tick box is not data; typed text, numbers and dates are. */
function countsAsData<T>(col: Column<T>): boolean {
  if (col.countsAsData !== undefined) return col.countsAsData
  return col.type !== 'select' && col.type !== 'checkbox' && !col.get
}

export function rowIsBlank<T>(columns: readonly Column<T>[], row: T, index: number): boolean {
  return columns.every((c) => !countsAsData(c) || isEmptyValue(getValue(c, row, index)))
}

export function emptyFor<T>(col: Column<T>): CellValue {
  if (col.empty !== undefined) return col.empty
  switch (col.type) {
    case 'number':
      return null
    case 'checkbox':
      return false
    default:
      return ''
  }
}

/** How a value reads in a cell that is not being edited. */
export function displayValue<T>(col: Column<T>, row: T, index: number): string {
  const v = getValue(col, row, index)
  if (col.format) return col.format(v, row, index)
  if (v === null || v === undefined || v === '') return ''
  if (v === false && col.type !== 'checkbox') return ''
  switch (col.type) {
    case 'number': {
      const n = typeof v === 'number' ? v : parseFloat(String(v))
      if (!Number.isFinite(n)) return String(v)
      return n.toLocaleString('en-IN', {
        minimumFractionDigits: col.decimals ?? 0,
        maximumFractionDigits: col.decimals ?? 3,
      })
    }
    case 'date':
      return formatDate(String(v))
    case 'select': {
      const o = col.options?.find((x) => optionValue(x) === String(v))
      return o ? optionLabel(o) : String(v)
    }
    case 'checkbox':
      return v ? 'Yes' : ''
    default:
      return String(v)
  }
}

/** The value as text a person, or Excel, would type: unformatted. */
export function editText<T>(col: Column<T>, row: T, index: number): string {
  const v = getValue(col, row, index)
  if (col.type === 'checkbox') return v ? 'TRUE' : 'FALSE'
  if (isEmptyValue(v)) return ''
  if (col.type === 'select') {
    const o = col.options?.find((x) => optionValue(x) === String(v))
    return o ? optionLabel(o) : String(v)
  }
  return String(v)
}

/** Text -> the value the column holds, or why it cannot. */
export function coerce<T>(col: Column<T>, raw: string): Parsed<CellValue> {
  switch (col.type) {
    case 'number':
      return parseNumber(raw)
    case 'date':
      return parseDate(raw)
    case 'checkbox':
      return parseBoolean(raw)
    case 'select': {
      if (!raw.trim()) return { ok: true, value: emptyFor(col) }
      const o = matchOption(col.options, raw)
      return o ? { ok: true, value: optionValue(o) } : col.freeText && raw.trim() ? { ok: true, value: raw.trim() } : { ok: false, error: 'Not one of the choices' }
    }
    default:
      return { ok: true, value: raw.trim() }
  }
}

/* --- Ranges -------------------------------------------------------------- */

export function makeRange(a: Cell, b: Cell): Range {
  return { r0: Math.min(a.r, b.r), r1: Math.max(a.r, b.r), c0: Math.min(a.c, b.c), c1: Math.max(a.c, b.c) }
}

export const inRange = (rg: Range, r: number, c: number) => r >= rg.r0 && r <= rg.r1 && c >= rg.c0 && c <= rg.c1

/** Every cell of the range as unformatted text, ready for the clipboard. */
export function rangeText<T>(columns: readonly Column<T>[], rows: Rows<T>, rg: Range): string {
  const matrix: string[][] = []
  for (let r = rg.r0; r <= Math.min(rg.r1, rows.length - 1); r++) {
    const line: string[] = []
    for (let c = rg.c0; c <= rg.c1; c++) line.push(editText(columns[c], rows[r], r))
    matrix.push(line)
  }
  return toTSV(matrix)
}

/** Rows out to `count`, padded with fresh blanks - a paste can run past the end. */
export function withRows<T>(rows: Rows<T>, count: number, newRow: () => T): T[] {
  const out = rows.slice()
  while (out.length < count) out.push(newRow())
  return out
}

function writeCell<T>(columns: readonly Column<T>[], out: T[], r: number, c: number, value: CellValue): boolean {
  const col = columns[c]
  if (!col || isReadOnly(col, out[r], r)) return false
  out[r] = setValue(col, out[r], value)
  return true
}

/** Empty every editable cell in the range. */
export function clearRange<T>(columns: readonly Column<T>[], rows: Rows<T>, rg: Range): T[] {
  const out = rows.slice()
  for (let r = rg.r0; r <= Math.min(rg.r1, out.length - 1); r++)
    for (let c = rg.c0; c <= rg.c1; c++) writeCell(columns, out, r, c, emptyFor(columns[c]))
  return out
}

/** Ctrl+D / Ctrl+R: the first row (or column) of the range repeated across the rest. */
export function fillRange<T>(columns: readonly Column<T>[], rows: Rows<T>, rg: Range, dir: 'down' | 'right'): T[] {
  const out = rows.slice()
  if (dir === 'down') {
    for (let c = rg.c0; c <= rg.c1; c++) {
      const source = getValue(columns[c], out[rg.r0], rg.r0)
      for (let r = rg.r0 + 1; r <= Math.min(rg.r1, out.length - 1); r++) writeCell(columns, out, r, c, source)
    }
  } else {
    for (let r = rg.r0; r <= Math.min(rg.r1, out.length - 1); r++) {
      const source = getValue(columns[rg.c0], out[r], r)
      for (let c = rg.c0 + 1; c <= rg.c1; c++) {
        const src = columns[rg.c0]
        const dst = columns[c]
        if (src.type === dst.type) writeCell(columns, out, r, c, source)
      }
    }
  }
  return out
}

export interface PasteResult<T> {
  rows: T[]
  range: Range
  pasted: number
  skipped: number
  added: number
}

/**
 * Drop a block of text onto the sheet.
 *
 * From one cell it lands with its top-left corner there and grows the sheet
 * to fit, however far down it runs. One value onto a selection of many fills
 * every cell of it, as Excel does. Cells that are computed, or that cannot
 * hold what was pasted, are left alone and counted so the person is told.
 */
export function planPaste<T>(
  columns: readonly Column<T>[],
  rows: Rows<T>,
  matrix: string[][],
  selection: Range,
  newRow: () => T,
): PasteResult<T> | null {
  if (!matrix.length || !matrix.some((l) => l.length)) return null

  const single = matrix.length === 1 && matrix[0].length === 1
  const targetRows = single ? selection.r1 - selection.r0 + 1 : matrix.length
  const targetCols = single ? selection.c1 - selection.c0 + 1 : Math.max(...matrix.map((l) => l.length))
  const lastRow = selection.r0 + targetRows - 1
  const out = withRows(rows, lastRow + 1, newRow)
  const added = out.length - rows.length

  let pasted = 0
  let skipped = 0
  for (let dr = 0; dr < targetRows; dr++) {
    for (let dc = 0; dc < targetCols; dc++) {
      const c = selection.c0 + dc
      if (c >= columns.length) {
        skipped++
        continue
      }
      const text = single ? matrix[0][0] : (matrix[dr]?.[dc] ?? '')
      const r = selection.r0 + dr
      const col = columns[c]
      if (isReadOnly(col, out[r], r)) {
        skipped++
        continue
      }
      const parsed = coerce(col, text)
      if (!parsed.ok) {
        skipped++
        continue
      }
      // Pasted-over blanks are still blanks: only write what came, so a block
      // with holes does not wipe the cells under them - except one value
      // painted over a selection, which is the point of it.
      if (text === '' && !single) continue
      writeCell(columns, out, r, c, parsed.value)
      pasted++
    }
  }

  return {
    rows: out,
    range: { r0: selection.r0, r1: lastRow, c0: selection.c0, c1: Math.min(columns.length - 1, selection.c0 + targetCols - 1) },
    pasted,
    skipped,
    added,
  }
}

/* --- Moving about -------------------------------------------------------- */

export const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n))

/**
 * Ctrl+Arrow, as Excel does it: from a cell with something in it, to the end
 * of the run of filled cells; from an empty one (or the end of a run), to the
 * next filled cell; failing that, to the edge of the sheet.
 */
export function jump<T>(
  columns: readonly Column<T>[],
  rows: Rows<T>,
  from: Cell,
  dr: number,
  dc: number,
  rowCount: number,
): Cell {
  const filled = (r: number, c: number) => r < rows.length && !isEmptyValue(getValue(columns[c], rows[r], r))
  const inside = (r: number, c: number) => r >= 0 && r < rowCount && c >= 0 && c < columns.length
  let { r, c } = from
  const nr = r + dr
  const nc = c + dc
  if (!inside(nr, nc)) return from

  if (filled(r, c) && filled(nr, nc)) {
    while (inside(r + dr, c + dc) && filled(r + dr, c + dc)) {
      r += dr
      c += dc
    }
    return { r, c }
  }
  r = nr
  c = nc
  while (inside(r + dr, c + dc) && !filled(r, c)) {
    r += dr
    c += dc
  }
  return { r, c }
}

/** Data rows only, for status-bar sums: numbers in the range, ignoring the rest. */
export function rangeNumbers<T>(columns: readonly Column<T>[], rows: Rows<T>, rg: Range): number[] {
  const nums: number[] = []
  for (let r = rg.r0; r <= Math.min(rg.r1, rows.length - 1); r++)
    for (let c = rg.c0; c <= rg.c1; c++) {
      const v = getValue(columns[c], rows[r], r)
      if (typeof v === 'number' && Number.isFinite(v)) nums.push(v)
    }
  return nums
}

/** What is wrong with each row that has been started: column id -> reason. */
export function validateRows<T>(columns: readonly Column<T>[], rows: Rows<T>): Map<number, Record<string, string>> {
  const out = new Map<number, Record<string, string>>()
  rows.forEach((row, r) => {
    if (rowIsBlank(columns, row, r)) return
    let errors: Record<string, string> | undefined
    for (const col of columns) {
      const v = getValue(col, row, r)
      let message: string | null | undefined
      if (col.required && isEmptyValue(v) && !isReadOnly(col, row, r)) message = 'Required'
      else if (col.validate && !isEmptyValue(v)) message = col.validate(v, row, r)
      if (message) (errors ??= {})[col.id] = message
    }
    if (errors) out.set(r, errors)
  })
  return out
}
