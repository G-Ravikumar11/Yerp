import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { inwardKeys, today, type Doc } from './api'

interface Row { key: number; item: StoreItemOption | null; qty: { qty: string; uom: string }; rate: string }
let seq = 1
const blank = (): Row => ({ key: seq++, item: null, qty: { qty: '', uom: '' }, rate: '' })

/** Client-supplied material and opening stock: a store, a date and a list of items with quantity and rate. */
export default function ItemLinesForm({ kind, doc }: { kind: 'client-supply' | 'opening'; doc?: Doc }) {
  const nav = useNavigate()
  const projects = useProjects()
  const supply = kind === 'client-supply'
  const [f, setF] = useState({ store_id: doc?.store_id ?? 0, date: doc?.date || today(), project_id: doc?.project_id ?? 0, client_ref: doc?.client_ref ?? '', remarks: doc?.remarks ?? '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const [rows, setRows] = useState<Row[]>(() =>
    (doc?.lines ?? []).length
      ? (doc?.lines ?? []).map((l) => {
          const factor = Number(l.entry_qty) ? Number(l.qty) / Number(l.entry_qty) : 1
          return { key: seq++, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom },
            rate: Number(l.rate) ? String(Math.round(Number(l.rate) * factor * 10000) / 10000) : '' }
        })
      : [blank()],
  )
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.item && Number(r.qty.qty) > 0)
  const save = useAction(
    () => {
      const lines = filled.map((r) => ({ item_id: r.item?.id, qty: r.qty.qty, uom: r.qty.uom, rate: r.rate }))
      const body = supply
        ? { store_id: f.store_id, supply_date: f.date, project_id: f.project_id, client_ref: f.client_ref, remarks: f.remarks, lines }
        : { store_id: f.store_id, as_on_date: f.date, remarks: f.remarks, lines }
      return doc ? storePut<Doc>('inward', `/${kind}/${doc.id}`, body) : storePost<Doc>('inward', `/${kind}`, body)
    },
    { invalidate: [[...inwardKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/inward/${kind}/${d.id}`) },
  )
  const ready = f.store_id > 0 && filled.length > 0 && (!supply || f.project_id > 0) && (supply || filled.every((r) => r.rate !== ''))
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="l-store"><StorePicker id="l-store" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label={supply ? 'Receipt date' : 'Stock as on'} htmlFor="l-date"><Input id="l-date" type="date" max={today()} value={f.date} onChange={(e) => set('date', e.target.value)} /></Field>
        {supply && <Field label="Project" htmlFor="l-proj"><Select id="l-proj" value={f.project_id || ''} placeholder="Choose a project" onChange={(e) => set('project_id', Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>}
        {supply && <Field label="Client's reference" htmlFor="l-ref" hint="Their challan or letter number."><Input id="l-ref" value={f.client_ref} onChange={(e) => set('client_ref', e.target.value)} /></Field>}
        <Field label="Remarks" htmlFor="l-rem" className="sm:col-span-2"><Textarea id="l-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="l-lines">
        <h3 id="l-lines" className="mb-2 border-b pb-1 text-sm font-semibold">Items</h3>
        <p className="mb-3 text-xs text-muted-foreground">{supply ? "The rate is the value the client puts on it. Leave it empty if the client gives none: the stock is then carried at nil value." : 'The rate is what each unit is worth, in the unit you count in.'}</p>
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.2fr)_9rem_auto]">
              <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' } })} />
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Input aria-label="Rate per unit" inputMode="decimal" className="text-right" placeholder={`Rate / ${r.qty.uom || 'unit'}`} value={r.rate} onChange={(e) => upd(r.key, { rate: e.target.value })} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove line" disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, blank()])}><Plus /> Add item</Button>
      </section>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/inward/${kind}/${doc.id}` : `/store/hub/inward/${kind}`)}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>{doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
