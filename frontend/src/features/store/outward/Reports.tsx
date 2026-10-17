import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileSpreadsheet } from 'lucide-react'
import { Badge, Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { StorePicker } from '../shared'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { CloseReturnableModal } from './Closing'
import { dmy, money, num, qs, useRecovery, useReturnables, useSubcontractors, useWriteoffs, type Recovery, type Returnable, type Writeoff } from './api'

/** What is still out: returnable items and tools issued and not yet back, who holds them and how late they are. */
export function ReturnablesPage() {
  const projects = useProjects()
  const [f, setF] = useState({ project_id: 0, store_id: 0, overdue_only: false })
  const q = useReturnables(f)
  const { can } = useSession()
  const [closing, setClosing] = useState<{ row: Returnable; mode: 'convert' | 'writeoff' } | null>(null)
  const columns: TableColumn<Returnable>[] = [
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'qty', header: 'Out', align: 'right', width: '6rem', sort: (r) => Number(r.qty_outstanding), cell: (r) => num(r.qty_outstanding) },
    { id: 'who', header: 'Held by', cell: (r) => <span>{r.holder_name || '-'} <span className="text-xs text-muted-foreground">{r.holder_type.toLowerCase()}</span></span> },
    { id: 'iss', header: 'Issue', width: '14rem', hideBelow: 'md', cell: (r) => <Link className="font-mono text-[13px] text-primary hover:underline" to={`/store/hub/outward/issue/${r.issue_id}`}>{r.issue_number}</Link> },
    { id: 'due', header: 'Back by', width: '8rem', sort: (r) => r.expected_return_date, cell: (r) => (r.expected_return_date ? dmy(r.expected_return_date) : '-') },
    { id: 'late', header: '', width: '8rem', sort: (r) => r.overdue_days, cell: (r) => (r.overdue_days > 0 ? <Badge tone="danger" dot>{r.overdue_days} days late</Badge> : null) },
    { id: 'act', header: '', width: '13rem', cell: (r) => (
      <span className="flex justify-end gap-1">
        {can(storePerm('outward', 'approve')) && <Button size="sm" variant="outline" onClick={() => setClosing({ row: r, mode: 'convert' })}>Charge</Button>}
        {can(storePerm('outward', 'create')) && <Button size="sm" variant="outline" onClick={() => setClosing({ row: r, mode: 'writeoff' })}>Write off</Button>}
      </span>
    ) },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Project" htmlFor="rb-proj" className="w-60"><Select id="rb-proj" value={f.project_id || ''} placeholder="All projects" onChange={(e) => setF({ ...f, project_id: Number(e.target.value) || 0 })} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Store" htmlFor="rb-store" className="w-52"><StorePicker id="rb-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => setF({ ...f, store_id: id ?? 0 })} /></Field>
        <label className="flex items-center gap-2 pb-2.5 text-sm"><input type="checkbox" checked={f.overdue_only} onChange={(e) => setF({ ...f, overdue_only: e.target.checked })} /> Overdue only</label>
        <Button variant="outline" className="ml-auto" asChild><a href={`/api/store/outward/returnables/export${qs({ project_id: f.project_id, store_id: f.store_id })}`}><FileSpreadsheet /> Excel</a></Button>
      </div>
      {q.data && <p className="mb-3 text-sm text-muted-foreground" role="status">{q.data.total} line{q.data.total === 1 ? '' : 's'} still out{q.data.overdue > 0 && <> - <span className="text-danger">{q.data.overdue} overdue</span></>}</p>}
      {q.isError ? <p role="alert" className="text-sm text-danger">Could not load the returnables.</p> : <DataTable label="Returnables still out" rows={q.data?.items ?? []} loading={q.isPending} columns={columns} rowKey={(r) => r.issue_line_id} empty="Nothing returnable is out." />}
      {closing && <CloseReturnableModal row={closing.row} mode={closing.mode} onClose={() => setClosing(null)} />}
    </div>
  )
}

