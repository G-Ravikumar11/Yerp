import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Check, Download, Pencil, Send, ShoppingCart, Undo2, Upload } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, Modal, Stat, StatGrid, Tabs, Textarea } from '@/components/ui'
import {
  ITEM_SHEET_EDIT, approveItemSheet, itemSheetFileUrl, itemSheetKeys, sendBackItemSheet, submitItemSheet, uploadItemSheet,
  useItemSheet, useItemSheets, type ItemSheet, type ItemSheetStatus, type ItemSheetSummary, type SheetBoqLine, type SheetIndent, type SheetOrder,
} from '@/api/itemSheet'
import { ApiError } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { plural } from '@/lib/format'
import { MaterialsEditor, MaterialsView } from './MaterialsTab'
import { DocumentsTab, IndentModal, IssueModal, PurchaseOrderModal, ReceiveModal, TrackingTab } from './Actions'

const STATUS: Record<ItemSheetStatus, { label: string; tone: 'neutral' | 'warning' | 'success' }> = {
  DRAFT: { label: 'Draft', tone: 'neutral' },
  SUBMITTED: { label: 'Waiting for the Master', tone: 'warning' },
  APPROVED: { label: 'Approved', tone: 'success' },
}

type Tab = 'materials' | 'tracking' | 'documents'

/**
 * The project's Item sheet, in the Store: the project's BOQ, line by line under its group codes, and under each line the
 * store materials it needs (code, HSN and unit from the Item Master). Made here or uploaded from Excel and approved by the
 * Master; purchase orders, goods receipts, indents and issues for its materials are raised and followed from the same screen.
 */
export default function ItemSheetPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const job = Number(params.get('job')) || 0
  const setJob = (id: number) => setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('job', String(id)); else n.delete('job'); return n }, { replace: true })
  const sheet = useItemSheet(job)

  return (
    <div>
      <PageHeader eyebrow="Store" title="Item sheet"
        description="Each project's BOQ, line by line under its group codes, with the store materials every line needs. Approved by the Master; orders, receipts, indents and issues for them are raised and tracked from here." />
      <div className="mb-4 flex flex-wrap items-end gap-4"><ProjectPicker value={job} onChange={setJob} id="item-sheet-job" /></div>
      {job === 0 && <Overview onOpen={setJob} />}
      {job > 0 && sheet.isError && <p role="alert" className="text-sm text-danger">Could not load the Item sheet.</p>}
      {job > 0 && sheet.isPending && <Card className="p-6 text-sm text-muted-foreground">Loading...</Card>}
      {job > 0 && sheet.data && <Sheet key={job} s={sheet.data} canEdit={can(ITEM_SHEET_EDIT)} />}
    </div>
  )
}

/** Every project and where its sheet stands. */
function Overview({ onOpen }: { onOpen: (job: number) => void }) {
  const list = useItemSheets()
  const cols: TableColumn<ItemSheetSummary>[] = [
    { id: 'p', header: 'Project', sort: (r) => r.name, cell: (r) => <div><p className="font-medium">{r.name}</p>{r.code && <p className="font-mono text-xs text-muted-foreground">{r.code}</p>}</div> },
    { id: 'l', header: 'Materials', align: 'right', sort: (r) => r.materials, cell: (r) => (r.status ? r.materials : '-') },
    { id: 's', header: 'Item sheet', sort: (r) => r.status ?? '', cell: (r) => (r.status ? <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge> : <span className="text-muted-foreground">Not made yet</span>) },
  ]
  return <DataTable label="Projects' Item sheets" rows={list.data?.items ?? []} columns={cols} rowKey={(r) => r.job_id} loading={list.isPending} onRowClick={(r) => onOpen(r.job_id)} empty="No projects yet." />
}

