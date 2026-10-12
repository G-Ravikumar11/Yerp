import { useState } from 'react'
import { Plus, Printer } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Button, Input, Skeleton, Stat, StatGrid, Tabs } from '@/components/ui'
import { useSchedule, type Activity } from '@/api/schedule'
import { today } from '@/lib/format'
import { useSession } from '@/lib/session'
import { ActivityModal } from './ActivityModal'
import { Bars, Curve } from './Bars'
import { DayPlan } from './DayPlan'
import { DrawModal } from './DrawModal'

/** The day's plan, the whole programme, and how far along the work is - and what slips if the thing before it slips. */
export default function SchedulePage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [tab, setTab] = useState<'day' | 'programme'>('day')
  const [on, setOn] = useState(today())
  const q = useSchedule(job)
  const d = q.data
  const s = d?.summary
  const [editing, setEditing] = useState<Activity | 'new' | null>(null)
  const [drawing, setDrawing] = useState(false)
  const v = s?.variance ?? 0
  return (
    <>
      <PageHeader eyebrow="Projects" title="Planning & Progress" description="What is to be done each day, how far along the work is, and what slips if the thing before it slips." actions={<>{can('workorders.manage') && <Button disabled={!job} onClick={() => setEditing('new')}><Plus /> Activity</Button>}<Button variant="outline" disabled={!job} onClick={() => setDrawing(true)}>Draw from a work order</Button><Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button></>} />
      <div className="mb-4 flex flex-wrap items-end gap-4"><ProjectPicker value={job} onChange={setJob} id="sch-job" /></div>
      {job > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="max-w-xs"><Tabs label="Planning views" value={tab} onChange={setTab} items={[{ value: 'day', label: 'Day plan' }, { value: 'programme', label: 'Programme' }]} /></div>
          {tab === 'day' && (
            <label className="flex items-center gap-2 text-[13px]">
              <span className="text-muted-foreground">Day</span>
              <Input type="date" value={on} onChange={(e) => e.target.value && setOn(e.target.value)} className="w-40" aria-label="Day to plan" />
              {on !== today() && <button type="button" className="text-xs font-medium text-primary underline underline-offset-4" onClick={() => setOn(today())}>Today</button>}
            </label>
          )}
        </div>
      )}
      {job > 0 && tab === 'day' && <DayPlan job={job} on={on} canReport={can('site.record') || can('workorders.manage')} />}
      {(tab === 'programme' || !job) && <StatGrid>
        <Stat label="Planned by today" value={`${s?.planned_percent ?? 0}%`} loading={q.isPending && job > 0} />
        <Stat label="Done" value={`${s?.actual_percent ?? 0}%`} loading={q.isPending && job > 0} />
        <Stat label="Ahead / behind" value={`${v > 0 ? '+' : ''}${v} pts`} tone={v < -5 ? 'danger' : v < 0 ? 'warning' : 'success'} loading={q.isPending && job > 0} />
        <Stat label="Late activities" value={s?.late ?? 0} sub={s?.behind ? `+${s.behind} behind` : undefined} loading={q.isPending && job > 0} />
        <Stat label="Finishes" value={s?.forecast_finish || '-'} sub={s && s.slip_days > 0 ? `${s.slip_days} days late` : undefined} tone={s && s.slip_days > 0 ? 'danger' : undefined} loading={q.isPending && job > 0} />
      </StatGrid>}
      {tab === 'programme' && (q.isPending && job > 0 ? <Skeleton className="h-48 w-full" /> : d && d.activities.length > 0 ? (
        <>
          <Bars activities={d.activities} onEdit={(a) => can('workorders.manage') && setEditing(a)} />
          <Curve curve={d.curve} />
        </>
      ) : job > 0 ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No programme yet. Add activities, or draw one from a work order: each line becomes an activity whose progress comes from the measurement book.</p> : null)}
      <ActivityModal job={job} activity={editing && editing !== 'new' ? editing : null} others={d?.activities ?? []} open={!!editing} onClose={() => setEditing(null)} />
      <DrawModal job={job} open={drawing} onClose={() => setDrawing(false)} />
    </>
  )
}
