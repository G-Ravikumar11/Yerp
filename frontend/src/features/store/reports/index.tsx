import { useState } from 'react'
import { Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { FileSpreadsheet, FileText, Plus, Snowflake, Upload } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, Field, Input, Modal, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { cn, formatINR } from '@/lib/utils'
import { storePerm, useStoreMeta, type StoreItemOption } from '@/api/store'
import { StoreShell } from '../StoreShell'
import { ItemPicker, StorePicker } from '../shared'
import {
  blankFilters, importNorms, NORM_TEMPLATE, reconciliationPath, reportFile, reportKeys, retireNorm, saveNorm, useCatalogue, useClientSupply,
  useDashboard, useNorms, useReconciliation, useReport, useSubcontractors, useWorkItems, type ImportRow, type Norm, type Report, type ReportFilters,
} from './api'

const BASE = '/store/hub/reports'
type Part = 'dashboard' | 'run' | 'reconcile' | 'norms'
const PARTS: { value: Part; label: string; path: string; info: string }[] = [
  { value: 'dashboard', label: 'Dashboard', path: '', info: 'Stock value by store, what is waiting, what is low, and which stores are frozen.' },
  { value: 'run', label: 'Reports', path: '/run', info: 'Stock register, valuation, ledgers, registers, consumption, ageing, subcontractor account, transfers, counts and scrap - each to Excel or PDF.' },
  { value: 'reconcile', label: 'Reconciliation', path: '/reconcile', info: 'Material used against what the work done should have used, by project, work order or subcontractor; and client-supplied material.' },
  { value: 'norms', label: 'Norms', path: '/norms', info: 'How much of each material a unit of work should take, and the wastage allowed.' },
]

/** Store > Reports. Sub-pages live under /store/hub/reports/*. */
export default function ReportsIndex() {
  const { pathname } = useLocation()
  const nav = useNavigate()
  const part: Part = PARTS.find((p) => p.path && pathname.startsWith(BASE + p.path))?.value ?? 'dashboard'
  return (
    <StoreShell slice="reports">
      <div className="mb-5"><Tabs label="Reports" value={part} onChange={(v) => nav(BASE + (PARTS.find((p) => p.value === v)?.path ?? ''))} items={PARTS} /></div>
      <Routes>
        <Route index element={<DashboardView />} />
        <Route path="run" element={<RunView />} />
        <Route path="reconcile" element={<ReconcileView />} />
        <Route path="norms" element={<NormsView />} />
        <Route path="*" element={<p className="text-sm text-muted-foreground">There is no such page in Reports.</p>} />
      </Routes>
    </StoreShell>
  )
}

const money = (v: string | number | undefined | null) => formatINR(Number(v ?? 0))

function DashboardView() {
  const d = useDashboard().data
  const nav = useNavigate()
  const waiting = (v: number | null) => (v === null ? '-' : v)
  return (
    <div className="space-y-4">
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Stock value" value={money(d?.stock_value)} loading={!d} />
        <Stat label="Below reorder level" value={d?.below_reorder ?? 0} tone={d?.below_reorder ? 'warning' : undefined} loading={!d} onClick={() => nav(`${BASE}/run`)} />
        <Stat label="In transit" value={money(d?.in_transit.value)} sub={`${d?.in_transit.lines ?? 0} lines`} loading={!d} />
        <Stat label="Overdue returnables" value={d?.overdue_returnables ?? 0} tone={d?.overdue_returnables ? 'danger' : undefined} loading={!d} />
        <Stat label="Pending indents" value={waiting(d?.pending_indents ?? null)} sub={d && d.pending_indents === null ? 'once Outward publishes it' : undefined} loading={!d} />
        <Stat label="GRNs pending QC" value={waiting(d?.grns_pending_qc ?? null)} sub={d && d.grns_pending_qc === null ? 'once Inward publishes it' : undefined} loading={!d} />
        <Stat label="Frozen stores" value={d?.frozen_stores.length ?? 0} tone={d?.frozen_stores.length ? 'warning' : undefined} loading={!d} />
      </StatGrid>
      {!!d?.frozen_stores.length && (
        <Card className="p-4 text-sm"><h3 className="mb-1 font-semibold">Frozen</h3>{d.frozen_stores.map((f) => <div key={f.store_id}><Snowflake className="mr-1 inline size-3.5" /><span className="font-mono">{f.code}</span> {f.reason} <span className="text-muted-foreground">since {f.since.replace('T', ' ')}</span></div>)}</Card>
      )}
      <DataTable label="Stock by store" rows={d?.by_store ?? []} rowKey={(s) => s.store_id} loading={!d} empty="No stores yet."
        columns={[
          { id: 'code', header: 'Store', cell: (s) => <div><span className="font-mono font-semibold">{s.code}</span> {s.name}</div> },
          { id: 'items', header: 'Items held', align: 'right', cell: (s) => s.items },
          { id: 'value', header: 'Value', align: 'right', cell: (s) => <strong>{money(s.value)}</strong> },
        ]} />
    </div>
  )
}

const NEEDS = {
  consumption: ['group'], ageing: ['days'], 'subcontractor-account': ['subcontractor'], valuation: [] as string[],
} as Record<string, string[]>

function ReportTable({ out, loading }: { out?: Report; loading: boolean }) {
  const cols: TableColumn<Record<string, string | number | null>>[] = (out?.columns ?? []).map((c) => ({
    id: c.key, header: c.label, align: c.align === 'R' ? 'right' : c.align === 'C' ? 'center' : 'left',
    cell: (r) => (c.key === 'status' && r[c.key] ? <Badge tone={String(r[c.key]).includes('Non') || String(r[c.key]).includes('Over') || r[c.key] === 'Cancelled' ? 'warning' : 'neutral'}>{r[c.key]}</Badge> : String(r[c.key] ?? '')),
  }))
  return (
    <>
      <DataTable label={out?.title ?? 'Report'} rows={out?.rows ?? []} columns={cols} rowKey={(_r, i) => i} loading={loading} empty="Nothing in this report for these filters." />
      {out && (Object.keys(out.totals).length > 0 || out.notes.length > 0) && (
        <div className="mt-2 space-y-1 text-sm">
          {Object.keys(out.totals).length > 0 && <div className="flex flex-wrap justify-end gap-4">{Object.entries(out.totals).map(([k, v]) => <span key={k}>{k.replace(/_/g, ' ')}: <strong>{money(v)}</strong></span>)}</div>}
          {out.notes.map((n, i) => <p key={i} className="text-xs text-muted-foreground">{n}</p>)}
        </div>
      )}
    </>
  )
}

function RunView() {
  const cat = useCatalogue()
  const meta = useStoreMeta()
  const subs = useSubcontractors()
  const [code, setCode] = useState('stock-register')
  const [f, setF] = useState<ReportFilters>(blankFilters())
  const [item, setItem] = useState<StoreItemOption | null>(null)
  const q = useReport(code, f)
  const needs = NEEDS[code] ?? []
  return (
    <div className="space-y-3">
      <Card className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Report" htmlFor="r-code"><Select id="r-code" value={code} options={(cat.data?.reports ?? []).map((r) => ({ value: r.code, label: r.title }))} onChange={(e) => setCode(e.target.value)} /></Field>
        <Field label="Project" htmlFor="r-proj"><ProjectPicker id="r-proj" value={f.project_id} onChange={(project_id) => setF((x) => ({ ...x, project_id }))} allowAll className="w-full" /></Field>
        <Field label="Store" htmlFor="r-store"><StorePicker id="r-store" value={f.store_id || null} onChange={(id) => setF({ ...f, store_id: id ?? 0 })} placeholder="All my stores" /></Field>
        <Field label="Item" htmlFor="r-item"><ItemPicker id="r-item" value={item} onChange={(it) => { setItem(it); setF({ ...f, item_id: it?.id ?? 0 }) }} placeholder="Any item" /></Field>
        <Field label="Category" htmlFor="r-cat"><Select id="r-cat" value={f.category} options={[{ value: '', label: 'Every category' }, ...(meta.data?.item_categories ?? []).map((c) => ({ value: c, label: c[0] + c.slice(1).toLowerCase() }))]} onChange={(e) => setF({ ...f, category: e.target.value })} /></Field>
        <Field label={code === 'valuation' ? 'As on' : 'From / to'} htmlFor="r-to">
          <div className="flex gap-2">
            {code !== 'valuation' && <Input type="date" aria-label="From" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />}
            <Input id="r-to" type="date" aria-label="To" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
          </div>
        </Field>
        {needs.includes('group') && <Field label="By" htmlFor="r-group"><Select id="r-group" value={f.group} options={[{ value: 'work_order', label: 'Work order' }, { value: 'boq_item', label: 'BOQ item' }, { value: 'cost_head', label: 'Cost head' }, { value: 'subcontractor', label: 'Subcontractor' }]} onChange={(e) => setF({ ...f, group: e.target.value })} /></Field>}
        {needs.includes('days') && <Field label="No issue in" htmlFor="r-days"><Select id="r-days" value={String(f.days)} options={[90, 180, 365].map((d) => ({ value: String(d), label: `${d} days` }))} onChange={(e) => setF({ ...f, days: Number(e.target.value) })} /></Field>}
        {needs.includes('subcontractor') && <Field label="Subcontractor" htmlFor="r-sub"><Select id="r-sub" value={f.subcontractor_id || ''} options={[{ value: '', label: 'All' }, ...(subs.data ?? []).map((s) => ({ value: s.id, label: s.name }))]} onChange={(e) => setF({ ...f, subcontractor_id: Number(e.target.value) || 0 })} /></Field>}
        <div className="flex items-end gap-2">
          <Button variant="outline" asChild><a href={reportFile(code, f, 'xlsx')}><FileSpreadsheet /> Excel</a></Button>
          <Button variant="outline" asChild><a href={reportFile(code, f, 'pdf')} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        </div>
      </Card>
      <ReportTable out={q.data} loading={q.isPending} />
    </div>
  )
}

function ReconcileView() {
  const subs = useSubcontractors()
  const [scope, setScope] = useState<'project' | 'subcontractor' | 'client'>('project')
  const [projectId, setProjectId] = useState(0)
  const [subId, setSubId] = useState(0)
  const [category, setCategory] = useState('')
  const extra = `${category ? `&category=${category}` : ''}${scope === 'subcontractor' && projectId ? `&project_id=${projectId}` : ''}`
  const recon = useReconciliation(scope === 'subcontractor' ? 'subcontractor' : 'project', scope === 'subcontractor' ? subId : scope === 'project' ? projectId : 0, extra)
  const client = useClientSupply(scope === 'client' ? projectId : 0)
  const out = scope === 'client' ? client.data : recon.data
  const id = scope === 'subcontractor' ? subId : projectId
  return (
    <div className="space-y-3">
      <Tabs label="Reconcile" value={scope} onChange={setScope} items={[{ value: 'project', label: 'Project' }, { value: 'subcontractor', label: 'Subcontractor' }, { value: 'client', label: 'Client-supplied' }]} />
      <Card className="flex flex-wrap items-end gap-3 p-4">
        <Field label={scope === 'subcontractor' ? 'Project (optional)' : 'Project'} htmlFor="rc-proj"><ProjectPicker id="rc-proj" value={projectId} onChange={setProjectId} allowAll={scope === 'subcontractor'} className="w-64" /></Field>
        {scope === 'subcontractor' && <Field label="Subcontractor" htmlFor="rc-sub"><Select id="rc-sub" className="w-64" placeholder="Choose" value={subId || ''} options={(subs.data ?? []).map((s) => ({ value: s.id, label: s.name }))} onChange={(e) => setSubId(Number(e.target.value) || 0)} /></Field>}
        {scope !== 'client' && <Field label="Materials" htmlFor="rc-cat"><Select id="rc-cat" className="w-64" value={category} options={[{ value: '', label: 'Every material with a norm' }, { value: 'CONSUMABLE', label: 'Consumables' }]} onChange={(e) => setCategory(e.target.value)} /></Field>}
        {scope !== 'client' && id > 0 && <Button variant="outline" asChild><a href={reconciliationPath(scope === 'subcontractor' ? 'subcontractor' : 'project', id, extra, 'xlsx')}><FileSpreadsheet /> Excel</a></Button>}
        {scope !== 'client' && id > 0 && <Button variant="outline" asChild><a href={reconciliationPath(scope === 'subcontractor' ? 'subcontractor' : 'project', id, extra, 'pdf')} target="_blank" rel="noopener"><FileText /> PDF</a></Button>}
      </Card>
      {id > 0 ? <ReportTable out={out} loading={scope === 'client' ? client.isPending : recon.isPending} /> : <p className="text-sm text-muted-foreground">Choose {scope === 'subcontractor' ? 'a subcontractor' : 'a project'}.</p>}
    </div>
  )
}

function NormsView() {
  const { can } = useSession()
  const manage = can(storePerm('reports', 'create'))
  const [q, setQ] = useState('')
  const norms = useNorms(q)
  const [editing, setEditing] = useState<Norm | 'new' | null>(null)
  const [importing, setImporting] = useState(false)
  const retire = useAction((id: number) => retireNorm(id), { invalidate: [reportKeys.all], success: 'Norm retired.' })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-72"><Input aria-label="Search norms" placeholder="Work-item code" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        {manage && <div className="ml-auto flex gap-2"><Button variant="outline" onClick={() => setImporting(true)}><Upload /> Import a sheet</Button><Button onClick={() => setEditing('new')}><Plus /> New norm</Button></div>}
      </div>
      <DataTable label="Consumption norms" rows={norms.data ?? []} rowKey={(n) => n.id} loading={norms.isPending} onRowClick={(n) => manage && setEditing(n)} empty="No norms yet. A norm says how much of a material a unit of work should take."
        columns={[
          { id: 'code', header: 'Work item', cell: (n) => <div><span className="font-mono font-semibold">{n.work_item_code}</span>{(n.description || n.boq_item) && <div className="text-xs text-muted-foreground">{n.description || n.boq_item}</div>}</div> },
          { id: 'item', header: 'Material', cell: (n) => <div><span className="font-mono text-xs text-muted-foreground">{n.item_code}</span> {n.item_name}</div> },
          { id: 'coef', header: 'Per unit of work', align: 'right', cell: (n) => `${Number(n.coefficient)} ${n.base_uom} / ${n.work_uom || 'unit'}` },
          { id: 'w', header: 'Wastage', align: 'right', cell: (n) => `${Number(n.wastage_pct)}%` },
          { id: 'p', header: 'Penal rate', align: 'right', hideBelow: 'md', cell: (n) => (n.penal_rate ? `${formatINR(Number(n.penal_rate))} / ${n.base_uom}` : 'average cost') },
          { id: 'x', header: '', align: 'right', cell: (n) => manage && <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); retire.mutate(n.id) }}>Retire</Button> },
        ]} />
      {editing && <NormForm norm={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {importing && <NormImport onClose={() => setImporting(false)} />}
    </div>
  )
}

