import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileSpreadsheet, FileText, History as HistoryIcon, Pencil, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, Field, Input, Modal, NumField, Select, Stat, StatGrid } from '@/components/ui'
import { apiUrl, get, post, put } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'

interface Entry {
  id: number; job_id: number; project: string; block: string; floor: string; element: string; member_ref: string; bar_mark: string; diameter_mm: number; grade: string; shape: string; dims: Record<string, number>
  num_bars: number; cutting_length_mm: number; total_length_m: number; unit_weight_kg_m: number; total_weight_kg: number; remarks: string; status: string; revision: number; approved_by: string
}
interface Shape { value: string; label: string; dims: string[] }
interface Group { block: string; floor: string; element: string; bars: number; total_length_m: number; total_weight_kg: number }
interface Data { entries: Entry[]; elements: string[]; grades: string[]; shapes: Shape[]; summary: { entries: number; total_length_m: number; total_weight_kg: number; by_diameter: { diameter_mm: number; bars: number; total_length_m: number; total_weight_kg: number }[]; by_group: Group[] } }
interface Figures { cutting_length_mm: number; total_length_m: number; unit_weight_kg_m: number; total_weight_kg: number }
interface Revision { revision: number; reason: string; by: string; at: string; entry: Entry }

const KEY = ['bbs'] as const
const fix = (v: number, n = 2) => v.toLocaleString('en-IN', { minimumFractionDigits: n, maximumFractionDigits: n })
const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'