function Sheet({ s, canEdit }: { s: ItemSheet; canEdit: boolean }) {
  const { can } = useSession()
  const [tab, setTab] = useState<Tab>('materials')
  const [editing, setEditing] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [sendingBack, setSendingBack] = useState(false)
  const [ordering, setOrdering] = useState(false)
  const [indentFor, setIndentFor] = useState<SheetBoqLine | null>(null)
  const [receiving, setReceiving] = useState<SheetOrder | null>(null)
  const [issuing, setIssuing] = useState<SheetIndent | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const inval = [itemSheetKeys.one(s.job_id), itemSheetKeys.all]
  const failed = (e: Error) => setProblems(e instanceof ApiError ? e.detail.split('\n').slice(1) : [])
  const upload = useAction((f: File) => uploadItemSheet(s.job_id, f), { invalidate: inval, success: (r) => `Uploaded: ${plural(r.material_count, 'material')}. Send it to the Master for approval.`, onSuccess: () => setProblems([]), onError: failed })
  const submit = useAction(() => submitItemSheet(s.job_id), { invalidate: inval, success: 'Sent to the Master for approval.' })
  const approve = useAction(() => approveItemSheet(s.job_id), { invalidate: inval, success: 'Approved. Purchase orders and indents for this project now go by it.' })
  const noBoq = !s.has_boq
  const status = s.status ? STATUS[s.status] : null
  // Raising documents is for an approved sheet, and for whoever holds the usual right to raise them.
  const live = s.approved
  const canOrder = live && can('purchase.manage')
  const canIndent = live && can('store.outward.create|store.admin')
  const canReceive = can('store.inward.create|store.admin')
  const toOrder = s.totals.filter((t) => t.to_order > 0).length

  if (editing) return (
    <div className="space-y-4">
      <Problems list={problems} />
      <MaterialsEditor s={s} onDone={() => setEditing(false)} setProblems={setProblems} />
    </div>
  )

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="space-y-1 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{s.name}</span>
            {status ? <Badge tone={status.tone}>{status.label}</Badge> : <Badge tone="neutral">Not made yet</Badge>}
          </p>
          {s.approved && <p className="text-muted-foreground">Approved by {s.approved_by}{s.approved_at && ` on ${s.approved_at.slice(0, 10)}`}.</p>}
          {s.status === 'SUBMITTED' && <p className="text-muted-foreground">Sent by {s.submitted_by}{s.submitted_at && ` on ${s.submitted_at.slice(0, 10)}`}.</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => window.open(itemSheetFileUrl(s.job_id), '_blank')} disabled={noBoq}><Download /> {s.material_count ? 'Download Excel' : 'Download template'}</Button>
          {canEdit && <>
            <input ref={file} type="file" accept=".xlsx" className="hidden" aria-label="Upload the Item sheet" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) upload.mutate(f) }} />
            <Button variant="outline" onClick={() => file.current?.click()} loading={upload.isPending} disabled={noBoq}><Upload /> Upload Excel</Button>
            <Button variant="outline" onClick={() => { setProblems([]); setEditing(true) }} disabled={noBoq}><Pencil /> {s.material_count ? 'Edit materials' : 'Add materials here'}</Button>
            {s.status === 'DRAFT' && s.material_count > 0 && <Button onClick={() => submit.mutate()} loading={submit.isPending}><Send /> Send for approval</Button>}
          </>}
          {s.is_master && s.status && s.status !== 'APPROVED' && s.material_count > 0 && <>
            {s.status === 'SUBMITTED' && <Button variant="outline" onClick={() => setSendingBack(true)}><Undo2 /> Send back</Button>}
            <Button onClick={() => approve.mutate()} loading={approve.isPending}><Check /> Approve</Button>
          </>}
        </div>
      </Card>

      {noBoq && (
        <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
          This project has no BOQ yet. The sheet's materials go under the BOQ's lines, so add the BOQ first. <Link className="font-medium underline" to="/projects/boq">Open BOQs</Link>
        </p>
      )}
      {s.returned_note && s.status === 'DRAFT' && (
        <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning"><span className="font-medium">Sent back by the Master:</span> {s.returned_note}</p>
      )}
      {s.approved && s.changed_since_approval && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">The sheet has been changed since the Master approved it. Purchase and the store still go by the approved one until the change is approved.</p>
      )}
      {!s.approved && s.exists && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">Not approved yet. Once the Master approves it, orders and indents for this project can be raised from here, and only for its materials.</p>
      )}
      <Problems list={problems} />

      {!noBoq && (<>
        <StatGrid>
          <Stat label="BOQ lines" value={String(s.groups.reduce((n, g) => n + g.lines.length, 0))} sub={plural(s.group_codes.length, 'group code')} />
          <Stat label="Materials" value={String(s.material_count)} sub={plural(s.item_count, 'item')} />
          <Stat label="Items to order" value={String(toOrder)} tone={toOrder ? 'warning' : undefined} />
          <Stat label="Open orders" value={String(s.orders.filter((o) => o.receivable).length)} sub="to receive" />
        </StatGrid>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs label="Item sheet" value={tab} onChange={setTab} items={[
            { value: 'materials', label: 'Materials' },
            { value: 'tracking', label: 'Tracking' },
            { value: 'documents', label: `Orders & store (${s.orders.length + s.receipts.length + s.indents.length + s.issues.length})` },
          ]} />
          {canOrder && s.material_count > 0 && <Button onClick={() => setOrdering(true)}><ShoppingCart /> Raise purchase order</Button>}
        </div>
        {tab === 'materials' && <MaterialsView s={s} onIndent={canIndent ? setIndentFor : undefined} />}
        {tab === 'tracking' && <TrackingTab s={s} />}
        {tab === 'documents' && <DocumentsTab s={s} onReceive={canReceive ? setReceiving : undefined} onIssue={can('store.outward.create|store.admin') ? setIssuing : undefined} />}
      </>)}

      {sendingBack && <SendBack job={s.job_id} onClose={() => setSendingBack(false)} />}
      {ordering && <PurchaseOrderModal s={s} onClose={() => setOrdering(false)} />}
      {indentFor && <IndentModal s={s} line={indentFor} onClose={() => setIndentFor(null)} />}
      {receiving && <ReceiveModal s={s} order={receiving} onClose={() => setReceiving(null)} />}
      {issuing && <IssueModal s={s} indent={issuing} onClose={() => setIssuing(null)} />}
    </div>
  )
}

function Problems({ list }: { list: string[] }) {
  if (!list.length) return null
  return (
    <div role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
      <p className="font-medium">Nothing was saved. Put these right and try again:</p>
      <ul className="mt-1 list-disc pl-5">{list.map((p, i) => <li key={i}>{p}</li>)}</ul>
    </div>
  )
}

function SendBack({ job, onClose }: { job: number; onClose: () => void }) {
  const [note, setNote] = useState('')
  const back = useAction(() => sendBackItemSheet(job, note), { invalidate: [itemSheetKeys.one(job), itemSheetKeys.all], success: 'Sent back to the storekeeper.', onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Send the Item sheet back" description="Say what has to change. It goes back to draft."
      footer={<><Button variant="ghost" onClick={onClose}>Not now</Button><Button onClick={() => back.mutate()} loading={back.isPending} disabled={!note.trim()}>Send back</Button></>}>
      <Field label="What has to change" htmlFor="is-note"><Textarea id="is-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} /></Field>
    </Modal>
  )
}