function NormForm({ norm, onClose }: { norm: Norm | null; onClose: () => void }) {
  const works = useWorkItems()
  const [f, setF] = useState({ work_item_code: norm?.work_item_code ?? '', boq_item_id: norm?.boq_item_id ?? null as number | null, description: norm?.description ?? '', work_uom: norm?.work_uom ?? '',
    coefficient: norm ? String(Number(norm.coefficient)) : '', wastage_pct: norm ? String(Number(norm.wastage_pct)) : '0', penal_rate: norm?.penal_rate ? String(Number(norm.penal_rate)) : '' })
  const [item, setItem] = useState<StoreItemOption | null>(norm ? { id: norm.item_id, code: norm.item_code, name: norm.item_name, base_uom: norm.base_uom, uoms: [], category: null } : null)
  const save = useAction(() => saveNorm(norm?.id ?? null, { ...f, item_id: item!.id, penal_rate: f.penal_rate || null, is_active: true }), { invalidate: [reportKeys.all], success: 'Norm saved.', onSuccess: onClose })
  const num = (k: 'coefficient' | 'wastage_pct' | 'penal_rate', label: string, hint?: string) => (
    <Field label={label} htmlFor={`nf-${k}`} hint={hint}><Input id={`nf-${k}`} inputMode="decimal" className="text-right" value={f[k]} onChange={(e) => /^\d*\.?\d{0,6}$/.test(e.target.value) && setF({ ...f, [k]: e.target.value })} /></Field>
  )
  return (
    <Modal open size="lg" onOpenChange={(o) => !o && onClose()} title={norm ? `Norm: ${norm.work_item_code}` : 'New consumption norm'} description="How much of the material one unit of the work should take, in the material's base unit."
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!f.work_item_code.trim() || !item || !Number(f.coefficient)} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Work item (BOQ item code)" htmlFor="nf-code">
          <Input id="nf-code" list="nf-codes" value={f.work_item_code} onChange={(e) => { const w = works.data?.find((x) => x.code === e.target.value); setF({ ...f, work_item_code: e.target.value, work_uom: w?.uom ?? f.work_uom, description: f.description || w?.description || '' }) }} />
          <datalist id="nf-codes">{(works.data ?? []).map((w) => <option key={w.boq_item_id} value={w.code}>{w.description}</option>)}</datalist>
        </Field>
        <Field label="Work measured in" htmlFor="nf-uom"><Input id="nf-uom" value={f.work_uom} placeholder="cum" onChange={(e) => setF({ ...f, work_uom: e.target.value })} /></Field>
        <Field label="Description" htmlFor="nf-desc" className="sm:col-span-2"><Input id="nf-desc" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Material" htmlFor="nf-item"><ItemPicker id="nf-item" value={item} onChange={setItem} /></Field>
        {num('coefficient', `${item?.base_uom || 'Base units'} per ${f.work_uom || 'unit of work'}`, 'e.g. 425 kg of cement a cum of M25')}
        {num('wastage_pct', 'Permissible wastage %')}
        {num('penal_rate', `Penal rate per ${item?.base_uom || 'unit'}`, 'For excess recovered from a subcontractor; blank = average cost')}
      </div>
    </Modal>
  )
}

