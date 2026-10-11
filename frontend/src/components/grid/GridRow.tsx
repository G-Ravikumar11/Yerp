import { memo } from 'react'
import { AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { displayValue, getValue, isReadOnly } from './model'
import type { Column } from './types'

export const ROW_NUMBER_WIDTH = 52

export interface Layout {
  widths: number[]
  /** `left` offset for a pinned column, null for one that scrolls. */
  pinLeft: (number | null)[]
  total: number
  /** Everything that stays put on the left, for scroll padding. */
  pinned: number
}

export function buildLayout<T>(columns: readonly Column<T>[]): Layout {
  const widths = columns.map((c) => c.width ?? (c.type === 'number' ? 120 : c.type === 'date' ? 130 : c.type === 'select' ? 140 : c.type === 'checkbox' ? 84 : 220))
  let pinned = ROW_NUMBER_WIDTH
  const pinLeft = columns.map((c, i) => {
    if (!c.pin) return null
    const left = pinned
    pinned += widths[i]
    return left
  })
  return { widths, pinLeft, total: ROW_NUMBER_WIDTH + widths.reduce((a, b) => a + b, 0), pinned }
}

export interface Handlers {
  cellDown: (r: number, c: number, e: React.MouseEvent) => void
  cellEnter: (r: number, c: number) => void
  cellDouble: (r: number, c: number) => void
  rowHeaderDown: (r: number, e: React.MouseEvent) => void
  toggle: (r: number, c: number) => void
}

export const cellId = (gridId: string, r: number, c: number) => `${gridId}-r${r}c${c}`

interface RowProps<T> {
  gridId: string
  row: T
  index: number
  columns: readonly Column<T>[]
  layout: Layout
  top: number
  height: number
  /** Column of the active cell if it is on this row, else -1. */
  activeC: number
  /** Selected columns on this row, else -1 / -1. */
  rc0: number
  rc1: number
  rowSelected: boolean
  editC: number
  editor?: React.ReactNode
  focused: boolean
  errors?: Record<string, string>
  blank: boolean
  /** The first empty row is prompted; the rest stay quiet. */
  promptRow: boolean
  className?: string
  handlers: Handlers
}

function GridRowImpl<T>({
  gridId,
  row,
  index,
  columns,
  layout,
  top,
  height,
  activeC,
  rc0,
  rc1,
  rowSelected,
  editC,
  editor,
  focused,
  errors,
  blank,
  promptRow,
  className,
  handlers,
}: RowProps<T>) {
  return (
    <div
      role="row"
      aria-rowindex={index + 2}
      className={cn('absolute left-0 flex', className)}
      style={{ top, height, width: layout.total }}
    >
      <div
        role="rowheader"
        onMouseDown={(e) => handlers.rowHeaderDown(index, e)}
        style={{ width: ROW_NUMBER_WIDTH }}
        className={cn(
          'sticky left-0 z-10 flex shrink-0 select-none items-center justify-end gap-1 border-b border-r border-border pr-2 text-[11px] tabular',
          rowSelected ? 'bg-select font-semibold text-primary' : 'bg-surface text-subtle',
        )}
      >
        {errors && <AlertCircle className="size-3 text-danger" aria-label="Has a problem" />}
        {blank && !rowSelected ? <span className="opacity-40">{index + 1}</span> : index + 1}
      </div>

      {columns.map((col, c) => {
        const readOnly = isReadOnly(col, row, index)
        const selected = c >= rc0 && c <= rc1
        const active = c === activeC
        const editing = c === editC
        const error = errors?.[col.id]
        const pin = layout.pinLeft[c]
        const text = displayValue(col, row, index)
        const right = (col.align ?? (col.type === 'number' ? 'right' : 'left')) === 'right'
        const center = col.align === 'center' || col.type === 'checkbox'

        return (
          <div
            key={col.id}
            id={cellId(gridId, index, c)}
            role="gridcell"
            aria-colindex={c + 2}
            aria-selected={selected || active}
            aria-readonly={readOnly || undefined}
            aria-invalid={error ? true : undefined}
            title={error}
            onMouseDown={(e) => handlers.cellDown(index, c, e)}
            onMouseEnter={() => handlers.cellEnter(index, c)}
            onDoubleClick={() => handlers.cellDouble(index, c)}
            style={{ width: layout.widths[c], left: pin ?? undefined }}
            className={cn(
              'relative flex shrink-0 select-none items-center border-b border-r border-border px-2.5 text-[13px]',
              pin !== null && 'sticky z-10',
              pin !== null && !selected && !error && (readOnly ? 'bg-surface' : 'bg-card'),
              readOnly && !selected && 'bg-surface/60 text-muted-foreground',
              right && !center && 'justify-end tabular',
              center && 'justify-center',
              col.mono && 'font-mono text-xs',
              selected && !active && 'bg-select',
              error && !selected && 'bg-invalid',
              active && (focused ? 'shadow-[inset_0_0_0_2px_var(--primary)]' : 'shadow-[inset_0_0_0_1.5px_var(--subtle)]'),
              active && (pin !== null ? 'z-[11] bg-card' : 'z-[5] bg-card'),
            )}
          >
            {editing ? (
              editor
            ) : col.type === 'checkbox' ? (
              <input
                type="checkbox"
                tabIndex={-1}
                checked={!!getValue(col, row, index)}
                disabled={readOnly}
                onChange={() => handlers.toggle(index, c)}
                aria-label={col.header}
                className="size-4 accent-[var(--primary)]"
              />
            ) : text ? (
              <span className="truncate">{text}</span>
            ) : promptRow && col.placeholder && !readOnly ? (
              <span className="truncate text-subtle">{col.placeholder}</span>
            ) : null}
            {error && !editing && <span aria-hidden className="absolute right-0 top-0 size-0 border-l-[8px] border-t-[8px] border-l-transparent border-t-danger" />}
          </div>
        )
      })}
    </div>
  )
}

export const GridRow = memo(GridRowImpl) as typeof GridRowImpl
