import { useState } from 'react'
import { FileSpreadsheet, FileText, Image, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { PromptModal } from '@/components/data/PromptModal'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Stat, StatGrid, Tabs } from '@/components/ui'
import { closeIncident, closePermit, recordTalk, safetyKeys, useSafety, type Incident, type Permit, type Talk } from '@/api/safety'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { IncidentModal } from './IncidentModal'
import { PermitModal } from './PermitModal'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

type Tab = 'incidents' | 'talks' | 'permits'

/** Incidents and near misses with their cause and fix, the morning toolbox talk, and permits to work. */
export default function SafetyPage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [tab, setTab] = useState<Tab>('incidents')
  const q = useSafety(job)
  const d = q.data
  const s = d?.summary
  const [reporting, setReporting] = useState(false)
  const [permitting, setPermitting] = useState(false)
  const [talking, setTalking] = useState(false)
  const [closing, setClosing] = useState<Incident | null>(null)
  const [closingPermit, setClosingPermit] = useState<Permit | null>(null)
  const [photos, setPhotos] = useState<Incident | null>(null)
  const refresh = { invalidate: [safetyKeys.all, ['staff']] }
  const close = useAction((v: { i: Incident; cause: string; fix: string }) => closeIncident(v.i.id, { root_cause: v.cause, corrective_action: v.fix }), { ...refresh, success: (r) => `${r.incident.number} closed`, onSuccess: () => setClosing(null) })
  const closeP = useAction((v: { p: Permit; note: string }) => closePermit(v.p.id, v.note), { ...refresh, success: (r) => `${r.permit.number} closed`, onSuccess: () => setClosingPermit(null) })
  const talk = useAction((v: Record<string, string>) => { const n = /^\s*\d+\s*$/.test(v.who) ? parseInt(v.who) : 0; return recordTalk({ job_id: job, topic: v.topic, attendees: n, attendee_names: n ? '' : v.who }) }, { ...refresh, success: 'Talk recorded', onSuccess: () => setTalking(false) })
  const signoff = can('site.signoff')
  const add = () => (tab === 'talks' ? setTalking(true) : tab === 'permits' ? setPermitting(true) : setReporting(true))

  const incidents: TableColumn<Incident>[] = [
    { id: 'no', header: 'No.', cell: (i) => <span className="font-mono text-[13px]">{i.number}</span> },
    { id: 'when', header: 'When', sort: (i) => i.happened_on, cell: (i) => `${formatDate(i.happened_on)} ${i.happened_at}` },
    { id: 'kind', header: 'Kind', cell: (i) => <span className={i.serious ? 'font-semibold text-danger' : ''}>{i.kind}</span> },
    { id: 'what', header: 'What happened', hideBelow: 'md', cell: (i) => <div className="max-w-80"><span className="line-clamp-2">{i.description}</span>{i.location && <div className="text-xs text-muted-foreground">{i.location}</div>}{i.root_cause && <div className="text-xs text-success">Cause: {i.root_cause} - Fix: {i.corrective_action}</div>}</div> },
    { id: 'hurt', header: 'Hurt', hideBelow: 'lg', cell: (i) => (i.injured_name ? <div>{i.injured_name}<div className="text-xs text-muted-foreground">{i.injury}{i.lost_days ? `, ${i.lost_days} days lost` : ''}</div></div> : '-') },
    { id: 'status', header: 'Status', cell: (i) => <Badge tone={i.status === 'OPEN' ? (i.serious ? 'danger' : 'warning') : 'success'} dot>{i.status === 'OPEN' ? 'Open' : 'Closed'}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (i) => (
        <div className="flex justify-end gap-1.5">
          {i.status === 'OPEN' && signoff && <Button size="sm" onClick={() => setClosing(i)}>Close</Button>}
          <Button size="sm" variant="outline" onClick={() => setPhotos(i)}><Image /> Photos</Button>
          <Button size="sm" variant="outline" asChild><a href={`/api/safety/incidents/${i.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="incident" id={r.id} label={String(r.number)} noun="incident" /> },
  ]
  const talks: TableColumn<Talk>[] = [
    { id: 'on', header: 'On', sort: (t) => t.held_on, cell: (t) => formatDate(t.held_on) },
    { id: 'topic', header: 'Topic', cell: (t) => <div>{t.topic}{t.notes && <div className="text-xs text-muted-foreground">{t.notes}</div>}</div> },
    { id: 'by', header: 'By', hideBelow: 'md', cell: (t) => t.conducted_by },
    { id: 'att', header: 'Attended', cell: (t) => <div>{t.attendees}{t.attendee_names && <div className="text-xs text-muted-foreground">{t.attendee_names}</div>}</div> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="toolbox" id={r.id} label={String(r.topic)} noun="toolbox talk" /> },
  ]
  const permits: TableColumn<Permit>[] = [
    { id: 'no', header: 'Permit', cell: (p) => <span className="font-mono text-[13px]">{p.number}</span> },
    { id: 'kind', header: 'Kind', cell: (p) => p.kind },
    { id: 'where', header: 'Where', hideBelow: 'md', cell: (p) => p.location },
    { id: 'runs', header: 'Runs', hideBelow: 'lg', cell: (p) => `${p.valid_from.slice(5)} to ${p.valid_to.slice(5)}` },
    { id: 'who', header: 'Worker', hideBelow: 'md', cell: (p) => p.receiver },
    { id: 'status', header: 'Status', cell: (p) => <Badge tone={p.expired ? 'danger' : p.status === 'ACTIVE' ? 'success' : 'neutral'} dot>{p.expired ? 'Run out' : p.status === 'ACTIVE' ? 'Live' : 'Closed'}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (p) => (
        <div className="flex justify-end gap-1.5">
          {p.status === 'ACTIVE' && signoff && <Button size="sm" onClick={() => setClosingPermit(p)}>Close</Button>}
          <Button size="sm" variant="outline" asChild><a href={`/api/safety/permits/${p.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="permit" id={r.id} label={String(r.number)} noun="permit" /> },
  ]
  const register = `/api/safety/${tab}.xlsx${job ? `?job_id=${job}` : ''}`
  const noPermit = tab === 'permits' && !signoff
  return (
    <>
      <PageHeader eyebrow="Projects" title="Safety" description="Incidents and near misses with their cause and fix, the morning toolbox talk, and permits to work." actions={<><Button variant="outline" asChild><a href={register}><FileSpreadsheet /> Register</a></Button><Button disabled={!job || noPermit} title={noPermit ? 'A permit to work is issued by a supervisor.' : undefined} onClick={add}><Plus /> New</Button></>} />
      <div className="mb-6"><ProjectPicker value={job} onChange={setJob} id="sf-job" allowAll /></div>
      <StatGrid>
        <Stat label="Days without a lost-time injury" value={s ? (s.days_without_lti === null ? 'none yet' : s.days_without_lti) : 0} loading={q.isPending} />
        <Stat label="Incidents this month" value={s?.incidents_this_month ?? 0} loading={q.isPending} />
        <Stat label="Near misses reported" value={s?.near_misses ?? 0} loading={q.isPending} />
        <Stat label="Toolbox talks this week" value={s?.talks_this_week ?? 0} loading={q.isPending} />
        <Stat label="Permits live" value={s?.active_permits ?? 0} sub={s?.expired_open ? `${s.expired_open} run out` : undefined} tone={s?.expired_open ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <div className="mb-4"><Tabs label="Safety" value={tab} onChange={setTab} items={[{ value: 'incidents', label: 'Incidents' }, { value: 'talks', label: 'Toolbox talks' }, { value: 'permits', label: 'Permits to work' }]} /></div>
      {tab === 'incidents' && <DataTable label="Incidents" rows={d?.incidents ?? []} columns={incidents} rowKey={(i) => i.id} loading={q.isPending} empty="Nothing reported. A near miss written down is the cheapest lesson there is." />}
      {tab === 'talks' && <DataTable label="Toolbox talks" rows={d?.talks ?? []} columns={talks} rowKey={(t) => t.id} loading={q.isPending} empty="No talks recorded." />}
      {tab === 'permits' && <DataTable label="Permits" rows={d?.permits ?? []} columns={permits} rowKey={(p) => p.id} loading={q.isPending} empty="No permits issued." />}

      <IncidentModal job={job} kinds={d?.kinds ?? []} open={reporting} onClose={() => setReporting(false)} />
      <PermitModal job={job} kinds={d?.permit_kinds ?? {}} open={permitting} onClose={() => setPermitting(false)} />
      <PromptModal open={talking} title="Toolbox talk" description="Who stood through it? Names separated by commas, or just the number." fields={[{ key: 'topic', label: 'The topic', required: true }, { key: 'who', label: 'Who attended' }]} confirm="Record the talk" busy={talk.isPending} error={talk.error?.message} onSubmit={(v) => talk.mutate(v)} onClose={() => setTalking(false)} />
      <PromptModal open={!!closing} title={closing ? `Close ${closing.number}` : ''} description="What went wrong, and what stops it happening again." fields={[{ key: 'cause', label: 'Why did it happen? (the root cause)', required: true }, { key: 'fix', label: 'What stops it happening again?', required: true }]} confirm="Close it" busy={close.isPending} error={close.error?.message} onSubmit={(v) => closing && close.mutate({ i: closing, cause: v.cause, fix: v.fix })} onClose={() => setClosing(null)} />
      <PromptModal open={!!closingPermit} title={closingPermit ? `Close ${closingPermit.number}` : ''} description="Is the area safe and the work stopped?" fields={[{ key: 'note', label: 'A note', initial: 'Work complete, area cleared' }]} confirm="Close the permit" busy={closeP.isPending} error={closeP.error?.message} onSubmit={(v) => closingPermit && closeP.mutate({ p: closingPermit, note: v.note })} onClose={() => setClosingPermit(null)} />
      {photos && <FilesModal type="incident" id={photos.id} title={photos.number} onClose={() => setPhotos(null)} />}
    </>
  )
}
