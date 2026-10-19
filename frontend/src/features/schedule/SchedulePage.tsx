import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FileUp, Plus, Printer } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Button, Input, Stat, StatGrid, Tabs } from '@/components/ui'
import { useSchedule, type Activity } from '@/api/schedule'
import { today } from '@/lib/format'
import { useSession } from '@/lib/session'
import { ActivityModal } from './ActivityModal'
import { Curve } from './Bars'
import { DayPlan } from './DayPlan'
import { programmeFileUrl } from '@/api/programme'
import { ProgrammeImportModal } from './programme/ProgrammeImportModal'
import { AiDayTasks, AiDraftModal, AiPlanPanel } from './AiPlanning'
import { BoqPickerModal } from './programme/BoqPickerModal'
import { ProgrammeView } from './programme/ProgrammeView'

/** The day's plan, the whole programme, and how far along the work is - and what slips if the thing before it slips. */
export default function SchedulePage() {
  const { can } = useSession()
  // The site and the day live in the address, so coming back from an activity's page lands on the same ones.
  const [params, setParams] = useSearchParams()
  const job = Number(params.get('job')) || 0
  const on = params.get('on') || today()
  const remember = (next: { job?: number; on?: string }) => setParams((p) => {
    const q = new URLSearchParams(p)
    if (next.job !== undefined) { if (next.job) q.set('job', String(next.job)); else q.delete('job') }
    if (next.on !== undefined) { if (next.on === today()) q.delete('on'); else q.set('on', next.on) }
    return q
  }, { replace: true })
  const setJob = (id: number) => remember({ job: id })
  const setOn = (day: string) => remember({ on: day })
  const [tab, setTab] = useState<'day' | 'programme'>('day')
  const q = useSchedule(job)
  const d = q.data
  const s = d?.summary
  const [editing, setEditing] = useState<Activity | 'new' | null>(null)
  const [drawing, setDrawing] = useState(false)  // draw from the BOQ
  const [importing, setImporting] = useState(false)  // import a programme sheet
  const [drafting, setDrafting] = useState(false)  // draft a programme with AI
  const v = s?.variance ?? 0
  // On the programme the grid's own toolbar has Row, Draw from BOQ and Import, so the page does not repeat them.
  const inGrid = tab === 'programme' && job > 0
  return (
    <>
      <PageHeader eyebrow="Projects" title="Planning & Progress" description="What is to be done each day, how far along the work is, and what slips if the thing before it slips." actions={<>{!inGrid && can('workorders.manage') && <Button disabled={!job} onClick={() => setEditing('new')}><Plus /> Activity</Button>}{!inGrid && <Button variant="outline" disabled={!job} onClick={() => setDrawing(true)}>Draw from BOQ</Button>}{!inGrid && <Button variant="outline" disabled={!job} onClick={() => setImporting(true)}><FileUp /> Import a programme</Button>}{can('workorders.manage') && <Button variant="outline" disabled={!job} onClick={() => setDrafting(true)}>Draft with AI</Button>}<Button variant="outline" onClick={() => (inGrid ? window.open(programmeFileUrl(job, 'pdf'), '_blank') : window.print())}><Printer /> {inGrid ? 'Print A3 PDF' : 'Print'}</Button></>} />
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
      {job > 0 && tab === 'day' && <AiDayTasks job={job} on={on} canAdd={can('site.record') || can('workorders.manage')} />}
      {job > 0 && tab === 'day' && <DayPlan job={job} on={on} canReport={can('site.record') || can('workorders.manage')} />}
      {job > 0 && tab === 'day' && <AiPlanPanel job={job} />}
      {(tab === 'programme' || !job) && <StatGrid>
        <Stat label="Planned by today" value={`${s?.planned_percent ?? 0}%`} loading={q.isPending && job > 0} />
        <Stat label="Done" value={`${s?.actual_percent ?? 0}%`} loading={q.isPending && job > 0} />
        <Stat label="Ahead / behind" value={`${v > 0 ? '+' : ''}${v} pts`} tone={v < -5 ? 'danger' : v < 0 ? 'warning' : 'success'} loading={q.isPending && job > 0} />
        <Stat label="Late activities" value={s?.late ?? 0} sub={s?.behind ? `+${s.behind} behind` : undefined} loading={q.isPending && job > 0} />
        <Stat label="Finishes" value={s?.forecast_finish || '-'} sub={s && s.slip_days > 0 ? `${s.slip_days} days late` : undefined} tone={s && s.slip_days > 0 ? 'danger' : undefined} loading={q.isPending && job > 0} />
      </StatGrid>}
      {tab === 'programme' && job > 0 && <ProgrammeView key={job} job={job} />}
      {tab === 'programme' && d && d.curve.length > 0 && <Curve curve={d.curve} />}
      {job > 0 && tab === 'programme' && <AiPlanPanel job={job} />}
      <ActivityModal job={job} activity={editing && editing !== 'new' ? editing : null} others={d?.activities ?? []} employees={d?.employees ?? []} teamScope={d?.team_scope} open={!!editing} onClose={() => setEditing(null)} />
      {drawing && <BoqPickerModal job={job} onClose={() => setDrawing(false)} onDone={() => setTab('programme')} />}
      <ProgrammeImportModal job={job} open={importing} onClose={() => setImporting(false)} />
      <AiDraftModal job={job} open={drafting} onClose={() => setDrafting(false)} />
    </>
  )
}
