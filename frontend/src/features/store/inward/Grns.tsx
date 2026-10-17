import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { FileText, Plus, Trash2, Undo2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { storeKeys, storePerm, useItemUoms, type StoreItemOption } from '@/api/store'
import { DocActionsBar, DocStatusBadge, ItemPicker, StorePicker, type DocAction } from '../shared'
import {
  createGrn, createReturn, grnAction, inwardKeys, KIND_LABEL, pdf, recordQc, useGate, useGrn, useGrns, usePoLines, usePos, useWorkOrders,
  type Grn, type GrnKind, type GrnLine, type GrnLineInput, type PoLine,
} from './api'

export const BASE = '/store/hub/inward'
const refresh = { invalidate: [inwardKeys.all, storeKeys.all] }
const money = (v: string | number | undefined) => formatINR(Number(v ?? 0))
const n = (v: string | null | undefined) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const qtyOk = (v: string) => /^\d*\.?\d{0,3}$/.test(v)
const sub = (a: string, b: string) => {
  const r = Number(a || 0) - Number(b || 0)
  return r > 0 ? String(Math.round(r * 1000) / 1000) : '0'
}
export const grnPath = (g: { id: number; kind: GrnKind }) => `${BASE}/${g.kind === 'CLIENT_SUPPLY' ? 'client-supply' : 'grn'}/${g.id}`

/** Inward > GRNs: every receipt, newest first. */
export function GrnList() {
  const { can } = useSession()
  const nav = useNavigate()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
  const list = useGrns(storeId ?? 0, status, kind)
  const cols: TableColumn<Grn>[] = [
    { id: 'no', header: 'Number', sort: (g) => g.number, cell: (g) => <div><span className="font-mono font-semibold">{g.number}</span><div className="text-xs text-muted-foreground">{KIND_LABEL[g.kind]}</div></div> },
    { id: 'date', header: 'Date', sort: (g) => g.grn_date, cell: (g) => formatDate(g.grn_date), hideBelow: 'md' },
    { id: 'from', header: 'From', cell: (g) => <div>{g.vendor_name || '-'}<div className="text-xs text-muted-foreground">{g.po_number || g.work_order || ''}</div></div> },
    { id: 'store', header: 'Store', cell: (g) => g.store_code, hideBelow: 'lg' },
    { id: 'value', header: 'Stock value', align: 'right', sort: (g) => Number(g.stock_value), cell: (g) => <strong>{money(g.stock_value)}</strong> },
    {
      id: 'st',
      header: 'Status',
      cell: (g) => (
        <div className="flex flex-wrap gap-1">
          <DocStatusBadge status={g.status} />
          {g.qc_pending > 0 && g.status !== 'CANCELLED' && <Badge tone="warning">QC {g.qc_pending}</Badge>}
        </div>
      ),
    },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-56"><StorePicker value={storeId} onChange={(id) => setStoreId(id)} placeholder="All my stores" /></div>
        <div className="w-40"><Select aria-label="Kind" value={kind} options={[{ value: '', label: 'Every kind' }, ...(Object.keys(KIND_LABEL) as GrnKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))]} onChange={(e) => setKind(e.target.value)} /></div>
        <div className="w-40"><Select aria-label="Status" value={status} options={[{ value: '', label: 'Any status' }, ...['DRAFT', 'SUBMITTED', 'APPROVED', 'POSTED', 'CANCELLED'].map((x) => ({ value: x, label: x[0] + x.slice(1).toLowerCase() }))]} onChange={(e) => setStatus(e.target.value)} /></div>
        {can(storePerm('inward', 'create')) && <Button className="ml-auto" asChild><Link to={`${BASE}/grn/new`}><Plus /> New GRN</Link></Button>}
      </div>
      <DataTable label="GRNs" rows={list.data ?? []} columns={cols} rowKey={(g) => g.id} loading={list.isPending} onRowClick={(g) => nav(grnPath(g))} empty="Nothing received yet." />
    </div>
  )
}

