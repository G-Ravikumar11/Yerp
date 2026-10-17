import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Plus } from 'lucide-react'
import { Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { storePerm, useStoreMeta } from '@/api/store'
import { DocStatusBadge, StorePicker } from '../shared'
import { dmy, money, qs, useDocs, type Doc, type InwardKind } from './api'

const DETAIL: Record<InwardKind, TableColumn<Doc>[]> = {
  grn: [
    { id: 'po', header: 'Purchase order', width: '9rem', hideBelow: 'md', cell: (d) => d.po_number || '-' },
    { id: 'sup', header: 'Supplier', hideBelow: 'sm', cell: (d) => d.supplier_name || '-' },
    { id: 'val', header: 'Value', align: 'right', width: '8rem', hideBelow: 'sm', sort: (d) => Number(d.value), cell: (d) => money(d.value) },
  ],
  returns: [
    { id: 'grn', header: 'Against receipt', width: '12rem', hideBelow: 'md', cell: (d) => d.grn_number || '-' },
    { id: 'sup', header: 'Supplier', hideBelow: 'sm', cell: (d) => d.supplier_name || '-' },
  ],
  'client-supply': [
    { id: 'proj', header: 'Project', hideBelow: 'sm', cell: (d) => d.project || '-' },
    { id: 'ref', header: 'Client ref', width: '9rem', hideBelow: 'md', cell: (d) => d.client_ref || '-' },
  ],
  opening: [{ id: 'val', header: 'Value', align: 'right', width: '8rem', hideBelow: 'sm', sort: (d) => Number(d.value), cell: (d) => money(d.value) }],
}

/** One kind of inward document, listed: filter by status, store and number, open one, or start a new one. */
export default function DocListPage({ kind, label, plural }: { kind: InwardKind; label: string; plural: string }) {
  const nav = useNavigate()
  const { can } = useSession()
  const meta = useStoreMeta()
  const [f, setF] = useState({ status: '', store_id: 0, q: '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const docs = useDocs(kind, f)
  const columns: TableColumn<Doc>[] = [
    { id: 'no', header: 'Number', width: '14rem', sort: (d) => d.number, cell: (d) => <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/store/hub/inward/${kind}/${d.id}`}>{d.number}</Link> },
    { id: 'date', header: 'Date', width: '8rem', sort: (d) => d.date, cell: (d) => dmy(d.date) },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'md', cell: (d) => <span className="font-mono text-[13px]">{d.store_code}</span> },
    ...DETAIL[kind],
    { id: 'lines', header: 'Lines', align: 'right', width: '4rem', hideBelow: 'lg', cell: (d) => d.line_count },
    { id: 'status', header: 'Status', width: '8rem', cell: (d) => <DocStatusBadge status={d.status} /> },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="il-store" className="w-52"><StorePicker id="il-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Status" htmlFor="il-status" className="w-40">
          <Select id="il-status" value={f.status} placeholder="Any" onChange={(e) => set('status', e.target.value)} options={(meta.data?.doc_statuses ?? []).map((s) => ({ value: s, label: s.charAt(0) + s.slice(1).toLowerCase() }))} />
        </Field>
        <Field label="Search" htmlFor="il-q" className="w-48"><Input id="il-q" value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="Number or supplier" /></Field>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" asChild><a href={`/api/store/inward/${kind}/export${qs({ status: f.status, store_id: f.store_id, q: f.q })}`}><FileSpreadsheet /> Excel</a></Button>
          {can(storePerm('inward', 'create')) && <Button onClick={() => nav(`/store/hub/inward/${kind}/new`)}><Plus /> New {label.toLowerCase()}</Button>}
        </div>
      </div>
      {docs.isError ? <p role="alert" className="text-sm text-danger">Could not load the {plural.toLowerCase()}.</p> : (
        <DataTable label={plural} rows={docs.data?.items ?? []} loading={docs.isPending} columns={columns} rowKey={(d) => d.id} onRowClick={(d) => nav(`/store/hub/inward/${kind}/${d.id}`)} empty={`No ${plural.toLowerCase()} yet.`} />
      )}
    </div>
  )
}
