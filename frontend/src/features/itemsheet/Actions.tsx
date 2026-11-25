import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PackageCheck, ShoppingCart, Truck } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, Input, Modal, Select } from '@/components/ui'
import {
  createGrn, createIndent, createIssue, itemSheetKeys, pendingIndentLines, raisePurchaseOrder, stepDocument,
  type ItemSheet, type SheetBoqLine, type SheetIndent, type SheetIssue, type SheetOrder, type SheetReceipt, type SheetTotal,
} from '@/api/itemSheet'
import { useSupplierNames } from '@/api/rfq'
import { ApiError } from '@/lib/api'
import { formatQty, plural, today } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'

const q = (v: number, unit: string) => (v ? `${formatQty(v)} ${unit}` : '-')
const num = (v: string) => v.replace(/[^\d.]/g, '')
const TONE: Record<string, 'neutral' | 'warning' | 'success' | 'danger' | 'info'> = {
  DRAFT: 'neutral', Draft: 'neutral', SUBMITTED: 'warning', 'Awaiting Approval': 'warning', APPROVED: 'info', Approved: 'success', OPEN: 'success',
  PARTIAL: 'info', POSTED: 'success', CLOSED: 'neutral', Closed: 'neutral', CANCELLED: 'danger', Cancelled: 'danger', REJECTED: 'danger', Rejected: 'danger',
}
const status = (s: string) => <Badge tone={TONE[s] ?? 'neutral'}>{s.charAt(0) + s.slice(1).toLowerCase().replace('_', ' ')}</Badge>

/** The project's stores for a form, its own first. */
function StoreField({ s, value, onChange, id }: { s: ItemSheet; value: number; onChange: (v: number) => void; id: string }) {
  return (
    <Field label="Store" htmlFor={id}>
      <Select id={id} value={value || ''} placeholder="Choose the store" onChange={(e) => onChange(Number(e.target.value))}
        options={s.stores.map((st) => ({ value: st.id, label: `${st.code} - ${st.name}${st.this_project ? ' (this project)' : ''}` }))} />
    </Field>
  )
}

// --- purchase order ----------------------------------------------------------------------------------------------------

interface PoRow { id: number; label: string; boq_key: string; item_code: string; item_name: string; unit: string; left: number; on: boolean; qty: string; price: string; gst: string }

