import { BUCKETS, type Buckets } from '@/api/owed'
import { cn, formatINR } from '@/lib/utils'

// "Not due" is kept apart from "0-30" on purpose: money that is not late yet is not a problem.
const TONE: Record<string, string> = { 'Not due': 'border-t-subtle', '0-30': 'border-t-primary', '31-60': 'border-t-warning', '61-90': 'border-t-warning', '90+': 'border-t-danger' }

export function AgeingStrip({ buckets, total }: { buckets?: Buckets; total: number }) {
  return (
    <div className="mb-5 grid grid-cols-2 gap-2.5 sm:grid-cols-5" role="list" aria-label="Ageing">
      {BUCKETS.map((b) => {
        const v = buckets?.[b] ?? 0
        return (
          <div key={b} role="listitem" className={cn('rounded-lg border border-border border-t-[3px] bg-card px-3 py-2.5', TONE[b])}>
            <div className="text-xs text-muted-foreground">{b === 'Not due' ? b : `${b} days`}</div>
            <div className="tabular mt-0.5 font-bold">{formatINR(v)}</div>
            <div className="text-[11px] text-muted-foreground">{total ? Math.round((v / total) * 100) : 0}%</div>
          </div>
        )
      })}
    </div>
  )
}
