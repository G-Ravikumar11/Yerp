import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { storePost, storePut, useStoreMeta, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { controlKeys, headLabel, num, today, useAllStores, useOpenWriteoffs, type Doc } from './api'

interface Row { key: number; item: StoreItemOption | null; qty: { qty: string; uom: string }; disposal: 'SCRAP' | 'WASTAGE'; reason: string; realised: string; head: string; request: number }
let seq = 1
const blank = (): Row => ({ key: seq++, item: null, qty: { qty: '', uom: '' }, disposal: 'SCRAP', reason: '', realised: '', head: '', request: 0 })
const asItem = (l: NonNullable<Doc['lines']>[number]): StoreItemOption => ({ id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null })

/** A transfer: from one store to another, with the items and quantities. */
export function TransferForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const [f, setF] = useState({ store_id: doc?.store_id ?? 0, to_store_id: doc?.to_store_id ?? 0, transfer_date: doc?.date || today(), vehicle_no: doc?.vehicle_no ?? '', remarks: doc?.remarks ?? '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const [rows, setRows] = useState<{ key: number; item: StoreItemOption | null; qty: { qty: string; uom: string } }[]>(() =>
    (doc?.lines ?? []).length ? (doc?.lines ?? []).map((l) => ({ key: seq++, item: asItem(l), qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom ?? '' } })) : [{ key: seq++, item: null, qty: { qty: '', uom: '' } }],
  )
  const upd = (key: number, patch: Partial<(typeof rows)[number]>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.item && Number(r.qty.qty) > 0)
  const save = useAction(
    () => {
      const body = { ...f, lines: filled.map((r) => ({ item_id: r.item?.id, qty: r.qty.qty, uom: r.qty.uom })) }
      return doc ? storePut<Doc>('control', `/transfer/${doc.id}`, body) : storePost<Doc>('control', '/transfer', body)
    },
    { invalidate: [[...controlKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/control/transfer/${d.id}`) },
  )
  const ready = f.store_id > 0 && f.to_store_id > 0 && f.store_id !== f.to_store_id && filled.length > 0
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="From store" htmlFor="t-from"><StorePicker id="t-from" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="To store" htmlFor="t-to" hint="Any store of the company; its staff receive it."><StoreAnyPicker id="t-to" value={f.to_store_id || null} excludeId={f.store_id || undefined} onChange={(id) => set('to_store_id', id ?? 0)} /></Field>
        <Field label="Transfer date" htmlFor="t-date"><Input id="t-date" type="date" max={today()} value={f.transfer_date} onChange={(e) => set('transfer_date', e.target.value)} /></Field>
        <Field label="Vehicle no." htmlFor="t-veh"><Input id="t-veh" value={f.vehicle_no} onChange={(e) => set('vehicle_no', e.target.value)} /></Field>
        <Field label="Remarks" htmlFor="t-rem" className="sm:col-span-2"><Textarea id="t-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="t-lines">
        <h3 id="t-lines" className="mb-2 border-b pb-1 text-sm font-semibold">Items</h3>
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.2fr)_auto]">
              <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' } })} />
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove line" disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, { key: seq++, item: null, qty: { qty: '', uom: '' } }])}><Plus /> Add item</Button>
      </section>
      <Footer cancelTo={doc ? `/store/hub/control/transfer/${doc.id}` : '/store/hub/control/transfer'} busy={save.isPending} disabled={!ready} label={doc ? 'Save changes' : 'Save as draft'} />
    </form>
  )
}

/** A destination may be any store of the company, not only the ones this person works in: only receiving needs access to it. */
function StoreAnyPicker({ id, value, excludeId, onChange }: { id: string; value: number | null; excludeId?: number; onChange: (id: number | null) => void }) {
  const stores = useAllStores()
  return (
    <Select id={id} value={value ?? ''} placeholder="Choose a store" disabled={stores.isPending} onChange={(e) => onChange(Number(e.target.value) || null)}
      options={(stores.data ?? []).filter((s) => s.id !== excludeId).map((s) => ({ value: s.id, label: `${s.code} - ${s.name}` }))} />
  )
}

function Footer({ cancelTo, busy, disabled, label }: { cancelTo: string; busy: boolean; disabled: boolean; label: string }) {
  const nav = useNavigate()
  return (
    <div className="flex justify-end gap-2 border-t border-border pt-4">
      <Button type="button" variant="ghost" onClick={() => nav(cancelTo)}>Cancel</Button>
      <Button type="submit" loading={busy} disabled={disabled}>{label}</Button>
    </div>
  )
}

/** A new stock count: the store, the date, and whether it is the whole store or chosen items. The count itself starts from its own page. */
export function CountForm() {
  const nav = useNavigate()
  const [f, setF] = useState({ store_id: 0, count_date: today(), count_type: 'FULL' as 'FULL' | 'PARTIAL', remarks: '' })
  const [items, setItems] = useState<(StoreItemOption | null)[]>([null])
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const chosen = items.filter((i): i is StoreItemOption => !!i)
  const save = useAction(() => storePost<Doc>('control', '/count', { ...f, item_ids: f.count_type === 'PARTIAL' ? chosen.map((i) => i.id) : [] }), {
    invalidate: [[...controlKeys.all]], success: (d) => `Count created - ${d.number}. Start it when you are ready to count.`, onSuccess: (d) => nav(`/store/hub/control/count/${d.id}`),
  })
  const ready = f.store_id > 0 && (f.count_type === 'FULL' || chosen.length > 0)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="c-store"><StorePicker id="c-store" value={f.store_id || null} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Count date" htmlFor="c-date"><Input id="c-date" type="date" max={today()} value={f.count_date} onChange={(e) => set('count_date', e.target.value)} /></Field>
        <Field label="Count" htmlFor="c-type"><Select id="c-type" value={f.count_type} onChange={(e) => set('count_type', e.target.value as 'FULL' | 'PARTIAL')} options={[{ value: 'FULL', label: 'Everything the store holds' }, { value: 'PARTIAL', label: 'Chosen items only' }]} /></Field>
        <Field label="Remarks" htmlFor="c-rem" className="sm:col-span-2 lg:col-span-3"><Textarea id="c-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      {f.count_type === 'PARTIAL' && (
        <section aria-labelledby="c-items">
          <h3 id="c-items" className="mb-2 border-b pb-1 text-sm font-semibold">Items to count</h3>
          <div className="grid gap-2">{items.map((it, i) => <ItemPicker key={i} value={it} onChange={(v) => setItems((xs) => xs.map((x, j) => (j === i ? v : x)))} />)}</div>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setItems((xs) => [...xs, null])}><Plus /> Add item</Button>
        </section>
      )}
      <p className="text-xs text-muted-foreground">Starting a count freezes the store: nothing can be received, issued or transferred until the count is posted or cancelled.</p>
      <Footer cancelTo="/store/hub/control/count" busy={save.isPending} disabled={!ready} label="Create count" />
    </form>
  )
}

/** Wastage and scrap: items written off, each as scrap (which can record what it fetched) or wastage (charged to a cost head). */
export function ScrapForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const meta = useStoreMeta()
  const projects = useProjects()
  const [f, setF] = useState({ store_id: doc?.store_id ?? 0, scrap_date: doc?.date || today(), project_id: doc?.project_id ?? 0, buyer: doc?.buyer ?? '', reference: doc?.reference ?? '', remarks: doc?.remarks ?? '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const [rows, setRows] = useState<Row[]>(() =>
    (doc?.lines ?? []).length
      ? (doc?.lines ?? []).map((l) => ({ key: seq++, item: asItem(l), qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom ?? '' }, disposal: l.disposal ?? 'SCRAP', reason: l.reason ?? '', realised: Number(l.realised_value) ? String(Number(l.realised_value)) : '',
          head: l.cost_head ?? '', request: l.writeoff_request_id ?? 0 }))
      : [blank()],
  )
  const requests = useOpenWriteoffs(f.store_id)
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.item && Number(r.qty.qty) > 0)
  const save = useAction(
    () => {
      const body = { ...f, project_id: f.project_id || null, lines: filled.map((r) => ({ item_id: r.item?.id, qty: r.qty.qty, uom: r.qty.uom, disposal: r.disposal, reason: r.reason, realised_value: r.disposal === 'SCRAP' ? r.realised : '', cost_head: r.head, writeoff_request_id: r.request || null })) }
      return doc ? storePut<Doc>('control', `/scrap/${doc.id}`, body) : storePost<Doc>('control', '/scrap', body)
    },
    { invalidate: [[...controlKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/control/scrap/${d.id}`) },
  )
  const ready = f.store_id > 0 && filled.length > 0 && filled.every((r) => r.reason.trim())
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="s-store"><StorePicker id="s-store" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Date" htmlFor="s-date"><Input id="s-date" type="date" max={today()} value={f.scrap_date} onChange={(e) => set('scrap_date', e.target.value)} /></Field>
        <Field label="Project" htmlFor="s-proj" hint="Whose cost it is, if any."><Select id="s-proj" value={f.project_id || ''} placeholder="No project" onChange={(e) => set('project_id', Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Buyer" htmlFor="s-buyer"><Input id="s-buyer" value={f.buyer} onChange={(e) => set('buyer', e.target.value)} /></Field>
        <Field label="Gate pass / voucher no." htmlFor="s-ref"><Input id="s-ref" value={f.reference} onChange={(e) => set('reference', e.target.value)} /></Field>
        <Field label="Remarks" htmlFor="s-rem"><Textarea id="s-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="s-lines">
        <h3 id="s-lines" className="mb-2 border-b pb-1 text-sm font-semibold">Items written off</h3>
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1.1fr)_9rem_minmax(0,1.3fr)_auto]">
              <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' }, request: 0 })} />
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Select aria-label="Disposal" value={r.disposal} onChange={(e) => upd(r.key, { disposal: e.target.value as 'SCRAP' | 'WASTAGE', realised: '' })} options={[{ value: 'SCRAP', label: 'Scrap' }, { value: 'WASTAGE', label: 'Wastage' }]} />
              <Input aria-label="Reason" placeholder="Why (required)" value={r.reason} onChange={(e) => upd(r.key, { reason: e.target.value })} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove line" disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>
              <div className="flex flex-wrap items-center gap-4 lg:col-span-5">
                {r.disposal === 'SCRAP' ? (
                  <label className="flex items-center gap-2 text-sm">Fetched <Input aria-label="Amount realised" inputMode="decimal" className="h-9 w-32 text-right" placeholder="0.00" value={r.realised} onChange={(e) => upd(r.key, { realised: e.target.value })} /></label>
                ) : (
                  <label className="flex items-center gap-2 text-sm">Charged to <Select aria-label="Cost head" className="h-9" value={r.head} placeholder="No cost head" onChange={(e) => upd(r.key, { head: e.target.value })} options={(meta.data?.cost_heads ?? []).map((h) => ({ value: h, label: headLabel(h) }))} /></label>
                )}
                {r.item && (requests.data ?? []).some((w) => w.item_id === r.item?.id) && (
                  <label className="flex items-center gap-2 text-sm" title="It left the store when it was issued, so no stock moves: the line only closes the request.">Deals with write-off request
                    <Select aria-label="Write-off request" className="h-9" value={r.request || ''} placeholder="None" onChange={(e) => upd(r.key, { request: Number(e.target.value) || 0 })}
                      options={(requests.data ?? []).filter((w) => w.item_id === r.item?.id).map((w) => ({ value: w.id, label: `#${w.id} - ${num(w.qty)} - ${w.reason}` }))} />
                  </label>
                )}
              </div>
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, blank()])}><Plus /> Add item</Button>
      </section>
      <Footer cancelTo={doc ? `/store/hub/control/scrap/${doc.id}` : '/store/hub/control/scrap'} busy={save.isPending} disabled={!ready} label={doc ? 'Save changes' : 'Save as draft'} />
    </form>
  )
}
