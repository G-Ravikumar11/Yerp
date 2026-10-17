import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Plus, Zap } from 'lucide-react'
import { Badge, Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { storePerm, useStoreMeta } from '@/api/store'
import { DocStatusBadge, StorePicker } from '../shared'
import { dmy, qs, useDocs, type Doc, type OutwardKind } from './api'

/** One kind of outward document, listed: filter by status, store and number, open one, or start a new one. */
export default function DocListPage({ kind, label, plural }: { kind: OutwardKind; label: string; plural: string }) {
  const nav = useNavigate()
  const { can } = useSession()
  const meta = useStoreMeta()
  const [f, setF] = useState({ status: '', store_id: 0, q: '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const docs = useDocs(kind, f)
  const columns: TableColumn<Doc>[] = [
    { id: 'no', header: 'Number', width: '14rem', sort: (d) => d.number, cell: (d) => <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/store/hub/outward/${kind}/${d.id}`}>{d.number}</Link> },
    { id: 'date', header: 'Date', width: '8rem', sort: (d) => d.date, cell: (d) => dmy(d.date) },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'md', cell: (d) => <span className="font-mono text-[13px]">{d.store_code}</span> },
    ...(kind === 'issue'
      ? ([
          { id: 'proj', header: 'Project', hideBelow: 'sm', cell: (d) => d.project || '-' },
          { id: 'to', header: 'Received by', hideBelow: 'md', cell: (d) => d.received_by_name || d.holder_name || '-' },
          { id: 'type', header: 'Type', width: '9rem', hideBelow: 'lg', cell: (d) => <span className="flex gap-1"><Badge>{d.issue_type === 'SUBCONTRACTOR' ? 'Subcontractor' : 'Site'}</Badge>{d.indent_number ? <Badge tone="info">{d.indent_number.split('/').pop()}</Badge> : d.direct && <Badge tone="warning">Direct</Badge>}</span> },
        ] as TableColumn<Doc>[])
      : ([{ id: 'iss', header: 'Against issue', width: '13rem', hideBelow: 'sm', cell: (d) => d.issue_number || '-' }, { id: 'to', header: 'Held by', hideBelow: 'md', cell: (d) => d.holder_name || '-' }] as TableColumn<Doc>[])),
    { id: 'lines', header: 'Lines', align: 'right', width: '4rem', hideBelow: 'lg', cell: (d) => d.line_count },
    { id: 'status', header: 'Status', width: '8rem', cell: (d) => <DocStatusBadge status={d.status} /> },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="ol-store" className="w-52"><StorePicker id="ol-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Status" htmlFor="ol-status" className="w-40">
          <Select id="ol-status" value={f.status} placeholder="Any" onChange={(e) => set('status', e.target.value)} options={(meta.data?.doc_statuses ?? []).map((s) => ({ value: s, label: s.charAt(0) + s.slice(1).toLowerCase() }))} />
        </Field>
        <Field label="Search" htmlFor="ol-q" className="w-48"><Input id="ol-q" value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="Number or holder" /></Field>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" asChild><a href={`/api/store/outward/${kind}/export${qs({ status: f.status, store_id: f.store_id, q: f.q })}`}><FileSpreadsheet /> Excel</a></Button>
          {kind === 'issue' && can('store.outward.direct_issue') && <Button variant="outline" onClick={() => nav('/store/hub/outward/issue/new?direct=1')}><Zap /> Direct issue</Button>}
          {can(storePerm('outward', 'create')) && <Button onClick={() => nav(`/store/hub/outward/${kind}/new`)}><Plus /> New {label.toLowerCase()}</Button>}
        </div>
      </div>
      {docs.isError ? <p role="alert" className="text-sm text-danger">Could not load the {plural.toLowerCase()}.</p> : (
        <DataTable label={plural} rows={docs.data?.items ?? []} loading={docs.isPending} columns={columns} rowKey={(d) => d.id} onRowClick={(d) => nav(`/store/hub/outward/${kind}/${d.id}`)} empty={`No ${plural.toLowerCase()} yet.`} />
      )}
    </div>
  )
}