/** One unit picker for an item, shared by the quantities of a line. */
function UomSelect({ itemId, value, onChange }: { itemId: number | null; value: string; onChange: (u: string) => void }) {
  const q = useItemUoms(itemId)
  const uoms = q.data?.uoms ?? []
  return <Select aria-label="Unit" value={value} disabled={!itemId || uoms.length < 2} options={(uoms.length ? uoms.map((u) => u.code) : [value]).filter(Boolean).map((u) => ({ value: u, label: u }))} onChange={(e) => onChange(e.target.value)} />
}

interface Row {
  key: number; po?: PoLine; item: StoreItemOption | null; uom: string; received: string; rejected: string; shortage: string; rate: string; gst: string
  batch: string; mtc: string; steel: boolean; nos: string; bundles: string; dia: string; length: string; weight: string; remarks: string
}
let rowKey = 0
const blankRow = (po?: PoLine): Row => ({
  key: ++rowKey, po, item: po?.item_id ? { id: po.item_id, code: po.item_code, name: po.item_name, base_uom: po.base_uom, uoms: [], category: null } : null,
  uom: po?.po_uom || '', received: '', rejected: '', shortage: '', rate: '', gst: '', batch: '', mtc: '', steel: false, nos: '', bundles: '', dia: '', length: '12', weight: '', remarks: '',
})