/** Every bar mark of a project, what it takes to cut and what it weighs. All the figures come from the server. */
export default function BbsPage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [f, setF] = useState({ floor: '', element: '', bar_mark: '', diameter: '' })
  const [editing, setEditing] = useState<Entry | 'new' | null>(null)
  const [history, setHistory] = useState<Entry | null>(null)
  const [rules, setRules] = useState(false)
  const qs = `job_id=${job ?? 0}&floor=${encodeURIComponent(f.floor)}&element=${encodeURIComponent(f.element)}&bar_mark=${encodeURIComponent(f.bar_mark)}&diameter=${f.diameter || 0}`
  const q = useQuery({ queryKey: [...KEY, qs], queryFn: () => get<Data>(`/api/bbs?${qs}`) })
  const approve = useAction((ids: number[]) => post<{ message: string }>('/api/bbs/approve', { ids }), { invalidate: [KEY], success: (r) => r.message })
  const d = q.data
  const drafts = (d?.entries ?? []).filter((e) => e.status !== 'Approved').map((e) => e.id)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const cols: TableColumn<Entry>[] = [
    { id: 'm', header: 'Member', cell: (e) => <div className="font-medium">{e.member_ref}<div className="text-xs font-normal text-muted-foreground">{e.element} - {e.block}, {e.floor}</div></div> },
    { id: 'b', header: 'Bar mark', sort: (e) => e.bar_mark, cell: (e) => <span className="font-mono">{e.bar_mark}</span> },
    { id: 'd', header: 'Dia', align: 'right', sort: (e) => e.diameter_mm, cell: (e) => <div>{e.diameter_mm}<div className="text-xs text-muted-foreground">{e.grade}</div></div> },
    { id: 's', header: 'Shape', hideBelow: 'md', cell: (e) => e.shape },
    { id: 'n', header: 'Bars', align: 'right', cell: (e) => e.num_bars },
    { id: 'c', header: 'Cut (mm)', align: 'right', hideBelow: 'md', cell: (e) => fix(e.cutting_length_mm, 0) },
    { id: 'l', header: 'Length (m)', align: 'right', cell: (e) => fix(e.total_length_m) },
    { id: 'u', header: 'kg/m', align: 'right', hideBelow: 'lg', cell: (e) => fix(e.unit_weight_kg_m, 3) },
    { id: 'w', header: 'Weight (kg)', align: 'right', sort: (e) => e.total_weight_kg, cell: (e) => <strong>{fix(e.total_weight_kg)}</strong> },
    { id: 'st', header: 'Status', cell: (e) => <div><Badge tone={e.status === 'Approved' ? 'success' : 'warning'} dot>{e.status}</Badge>{e.revision > 0 && <div className="text-xs text-muted-foreground">Rev {e.revision}</div>}</div> },
    {
      id: 'a', header: '', align: 'right',
      cell: (e) => (
        <div className="flex justify-end gap-1">
          {e.status !== 'Approved' && can('site.signoff') && <Button size="sm" variant="outline" onClick={() => approve.mutate([e.id])}>Approve</Button>}
          {(e.status !== 'Approved' ? can('site.record') : can('site.signoff')) && <Button size="icon-sm" variant="ghost" aria-label={`Edit ${e.bar_mark}`} onClick={() => setEditing(e)}><Pencil /></Button>}
          {e.revision > 0 && <Button size="icon-sm" variant="ghost" aria-label={`History of ${e.bar_mark}`} onClick={() => setHistory(e)}><HistoryIcon /></Button>}
        </div>
      ),
    },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Bar Bending Schedule" description="Every bar mark of a project: what it takes to cut, and what the steel weighs."
        actions={<>
          <Button variant="outline" asChild><a href={apiUrl(`/api/bbs/export.xlsx?${qs}`)}><FileSpreadsheet /> Excel</a></Button>
          {job ? <Button variant="outline" asChild><a href={apiUrl(`/api/bbs/schedule.pdf?job_id=${job}`)} target="_blank" rel="noopener"><FileText /> PDF</a></Button> : null}
          {can('site.signoff') && <Button variant="outline" onClick={() => setRules(true)}>Bend rules</Button>}
          {can('site.record') && <Button onClick={() => setEditing('new')}><Plus /> Bar mark</Button>}
        </>} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-72"><ProjectPicker id="bbs-job" value={job} onChange={setJob} allowAll /></div>
        <div className="w-32"><Input aria-label="Floor" placeholder="Floor" value={f.floor} onChange={set('floor')} /></div>
        <div className="w-36"><Select aria-label="Element" value={f.element} placeholder="Any element" onChange={set('element')} options={(d?.elements ?? []).map((x) => ({ value: x, label: x }))} /></div>
        <div className="w-32"><Input aria-label="Bar mark" placeholder="Bar mark" value={f.bar_mark} onChange={set('bar_mark')} /></div>
        <div className="w-28"><Input aria-label="Diameter" placeholder="Dia (mm)" inputMode="decimal" value={f.diameter} onChange={set('diameter')} /></div>
        {drafts.length > 1 && can('site.signoff') && <Button className="ml-auto" variant="outline" loading={approve.isPending} onClick={() => approve.mutate(drafts)}>Approve all {drafts.length}</Button>}
      </div>
      <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
        <Stat label="Bar marks" value={d?.summary.entries ?? 0} loading={q.isPending} />
        <Stat label="Total length" value={`${fix(d?.summary.total_length_m ?? 0)} m`} loading={q.isPending} />
        <Stat label="Total steel" value={`${fix(d?.summary.total_weight_kg ?? 0)} kg`} loading={q.isPending} />
      </StatGrid>
      {q.isError ? <p role="alert" className="text-sm text-danger">{q.error.message}</p> : <Card className="overflow-hidden"><DataTable label="Bar marks" className="rounded-none border-0 shadow-none" rows={d?.entries ?? []} columns={cols} rowKey={(e) => e.id} loading={q.isPending} empty="No bar marks for these filters." /></Card>}
      {(d?.summary.by_group.length ?? 0) > 0 && (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <Summary title="By floor and element" head={['Block', 'Floor', 'Element', 'Bars', 'Length (m)', 'Weight (kg)']} rows={d!.summary.by_group.map((g) => [g.block, g.floor, g.element, String(g.bars), fix(g.total_length_m), fix(g.total_weight_kg)])} />
          <Summary title="By diameter" head={['Dia (mm)', 'Bars', 'Length (m)', 'Weight (kg)']} rows={d!.summary.by_diameter.map((g) => [String(g.diameter_mm), String(g.bars), fix(g.total_length_m), fix(g.total_weight_kg)])} />
        </div>
      )}
      {editing && d && <EntryModal entry={editing === 'new' ? null : editing} job={job} data={d} onClose={() => setEditing(null)} />}
      {history && <HistoryModal entry={history} onClose={() => setHistory(null)} />}
      {rules && <RulesModal job={job} onClose={() => setRules(false)} />}
    </>
  )
}

