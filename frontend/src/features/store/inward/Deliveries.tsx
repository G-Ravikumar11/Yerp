import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Field, Input, Modal } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { dmy, money, num } from './api'

interface PendingLine { po_line_id: number; item_code: string; item_name: string; base_uom: string; ordered: string; accepted: string; pending: string }
interface PendingPo { po_id: number; number: string; supplier_name: string; project: string; issue_date: string; needed_by: string; days_late: number; lines: PendingLine[] }
interface Closed { po_id: number; number: string; supplier_name: string; reason: string; closed_by: string; closed_at: string }
interface Card { supplier_name: string; orders: number; ordered_value: string; accepted_value: string; rejected_value: string; fill_pct: string; rejection_pct: string; on_time_pct: string }

const KEY = ['store', 'deliveries'] as const
/** Short-closing an order is purchasing's decision, not the store's. */
const CLOSE_RIGHT = 'purchase.manage'
type View = 'pending' | 'closed' | 'suppliers'
const VIEWS: { key: View; label: string }[] = [{ key: 'pending', label: 'Still to come' }, { key: 'closed', label: 'Short-closed' }, { key: 'suppliers', label: 'Supplier scorecard' }]
const pill = (on: boolean) => cn('whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium', on ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

/** What suppliers still owe on approved orders, orders given up on, and how each supplier has delivered. */
export default function Deliveries() {
  const [view, setView] = useState<View>('pending')
  return (
    <div>
      <p className="mb-4 text-sm text-muted-foreground">Approved orders with goods still to come, orders closed short, and how each supplier has delivered against what was ordered.</p>
      <div className="mb-4 flex w-fit gap-1 rounded-xl bg-muted p-1" role="tablist">
        {VIEWS.map((v) => <button key={v.key} type="button" role="tab" aria-selected={view === v.key} className={pill(view === v.key)} onClick={() => setView(v.key)}>{v.label}</button>)}
      </div>
      {view === 'pending' ? <Pending /> : view === 'closed' ? <ClosedOrders /> : <Scorecard />}
    </div>
  )
}

function Pending() {
  const { can } = useSession()
  const [supplier, setSupplier] = useState('')
  const [closing, setClosing] = useState<PendingPo | null>(null)
  const rows = useQuery({ queryKey: [...KEY, 'pending', supplier], queryFn: () => get<{ items: PendingPo[] }>(`/api/store/deliveries/pending${supplier.trim() ? `?supplier=${encodeURIComponent(supplier.trim())}` : ''}`) })
  const columns: TableColumn<PendingPo>[] = [
    { id: 'po', header: 'Order', width: '11rem', cell: (p) => <span className="font-mono text-[13px] font-medium">{p.number}</span> },
    { id: 'sup', header: 'Supplier', cell: (p) => p.supplier_name || '-' },
    { id: 'proj', header: 'Project', hideBelow: 'md', cell: (p) => p.project || '-' },
    { id: 'due', header: 'Needed by', width: '10rem', cell: (p) => (p.needed_by ? <span className={p.days_late ? 'text-danger' : ''}>{dmy(p.needed_by)}{p.days_late ? ` - ${p.days_late} day${p.days_late === 1 ? '' : 's'} late` : ''}</span> : '-') },
    { id: 'what', header: 'Still to come', hideBelow: 'sm', cell: (p) => <ul className="text-sm">{p.lines.map((l) => <li key={l.po_line_id}>{l.item_name}: {num(l.pending)} {l.base_uom} <span className="text-muted-foreground">of {num(l.ordered)}</span></li>)}</ul> },
    { id: 'act', header: '', width: '8rem', cell: (p) => can(CLOSE_RIGHT) ? <Button size="sm" variant="outline" onClick={() => setClosing(p)}>Short-close</Button> : null },
  ]
  return (
    <div>
      <Field label="Supplier" htmlFor="dl-sup" className="mb-4 w-56"><Input id="dl-sup" value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Part of the name" /></Field>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the pending deliveries.</p> : (
        <DataTable label="Pending deliveries" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(p) => p.po_id} empty="Nothing is waiting to be delivered." />
      )}
      {closing && <CloseModal po={closing} onClose={() => setClosing(null)} />}
    </div>
  )
}

