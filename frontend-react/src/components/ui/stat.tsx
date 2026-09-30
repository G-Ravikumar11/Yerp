import { cn } from '@/lib/utils'
import { Skeleton } from './skeleton'

const toneClass = { success: 'text-success', warning: 'text-warning', danger: 'text-danger' } as const

/** One figure with its label - the tiles across the top of a screen. */
export function Stat({
  label,
  value,
  sub,
  tone,
  loading,
  className,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  tone?: 'success' | 'warning' | 'danger'
  loading?: boolean
  className?: string
}) {
  return (
    <div className={cn('min-w-0 rounded-xl border border-border bg-card p-4 shadow-card', className)}>
      <p className="text-[12.5px] text-muted-foreground">{label}</p>
      {loading ? (
        <Skeleton className="mt-2.5 h-7 w-28" />
      ) : (
        <p className={cn('tabular mt-1.5 break-words font-display text-xl font-semibold leading-tight sm:text-2xl', tone && toneClass[tone])}>{value}</p>
      )}
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

export function StatGrid({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-5', className)}>{children}</div>
}
