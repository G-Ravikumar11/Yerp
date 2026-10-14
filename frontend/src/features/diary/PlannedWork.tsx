import { useState } from 'react'
import { Button, Skeleton } from '@/components/ui'
import { useDayPlan, type DayRow, type DayTask } from '@/api/schedule'
import { cn } from '@/lib/utils'
import { ProgressBar } from '@/features/schedule/ProgressBar'

/** What a task is as the diary has it so far: all done, part done, or not started. */
export interface TaskState { done: boolean; percent: number }

const stateOf = (t: DayTask, over: Record<number, TaskState>): TaskState => over[t.id] ?? { done: t.done, percent: t.percent }
const share = (s: TaskState) => (s.done ? 100 : s.percent)

/**
 * The work Planning & Progress has down for this site: every activity running on the day (and any overdue), with its
 * tasks to press Done or Partially on. An activity with no tasks takes a slider instead. The bars move as you press, and
 * the plan itself moves when the diary is saved.
 */
export function PlannedWork({ job, date, taskState, onTask, percent, onPercent, disabled }: {
  job: number
  date: string
  taskState: Record<number, TaskState>
  onTask: (t: DayTask, state: TaskState) => void
  percent: Record<number, number>
  onPercent: (r: DayRow, pct: number) => void
  disabled?: boolean
}) {
  const plan = useDayPlan(job, date)
  const [partly, setPartly] = useState<{ id: number; value: number } | null>(null)
  if (job <= 0) return null
  if (plan.isPending) return <Skeleton className="mt-5 h-20 w-full" />
  const d = plan.data
  if (!d) return null
  // Every activity on the site, none left out: running or overdue first, then what starts later, then what is finished.
  const running = [...d.today, ...d.overdue].filter((r) => r.editable)
  const later = [...d.soon, ...d.others.filter((r) => r.bucket === 'later')].filter((r) => r.editable)
  const finished = d.others.filter((r) => r.bucket === 'done' && r.editable)
  const rows = [...running, ...later, ...finished]
  const shown = new Set(rows.map((r) => r.id))
  // Tasks written for this day that sit under an activity not running today, or under none.
  const loose = d.tasks.filter((t) => !t.activity_id || !shown.has(t.activity_id))
  if (rows.length === 0 && loose.length === 0) return <p className="mt-5 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">Nothing is planned on this site yet. Activities added in Planning &amp; Progress appear here.</p>

  const taskLine = (t: DayTask) => {
    const s = stateOf(t, taskState)
    const editing = partly?.id === t.id
    return (
      <li key={t.id} className="rounded-md border border-border bg-card px-2.5 py-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1">
            <div className={cn('text-sm', s.done && 'text-muted-foreground line-through')}>{t.text}</div>
            <div className="text-[11px] text-muted-foreground">{t.date}{!s.done && s.percent > 0 ? ` - ${s.percent}% done` : ''}</div>
          </div>
          {!disabled && !editing && (
            <div className="flex items-center gap-1.5">
              {!s.done && <Button size="sm" variant="outline" onClick={() => setPartly({ id: t.id, value: s.percent > 0 ? s.percent : 50 })}>Partially</Button>}
              <Button size="sm" variant={s.done ? 'ghost' : 'outline'} onClick={() => onTask(t, s.done ? { done: false, percent: 0 } : { done: true, percent: 100 })}>{s.done ? 'Undo' : 'Done'}</Button>
              {!s.done && s.percent > 0 && <Button size="sm" variant="ghost" onClick={() => onTask(t, { done: false, percent: 0 })}>Reset</Button>}
            </div>
          )}
        </div>
        {!s.done && s.percent > 0 && !editing && <ProgressBar thin percent={s.percent} tone="bg-warning" label={`${t.text} part done`} className="mt-1" />}
        {editing && partly && (
          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-2">
            <span className="text-xs text-muted-foreground">How much of it is done?</span>
            <input type="range" min={5} max={95} step={5} value={partly.value} aria-label={`How much of ${t.text} is done`} onChange={(e) => setPartly({ id: t.id, value: Number(e.target.value) })} className="h-2 min-w-32 flex-1 cursor-pointer accent-[var(--primary)]" />
            <span className="w-10 text-right text-xs font-semibold tabular">{partly.value}%</span>
            <Button size="sm" onClick={() => { onTask(t, { done: false, percent: partly.value }); setPartly(null) }}>Set</Button>
            <Button size="sm" variant="ghost" onClick={() => setPartly(null)}>Cancel</Button>
          </div>
        )}
      </li>
    )
  }

  const card = (r: DayRow) => {
          const hasTasks = r.tasks.length > 0
          const now = hasTasks ? r.tasks.reduce((sum, t) => sum + share(stateOf(t, taskState)), 0) / r.tasks.length : (percent[r.id] ?? r.actual_percent)
          const value = percent[r.id] ?? r.actual_percent
          return (
            <div key={r.id} className="rounded-md border border-border bg-background/40 p-2.5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-semibold"><span className="mr-1.5 font-mono text-[11px] font-normal text-muted-foreground">{r.code}</span>{r.name}</span>
                <span className="text-[11px] text-muted-foreground">{r.planned_start} to {r.planned_finish}{r.bucket === 'overdue' ? ' - overdue' : ''}</span>
              </div>
              <ProgressBar thin percent={now} planned={r.bucket === 'today' ? r.planned_percent : undefined} tone={r.bucket === 'overdue' ? 'bg-danger' : r.bucket === 'later' ? 'bg-subtle' : 'bg-success'} label={`${r.name} done`} className="mb-2" />
              {hasTasks ? (
                <ul className="grid gap-1">{r.tasks.map(taskLine)}</ul>
              ) : (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-xs text-muted-foreground">No tasks under it. How far along is it now?</span>
                  <input type="range" min={0} max={100} step={5} value={Math.round(value)} disabled={disabled} aria-label={`How far along: ${r.name}`} onChange={(e) => onPercent(r, Number(e.target.value))} className="h-2 w-40 cursor-pointer accent-[var(--primary)]" />
                  <span className="w-10 text-right text-xs tabular">{Math.round(value)}%</span>
                </div>
              )}
            </div>
          )
  }

  return (
    <section aria-label="Planned work" className="mt-5 rounded-lg border border-border bg-muted/30 p-3">
      <h3 className="text-sm font-semibold">Planned work for this day</h3>
      <p className="mb-3 text-xs text-muted-foreground">Everything in Planning &amp; Progress that is running on this site. Press Done or Partially on what was done; it moves the plan when you save.</p>
      <div className="grid gap-3">
        {running.map(card)}
        {later.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Starting later</div>
            <div className="grid gap-3">{later.map(card)}</div>
          </div>
        )}
        {finished.length > 0 && (
          <details className="rounded-md border border-border bg-background/40 p-2.5">
            <summary className="cursor-pointer text-sm font-semibold">Finished ({finished.length})</summary>
            <div className="mt-2 grid gap-3">{finished.map(card)}</div>
          </details>
        )}
        {loose.length > 0 && (
          <div className="rounded-md border border-border bg-background/40 p-2.5">
            <div className="mb-1 text-sm font-semibold">Other tasks for this day</div>
            <ul className="grid gap-1">{loose.map(taskLine)}</ul>
          </div>
        )}
      </div>
    </section>
  )
}