/** A new GRN: against an order, direct (no PO), or client-supplied material. Opened from a gate entry it starts filled in. */
export function GrnForm() {
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const gateId = Number(sp.get('gate')) || 0
  const gate = useGate(gateId)
  const [kind, setKind] = useState<GrnKind>((sp.get('kind') as GrnKind) || 'PO')
  const [storeId, setStoreId] = useState<number | null>(null)
  const [poId, setPoId] = useState(0)
  const [woId, setWoId] = useState(0)
  const [head, setHead] = useState({ grn_date: today(), vendor_name: '', challan_no: '', challan_date: '', invoice_no: '', invoice_date: '', freight: '', loading: '', other_charges: '', reason: '', remarks: '' })
  const [gst, setGst] = useState<'' | 'yes' | 'no'>('')
  const [rows, setRows] = useState<Row[]>(() => (sp.get('kind') && sp.get('kind') !== 'PO' ? [blankRow()] : []))
  const pos = usePos(storeId ?? 0)
  const poLines = usePoLines(kind === 'PO' ? poId : 0, storeId ?? 0)
  const wos = useWorkOrders(kind === 'CLIENT_SUPPLY' ? storeId ?? 0 : 0)
  // From a gate entry: its store, order, vendor and challan - taken over once, when it arrives.
  const [fromGate, setFromGate] = useState<number | null>(null)
  if (gate.data && fromGate !== gate.data.id) {
    const g = gate.data
    setFromGate(g.id)
    setStoreId(g.store_id)
    if (g.po_id) setPoId(g.po_id)
    setHead((h) => ({ ...h, vendor_name: g.vendor_name, challan_no: g.challan_no, challan_date: g.challan_date ?? '' }))
  }
  // An order's open lines become the rows to receive against, each time a (new) order's lines arrive.
  const [seeded, setSeeded] = useState<unknown>(null)
  if (kind === 'PO' && poLines.data && seeded !== poLines.data) {
    setSeeded(poLines.data)
    setRows(poLines.data.filter((l) => !l.problem && Number(l.pending_base ?? 0) > 0).map((l) => blankRow(l)))
  }
  const changeKind = (k: GrnKind) => {
    setKind(k)
    setSeeded(null)
    setRows(k === 'PO' ? [] : [blankRow()])
  }
  const set = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.item && Number(r.received) > 0)
  const body = () => ({
    store_id: storeId as number, kind, grn_date: head.grn_date, po_id: kind === 'PO' ? poId : null, gate_entry_id: gateId || null,
    work_order_id: kind === 'CLIENT_SUPPLY' ? woId : null, vendor_name: head.vendor_name, challan_no: head.challan_no, challan_date: head.challan_date || null,
    invoice_no: head.invoice_no, invoice_date: head.invoice_date || null, freight: head.freight || '0', loading: head.loading || '0',
    other_charges: head.other_charges || '0', gst_recoverable: gst === '' ? null : gst === 'yes', reason: head.reason, remarks: head.remarks,
    lines: filled.map((r): GrnLineInput => ({
      po_line_id: r.po?.po_line_id ?? null, item_id: r.item?.id ?? null, uom: r.uom || r.item?.base_uom || '', received_qty: r.received,
      accepted_qty: sub(r.received, r.rejected), rejected_qty: r.rejected || '0', shortage_qty: r.shortage || '0',
      rate: kind === 'DIRECT' ? r.rate : undefined, gst_pct: kind === 'DIRECT' ? r.gst || '0' : undefined, batch_no: r.batch, mtc_ref: r.mtc,
      ...(r.steel ? { nos: Number(r.nos) || null, bundles: Number(r.bundles) || null, dia_mm: r.dia, bar_length_m: r.length, actual_weight: r.weight } : {}),
      remarks: r.remarks,
    })),
  })
  const save = useAction(() => createGrn(body()), { ...refresh, success: (g) => `${g.number} saved as a draft.`, onSuccess: (g) => nav(grnPath(g)) })
  const ready = !!storeId && filled.length > 0 && (kind !== 'PO' || poId > 0) && (kind !== 'CLIENT_SUPPLY' || woId > 0) && (kind !== 'DIRECT' || !!head.reason.trim())
  const h = (k: keyof typeof head) => ({ value: head[k], onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setHead({ ...head, [k]: e.target.value }) })
  return (
    <div className="space-y-4">
      <Card className="grid gap-4 p-4 sm:grid-cols-3">
        <Field label="Receipt" htmlFor="g-kind">
          <Select id="g-kind" value={kind} disabled={!!gateId} options={(Object.keys(KIND_LABEL) as GrnKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))} onChange={(e) => changeKind(e.target.value as GrnKind)} />
        </Field>
        <Field label="Store" htmlFor="g-store"><StorePicker id="g-store" value={storeId} disabled={!!gateId} onChange={(id) => { setStoreId(id); setPoId(0); setWoId(0) }} /></Field>
        <Field label="Date" htmlFor="g-date"><Input id="g-date" type="date" max={today()} {...h('grn_date')} /></Field>
        {kind === 'PO' && (
          <Field label="Purchase order" htmlFor="g-po" hint={storeId ? 'Approved orders for this store\'s project' : 'Choose the store first'}>
            <Select id="g-po" placeholder="Choose an order" disabled={!storeId} value={poId || ''} options={(pos.data ?? []).filter((p) => !p.fully_received).map((p) => ({ value: p.id, label: `${p.number} - ${p.vendor}` }))} onChange={(e) => { setPoId(Number(e.target.value) || 0); const p = pos.data?.find((x) => x.id === Number(e.target.value)); if (p && !head.vendor_name) setHead((x) => ({ ...x, vendor_name: p.vendor })) }} />
          </Field>
        )}
        {kind === 'CLIENT_SUPPLY' && (
          <Field label="Client work order" htmlFor="g-wo" hint="Valued at the rate agreed for it (Client rates)">
            <Select id="g-wo" placeholder="Choose" disabled={!storeId} value={woId || ''} options={(wos.data ?? []).map((w) => ({ value: w.id, label: w.number }))} onChange={(e) => setWoId(Number(e.target.value) || 0)} />
          </Field>
        )}
        <Field label={kind === 'CLIENT_SUPPLY' ? 'Supplied by' : 'Supplier'} htmlFor="g-vendor"><Input id="g-vendor" {...h('vendor_name')} /></Field>
        <Field label="Challan no / date" htmlFor="g-ch"><div className="flex gap-2"><Input id="g-ch" {...h('challan_no')} /><Input type="date" aria-label="Challan date" {...h('challan_date')} /></div></Field>
        {kind !== 'CLIENT_SUPPLY' && <Field label="Invoice no / date" htmlFor="g-inv"><div className="flex gap-2"><Input id="g-inv" {...h('invoice_no')} /><Input type="date" aria-label="Invoice date" {...h('invoice_date')} /></div></Field>}
        <Field label="Freight / loading / other" htmlFor="g-fr" hint="Shared over the lines by value, into the landed rate">
          <div className="flex gap-2">
            {(['freight', 'loading', 'other_charges'] as const).map((k) => <Input key={k} id={k === 'freight' ? 'g-fr' : undefined} aria-label={k} inputMode="decimal" className="text-right" placeholder="0" value={head[k]} onChange={(e) => /^\d*\.?\d{0,2}$/.test(e.target.value) && setHead({ ...head, [k]: e.target.value })} />)}
          </div>
        </Field>
        {kind !== 'CLIENT_SUPPLY' && (
          <Field label="Input GST" htmlFor="g-gst">
            <Select id="g-gst" value={gst} options={[{ value: '', label: 'Company setting' }, { value: 'yes', label: 'Recoverable (not in stock value)' }, { value: 'no', label: 'Not recoverable (in stock value)' }]} onChange={(e) => setGst(e.target.value as '' | 'yes' | 'no')} />
          </Field>
        )}
        {kind === 'DIRECT' && <Field label="Why no purchase order?" htmlFor="g-reason" className="sm:col-span-3"><Textarea id="g-reason" rows={2} {...h('reason')} placeholder="Emergency: slab pour tonight, regular supplier out of stock" /></Field>}
      </Card>

      <Card className="p-0">
        {kind === 'PO' && !poId && <p className="p-4 text-sm text-muted-foreground">Choose an order to see what is still to come.</p>}
        {kind === 'PO' && poId > 0 && (poLines.data ?? []).some((l) => l.problem) && (
          <ul className="border-b border-border p-4 text-xs text-warning">{(poLines.data ?? []).filter((l) => l.problem).map((l) => <li key={l.po_line_id}>{l.description || l.item_code}: {l.problem}</li>)}</ul>
        )}
        {rows.map((r) => (
          <div key={r.key} className="space-y-2 border-b border-border p-4 last:border-b-0">
            <div className="grid gap-2 lg:grid-cols-[minmax(0,2fr)_7rem_repeat(3,minmax(0,1fr))_minmax(0,1fr)_auto] lg:items-end">
              {r.po ? (
                <div className="min-w-0 text-sm">
                  <div className="truncate"><span className="font-mono text-xs text-muted-foreground">{r.po.item_code}</span> {r.po.item_name || r.po.description}</div>
                  <div className="text-xs text-muted-foreground">Pending {n(r.po.pending_qty)} {r.po.po_uom} of {n(r.po.ordered_qty)} · {money(r.po.po_rate)}/{r.po.po_uom} · GST {Number(r.po.gst_pct)}%{Number(r.po.tolerance_pct) ? ` · tolerance ${Number(r.po.tolerance_pct)}%` : ''}</div>
                </div>
              ) : (
                <Field label="Item" htmlFor={`it-${r.key}`}><ItemPicker id={`it-${r.key}`} value={r.item} onChange={(item) => set(r.key, { item, uom: item?.base_uom ?? '' })} /></Field>
              )}
              <Field label="Unit" htmlFor=""><UomSelect itemId={r.item?.id ?? null} value={r.uom || r.item?.base_uom || ''} onChange={(uom) => set(r.key, { uom })} /></Field>
              <Field label="Received" htmlFor={`rc-${r.key}`}><Input id={`rc-${r.key}`} inputMode="decimal" className="text-right" value={r.received} onChange={(e) => qtyOk(e.target.value) && set(r.key, { received: e.target.value })} /></Field>
              <Field label="Rejected" htmlFor={`rj-${r.key}`}><Input id={`rj-${r.key}`} inputMode="decimal" className="text-right" value={r.rejected} onChange={(e) => qtyOk(e.target.value) && set(r.key, { rejected: e.target.value })} /></Field>
              <Field label="Short" htmlFor={`sh-${r.key}`}><Input id={`sh-${r.key}`} inputMode="decimal" className="text-right" value={r.shortage} onChange={(e) => qtyOk(e.target.value) && set(r.key, { shortage: e.target.value })} /></Field>
              <div className="pb-2 text-sm">Accepted <strong>{n(sub(r.received, r.rejected))}</strong></div>
              {!r.po && <Button size="icon-sm" variant="ghost" aria-label="Remove line" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              {kind === 'DIRECT' && (
                <>
                  <Field label={`Rate per ${r.uom || 'unit'}`} htmlFor={`rt-${r.key}`} className="w-32"><Input id={`rt-${r.key}`} inputMode="decimal" className="text-right" value={r.rate} onChange={(e) => /^\d*\.?\d{0,4}$/.test(e.target.value) && set(r.key, { rate: e.target.value })} /></Field>
                  <Field label="GST %" htmlFor={`gs-${r.key}`} className="w-20"><Input id={`gs-${r.key}`} inputMode="decimal" className="text-right" value={r.gst} onChange={(e) => /^\d*\.?\d{0,3}$/.test(e.target.value) && set(r.key, { gst: e.target.value })} /></Field>
                </>
              )}
              <Field label="Batch / heat no" htmlFor={`bt-${r.key}`} className="w-36"><Input id={`bt-${r.key}`} value={r.batch} onChange={(e) => set(r.key, { batch: e.target.value })} /></Field>
              <Field label="MTC ref" htmlFor={`mt-${r.key}`} className="w-36"><Input id={`mt-${r.key}`} value={r.mtc} onChange={(e) => set(r.key, { mtc: e.target.value })} /></Field>
              <label className="flex items-center gap-2 pb-2 text-[13px]"><input type="checkbox" checked={r.steel} onChange={(e) => set(r.key, { steel: e.target.checked })} /> Steel bars</label>
              {r.steel && (
                <>
                  <Field label="Bundles" htmlFor={`bn-${r.key}`} className="w-20"><Input id={`bn-${r.key}`} inputMode="numeric" value={r.bundles} onChange={(e) => /^\d*$/.test(e.target.value) && set(r.key, { bundles: e.target.value })} /></Field>
                  <Field label="Nos" htmlFor={`ns-${r.key}`} className="w-20"><Input id={`ns-${r.key}`} inputMode="numeric" value={r.nos} onChange={(e) => /^\d*$/.test(e.target.value) && set(r.key, { nos: e.target.value })} /></Field>
                  <Field label="Dia mm" htmlFor={`di-${r.key}`} className="w-20"><Input id={`di-${r.key}`} inputMode="decimal" value={r.dia} onChange={(e) => qtyOk(e.target.value) && set(r.key, { dia: e.target.value })} /></Field>
                  <Field label="Length m" htmlFor={`ln-${r.key}`} className="w-20"><Input id={`ln-${r.key}`} inputMode="decimal" value={r.length} onChange={(e) => qtyOk(e.target.value) && set(r.key, { length: e.target.value })} /></Field>
                  <Field label="Weighed kg" htmlFor={`wt-${r.key}`} className="w-28" hint={gate.data?.net_weight ? `gate net ${n(gate.data.net_weight)}` : undefined}><Input id={`wt-${r.key}`} inputMode="decimal" value={r.weight} onChange={(e) => qtyOk(e.target.value) && set(r.key, { weight: e.target.value })} /></Field>
                  {Number(r.nos) > 0 && Number(r.dia) > 0 && <span className="pb-2 text-xs text-muted-foreground">theoretical {n(String((Number(r.nos) * Number(r.dia) ** 2 / 162) * Number(r.length || 12)))} kg</span>}
                </>
              )}
            </div>
          </div>
        ))}
        {kind !== 'PO' && <div className="p-4"><Button variant="outline" size="sm" onClick={() => setRows((rs) => [...rs, blankRow()])}><Plus /> Add line</Button></div>}
      </Card>
      <p className="text-xs text-muted-foreground">Items that need a quality check go in as QC pending: the inspector records what is accepted and rejected, and only that is taken into stock.</p>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => nav(`${BASE}/grn`)}>Back</Button>
        <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>Save draft</Button>
      </div>
    </div>
  )
}

