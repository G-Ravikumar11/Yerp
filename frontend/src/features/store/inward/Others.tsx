import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { FileText, Plus, Truck } from 'lucide-react'
import { DataTable } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, Input, Modal, Select, Stat, StatGrid, Tabs, Textarea } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { storeKeys, storePerm, type StoreItemOption } from '@/api/store'
import { DocActionsBar, DocStatusBadge, ItemPicker, StorePicker, type DocAction } from '../shared'
import {
  cancelGate, inwardKeys, pdf, returnAction, saveClientRate, saveGate, saveInwardSettings, useClientRates, useGates, useInwardSettings,
  usePending, useReturn, useReturns, useWorkOrders, type Gate,
} from './api'
import { BASE } from './Grns'

const refresh = { invalidate: [inwardKeys.all, storeKeys.all] }
const money = (v: string | number | undefined) => formatINR(Number(v ?? 0))
const n = (v: string | null | undefined) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const GATE_TONE = { OPEN: 'info', GRN_MADE: 'success', CANCELLED: 'danger' } as const

/** Inward > Gate register: every vehicle that came in with material. */
export function GateRegister() {
  const { can } = useSession()
  const nav = useNavigate()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const list = useGates(storeId ?? 0)
  const cancel = useAction((id: number) => cancelGate(id), { ...refresh, success: 'Gate entry cancelled.' })
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-56"><StorePicker value={storeId} onChange={(id) => setStoreId(id)} placeholder="All my stores" /></div>
        {can(storePerm('inward', 'create')) && <Button className="ml-auto" onClick={() => setAdding(true)}><Truck /> Vehicle in</Button>}
      </div>
      <DataTable
        label="Gate register"
        rows={list.data ?? []}
        rowKey={(g) => g.id}
        loading={list.isPending}
        empty="No vehicles recorded yet."
        columns={[
          { id: 'no', header: 'Entry', cell: (g) => <div><span className="font-mono font-semibold">{g.number}</span><div className="text-xs text-muted-foreground">{formatDate(g.entry_date)} {g.time_in}</div></div> },
          { id: 'veh', header: 'Vehicle', cell: (g) => <div className="font-mono">{g.vehicle_no || '-'}</div> },
          { id: 'from', header: 'From', cell: (g) => <div>{g.vendor_name || '-'}<div className="text-xs text-muted-foreground">{g.po_number ?? ''} {g.challan_no && `DC ${g.challan_no}`}</div></div> },
          { id: 'wb', header: 'Weighbridge', align: 'right', hideBelow: 'md', cell: (g) => (g.net_weight ? <div>{n(g.net_weight)} kg<div className="text-xs text-muted-foreground">{g.weighbridge_slip_no} · {n(g.gross_weight)} - {n(g.tare_weight)}</div></div> : '-') },
          { id: 'st', header: 'Status', cell: (g) => <div><Badge tone={GATE_TONE[g.status]}>{g.status === 'GRN_MADE' ? 'GRN made' : g.status.toLowerCase()}</Badge>{g.grns.map((x) => <div key={x.id} className="font-mono text-xs">{x.number}</div>)}</div> },
          {
            id: 'act',
            header: '',
            align: 'right',
            cell: (g) =>
              g.status === 'OPEN' && (
                <div className="flex justify-end gap-1.5">
                  {can(storePerm('inward', 'create')) && <Button size="sm" onClick={() => nav(`${BASE}/grn/new?gate=${g.id}`)}>Make GRN</Button>}
                  {can(storePerm('inward', 'cancel')) && <Button size="sm" variant="outline" onClick={() => cancel.mutate(g.id)}>Cancel</Button>}
                </div>
              ),
          },
        ]}
      />
      {adding && <GateForm onClose={() => setAdding(false)} />}
    </div>
  )
}