function Summary({ title, head, rows }: { title: string; head: string[]; rows: string[][] }) {
  return (
    <section aria-label={title}>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-border"><table className="w-full text-[13px]"><thead className="bg-surface"><tr>{head.map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={i} className="border-t border-border">{r.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}</tr>)}</tbody></table></div>
    </section>
  )
}

function EntryModal({ entry: e, job, data, onClose }: { entry: Entry | null; job: number; data: Data; onClose: () => void }) {
  const [project, setProject] = useState(e?.job_id ?? job)
  const [f, setF] = useState({ block: e?.block ?? '', floor: e?.floor ?? '', element: e?.element ?? 'Beam', member_ref: e?.member_ref ?? '', bar_mark: e?.bar_mark ?? '', grade: e?.grade ?? 'Fe500D', shape: e?.shape ?? 'Straight', remarks: e?.remarks ?? '', reason: '' })
  const [n, setN] = useState({ diameter_mm: e?.diameter_mm ?? 0, num_bars: e?.num_bars ?? 0, cutting_length_mm: e?.cutting_length_mm ?? 0 })
  const [dims, setDims] = useState<Record<string, number>>(e?.dims ?? {})
  const [figures, setFigures] = useState<Figures | null>(null)
  const [problem, setProblem] = useState('')
  const set = (k: keyof typeof f) => (x: { target: { value: string } }) => setF((v) => ({ ...v, [k]: x.target.value }))
  const shape = data.shapes.find((s) => s.value === f.shape)
  const body = { ...f, ...n, dims, job_id: project }
  const ready = project && n.diameter_mm > 0 && n.num_bars > 0
  const signature = JSON.stringify(body)
  useEffect(() => {
    if (!ready) return
    const t = setTimeout(() => { post<Figures>('/api/bbs/calculate', JSON.parse(signature)).then((r) => { setFigures(r); setProblem('') }, (x: Error) => { setFigures(null); setProblem(x.message) }) }, 300)
    return () => clearTimeout(t)
  }, [signature, ready])
  const save = useAction(() => (e ? put<{ message: string }>(`/api/bbs/${e.id}`, body) : post<{ message: string }>('/api/bbs', body)), { invalidate: [KEY], success: (r) => r.message, onSuccess: onClose })
  const needReason = e?.status === 'Approved' && !f.reason.trim()
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={e ? `Edit bar mark ${e.bar_mark}` : 'Add a bar mark'} description={e?.status === 'Approved' ? 'This entry is approved. Saving a change sends it back for approval.' : undefined}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!figures || needReason || save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Project" htmlFor="bb-job" className="sm:col-span-3"><ProjectPicker id="bb-job" value={project} onChange={setProject} /></Field>
        <Field label="Building / block" htmlFor="bb-block"><Input id="bb-block" value={f.block} onChange={set('block')} /></Field>
        <Field label="Floor" htmlFor="bb-floor"><Input id="bb-floor" value={f.floor} onChange={set('floor')} /></Field>
        <Field label="Structural element" htmlFor="bb-el"><Select id="bb-el" value={f.element} onChange={set('element')} options={data.elements.map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Member reference" htmlFor="bb-mem"><Input id="bb-mem" value={f.member_ref} onChange={set('member_ref')} /></Field>
        <Field label="Bar mark" htmlFor="bb-mark"><Input id="bb-mark" value={f.bar_mark} onChange={set('bar_mark')} /></Field>
        <Field label="Steel grade" htmlFor="bb-gr"><Select id="bb-gr" value={f.grade} onChange={set('grade')} options={data.grades.map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Bar diameter (mm)" htmlFor="bb-dia"><NumField id="bb-dia" value={n.diameter_mm} onValue={(v) => setN((x) => ({ ...x, diameter_mm: v }))} /></Field>
        <Field label="Number of bars" htmlFor="bb-num"><NumField id="bb-num" value={n.num_bars} onValue={(v) => setN((x) => ({ ...x, num_bars: v }))} /></Field>
        <Field label="Bar shape" htmlFor="bb-shape"><Select id="bb-shape" value={f.shape} onChange={set('shape')} options={data.shapes} /></Field>
        {shape?.dims.map((k) => <Field key={k} label={`Dimension ${k} (mm)`} htmlFor={`bb-d${k}`}><NumField id={`bb-d${k}`} value={dims[k] ?? 0} onValue={(v) => setDims((x) => ({ ...x, [k]: v }))} /></Field>)}
        {f.shape === 'Custom' && <Field label="Cutting length (mm)" htmlFor="bb-cut"><NumField id="bb-cut" value={n.cutting_length_mm} onValue={(v) => setN((x) => ({ ...x, cutting_length_mm: v }))} /></Field>}
        <Field label="Remarks" htmlFor="bb-rem" className="sm:col-span-3"><Input id="bb-rem" value={f.remarks} onChange={set('remarks')} /></Field>
        {e && <Field label="Reason for the change" htmlFor="bb-why" error={needReason ? 'Say why an approved entry is changing.' : undefined} className="sm:col-span-3"><Input id="bb-why" value={f.reason} onChange={set('reason')} /></Field>}
      </div>
      {figures && (
        <dl aria-label="Worked out" className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg border border-border bg-surface p-3 text-[13px] sm:grid-cols-4">
          <div><dt className="text-xs text-muted-foreground">Cutting length</dt><dd>{fix(figures.cutting_length_mm, 1)} mm</dd></div>
          <div><dt className="text-xs text-muted-foreground">Total length</dt><dd>{fix(figures.total_length_m, 3)} m</dd></div>
          <div><dt className="text-xs text-muted-foreground">Unit weight</dt><dd>{fix(figures.unit_weight_kg_m, 3)} kg/m</dd></div>
          <div><dt className="text-xs text-muted-foreground">Total weight</dt><dd className="font-semibold">{fix(figures.total_weight_kg, 3)} kg</dd></div>
        </dl>
      )}
      {(problem || save.error) && <p role="alert" className="mt-3 text-[13px] text-danger">{problem || save.error?.message}</p>}
    </Modal>
  )
}

function HistoryModal({ entry, onClose }: { entry: Entry; onClose: () => void }) {
  const q = useQuery({ queryKey: [...KEY, 'history', entry.id], queryFn: () => get<{ revisions: Revision[] }>(`/api/bbs/${entry.id}/revisions`) })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`History of ${entry.bar_mark}`} footer={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      <ul className="grid gap-2 text-[13px]">{q.data?.revisions.map((r) => <li key={r.revision} className="rounded-lg border border-border p-2.5"><strong>Revision {r.revision}</strong>: {r.entry.num_bars} bars, {r.entry.diameter_mm} mm, cut {fix(r.entry.cutting_length_mm, 0)} mm, {fix(r.entry.total_weight_kg)} kg<div className="text-xs text-muted-foreground">Replaced {r.at} by {r.by}{r.reason && `: ${r.reason}`}</div></li>)}</ul>
    </Modal>
  )
}