/** Returnables reported lost or damaged, waiting for the store to write them off or recover them. */
export function WriteoffsPage() {
  const [status, setStatus] = useState('OPEN')
  const q = useWriteoffs(status)
  const columns: TableColumn<Writeoff>[] = [
    { id: 'item', header: 'Item', cell: (w) => <div><div className="font-medium">{w.item_name}</div><div className="font-mono text-xs text-muted-foreground">{w.item_code}</div></div> },
    { id: 'qty', header: 'Quantity', align: 'right', width: '7rem', cell: (w) => num(w.qty) },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'sm', cell: (w) => <span className="font-mono text-[13px]">{w.store_code}</span> },
    { id: 'why', header: 'What happened', hideBelow: 'md', cell: (w) => w.reason },
    { id: 'on', header: 'Raised', width: '8rem', hideBelow: 'md', cell: (w) => dmy(w.created_at) },
    { id: 'st', header: 'Status', width: '10rem', cell: (w) => <Badge tone={w.status === 'OPEN' ? 'warning' : w.status === 'CLOSED' ? 'success' : 'neutral'} dot>{w.status === 'CLOSED' && w.closed_ref ? `Closed by ${w.closed_ref}` : w.status.charAt(0) + w.status.slice(1).toLowerCase()}</Badge> },
  ]
  return (
    <div>
      <Field label="Show" htmlFor="wo-status" className="mb-4 w-44"><Select id="wo-status" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: 'OPEN', label: 'Waiting' }, { value: 'CLOSED', label: 'Dealt with' }, { value: 'WITHDRAWN', label: 'Withdrawn' }, { value: '', label: 'All' }]} /></Field>
      {q.isError ? <p role="alert" className="text-sm text-danger">Could not load the write-off requests.</p> : <DataTable label="Write-off requests" rows={q.data ?? []} loading={q.isPending} columns={columns} rowKey={(w) => w.id} empty="No write-off requests." />}
    </div>
  )
}

type Row = Recovery['items'][number]

/** Material issued to one subcontractor, what came back and what is to be recovered from their next bill. */
export function RecoveryPage() {
  const subs = useSubcontractors()
  const [sub, setSub] = useState(0)
  const [upto, setUpto] = useState('')
  const q = useRecovery(sub, upto)
  const columns: TableColumn<Row>[] = [
    { id: 'date', header: 'Issued', width: '8rem', cell: (r) => dmy(r.issue_date) },
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'iss', header: 'Issued qty', align: 'right', width: '7rem', cell: (r) => num(r.qty_issued) },
    { id: 'ret', header: 'Returned', align: 'right', width: '7rem', cell: (r) => num(r.qty_returned) },
    { id: 'rate', header: 'Rate', align: 'right', width: '6rem', hideBelow: 'sm', cell: (r) => (r.chargeable ? money(r.recovery_rate) : '-') },
    { id: 'val', header: 'To recover', align: 'right', width: '8rem', cell: (r) => (r.chargeable ? money(r.recovery_value) : <span className="text-muted-foreground">Not charged</span>) },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Subcontractor" htmlFor="rc-sub" className="w-64"><Select id="rc-sub" value={sub || ''} placeholder="Choose a subcontractor" onChange={(e) => setSub(Number(e.target.value) || 0)} options={(subs.data ?? []).map((s) => ({ value: s.id, label: s.name }))} /></Field>
        <Field label="Up to" htmlFor="rc-upto" className="w-44"><Input id="rc-upto" type="date" value={upto} onChange={(e) => setUpto(e.target.value)} /></Field>
      </div>
      {!sub ? <p className="text-sm text-muted-foreground">Choose a subcontractor to see what is to be recovered from their bill.</p> : q.isError ? <p role="alert" className="text-sm text-danger">Could not load the statement.</p> : (
        <DataTable label="Subcontractor material" rows={q.data?.items ?? []} loading={q.isPending} columns={columns} rowKey={(r) => r.issue_line_id} empty="Nothing has been issued to this subcontractor."
          footer={q.data ? <p className="px-3 py-2 text-right text-sm">To recover: <b>{money(q.data.total_recovery)}</b></p> : undefined} />
      )}
    </div>
  )
}
