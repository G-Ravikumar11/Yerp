import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileSpreadsheet, PackageOpen, Pencil, Plus, Printer, ShoppingCart, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { EnquiryFromLines } from '../reports/RaiseEnquiry'
import { dmy, num, outwardKeys, qs, today, useBoqItems, useIndent, useIndents, useWorkOrders, type Indent, type IndentLine } from './api'

const TONE = { DRAFT: 'neutral', SUBMITTED: 'info', OPEN: 'warning', PARTIAL: 'warning', CLOSED: 'success', CANCELLED: 'danger' } as const
const LABEL = { DRAFT: 'Draft', SUBMITTED: 'Awaiting approval', OPEN: 'Open', PARTIAL: 'Partly issued', CLOSED: 'Closed', CANCELLED: 'Cancelled' } as const
export const IndentBadge = ({ status }: { status: Indent['status'] }) => <Badge tone={TONE[status]} dot>{LABEL[status]}</Badge>

/** Indents: material asked for by site engineers, approved by the project manager and filled by issues. */
export function IndentListPage() {
  const nav = useNavigate()
  const { can } = useSession()
  const [params] = useSearchParams()
  const [f, setF] = useState({ status: params.get('status') ?? '', store_id: 0, project_id: 0, q: '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const projects = useProjects()
  const list = useIndents(f)
  const columns: TableColumn<Indent>[] = [
    { id: 'no', header: 'Number', width: '14rem', sort: (d) => d.number, cell: (d) => <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/store/hub/outward/indent/${d.id}`}>{d.number}</Link> },
    { id: 'date', header: 'Raised', width: '8rem', sort: (d) => d.date, cell: (d) => dmy(d.date) },
    { id: 'need', header: 'Needed by', width: '9rem', hideBelow: 'sm', sort: (d) => d.required_by, cell: (d) => (d.required_by ? <span className={d.overdue ? 'text-danger' : ''}>{dmy(d.required_by)}{d.overdue && ' (late)'}</span> : '-') },
    { id: 'proj', header: 'Project', hideBelow: 'md', cell: (d) => d.project },
    { id: 'for', header: 'For', hideBelow: 'lg', cell: (d) => d.activity || d.boq_item || d.work_order || '-' },
    { id: 'by', header: 'Raised by', hideBelow: 'lg', cell: (d) => d.requested_by },
    { id: 'done', header: 'Issued', align: 'right', width: '6rem', hideBelow: 'sm', cell: (d) => (['OPEN', 'PARTIAL', 'CLOSED'].includes(d.status) ? `${d.fulfilled_pct}%` : '-') },
    { id: 'status', header: 'Status', width: '11rem', cell: (d) => <IndentBadge status={d.status} /> },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="in-store" className="w-52"><StorePicker id="in-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Project" htmlFor="in-proj" className="w-56"><Select id="in-proj" value={f.project_id || ''} placeholder="All projects" onChange={(e) => set('project_id', Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Status" htmlFor="in-status" className="w-44"><Select id="in-status" value={f.status} placeholder="Any" onChange={(e) => set('status', e.target.value)} options={Object.entries(LABEL).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Search" htmlFor="in-q" className="w-44"><Input id="in-q" value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="Number, activity, person" /></Field>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" asChild><a href={`/api/store/outward/indent/export${qs(f)}`}><FileSpreadsheet /> Excel</a></Button>
          {can(storePerm('outward', 'create')) && <Button onClick={() => nav('/store/hub/outward/indent/new')}><Plus /> New indent</Button>}
        </div>
      </div>
      {list.isError ? <p role="alert" className="text-sm text-danger">Could not load the indents.</p> : <DataTable label="Indents" rows={list.data?.items ?? []} loading={list.isPending} columns={columns} rowKey={(d) => d.id} onRowClick={(d) => nav(`/store/hub/outward/indent/${d.id}`)} empty="No indents yet." />}
    </div>
  )
}

interface Row { key: number; item: StoreItemOption | null; qty: { qty: string; uom: string }; purpose: string }
let seq = 1

/** Raise (or change a draft) indent: the project, what it is for, when it is needed, and the items. */
export function IndentForm({ indent }: { indent?: Indent }) {
  const nav = useNavigate()
  const projects = useProjects()
  const [f, setF] = useState({ store_id: indent?.store_id ?? 0, indent_date: indent?.date || today(), required_by: indent?.required_by ?? '', project_id: indent?.project_id ?? 0, work_order_id: indent?.work_order_id ?? 0, boq_item_id: indent?.boq_item_id ?? 0, activity: indent?.activity ?? '', remarks: indent?.remarks ?? '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const orders = useWorkOrders(f.project_id)
  const boq = useBoqItems(f.project_id)
  const [rows, setRows] = useState<Row[]>(() => ((indent?.lines ?? []).length
    ? (indent?.lines ?? []).map((l) => ({ key: seq++, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, qty: { qty: String(Number(l.entry_qty)), uom: l.entry_uom }, purpose: l.purpose }))
    : [{ key: seq++, item: null, qty: { qty: '', uom: '' }, purpose: '' }]))
  const upd = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.item && Number(r.qty.qty) > 0)
  const save = useAction(
    () => {
      const body = { ...f, work_order_id: f.work_order_id || null, boq_item_id: f.boq_item_id || null, lines: filled.map((r) => ({ item_id: r.item?.id, qty: r.qty.qty, uom: r.qty.uom, purpose: r.purpose })) }
      return indent ? storePut<Indent>('outward', `/indent/${indent.id}`, body) : storePost<Indent>('outward', '/indent', body)
    },
    { invalidate: [[...outwardKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/outward/indent/${d.id}`) },
  )
  const ready = f.store_id > 0 && f.project_id > 0 && filled.length > 0 && !!(f.work_order_id || f.boq_item_id || f.activity.trim())
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Store" htmlFor="ix-store"><StorePicker id="ix-store" value={f.store_id || null} disabled={!!indent} onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Date" htmlFor="ix-date"><Input id="ix-date" type="date" max={today()} value={f.indent_date} onChange={(e) => set('indent_date', e.target.value)} /></Field>
        <Field label="Needed by" htmlFor="ix-need"><Input id="ix-need" type="date" min={f.indent_date} value={f.required_by} onChange={(e) => set('required_by', e.target.value)} /></Field>
        <Field label="Project" htmlFor="ix-proj"><Select id="ix-proj" value={f.project_id || ''} placeholder="Choose a project" onChange={(e) => setF((x) => ({ ...x, project_id: Number(e.target.value) || 0, work_order_id: 0, boq_item_id: 0 }))} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Work order" htmlFor="ix-wo"><Select id="ix-wo" value={f.work_order_id || ''} placeholder="None" disabled={!f.project_id} onChange={(e) => set('work_order_id', Number(e.target.value) || 0)} options={(orders.data ?? []).map((w) => ({ value: w.id, label: w.number }))} /></Field>
        <Field label="BOQ item" htmlFor="ix-boq" hint="Issues against this indent are charged to it."><Select id="ix-boq" value={f.boq_item_id || ''} placeholder="None" disabled={!f.project_id} onChange={(e) => set('boq_item_id', Number(e.target.value) || 0)} options={(boq.data ?? []).map((b) => ({ value: b.id, label: `${b.item_no} ${b.description}`.slice(0, 70) }))} /></Field>
        <Field label="Activity" htmlFor="ix-act" hint="Needed if there is no work order or BOQ item." className="sm:col-span-2"><Input id="ix-act" value={f.activity} onChange={(e) => set('activity', e.target.value)} placeholder="Columns, block 2" maxLength={200} /></Field>
        <Field label="Remarks" htmlFor="ix-rem"><Textarea id="ix-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      <section aria-labelledby="ix-lines">
        <h3 id="ix-lines" className="mb-2 border-b pb-1 text-sm font-semibold">Material asked for</h3>
        <div className="grid gap-3">
          {rows.map((r) => (
            <div key={r.key} className="grid gap-3 rounded-lg border border-border p-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1.1fr)_minmax(0,1.2fr)_auto]">
              <ItemPicker value={r.item} onChange={(item) => upd(r.key, { item, qty: { qty: '', uom: item?.base_uom ?? '' } })} />
              <UomQtyInput itemId={r.item?.id ?? null} value={r.qty} onChange={(qty) => upd(r.key, { qty })} />
              <Input aria-label="Purpose" placeholder="What it is for" value={r.purpose} onChange={(e) => upd(r.key, { purpose: e.target.value })} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove line" disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}><Trash2 /></Button>
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setRows((rs) => [...rs, { key: seq++, item: null, qty: { qty: '', uom: '' }, purpose: '' }])}><Plus /> Add item</Button>
      </section>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(indent ? `/store/hub/outward/indent/${indent.id}` : '/store/hub/outward/indent')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>{indent ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}

/** An indent: its lines (asked, approved, issued, pending), history, and what its status allows - submit, approve with cut quantities, issue against it, close or cancel. */
export function IndentPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const { can } = useSession()
  const q = useIndent(Number(id))
  const [approving, setApproving] = useState(false)
  const [buying, setBuying] = useState(false)
  const [reason, setReason] = useState<'cancel' | 'close' | null>(null)
  const [why, setWhy] = useState('')
  const [discarding, setDiscarding] = useState(false)
  const refresh = [[...outwardKeys.all]]
  const act = useAction((path: string) => storePost<Indent>('outward', `/indent/${id}/${path}`, { reason: why }), { invalidate: refresh, success: (d) => `${d.number}: ${LABEL[d.status].toLowerCase()}`, onSuccess: () => { setReason(null); setWhy('') } })
  const discard = useAction(() => storeDelete<{ message: string }>('outward', `/indent/${id}`), { invalidate: refresh, onSuccess: () => nav('/store/hub/outward/indent') })
  const back = <Link to="/store/hub/outward/indent" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Indents</Link>
  const d = q.data
  if (q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (q.isError || !d) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this indent.</p></div>
  const open = d.status === 'OPEN' || d.status === 'PARTIAL'
  // What the store cannot give from what it holds: the part of the indent to buy.
  const short = open ? (d.lines ?? []).filter((l) => Number(l.short ?? 0) > 0) : []
  const columns: TableColumn<IndentLine>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
    { id: 'ask', header: 'Asked', align: 'right', width: '8rem', cell: (l) => `${num(l.qty)} ${l.base_uom}` },
    { id: 'app', header: 'Approved', align: 'right', width: '8rem', cell: (l) => (l.approved_qty == null ? '-' : <span className={Number(l.approved_qty) < Number(l.qty) ? 'text-warning' : ''}>{num(l.approved_qty)} {l.base_uom}</span>) },
    { id: 'iss', header: 'Issued', align: 'right', width: '8rem', cell: (l) => `${num(l.fulfilled)} ${l.base_uom}` },
    { id: 'pen', header: 'Pending', align: 'right', width: '8rem', cell: (l) => (l.pending == null ? '-' : `${num(l.pending)} ${l.base_uom}`) },
    ...(open ? [{ id: 'short', header: 'Short in store', align: 'right' as const, width: '9rem', cell: (l: IndentLine) => (Number(l.short ?? 0) > 0 ? <span className="font-medium text-danger">{num(l.short)} {l.base_uom}</span> : <span className="text-muted-foreground">-</span>) }] : []),
    { id: 'why', header: 'Purpose', hideBelow: 'md', cell: (l) => <div>{l.purpose || '-'}{l.reason && <div className="text-xs text-warning">{l.substitute_for_line_id ? 'Substituted: ' : 'Cut back: '}{l.reason}</div>}</div> },
  ]
  const facts: [string, string][] = [['Store', `${d.store_code} - ${d.store_name}`], ['Raised', `${dmy(d.date)} by ${d.requested_by}`], ['Needed by', d.required_by ? dmy(d.required_by) : '-'], ['Project', d.project], ['Work order', d.work_order || '-'],
    ['BOQ item', d.boq_item || '-'], ['Activity', d.activity || '-'], ['Approved', d.approved_by ? `${d.approved_by} on ${dmy(d.approved_at)}${d.approver_remarks ? ' - ' + d.approver_remarks : ''}` : '-'], ['Remarks', d.remarks || '-']]
  return (
    <div>
      {back}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="font-mono text-lg font-semibold">{d.number}</h2><div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground"><IndentBadge status={d.status} /> Indent{d.short_closed && <Badge tone="warning">Closed short</Badge>}</div></div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" asChild><a href={`/api/store/outward/indent/${d.id}/print`} target="_blank" rel="noreferrer"><Printer /> Print</a></Button>
          {d.status === 'DRAFT' && can(storePerm('outward', 'create')) && (<><Button variant="outline" onClick={() => nav(`/store/hub/outward/indent/${d.id}/edit`)}><Pencil /> Edit</Button><Button variant="ghost" onClick={() => setDiscarding(true)}><Trash2 /> Delete draft</Button><Button loading={act.isPending} onClick={() => act.mutate('submit')}>Submit for approval</Button></>)}
          {d.status === 'SUBMITTED' && can(storePerm('outward', 'approve')) && <Button onClick={() => setApproving(true)}>Review and approve</Button>}
          {open && can(storePerm('outward', 'create')) && <Button onClick={() => nav(`/store/hub/outward/issue/new?indent=${d.id}`)}><PackageOpen /> Issue against it</Button>}
          {short.length > 0 && can('purchase.manage') && <Button variant="outline" onClick={() => setBuying(true)}><ShoppingCart /> Buy the short items</Button>}
          {open && can(storePerm('outward', 'approve')) && <Button variant="outline" onClick={() => setReason('close')}>Close short</Button>}
          {(d.status === 'DRAFT' || d.status === 'SUBMITTED' || d.status === 'OPEN') && can(storePerm('outward', 'create')) && <Button variant="ghost" onClick={() => setReason('cancel')}>Cancel</Button>}
        </div>
      </div>
      {d.status === 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">Cancelled: {d.cancel_reason}.</p>}
      {d.short_closed && <p role="status" className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">Closed short: {d.cancel_reason}.</p>}
      {short.length > 0 && <p role="status" className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{d.store_code} cannot fill {short.length === 1 ? '1 line' : `${short.length} lines`} from what it holds{can('purchase.manage') ? ' - press Buy the short items to raise a purchase enquiry for the rest.' : '. Ask purchasing to buy the rest.'}</p>}
      {d.status === 'SUBMITTED' && <p role="status" className="mb-4 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">Waiting for the project manager. They can reduce the quantities when they approve.</p>}
      <dl className="mb-5 grid gap-x-6 gap-y-2 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">{facts.map(([k, v]) => <div key={k}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>)}</dl>
      <DataTable label="Indent lines" rows={d.lines ?? []} columns={columns} rowKey={(l) => l.id} />
      {(d.issues ?? []).length > 0 && <p className="mt-3 text-sm text-muted-foreground">Issues: {(d.issues ?? []).map((i) => <Link key={i.id} className="mr-3 font-mono text-primary hover:underline" to={`/store/hub/outward/issue/${i.id}`}>{i.number} ({i.status.toLowerCase()})</Link>)}</p>}
      <section aria-labelledby="in-history" className="mt-6"><h3 id="in-history" className="mb-2 border-b pb-1 text-sm font-semibold">History</h3>
        <ul className="space-y-1 text-sm">{(d.history ?? []).map((h, i) => <li key={i}><span className="font-medium capitalize">{h.action}</span> by {h.by || 'the account holder'} on {dmy(h.at)}{h.note ? ` - ${h.note}` : ''}</li>)}</ul></section>
      {approving && <ApproveModal indent={d} onClose={() => setApproving(false)} />}
      {buying && (
        <EnquiryFromLines title={`${d.number} - short items for ${d.activity || d.project}`} jobId={d.project_id} neededBy={d.required_by}
          notes={`Raised from indent ${d.number} (${d.store_code}): what the store could not give from stock.`}
          description={`The items ${d.store_code} is short of for ${d.number}, at the quantity still to find. Change what is needed, then ask suppliers for quotes from the enquiry.`}
          lines={short.map((l) => ({ key: String(l.id), item_code: l.item_code, item_name: l.item_name, uom: l.base_uom, qty: String(Number(l.short)), note: `short by ${num(l.short)} ${l.base_uom} on ${d.number}`, on: true }))}
          onClose={() => setBuying(false)} />
      )}
      <Modal open={!!reason} onOpenChange={(o) => !o && setReason(null)} title={reason === 'close' ? 'Close this indent short?' : 'Cancel this indent?'} description={reason === 'close' ? 'What is still pending will not be issued.' : 'Nothing has been issued against it.'}>
        <form onSubmit={(e) => { e.preventDefault(); if (why.trim().length > 2 && reason) act.mutate(reason) }} className="grid gap-4">
          <Field label="Why" htmlFor="in-why"><Input id="in-why" value={why} onChange={(e) => setWhy(e.target.value)} autoFocus maxLength={200} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setReason(null)}>Keep it</Button><Button type="submit" loading={act.isPending} disabled={why.trim().length < 3}>{reason === 'close' ? 'Close it' : 'Cancel it'}</Button></div>
        </form>
      </Modal>
      <ConfirmDialog open={discarding} onOpenChange={setDiscarding} title="Delete this draft?" description="It has not been submitted." confirmLabel="Delete" tone="danger" onConfirm={() => { discard.mutate(); setDiscarding(false) }} />
    </div>
  )
}

function ApproveModal({ indent, onClose }: { indent: Indent; onClose: () => void }) {
  const lines = indent.lines ?? []
  const [qty, setQty] = useState<Record<number, string>>(() => Object.fromEntries(lines.map((l) => [l.id, String(Number(l.entry_qty))])))
  const [why, setWhy] = useState<Record<number, string>>({})
  const [sub, setSub] = useState<Record<number, { item: StoreItemOption | null; qty: string; uom: string }>>({})
  const [remarks, setRemarks] = useState('')
  const cut = (l: IndentLine) => Number(qty[l.id] ?? l.entry_qty) < Number(l.entry_qty)
  const body = () => ({
    remarks,
    lines: lines.map((l) => {
      const s = sub[l.id]
      return { line_id: l.id, approved_qty: qty[l.id] ?? '0', uom: l.entry_uom, reason: why[l.id] ?? '', ...(cut(l) && s?.item ? { substitute_item_id: s.item.id, substitute_qty: s.qty, substitute_uom: s.uom || s.item.base_uom } : {}) }
    }),
  })
  const save = useAction(() => storePost<Indent>('outward', `/indent/${indent.id}/approve`, body()), { invalidate: [[...outwardKeys.all]], success: (d) => `${d.number} approved`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`Approve ${indent.number}`} description="You can reduce what was asked for, to nothing if need be, but not raise it. Say why a line is cut, and give another item in its place if you can.">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4">
        <ul className="divide-y rounded-lg border">
          {lines.map((l) => (
            <li key={l.id} className="grid gap-2 px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span><span className="font-medium">{l.item_name}</span> <span className="text-muted-foreground">asked {num(l.entry_qty)} {l.entry_uom}</span></span>
                <span className="flex items-center gap-2"><Input aria-label={`Approved quantity of ${l.item_name}`} inputMode="decimal" className="h-9 w-28 text-right" value={qty[l.id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value }))} /> {l.entry_uom}</span>
              </div>
              {cut(l) && (
                <div className="grid gap-2 rounded-lg bg-muted/50 p-2">
                  <Input aria-label={`Why ${l.item_name} was cut`} placeholder="Why this was cut back" maxLength={200} value={why[l.id] ?? ''} onChange={(e) => setWhy((w) => ({ ...w, [l.id]: e.target.value }))} />
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                    <ItemPicker value={sub[l.id]?.item ?? null} placeholder="Give another item in its place (optional)" onChange={(item) => setSub((s) => ({ ...s, [l.id]: { item, qty: s[l.id]?.qty ?? '', uom: item?.base_uom ?? '' } }))} />
                    {sub[l.id]?.item && <Input aria-label={`Quantity of ${sub[l.id]?.item?.name}`} inputMode="decimal" className="text-right" placeholder={`Quantity (${sub[l.id]?.item?.base_uom})`} value={sub[l.id]?.qty ?? ''} onChange={(e) => setSub((s) => ({ ...s, [l.id]: { ...s[l.id], qty: e.target.value } }))} />}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
        <Field label="Remarks" htmlFor="ap-rem"><Input id="ap-rem" value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Taken as the reason for any line without its own" maxLength={200} /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Approve</Button></div>
      </form>
    </Modal>
  )
}
