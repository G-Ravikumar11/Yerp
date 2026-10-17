import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Trash2, Zap } from 'lucide-react'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storePost, storePut, useStoreMeta, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { headLabel, num, outwardKeys, today, useBoqItems, useEmployees, useIndentPending, useOpenIndents, useOutwardSettings, useSubOrders, useSubcontractors, useWorkOrders, type Doc } from './api'

interface Row { key: number; item: StoreItemOption | null; qty: { qty: string; uom: string }; target: string; chargeable: boolean; basis: string; rate: string; handling: string; due: string; indentLine: number }
let seq = 1
const blank = (): Row => ({ key: seq++, item: null, qty: { qty: '', uom: '' }, target: '', chargeable: false, basis: '', rate: '', handling: '', due: '', indentLine: 0 })
const isReturnable = (i: StoreItemOption | null) => i?.category === 'RETURNABLE' || i?.category === 'TOOL'

/**
 * An issue: material out of a store. A site issue is made against an approved indent (its lines are filled in for you) or, for someone with the
 * direct-issue right, on its own; it is charged to a BOQ item or a cost head and says who received the material. A subcontractor issue names the
 * subcontract work order and whether each line is free of cost or recovered at the contract rate or the average cost, plus handling.
 */
export default function IssueForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const { can } = useSession()
  const direct = !doc && params.get('direct') === '1'
  const canDirect = can('store.outward.direct_issue')
  const meta = useStoreMeta()
  const projects = useProjects()
  const subs = useSubcontractors()
  const emps = useEmployees()
  const settings = useOutwardSettings()
  const indents = useOpenIndents()
  const [f, setF] = useState({
    store_id: doc?.store_id ?? 0, issue_date: doc?.date || today(), issue_type: (doc?.issue_type ?? 'SITE') as 'SITE' | 'SUBCONTRACTOR', project_id: doc?.project_id ?? 0, work_order_id: doc?.work_order_id ?? 0,
    indent_id: doc?.indent_id ?? Number(params.get('indent') || 0), subcontractor_id: doc?.subcontractor_id ?? 0, subcontract_order_id: doc?.subcontract_order_id ?? 0,
    received_by_type: doc?.received_by_type || 'PERSON', received_by_employee_id: doc?.received_by_employee_id ?? 0, received_by_name: doc?.received_by_name ?? '', purpose: doc?.purpose ?? '', remarks: doc?.remarks ?? '',
  })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const boq = useBoqItems(f.project_id)
  const orders = useWorkOrders(f.project_id)
  const subOrders = useSubOrders(f.subcontractor_id, f.project_id)
  const pending = useIndentPending(f.indent_id)
  const sub = f.issue_type === 'SUBCONTRACTOR'
  const [rows, setRows] = useState<Row[]>(() =>
    (doc?.lines ?? []).length
      ? (doc?.lines ?? []).map((l) => ({
          key: seq++, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: l.returnable ? 'RETURNABLE' : null }, qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom },
          target: l.boq_item_id ? `boq:${l.boq_item_id}` : l.cost_head ? `head:${l.cost_head}` : '', chargeable: l.chargeable, basis: l.recovery_basis ?? '', rate: Number(l.recovery_rate) ? String(Number(l.recovery_rate)) : '',
          handling: l.chargeable ? String(Number(l.handling_pct ?? 0)) : '', due: l.expected_return_date, indentLine: l.indent_line_id ?? 0,
        }))
      : [blank()],
  )
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  // Choosing an indent fills the lines from what is still to be issued on it.
  const chooseIndent = (id: number) => { setF((x) => ({ ...x, indent_id: id })); setRows([blank()]) }
  const fromIndent = () => {
    const p = pending.data
    if (!p) return
    setF((x) => ({ ...x, store_id: p.indent.store_id, project_id: p.indent.project_id, work_order_id: p.indent.work_order_id ?? 0 }))
    setRows(p.lines.map((l) => ({ ...blank(), item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, qty: { qty: String(Number(l.pending)), uom: l.base_uom },
      target: p.indent.boq_item_id ? `boq:${p.indent.boq_item_id}` : '', indentLine: l.indent_line_id })))
  }
  const filled = rows.filter((r) => r.item && Number(r.qty.qty) > 0)
  const body = () => ({
    store_id: f.store_id, issue_date: f.issue_date, issue_type: f.issue_type, project_id: f.project_id, work_order_id: f.work_order_id || null, indent_id: f.indent_id || null,
    subcontractor_id: sub ? f.subcontractor_id || null : null, subcontract_order_id: sub ? f.subcontract_order_id || null : null,
    received_by_type: f.received_by_type, received_by_employee_id: f.received_by_type === 'PERSON' ? f.received_by_employee_id || null : null, received_by_name: f.received_by_employee_id && f.received_by_type === 'PERSON' ? '' : f.received_by_name,
    purpose: f.purpose, remarks: f.remarks,
    lines: filled.map((r) => ({ item_id: r.item?.id, qty: r.qty.qty, uom: r.qty.uom, indent_line_id: r.indentLine || null, boq_item_id: r.target.startsWith('boq:') ? Number(r.target.slice(4)) : null, cost_head: r.target.startsWith('head:') ? r.target.slice(5) : '',
      chargeable: sub && r.chargeable, recovery_basis: sub && r.chargeable ? r.basis : '', recovery_rate: sub && r.chargeable && (r.basis || settings.data?.default_recovery_basis) === 'CONTRACT_RATE' ? r.rate : '',
      handling_pct: sub && r.chargeable ? r.handling : '', expected_return_date: isReturnable(r.item) ? r.due : '' })),
  })
  const save = useAction(
    () => (direct ? storePost<Doc>('outward', '/issue/direct', body()) : doc ? storePut<Doc>('outward', `/issue/${doc.id}`, body()) : storePost<Doc>('outward', '/issue', body())),
    { invalidate: [[...outwardKeys.all], ['store', 'lookup']], success: (d) => (direct ? `Issued and posted - ${d.number}` : `Saved as draft - ${d.number}`), onSuccess: (d) => nav(`/store/hub/outward/issue/${d.id}`) },
  )
  const needsIndent = !sub && !f.indent_id && !canDirect
  const costOk = sub || filled.every((r) => r.target)
  const whoOk = f.received_by_type === 'PERSON' && f.received_by_employee_id > 0 ? true : !!f.received_by_name.trim()
  const orderOk = !sub || (f.subcontractor_id > 0 && f.subcontract_order_id > 0)
  const rateOk = filled.every((r) => !(sub && r.chargeable) || (r.basis || settings.data?.default_recovery_basis) !== 'CONTRACT_RATE' || Number(r.rate) > 0)
  const ready = f.store_id > 0 && f.project_id > 0 && filled.length > 0 && costOk && whoOk && orderOk && rateOk && !needsIndent
  const openIndents = (indents.data ?? []).filter((i) => !f.store_id || i.store_id === f.store_id)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      {direct && <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">A direct issue is approved and posted to stock the moment you save it, with no indent. It is marked as direct on the document.</p>}
      {needsIndent && <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">A site issue is made against an approved indent. Choose one below, or ask for the direct-issue right.</p>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="i-store"><StorePicker id="i-store" value={f.store_id || null} disabled={!!doc} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Issue date" htmlFor="i-date"><Input id="i-date" type="date" max={today()} value={f.issue_date} onChange={(e) => set('issue_date', e.target.value)} /></Field>
        <Field label="Issued for" htmlFor="i-type"><Select id="i-type" value={f.issue_type} onChange={(e) => setF((x) => ({ ...x, issue_type: e.target.value as 'SITE' | 'SUBCONTRACTOR', indent_id: 0 }))} options={[{ value: 'SITE', label: 'Site use' }, { value: 'SUBCONTRACTOR', label: 'A subcontractor' }]} /></Field>
        {!sub && (
          <Field label="Indent" htmlFor="i-indent" hint="The approved request this fills.">
            <div className="flex gap-2">
              <Select id="i-indent" value={f.indent_id || ''} placeholder={canDirect ? 'None (direct issue)' : 'Choose an approved indent'} disabled={!!doc} onChange={(e) => chooseIndent(Number(e.target.value) || 0)} options={openIndents.map((i) => ({ value: i.id, label: `${i.number} - ${i.activity || i.project}` }))} />
              {f.indent_id > 0 && !doc && <Button type="button" variant="outline" size="sm" onClick={fromIndent} disabled={!pending.data}>Fill</Button>}
            </div>
          </Field>
        )}
        <Field label="Project" htmlFor="i-proj"><Select id="i-proj" value={f.project_id || ''} placeholder="Choose a project" onChange={(e) => { set('project_id', Number(e.target.value) || 0); set('work_order_id', 0); setRows((rs) => rs.map((r) => ({ ...r, target: r.target.startsWith('boq:') ? '' : r.target }))) }} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Work order" htmlFor="i-wo"><Select id="i-wo" value={f.work_order_id || ''} placeholder="None" disabled={!f.project_id} onChange={(e) => set('work_order_id', Number(e.target.value) || 0)} options={(orders.data ?? []).map((w) => ({ value: w.id, label: `${w.number}${w.status === 'Closed' ? ' (closed)' : ''}` }))} /></Field>
        {sub && <Field label="Subcontractor" htmlFor="i-sub"><Select id="i-sub" value={f.subcontractor_id || ''} placeholder="Choose a subcontractor" onChange={(e) => setF((x) => ({ ...x, subcontractor_id: Number(e.target.value) || 0, subcontract_order_id: 0 }))} options={(subs.data ?? []).map((s) => ({ value: s.id, label: s.name }))} /></Field>}
        {sub && <Field label="Subcontract work order" htmlFor="i-sworder"><Select id="i-sworder" value={f.subcontract_order_id || ''} placeholder="Choose the order" disabled={!f.subcontractor_id} onChange={(e) => set('subcontract_order_id', Number(e.target.value) || 0)} options={(subOrders.data ?? []).map((o) => ({ value: o.id, label: `${o.number}${o.subject ? ' - ' + o.subject : ''}` }))} /></Field>}
        <Field label="Received by" htmlFor="i-rtype"><Select id="i-rtype" value={f.received_by_type} onChange={(e) => setF((x) => ({ ...x, received_by_type: e.target.value, received_by_employee_id: 0 }))} options={[{ value: 'PERSON', label: 'A person' }, { value: 'FOREMAN', label: 'A foreman' }, { value: 'GANG', label: 'A gang' }]} /></Field>
        {f.received_by_type === 'PERSON' && <Field label="Employee" htmlFor="i-emp" hint="Or type a name below."><Select id="i-emp" value={f.received_by_employee_id || ''} placeholder="Not an employee" onChange={(e) => set('received_by_employee_id', Number(e.target.value) || 0)} options={(emps.data ?? []).map((e) => ({ value: e.id, label: e.name }))} /></Field>}
        {!(f.received_by_type === 'PERSON' && f.received_by_employee_id > 0) && <Field label={f.received_by_type === 'GANG' ? 'Gang name' : 'Name'} htmlFor="i-rname"><Input id="i-rname" value={f.received_by_name} onChange={(e) => set('received_by_name', e.target.value)} maxLength={80} /></Field>}
        <Field label="Purpose" htmlFor="i-purpose"><Input id="i-purpose" value={f.purpose} onChange={(e) => set('purpose', e.target.value)} placeholder="Column casting, block 2" /></Field>
        <Field label="Remarks" htmlFor="i-rem"><Textarea id="i-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="i-lines">
        <h3 id="i-lines" className="mb-2 border-b pb-1 text-sm font-semibold">Material</h3>
        {!sub && <p className="mb-3 text-xs text-muted-foreground">Each line is charged to a BOQ item of the project, or to a cost head when it is not BOQ work. It is valued at the store's average rate when it is posted.</p>}
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1.1fr)_minmax(0,1.4fr)_auto]">
              <div>
                {r.indentLine ? <div><div className="text-sm font-medium">{r.item?.name}</div><div className="text-xs text-muted-foreground">from the indent</div></div> : <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' }, due: '' })} />}
              </div>
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Select aria-label="Charge to" value={r.target} placeholder={sub ? 'Charge to (optional)' : 'Charge to...'} onChange={(e) => upd(r.key, { target: e.target.value })}
                options={[...(boq.data ?? []).map((b) => ({ value: `boq:${b.id}`, label: `BOQ ${b.item_no} ${b.description}`.slice(0, 70) })), ...(meta.data?.cost_heads ?? []).map((h) => ({ value: `head:${h}`, label: `Cost head: ${headLabel(h)}` }))]} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove line" disabled={rows.length === 1 || !!r.indentLine} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>
              {(sub || isReturnable(r.item)) && (
                <div className="flex flex-wrap items-center gap-4 lg:col-span-4">
                  {isReturnable(r.item) && <label className="flex items-center gap-2 text-sm">Expected back by <Input type="date" className="h-9 w-40" min={f.issue_date} value={r.due} onChange={(e) => upd(r.key, { due: e.target.value })} /></label>}
                  {sub && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={r.chargeable} onChange={(e) => upd(r.key, { chargeable: e.target.checked, handling: e.target.checked && !r.handling ? String(Number(settings.data?.subcon_handling_pct ?? 0)) : r.handling })} /> Recover from the subcontractor's bill (otherwise free of cost)</label>}
                  {sub && r.chargeable && (
                    <>
                      <label className="flex items-center gap-2 text-sm">at <Select aria-label="Recovery rate basis" className="h-9" value={r.basis || settings.data?.default_recovery_basis || 'AVERAGE_COST'} onChange={(e) => upd(r.key, { basis: e.target.value })} options={[{ value: 'AVERAGE_COST', label: 'average cost' }, { value: 'CONTRACT_RATE', label: 'contract rate' }]} /></label>
                      {(r.basis || settings.data?.default_recovery_basis) === 'CONTRACT_RATE' && <Input aria-label="Contract rate" inputMode="decimal" className="h-9 w-28 text-right" placeholder={`per ${r.item?.base_uom ?? 'unit'}`} value={r.rate} onChange={(e) => upd(r.key, { rate: e.target.value })} />}
                      <label className="flex items-center gap-2 text-sm">plus handling <Input aria-label="Handling percentage" inputMode="decimal" className="h-9 w-20 text-right" value={r.handling} onChange={(e) => upd(r.key, { handling: e.target.value })} /> %</label>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
        {!f.indent_id && <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, blank()])}><Plus /> Add item</Button>}
        {f.indent_id > 0 && pending.data && <p className="mt-2 text-xs text-muted-foreground">{pending.data.lines.map((l) => `${l.item_name}: ${num(l.pending)} ${l.base_uom} still to issue`).join('; ')}</p>}
      </section>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/outward/issue/${doc.id}` : '/store/hub/outward/issue')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>{direct ? <><Zap /> Issue now</> : doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
