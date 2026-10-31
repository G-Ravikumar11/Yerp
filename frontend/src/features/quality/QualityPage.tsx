import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ClipboardCheck, FileSpreadsheet, Image, Plus, Settings2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, Stat, StatGrid, Tabs } from '@/components/ui'
import { emptyQuery, exportUrl, useCubes, useInspections, useNcrs, useSummary, type CubeSet, type Inspection, type ListQuery, type Ncr } from '@/api/quality'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { CubeModal, CubeSetModal } from './CubeModals'
import { InspectionModal, NewInspectionModal } from './InspectionModal'
import { RegisterInspectionModal } from './RegisterInspectionModal'
import { CubeDashboard } from './CubeDashboard'
import { NcrDetail, NcrModal, type NcrSource } from './NcrModals'
import { SetupModal } from './SetupModal'
import { ListBar, LoadError, Pager, cubeTone, inspectionTone, ncrTone } from './parts'

type Tab = 'inspections' | 'cubes' | 'ncrs'

const STATUSES: Record<Tab, { value: string; label: string }[]> = {
  inspections: [{ value: 'PENDING', label: 'Pending' }, { value: 'SUBMITTED', label: 'Waiting for approval' }, { value: 'PASSED', label: 'Passed' }, { value: 'FAILED', label: 'Failed' }],
  cubes: [
    { value: 'to_crush', label: 'To crush (due or overdue)' }, { value: 'below_grade', label: 'Below criteria' }, { value: 'review', label: 'For engineering review' },
    { value: 'awaiting_results', label: 'Awaiting results' }, { value: 'criteria_not_set', label: 'Criteria not set' }, { value: 'accepted', label: 'Accepted' },
    { value: 'accepted_with_conditions', label: 'Accepted with conditions' }, { value: 'rejected', label: 'Rejected' },
  ],
  ncrs: [
    { value: 'not_closed', label: 'Not closed' }, { value: 'overdue', label: 'Overdue' }, { value: 'OPEN', label: 'Open' }, { value: 'ASSIGNED', label: 'Assigned' },
    { value: 'UNDER_CORRECTION', label: 'Under correction' }, { value: 'REINSPECTION', label: 'Reinspection' }, { value: 'CLOSED', label: 'Closed' }, { value: 'REJECTED', label: 'Rejected' },
  ],
}
const SORTS: Record<Tab, { value: string; label: string }[]> = {
  inspections: [{ value: 'date', label: 'Date' }, { value: 'number', label: 'Inspection ID' }, { value: 'checklist', label: 'Checklist' }, { value: 'inspector', label: 'Inspector' }, { value: 'result', label: 'Result' }],
  cubes: [{ value: 'cast', label: 'Casting date' }, { value: 'number', label: 'Sample ID' }, { value: 'grade', label: 'Grade' }, { value: 'status', label: 'Status' }],
  ncrs: [{ value: 'raised', label: 'Raised' }, { value: 'due', label: 'Due date' }, { value: 'number', label: 'NCR number' }, { value: 'severity', label: 'Severity' }, { value: 'status', label: 'Status' }],
}
const TAB_LABEL: Record<Tab, string> = { inspections: 'Inspections', cubes: 'Cube tests', ncrs: 'Non-conformances' }