/** A purchase order for the sheet's materials, made by the usual route: its budget and rate checks and its approval apply. */
export function PurchaseOrderModal({ s, onClose }: { s: ItemSheet; onClose: () => void }) {
  const suppliers = useSupplierNames()
  const [rows, setRows] = useState<PoRow[]>(() => s.groups.flatMap((g) => g.lines.flatMap((l) => l.materials.map((m) => {
    const left = Math.max(0, +(m.qty - m.ordered - m.awaiting).toFixed(3))
    return { id: m.id, label: `${g.code ? `${g.code} · ` : ''}${l.item_no ? `${l.item_no} ` : ''}${l.description}`, boq_key: l.key, item_code: m.item_code, item_name: m.item_name,
      unit: m.unit, left, on: left > 0, qty: left > 0 ? String(left) : '', price: '', gst: '18' }
  }))))
  const [f, setF] = useState({ supplier_name: '', needed_by: '', notes: '', budget_reason: '' })
  const [overBudget, setOverBudget] = useState('')
  const set = (i: number, patch: Partial<PoRow>) => setRows((r) => r.map((x, n) => (n === i ? { ...x, ...patch } : x)))
  const chosen = rows.filter((r) => r.on && Number(r.qty) > 0)
  const value = chosen.reduce((t, r) => t + Number(r.qty) * Number(r.price || 0), 0)
  const raise = useAction(() => raisePurchaseOrder({
    supplier_name: f.supplier_name.trim(), job_id: s.job_id, needed_by: f.needed_by, notes: f.notes, category: 'materials', budget_reason: f.budget_reason,
    line_items: chosen.map((r) => ({ description: r.item_name, item_code: r.item_code, uom: r.unit, qty: Number(r.qty), price: Number(r.price || 0), tax_rate: `${r.gst}%`, boq_key: r.boq_key })),
  }), {
    invalidate: [itemSheetKeys.one(s.job_id)],
    success: (r) => `${r.order?.number ?? r.number ?? 'The order'} drawn up for ${f.supplier_name.trim()}. It goes for approval as usual; once approved it can be received from here.`,
    onSuccess: onClose,
    onError: (e) => setOverBudget(e instanceof ApiError && e.status === 409 && /budget/i.test(e.detail) ? e.detail : ''),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title="Raise a purchase order"
      description="For this project's sheet materials. Each line is tied to its BOQ line, so the sheet follows what is ordered and received for it."
      footer={<><span className="mr-auto text-sm text-muted-foreground">{plural(chosen.length, 'line')} · {formatINR(value)} before GST</span>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={() => raise.mutate()} loading={raise.isPending} disabled={!f.supplier_name.trim() || !chosen.length}><ShoppingCart /> Raise order</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Supplier" htmlFor="po-sup" className="sm:col-span-2">
            <Input id="po-sup" list="po-sup-list" value={f.supplier_name} onChange={(e) => setF({ ...f, supplier_name: e.target.value })} placeholder="Who it is ordered from" />
            <datalist id="po-sup-list">{(suppliers.data ?? []).map((x) => <option key={x.name} value={x.name} />)}</datalist>
          </Field>
          <Field label="Needed by" htmlFor="po-need"><Input id="po-need" type="date" value={f.needed_by} onChange={(e) => setF({ ...f, needed_by: e.target.value })} /></Field>
          <Field label="Notes (optional)" htmlFor="po-notes" className="sm:col-span-3"><Input id="po-notes" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        </div>
        {overBudget && (
          <div role="alert" className="space-y-2 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
            <p>{overBudget}</p>
            <Field label="Why it has to go over the budget" htmlFor="po-reason"><Input id="po-reason" value={f.budget_reason} onChange={(e) => setF({ ...f, budget_reason: e.target.value })} /></Field>
          </div>
        )}
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm" aria-label="Materials to order">
            <thead className="text-xs uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-border">
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2 text-left font-medium">Material and BOQ line</th>
                <th className="px-3 py-2 text-right font-medium">Left to order</th>
                <th className="w-28 px-3 py-2 text-right font-medium">Quantity</th>
                <th className="w-28 px-3 py-2 text-right font-medium">Rate</th>
                <th className="w-24 px-3 py-2 text-right font-medium">GST</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2"><input type="checkbox" aria-label={`Order ${r.item_name} for ${r.label}`} checked={r.on} onChange={(e) => set(i, { on: e.target.checked })} /></td>
                  <td className="px-3 py-2"><p>{r.item_name} <span className="font-mono text-xs text-muted-foreground">{r.item_code}</span></p><p className="text-xs text-muted-foreground">{r.label}</p></td>
                  <td className="px-3 py-2 text-right tabular">{q(r.left, r.unit)}</td>
                  <td className="px-3 py-2"><Input aria-label={`Quantity of ${r.item_name} for ${r.label}`} inputMode="decimal" className="text-right" value={r.qty} disabled={!r.on} onChange={(e) => set(i, { qty: num(e.target.value) })} /></td>
                  <td className="px-3 py-2"><Input aria-label={`Rate of ${r.item_name} for ${r.label}`} inputMode="decimal" className="text-right" value={r.price} disabled={!r.on} onChange={(e) => set(i, { price: num(e.target.value) })} placeholder="per unit" /></td>
                  <td className="px-3 py-2"><Select aria-label={`GST on ${r.item_name}`} value={r.gst} disabled={!r.on} onChange={(e) => set(i, { gst: e.target.value })} options={['0', '5', '12', '18', '28'].map((g) => ({ value: g, label: `${g}%` }))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Modal>
  )
}

// --- goods receipt -----------------------------------------------------------------------------------------------------

/** Goods come in against an approved order: a goods receipt is made and sent for approval, and posted by the store as usual. */
export function ReceiveModal({ s, order, onClose }: { s: ItemSheet; order: SheetOrder; onClose: () => void }) {
  const lines = order.lines.filter((l) => l.item_id && l.pending > 0)
  const [store, setStore] = useState(s.stores[0]?.id ?? 0)
  const [f, setF] = useState({ date: today(), challan_no: '', vehicle_no: '' })
  const [qty, setQty] = useState<Record<number, string>>(() => Object.fromEntries(lines.map((l) => [l.po_line_id, String(l.pending)])))
  const receive = useAction(async () => {
    const grn = await createGrn({ store_id: store, grn_date: f.date, po_id: order.id, project_id: s.job_id, challan_no: f.challan_no, vehicle_no: f.vehicle_no,
      lines: lines.filter((l) => Number(qty[l.po_line_id]) > 0).map((l) => ({ po_line_id: l.po_line_id, qty: qty[l.po_line_id], uom: l.unit })) })
    await stepDocument('grn', grn.id, 'submit')
    return grn
  }, { invalidate: [itemSheetKeys.one(s.job_id)], success: (g) => `${g.number} made and sent for approval. The store posts it once approved.`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`Receive against ${order.number}`} description={`${order.supplier} · what is still to come on each line`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => receive.mutate()} loading={receive.isPending} disabled={!store || !lines.some((l) => Number(qty[l.po_line_id]) > 0)}><Truck /> Receive</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <StoreField s={s} value={store} onChange={setStore} id="grn-store" />
          <Field label="Received on" htmlFor="grn-date"><Input id="grn-date" type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label="Challan no" htmlFor="grn-challan"><Input id="grn-challan" value={f.challan_no} onChange={(e) => setF({ ...f, challan_no: e.target.value })} /></Field>
          <Field label="Vehicle no" htmlFor="grn-vehicle"><Input id="grn-vehicle" value={f.vehicle_no} onChange={(e) => setF({ ...f, vehicle_no: e.target.value })} /></Field>
        </div>
        <table className="w-full text-sm" aria-label="Quantities received">
          <thead className="text-xs uppercase tracking-wide text-muted-foreground"><tr className="border-b border-border"><th className="py-2 text-left font-medium">Material</th><th className="py-2 text-right font-medium">Still to come</th><th className="w-32 py-2 text-right font-medium">Received now</th></tr></thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.po_line_id} className="border-b border-border last:border-0">
                <td className="py-2">{l.item_name} <span className="font-mono text-xs text-muted-foreground">{l.item_code}</span></td>
                <td className="py-2 text-right tabular">{q(l.pending, l.unit)}</td>
                <td className="py-2 pl-3"><Input aria-label={`Received now of ${l.item_name}`} inputMode="decimal" className="text-right" value={qty[l.po_line_id] ?? ''} onChange={(e) => setQty({ ...qty, [l.po_line_id]: num(e.target.value) })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  )
}

// --- indent ------------------------------------------------------------------------------------------------------------

/** Material asked for, for one BOQ line: an indent with the line's materials, sent for the project manager's approval. */
export function IndentModal({ s, line, onClose }: { s: ItemSheet; line: SheetBoqLine; onClose: () => void }) {
  const [store, setStore] = useState(s.stores[0]?.id ?? 0)
  const [f, setF] = useState({ required_by: '', activity: `${line.item_no ? `${line.item_no} ` : ''}${line.description}`.slice(0, 200) })
  const [qty, setQty] = useState<Record<number, string>>(() => Object.fromEntries(line.materials.map((m) => {
    const left = Math.max(0, +(m.qty - m.indented).toFixed(3))
    return [m.id, left > 0 ? String(left) : '']
  })))
  const ask = useAction(async () => {
    const ind = await createIndent({ store_id: store, project_id: s.job_id, boq_item_id: line.line_id, activity: f.activity, required_by: f.required_by,
      lines: line.materials.filter((m) => Number(qty[m.id]) > 0).map((m) => ({ item_id: m.item_id, qty: qty[m.id], uom: m.unit })) })
    await stepDocument('indent', ind.id, 'submit')
    return ind
  }, { invalidate: [itemSheetKeys.one(s.job_id)], success: (i) => `${i.number} sent to the project manager for approval.`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title="Ask for material" description={`For ${line.item_no ? `${line.item_no} ` : ''}${line.description}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => ask.mutate()} loading={ask.isPending} disabled={!store || !line.materials.some((m) => Number(qty[m.id]) > 0)}>Send the indent</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <StoreField s={s} value={store} onChange={setStore} id="ind-store" />
          <Field label="Needed by" htmlFor="ind-need"><Input id="ind-need" type="date" value={f.required_by} onChange={(e) => setF({ ...f, required_by: e.target.value })} /></Field>
          <Field label="For" htmlFor="ind-activity" className="sm:col-span-2"><Input id="ind-activity" value={f.activity} onChange={(e) => setF({ ...f, activity: e.target.value })} /></Field>
        </div>
        <table className="w-full text-sm" aria-label="Quantities asked for">
          <thead className="text-xs uppercase tracking-wide text-muted-foreground"><tr className="border-b border-border"><th className="py-2 text-left font-medium">Material</th><th className="py-2 text-right font-medium">Needed · indented</th><th className="w-32 py-2 text-right font-medium">Ask for</th></tr></thead>
          <tbody>
            {line.materials.map((m) => (
              <tr key={m.id} className="border-b border-border last:border-0">
                <td className="py-2">{m.item_name} <span className="font-mono text-xs text-muted-foreground">{m.item_code}</span></td>
                <td className="py-2 text-right tabular">{formatQty(m.qty)} · {formatQty(m.indented)} {m.unit}</td>
                <td className="py-2 pl-3"><Input aria-label={`Ask for ${m.item_name}`} inputMode="decimal" className="text-right" value={qty[m.id] ?? ''} onChange={(e) => setQty({ ...qty, [m.id]: num(e.target.value) })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  )
}

// --- issue -------------------------------------------------------------------------------------------------------------

/** Material handed out against an approved indent: an issue is made and sent for approval, and posted by the store as usual. */
export function IssueModal({ s, indent, onClose }: { s: ItemSheet; indent: SheetIndent; onClose: () => void }) {
  const pending = useQuery({ queryKey: ['item-sheet', 'indent-lines', indent.id], queryFn: () => pendingIndentLines(indent.id) })
  const lines = pending.data?.lines ?? []
  const [f, setF] = useState({ date: today(), type: 'FOREMAN', name: '' })
  const [qty, setQty] = useState<Record<number, string>>({})
  const value = (id: number, fallback: string) => qty[id] ?? fallback
  const issue = useAction(async () => {
    const doc = await createIssue({ store_id: indent.store_id, issue_date: f.date, project_id: s.job_id, indent_id: indent.id, received_by_type: f.type, received_by_name: f.name.trim(),
      lines: lines.filter((l) => Number(value(l.indent_line_id, l.pending)) > 0).map((l) => ({ item_id: l.item_id, qty: value(l.indent_line_id, l.pending), uom: l.base_uom, indent_line_id: l.indent_line_id })) })
    await stepDocument('issue', doc.id, 'submit')
    return doc
  }, { invalidate: [itemSheetKeys.one(s.job_id)], success: (d) => `${d.number} made and sent for approval. The store posts it once approved.`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`Issue against ${indent.number}`} description={`${indent.store_code} · ${indent.boq_item || indent.activity}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => issue.mutate()} loading={issue.isPending} disabled={!f.name.trim() || !lines.length}><PackageCheck /> Issue</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Issued on" htmlFor="iss-date"><Input id="iss-date" type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label="Received by" htmlFor="iss-type"><Select id="iss-type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} options={[{ value: 'FOREMAN', label: 'Foreman' }, { value: 'PERSON', label: 'Person' }, { value: 'GANG', label: 'Gang' }]} /></Field>
          <Field label="Name" htmlFor="iss-name"><Input id="iss-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        </div>
        {pending.isPending ? <p className="text-sm text-muted-foreground">Loading...</p> : lines.length === 0 ? <p className="text-sm text-muted-foreground">Nothing is left to issue on this indent.</p> : (
          <table className="w-full text-sm" aria-label="Quantities issued">
            <thead className="text-xs uppercase tracking-wide text-muted-foreground"><tr className="border-b border-border"><th className="py-2 text-left font-medium">Material</th><th className="py-2 text-right font-medium">Still to issue</th><th className="w-32 py-2 text-right font-medium">Issue now</th></tr></thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.indent_line_id} className="border-b border-border last:border-0">
                  <td className="py-2">{l.item_name} <span className="font-mono text-xs text-muted-foreground">{l.item_code}</span></td>
                  <td className="py-2 text-right tabular">{formatQty(Number(l.pending))} {l.base_uom}</td>
                  <td className="py-2 pl-3"><Input aria-label={`Issue now of ${l.item_name}`} inputMode="decimal" className="text-right" value={value(l.indent_line_id, l.pending)} onChange={(e) => setQty({ ...qty, [l.indent_line_id]: num(e.target.value) })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Modal>
  )
}

// --- tracking ------------------------------------------------------------------------------------------------------------

/** Every material over the whole project: what the sheet needs and how far purchase and the store have got with it. */
export function TrackingTab({ s }: { s: ItemSheet }) {
  const cols: TableColumn<SheetTotal>[] = [
    { id: 'n', header: 'Material', sort: (r) => r.item_name, cell: (r) => <div className="min-w-[10rem]"><p>{r.item_name}</p><p className="text-xs text-muted-foreground"><span className="font-mono">{r.item_code}</span>{r.hsn && ` · HSN ${r.hsn}`}{!r.on_sheet && <span className="text-warning"> · not on the sheet</span>}</p></div> },
    { id: 'req', header: 'Needed', align: 'right', sort: (r) => r.required, cell: (r) => <div><p className="font-medium">{q(r.required, r.unit)}</p>{r.approved_qty !== null && r.approved_qty !== r.required && <p className="text-xs text-muted-foreground">{formatQty(r.approved_qty)} approved</p>}</div> },
    { id: 'ord', header: 'Ordered', align: 'right', sort: (r) => r.ordered, cell: (r) => <div><p>{q(r.ordered, r.unit)}</p>{r.awaiting > 0 && <p className="text-xs text-muted-foreground">{formatQty(r.awaiting)} awaiting approval</p>}</div> },
    { id: 'rec', header: 'Received', align: 'right', hideBelow: 'sm', sort: (r) => r.received, cell: (r) => q(r.received, r.unit) },
    { id: 'ind', header: 'Indented', align: 'right', hideBelow: 'lg', sort: (r) => r.indented, cell: (r) => q(r.indented, r.unit) },
    { id: 'iss', header: 'Issued', align: 'right', sort: (r) => r.issued, cell: (r) => <span className={r.issued > r.required ? 'font-semibold text-danger' : ''}>{q(r.issued, r.unit)}</span> },
    { id: 'site', header: 'At site', align: 'right', hideBelow: 'md', sort: (r) => r.at_site, cell: (r) => q(r.at_site, r.unit) },
    { id: 'to', header: 'To order', align: 'right', hideBelow: 'md', sort: (r) => r.to_order, cell: (r) => (r.to_order > 0 ? <span className="font-semibold text-warning">{q(r.to_order, r.unit)}</span> : '-') },
    { id: 'tr', header: 'To receive', align: 'right', hideBelow: 'lg', sort: (r) => r.to_receive, cell: (r) => q(r.to_receive, r.unit) },
  ]
  return <DataTable label="Tracking" rows={s.totals} columns={cols} rowKey={(r) => r.item_id} empty="No materials on the sheet yet." />
}

// --- documents ---------------------------------------------------------------------------------------------------------

type Kind = 'grn' | 'indent' | 'issue'
const NEXT: Record<Kind, Record<string, { action: 'submit' | 'approve' | 'post'; label: string; right: string }>> = {
  grn: { DRAFT: { action: 'submit', label: 'Submit', right: 'store.inward.create' }, SUBMITTED: { action: 'approve', label: 'Approve', right: 'store.inward.approve' }, APPROVED: { action: 'post', label: 'Post', right: 'store.inward.post' } },
  indent: { DRAFT: { action: 'submit', label: 'Submit', right: 'store.outward.create' }, SUBMITTED: { action: 'approve', label: 'Approve', right: 'store.outward.approve' } },
  issue: { DRAFT: { action: 'submit', label: 'Submit', right: 'store.outward.create' }, SUBMITTED: { action: 'approve', label: 'Approve', right: 'store.outward.approve' }, APPROVED: { action: 'post', label: 'Post', right: 'store.outward.post' } },
}

/** The next step of a store document, for whoever holds the right to take it. The server still checks every rule. */
function NextStep({ job, kind, id, at }: { job: number; kind: Kind; id: number; at: string }) {
  const { can } = useSession()
  const next = NEXT[kind][at]
  const step = useAction(() => stepDocument(kind, id, next!.action), { invalidate: [itemSheetKeys.one(job)], success: (r) => `${r.number}: ${r.status.toLowerCase()}.` })
  if (!next || !can(`${next.right}|store.admin`)) return null
  return <Button size="sm" variant="outline" onClick={() => step.mutate()} loading={step.isPending}>{next.label}</Button>
}

const docLink = (to: string, number: string) => <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={to}>{number}</Link>

/** The project's purchase orders, goods receipts, indents and issues, each with its next step. */
export function DocumentsTab({ s, onReceive, onIssue }: { s: ItemSheet; onReceive?: (o: SheetOrder) => void; onIssue?: (i: SheetIndent) => void }) {
  const orderCols: TableColumn<SheetOrder>[] = [
    { id: 'n', header: 'Order', cell: (o) => <div><p className="font-mono text-[13px] font-medium">{o.number}</p><p className="text-xs text-muted-foreground">{o.date}</p></div> },
    { id: 's', header: 'Supplier', hideBelow: 'sm', cell: (o) => o.supplier },
    { id: 'l', header: 'Materials', hideBelow: 'md', cell: (o) => <span className="text-xs">{o.lines.filter((l) => l.item_id).map((l) => `${l.item_name}: ${formatQty(l.received)} of ${formatQty(l.ordered)} ${l.unit}`).join(' · ') || '-'}</span> },
    { id: 't', header: 'Value', align: 'right', hideBelow: 'sm', cell: (o) => formatINR(o.total) },
    { id: 'st', header: 'Status', cell: (o) => status(o.status) },
    { id: 'a', header: '', align: 'right', cell: (o) => (onReceive && o.receivable ? <Button size="sm" variant="outline" onClick={() => onReceive(o)}><Truck /> Receive</Button> : <Link className="text-xs text-primary hover:underline" to="/store/purchase-orders">Open orders</Link>) },
  ]
  const grnCols: TableColumn<SheetReceipt>[] = [
    { id: 'n', header: 'Receipt', cell: (g) => <div>{docLink(`/store/hub/inward/grn/${g.id}`, g.number)}<p className="text-xs text-muted-foreground">{g.date}</p></div> },
    { id: 'p', header: 'Order', hideBelow: 'sm', cell: (g) => g.po_number || '-' },
    { id: 's', header: 'Supplier · store', hideBelow: 'md', cell: (g) => `${g.supplier || '-'} · ${g.store_code}` },
    { id: 'st', header: 'Status', cell: (g) => status(g.status) },
    { id: 'a', header: '', align: 'right', cell: (g) => <NextStep job={s.job_id} kind="grn" id={g.id} at={g.status} /> },
  ]
  const indentCols: TableColumn<SheetIndent>[] = [
    { id: 'n', header: 'Indent', cell: (i) => <div>{docLink(`/store/hub/outward/indent/${i.id}`, i.number)}<p className="text-xs text-muted-foreground">{i.date}</p></div> },
    { id: 'b', header: 'For', hideBelow: 'sm', cell: (i) => <span className="text-xs">{i.boq_item || i.activity}</span> },
    { id: 'st', header: 'Status', cell: (i) => status(i.status) },
    { id: 'a', header: '', align: 'right', cell: (i) => (
      <div className="flex justify-end gap-2">
        <NextStep job={s.job_id} kind="indent" id={i.id} at={i.status} />
        {onIssue && (i.status === 'OPEN' || i.status === 'PARTIAL') && <Button size="sm" variant="outline" onClick={() => onIssue(i)}><PackageCheck /> Issue</Button>}
      </div>) },
  ]
  const issueCols: TableColumn<SheetIssue>[] = [
    { id: 'n', header: 'Issue', cell: (i) => <div>{docLink(`/store/hub/outward/issue/${i.id}`, i.number)}<p className="text-xs text-muted-foreground">{i.date}</p></div> },
    { id: 'i', header: 'Indent', hideBelow: 'sm', cell: (i) => i.indent_number || '-' },
    { id: 'r', header: 'Received by', hideBelow: 'md', cell: (i) => i.received_by },
    { id: 'st', header: 'Status', cell: (i) => status(i.status) },
    { id: 'a', header: '', align: 'right', cell: (i) => <NextStep job={s.job_id} kind="issue" id={i.id} at={i.status} /> },
  ]
  const section = (title: string, node: ReactNode) => <Card className="space-y-2 p-4"><h2 className="text-sm font-semibold">{title}</h2>{node}</Card>
  return (
    <div className="space-y-4">
      {section('Purchase orders', <DataTable label="Purchase orders" rows={s.orders} columns={orderCols} rowKey={(o) => o.id} empty="No purchase orders for this project yet." />)}
      {section('Goods received', <DataTable label="Goods received" rows={s.receipts} columns={grnCols} rowKey={(g) => g.id} empty="Nothing received yet." />)}
      {section('Indents', <DataTable label="Indents" rows={s.indents} columns={indentCols} rowKey={(i) => i.id} empty="No indents yet." />)}
      {section('Issues', <DataTable label="Issues" rows={s.issues} columns={issueCols} rowKey={(i) => i.id} empty="Nothing issued yet." />)}
    </div>
  )
}
