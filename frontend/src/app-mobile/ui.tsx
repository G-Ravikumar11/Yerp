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
  return <span className={cn('inline-flex h-6 items-center rounded-full px-2.5 text-xs font-semibold', TONES[tone])}>{children}</span>
}

/** A section heading: sentence case and bold, the way a phone app has it, with an optional link on the right. */
export function Label({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2.5 mt-6 flex items-center justify-between px-1">
      <h2 className="flex items-center gap-2 text-[17px] font-bold tracking-tight">{children}</h2>
      {action}
    </div>
  )
}

/** The card everything sits on: white on the soft background in light, a lifted panel in dark; rounded, with a hairline. */
export function Sheet({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-2xl border border-border bg-card p-4 shadow-[var(--app-card-shadow)]', className)}>{children}</div>
}

/** A round button with an icon in it: the bell, search, settings. */
export const roundBtn = 'grid size-10 shrink-0 place-items-center rounded-full border border-border bg-card shadow-[var(--app-card-shadow)] active:scale-95'

/** The big title at the top of a tab, the way a phone app has it. */
export function LargeTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-3 pb-3 pt-2">
      <div className="min-w-0">
        <h1 className="text-[30px] font-extrabold leading-tight tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-sm text-muted-foreground">{sub}</p>}
      </div>
      {right}
    </div>
  )
}