function NormImport({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [rows, setRows] = useState<ImportRow[] | null>(null)
  const check = useAction(() => importNorms(file!, false), { success: false, onSuccess: (r) => setRows(r.rows) })
  const apply = useAction(() => importNorms(file!, true), { invalidate: [reportKeys.all], success: (r) => `${r.summary.ok} norms saved.`, onSuccess: onClose })
  const good = (rows ?? []).filter((r) => !r.errors.length).length
  return (
    <Modal open size="lg" onOpenChange={(o) => !o && onClose()} title="Import norms" description="Columns: work_item_code, item_code, coefficient, wastage_pct, penal_rate, work_uom, description. A norm already there for the same code and material is updated."
      footer={<><Button variant="outline" asChild><a href={NORM_TEMPLATE}><FileSpreadsheet /> Template</a></Button><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={apply.isPending} disabled={!rows || !good} onClick={() => apply.mutate()}>Save {good} norms</Button></>}>
      <div className="flex items-end gap-2">
        <Input type="file" accept=".csv,text/csv" aria-label="Sheet" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRows(null) }} />
        <Button disabled={!file} loading={check.isPending} onClick={() => check.mutate()}>Check</Button>
      </div>
      {rows && (
        <ul className="mt-3 max-h-72 space-y-1 overflow-auto text-sm">
          {rows.map((r) => <li key={r.row} className={cn(r.errors.length ? 'text-danger' : '')}>Row {r.row}: {r.work_item_code} / {r.item_code} x {r.coefficient} {r.errors.length ? `- ${r.errors.join(' ')}` : `(${r.action})`}</li>)}
        </ul>
      )}
    </Modal>
  )
}