/** Now as HH:MM, for the time a vehicle came in. */
function clock() {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

function GateForm({ onClose }: { onClose: () => void }) {
  const [storeId, setStoreId] = useState<number | null>(null)
  const [f, setF] = useState(() => ({ entry_date: today(), time_in: clock(), vehicle_no: '', vendor_name: '', challan_no: '', challan_date: '', weighbridge_slip_no: '', gross_weight: '', tare_weight: '', remarks: '' }))
  const net = Number(f.gross_weight) && Number(f.tare_weight) ? Number(f.gross_weight) - Number(f.tare_weight) : null
  const save = useAction((): Promise<Gate> => saveGate(null, { ...f, store_id: storeId, challan_date: f.challan_date || null, gross_weight: f.gross_weight || null, tare_weight: f.tare_weight || null }), {
    ...refresh, success: (g) => `${g.number} recorded.`, onSuccess: onClose,
  })
  const t = (k: keyof typeof f, label: string, extra: Record<string, unknown> = {}) => (
    <Field label={label} htmlFor={`gt-${k}`}><Input id={`gt-${k}`} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} {...extra} /></Field>
  )
  return (
    <Modal open size="lg" onOpenChange={(o) => !o && onClose()} title="Vehicle in" description="The inward register: a GRN can be made from it once the material is counted."
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!storeId} onClick={() => save.mutate()}>Record</Button></>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Store" htmlFor="gt-store" className="sm:col-span-2"><StorePicker id="gt-store" value={storeId} onChange={(id) => setStoreId(id)} /></Field>
        {t('time_in', 'Time in', { type: 'time' })}
        {t('entry_date', 'Date', { type: 'date', max: today() })}
        {t('vehicle_no', 'Vehicle no')}
        {t('vendor_name', 'Vendor')}
        {t('challan_no', 'Delivery challan no')}
        {t('challan_date', 'Challan date', { type: 'date' })}
        {t('weighbridge_slip_no', 'Weighbridge slip')}
        {t('gross_weight', 'Gross kg', { inputMode: 'decimal', className: 'text-right' })}
        {t('tare_weight', 'Tare kg', { inputMode: 'decimal', className: 'text-right' })}
        <div className="pb-2 text-sm sm:self-end">Net <strong>{net !== null ? `${n(String(net))} kg` : '-'}</strong></div>
        <Field label="Remarks" htmlFor="gt-rem" className="sm:col-span-3"><Textarea id="gt-rem" rows={2} value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

/** Inward > Returns: material sent back to suppliers. */
export function ReturnList() {
  const nav = useNavigate()
  const list = useReturns()
  return (
    <DataTable
      label="Purchase returns"
      rows={list.data ?? []}
      rowKey={(r) => r.id}
      loading={list.isPending}
      onRowClick={(r) => nav(`${BASE}/returns/${r.id}`)}
      empty="Nothing returned. A return is raised from a posted GRN."
      columns={[
        { id: 'no', header: 'Number', cell: (r) => <span className="font-mono font-semibold">{r.number}</span> },
        { id: 'grn', header: 'Against', cell: (r) => <div><span className="font-mono text-xs">{r.grn_number}</span><div className="text-xs text-muted-foreground">{r.vendor}</div></div> },
        { id: 'date', header: 'Date', hideBelow: 'md', cell: (r) => formatDate(r.return_date) },
        { id: 'total', header: 'Debit note', align: 'right', cell: (r) => <strong>{money(r.total)}</strong> },
        { id: 'st', header: 'Status', cell: (r) => <DocStatusBadge status={r.status} /> },
      ]}
    />
  )
}

export function ReturnView() {
  const { id } = useParams()
  const { can } = useSession()
  const q = useReturn(Number(id))
  const [busy, setBusy] = useState<DocAction | null>(null)
  const step = useAction((v: { action: DocAction; reason?: string }) => returnAction(Number(id), v.action, v.reason), { ...refresh, success: (r) => `${r.number} is ${r.status.toLowerCase()}.` })
  const r = q.data
  if (!r?.debit_note) return <p className="text-sm text-muted-foreground">{q.isError ? 'This return cannot be opened.' : 'Loading...'}</p>
  const d = r.debit_note
  const act = async (action: DocAction, reason?: string) => {
    setBusy(action)
    try {
      await step.mutateAsync({ action, reason })
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><h2 className="font-mono text-lg font-semibold">{r.number}</h2><DocStatusBadge status={r.status} /></div>
          <p className="mt-1 text-sm text-muted-foreground">Against {d.grn_number}{d.po_number && ` · ${d.po_number}`}{d.invoice_no && ` · invoice ${d.invoice_no}`} · {d.vendor}{d.vendor_gstin && ` (${d.vendor_gstin})`} · {formatDate(r.return_date)}</p>
          <p className="text-sm">{r.reason}</p>
          {r.cancel_reason && <p className="text-sm text-danger">Cancelled: {r.cancel_reason}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild><a href={pdf.ret(r.id)} target="_blank" rel="noopener"><FileText /> Return / debit note</a></Button>
          <DocActionsBar status={r.status} busy={busy} onAction={act}
            can={{ submit: can(storePerm('inward', 'create')), approve: can(storePerm('inward', 'approve')), post: can(storePerm('inward', 'post')), cancel: can(storePerm('inward', 'cancel')) }} />
        </div>
      </div>
      <DataTable
        label="Debit note"
        rows={d.lines}
        rowKey={(l) => `${l.item_code}-${l.source}`}
        footer={<div className="flex justify-end gap-6 px-4 py-3 text-sm"><span>Taxable {money(d.taxable_value)}</span><span>GST {money(d.gst)}</span><strong>Total {money(d.total)}</strong></div>}
        columns={[
          { id: 'item', header: 'Item', cell: (l) => <div><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}<div><Badge>{l.source === 'REJECTED' ? 'rejected - debit only' : 'from stock'}</Badge></div></div> },
          { id: 'qty', header: 'Quantity', align: 'right', cell: (l) => <div>{n(l.qty)} {l.uom}{l.uom !== l.base_uom && <div className="text-xs text-muted-foreground">{n(l.qty_base)} {l.base_uom}</div>}</div> },
          { id: 'rate', header: 'Rate', align: 'right', cell: (l) => `${formatINR(Number(l.rate))} / ${l.base_uom}` },
          { id: 'tax', header: 'Taxable', align: 'right', cell: (l) => money(l.taxable_value) },
          { id: 'gst', header: 'GST', align: 'right', cell: (l) => `${money(l.gst)} (${Number(l.gst_pct)}%)` },
          { id: 'tot', header: 'Total', align: 'right', cell: (l) => <strong>{money(l.total)}</strong> },
        ]}
      />
    </div>
  )
}

/** Inward > Pending: what approved orders still have to deliver. */
export function PendingView() {
  const [group, setGroup] = useState<'po' | 'vendor'>('po')
  const q = usePending(group)
  const total = (q.data ?? []).reduce((s, g) => s + Number(g.pending_value), 0)
  const nav = useNavigate()
  return (
    <div className="space-y-3">
      <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
        <Stat label="Still to come" value={money(total)} loading={q.isPending} />
        <Stat label={group === 'po' ? 'Orders' : 'Vendors'} value={(q.data ?? []).length} loading={q.isPending} />
        <Stat label="Lines" value={(q.data ?? []).reduce((s, g) => s + g.lines, 0)} loading={q.isPending} />
      </StatGrid>
      <Tabs label="Group by" value={group} onChange={setGroup} items={[{ value: 'po', label: 'By order' }, { value: 'vendor', label: 'By vendor' }]} />
      {(q.data ?? []).map((g) => (
        <Card key={`${g.po_id}-${g.vendor}`} className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
            <div><span className="font-semibold">{group === 'po' ? g.po_number : g.vendor || '-'}</span> <span className="text-sm text-muted-foreground">{group === 'po' ? g.vendor : g.orders.join(', ')}</span></div>
            <div className="flex items-center gap-3"><strong>{money(g.pending_value)}</strong>{group === 'po' && <Button size="sm" variant="outline" onClick={() => nav(`${BASE}/grn/new`)}><Plus /> Receive</Button>}</div>
          </div>
          <DataTable
            label="Pending lines"
            className="rounded-none border-0 shadow-none"
            rows={g.items}
            rowKey={(l) => `${l.po_number}-${l.item_code}`}
            columns={[
              ...(group === 'vendor' ? [{ id: 'po', header: 'Order', cell: (l: (typeof g.items)[number]) => <span className="font-mono text-xs">{l.po_number}</span> }] : []),
              { id: 'item', header: 'Item', cell: (l) => <div><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</div> },
              { id: 'ord', header: 'Ordered', align: 'right', cell: (l) => `${n(l.ordered_qty)} ${l.po_uom}` },
              { id: 'pend', header: 'Pending', align: 'right', cell: (l) => <strong>{n(l.pending_qty)} {l.po_uom}</strong> },
              { id: 'hand', header: 'On GRNs not posted', align: 'right', hideBelow: 'md', cell: (l) => (Number(l.in_hand_base) ? `${n(l.in_hand_base)} ${l.base_uom}` : '-') },
              { id: 'val', header: 'Value', align: 'right', cell: (l) => money(l.pending_value) },
            ]}
          />
        </Card>
      ))}
      {!q.isPending && !(q.data ?? []).length && <p className="text-sm text-muted-foreground">Every approved order has been received in full.</p>}
    </div>
  )
}

/** Inward > Client rates and settings. */
export function RatesAndSettings() {
  const { can } = useSession()
  const manage = can(storePerm('inward', 'approve'))
  const [storeId, setStoreId] = useState<number | null>(null)
  const [woId, setWoId] = useState(0)
  const [item, setItem] = useState<StoreItemOption | null>(null)
  const [rate, setRate] = useState('')
  const [reference, setReference] = useState('')
  const wos = useWorkOrders(storeId ?? 0)
  const rates = useClientRates()
  const settings = useInwardSettings()
  const add = useAction(() => saveClientRate({ work_order_id: woId, item_id: item!.id, rate, reference }), { ...refresh, success: 'Rate saved.', onSuccess: () => { setItem(null); setRate(''); setReference('') } })
  const gst = useAction((v: boolean) => saveInwardSettings(v), { ...refresh, success: 'Saved.' })
  return (
    <div className="space-y-6">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div><h3 className="text-sm font-semibold">Input GST on receipts</h3><p className="text-xs text-muted-foreground">Recoverable GST is claimed back and kept out of stock value; if it cannot be claimed it is part of what the material cost. A GRN can override this.</p></div>
        <Select aria-label="Input GST" className="w-72" disabled={!manage || settings.isPending} value={settings.data?.gst_recoverable === false ? 'no' : 'yes'} options={[{ value: 'yes', label: 'Recoverable (not in stock value)' }, { value: 'no', label: 'Not recoverable (in stock value)' }]} onChange={(e) => gst.mutate(e.target.value === 'yes')} />
      </Card>
      <section>
        <h3 className="mb-1 text-sm font-semibold">Client-supplied material rates</h3>
        <p className="mb-3 text-xs text-muted-foreground">The rate the client work order fixes for material the client supplies and recovers, per base unit. Client-supply receipts are valued at it.</p>
        {manage && (
          <Card className="mb-3 grid gap-3 p-4 sm:grid-cols-[12rem_10rem_1fr_8rem_1fr_auto] sm:items-end">
            <Field label="Store" htmlFor="cr-store"><StorePicker id="cr-store" value={storeId} onChange={(id) => { setStoreId(id); setWoId(0) }} /></Field>
            <Field label="Work order" htmlFor="cr-wo"><Select id="cr-wo" placeholder="Choose" disabled={!storeId} value={woId || ''} options={(wos.data ?? []).map((w) => ({ value: w.id, label: w.number }))} onChange={(e) => setWoId(Number(e.target.value) || 0)} /></Field>
            <Field label="Item" htmlFor="cr-item"><ItemPicker id="cr-item" value={item} onChange={setItem} /></Field>
            <Field label={`Rate / ${item?.base_uom || 'unit'}`} htmlFor="cr-rate"><Input id="cr-rate" inputMode="decimal" className="text-right" value={rate} onChange={(e) => /^\d*\.?\d{0,4}$/.test(e.target.value) && setRate(e.target.value)} /></Field>
            <Field label="Contract reference" htmlFor="cr-ref"><Input id="cr-ref" value={reference} placeholder="Clause 14.2" onChange={(e) => setReference(e.target.value)} /></Field>
            <Button loading={add.isPending} disabled={!woId || !item || !rate} onClick={() => add.mutate()}>Save</Button>
          </Card>
        )}
        <DataTable
          label="Client rates"
          rows={rates.data ?? []}
          rowKey={(r) => r.id}
          loading={rates.isPending}
          empty="No agreed rates yet."
          columns={[
            { id: 'wo', header: 'Work order', cell: (r) => <span className="font-mono">{r.work_order}</span> },
            { id: 'item', header: 'Item', cell: (r) => <div><span className="font-mono text-xs text-muted-foreground">{r.item_code}</span> {r.item_name}</div> },
            { id: 'rate', header: 'Rate', align: 'right', cell: (r) => `${formatINR(Number(r.rate))} / ${r.base_uom}` },
            { id: 'ref', header: 'Reference', hideBelow: 'md', cell: (r) => r.reference || '-' },
          ]}
        />
      </section>
    </div>
  )
}
