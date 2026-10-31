import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { AttachButton, StorePicker } from '../shared'
import { dmy, num, qs, today } from './api'

interface Rejection {
  id: number
  status: 'HELD' | 'RETURNED' | 'DISPOSED'
  store_code: string
  grn_id: number | null
  ncr_id: number | null
  ncr_number: string
  batch_no: string
  rejected_on: string
  rejected_by: string
  grn_number: string
  supplier_name: string
  grn_date: string
  item_code: string
  item_name: string
  qty: string
  reason: string
  resolved_on: string
  resolved_by: string
  vehicle_no: string
  note: string
  days_held: number
}

const KEY = ['store', 'rejections'] as const

/** Goods turned away at the gate, and lots rejected on an NCR: what is still lying there for the supplier to collect, and what became of the rest. */
export default function RejectedGoods() {
  const { can } = useSession()
  const [f, setF] = useState({ status: 'HELD', store_id: 0 })
  const [closing, setClosing] = useState<Rejection | null>(null)
  const rows = useQuery({ queryKey: [...KEY, f], queryFn: () => get<{ items: Rejection[] }>(`/api/store/rejections${qs({ status: f.status, store_id: f.store_id })}`) })
  const columns: TableColumn<Rejection>[] = [
    { id: 'grn', header: 'Source', width: '13rem', cell: (r) => r.grn_id
      ? <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/store/hub/inward/grn/${r.grn_id}`}>{r.grn_number}</Link>
      : <div><Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/projects/quality?ncr=${r.ncr_id}`}>{r.ncr_number}</Link><div className="text-xs text-muted-foreground">{dmy(r.rejected_on)}{r.rejected_by ? `, ${r.rejected_by}` : ''}</div></div> },
    { id: 'lot', header: 'Batch', width: '8rem', hideBelow: 'md', cell: (r) => <span className="font-mono text-[13px]">{r.batch_no || '-'}</span> },
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'qty', header: 'Quantity', align: 'right', width: '7rem', cell: (r) => num(r.qty) },
    { id: 'sup', header: 'Supplier', hideBelow: 'md', cell: (r) => r.supplier_name || '-' },
    { id: 'why', header: 'Why', hideBelow: 'lg', cell: (r) => r.reason || '-' },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'md', cell: (r) => <span className="font-mono text-[13px]">{r.store_code}</span> },
    {
      id: 'state', header: 'Status', width: '14rem',
      cell: (r) => r.status === 'HELD'
        ? <div className="flex items-center gap-2"><span className={r.days_held > 7 ? 'text-danger' : 'text-muted-foreground'}>Held {r.days_held} day{r.days_held === 1 ? '' : 's'}</span>
            {can(storePerm('inward', 'create')) && <Button size="sm" variant="outline" onClick={() => setClosing(r)}>Close</Button>}</div>
        : <span className="text-muted-foreground">{r.status === 'RETURNED' ? `Returned ${dmy(r.resolved_on)} (${r.vehicle_no})` : `Disposed ${dmy(r.resolved_on)}`}</span>,
    },
  ]
  return (
    <div>
      <p className="mb-4 text-sm text-muted-foreground">Goods turned away at receipt never enter stock, and a lot rejected on an NCR has left it. They are listed here until they go back to the supplier or are disposed of.</p>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="rj-store" className="w-52"><StorePicker id="rj-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => setF((x) => ({ ...x, store_id: id ?? 0 }))} /></Field>
        <Field label="Status" htmlFor="rj-status" className="w-40">
          <Select id="rj-status" value={f.status} placeholder="Any" onChange={(e) => setF((x) => ({ ...x, status: e.target.value }))}
            options={[{ value: 'HELD', label: 'Held' }, { value: 'RETURNED', label: 'Returned' }, { value: 'DISPOSED', label: 'Disposed' }]} />
        </Field>
      </div>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the rejected goods.</p> : (
        <DataTable label="Rejected goods" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => r.id} empty="No rejected goods." />
      )}
      {closing && <CloseModal row={closing} onClose={() => setClosing(null)} />}
    </div>
  )
}

function CloseModal({ row, onClose }: { row: Rejection; onClose: () => void }) {
  const [outcome, setOutcome] = useState<'RETURNED' | 'DISPOSED'>('RETURNED')
  const [vehicle, setVehicle] = useState('')
  const [note, setNote] = useState('')
  const [on, setOn] = useState(today())
  const save = useAction(() => post<Rejection>(`/api/store/rejections/${row.id}/resolve`, { outcome, vehicle_no: vehicle, note, on_date: on }), {
    invalidate: [[...KEY]],
    success: outcome === 'RETURNED' ? 'Marked as returned to the supplier' : 'Marked as disposed of',
    onSuccess: onClose,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`${row.item_name} - ${num(row.qty)} rejected`} description={`From ${row.grn_number || row.ncr_number}${row.supplier_name ? `, ${row.supplier_name}` : ''}.`}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4">
        <Field label="What happened" htmlFor="rj-out"><Select id="rj-out" value={outcome} onChange={(e) => setOutcome(e.target.value as 'RETURNED' | 'DISPOSED')} options={[{ value: 'RETURNED', label: 'Went back to the supplier' }, { value: 'DISPOSED', label: 'Disposed of here' }]} /></Field>
        {outcome === 'RETURNED' && <Field label="Vehicle number" htmlFor="rj-veh"><Input id="rj-veh" value={vehicle} onChange={(e) => setVehicle(e.target.value)} maxLength={30} /></Field>}
        <Field label="Note" htmlFor="rj-note" hint={outcome === 'DISPOSED' ? 'Required: say how it was disposed of.' : undefined}><Input id="rj-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></Field>
        <Field label="Date" htmlFor="rj-on"><Input id="rj-on" type="date" max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
          <span className="mr-auto"><AttachButton type="store_rejection" id={row.id} title={`${row.item_name} - ${row.grn_number || row.ncr_number}`} /></span>
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>Close</Button>
        </div>
      </form>
    </Modal>
  )
}
