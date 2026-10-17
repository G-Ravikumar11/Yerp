import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileSpreadsheet, FileText } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Button, Card, Input, Select, SkeletonRows } from '@/components/ui'
import { apiUrl } from '@/lib/api'
import { storeGet, useStoreMeta } from '@/api/store'
import { StorePicker } from '../shared'

interface Column { key: string; label: string; align: 'L' | 'R' | 'C'; kind: 'text' | 'qty' | 'money' }
interface Report { code: string; title: string; params: Record<string, string>; columns: Column[]; rows: Record<string, string>[]; totals: Record<string, string>; generated_at: string }
interface Options { projects: { id: number; name: string }[]; subcontractors: { id: number; name: string }[] }

const LABEL: Record<string, string> = { as_on: 'As on', from: 'From', to: 'To', store_id: 'Store', project_id: 'Project', subcontractor_id: 'Subcontractor', category: 'Category', days: 'Days without issue', group_by: 'Group by' }
const PARAMS: Record<string, string[]> = {
  'stock-valuation': ['as_on', 'store_id', 'category'], 'stock-movement': ['from', 'to', 'store_id'], reorder: ['store_id'], 'slow-moving': ['days', 'store_id'],
  consumption: ['project_id', 'from', 'to', 'group_by'], 'subcon-material': ['subcontractor_id', 'to'], returnables: ['project_id', 'store_id'], 'in-transit': ['project_id', 'store_id'],
  'count-variances': ['store_id', 'from', 'to'], scrap: ['project_id', 'from', 'to'], 'po-pending': ['project_id'],
}
const REQUIRED: Record<string, string[]> = { 'stock-movement': ['from', 'to'], consumption: ['project_id'], 'subcon-material': ['subcontractor_id'], 'count-variances': ['store_id'] }
const fmt = (c: Column, v: string | undefined) => {
  if (v === undefined || v === '') return ''
  if (c.kind === 'money') return Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (c.kind === 'qty' && v !== '' && !Number.isNaN(Number(v))) return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
  return v
}

/** Run one report: choose its parameters, see the table, take it away as Excel or PDF. */
export function ReportView() {
  const { code = '' } = useParams()
  const meta = useStoreMeta()
  const opts = useQuery({ queryKey: ['store', 'outward', 'options'], staleTime: 60_000, queryFn: () => storeGet<Options>('outward', '/options') })
  const keys = PARAMS[code] ?? []
  const [vals, setVals] = useState<Record<string, string>>({})
  const set = (k: string, v: string) => setVals((x) => ({ ...x, [k]: v }))
  const ready = (REQUIRED[code] ?? []).every((k) => !!vals[k])
  const query = useMemo(() => new URLSearchParams(Object.entries(vals).filter(([, v]) => v)).toString(), [vals])
  const res = useQuery({ queryKey: ['store', 'reports', 'run', code, query], enabled: ready, retry: false, queryFn: () => storeGet<Report>('reports', `/run/${code}?${query}`) })
  const rep = res.data
  const link = (format: string) => apiUrl(`/api/store/reports/run/${code}?${query}${query ? '&' : ''}format=${format}`)
  const input = (k: string) => {
    if (k === 'store_id') return <StorePicker value={vals[k] ? Number(vals[k]) : null} onChange={(id) => set(k, id ? String(id) : '')} placeholder="All my stores" />
    if (k === 'project_id') return <Select value={vals[k] ?? ''} placeholder={REQUIRED[code]?.includes(k) ? 'Choose a project' : 'All projects'} options={(opts.data?.projects ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => set(k, e.target.value)} />
    if (k === 'subcontractor_id') return <Select value={vals[k] ?? ''} placeholder="Choose" options={(opts.data?.subcontractors ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => set(k, e.target.value)} />
    if (k === 'category') return <Select value={vals[k] ?? ''} placeholder="All categories" options={(meta.data?.item_categories ?? []).map((c) => ({ value: c, label: c }))} onChange={(e) => set(k, e.target.value)} />
    if (k === 'group_by') return <Select value={vals[k] ?? ''} placeholder="Detail" options={[{ value: 'cost_head', label: 'Cost head' }, { value: 'work_order', label: 'Work order' }, { value: 'item', label: 'Item' }]} onChange={(e) => set(k, e.target.value)} />
    if (k === 'days') return <Input inputMode="numeric" placeholder="90" value={vals[k] ?? ''} onChange={(e) => set(k, e.target.value)} />
    return <Input type="date" value={vals[k] ?? ''} onChange={(e) => set(k, e.target.value)} />
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/store/hub/reports" className="text-sm text-primary hover:underline">All reports</Link>
        {rep && (
          <div className="flex gap-2">
            <a href={link('xlsx')}><Button variant="outline" size="sm"><FileSpreadsheet /> Excel</Button></a>
            <a href={link('pdf')} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><FileText /> PDF</Button></a>
          </div>
        )}
      </div>
      {keys.length > 0 && <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">{keys.map((k) => <label key={k} className="text-sm">{LABEL[k]}{REQUIRED[code]?.includes(k) && ' *'}{input(k)}</label>)}</Card>}
      {!ready && <p className="text-sm text-muted-foreground">Fill in the fields marked * to run this report.</p>}
      {res.isLoading && ready && <SkeletonRows rows={6} cols={5} />}
      {res.isError && <p className="text-sm text-danger">{(res.error as { detail?: string })?.detail ?? 'The report could not be run.'}</p>}
      {rep && (
        <Card className="overflow-x-auto">
          <div className="border-b border-border p-4"><h2 className="text-lg font-semibold">{rep.title}</h2><p className="text-xs text-muted-foreground">Run {rep.generated_at.replace('T', ' ')} · {rep.rows.length} rows</p></div>
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-xs uppercase text-muted-foreground">{rep.columns.map((c) => <th key={c.key} className={`p-3 ${c.align === 'R' ? 'text-right' : c.align === 'C' ? 'text-center' : 'text-left'}`}>{c.label}</th>)}</tr></thead>
            <tbody>
              {rep.rows.map((r, i) => <tr key={i} className="border-b border-border last:border-0">{rep.columns.map((c) => <td key={c.key} className={`p-3 ${c.align === 'R' ? 'text-right' : c.align === 'C' ? 'text-center' : ''}`}>{fmt(c, r[c.key])}</td>)}</tr>)}
              {rep.rows.length === 0 && <tr><td colSpan={rep.columns.length} className="p-6 text-center text-muted-foreground">Nothing to show for these choices.</td></tr>}
              {rep.rows.length > 0 && Object.keys(rep.totals).length > 0 && <tr className="border-t-2 border-border font-semibold">{rep.columns.map((c) => <td key={c.key} className={`p-3 ${c.align === 'R' ? 'text-right' : ''}`}>{fmt(c, rep.totals[c.key])}</td>)}</tr>}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
