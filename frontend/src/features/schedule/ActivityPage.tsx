import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useActivity } from '@/api/schedule'
import { useSession } from '@/lib/session'
import { today } from '@/lib/format'
import { ActivityPanel } from './ActivityPanel'
import { ProgressRing } from './ProgressRing'

const TONE: Record<string, string> = { done: 'bg-success', late: 'bg-danger', behind: 'bg-warning', 'on track': 'bg-primary', 'not started': 'bg-subtle' }
const RING: Record<string, string> = { done: 'stroke-success', late: 'stroke-danger', behind: 'stroke-warning', 'on track': 'stroke-primary', 'not started': 'stroke-subtle' }
const BADGE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = { done: 'success', late: 'danger', behind: 'warning', 'on track': 'neutral', 'not started': 'neutral' }

/** One activity on a page of its own, opened from the day plan: where it stands, its tasks to be done and ticked off, and its history. */
export default function ActivityPage() {
  const { job, id } = useParams()
  const [params] = useSearchParams()
  const { can } = useSession()
  const q = useActivity(Number(id))
  const d = q.data
  const a = d?.activity
  const back = <Link to={`/projects/programme?job=${job}${params.get('on') ? `&on=${params.get('on')}` : ''}`} className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" /> Planning &amp; Progress</Link>
  if (q.isError) return <>{back}<p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">This activity no longer exists. It may have been deleted.</p></>
  if (q.isPending || !d || !a) return <>{back}<Skeleton className="h-64 w-full" /></>
  const tone = TONE[a.state] ?? 'bg-primary'
  return (
    <>
      {back}
      <PageHeader eyebrow={`${d.job.number} - ${d.job.name}`} title={`${a.code} ${a.name}`} description={`${a.planned_start} to ${a.planned_finish}${a.depends_on ? ` - after ${a.depends_on}` : ''}`} actions={<Badge tone={BADGE[a.state] ?? 'neutral'}>{a.state}</Badge>} />
      <div className="mb-5 flex flex-wrap items-center gap-6 rounded-xl border border-border bg-card p-4 shadow-card">
        <ProgressRing size={96} percent={a.actual_percent} planned={a.planned_percent} tone={RING[a.state]} label={`${a.name} done`} />
        <StatGrid className="flex-1">
          <Stat label="Done" value={`${a.actual_percent}%`} />
          <Stat label="Planned by today" value={`${a.planned_percent}%`} />
          <Stat label="Forecast finish" value={a.forecast_finish || '-'} sub={a.slip_days > 0 ? `${a.slip_days} days late` : undefined} tone={a.slip_days > 0 ? 'danger' : undefined} />
          <Stat label="Tasks done" value={`${a.tasks_done}/${a.tasks_total}`} />
        </StatGrid>
      </div>
      <ActivityPanel job={Number(job)} row={a} on={params.get('on') || today()} can={can('site.record') || can('workorders.manage')} tone={tone} />
      <section aria-label="Progress history" className="mt-6">
        <h2 className="mb-2 text-sm font-semibold">Progress history</h2>
        {d.history.length === 0 ? (
          <p className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">No progress has been reported on it yet.</p>
        ) : (
          <ul className="grid gap-1">
            {d.history.map((h, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-3 rounded-md border border-border bg-card px-3 py-1.5 text-sm">
                <span className="tabular text-muted-foreground">{h.on}</span>
                <span className="font-semibold tabular">{h.percent}%</span>
                <span className="text-xs text-muted-foreground">{[h.note, h.by && `by ${h.by}`].filter(Boolean).join(' - ')}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
