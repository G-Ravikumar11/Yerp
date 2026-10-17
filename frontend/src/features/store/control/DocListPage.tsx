import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Plus } from 'lucide-react'
import { Badge, Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { storePerm, useStoreMeta } from '@/api/store'
import { DocStatusBadge, StorePicker } from '../shared'
import { dmy, money, qs, useDocs, type ControlKind, type Doc } from './api'

const EXTRA: Record<ControlKind, TableColumn<Doc>[]> = {
  transfer: [
    { id: 'to', header: 'To', width: '6rem', cell: (d) => <span className="font-mono text-[13px]">{d.to_store_code}</span> },
    { id: 'val', header: 'Value', align: 'right', width: '8rem', hideBelow: 'sm', sort: (d) => Number(d.value), cell: (d) => money(d.value) },
    { id: 'rec', header: 'Receipt', width: '9rem', hideBelow: 'md', cell: (d) => (d.receipt_status === 'IN_TRANSIT' ? <Badge tone="warning" dot>In transit</Badge> : d.receipt_status === 'RECEIVED' ? <Badge tone="success" dot>Received</Badge> : <span className="text-muted-foreground">-</span>) },
  ],
  count: [
    { id: 'type', header: 'Type', width: '7rem', hideBelow: 'sm', cell: (d) => <Badge>{d.count_type === 'PARTIAL' ? 'Partial' : 'Full'}</Badge> },
    { id: 'prog', header: 'Counted', align: 'right', width: '8rem', hideBelow: 'md', cell: (d) => (d.started ? `${d.counted} of ${d.line_count}` : 'Not started') },
    { id: 'frz', header: '', width: '7rem', cell: (d) => (d.frozen ? <Badge tone="warning" dot>Store frozen</Badge> : null) },
  ],
  scrap: [
    { id: 'proj', header: 'Project', hideBelow: 'sm', cell: (d) => d.project || '-' },
    { id: 'buyer', header: 'Buyer', hideBelow: 'md', cell: (d) => d.buyer || '-' },
    { id: 'real', header: 'Realised', align: 'right', width: '8rem', hideBelow: 'sm', cell: (d) => money(d.realised) },
  ],
}

/** One kind of control document, listed: filter by status, store and number, open one, or start a new one. */
export default function DocListPage({ kind, label, plural }: { kind: ControlKind; label: string; plural: string }) {
  const nav = useNavigate()
  const { can } = useSession()
  const meta = useStoreMeta()
  const [f, setF] = useState({ status: '', store_id: 0, q: '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const docs = useDocs(kind, f)
  const columns: TableColumn<Doc>[] = [
    { id: 'no', header: 'Number', width: '14rem', sort: (d) => d.number, cell: (d) => <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/store/hub/control/${kind}/${d.id}`}>{d.number}</Link> },
    { id: 'date', header: 'Date', width: '8rem', sort: (d) => d.date, cell: (d) => dmy(d.date) },
    { id: 'store', header: kind === 'transfer' ? 'From' : 'Store', width: '6rem', hideBelow: 'sm', cell: (d) => <span className="font-mono text-[13px]">{d.store_code}</span> },
    ...EXTRA[kind],
    { id: 'status', header: 'Status', width: '8rem', cell: (d) => <DocStatusBadge status={d.status} /> },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="cl-store" className="w-52"><StorePicker id="cl-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Status" htmlFor="cl-status" className="w-40">
          <Select id="cl-status" value={f.status} placeholder="Any" onChange={(e) => set('status', e.target.value)} options={(meta.data?.doc_statuses ?? []).map((s) => ({ value: s, label: s.charAt(0) + s.slice(1).toLowerCase() }))} />
        </Field>
        <Field label="Search" htmlFor="cl-q" className="w-44"><Input id="cl-q" value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="Number" /></Field>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" asChild><a href={`/api/store/control/${kind}/export${qs({ status: f.status, store_id: f.store_id, q: f.q })}`}><FileSpreadsheet /> Excel</a></Button>
          {can(storePerm('control', 'create')) && <Button onClick={() => nav(`/store/hub/control/${kind}/new`)}><Plus /> New {label.toLowerCase()}</Button>}
        </div>
      </div>
      {docs.isError ? <p role="alert" className="text-sm text-danger">Could not load the {plural.toLowerCase()}.</p> : (
        <DataTable label={plural} rows={docs.data?.items ?? []} loading={docs.isPending} columns={columns} rowKey={(d) => d.id} onRowClick={(d) => nav(`/store/hub/control/${kind}/${d.id}`)} empty={`No ${plural.toLowerCase()} yet.`} />
      )}
    </div>
  )
}
