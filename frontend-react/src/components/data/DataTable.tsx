import { useMemo, useState } from 'react'
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
export function DataTable<T>({
  rows,
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