function CloseModal({ po, onClose }: { po: PendingPo; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const save = useAction(() => post<{ message: string }>(`/api/store/deliveries/${po.po_id}/short-close`, { reason }), { invalidate: [[...KEY], ['store', 'inward']], onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Short-close ${po.number}`} description="Nothing more will be received against this order. What has already been received stays. It can be reopened later.">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4">
        <Field label="Why" htmlFor="sc-why" hint="Required."><Input id="sc-why" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>Short-close</Button>
        </div>
      </form>
    </Modal>
  )
}

function ClosedOrders() {
  const { can } = useSession()
  const rows = useQuery({ queryKey: [...KEY, 'closed'], queryFn: () => get<{ items: Closed[] }>('/api/store/deliveries/short-closed') })
  const reopen = useAction((id: number) => post<{ message: string }>(`/api/store/deliveries/${id}/reopen`), { invalidate: [[...KEY], ['store', 'inward']] })
  const columns: TableColumn<Closed>[] = [
    { id: 'po', header: 'Order', width: '11rem', cell: (c) => <span className="font-mono text-[13px] font-medium">{c.number}</span> },
    { id: 'sup', header: 'Supplier', cell: (c) => c.supplier_name || '-' },
    { id: 'why', header: 'Why', hideBelow: 'sm', cell: (c) => c.reason },
    { id: 'by', header: 'Closed by', width: '10rem', hideBelow: 'md', cell: (c) => c.closed_by || '-' },
    { id: 'act', header: '', width: '7rem', cell: (c) => can(CLOSE_RIGHT) ? <Button size="sm" variant="outline" loading={reopen.isPending && reopen.variables === c.po_id} onClick={() => reopen.mutate(c.po_id)}>Reopen</Button> : null },
  ]
  return rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the short-closed orders.</p> : (
    <DataTable label="Short-closed orders" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(c) => c.po_id} empty="No order has been short-closed." />
  )
}

function Scorecard() {
  const rows = useQuery({ queryKey: [...KEY, 'suppliers'], queryFn: () => get<{ items: Card[] }>('/api/store/deliveries/suppliers') })
  const columns: TableColumn<Card>[] = [
    { id: 'sup', header: 'Supplier', sort: (c) => c.supplier_name, cell: (c) => <span className="font-medium">{c.supplier_name}</span> },
    { id: 'n', header: 'Orders', align: 'right', width: '6rem', cell: (c) => c.orders },
    { id: 'ord', header: 'Ordered', align: 'right', width: '9rem', hideBelow: 'md', cell: (c) => money(c.ordered_value) },
    { id: 'acc', header: 'Delivered', align: 'right', width: '9rem', hideBelow: 'md', cell: (c) => money(c.accepted_value) },
    { id: 'fill', header: 'Delivered %', align: 'right', width: '7rem', sort: (c) => Number(c.fill_pct), cell: (c) => `${c.fill_pct}%` },
    { id: 'rej', header: 'Rejected %', align: 'right', width: '7rem', sort: (c) => Number(c.rejection_pct), cell: (c) => <span className={Number(c.rejection_pct) > 5 ? 'text-danger' : ''}>{c.rejection_pct}%</span> },
    { id: 'time', header: 'On time', align: 'right', width: '7rem', cell: (c) => (c.on_time_pct ? `${c.on_time_pct}%` : '-') },
  ]
  return rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the supplier scorecard.</p> : (
    <DataTable label="Supplier scorecard" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(c) => c.supplier_name} empty="No supplier has delivered yet." />
  )
}
