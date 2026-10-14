import { Link } from 'react-router-dom'
import { Badge, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useDayPlan, type DayRow } from '@/api/schedule'
import { DayTasks } from './DayTasks'
import { ProgressBar } from './ProgressBar'

const word = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** Where an activity stands against its plan, as the colour of its bar. */
const tone = (r: DayRow) => (r.bucket === 'overdue' ? 'bg-danger' : r.bucket === 'soon' ? 'bg-subtle' : r.to_catch_up > 10 ? 'bg-warning' : 'bg-success')

/**
 * A group of activities as small cards side by side. Pressing one opens that activity on a page of its own inside the app,
 * with its tasks to be done and ticked off.
 */
function Group({ title, hint, rows, empty, job, on, note }: { title: string; hint: string; rows: DayRow[]; empty: string; job: number; on: string; note: (r: DayRow) => React.ReactNode }) {
  return (
    <section aria-label={title} className="mb-5">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-muted-foreground">{hint}</span>
        <Badge tone="neutral">{rows.length}</Badge>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
          {rows.map((r) => (
            <li key={r.id}>
              <Link
                to={`/projects/programme/${job}/activity/${r.id}?on=${on}`}
                aria-label={`Open ${r.name}`}
                className="block w-full rounded-lg border border-border bg-card px-2.5 py-2 text-left shadow-card transition-colors hover:border-primary hover:bg-accent/40"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[13px] font-semibold" title={r.name}><span className="mr-1.5 font-mono text-[10px] font-normal text-muted-foreground">{r.code}</span>{r.name}</span>
                  {r.tasks_total > 0 && <span className="shrink-0 text-[10px] text-muted-foreground">{r.tasks_done}/{r.tasks_total}</span>}
                </div>
                <ProgressBar thin percent={r.actual_percent} planned={r.bucket === 'today' ? r.planned_percent : undefined} tone={tone(r)} label={`${r.name} done`} className="mt-1.5" />
                <div className="mt-1 truncate text-[10px] text-muted-foreground">{note(r)}</div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** What the site is meant to be doing on one day: the work due, how far along it is, what is overdue and what is next. */
export function DayPlan({ job, on, canReport }: { job: number; on: string; canReport: boolean }) {
  const q = useDayPlan(job, on)
  const d = q.data
  const s = d?.summary
  if (q.isPending && job > 0) return <Skeleton className="h-48 w-full" />
  if (!d) return null
  const v = s?.variance ?? 0
  const common = { job, on }
  return (
    <>
      <StatGrid>
        <Stat label="Work done overall" value={`${s?.done_percent ?? 0}%`} />
        <Stat label="Planned by this day" value={`${s?.planned_percent ?? 0}%`} />
        <Stat label="Ahead / behind" value={`${v > 0 ? '+' : ''}${v} pts`} tone={v < -5 ? 'danger' : v < 0 ? 'warning' : 'success'} />
        <Stat label="Work due this day" value={s?.working ?? 0} />
        <Stat label="Overdue" value={s?.overdue ?? 0} tone={s?.overdue ? 'danger' : undefined} />
      </StatGrid>
      <div className="mb-5 rounded-lg border border-border bg-card px-3 py-2.5 shadow-card">
        <div className="mb-1 flex items-center justify-between text-sm"><span className="font-semibold">Whole project</span><span className="text-xs text-muted-foreground">tick marks where the plan has it</span></div>
        <ProgressBar percent={s?.done_percent ?? 0} planned={s?.planned_percent} label="Whole project done" tone={v < -5 ? 'bg-danger' : v < 0 ? 'bg-warning' : 'bg-success'} />
      </div>

      <Group title="Work to be done" hint="running on this day - press one to open it" rows={d.today} empty="Nothing in the programme is running on this day." {...common}
        note={(r) => (r.to_catch_up > 0 ? `${r.to_catch_up} pts behind plan` : 'On plan') + (r.days_left !== null ? (r.days_left <= 0 ? ' - due today' : ` - ${word(r.days_left, 'day')} left`) : '')} />
      <Group title="Overdue" hint="past the planned finish and not done" rows={d.overdue} empty="Nothing is past its finish date." {...common}
        note={(r) => `${word(r.days_late ?? 0, 'day')} late - ${r.remaining}% to do`} />
      <Group title="Coming up" hint="starting in the next 7 days" rows={d.soon} empty="Nothing starts in the next week." {...common}
        note={(r) => (r.starts_in === 1 ? 'Starts tomorrow' : `Starts in ${word(r.starts_in ?? 0, 'day')}`)} />

      <DayTasks job={job} on={on} tasks={d.tasks} activities={[...d.today, ...d.overdue, ...d.soon]} can={canReport} />
    </>
  )
}
