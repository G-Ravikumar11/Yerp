import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Card, Field, Input, Modal, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { useBankAccounts } from '@/api/money'
import { cn } from '@/lib/utils'

interface Summary {
  as_on: string; stock_value: string; by_category: { category: string; lines: number; value: string }[]
  not_billed: string; not_billed_orders: number; over_billed: string; over_billed_orders: number
  scrap_to_collect: string; scrap_sales_open: number; cross_charges_pending: string; cross_charges_open: number; price_variance: string
}
interface NotBilled { po_id: number; po_number: string; supplier_name: string; project: string; received_value: string; billed_value: string; difference: string; last_received: string; status: 'NOT_BILLED' | 'OVER_BILLED' }
interface Sale { scrap_id: number; number: string; date: string; store_code: string; buyer: string; reference: string; realised: string; received: string; outstanding: string; settled: boolean }
interface Charge { id: number; transfer_number: string; date: string; from_project: string; to_project: string; amount: string; status: 'PENDING' | 'ADJUSTED' | 'VOID' | 'REVERSE'; adjusted_on: string; adjusted_by: string; note: string }
interface Variance { grn_id: number; grn_number: string; supplier_name: string; po_number: string; linked_at: string; variance: string }

const KEY = ['store', 'accounts'] as const
const money = (v: string | undefined) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const dmy = (iso: string) => (iso ? new Date(iso.slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
const today = () => new Date().toLocaleDateString('en-CA')
type View = 'not-billed' | 'scrap' | 'cross' | 'variance'
const VIEWS: { key: View; label: string }[] = [{ key: 'not-billed', label: 'Received, not billed' }, { key: 'scrap', label: 'Scrap sales' }, { key: 'cross', label: 'Between projects' }, { key: 'variance', label: 'Price differences' }]
const pill = (on: boolean) => cn('whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium', on ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

/** What accounts take from the stores: stock value, what was received and not billed, scrap money to collect, and cost to charge across projects. */
export default function AccountsPage() {
  const [view, setView] = useState<View>('not-billed')
  const sum = useQuery({ queryKey: [...KEY, 'summary'], queryFn: () => get<Summary>('/api/store/accounts/summary') })
  const s = sum.data
  const tile = (label: string, value: string, hint?: string, tone?: string) => (
    <Card className="p-4"><div className="text-xs text-muted-foreground">{label}</div><div className={cn('mt-1 text-lg font-semibold', tone)}>{value}</div>{hint && <div className="text-xs text-muted-foreground">{hint}</div>}</Card>
  )
  return (
    <div>
      {sum.isError ? <p role="alert" className="mb-4 text-sm text-danger">Could not load the figures.</p> : (
        <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {tile('Stock held', s ? money(s.stock_value) : '-', s ? `as on ${dmy(s.as_on)}` : undefined)}
          {tile('Received, not billed', s ? money(s.not_billed) : '-', s ? `${s.not_billed_orders} order${s.not_billed_orders === 1 ? '' : 's'}` : undefined)}
          {tile('Scrap to collect', s ? money(s.scrap_to_collect) : '-', s ? `${s.scrap_sales_open} sale${s.scrap_sales_open === 1 ? '' : 's'}` : undefined)}
          {tile('To charge across projects', s ? money(s.cross_charges_pending) : '-', s ? `${s.cross_charges_open} open` : undefined)}
          {tile('Gate-delivery price difference', s ? money(s.price_variance) : '-', undefined, s && Number(s.price_variance) > 0 ? 'text-warning' : undefined)}
        </div>
      )}
      {s && s.by_category.length > 0 && <p className="mb-4 text-sm text-muted-foreground">Stock by category: {s.by_category.map((c) => `${c.category.toLowerCase()} ${money(c.value)}`).join(' - ')}.{Number(s.over_billed) > 0 && <span className="text-danger"> Suppliers have billed {money(s.over_billed)} more than was received on {s.over_billed_orders} order{s.over_billed_orders === 1 ? '' : 's'}.</span>}</p>}
      <div className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1" role="tablist">
        {VIEWS.map((v) => <button key={v.key} type="button" role="tab" aria-selected={view === v.key} className={pill(view === v.key)} onClick={() => setView(v.key)}>{v.label}</button>)}
      </div>
      {view === 'not-billed' ? <NotBilledList /> : view === 'scrap' ? <ScrapList /> : view === 'cross' ? <CrossList /> : <VarianceList />}
    </div>
  )
}

function NotBilledList() {
  const rows = useQuery({ queryKey: [...KEY, 'not-billed'], queryFn: () => get<{ items: NotBilled[] }>('/api/store/accounts/not-billed') })
  const columns: TableColumn<NotBilled>[] = [
    { id: 'po', header: 'Order', width: '11rem', cell: (r) => <span className="font-mono text-[13px] font-medium">{r.po_number}</span> },
    { id: 'sup', header: 'Supplier', cell: (r) => r.supplier_name || '-' },
    { id: 'proj', header: 'Project', hideBelow: 'md', cell: (r) => r.project || '-' },
    { id: 'rec', header: 'Received', align: 'right', width: '9rem', cell: (r) => money(r.received_value) },
    { id: 'bil', header: 'Billed', align: 'right', width: '9rem', cell: (r) => money(r.billed_value) },
    { id: 'diff', header: 'Difference', align: 'right', width: '10rem', sort: (r) => Number(r.difference), cell: (r) => <span className={r.status === 'OVER_BILLED' ? 'text-danger' : ''}>{money(r.difference)} <span className="text-xs text-muted-foreground">{r.status === 'OVER_BILLED' ? 'over-billed' : 'not billed'}</span></span> },
    { id: 'last', header: 'Last received', width: '9rem', hideBelow: 'lg', cell: (r) => dmy(r.last_received) },
  ]
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">What posted receipts took into stock against each order, compared with the supplier bills raised on it (drafts and rejected bills do not count). The old store's receipts are not included.</p>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the orders.</p> : <DataTable label="Received, not billed" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => r.po_id} empty="Every received order has been billed." />}
    </div>
  )
}

function ScrapList() {
  const { can } = useSession()
  const [receiving, setReceiving] = useState<Sale | null>(null)
  const rows = useQuery({ queryKey: [...KEY, 'scrap'], queryFn: () => get<{ items: Sale[] }>('/api/store/accounts/scrap') })
  const columns: TableColumn<Sale>[] = [
    { id: 'no', header: 'Scrap document', width: '14rem', cell: (r) => <span className="font-mono text-[13px] font-medium">{r.number}</span> },
    { id: 'date', header: 'Date', width: '9rem', cell: (r) => dmy(r.date) },
    { id: 'buyer', header: 'Buyer', cell: (r) => r.buyer || '-' },
    { id: 'real', header: 'Sold for', align: 'right', width: '9rem', cell: (r) => money(r.realised) },
    { id: 'got', header: 'Received', align: 'right', width: '9rem', hideBelow: 'sm', cell: (r) => money(r.received) },
    { id: 'out', header: 'To collect', align: 'right', width: '12rem', cell: (r) => r.settled ? <Badge tone="success" dot>Paid</Badge> : <span className="flex items-center justify-end gap-2">{money(r.outstanding)}{can(storePerm('reports')) && <Button size="sm" variant="outline" onClick={() => setReceiving(r)}>Receive</Button>}</span> },
  ]
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">Scrap sold and posted. Receiving the money records a sundry receipt (Scrap sale) in the bank book, charged to the project.</p>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the scrap sales.</p> : <DataTable label="Scrap sales" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => r.scrap_id} empty="No scrap has been sold." />}
      {receiving && <ReceiveModal sale={receiving} onClose={() => setReceiving(null)} />}
    </div>
  )
}

function ReceiveModal({ sale, onClose }: { sale: Sale; onClose: () => void }) {
  const accounts = useBankAccounts()
  const [f, setF] = useState({ amount: String(Number(sale.outstanding)), account_id: '', paid_on: today(), mode: 'Bank transfer', reference: '' })
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }))
  const save = useAction(() => post<{ message: string }>(`/api/store/accounts/scrap/${sale.scrap_id}/receive`, { ...f, account_id: f.account_id ? Number(f.account_id) : null }), { invalidate: [[...KEY]], onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Receive money for ${sale.number}`} description={`${sale.buyer || 'The buyer'} owes ${money(sale.outstanding)}.`}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4 sm:grid-cols-2">
        <Field label="Amount" htmlFor="rs-amt"><Input id="rs-amt" inputMode="decimal" className="text-right" value={f.amount} onChange={(e) => set('amount', e.target.value)} /></Field>
        <Field label="Date" htmlFor="rs-on"><Input id="rs-on" type="date" max={today()} value={f.paid_on} onChange={(e) => set('paid_on', e.target.value)} /></Field>
        <Field label="Into" htmlFor="rs-acc"><Select id="rs-acc" value={f.account_id} placeholder="No account" onChange={(e) => set('account_id', e.target.value)} options={(accounts.data ?? []).map((a) => ({ value: a.id, label: a.name }))} /></Field>
        <Field label="How" htmlFor="rs-mode"><Select id="rs-mode" value={f.mode} onChange={(e) => set('mode', e.target.value)} options={['Bank transfer', 'Cheque', 'Cash', 'UPI'].map((m) => ({ value: m, label: m }))} /></Field>
        <Field label="Reference" htmlFor="rs-ref" hint="UTR or cheque number." className="sm:col-span-2"><Input id="rs-ref" value={f.reference} onChange={(e) => set('reference', e.target.value)} maxLength={80} /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4 sm:col-span-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Record receipt</Button></div>
      </form>
    </Modal>
  )
}

function CrossList() {
  const { can } = useSession()
  const [adjusting, setAdjusting] = useState<Charge | null>(null)
  const rows = useQuery({ queryKey: [...KEY, 'cross'], queryFn: () => get<{ items: Charge[] }>('/api/store/accounts/cross-charges') })
  const columns: TableColumn<Charge>[] = [
    { id: 'no', header: 'Transfer', width: '14rem', cell: (r) => <span className="font-mono text-[13px] font-medium">{r.transfer_number}</span> },
    { id: 'date', header: 'Received', width: '9rem', hideBelow: 'sm', cell: (r) => dmy(r.date) },
    { id: 'from', header: 'From project', cell: (r) => r.from_project || '-' },
    { id: 'to', header: 'To project', cell: (r) => r.to_project || '-' },
    { id: 'amt', header: 'Amount', align: 'right', width: '9rem', cell: (r) => money(r.amount) },
    { id: 'st', header: 'Status', width: '13rem', cell: (r) => r.status === 'PENDING' || r.status === 'REVERSE'
      ? <span className="flex items-center gap-2"><Badge tone={r.status === 'REVERSE' ? 'danger' : 'warning'} dot>{r.status === 'REVERSE' ? 'Put back' : 'To charge'}</Badge>{can(storePerm('reports', 'create')) && <Button size="sm" variant="outline" onClick={() => setAdjusting(r)}>{r.status === 'REVERSE' ? 'Done' : 'Adjusted'}</Button>}</span>
      : <span className="text-muted-foreground">{r.status === 'ADJUSTED' ? `Adjusted ${dmy(r.adjusted_on)}` : 'Void'}</span> },
  ]
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">Stock moved between two projects' stores: the cost leaves one project and lands on the other, so accounts charge it across and mark it done. A transfer cancelled after that comes back as "put back".</p>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the transfers.</p> : <DataTable label="Between projects" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => r.id} empty="No stock has moved between projects." />}
      {adjusting && <AdjustModal charge={adjusting} onClose={() => setAdjusting(null)} />}
    </div>
  )
}

function AdjustModal({ charge, onClose }: { charge: Charge; onClose: () => void }) {
  const [note, setNote] = useState('')
  const save = useAction(() => post<{ status: string }>(`/api/store/accounts/cross-charges/${charge.id}/adjust`, { note }), { invalidate: [[...KEY]], success: charge.status === 'REVERSE' ? 'Marked as put back' : 'Marked as adjusted', onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`${charge.transfer_number}: ${money(charge.amount)}`} description={`${charge.from_project || 'One project'} to ${charge.to_project || 'another'}.`}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4">
        <Field label="Reference" htmlFor="aj-note" hint="The journal or voucher it was done under."><Input id="aj-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Save</Button></div>
      </form>
    </Modal>
  )
}

function VarianceList() {
  const rows = useQuery({ queryKey: [...KEY, 'variance'], queryFn: () => get<{ items: Variance[] }>('/api/store/accounts/price-variances') })
  const columns: TableColumn<Variance>[] = [
    { id: 'grn', header: 'Gate delivery', width: '14rem', cell: (r) => <span className="font-mono text-[13px] font-medium">{r.grn_number}</span> },
    { id: 'po', header: 'Linked to order', width: '11rem', cell: (r) => r.po_number },
    { id: 'sup', header: 'Supplier', hideBelow: 'sm', cell: (r) => r.supplier_name || '-' },
    { id: 'on', header: 'Linked', width: '9rem', hideBelow: 'md', cell: (r) => dmy(r.linked_at) },
    { id: 'var', header: 'Order rate vs rate at the gate', align: 'right', width: '14rem', sort: (r) => Number(r.variance), cell: (r) => <span className={Number(r.variance) > 0 ? 'text-warning' : ''}>{money(r.variance)}</span> },
  ]
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">A delivery taken in at a rate known at the gate is valued at that rate. When it is linked to its order, the difference from the order's rate is kept here; the stock keeps the value it came in at.</p>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the differences.</p> : <DataTable label="Price differences" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => r.grn_id} empty="No gate delivery has a price difference." />}
    </div>
  )
}
