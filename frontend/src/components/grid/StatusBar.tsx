import { AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

const fmt = (n: number) => n.toLocaleString('en-IN', { maximumFractionDigits: 3 })

/**
 * Under the sheet: how many rows are in it, what needs fixing, what the last
 * action did, and - as Excel's bottom edge does - the count, sum and average
 * of whatever numbers are selected.
 */
export function StatusBar({
  rowCount,
  issueCount,
  onIssues,
  message,
  selection,
  cells,
  footer,
  readOnly,
}: {
  rowCount: number
  issueCount: number
  onIssues: () => void
  message: string
  selection: number[]
  cells: number
  footer?: React.ReactNode
  readOnly: boolean
}) {
  const sum = selection.reduce((a, b) => a + b, 0)
  return (
    <div className="flex min-h-9 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface px-3 py-1.5 text-xs text-muted-foreground">
      <span className="tabular font-medium text-foreground">
        {rowCount} row{rowCount === 1 ? '' : 's'}
      </span>
      {issueCount > 0 && (
        <button
          type="button"
          onClick={onIssues}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-danger transition-colors hover:bg-danger-soft"
        >
          <AlertCircle className="size-3.5" />
          {issueCount} to fix
        </button>
      )}
      {readOnly && <span>Read only</span>}
      {footer}
      <span role="status" aria-live="polite" className={cn('min-w-0 flex-1 truncate', !message && 'sr-only')}>
        {message}
      </span>
      {selection.length > 1 && (
        <span className="tabular ml-auto flex gap-3">
          <span>Count {selection.length}</span>
          <span>Sum {fmt(sum)}</span>
          <span>Avg {fmt(sum / selection.length)}</span>
        </span>
      )}
      {selection.length <= 1 && cells > 1 && <span className="tabular ml-auto">{cells} cells</span>}
      <span className="ml-auto hidden text-subtle lg:inline">Enter ↓ · Tab → · F2 edit · Ctrl+V paste from Excel · Ctrl+Z undo</span>
    </div>
  )
}
