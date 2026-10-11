import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Card, SkeletonRows } from '@/components/ui'

export interface TableColumn<T> {
  id: string
  header: React.ReactNode
  cell: (row: T, index: number) => React.ReactNode
  align?: 'left' | 'right' | 'center'
  /** A CSS width - "7rem". Columns without one share what is left. */
  width?: string
  /** What to sort on. Without it the header is just a label. */
  sort?: (row: T) => string | number
  /** Drop the column on narrow screens rather than scroll sideways. */
  hideBelow?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}

const hide = { sm: 'max-sm:hidden', md: 'max-md:hidden', lg: 'max-lg:hidden', xl: 'max-xl:hidden' } as const
const alignment = { left: 'text-left', right: 'text-right tabular', center: 'text-center' } as const

/**
 * A read-only list: sticky header, click-to-sort where a column says how,
 * keyboard-openable rows, and a proper empty and loading state. Lists that are
 * edited in place use the data grid; this is for reading and picking.
 */
/** Ticking rows to act on them together - delete, say. Only the rows `canSelect` allows have a box. */
export interface Selection<T> {
  selected: ReadonlySet<string | number>
  onChange: (next: Set<string | number>) => void
  canSelect?: (row: T) => boolean
}

export function DataTable<T>({
  rows,
  selection,
  columns,
  rowKey,
  onRowClick,
  loading,
  empty = 'Nothing here yet.',
  footer,
  label,
  rowClassName,
  className,
}: {
  rows: readonly T[]
  selection?: Selection<T>
  columns: readonly TableColumn<T>[]
  rowKey: (row: T, index: number) => string | number
  onRowClick?: (row: T) => void
  loading?: boolean
  empty?: React.ReactNode
  footer?: React.ReactNode
  label: string
  rowClassName?: (row: T) => string | undefined
  className?: string
}) {
  const [sort, setSort] = useState<{ id: string; dir: 1 | -1 } | null>(null)
  // The page passes `selection` and `rowKey` afresh on every render; what can be ticked changes only with the rows.
  const latest = useRef({ rowKey, canSelect: selection?.canSelect })
  latest.current = { rowKey, canSelect: selection?.canSelect }
  const on = !!selection
  const selectable = useMemo(() => {
    const { rowKey: key, canSelect } = latest.current
    return on ? rows.flatMap((r, i) => (!canSelect || canSelect(r) ? [key(r, i)] : [])) : []
  }, [rows, on])
  // A row the filters no longer show is no longer ticked: Delete acts on what is in front of you, never on rows out of sight.
  useEffect(() => {
    if (!selection || loading || selection.selected.size === 0) return
    const shown = new Set(selectable)
    const kept = [...selection.selected].filter((k) => shown.has(k))
    if (kept.length !== selection.selected.size) selection.onChange(new Set(kept))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectable, loading])
  const ticked = selection ? selectable.filter((k) => selection.selected.has(k)).length : 0
  const all = selectable.length > 0 && ticked === selectable.length
  const head = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (head.current) head.current.indeterminate = ticked > 0 && !all
  }, [ticked, all])

  const sorted = useMemo(() => {
    const col = sort && columns.find((c) => c.id === sort.id)
    if (!sort || !col?.sort) return rows
    const key = col.sort
    return rows.slice().sort((a, b) => {
      const x = key(a)
      const y = key(b)
      const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })
      return r * sort.dir
    })
  }, [rows, columns, sort])

  return (
    <Card className={cn('overflow-hidden', className)}>
      <div className="overflow-x-auto">
        <table aria-label={label} className="w-full min-w-max border-collapse text-[13.5px]">
          <thead className="bg-surface">
            <tr>
              {selection && (
                <th scope="col" className="w-10 border-b border-border px-4 py-2.5">
                  <input
                    ref={head}
                    type="checkbox"
                    aria-label="Select every row"
                    checked={all}
                    disabled={selectable.length === 0}
                    onChange={(e) => selection.onChange(e.target.checked ? new Set([...selection.selected, ...selectable]) : new Set([...selection.selected].filter((k) => !selectable.includes(k))))}
                  />
                </th>
              )}
              {columns.map((c) => {
                const on = sort?.id === c.id
                return (
                  <th
                    key={c.id}
                    scope="col"
                    aria-sort={on ? (sort!.dir === 1 ? 'ascending' : 'descending') : undefined}
                    style={{ width: c.width }}
                    className={cn(
                      'whitespace-nowrap border-b border-border px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground',
                      alignment[c.align ?? 'left'],
                      c.hideBelow && hide[c.hideBelow],
                    )}
                  >
                    {c.sort ? (
                      <button
                        type="button"
                        onClick={() => setSort((s) => (s?.id === c.id ? (s.dir === 1 ? { id: c.id, dir: -1 } : null) : { id: c.id, dir: 1 }))}
                        className={cn('inline-flex items-center gap-1 uppercase transition-colors hover:text-foreground', on && 'text-foreground')}
                      >
                        {c.header}
                        {on && (sort!.dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={rowKey(row, i)}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === 'Enter' && e.target === e.currentTarget) onRowClick(row)
                      }
                    : undefined
                }
                className={cn(
                  'border-b border-border transition-colors last:border-b-0',
                  onRowClick && 'cursor-pointer hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
                  rowClassName?.(row),
                )}
              >
                {selection && (
                  <td className="w-10 px-4 py-3 align-middle" onClick={(e) => e.stopPropagation()}>
                    {(!selection.canSelect || selection.canSelect(row)) && (
                      <input
                        type="checkbox"
                        aria-label="Select this row"
                        checked={selection.selected.has(rowKey(row, i))}
                        onChange={(e) => {
                          const next = new Set(selection.selected)
                          if (e.target.checked) next.add(rowKey(row, i))
                          else next.delete(rowKey(row, i))
                          selection.onChange(next)
                        }}
                      />
                    )}
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.id} className={cn('px-4 py-3 align-middle', alignment[c.align ?? 'left'], c.hideBelow && hide[c.hideBelow], c.className)}>
                    {c.cell(row, i)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loading && <SkeletonRows rows={5} cols={Math.min(columns.length, 5)} />}
      {!loading && rows.length === 0 && <div className="px-4 py-12 text-center text-sm text-muted-foreground">{empty}</div>}
      {footer && <div className="border-t border-border bg-surface px-4 py-2.5 text-xs text-muted-foreground">{footer}</div>}
    </Card>
  )
}
