import { useState } from 'react'
import { FileSpreadsheet, Printer, Save } from 'lucide-react'
import { Badge, Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost, useStoreMeta } from '@/api/store'
import { StorePicker } from '../shared'
import { RaiseEnquiry } from './RaiseEnquiry'
import { dmy, money, num, qs, reportKeys, useReport, useSaved, type ReportData, type ReportKey, type Row, type Saved } from './api'

type Params = Record<string, string>
const C = (id: string, header: string, cell: (r: Row) => React.ReactNode, extra: Partial<TableColumn<Row>> = {}): TableColumn<Row> => ({ id, header, cell, ...extra })
const code = (r: Row) => <div><div className="font-medium">{String(r.item_name)}</div><div className="font-mono text-xs text-muted-foreground">{String(r.item_code)}</div></div>
const storeCol = C('store', 'Store', (r) => <span className="font-mono text-[13px]">{String(r.store_code)}</span>, { width: '5.5rem', sort: (r) => String(r.store_code) })
const nr = (id: string, header: string, key: string, fmt: (v: unknown) => string = num, extra: Partial<TableColumn<Row>> = {}) =>
  C(id, header, (r) => (r[key] == null || r[key] === '' ? '-' : fmt(r[key])), { align: 'right', width: '8rem', sort: (r) => Number(r[key] ?? 0), ...extra })
const level = { OVER: 'danger', UNDER: 'info', OK: 'success' } as const
const abcTone = { A: 'danger', B: 'warning', C: 'neutral' } as const
const pct = (v: unknown) => `${Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}%`