/** Checklists walked before work is covered, cubes read against the criteria, and non-conformances followed to a verified close. */
export default function QualityPage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [tab, setTab] = useState<Tab>('inspections')
  const [filters, setFilters] = useState<Record<Tab, ListQuery>>({ inspections: emptyQuery(), cubes: emptyQuery(), ncrs: emptyQuery() })
  const f: ListQuery = { ...filters[tab], job }
  const patch = useCallback((p: Partial<ListQuery>) => setFilters((all) => ({ ...all, [tab]: { ...all[tab], ...p } })), [tab])
  const sum = useSummary(job)
  const ins = useInspections({ ...filters.inspections, job })
  const cubes = useCubes({ ...filters.cubes, job })
  const ncrs = useNcrs({ ...filters.ncrs, job })
  const active = { inspections: ins, cubes, ncrs }[tab]

  const [starting, setStarting] = useState(false)
  const [registering, setRegistering] = useState(false)
  const [cubing, setCubing] = useState(false)
  const [setup, setSetup] = useState(false)
  const [ncrFrom, setNcrFrom] = useState<NcrSource | 'new' | null>(null)
  const [openIns, setOpenIns] = useState<number | null>(null)
  const [openCube, setOpenCube] = useState<number | null>(null)
  // A link from a store batch or a failed cube test opens its NCR here.
  const [params] = useSearchParams()
  const [openNcr, setOpenNcr] = useState<number | null>(Number(params.get('ncr')) || null)
  const [photos, setPhotos] = useState<{ type: string; id: number; title: string } | null>(null)

  const go = (to: Tab, status: string) => { setTab(to); setFilters((all) => ({ ...all, [to]: { ...emptyQuery(), size: all[to].size, status } })) }
  // Register puts on the record what has been done: an inspection carried out, a pour's cubes, a defect found.
  const register = () => (tab === 'cubes' ? setCubing(true) : tab === 'ncrs' ? setNcrFrom('new') : setRegistering(true))
  const add = () => (tab === 'cubes' ? setCubing(true) : tab === 'ncrs' ? setNcrFrom('new') : setStarting(true))
  const filtered = !!(f.q || f.status || f.from || f.to || f.severity)
  const s = sum.data
  const is = (t: Tab, status: string) => tab === t && f.status === status

  const inspectionCols: TableColumn<Inspection>[] = [
    { id: 'no', header: 'Inspection ID', cell: (i) => <button type="button" className="font-mono text-[13px] font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpenIns(i.id)}>{i.number}</button> },
    { id: 'list', header: 'Checklist / activity', cell: (i) => <div>{i.checklist}{i.work_activity && <div className="text-xs text-muted-foreground">{i.work_activity}</div>}</div> },
    { id: 'where', header: 'Project and location', hideBelow: 'md', cell: (i) => <div>{i.project}<div className="text-xs text-muted-foreground">{[i.building, i.floor_area, i.location].filter(Boolean).join(' - ')}</div></div> },
    { id: 'on', header: 'Date', hideBelow: 'lg', cell: (i) => formatDate(i.inspected_on) },
    { id: 'by', header: 'Inspector', hideBelow: 'lg', cell: (i) => i.assigned_to || i.inspected_by },
    { id: 'res', header: 'Result', cell: (i) => <div className="flex flex-wrap items-center gap-1.5"><Badge tone={inspectionTone(i.result)} dot>{i.result_label}</Badge>{i.approval_status === 'submitted' && <Badge tone="info">Awaiting approval</Badge>}{i.failed_items > 0 && <span className="text-xs text-danger">{i.failed_items} not ok</span>}</div> },
    {
      id: 'act', header: 'Actions', align: 'right',
      cell: (i) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setOpenIns(i.id)}>{i.editable && can('site.record') ? 'Open' : 'View'}</Button>
          <Button size="sm" variant="outline" aria-label={`Photos for ${i.number}`} onClick={() => setPhotos({ type: 'inspection', id: i.id, title: i.number })}><Image /></Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="inspection" simple id={r.id} label={String(r.number)} noun="inspection" /> },
  ]

  const cubeCols: TableColumn<CubeSet>[] = [
    { id: 'no', header: 'Sample ID', cell: (c) => <div><button type="button" className="font-mono text-[13px] font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpenCube(c.id)}>{c.number}</button>{c.cube_ids && <div className="text-xs text-muted-foreground">{c.cube_ids}</div>}</div> },
    { id: 'grade', header: 'Grade', cell: (c) => c.grade },
    { id: 'where', header: 'Pour / location', hideBelow: 'md', cell: (c) => <div>{c.location}<div className="text-xs text-muted-foreground">{[c.project, c.pour_ref].filter(Boolean).join(' - ')}</div></div> },
    { id: 'cast', header: 'Cast', hideBelow: 'lg', cell: (c) => formatDate(c.cast_on) },
    {
      id: 'tests', header: 'Tests (MPa)',
      cell: (c) => (
        <ul className="grid gap-0.5 text-[13px]">
          {c.schedule.map((t) => {
            const r = c.results.find((x) => x.age_days === t.age_days)
            return r ? (
              <li key={t.age_days}><span className="text-muted-foreground">{t.age_days}d</span> <span className={r.failed ? 'font-semibold text-danger' : r.evaluation === 'no_criteria' ? 'font-semibold text-info' : 'font-semibold'}>{r.average}</span>{!r.spread_ok && <span title="A cube is more than 15% off the average" className="ml-1 text-warning">!</span>} <span className="text-xs text-muted-foreground">tested {formatDate(r.tested_on)}</span></li>
            ) : (
              <li key={t.age_days} className={t.state === 'overdue' ? 'text-danger' : 'text-muted-foreground'}><span>{t.age_days}d</span> {t.state === 'overdue' ? 'overdue, was due' : t.state === 'due' ? 'due today' : 'due'} {t.state === 'due' ? '' : formatDate(t.due_on)}</li>
            )
          })}
        </ul>
      ),
    },
    { id: 'st', header: 'Status', cell: (c) => <div className="flex flex-col items-start gap-1"><Badge tone={cubeTone(c.status)} dot>{c.status}</Badge>{c.needs_review && c.status !== 'for engineering review' && c.status !== 'criteria not set' && <span className="text-xs text-info">needs review</span>}</div> },
    {
      id: 'act', header: 'Actions', align: 'right',
      cell: (c) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setOpenCube(c.id)}>{can('site.record') && c.due.length ? 'Result' : 'View'}</Button>
          <Button size="sm" variant="outline" aria-label={`Test reports for ${c.number}`} onClick={() => setPhotos({ type: 'cube_set', id: c.id, title: `${c.number} test reports` })}><Image /></Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="cube_set" simple id={r.id} label={String(r.number)} noun="cube set" /> },
  ]

  const ncrCols: TableColumn<Ncr>[] = [
    { id: 'no', header: 'NCR', cell: (n) => <button type="button" className="font-mono text-[13px] font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpenNcr(n.id)}>{n.number}</button> },
    { id: 'where', header: 'Project and location', hideBelow: 'md', cell: (n) => <div>{n.project}<div className="text-xs text-muted-foreground">{n.location}</div></div> },
    { id: 'what', header: 'Issue', cell: (n) => <div className="max-w-80"><span className="line-clamp-2">{n.description}</span>{n.closure_note && <div className="text-xs text-success">Closed: {n.closure_note}</div>}</div> },
    { id: 'sev', header: 'Severity', hideBelow: 'sm', cell: (n) => <Badge tone={n.severity === 'Minor' ? 'neutral' : 'danger'}>{n.severity}</Badge> },
    { id: 'owner', header: 'Responsible', hideBelow: 'lg', cell: (n) => n.responsible },
    { id: 'by', header: 'Due', hideBelow: 'lg', cell: (n) => <span className={n.overdue ? 'font-semibold text-danger' : ''}>{formatDate(n.target_date)}</span> },
    { id: 'st', header: 'Status', cell: (n) => <Badge tone={ncrTone(n.status, n.overdue)} dot>{n.overdue ? 'Late - ' : ''}{n.status_label}</Badge> },
    {
      id: 'act', header: 'Actions', align: 'right',
      cell: (n) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setOpenNcr(n.id)}>Open</Button>
          <Button size="sm" variant="outline" aria-label={`Evidence for ${n.number}`} onClick={() => setPhotos({ type: 'ncr', id: n.id, title: n.number })}><Image /></Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="ncr" simple id={r.id} label={String(r.number)} noun="NCR" /> },
  ]

  const empty = filtered ? `No ${TAB_LABEL[tab].toLowerCase()} match these filters.` : { inspections: 'No inspections yet. Walk the checklist before work is covered up.', cubes: "No cube samples yet. Register each pour's cubes the day they are cast.", ncrs: 'No non-conformances.' }[tab]
  const total = active.data?.total ?? 0
  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Quality"
        description="Checklists walked before work is covered, cubes read against the criteria, and non-conformances followed to a verified close."
        actions={
          <>
            {can('site.signoff') && <Button variant="outline" onClick={() => setSetup(true)}><Settings2 /> Checklists and criteria</Button>}
            <Button variant="outline" asChild><a href={exportUrl(tab, f)} title="Download the register as a spreadsheet"><FileSpreadsheet /> Export</a></Button>
            {can('site.record') && <Button variant="outline" onClick={register}><ClipboardCheck /> Register</Button>}
            {can('site.record') && <Button onClick={add}><Plus /> New</Button>}
          </>
        }
      />
      <div className="mb-6"><ProjectPicker value={job} onChange={(j) => { setJob(j); setFilters((all) => ({ inspections: { ...all.inspections, page: 1 }, cubes: { ...all.cubes, page: 1 }, ncrs: { ...all.ncrs, page: 1 } })) }} id="qc-job" allowAll /></div>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Inspections failed" value={s?.inspections_failed ?? 0} tone={s?.inspections_failed ? 'danger' : undefined} sub={s?.inspections_awaiting_approval ? `${s.inspections_awaiting_approval} awaiting approval` : undefined} loading={sum.isPending} onClick={() => go('inspections', 'FAILED')} active={is('inspections', 'FAILED')} />
        <Stat label="Cubes to crush" value={s?.cubes_to_crush ?? 0} tone={s?.cubes_overdue ? 'warning' : undefined} sub={s?.cubes_overdue ? `${s.cubes_overdue} overdue` : undefined} loading={sum.isPending} onClick={() => go('cubes', 'to_crush')} active={is('cubes', 'to_crush')} />
        <Stat label="Below grade" value={s?.below_grade ?? 0} tone={s?.below_grade ? 'danger' : undefined} sub={s?.cubes_for_review ? `${s.cubes_for_review} for engineering review` : undefined} loading={sum.isPending} onClick={() => go('cubes', 'below_grade')} active={is('cubes', 'below_grade')} />
        <Stat label="NCRs open" value={s?.ncrs_open ?? 0} sub={s?.ncrs_overdue ? `${s.ncrs_overdue} late` : undefined} loading={sum.isPending} onClick={() => go('ncrs', 'not_closed')} active={is('ncrs', 'not_closed')} />
      </StatGrid>
      {sum.isError && <div className="mb-4"><LoadError message={sum.error.message} retry={() => sum.refetch()} /></div>}
      <div className="mb-4"><Tabs label="Quality" value={tab} onChange={setTab} items={[{ value: 'inspections', label: 'Inspections' }, { value: 'cubes', label: 'Cube tests' }, { value: 'ncrs', label: 'Non-conformances' }]} /></div>
      <ListBar key={tab} f={f} set={patch} statuses={STATUSES[tab]} sorts={SORTS[tab]} severities={tab === 'ncrs' ? ['Minor', 'Major', 'Critical'] : undefined} placeholder={{ inspections: 'Search ID, checklist, location, inspector', cubes: 'Search sample, pour, grade, supplier', ncrs: 'Search NCR, issue, location, responsible' }[tab]} />
      {tab === 'cubes' && <CubeDashboard job={job} onNcr={setOpenNcr} />}
      {active.isError ? (
        <LoadError message={active.error.message} retry={() => active.refetch()} />
      ) : (
        <Card className="overflow-hidden">
          <div className={active.isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}>
            {tab === 'inspections' && <DataTable label="Inspections" className="rounded-none border-0 shadow-none" rows={ins.data?.rows ?? []} columns={inspectionCols} rowKey={(i) => i.id} loading={ins.isPending} empty={empty} />}
            {tab === 'cubes' && <DataTable label="Cube samples" className="rounded-none border-0 shadow-none" rows={cubes.data?.rows ?? []} columns={cubeCols} rowKey={(c) => c.id} loading={cubes.isPending} empty={empty} footer={<p className="px-4 py-2 text-xs text-muted-foreground">Averages in N/mm2 (MPa), read against the criteria set for the project. "!" marks a cube more than 15% off its set's average (IS 516). A result is evidence; the engineer accepts the concrete.</p>} />}
            {tab === 'ncrs' && <DataTable label="Non-conformances" className="rounded-none border-0 shadow-none" rows={ncrs.data?.rows ?? []} columns={ncrCols} rowKey={(n) => n.id} loading={ncrs.isPending} empty={empty} />}
          </div>
          {!active.isPending && <Pager f={f} total={total} set={patch} />}
        </Card>
      )}

      <RegisterInspectionModal job={job} open={registering} onClose={() => setRegistering(false)} onRegistered={(i) => { setRegistering(false); setTab('inspections'); setOpenIns(i.id) }} />
      <NewInspectionModal job={job} open={starting} onClose={() => setStarting(false)} onStarted={(i) => { setStarting(false); setTab('inspections'); setOpenIns(i.id) }} />
      <InspectionModal id={openIns} onClose={() => setOpenIns(null)} onPhotos={(i) => setPhotos({ type: 'inspection', id: i.id, title: i.number })} onNcr={(i) => setNcrFrom({ type: 'inspection', id: i.id })} onOpen={setOpenIns} />
      <CubeSetModal job={job} open={cubing} onClose={() => setCubing(false)} onLogged={(c) => { setCubing(false); setTab('cubes'); setOpenCube(c.id) }} />
      <CubeModal id={openCube} onClose={() => setOpenCube(null)} onNcr={(c, age) => setNcrFrom({ type: 'cube_set', id: c.id, ref: age ? String(age) : '' })} onFiles={(c) => setPhotos({ type: 'cube_set', id: c.id, title: `${c.number} test reports` })} />
      <NcrModal job={job} from={ncrFrom && ncrFrom !== 'new' ? ncrFrom : null} open={!!ncrFrom} onClose={() => setNcrFrom(null)} onRaised={(n) => { setOpenIns(null); setOpenCube(null); setTab('ncrs'); setOpenNcr(n.id) }} />
      <NcrDetail id={openNcr} onClose={() => setOpenNcr(null)} onPhotos={(n) => setPhotos({ type: 'ncr', id: n.id, title: `${n.number} evidence` })} />
      <SetupModal job={job} open={setup} onClose={() => setSetup(false)} />
      {photos && <FilesModal type={photos.type} id={photos.id} title={photos.title} onClose={() => setPhotos(null)} />}
    </>
  )
}
