import type { ReactNode } from 'react'

export type CellValue = string | number | boolean | null | undefined
export type ColumnType = 'text' | 'number' | 'select' | 'date' | 'checkbox'
export type Option = string | { value: string; label: string }

/**
 * What a column is. The grid never reaches into a row itself: it asks the
 * column to `get` a value and to `set` one, so a row can be any shape and a
 * column can be computed from the others.
 */
export interface Column<T> {
  /** Also the field read and written on the row, unless `get` / `set` say otherwise. */
  id: string
  header: string
  /** A second, quieter line under the header - the unit, or what to enter. */
  hint?: string
  type?: ColumnType
  /** Pixels. */
  width?: number
  align?: 'left' | 'right' | 'center'
  /** For `select` columns: the only answers there are. */
  options?: readonly Option[]
  /** A computed column is `readOnly` with a `get`. May depend on the row. */
  readOnly?: boolean | ((row: T, index: number) => boolean)
  get?: (row: T, index: number) => CellValue
  set?: (row: T, value: CellValue) => T
  /** How the value reads when it is not being edited. */
  format?: (value: CellValue, row: T, index: number) => string
  /** A reason the value is wrong, or nothing. Only asked of rows that have data. */
  validate?: (value: CellValue, row: T, index: number) => string | null | undefined
  /** A row that has anything in it must have this too. */
  required?: boolean
  placeholder?: string
  /** Decimal places shown for a number. Editing never rounds what was typed. */
  decimals?: number
  mono?: boolean
  /** Stays in view while the sheet scrolls sideways. Only the leading columns. */
  pin?: boolean
  /** A total pinned under the column. */
  summary?: 'sum' | ((rows: readonly T[]) => string)
  /**
   * Whether a value here means the row has been started. A picker that
   * always has an answer, or a tick box, does not: they must not make a
   * blank row look used.
   */
  countsAsData?: boolean
  /** What clearing the cell leaves. */
  empty?: CellValue
}

export interface Cell {
  r: number
  c: number
}

export interface Range {
  r0: number
  r1: number
  c0: number
  c1: number
}

export type ChangeKind = 'edit' | 'paste' | 'clear' | 'fill' | 'cut' | 'insert' | 'delete' | 'undo' | 'redo'

export interface ChangeInfo {
  kind: ChangeKind
  /** The cells touched, where that means anything (not for undo / redo). */
  range?: Range
}

export interface GridHandle {
  focus: () => void
  undo: () => void
  redo: () => void
  selectCell: (r: number, c: number) => void
}

export interface DataGridProps<T> {
  columns: readonly Column<T>[]
  rows: readonly T[]
  onRowsChange: (rows: T[], info: ChangeInfo) => void
  /** A fresh blank row. Used for the row waiting at the bottom and for pasting past the end. */
  newRow: () => T
  /** Defaults to: no column that counts as data has anything in it. */
  isBlank?: (row: T, index: number) => boolean
  /** Keep one empty row waiting under the last, the way a sheet does. Default on. */
  autoGrow?: boolean
  /** Show at least this many rows, padding with blanks. */
  minRows?: number
  readOnly?: boolean
  /** Visible height of the body in pixels before it scrolls. */
  maxHeight?: number
  rowHeight?: number
  rowClassName?: (row: T, index: number) => string | undefined
  /** Anything that belongs beside the row count in the status bar. */
  footer?: ReactNode
  onSelectionChange?: (range: Range | null) => void
  'aria-label': string
  className?: string
  emptyText?: string
  ref?: React.Ref<GridHandle>
}