/** Which filters each report takes, and how its result is laid out. */
const CONFIG: Record<ReportKey, { filters: ('store' | 'project' | 'as_on' | 'range' | 'category' | 'q' | 'group' | 'tolerance' | 'days' | 'zero' | 'method')[]; need?: 'project'; columns: (d: ReportData) => TableColumn<Row>[]; key: (r: Row) => string | number; total?: (d: ReportData) => string | null }> = {
  valuation: {
    filters: ['store', 'as_on', 'method', 'category', 'q', 'zero'],
    columns: () => [storeCol, C('item', 'Item', code, { sort: (r) => String(r.item_name) }), C('cat', 'Category', (r) => String(r.category), { width: '8rem', hideBelow: 'md' }), nr('qty', 'Quantity', 'qty'),
      nr('rate', 'Avg rate', 'avg_rate', money, { hideBelow: 'sm', width: '7rem' }), nr('val', 'Value', 'value', money)],
    key: (r) => `${r.store_id}-${r.item_id}`,
    total: (d) => `Total value ${money(d.total_value)}${d.method === 'fifo' ? ' (FIFO)' : ''}`,
  },
  movement: {
    filters: ['store', 'range', 'q'],
    columns: (d) => [storeCol, C('item', 'Item', code), nr('oq', 'Opening qty', 'opening_qty', num, { hideBelow: 'md', width: '7rem' }), nr('ov', 'Opening value', 'opening_value', money, { width: '8rem' }),
      ...(d.buckets ?? []).map((b) => nr(b.key, b.label, `${b.key}_value`, money, { hideBelow: 'lg', width: '8rem' })), nr('cq', 'Closing qty', 'closing_qty', num, { width: '7rem' }), nr('cv', 'Closing value', 'closing_value', money, { width: '8rem' })],
    key: (r) => `${r.store_id}-${r.item_id}`,
    total: (d) => `Opening ${money(d.totals?.opening_value)} - closing ${money(d.totals?.closing_value)}`,
  },
  consumption: { filters: ['store', 'project', 'range', 'group'], columns: () => [], key: (r) => String(r.item_id), total: (d) => `Total consumed ${money(d.total_value)}` },
  'norm-variance': {
    filters: ['store', 'project', 'tolerance'],
    need: 'project',
    columns: () => [C('boq', 'BOQ item', (r) => String(r.boq_item)), C('item', 'Item', code), nr('should', 'Should use', 'theoretical_qty', num, { width: '8rem' }), nr('used', 'Used', 'actual_qty', num, { width: '7rem' }),
      nr('diff', 'Difference', 'variance_qty', num, { width: '8rem' }), nr('pct', '%', 'variance_pct', (v) => `${v}%`, { width: '5rem', hideBelow: 'sm' }),
      C('st', '', (r) => <Badge tone={level[r.status as keyof typeof level]} dot>{String(r.status)}</Badge>, { width: '6rem' })],
    key: (r) => `${r.boq_item_id}-${r.item_id}`,
    total: (d) => `${d.over ?? 0} item${d.over === 1 ? '' : 's'} over the norm`,
  },
  'slow-moving': {
    filters: ['store', 'days'],
    columns: () => [storeCol, C('item', 'Item', code), nr('qty', 'Quantity', 'qty'), nr('val', 'Tied up', 'value', money), C('last', 'Last moved', (r) => (r.last_moved ? dmy(r.last_moved) : 'never'), { width: '8rem', hideBelow: 'sm' }), nr('idle', 'Days idle', 'days_idle', num, { width: '7rem' })],
    key: (r) => `${r.store_id}-${r.item_id}`,
    total: (d) => `Tied up ${money(d.total_value)}`,
  },
  reorder: {
    filters: ['store'],
    columns: () => [storeCol, C('item', 'Item', code), nr('qty', 'On hand', 'qty'), nr('lvl', 'Reorder level', 'reorder_level', num, { hideBelow: 'sm' }), nr('min', 'Minimum', 'min_qty', num, { hideBelow: 'md' }),
      nr('order', 'Order about', 'suggested_qty', num), C('flag', '', (r) => (r.below_minimum ? <Badge tone="danger" dot>Below minimum</Badge> : null), { width: '9rem' })],
    key: (r) => `${r.store_id}-${r.item_id}`,
  },
  abc: {
    filters: ['store', 'range'],
    columns: () => [C('cls', 'Class', (r) => <Badge tone={abcTone[r.class as keyof typeof abcTone]}>{String(r.class)}</Badge>, { width: '5rem', sort: (r) => String(r.class) }), C('item', 'Item', code),
      nr('qty', 'Used', 'qty', num, { hideBelow: 'sm' }), nr('val', 'Value', 'value', money, { width: '9rem' }), nr('share', 'Share', 'share_pct', pct, { width: '6rem' }), nr('cum', 'Running', 'cumulative_pct', pct, { width: '6rem', hideBelow: 'sm' })],
    key: (r) => String(r.item_id),
    total: (d) => (d.classes ?? []).map((c) => `${c.class}: ${c.items} item${c.items === 1 ? '' : 's'}, ${c.share_pct}% of ${money(d.total_value)}`).join(' - ') || null,
  },
  ageing: {
    filters: ['store'],
    columns: (d) => [storeCol, C('item', 'Item', code), nr('qty', 'Quantity', 'qty', num, { hideBelow: 'md', width: '7rem' }), nr('val', 'Value', 'value', money, { width: '8rem' }),
      ...(d.buckets ?? []).map((b, i) => nr(b.key, b.label, `${b.key}_value`, money, { width: '8rem', hideBelow: i < 2 ? 'sm' : 'lg' })),
      C('oldest', 'Oldest lot', (r) => (r.oldest ? dmy(r.oldest) : '-'), { width: '8rem', hideBelow: 'md' })],
    key: (r) => `${r.store_id}-${r.item_id}`,
    total: (d) => `Total ${money(d.total_value)}` + ((d.buckets ?? []).length ? ' - ' + (d.buckets ?? []).map((b) => `${b.label} ${money(d.totals?.[`${b.key}_value`])}`).join(', ') : ''),
  },
  reconciliation: {
    filters: ['store', 'project', 'as_on'],
    need: 'project',
    columns: () => [C('item', 'Item', code), nr('rec', 'Received', 'received'), nr('tr', 'Transfers', 'transfers', num, { hideBelow: 'lg' }), nr('ret', 'Returned', 'returned', num, { hideBelow: 'lg' }),
      nr('iss', 'Issued', 'issued'), nr('was', 'Wasted', 'wasted', num, { hideBelow: 'md' }), nr('adj', 'Adjusted', 'adjusted', num, { hideBelow: 'lg' }), nr('bal', 'Balance', 'balance'),
      nr('else', 'Issued from other stores', 'issued_elsewhere', num, { hideBelow: 'md', width: '9rem' }), nr('req', 'BOQ needs', 'required'), nr('left', 'Still to issue', 'still_to_issue'),
      C('st', '', (r) => (r.status === 'OVER' ? <Badge tone="danger" dot>Over BOQ</Badge> : r.status === 'NO_NORM' ? <Badge tone="neutral">No norm</Badge> : <Badge tone="success" dot>Within</Badge>), { width: '7rem' })],
    key: (r) => String(r.item_id),
    total: (d) => `Site stores: ${(d.site_stores ?? []).map((s) => s.code).join(', ') || 'none'} - balance worth ${money(d.balance_value)} - ${d.over ?? 0} item${d.over === 1 ? '' : 's'} over the BOQ`,
  },
}

