import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
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
  to,
  className,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  tone?: 'success' | 'warning' | 'danger'
  loading?: boolean
  /** Makes the whole tile a link to the page this figure comes from. */
  to?: string
  className?: string
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12.5px] text-muted-foreground">{label}</p>
        {to && <ArrowUpRight className="size-3.5 shrink-0 text-subtle transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground" />}
      </div>
      {loading ? (
        <Skeleton className="mt-2.5 h-7 w-28" />
      ) : (
        <p className={cn('tabular mt-1.5 break-words font-display text-xl font-semibold leading-tight sm:text-2xl', tone && toneClass[tone])}>{value}</p>
      )}
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </>
  )
  const box = 'min-w-0 rounded-xl border border-border bg-card p-4 shadow-card'
  if (!to) return <div className={cn(box, className)}>{body}</div>
  return (
    <Link
      to={to}
      className={cn(box, 'group block transition-all hover:-translate-y-0.5 hover:border-ring/50 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', className)}
    >
      {body}
    </Link>
  )
}

export function StatGrid({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-5', className)}>{children}</div>
}