/** One GRN: what came, what was accepted, its quality checks, returns, and the step it can take next. */
export function GrnView() {
  const { id } = useParams()
  const { can } = useSession()
  const q = useGrn(Number(id))
  const [busy, setBusy] = useState<DocAction | null>(null)
  const [qcLine, setQcLine] = useState<GrnLine | null>(null)
  const [returning, setReturning] = useState(false)
  const step = useAction((v: { action: DocAction; reason?: string }) => grnAction(Number(id), v.action, v.reason), { ...refresh, success: (g) => `${g.number} is ${g.status.toLowerCase()}.` })
  const g = q.data
  if (!g) return <p className="text-sm text-muted-foreground">{q.isError ? 'This GRN cannot be opened.' : 'Loading...'}</p>
  const act = async (action: DocAction, reason?: string) => {
    setBusy(action)
    try {
      await step.mutateAsync({ action, reason })
    } finally {
      setBusy(null)
    }
  }
  const inspector = can(storePerm('inward', 'approve'))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-lg font-semibold">{g.number}</h2>
            <DocStatusBadge status={g.status} />
            <Badge>{KIND_LABEL[g.kind]}</Badge>
            {g.qc_pending > 0 && g.status !== 'CANCELLED' && <Badge tone="warning">{g.qc_pending} awaiting QC</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {g.store_code} · {formatDate(g.grn_date)} · {g.vendor_name || '-'}{g.po_number && ` · ${g.po_number}`}{g.work_order && ` · ${g.work_order}`}{g.gate_number && ` · gate ${g.gate_number}`}
          </p>
          <p className="text-sm text-muted-foreground">
            Challan {g.challan_no || '-'} · invoice {g.invoice_no || '-'} · charges {money(Number(g.freight) + Number(g.loading) + Number(g.other_charges))} · GST {g.gst_recoverable ? 'recoverable' : 'in stock value'}
          </p>
          {g.reason && <p className="mt-1 text-sm">No PO: {g.reason}</p>}
          {g.cancel_reason && <p className="mt-1 text-sm text-danger">Cancelled: {g.cancel_reason}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild><a href={pdf.grn(g.id)} target="_blank" rel="noopener"><FileText /> GRN</a></Button>
          {g.lines?.some((l) => l.qc_status !== 'NOT_REQUIRED') && <Button variant="outline" size="sm" asChild><a href={pdf.qc(g.id)} target="_blank" rel="noopener"><FileText /> QC report</a></Button>}
          {g.rejection_memo && <Button variant="outline" size="sm" asChild><a href={pdf.rejection(g.id)} target="_blank" rel="noopener"><FileText /> {g.rejection_memo}</a></Button>}
          {g.status === 'POSTED' && g.kind !== 'CLIENT_SUPPLY' && can(storePerm('inward', 'create')) && <Button variant="outline" size="sm" onClick={() => setReturning(true)}><Undo2 /> Return to supplier</Button>}
          <DocActionsBar status={g.status} busy={busy} onAction={act}
            can={{ submit: can(storePerm('inward', 'create')), approve: inspector, post: can(storePerm('inward', 'post')), cancel: can(storePerm('inward', 'cancel')) }} />
        </div>
      </div>
      <DataTable
        label="GRN lines"
        rows={g.lines ?? []}
        rowKey={(l) => l.id}
        columns={[
          { id: 'n', header: '#', width: '3rem', cell: (l) => l.line_no },
          {
            id: 'item',
            header: 'Item',
            cell: (l) => (
              <div>
                <span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}
                <div className="text-xs text-muted-foreground">
                  {[l.batch_no && `heat ${l.batch_no}`, l.mtc_ref && `MTC ${l.mtc_ref}`, l.qc && `QC ${l.qc.test_ref} by ${l.qc.inspector}`].filter(Boolean).join(' · ')}
                </div>
                {l.steel && (
                  <div className={`text-xs ${Math.abs(Number(l.steel.variance_pct ?? 0)) > 2 ? 'text-warning' : 'text-muted-foreground'}`}>
                    {l.nos} nos x {Number(l.dia_mm)} mm: theoretical {n(l.steel.theoretical_kg)} kg{l.steel.actual_kg && `, weighed ${n(l.steel.actual_kg)} kg (${Number(l.steel.variance_kg) >= 0 ? '+' : ''}${n(l.steel.variance_kg)} kg, ${l.steel.variance_pct}%)`}
                  </div>
                )}
              </div>
            ),
          },
          { id: 'rec', header: 'Received', align: 'right', cell: (l) => `${n(l.received_qty)} ${l.uom}` },
          { id: 'acc', header: 'Accepted', align: 'right', cell: (l) => (l.qc_status === 'QC_PENDING' ? <Badge tone="warning">QC pending</Badge> : `${n(l.accepted_qty)} ${l.uom}`) },
          { id: 'rej', header: 'Rejected', align: 'right', hideBelow: 'md', cell: (l) => (Number(l.rejected_qty) ? `${n(l.rejected_qty)} ${l.uom}` : '-') },
          { id: 'short', header: 'Short', align: 'right', hideBelow: 'lg', cell: (l) => (Number(l.shortage_qty) ? `${n(l.shortage_qty)} ${l.uom}` : '-') },
          { id: 'rate', header: 'Landed rate', align: 'right', hideBelow: 'md', cell: (l) => <div>{formatINR(Number(l.landed_rate))} / {l.base_uom}<div className="text-xs text-muted-foreground">rate {formatINR(Number(l.base_rate))}{Number(l.charges_share) ? `, charges ${money(l.charges_share)}` : ''}</div></div> },
          { id: 'val', header: 'Stock value', align: 'right', cell: (l) => <div><strong>{money(l.stock_value)}</strong>{l.posted && <div className="text-xs text-success">in stock</div>}</div> },
          { id: 'qc', header: '', align: 'right', cell: (l) => l.qc_status === 'QC_PENDING' && inspector && g.status !== 'DRAFT' && g.status !== 'CANCELLED' && <Button size="sm" onClick={() => setQcLine(l)}>Record QC</Button> },
        ]}
      />
      {!!g.returns?.length && (
        <Card className="p-4 text-sm">
          <h3 className="mb-2 font-semibold">Returns to the supplier</h3>
          {g.returns.map((r) => <div key={r.id}><Link className="font-mono text-primary hover:underline" to={`${BASE}/returns/${r.id}`}>{r.number}</Link> <DocStatusBadge status={r.status} /></div>)}
        </Card>
      )}
      {!!g.trail?.length && (
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold">History</h3>
          <ol className="space-y-1 text-sm">{g.trail.map((t, i) => <li key={i}><span className="text-muted-foreground tabular">{t.at.replace('T', ' ')}</span> {t.from && t.from !== t.to ? `${t.from.toLowerCase()} → ${t.to.toLowerCase()}` : t.from ? 'note' : `created as ${t.to.toLowerCase()}`} <span className="text-muted-foreground">by {t.by || 'the account holder'}</span>{t.note && <span className="italic"> "{t.note}"</span>}</li>)}</ol>
        </Card>
      )}
      {qcLine && <QcModal line={qcLine} onClose={() => setQcLine(null)} />}
      {returning && <ReturnModal grn={g} onClose={() => setReturning(false)} />}
    </div>
  )
}

