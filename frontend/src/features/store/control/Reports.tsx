import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { StorePicker } from '../shared'
import { dmy, money, num, useInTransit, useRealisation, useVariances, type RealisationRow, type TransitRow, type VarianceRow } from './api'

/** Stock sent from one store and not yet received at the other, with what it is worth. */
export function InTransitPage() {
  const projects = useProjects()
  const [project, setProject] = useState(0)
  const q = useInTransit(project)
  const columns: TableColumn<TransitRow>[] = [
    { id: 'no', header: 'Transfer', width: '14rem', cell: (r) => <Link className="font-mono text-[13px] text-primary hover:underline" to={`/store/hub/control/transfer/${r.transfer_id}`}>{r.number}</Link> },
    { id: 'route', header: 'From to', width: '9rem', cell: (r) => <span className="font-mono text-[13px]">{r.from_store} to {r.to_store}</span> },
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'qty', header: 'Quantity', align: 'right', width: '7rem', cell: (r) => num(r.qty) },
    { id: 'val', header: 'Value', align: 'right', width: '8rem', sort: (r) => Number(r.value), cell: (r) => money(r.value) },
    { id: 'days', header: 'On the way', width: '9rem', sort: (r) => r.days, cell: (r) => <span>{r.days} day{r.days === 1 ? '' : 's'} {r.inter_project && <Badge className="ml-1">Inter-project</Badge>}</span> },
    { id: 'on', header: 'Sent', width: '8rem', hideBelow: 'md', cell: (r) => dmy(r.dispatched_on) },
  ]
  return (
    <div>
      <Field label="Project" htmlFor="it-proj" className="mb-4 w-64"><Select id="it-proj" value={project || ''} placeholder="All projects" onChange={(e) => setProject(Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
      {q.data && <p className="mb-3 text-sm text-muted-foreground" role="status">{q.data.total} line{q.data.total === 1 ? '' : 's'} on the way, worth <span className="font-semibold text-foreground">{money(q.data.total_value)}</span></p>}
      {q.isError ? <p role="alert" className="text-sm text-danger">Could not load the stock in transit.</p> : <DataTable label="Stock in transit" rows={q.data?.items ?? []} loading={q.isPending} columns={columns} rowKey={(r) => `${r.transfer_id}-${r.item_code}`} empty="Nothing is in transit." />}
    </div>
  )
}

/** What posted stock counts found against the books at a store. */
export function VariancesPage() {
  const [store, setStore] = useState(0)
  const [range, setRange] = useState({ from: '', to: '' })
  const q = useVariances(store, range.from, range.to)
  const columns: TableColumn<VarianceRow>[] = [
    { id: 'no', header: 'Count', width: '14rem', cell: (r) => <Link className="font-mono text-[13px] text-primary hover:underline" to={`/store/hub/control/count/${r.count_id}`}>{r.number}</Link> },
    { id: 'date', header: 'Date', width: '8rem', cell: (r) => dmy(r.count_date) },
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'sys', header: 'Books', align: 'right', width: '7rem', hideBelow: 'sm', cell: (r) => num(r.system_qty) },
    { id: 'cnt', header: 'Counted', align: 'right', width: '7rem', hideBelow: 'sm', cell: (r) => num(r.counted_qty) },
    { id: 'var', header: 'Difference', align: 'right', width: '8rem', cell: (r) => <span className={Number(r.variance_qty) < 0 ? 'text-danger' : 'text-success'}>{Number(r.variance_qty) > 0 ? '+' : ''}{num(r.variance_qty)}</span> },
    { id: 'val', header: 'Value', align: 'right', width: '8rem', cell: (r) => money(r.variance_value) },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="cv-store" className="w-56"><StorePicker id="cv-store" value={store || null} onChange={(id) => setStore(id ?? 0)} /></Field>
        <Field label="From" htmlFor="cv-from" className="w-40"><Input id="cv-from" type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></Field>
        <Field label="To" htmlFor="cv-to" className="w-40"><Input id="cv-to" type="date" min={range.from || undefined} value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></Field>
      </div>
      {!store ? <p className="text-sm text-muted-foreground">Choose a store to see what its counts found.</p> : q.isError ? <p role="alert" className="text-sm text-danger">Could not load the variances.</p> : (
        <DataTable label="Count variances" rows={q.data?.items ?? []} loading={q.isPending} columns={columns} rowKey={(r) => `${r.count_id}-${r.item_code}`} empty="No differences were found."
          footer={q.data ? <p className="px-3 py-2 text-right text-sm">Net difference: <b>{money(q.data.net_value)}</b></p> : undefined} />
      )}
    </div>
  )
}

/** Scrap sold or written off: what it was worth in the books against what it fetched. */
export function RealisationPage() {
  const projects = useProjects()
  const [project, setProject] = useState(0)
  const [range, setRange] = useState({ from: '', to: '' })
  const q = useRealisation(project, range.from, range.to)
  const columns: TableColumn<RealisationRow>[] = [
    { id: 'no', header: 'Document', width: '14rem', cell: (r) => <Link className="font-mono text-[13px] text-primary hover:underline" to={`/store/hub/control/scrap/${r.scrap_doc_id}`}>{r.number}</Link> },
    { id: 'date', header: 'Date', width: '8rem', cell: (r) => dmy(r.date) },
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'qty', header: 'Quantity', align: 'right', width: '7rem', hideBelow: 'sm', cell: (r) => num(r.qty) },
    { id: 'book', header: 'Book value', align: 'right', width: '8rem', cell: (r) => money(r.book_value) },
    { id: 'real', header: 'Fetched', align: 'right', width: '8rem', cell: (r) => money(r.realised_value) },
    { id: 'gain', header: 'Gain / loss', align: 'right', width: '8rem', cell: (r) => <span className={Number(r.gain) < 0 ? 'text-danger' : 'text-success'}>{money(r.gain)}</span> },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Project" htmlFor="sr-proj" className="w-64"><Select id="sr-proj" value={project || ''} placeholder="All projects" onChange={(e) => setProject(Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="From" htmlFor="sr-from" className="w-40"><Input id="sr-from" type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></Field>
        <Field label="To" htmlFor="sr-to" className="w-40"><Input id="sr-to" type="date" min={range.from || undefined} value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></Field>
      </div>
      {q.data && <p className="mb-3 text-sm text-muted-foreground" role="status">Book value {money(q.data.book_value)}, fetched <span className="font-semibold text-foreground">{money(q.data.realised_value)}</span></p>}
      {q.isError ? <p role="alert" className="text-sm text-danger">Could not load the scrap figures.</p> : <DataTable label="Scrap realisation" rows={q.data?.items ?? []} loading={q.isPending} columns={columns} rowKey={(r) => `${r.scrap_doc_id}-${r.item_code}`} empty="No scrap has been posted." />}
    </div>
  )
}
