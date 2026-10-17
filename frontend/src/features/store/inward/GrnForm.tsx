import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { inwardKeys, money, num, today, usePoOptions, type Doc } from './api'

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
}
let seq = 1
const blank = (): Row => ({ key: seq++, po_line_id: null, item: null, label: '', hint: '', qty: { qty: '', uom: '' }, rate: '', rejected: '', reason: '', batch: '' })
const asNumber = (n: number) => (Number.isFinite(n) ? String(Math.round(n * 10000) / 10000) : '')

/** A goods receipt: against a purchase order (its lines are offered, with what is still to come) or, for a cash purchase, free lines. */
export default function GrnForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const projects = useProjects()
  const [f, setF] = useState({
    store_id: doc?.store_id ?? 0, grn_date: doc?.date || today(), po_id: doc?.po_id ?? 0, supplier_name: doc?.supplier_name ?? '', challan_no: doc?.challan_no ?? '',
    challan_date: doc?.challan_date ?? '', vehicle_no: doc?.vehicle_no ?? '', project_id: doc?.project_id ?? 0, remarks: doc?.remarks ?? '',
  })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const pos = usePoOptions()
  const po = (pos.data ?? []).find((p) => p.id === f.po_id)
  const [rows, setRows] = useState<Row[]>(() =>
    (doc?.lines ?? []).map((l) => {
      const factor = Number(l.entry_qty) ? Number(l.received_qty) / Number(l.entry_qty) : 1
      return {
        key: seq++, po_line_id: l.po_line_id ?? null, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, label: l.item_name, hint: '',
        qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom }, rate: asNumber(Number(l.rate) * factor), rejected: Number(l.rejected_qty) ? asNumber(Number(l.rejected_qty) / factor) : '',
        reason: l.reject_reason ?? '', batch: l.batch_no ?? '',
      }
    }),
  )
  // Choosing an order offers its lines: each starts empty, and only those given a quantity go on the receipt.
  const choose = (id: number) => {
    const p = (pos.data ?? []).find((x) => x.id === id)
    setF((x) => ({ ...x, po_id: id, supplier_name: p ? p.supplier_name : x.supplier_name, project_id: p?.project_id ?? x.project_id }))
    setRows(p ? p.lines.map((l) => ({ ...blank(), po_line_id: l.po_line_id, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, label: l.description || l.item_name,
      hint: `Ordered ${num(l.po_qty)} ${l.po_uom} at ${money(l.price)}; ${num(l.pending)} ${l.base_uom} still to come`, qty: { qty: '', uom: l.po_uom }, rate: l.price })) : [])
  }
  // Editing a draft: the order line's figures come from the order, looked up as it is drawn.
  const hintOf = (r: Row) => {
    if (r.hint) return r.hint
    const l = po?.lines.find((x) => x.po_line_id === r.po_line_id)
    return l ? `Ordered ${num(l.po_qty)} ${l.po_uom}; ${num(l.pending)} ${l.base_uom} still to come` : ''
  }
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const filled = rows.filter((r) => r.qty.qty.trim() && Number(r.qty.qty) > 0)
  const save = useAction(
    () => {
      const body = {
        ...f, po_id: f.po_id || null, project_id: f.project_id || null,
        lines: filled.map((r) => ({ po_line_id: r.po_line_id, item_id: r.po_line_id ? null : r.item?.id, qty: r.qty.qty, uom: r.qty.uom, rate: r.rate, rejected_qty: r.rejected, reject_reason: r.reason, batch_no: r.batch })),
      }
      return doc ? storePut<Doc>('inward', `/grn/${doc.id}`, body) : storePost<Doc>('inward', '/grn', body)
    },
    { invalidate: [[...inwardKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/inward/grn/${d.id}`) },
  )
  const ready = f.store_id > 0 && filled.length > 0 && (f.po_id > 0 || (f.supplier_name.trim() && filled.every((r) => r.item && r.rate)))
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="g-store"><StorePicker id="g-store" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Receipt date" htmlFor="g-date"><Input id="g-date" type="date" max={today()} value={f.grn_date} onChange={(e) => set('grn_date', e.target.value)} /></Field>
        <Field label="Purchase order" htmlFor="g-po" hint="Leave empty for a cash purchase.">
          <Select id="g-po" value={f.po_id || ''} placeholder="No purchase order" disabled={!!doc || pos.isPending} onChange={(e) => choose(Number(e.target.value) || 0)}
            options={(pos.data ?? []).map((p) => ({ value: p.id, label: `${p.number} - ${p.supplier_name}` }))} />
        </Field>
        <Field label="Supplier" htmlFor="g-sup"><Input id="g-sup" value={f.supplier_name} disabled={f.po_id > 0} onChange={(e) => set('supplier_name', e.target.value)} /></Field>
        <Field label="Challan / invoice no." htmlFor="g-ch"><Input id="g-ch" value={f.challan_no} onChange={(e) => set('challan_no', e.target.value)} /></Field>
        <Field label="Challan date" htmlFor="g-chd"><Input id="g-chd" type="date" max={today()} value={f.challan_date} onChange={(e) => set('challan_date', e.target.value)} /></Field>
        <Field label="Vehicle no." htmlFor="g-veh"><Input id="g-veh" value={f.vehicle_no} onChange={(e) => set('vehicle_no', e.target.value)} /></Field>
        <Field label="Project" htmlFor="g-proj"><Select id="g-proj" value={f.project_id || ''} placeholder="No project" onChange={(e) => set('project_id', Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Remarks" htmlFor="g-rem"><Textarea id="g-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="g-lines">
        <h3 id="g-lines" className="mb-2 border-b pb-1 text-sm font-semibold">What was received</h3>
        {f.po_id > 0 && <p className="mb-3 text-xs text-muted-foreground">Enter the quantity that arrived against each line; lines left empty are not on this receipt. Quantities beyond the order and the item's tolerance are refused.</p>}
        {rows.length === 0 && f.po_id === 0 && <p className="mb-3 text-sm text-muted-foreground">Add the items that arrived.</p>}
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.2fr)_8rem_8rem_minmax(0,1fr)_auto]">
              <div>
                {r.po_line_id || doc ? <><div className="text-sm font-medium">{r.label || r.item?.name}</div><div className="text-xs text-muted-foreground">{hintOf(r)}</div></> : <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' } })} />}
              </div>
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Input aria-label="Rate per unit" inputMode="decimal" placeholder={`Rate / ${r.qty.uom || 'unit'}`} className="text-right" value={r.rate} onChange={(e) => upd(r.key, { rate: e.target.value })} />
              <Input aria-label="Rejected quantity" inputMode="decimal" placeholder="Rejected" className="text-right" value={r.rejected} onChange={(e) => upd(r.key, { rejected: e.target.value })} />
              <Input aria-label="Reason for rejection" placeholder={Number(r.rejected) ? 'Why rejected (required)' : 'Batch / remarks'} value={Number(r.rejected) ? r.reason : r.batch} onChange={(e) => (Number(r.rejected) ? upd(r.key, { reason: e.target.value }) : upd(r.key, { batch: e.target.value }))} />
              {f.po_id === 0 && <Button type="button" variant="ghost" size="sm" aria-label="Remove line" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>}
            </div>
          ))}
        </div>
        {f.po_id === 0 && <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, blank()])}><Plus /> Add item</Button>}
      </section>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/inward/grn/${doc.id}` : '/store/hub/inward/grn')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>{doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