function QcModal({ line, onClose }: { line: GrnLine; onClose: () => void }) {
  const [f, setF] = useState({ accepted_qty: line.received_qty.replace(/\.?0+$/, ''), rejected_qty: '0', test_type: '', test_ref: '', remarks: '' })
  const save = useAction(() => recordQc(line.id, f), { ...refresh, success: 'Quality check recorded.', onSuccess: onClose })
  const sumOk = Math.abs(Number(f.accepted_qty || 0) + Number(f.rejected_qty || 0) - Number(line.received_qty)) < 0.0005
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Quality check: ${line.item_code} ${line.item_name}`} description={`${n(line.received_qty)} ${line.uom} received. Accepted and rejected must add up to it.`}
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!sumOk || !f.test_ref.trim()} onClick={() => save.mutate()}>Record</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={`Accepted (${line.uom})`} htmlFor="qc-a"><Input id="qc-a" inputMode="decimal" className="text-right" value={f.accepted_qty} onChange={(e) => qtyOk(e.target.value) && setF({ ...f, accepted_qty: e.target.value, rejected_qty: sub(line.received_qty, e.target.value) })} /></Field>
        <Field label={`Rejected (${line.uom})`} htmlFor="qc-r" error={sumOk ? undefined : 'Does not add up to what was received'}><Input id="qc-r" inputMode="decimal" className="text-right" value={f.rejected_qty} onChange={(e) => qtyOk(e.target.value) && setF({ ...f, rejected_qty: e.target.value })} /></Field>
        <Field label="Test" htmlFor="qc-t"><Input id="qc-t" value={f.test_type} placeholder="Setting time / cube / tensile" onChange={(e) => setF({ ...f, test_type: e.target.value })} /></Field>
        <Field label="Test reference" htmlFor="qc-ref"><Input id="qc-ref" value={f.test_ref} placeholder="Lab report or TC number" onChange={(e) => setF({ ...f, test_ref: e.target.value })} /></Field>
        <Field label="Remarks" htmlFor="qc-rem" className="sm:col-span-2"><Textarea id="qc-rem" rows={2} value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

function ReturnModal({ grn, onClose }: { grn: Grn; onClose: () => void }) {
  const nav = useNavigate()
  const [head, setHead] = useState({ return_date: today(), reason: '', vehicle_no: '', remarks: '' })
  const options = useMemo(() => (grn.lines ?? []).flatMap((l) => [
    ...(Number(l.rejected_qty) > 0 ? [{ key: `${l.id}-R`, line: l, source: 'REJECTED' as const, max: l.rejected_qty }] : []),
    ...(l.posted && Number(l.accepted_qty) > 0 ? [{ key: `${l.id}-A`, line: l, source: 'ACCEPTED' as const, max: l.accepted_qty }] : []),
  ]), [grn.lines])
  const [qty, setQty] = useState<Record<string, string>>({})
  const lines = options.filter((o) => Number(qty[o.key]) > 0).map((o) => ({ grn_line_id: o.line.id, source: o.source, qty: qty[o.key] }))
  const save = useAction(() => createReturn({ grn_id: grn.id, ...head, lines }), { ...refresh, success: (r) => `${r.number} raised.`, onSuccess: (r) => nav(`${BASE}/returns/${r.id}`) })
  return (
    <Modal open size="lg" onOpenChange={(o) => !o && onClose()} title={`Return to supplier: ${grn.number}`} description="Rejected material never entered stock and is only debited; accepted material leaves stock."
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!lines.length || !head.reason.trim()} onClick={() => save.mutate()}>Raise return</Button></>}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Date" htmlFor="rt-d"><Input id="rt-d" type="date" min={grn.grn_date} max={today()} value={head.return_date} onChange={(e) => setHead({ ...head, return_date: e.target.value })} /></Field>
          <Field label="Vehicle" htmlFor="rt-v"><Input id="rt-v" value={head.vehicle_no} onChange={(e) => setHead({ ...head, vehicle_no: e.target.value })} /></Field>
          <Field label="Reason" htmlFor="rt-r"><Input id="rt-r" value={head.reason} onChange={(e) => setHead({ ...head, reason: e.target.value })} /></Field>
        </div>
        {options.length ? options.map((o) => (
          <div key={o.key} className="flex items-center gap-3 text-sm">
            <span className="min-w-0 flex-1 truncate">{o.line.item_code} {o.line.item_name} <Badge>{o.source === 'REJECTED' ? 'rejected' : 'from stock'}</Badge></span>
            <span className="text-xs text-muted-foreground">up to {n(o.max)} {o.line.uom}</span>
            <Input aria-label={`Return ${o.line.item_code}`} inputMode="decimal" className="w-28 text-right" value={qty[o.key] ?? ''} onChange={(e) => qtyOk(e.target.value) && setQty({ ...qty, [o.key]: e.target.value })} />
          </div>
        )) : <p className="text-sm text-muted-foreground">Nothing on this GRN can go back.</p>}
      </div>
    </Modal>
  )
}
