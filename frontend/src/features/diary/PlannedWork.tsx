import { Skeleton } from '@/components/ui'
import { useDayPlan, type DayRow, type DayTask } from '@/api/schedule'
import { cn } from '@/lib/utils'

/**
 * The work Planning & Progress has down for this site on this day: its tasks to tick off, and the activities that have no
 * tasks, to say how far along they are now. What is changed here moves the plan when the diary is saved.
 */
export function PlannedWork({ job, date, taskDone, onTask, percent, onPercent, disabled }: {
  job: number
  date: string
  taskDone: Record<number, boolean>
  onTask: (t: DayTask, done: boolean) => void
  percent: Record<number, number>
  onPercent: (r: DayRow, pct: number) => void
  disabled?: boolean
}) {
  const plan = useDayPlan(job, date)
  if (job <= 0) return null
  if (plan.isPending) return <Skeleton className="mt-5 h-20 w-full" />
  const d = plan.data
  if (!d) return null
  // Activities running (or overdue) that carry no tasks of their own: their progress is told here as a percentage.
  const open = [...d.today, ...d.overdue].filter((r) => r.editable && r.tasks_total === 0)
  if (d.tasks.length === 0 && open.length === 0) return null
  return (
    <section aria-label="Planned work" className="mt-5 rounded-lg border border-border bg-muted/30 p-3">
      <h3 className="text-sm font-semibold">Planned work for this day</h3>
      <p className="mb-2 text-xs text-muted-foreground">Tick what was done and say how far along the rest is. It moves Planning &amp; Progress when you save.</p>
      {d.tasks.length > 0 && (
        <ul className="mb-2 grid gap-1">
          {d.tasks.map((t) => {
            const done = taskDone[t.id] ?? t.done
            return (
              <li key={t.id}>
                <label className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-accent/40">
                  <input type="checkbox" checked={done} disabled={disabled} className="mt-0.5 size-4 accent-[var(--primary)]" onChange={(e) => onTask(t, e.target.checked)} />
                  <span className={cn(done && 'text-muted-foreground line-through')}>{t.text}{t.activity && <span className="ml-2 text-[11px] text-muted-foreground">{t.activity}</span>}</span>
                </label>
              </li>
            )
          })}
        </ul>
      )}
      {open.length > 0 && (
        <ul className="grid gap-1.5">
          {open.map((r) => {
            const value = percent[r.id] ?? r.actual_percent
            return (
              <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="min-w-40 flex-1"><span className="mr-1.5 font-mono text-[11px] text-muted-foreground">{r.code}</span>{r.name}</span>
                <input type="range" min={0} max={100} step={5} value={Math.round(value)} disabled={disabled} aria-label={`How far along: ${r.name}`} onChange={(e) => onPercent(r, Number(e.target.value))} className="h-2 w-40 cursor-pointer accent-[var(--primary)]" />
                <span className="w-10 text-right text-xs tabular">{Math.round(value)}%</span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
