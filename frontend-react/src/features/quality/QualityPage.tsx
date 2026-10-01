import { useState } from 'react'
import { FileSpreadsheet, FileText, Image, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { PromptModal } from '@/components/data/PromptModal'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Stat, StatGrid, Tabs } from '@/components/ui'
import { closeNcr, qcKeys, useQuality, type CubeSet, type Inspection, type Ncr } from '@/api/quality'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { CubeResultModal, CubeSetModal, NcrModal } from './CubeModals'
import { InspectionModal, NewInspectionModal } from './InspectionModal'

type Tab = 'inspections' | 'cubes' | 'ncrs'
const resultTone = (r: string) => (r === 'PASSED' ? 'success' : r === 'FAILED' ? 'danger' : 'warning') as 'success' | 'danger' | 'warning'

/** Checklists walked before work is covered, cubes read against the grade, and non-conformances followed to a close. */
export default function QualityPage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [tab, setTab] = useState<Tab>('inspections')
  const q = useQuality(job)
  const d = q.data
  const [starting, setStarting] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [cubing, setCubing] = useState(false)
  const [result, setResult] = useState<CubeSet | null>(null)
  const [ncrFrom, setNcrFrom] = useState<{ type: string; id: number } | 'new' | null>(null)
  const [closing, setClosing] = useState<Ncr | null>(null)
  const [photos, setPhotos] = useState<{ type: string; id: number; title: string } | null>(null)
  const close = useAction((v: { n: Ncr; note: string }) => closeNcr(v.n.id, v.note), { invalidate: [qcKeys.all], success: (r) => `${r.ncr.number} closed`, onSuccess: () => setClosing(null) })
  const current = d?.inspections.find((i) => i.id === open) ?? null
  const add = () => (tab === 'cubes' ? setCubing(true) : tab === 'ncrs' ? setNcrFrom('new') : setStarting(true))

  const inspections: TableColumn<Inspection>[] = [
    { id: 'no', header: 'No.', cell: (i) => <button type="button" className="font-mono text-[13px] font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(i.id)}>{i.number}</button> },
    { id: 'list', header: 'Checklist', cell: (i) => i.checklist },
    { id: 'where', header: 'Where', hideBelow: 'md', cell: (i) => i.location },
    { id: 'on', header: 'On', hideBelow: 'lg', sort: (i) => i.inspected_on, cell: (i) => formatDate(i.inspected_on) },
    { id: 'by', header: 'By', hideBelow: 'lg', cell: (i) => i.inspected_by },
    { id: 'res', header: 'Result', cell: (i) => <div className="flex items-center gap-1.5"><Badge tone={resultTone(i.result)} dot>{i.result === 'OPEN' ? 'Open' : i.result === 'PASSED' ? 'Passed' : 'Failed'}</Badge>{i.failed_items > 0 && <span className="text-xs text-danger">{i.failed_items} not ok</span>}</div> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (i) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setOpen(i.id)}>Open</Button>
          <Button size="sm" variant="outline" onClick={() => setPhotos({ type: 'inspection', id: i.id, title: i.number })}><Image /> Photos</Button>
        </div>
      ),
    },
  ]
  const cubes: TableColumn<CubeSet>[] = [
    { id: 'no', header: 'Set', cell: (c) => <span className="font-mono text-[13px]">{c.number}</span> },
    { id: 'cast', header: 'Cast', sort: (c) => c.cast_on, cell: (c) => formatDate(c.cast_on) },
    { id: 'where', header: 'Where', hideBelow: 'md', cell: (c) => <div>{c.location}{c.supplier && <div className="text-xs text-muted-foreground">{c.supplier}{c.docket && ` #${c.docket}`}</div>}</div> },
    { id: 'grade', header: 'Grade', cell: (c) => c.grade },
    ...[7, 28].map((age): TableColumn<CubeSet> => ({
      id: `d${age}`,
      header: `${age} days`,
      cell: (c) => {
        const r = c.results.find((x) => x.age_days === age)
        if (r) return <span className={r.ok ? 'font-semibold' : 'font-semibold text-danger'}>{r.average}{!r.spread_ok && <span title="A cube is more than 15% off the average" className="ml-1 text-warning">!</span>}</span>
        const due = c.due.find((x) => x.age_days === age)
        return due ? <span className={`text-xs ${due.overdue ? 'text-danger' : 'text-muted-foreground'}`}>due {formatDate(due.due_on)}</span> : null
      },
    })),
    { id: 'st', header: 'Status', cell: (c) => <Badge tone={c.status === 'below grade' ? 'danger' : c.status === 'meets grade' ? 'success' : 'neutral'} dot>{c.status}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (c) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setResult(c)}>Result</Button>
          {c.status === 'below grade' && <Button size="sm" variant="outline" className="text-danger" onClick={() => setNcrFrom({ type: 'cube_set', id: c.id })}>Raise NCR</Button>}
        </div>
      ),
    },
  ]
  const ncrs: TableColumn<Ncr>[] = [
    { id: 'no', header: 'NCR', cell: (n) => <div><span className="font-mono text-[13px]">{n.number}</span>{n.severity === 'Major' && <div className="text-[11px] text-danger">major</div>}</div> },
    { id: 'raised', header: 'Raised', hideBelow: 'lg', sort: (n) => n.raised_on, cell: (n) => formatDate(n.raised_on) },
    { id: 'where', header: 'Where', hideBelow: 'md', cell: (n) => n.location },
    { id: 'what', header: 'What', cell: (n) => <div className="max-w-80"><span className="line-clamp-2">{n.description}</span>{n.closure_note && <div className="text-xs text-success">Closed: {n.closure_note}</div>}</div> },
    { id: 'owner', header: 'Owner', hideBelow: 'lg', cell: (n) => n.responsible },
    { id: 'by', header: 'By', hideBelow: 'lg', cell: (n) => <span className={n.overdue ? 'font-semibold text-danger' : ''}>{formatDate(n.target_date)}</span> },
    { id: 'st', header: 'Status', cell: (n) => <Badge tone={n.overdue ? 'danger' : n.status === 'OPEN' ? 'warning' : 'success'} dot>{n.status === 'OPEN' ? (n.overdue ? 'Late' : 'Open') : 'Closed'}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (n) => (
        <div className="flex justify-end gap-1.5">
          {n.status === 'OPEN' && can('site.signoff') && <Button size="sm" onClick={() => setClosing(n)}>Close</Button>}
          <Button size="sm" variant="outline" onClick={() => setPhotos({ type: 'ncr', id: n.id, title: n.number })}><Image /> Photos</Button>
          <Button size="sm" variant="outline" asChild><a href={`/api/qc/ncrs/${n.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        </div>
      ),
    },
  ]
  const failed = d?.inspections.filter((i) => i.result === 'FAILED').length ?? 0
  return (
    <>
      <PageHeader eyebrow="Projects" title="Quality" description="Checklists walked before work is covered, cubes read against the grade, and non-conformances followed to a close." actions={<><Button variant="outline" asChild><a href={`/api/qc/${tab}.xlsx${job ? `?job_id=${job}` : ''}`}><FileSpreadsheet /> Register</a></Button><Button disabled={!job} onClick={add}><Plus /> New</Button></>} />
      <div className="mb-6"><ProjectPicker value={job} onChange={setJob} id="qc-job" allowAll /></div>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Inspections failed" value={failed} tone={failed ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Cubes to crush" value={d?.cubeSummary.due ?? 0} loading={q.isPending} />
        <Stat label="Below grade" value={d?.cubeSummary.below ?? 0} tone={d?.cubeSummary.below ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="NCRs open" value={d?.ncrSummary.open ?? 0} sub={d?.ncrSummary.overdue ? `${d.ncrSummary.overdue} late` : undefined} loading={q.isPending} />
      </StatGrid>
      <div className="mb-4"><Tabs label="Quality" value={tab} onChange={setTab} items={[{ value: 'inspections', label: 'Inspections' }, { value: 'cubes', label: 'Cube tests' }, { value: 'ncrs', label: 'Non-conformances' }]} /></div>
      {tab === 'inspections' && <DataTable label="Inspections" rows={d?.inspections ?? []} columns={inspections} rowKey={(i) => i.id} loading={q.isPending} empty="No inspections yet. Walk the checklist before work is covered up." />}
      {tab === 'cubes' && <DataTable label="Cube sets" rows={d?.cubes ?? []} columns={cubes} rowKey={(c) => c.id} loading={q.isPending} empty="No cube sets yet. Log each pour's cubes the day they are cast." footer={<p className="px-4 py-2 text-xs text-muted-foreground">Averages in N/mm2. "!" marks a set with a cube more than 15% off its average (IS 516).</p>} />}
      {tab === 'ncrs' && <DataTable label="Non-conformances" rows={d?.ncrs ?? []} columns={ncrs} rowKey={(n) => n.id} loading={q.isPending} empty="No non-conformances." />}

      <NewInspectionModal job={job} open={starting} onClose={() => setStarting(false)} onStarted={(i) => { setStarting(false); setOpen(i.id) }} />
      <InspectionModal inspection={current} onClose={() => setOpen(null)} onPhotos={(i) => setPhotos({ type: 'inspection', id: i.id, title: i.number })} onNcr={(i) => setNcrFrom({ type: 'inspection', id: i.id })} />
      <CubeSetModal job={job} open={cubing} onClose={() => setCubing(false)} />
      <CubeResultModal set={result} onClose={() => setResult(null)} />
      <NcrModal job={job} from={ncrFrom && ncrFrom !== 'new' ? ncrFrom : null} open={!!ncrFrom} onClose={() => setNcrFrom(null)} onRaised={() => { setOpen(null); setTab('ncrs') }} />
      <PromptModal open={!!closing} title={closing ? `Close ${closing.number}` : ''} description="What was done to put it right?" fields={[{ key: 'note', label: 'What was done', required: true }]} confirm="Close it" busy={close.isPending} error={close.error?.message} onSubmit={(v) => closing && close.mutate({ n: closing, note: v.note })} onClose={() => setClosing(null)} />
      {photos && <FilesModal type={photos.type} id={photos.id} title={photos.title} onClose={() => setPhotos(null)} />}
    </>
  )
}
