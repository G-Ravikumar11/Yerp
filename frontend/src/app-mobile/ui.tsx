import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** The small pieces the phone screens share: a coloured pill, a section label, and the card they sit on. */
const TONES = {
  ok: 'bg-success/15 text-success',
  warn: 'bg-warning/15 text-warning',
  bad: 'bg-danger/15 text-danger',
  info: 'bg-primary/15 text-primary',
  quiet: 'bg-muted text-muted-foreground',
} as const

export function Pill({ tone = 'quiet', children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={cn('inline-flex h-6 items-center rounded-md px-2.5 text-xs font-semibold', TONES[tone])}>{children}</span>
}

export function Label({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2.5 mt-6 flex items-center justify-between px-1">
      <h2 className="text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">{children}</h2>
      {action}
    </div>
  )
}

export function Sheet({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-lg border border-border bg-card p-4', className)}>{children}</div>
}

/** The big title at the top of a tab, the way a phone app has it. */
export function LargeTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-3 pb-3 pt-2">
      <div className="min-w-0">
        <h1 className="font-display text-[32px] font-bold leading-tight tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-sm text-muted-foreground">{sub}</p>}
      </div>
      {right}
    </div>
  )
}