/** One report: its filters, the result as a table, Excel and PDF of the same figures, and saving the filters under a name. */
export default function ReportPage({ report }: { report: ReportKey }) {
  const cfg = CONFIG[report]
  const { can } = useSession()
  const meta = useStoreMeta()
  const projects = useProjects()
  const saved = useSaved()
  const [p, setP] = useState<Params>({})
  const [name, setName] = useState('')
  const set = (k: string, v: string) => setP((x) => ({ ...x, [k]: v }))
  const ready = !cfg.need || !!p.project_id
  const q = useReport(report, p, ready)
  const mine = (saved.data ?? []).filter((s) => s.report === report)
  const save = useAction(() => storePost<Saved>('reports', '/saved', { name, report, params: p }), { invalidate: [[...reportKeys.all, 'saved']], success: 'Report saved', onSuccess: () => setName('') })
  const drop = useAction((id: number) => storeDelete<{ message: string }>('reports', `/saved/${id}`), { invalidate: [[...reportKeys.all, 'saved']] })
  const has = (f: string) => (cfg.filters as string[]).includes(f)
  const data = q.data
  const rows: Row[] = report === 'consumption' ? (data?.groups ?? []).flatMap((g) => [{ _group: true, name: g.name, value: g.value, item_id: `g${g.key}` } as Row, ...g.items.map((i) => ({ ...i, name: '', item_id: `${g.key}-${i.item_id}` }))]) : (data?.rows ?? [])
  const columns: TableColumn<Row>[] = report === 'consumption'
    ? [C('name', 'Group / item', (r) => (r._group ? <span className="font-semibold">{String(r.name)}</span> : <span className="pl-4"><span className="font-mono text-xs text-muted-foreground">{String(r.item_code)}</span> {String(r.item_name)}</span>)),
       nr('qty', 'Quantity', 'qty', num, { width: '8rem' }), nr('val', 'Value', 'value', money, { width: '9rem' })]
    : cfg.columns(data ?? ({} as ReportData))
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {has('store') && <Field label="Store" htmlFor="rp-store" className="w-52"><StorePicker id="rp-store" value={Number(p.store_id) || null} placeholder="All my stores" onChange={(id) => set('store_id', id ? String(id) : '')} /></Field>}
        {has('project') && <Field label="Project" htmlFor="rp-proj" className="w-60"><Select id="rp-proj" value={p.project_id ?? ''} placeholder={cfg.need ? 'Choose a project' : 'All projects'} onChange={(e) => set('project_id', e.target.value)} options={(projects.data ?? []).map((x) => ({ value: x.id, label: projectLabel(x) }))} /></Field>}
        {has('method') && <Field label="Value at" htmlFor="rp-method" className="w-48"><Select id="rp-method" value={p.method ?? 'average'} onChange={(e) => set('method', e.target.value === 'average' ? '' : e.target.value)} options={[{ value: 'average', label: 'Weighted average (books)' }, { value: 'fifo', label: 'FIFO - first in, first out' }]} /></Field>}
        {has('as_on') && <Field label="As on" htmlFor="rp-ason" className="w-40"><Input id="rp-ason" type="date" value={p.as_on ?? ''} onChange={(e) => set('as_on', e.target.value)} /></Field>}
        {has('range') && <><Field label="From" htmlFor="rp-from" className="w-40"><Input id="rp-from" type="date" value={p.from_date ?? ''} onChange={(e) => set('from_date', e.target.value)} /></Field>
          <Field label="To" htmlFor="rp-to" className="w-40"><Input id="rp-to" type="date" min={p.from_date || undefined} value={p.to_date ?? ''} onChange={(e) => set('to_date', e.target.value)} /></Field></>}
        {has('category') && <Field label="Category" htmlFor="rp-cat" className="w-40"><Select id="rp-cat" value={p.category ?? ''} placeholder="Any" onChange={(e) => set('category', e.target.value)} options={(meta.data?.item_categories ?? []).map((c) => ({ value: c, label: c }))} /></Field>}
        {has('q') && <Field label="Search" htmlFor="rp-q" className="w-44"><Input id="rp-q" value={p.q ?? ''} onChange={(e) => set('q', e.target.value)} placeholder="Item" /></Field>}
        {has('group') && <Field label="Group by" htmlFor="rp-group" className="w-44"><Select id="rp-group" value={p.group_by ?? 'project'} onChange={(e) => set('group_by', e.target.value)} options={[{ value: 'project', label: 'Project' }, { value: 'cost_head', label: 'Cost head' }, { value: 'work_order', label: 'Work order' }, { value: 'boq_item', label: 'BOQ item' }, { value: 'item', label: 'Item' }]} /></Field>}
        {has('tolerance') && <Field label="Allow over by %" htmlFor="rp-tol" className="w-36"><Input id="rp-tol" inputMode="decimal" className="text-right" value={p.tolerance_pct ?? ''} onChange={(e) => set('tolerance_pct', e.target.value)} placeholder="0" /></Field>}
        {has('days') && <Field label="Idle for at least (days)" htmlFor="rp-days" className="w-44"><Input id="rp-days" inputMode="numeric" className="text-right" value={p.days ?? ''} onChange={(e) => set('days', e.target.value)} placeholder="90" /></Field>}
        {has('zero') && <label className="flex items-center gap-2 pb-2.5 text-sm"><input type="checkbox" checked={p.include_zero === 'true'} onChange={(e) => set('include_zero', e.target.checked ? 'true' : '')} /> Show nil stock</label>}
        <div className="ml-auto flex flex-wrap gap-2">
          {report === 'reorder' && can('purchase.manage') && <RaiseEnquiry rows={data?.rows ?? []} />}
          <Button variant="outline" disabled={!ready} asChild><a href={`/api/store/reports/${report}/export${qs(p)}`}><FileSpreadsheet /> Excel</a></Button>
          <Button variant="outline" disabled={!ready} asChild><a href={`/api/store/reports/${report}/print${qs(p)}`} target="_blank" rel="noreferrer"><Printer /> PDF</a></Button>
        </div>
      </div>
      {(mine.length > 0 || can(storePerm('reports', 'create'))) && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          {mine.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1">
              <button type="button" className="font-medium hover:underline" onClick={() => setP(s.params)}>{s.name}</button>
              {can(storePerm('reports', 'create')) && <button type="button" aria-label={`Remove saved report ${s.name}`} className="text-muted-foreground hover:text-danger" onClick={() => drop.mutate(s.id)}>x</button>}
            </span>
          ))}
          {can(storePerm('reports', 'create')) && (
            <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate() }}>
              <Input aria-label="Name to save this report under" className="h-9 w-44" placeholder="Save as..." value={name} onChange={(e) => setName(e.target.value)} />
              <Button type="submit" variant="outline" size="sm" loading={save.isPending} disabled={!name.trim()}><Save /> Save</Button>
            </form>
          )}
        </div>
      )}
      {!ready ? <p className="text-sm text-muted-foreground">{report === 'reconciliation' ? "Choose a project to see its site's material statement." : 'Choose a project to compare its norms with what was issued.'}</p> : q.isError ? <p role="alert" className="text-sm text-danger">Could not run the report.</p> : (
        <DataTable label={REPORT_LABEL[report]} rows={rows} loading={q.isPending} columns={columns} rowKey={(r) => (report === 'consumption' ? String(r.item_id) : cfg.key(r))} rowClassName={(r) => (r._group ? 'bg-muted/40' : undefined)} empty="Nothing to show for these filters."
          footer={data && cfg.total && cfg.total(data) ? <p className="px-3 py-2 text-right text-sm font-medium">{cfg.total(data)}</p> : undefined} />
      )}
      {data?.by_category && data.by_category.length > 0 && (
        <p className="mt-3 text-sm text-muted-foreground">{data.by_category.map((c) => `${c.category.toLowerCase()} ${money(c.value)}`).join(' - ')}</p>
      )}
    </div>
  )
}

const REPORT_LABEL: Record<ReportKey, string> = { valuation: 'Stock valuation', movement: 'Stock movement', consumption: 'Material consumption', 'norm-variance': 'Norms against use', 'slow-moving': 'Slow-moving stock', reorder: 'Reorder',
  abc: 'ABC analysis', ageing: 'Stock ageing', reconciliation: 'Site material reconciliation' }
