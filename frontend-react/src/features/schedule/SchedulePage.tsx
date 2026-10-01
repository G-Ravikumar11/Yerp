import { useState } from 'react'
import { Plus, Printer } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { PromptModal } from '@/components/data/PromptModal'
import { Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { schKeys, setProgress, useSchedule, type Activity } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { ActivityModal } from './ActivityModal'
import { Bars, Curve } from './Bars'
import { DrawModal } from './DrawModal'

/** What is meant to happen when, what has happened, and what slips if the thing before it slips. */
export default function SchedulePage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const q = useSchedule(job)
  const d = q.data
  const s = d?.summary
  const [editing, setEditing] = useState<Activity | 'new' | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [progress, setProgressOf] = useState<Activity | null>(null)
  const set = useAction((v: { a: Activity; pct: number }) => setProgress(v.a.id, v.pct), { invalidate: [schKeys.all], success: 'Progress recorded', onSuccess: () => setProgressOf(null) })
  const v = s?.variance ?? 0
  return (
    <>
      <PageHeader eyebrow="Projects" title="Programme & Progress" description="What is meant to happen when, what has happened, and what slips if the thing before it slips." actions={<>{can('workorders.manage') && <Button disabled={!job} onClick={() => setEditing('new')}><Plus /> Activity</Button>}<Button variant="outline" disabled={!job} onClick={() => setDrawing(true)}>Draw from a work order</Button><Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button></>} />
      <div className="mb-6"><ProjectPicker value={job} onChange={setJob} id="sch-job" /></div>
      <StatGrid>
        <Stat label="Planned by today" value={`${s?.planned_percent ?? 0}%`} loading={q.isPending && job > 0} />
        <Stat label="Done" value={`${s?.actual_percent ?? 0}%`} loading={q.isPending && job > 0} />
        <Stat label="Ahead / behind" value={`${v > 0 ? '+' : ''}${v} pts`} tone={v < -5 ? 'danger' : v < 0 ? 'warning' : 'success'} loading={q.isPending && job > 0} />
        <Stat label="Late activities" value={s?.late ?? 0} sub={s?.behind ? `+${s.behind} behind` : undefined} loading={q.isPending && job > 0} />
        <Stat label="Finishes" value={s?.forecast_finish || '-'} sub={s && s.slip_days > 0 ? `${s.slip_days} days late` : undefined} tone={s && s.slip_days > 0 ? 'danger' : undefined} loading={q.isPending && job > 0} />
      </StatGrid>
      {q.isPending && job > 0 ? <Skeleton className="h-48 w-full" /> : d && d.activities.length > 0 ? (
        <>
          <Bars activities={d.activities} onEdit={(a) => can('workorders.manage') && setEditing(a)} onProgress={setProgressOf} />
          <Curve curve={d.curve} />
        </>
      ) : job > 0 ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No programme yet. Add activities, or draw one from a work order: each line becomes an activity whose progress comes from the measurement book.</p> : null}
      <ActivityModal job={job} activity={editing && editing !== 'new' ? editing : null} others={d?.activities ?? []} open={!!editing} onClose={() => setEditing(null)} />
      <DrawModal job={job} open={drawing} onClose={() => setDrawing(false)} />
      <PromptModal open={!!progress} title={progress ? `${progress.code} ${progress.name}` : ''} description="How far along is it, in per cent?" fields={[{ key: 'pct', label: progress ? `Per cent done (now ${progress.actual_percent}%)` : '', required: true }]} confirm="Record progress" busy={set.isPending} error={set.error?.message} onSubmit={(x) => progress && set.mutate({ a: progress, pct: parseFloat(x.pct) })} onClose={() => setProgressOf(null)} />
    </>
  )
}
