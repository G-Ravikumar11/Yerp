import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Trash2, Zap } from 'lucide-react'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { storePost, storePut, useStoreMeta, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { headLabel, outwardKeys, today, useBoqItems, useEmployees, useSubcontractors, useWorkOrders, type Doc } from './api'

interface Row { key: number; item: StoreItemOption | null; qty: { qty: string; uom: string }; target: string; chargeable: boolean; rate: string; due: string }
let seq = 1
const blank = (): Row => ({ key: seq++, item: null, qty: { qty: '', uom: '' }, target: '', chargeable: false, rate: '', due: '' })
const isReturnable = (i: StoreItemOption | null) => i?.category === 'RETURNABLE' || i?.category === 'TOOL'

/** An issue: material out of a store, for a project's BOQ item or a cost head, or to a subcontractor. Returnable items need a holder. */
export default function IssueForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const direct = !doc && params.get('direct') === '1'
  const meta = useStoreMeta()
  const projects = useProjects()
  const subs = useSubcontractors()
  const emps = useEmployees()
  const [f, setF] = useState({
    store_id: doc?.store_id ?? 0, issue_date: doc?.date || today(), issue_type: (doc?.issue_type ?? 'SITE') as 'SITE' | 'SUBCONTRACTOR', project_id: doc?.project_id ?? 0, work_order_id: doc?.work_order_id ?? 0,
    subcontractor_id: doc?.subcontractor_id ?? 0, holder_type: doc?.issue_type === 'SUBCONTRACTOR' ? '' : (doc?.holder_type ?? ''), holder_id: doc?.holder_id ?? 0, holder_name: doc?.holder_name ?? '',
    purpose: doc?.purpose ?? '', remarks: doc?.remarks ?? '',
  })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const boq = useBoqItems(f.project_id)
  const orders = useWorkOrders(f.project_id)
  const [rows, setRows] = useState<Row[]>(() =>
    (doc?.lines ?? []).length
      ? (doc?.lines ?? []).map((l) => ({
          key: seq++, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: l.returnable ? 'RETURNABLE' : null }, qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom },
          target: l.boq_item_id ? `boq:${l.boq_item_id}` : l.cost_head ? `head:${l.cost_head}` : '', chargeable: l.chargeable, rate: Number(l.recovery_rate) ? String(Number(l.recovery_rate)) : '', due: l.expected_return_date,
        }))
      : [blank()],
  )
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.item && Number(r.qty.qty) > 0)
  const sub = f.issue_type === 'SUBCONTRACTOR'
  const body = () => ({
    store_id: f.store_id, issue_date: f.issue_date, issue_type: f.issue_type, project_id: f.project_id, work_order_id: f.work_order_id || null, subcontractor_id: sub ? f.subcontractor_id || null : null,
    holder_type: sub ? '' : f.holder_type, holder_id: !sub && f.holder_type && f.holder_type !== 'GANG' ? f.holder_id || null : null, holder_name: !sub && f.holder_type === 'GANG' ? f.holder_name : '',
    purpose: f.purpose, remarks: f.remarks,
    lines: filled.map((r) => ({ item_id: r.item?.id, qty: r.qty.qty, uom: r.qty.uom, boq_item_id: r.target.startsWith('boq:') ? Number(r.target.slice(4)) : null, cost_head: r.target.startsWith('head:') ? r.target.slice(5) : '',
      chargeable: sub && r.chargeable, recovery_rate: sub && r.chargeable ? r.rate : '', expected_return_date: isReturnable(r.item) ? r.due : '' })),
  })
  const save = useAction(
    () => (direct ? storePost<Doc>('outward', '/issue/direct', body()) : doc ? storePut<Doc>('outward', `/issue/${doc.id}`, body()) : storePost<Doc>('outward', '/issue', body())),
    { invalidate: [[...outwardKeys.all], ['store', 'lookup']], success: (d) => (direct ? `Issued and posted - ${d.number}` : `Saved as draft - ${d.number}`), onSuccess: (d) => nav(`/store/hub/outward/issue/${d.id}`) },
  )
  const needsHolder = filled.some((r) => isReturnable(r.item)) && !sub
  const holderOk = !needsHolder || (f.holder_type === 'GANG' ? !!f.holder_name.trim() : f.holder_type ? f.holder_id > 0 : false)
  const costOk = sub || filled.every((r) => r.target)
  const ready = f.store_id > 0 && f.project_id > 0 && filled.length > 0 && costOk && holderOk && (!sub || f.subcontractor_id > 0) && filled.every((r) => !(sub && r.chargeable) || Number(r.rate) > 0)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      {direct && <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">A direct issue is approved and posted to stock the moment you save it. It is marked as direct on the document.</p>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="i-store"><StorePicker id="i-store" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Issue date" htmlFor="i-date"><Input id="i-date" type="date" max={today()} value={f.issue_date} onChange={(e) => set('issue_date', e.target.value)} /></Field>
        <Field label="Issued for" htmlFor="i-type"><Select id="i-type" value={f.issue_type} onChange={(e) => set('issue_type', e.target.value as 'SITE' | 'SUBCONTRACTOR')} options={[{ value: 'SITE', label: 'Site use' }, { value: 'SUBCONTRACTOR', label: 'A subcontractor' }]} /></Field>
        <Field label="Project" htmlFor="i-proj"><Select id="i-proj" value={f.project_id || ''} placeholder="Choose a project" onChange={(e) => { set('project_id', Number(e.target.value) || 0); set('work_order_id', 0); setRows((rs) => rs.map((r) => ({ ...r, target: r.target.startsWith('boq:') ? '' : r.target }))) }} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Work order" htmlFor="i-wo"><Select id="i-wo" value={f.work_order_id || ''} placeholder="None" disabled={!f.project_id} onChange={(e) => set('work_order_id', Number(e.target.value) || 0)} options={(orders.data ?? []).map((w) => ({ value: w.id, label: w.number }))} /></Field>
        {sub ? (
          <Field label="Subcontractor" htmlFor="i-sub"><Select id="i-sub" value={f.subcontractor_id || ''} placeholder="Choose a subcontractor" onChange={(e) => set('subcontractor_id', Number(e.target.value) || 0)} options={(subs.data ?? []).map((s) => ({ value: s.id, label: s.name }))} /></Field>
        ) : (
          <Field label="Taken by" htmlFor="i-holder" hint={needsHolder ? 'Required: a returnable item is on this issue.' : 'Needed for returnable items and tools.'}>
            <Select id="i-holder" value={f.holder_type} placeholder="Nobody in particular" onChange={(e) => setF((x) => ({ ...x, holder_type: e.target.value, holder_id: 0, holder_name: '' }))} options={[{ value: 'EMPLOYEE', label: 'An employee' }, { value: 'GANG', label: 'A gang' }]} />
          </Field>
        )}
        {!sub && f.holder_type === 'EMPLOYEE' && <Field label="Employee" htmlFor="i-emp"><Select id="i-emp" value={f.holder_id || ''} placeholder="Choose" onChange={(e) => set('holder_id', Number(e.target.value) || 0)} options={(emps.data ?? []).map((e) => ({ value: e.id, label: e.name }))} /></Field>}
        {!sub && f.holder_type === 'GANG' && <Field label="Gang name" htmlFor="i-gang"><Input id="i-gang" value={f.holder_name} onChange={(e) => set('holder_name', e.target.value)} /></Field>}
        <Field label="Purpose" htmlFor="i-purpose"><Input id="i-purpose" value={f.purpose} onChange={(e) => set('purpose', e.target.value)} placeholder="Column casting, block 2" /></Field>
        <Field label="Remarks" htmlFor="i-rem"><Textarea id="i-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="i-lines">
        <h3 id="i-lines" className="mb-2 border-b pb-1 text-sm font-semibold">Material</h3>
        {!sub && <p className="mb-3 text-xs text-muted-foreground">Each line is charged to a BOQ item of the project, or to a cost head when it is not BOQ work. It is valued at the store's average rate when it is posted.</p>}
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1.1fr)_minmax(0,1.4fr)_auto]">
              <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' }, due: '' })} />
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Select aria-label="Charge to" value={r.target} placeholder={sub ? 'Charge to (optional)' : 'Charge to...'} onChange={(e) => upd(r.key, { target: e.target.value })}
                options={[...(boq.data ?? []).map((b) => ({ value: `boq:${b.id}`, label: `BOQ ${b.item_no} ${b.description}`.slice(0, 70) })), ...(meta.data?.cost_heads ?? []).map((h) => ({ value: `head:${h}`, label: `Cost head: ${headLabel(h)}` }))]} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove line" disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>
              {(sub || isReturnable(r.item)) && (
                <div className="flex flex-wrap items-center gap-4 lg:col-span-4">
                  {isReturnable(r.item) && <label className="flex items-center gap-2 text-sm">Expected back by <Input type="date" className="h-9 w-40" min={f.issue_date} value={r.due} onChange={(e) => upd(r.key, { due: e.target.value })} /></label>}
                  {sub && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={r.chargeable} onChange={(e) => upd(r.key, { chargeable: e.target.checked })} /> Recover from the subcontractor's bill</label>}
                  {sub && r.chargeable && <label className="flex items-center gap-2 text-sm">at <Input aria-label="Recovery rate" inputMode="decimal" className="h-9 w-28 text-right" placeholder={`per ${r.item?.base_uom ?? 'unit'}`} value={r.rate} onChange={(e) => upd(r.key, { rate: e.target.value })} /></label>}
                </div>
              )}
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, blank()])}><Plus /> Add item</Button>
      </section>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/outward/issue/${doc.id}` : '/store/hub/outward/issue')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>{direct ? <><Zap /> Issue now</> : doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
