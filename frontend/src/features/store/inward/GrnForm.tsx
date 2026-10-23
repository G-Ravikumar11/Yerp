import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Link2, Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { CHARGE_KINDS, inwardKeys, money, num, today, usePoOptions, type Charge, type ChargeKind, type Doc } from './api'

interface Row {
  key: number
  po_line_id: number | null
  item: StoreItemOption | null
  label: string
  hint: string
  qty: { qty: string; uom: string }
  rate: string
  rejected: string
  reason: string
  batch: string
  made: string
  expiry: string
  /** The expiry was filled in from the manufacturing date (cement), not typed. */
  autoExpiry: boolean
  /** The order line names no stock item yet: the person receiving says which it is. */
  needsItem?: boolean
  pick?: StoreItemOption | null
}
let seq = 1
const blank = (): Row => ({ key: seq++, po_line_id: null, item: null, label: '', hint: '', qty: { qty: '', uom: '' }, rate: '', rejected: '', reason: '', batch: '', made: '', expiry: '', autoExpiry: false })
// Cement loses strength after about ninety days: given its manufacturing date, its expiry is filled in.
const CEMENT_DAYS = 90
const isCement = (r: Row) => /\bcement\b/i.test(r.item?.name || r.label)
const plusDays = (iso: string, days: number) => { const d = new Date(iso + 'T00:00'); d.setDate(d.getDate() + days); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
/** Shelf life is asked for consumables and batch-tracked items - cement, admixtures, epoxies. */
const hasShelfLife = (r: Row) => r.item?.category === 'CONSUMABLE' || !!r.item?.batch_tracked
const asNumber = (n: number) => (Number.isFinite(n) ? String(Math.round(n * 10000) / 10000) : '')

/** A goods receipt: against a purchase order (its lines are offered, with what is still to come) or, for a cash purchase, free lines. */
export default function GrnForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const projects = useProjects()
  const [f, setF] = useState({
    store_id: doc?.store_id ?? 0, grn_date: doc?.date || today(), po_id: doc?.po_id ?? 0, supplier_name: doc?.supplier_name ?? '', challan_no: doc?.challan_no ?? '',
    challan_date: doc?.challan_date ?? '', vehicle_no: doc?.vehicle_no ?? '', project_id: doc?.project_id ?? 0, remarks: doc?.remarks ?? '',
    gate_delivery: doc?.gate_delivery ?? false, driver_remarks: doc?.driver_remarks ?? '',
  })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const qc = useQueryClient()
  const [charges, setCharges] = useState<Charge[]>(() => doc?.charges ?? [])
  const updCharge = (i: number, patch: Partial<Charge>) => setCharges((cs) => cs.map((c, n) => (n === i ? { ...c, ...patch } : c)))
  const chargeTotal = charges.reduce((s, c) => s + (Number(c.amount) || 0), 0)
  const pos = usePoOptions()
  const po = (pos.data ?? []).find((p) => p.id === f.po_id)
  const [rows, setRows] = useState<Row[]>(() =>
    (doc?.lines ?? []).map((l) => {
      const factor = Number(l.entry_qty) ? Number(l.received_qty) / Number(l.entry_qty) : 1
      return {
        key: seq++, po_line_id: l.po_line_id ?? null, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, label: l.item_name, hint: '',
        qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom }, rate: asNumber(Number(l.rate) * factor), rejected: Number(l.rejected_qty) ? asNumber(Number(l.rejected_qty) / factor) : '',
        reason: l.reject_reason ?? '', batch: l.batch_no ?? '', made: l.manufacturing_date ?? '', expiry: l.expiry_date ?? '', autoExpiry: false,
      }
    }),
  )
  // Choosing an order offers its lines: each starts empty, and only those given a quantity go on the receipt.
  const choose = (id: number) => {
    const p = (pos.data ?? []).find((x) => x.id === id)
    setF((x) => ({ ...x, po_id: id, gate_delivery: id ? false : x.gate_delivery, supplier_name: p ? p.supplier_name : x.supplier_name, project_id: p?.project_id ?? x.project_id }))
    setRows(p ? p.lines.map((l): Row => (l.needs_item || l.item_id == null
      ? { ...blank(), po_line_id: l.po_line_id, needsItem: true, label: l.description || l.item_code || 'Order line', hint: `Ordered ${num(l.po_qty)} ${l.po_uom} at ${money(l.price)}${l.item_code ? ` - code ${l.item_code} is not a stock item` : ''}`, qty: { qty: '', uom: l.po_uom }, rate: l.price }
      : { ...blank(), po_line_id: l.po_line_id, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: l.category ?? null, batch_tracked: l.batch_tracked }, label: l.description || l.item_name,
          hint: `Ordered ${num(l.po_qty)} ${l.po_uom} at ${money(l.price)}; ${num(l.pending)} ${l.base_uom} still to come`, qty: { qty: '', uom: l.po_uom }, rate: l.price })) : [])
  }
  // Tie an order line to its stock item, here on the receipt; the order remembers it from then on.
  const link = useAction(
    (r: Row) => storePost<{ item_id: number; item_code: string; item_name: string }>('inward', `/po-line/${r.po_line_id}/item`, { item_id: r.pick?.id }),
    {
      success: (d) => `Order line tied to ${d.item_name}`,
      onSuccess: (d, r) => {
        upd(r.key, { needsItem: false, item: r.pick ? { ...r.pick, id: d.item_id } : null, hint: `${r.hint.split(' - code')[0]} - received as ${d.item_name}` })
        qc.invalidateQueries({ queryKey: ['store', 'inward', 'po-options'] })
      },
    },
  )
  // Editing a draft: the order line's figures come from the order, looked up as it is drawn.
  const hintOf = (r: Row) => {
    if (r.hint) return r.hint
    const l = po?.lines.find((x) => x.po_line_id === r.po_line_id)
    return l ? `Ordered ${num(l.po_qty)} ${l.po_uom}; ${num(l.pending)} ${l.base_uom} still to come` : ''
  }
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const madeOn = (r: Row, made: string) =>
    upd(r.key, isCement(r) && made && (!r.expiry || r.autoExpiry) ? { made, expiry: plusDays(made, CEMENT_DAYS), autoExpiry: true } : { made })

  const filled = rows.filter((r) => !r.needsItem && r.qty.qty.trim() && Number(r.qty.qty) > 0)
  const save = useAction(
    () => {
      const body = {
        ...f, po_id: f.po_id || null, project_id: f.project_id || null, charges: charges.filter((c) => Number(c.amount) > 0),
        lines: filled.map((r) => ({ po_line_id: r.po_line_id, item_id: r.po_line_id ? null : r.item?.id, qty: r.qty.qty, uom: r.qty.uom, rate: r.rate, rejected_qty: r.rejected, reject_reason: r.reason, batch_no: r.batch,
          manufacturing_date: hasShelfLife(r) ? r.made : '', expiry_date: hasShelfLife(r) ? r.expiry : '' })),
      }
      return doc ? storePut<Doc>('inward', `/grn/${doc.id}`, body) : storePost<Doc>('inward', '/grn', body)
    },
    { invalidate: [[...inwardKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/inward/grn/${d.id}`) },
  )
  const gate = f.po_id === 0 && f.gate_delivery
  // A gate delivery is matched on its challan later, so the challan, vehicle and driver's word are required; its rate may be left for the store to fill.
  const challan = !gate || [f.challan_no, f.challan_date, f.vehicle_no, f.driver_remarks].every((v) => v.trim())
  const ready = f.store_id > 0 && filled.length > 0 && challan && (f.po_id > 0 || (f.supplier_name.trim() && filled.every((r) => r.item && (r.rate || gate))))
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="g-store"><StorePicker id="g-store" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Receipt date" htmlFor="g-date"><Input id="g-date" type="date" max={today()} value={f.grn_date} onChange={(e) => set('grn_date', e.target.value)} /></Field>
        <Field label="Purchase order" htmlFor="g-po" hint="Leave empty for a cash purchase or a delivery that came before its order.">
          <Select id="g-po" value={f.po_id || ''} placeholder="No purchase order" disabled={!!doc || pos.isPending} onChange={(e) => choose(Number(e.target.value) || 0)}
            options={(pos.data ?? []).map((p) => ({ value: p.id, label: `${p.number} - ${p.supplier_name}` }))} />
        </Field>
        <Field label="Supplier" htmlFor="g-sup"><Input id="g-sup" value={f.supplier_name} disabled={f.po_id > 0} onChange={(e) => set('supplier_name', e.target.value)} /></Field>
        {f.po_id === 0 && (
          <label className="flex items-start gap-2 rounded-lg border border-border p-3 text-sm sm:col-span-2 lg:col-span-3">
            <input type="checkbox" className="mt-0.5" checked={f.gate_delivery} disabled={!!doc} onChange={(e) => set('gate_delivery', e.target.checked)} />
            <span><span className="font-medium">Unbilled / gate challan delivery</span> - a lorry unloaded before its purchase order was raised. It goes into stock now on its challan and is linked to the order later.</span>
          </label>
        )}
        <Field label="Challan / invoice no." htmlFor="g-ch"><Input id="g-ch" value={f.challan_no} onChange={(e) => set('challan_no', e.target.value)} /></Field>
        <Field label="Challan date" htmlFor="g-chd"><Input id="g-chd" type="date" max={today()} value={f.challan_date} onChange={(e) => set('challan_date', e.target.value)} /></Field>
        <Field label="Vehicle no." htmlFor="g-veh"><Input id="g-veh" value={f.vehicle_no} onChange={(e) => set('vehicle_no', e.target.value)} /></Field>
        {gate && <Field label="Driver / transporter remarks" htmlFor="g-drv" className="sm:col-span-2" hint="Who brought it, when, and anything they said - what it will be matched on."><Input id="g-drv" value={f.driver_remarks} maxLength={300} onChange={(e) => set('driver_remarks', e.target.value)} /></Field>}
        <Field label="Project" htmlFor="g-proj"><Select id="g-proj" value={f.project_id || ''} placeholder="No project" onChange={(e) => set('project_id', Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Remarks" htmlFor="g-rem"><Textarea id="g-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="g-lines">
        <h3 id="g-lines" className="mb-2 border-b pb-1 text-sm font-semibold">What was received</h3>
        {f.po_id > 0 && <p className="mb-3 text-xs text-muted-foreground">Enter the quantity that arrived against each line; lines left empty are not on this receipt. Quantities beyond the order and the item's tolerance are refused.</p>}
        {rows.length === 0 && f.po_id === 0 && <p className="mb-3 text-sm text-muted-foreground">Add the items that arrived.</p>}
        {gate && <p className="mb-3 text-xs text-muted-foreground">A rate left empty is taken from what the store already holds the item at, or its usual purchase rate. The order's rate settles it when the delivery is linked.</p>}
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.2fr)_8rem_8rem_minmax(0,1fr)_auto]">
              {r.needsItem ? (
                <div className="grid gap-2 lg:col-span-6">
                  <div><div className="text-sm font-medium">{r.label}</div><div className="text-xs text-muted-foreground">{r.hint}</div></div>
                  <div className="flex flex-wrap items-center gap-2 rounded-md bg-amber-50 p-2 text-sm dark:bg-amber-950/30">
                    <span className="text-amber-800 dark:text-amber-200">Which stock item is this?</span>
                    <div className="min-w-56 flex-1"><ItemPicker value={r.pick ?? null} onChange={(pick) => upd(r.key, { pick })} /></div>
                    <Button type="button" size="sm" disabled={!r.pick} loading={link.isPending} onClick={() => link.mutate(r)}><Link2 /> Tie to this item</Button>
                  </div>
                </div>
              ) : <>
              <div>
                {r.po_line_id || doc ? <><div className="text-sm font-medium">{r.label || r.item?.name}</div><div className="text-xs text-muted-foreground">{hintOf(r)}</div></> : <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' } })} />}
              </div>
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Input aria-label="Rate per unit" inputMode="decimal" placeholder={gate ? 'Rate (if known)' : `Rate / ${r.qty.uom || 'unit'}`} className="text-right" value={r.rate} onChange={(e) => upd(r.key, { rate: e.target.value })} />
              <Input aria-label="Rejected quantity" inputMode="decimal" placeholder="Rejected" className="text-right" value={r.rejected} onChange={(e) => upd(r.key, { rejected: e.target.value })} />
              <Input aria-label="Reason for rejection" placeholder={Number(r.rejected) ? 'Why rejected (required)' : 'Batch / remarks'} value={Number(r.rejected) ? r.reason : r.batch} onChange={(e) => (Number(r.rejected) ? upd(r.key, { reason: e.target.value }) : upd(r.key, { batch: e.target.value }))} />
              {f.po_id === 0 && <Button type="button" variant="ghost" size="sm" aria-label="Remove line" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>}
              {hasShelfLife(r) && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm lg:col-span-6">
                  {Number(r.rejected) > 0 && <label className="flex items-center gap-2">Batch <Input aria-label="Batch number" className="h-9 w-32" value={r.batch} onChange={(e) => upd(r.key, { batch: e.target.value })} /></label>}
                  <label className="flex items-center gap-2">Manufactured <Input type="date" aria-label="Manufacturing date" className="h-9 w-40" max={today()} value={r.made} onChange={(e) => madeOn(r, e.target.value)} /></label>
                  <label className="flex items-center gap-2">Expires <Input type="date" aria-label="Expiry date" className="h-9 w-40" min={r.made || undefined} value={r.expiry} onChange={(e) => upd(r.key, { expiry: e.target.value, autoExpiry: false })} /></label>
                  <span className="text-xs text-muted-foreground">{r.autoExpiry ? `Cement: ${CEMENT_DAYS} days from manufacture.` : isCement(r) ? `Cement expires ${CEMENT_DAYS} days from manufacture if left empty.` : 'Optional - keeps expired stock off site.'}</span>
                </div>
              )}
              </>}
            </div>
          ))}
        </div>
        {f.po_id === 0 && <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, blank()])}><Plus /> Add item</Button>}
      </section>
      <section aria-labelledby="g-charges">
        <h3 id="g-charges" className="mb-2 border-b pb-1 text-sm font-semibold">Freight and other charges</h3>
        <p className="mb-3 text-xs text-muted-foreground">What it cost to bring the goods in besides the rate - the lorry, unloading, GST that cannot be claimed back. Spread over the accepted lines when the receipt posts, so the stock is valued at its landed cost.</p>
        <div className="grid gap-2">
          {charges.map((c, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[12rem_minmax(0,1fr)_9rem_10rem_auto]">
              <Select aria-label="Kind of charge" value={c.kind} onChange={(e) => updCharge(i, { kind: e.target.value as ChargeKind })} options={Object.entries(CHARGE_KINDS).map(([value, label]) => ({ value, label }))} />
              <Input aria-label="Description" placeholder="Description (optional)" value={c.label} maxLength={80} onChange={(e) => updCharge(i, { label: e.target.value })} />
              <Input aria-label="Amount" inputMode="decimal" placeholder="Amount" className="text-right" value={c.amount} onChange={(e) => updCharge(i, { amount: e.target.value })} />
              <Select aria-label="Spread by" value={c.basis} onChange={(e) => updCharge(i, { basis: e.target.value as Charge['basis'] })} options={[{ value: 'VALUE', label: 'Spread by value' }, { value: 'QTY', label: 'Spread by quantity' }]} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove charge" onClick={() => setCharges((cs) => cs.filter((_x, n) => n !== i))}><Trash2 /></Button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button type="button" variant="outline" size="sm" onClick={() => setCharges((cs) => [...cs, { kind: 'FREIGHT', label: '', amount: '', basis: 'VALUE' }])}><Plus /> Add a charge</Button>
          {chargeTotal > 0 && <span className="text-sm text-muted-foreground">Charges: <span className="font-medium text-foreground">{money(String(chargeTotal))}</span></span>}
        </div>
      </section>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/inward/grn/${doc.id}` : '/store/hub/inward/grn')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>{doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
