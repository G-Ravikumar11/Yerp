import type { MbLine } from '@/api/mb'
import { formatQty } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'

/** What the work order says about one item - the unit, the rate, how much is ordered and how much is left. */
export function ItemFacts({ line, className }: { line: MbLine; className?: string }) {
  const left = Math.max(0, line.balance_to_measure ?? 0)
  const facts: [string, string, boolean?][] = [
    ['Unit', line.uom || '-'],
    ['Ordered', formatQty(line.ordered_qty)],
    ['Measured', formatQty(line.measured_to_date), !!line.over_measured],
    ['Still to do', formatQty(left)],
    ['Rate', formatINR(line.rate ?? 0)],
    ['Allowed up to', formatQty(line.max_quantity)],
  ]
  return (
    <dl className={cn('grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-6', className)}>
      {facts.map(([label, value, bad]) => (
        <div key={label} className="min-w-0">
          <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
          <dd className={cn('tabular truncate text-sm font-medium', bad && 'text-danger')}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