function RulesModal({ job, onClose }: { job: number; onClose: () => void }) {
  const q = useQuery({ queryKey: [...KEY, 'rules', job], queryFn: () => get<Record<string, number>>(`/api/bbs/rules?job_id=${job ?? 0}`) })
  const [v, setV] = useState<Record<string, string>>({})
  const value = (k: string) => v[k] ?? String(q.data?.[k] ?? '')
  const save = useAction(() => put<{ message: string }>('/api/bbs/rules', { job_id: job ?? 0, bend_45: Number(value('bend_45')), bend_90: Number(value('bend_90')), bend_135: Number(value('bend_135')), hook: Number(value('hook')) }), { invalidate: [KEY], success: (r) => r.message, onSuccess: onClose })
  const field = (k: string, label: string) => <Field label={label} htmlFor={`br-${k}`}><Input id={`br-${k}`} type="number" min="0" step="0.5" value={value(k)} onChange={(e) => setV((x) => ({ ...x, [k]: e.target.value }))} /></Field>
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Bend rules" description={`In multiples of the bar diameter, for ${job ? 'this project' : 'the whole company'}. Entries already saved keep their length.`} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">{field('bend_45', '45 degree bend deduction')}{field('bend_90', '90 degree bend deduction')}{field('bend_135', '135 degree bend deduction')}{field('hook', 'Hook allowance')}</div>
      {save.error && <p role="alert" className="mt-3 text-[13px] text-danger">{save.error.message}</p>}
    </Modal>
  )
}
