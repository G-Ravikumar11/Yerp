import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Check, Download, Pencil, Plus, Send, Trash2, Undo2, Upload } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import {
  ITEM_SHEET_EDIT, approveItemSheet, itemSheetFileUrl, itemSheetKeys, saveItemSheet, sendBackItemSheet, submitItemSheet, uploadItemSheet,
  useItemSheet, useItemSheets, type ItemSheet, type ItemSheetLine, type ItemSheetStatus, type ItemSheetSummary, type ItemSheetUsage,
} from '@/api/itemSheet'
import type { StoreItemOption } from '@/api/store'
import { ItemPicker } from '@/features/store/shared'
import { ApiError } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatQty, plural } from '@/lib/format'

const STATUS: Record<ItemSheetStatus, { label: string; tone: 'neutral' | 'warning' | 'success' }> = {
  DRAFT: { label: 'Draft', tone: 'neutral' },
  SUBMITTED: { label: 'Waiting for the Master', tone: 'warning' },
  APPROVED: { label: 'Approved', tone: 'success' },
}

/** A line being edited: the item is held whole so the box can show it without looking it up again. */
interface Draft { group_code: string; item: StoreItemOption | null; qty: string; remarks: string; hsn: string }

const asOption = (l: ItemSheetLine): StoreItemOption => ({ id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.unit, uoms: [], category: null })
const blank = (group = ''): Draft => ({ group_code: group, item: null, qty: '', remarks: '', hsn: '' })

/**
 * The project's Item sheet, in the Store: the materials the project will need, each under a group code of its BOQ, with the
 * item's HSN and unit from the item master. Made here or uploaded from the Excel template; once the Master approves it, an
 * indent for the project may ask only for what is on it.
 */
export default function ItemSheetPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const job = Number(params.get('job')) || 0
  const setJob = (id: number) => setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('job', String(id)); else n.delete('job'); return n }, { replace: true })
  const sheet = useItemSheet(job)
  const canEdit = ITEM_SHEET_EDIT.some((p) => can(p))

  return (
    <div>
      <PageHeader eyebrow="Store" title="Item sheet"
        description="The materials each project needs, under its BOQ group codes, with HSN from the item master. Made here or uploaded from Excel, approved by the Master - then indents ask only for what is on it." />
      <div className="mb-4 flex flex-wrap items-end gap-4"><ProjectPicker value={job} onChange={setJob} id="item-sheet-job" /></div>
      {job === 0 && <Overview onOpen={setJob} />}
      {job > 0 && sheet.isError && <p role="alert" className="text-sm text-danger">Could not load the Item sheet.</p>}
      {job > 0 && sheet.isPending && <Card className="p-6 text-sm text-muted-foreground">Loading...</Card>}
      {job > 0 && sheet.data && <Sheet key={job} s={sheet.data} canEdit={canEdit} />}
    </div>
  )
}

/** Every project and where its sheet stands. */
function Overview({ onOpen }: { onOpen: (job: number) => void }) {
  const list = useItemSheets()
  const cols: TableColumn<ItemSheetSummary>[] = [
    { id: 'p', header: 'Project', sort: (r) => r.name, cell: (r) => <div><p className="font-medium">{r.name}</p>{r.code && <p className="font-mono text-xs text-muted-foreground">{r.code}</p>}</div> },
    { id: 'l', header: 'Lines', align: 'right', sort: (r) => r.lines, cell: (r) => (r.status ? r.lines : '-') },
    { id: 's', header: 'Item sheet', sort: (r) => r.status ?? '', cell: (r) => (r.status ? <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge> : <span className="text-muted-foreground">Not made yet</span>) },
  ]
  return <DataTable label="Projects' Item sheets" rows={list.data?.items ?? []} columns={cols} rowKey={(r) => r.job_id} loading={list.isPending} onRowClick={(r) => onOpen(r.job_id)}
    empty="No projects yet." />
}

function Sheet({ s, canEdit }: { s: ItemSheet; canEdit: boolean }) {
  const [editing, setEditing] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [sendingBack, setSendingBack] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const inval = [itemSheetKeys.one(s.job_id), itemSheetKeys.all]
  const failed = (e: Error) => setProblems(e instanceof ApiError ? e.detail.split('\n').slice(1) : [])
  const upload = useAction((f: File) => uploadItemSheet(s.job_id, f), { invalidate: inval, success: (r) => `Uploaded: ${plural(r.lines.length, 'line')}. Send it to the Master for approval.`, onSuccess: () => setProblems([]), onError: failed })
  const submit = useAction(() => submitItemSheet(s.job_id), { invalidate: inval, success: 'Sent to the Master for approval.' })
  const approve = useAction(() => approveItemSheet(s.job_id), { invalidate: inval, success: 'Approved. Indents for this project now go by it.' })
  const noBoq = s.groups.length === 0
  const status = s.status ? STATUS[s.status] : null

  if (editing) return <Editor s={s} onDone={() => setEditing(false)} problems={problems} setProblems={setProblems} />

  const cols: TableColumn<ItemSheetLine>[] = [
    { id: 'g', header: 'Group code', sort: (l) => s.groups.indexOf(l.group_code), cell: (l) => <span className="font-medium">{l.group_code}</span> },
    { id: 'c', header: 'Item code', hideBelow: 'md', sort: (l) => l.item_code, cell: (l) => <span className="font-mono text-xs">{l.item_code}</span> },
    { id: 'n', header: 'Item', sort: (l) => l.item_name, cell: (l) => <div className="min-w-[10rem] max-w-[22rem]"><p>{l.item_name}</p><p className="font-mono text-xs text-muted-foreground md:hidden">{l.item_code}</p></div> },
    { id: 'h', header: 'HSN', hideBelow: 'sm', sort: (l) => l.hsn, cell: (l) => l.hsn || <span className="text-muted-foreground">-</span> },
    { id: 'q', header: 'Quantity', align: 'right', sort: (l) => l.qty, cell: (l) => `${formatQty(l.qty)} ${l.unit}` },
    { id: 'r', header: 'Remarks', hideBelow: 'lg', cell: (l) => <span className="text-muted-foreground">{l.remarks || '-'}</span> },
  ]

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="space-y-1 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{s.name}</span>
            {status ? <Badge tone={status.tone}>{status.label}</Badge> : <Badge tone="neutral">Not made yet</Badge>}
            {s.exists && <span className="text-muted-foreground">{plural(s.lines.length, 'line')}, {plural(s.item_count, 'item')}</span>}
          </p>
          {s.approved && <p className="text-muted-foreground">Approved by {s.approved_by}{s.approved_at && ` on ${s.approved_at.slice(0, 10)}`}.</p>}
          {s.status === 'SUBMITTED' && <p className="text-muted-foreground">Sent by {s.submitted_by}{s.submitted_at && ` on ${s.submitted_at.slice(0, 10)}`}.</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => window.open(itemSheetFileUrl(s.job_id), '_blank')} disabled={noBoq}><Download /> {s.lines.length ? 'Download Excel' : 'Download template'}</Button>
          {canEdit && <>
            <input ref={file} type="file" accept=".xlsx" className="hidden" aria-label="Upload the Item sheet" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) upload.mutate(f) }} />
            <Button variant="outline" onClick={() => file.current?.click()} loading={upload.isPending} disabled={noBoq}><Upload /> Upload Excel</Button>
            <Button variant="outline" onClick={() => { setProblems([]); setEditing(true) }} disabled={noBoq}><Pencil /> {s.lines.length ? 'Edit' : 'Make it here'}</Button>
            {s.status === 'DRAFT' && s.lines.length > 0 && <Button onClick={() => submit.mutate()} loading={submit.isPending}><Send /> Send for approval</Button>}
          </>}
          {s.is_master && s.status && s.status !== 'APPROVED' && s.lines.length > 0 && <>
            {s.status === 'SUBMITTED' && <Button variant="outline" onClick={() => setSendingBack(true)}><Undo2 /> Send back</Button>}
            <Button onClick={() => approve.mutate()} loading={approve.isPending}><Check /> Approve</Button>
          </>}
        </div>
      </Card>

      {noBoq && (
        <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
          This project's BOQ has no group codes yet{s.exists ? '' : ' (or it has no BOQ)'}. Every line of the Item sheet sits under a BOQ group code, so add the BOQ, with its group codes, first. <Link className="font-medium underline" to="/projects/boq">Open BOQs</Link>
        </p>
      )}
      {s.returned_note && s.status === 'DRAFT' && (
        <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning"><span className="font-medium">Sent back by the Master:</span> {s.returned_note}</p>
      )}
      {s.approved && s.changed_since_approval && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
          The sheet has been changed since the Master approved it. Indents still go by the approved one until the change is approved.
        </p>
      )}
      {!s.approved && s.exists && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">Not approved yet, so indents for this project are not held to it.</p>
      )}
      <Problems list={problems} />

      {s.exists ? (
        <DataTable label="Item sheet" rows={s.lines} columns={cols} rowKey={(l) => l.id} empty="No lines." />
      ) : !noBoq && (
        <Card className="p-6 text-sm text-muted-foreground">
          No Item sheet for this project yet. {canEdit ? 'Download the template, fill it in Excel and upload it - or make it here.' : 'The storekeeper makes it.'}
        </Card>
      )}
      {s.approved && s.usage.length > 0 && <Usage rows={s.usage} />}
      {sendingBack && <SendBack job={s.job_id} onClose={() => setSendingBack(false)} />}
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

/** By the approved sheet, item by item: what it allows and what the project's indents have asked for so far. */
function Usage({ rows }: { rows: ItemSheetUsage[] }) {
  const cols: TableColumn<ItemSheetUsage>[] = [
    { id: 'n', header: 'Item', sort: (r) => r.item_name, cell: (r) => <div><p>{r.item_name}</p><p className="font-mono text-xs text-muted-foreground">{r.item_code}</p></div> },
    { id: 's', header: 'On the sheet', align: 'right', sort: (r) => r.sheet_qty, cell: (r) => (r.on_sheet ? `${formatQty(r.sheet_qty)} ${r.unit}` : <span className="text-muted-foreground">Not on it</span>) },
    { id: 'i', header: 'Indented', align: 'right', sort: (r) => r.indented, cell: (r) => <span className={r.indented > r.sheet_qty ? 'font-semibold text-danger' : ''}>{formatQty(r.indented)} {r.unit}</span> },
    { id: 'l', header: 'Left', align: 'right', hideBelow: 'sm', sort: (r) => r.sheet_qty - r.indented, cell: (r) => `${formatQty(Math.max(0, r.sheet_qty - r.indented))} ${r.unit}` },
  ]
  return (
    <div>
      <h2 className="mb-2 mt-6 text-sm font-semibold">Indented against the approved sheet</h2>
      <DataTable label="Indented against the sheet" rows={rows} columns={cols} rowKey={(r) => r.item_id} />
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

/** Making or changing the sheet in the app: a group code from the BOQ, an item from the master, the quantity. */
function Editor({ s, onDone, problems, setProblems }: { s: ItemSheet; onDone: () => void; problems: string[]; setProblems: (p: string[]) => void }) {
  const [rows, setRows] = useState<Draft[]>(() => (s.lines.length
    ? s.lines.map((l) => ({ group_code: l.group_code, item: asOption(l), qty: String(l.qty), remarks: l.remarks, hsn: l.hsn }))
    : [blank(s.groups[0])]))
  const set = (i: number, patch: Partial<Draft>) => setRows((r) => r.map((x, n) => (n === i ? { ...x, ...patch } : x)))
  const save = useAction(
    () => saveItemSheet(s.job_id, rows.map((r) => ({ group_code: r.group_code, item_code: r.item?.code ?? '', qty: r.qty === '' ? null : Number(r.qty), remarks: r.remarks }))),
    { invalidate: [itemSheetKeys.one(s.job_id), itemSheetKeys.all],
      success: (r) => (r.approved ? 'Saved. It needs the Master\'s approval again; the approved one stays in force till then.' : 'Saved. Send it to the Master for approval when it is complete.'),
      onSuccess: () => { setProblems([]); onDone() },
      onError: (e) => setProblems(e instanceof ApiError ? e.detail.split('\n').slice(1) : []) },
  )
  const groups = s.groups.map((g) => ({ value: g, label: g }))
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <p className="text-sm text-muted-foreground">
          Each line: a group code from the project's BOQ, an item from the item master (its HSN and unit come from there), and the quantity in the item's unit. The same item may be under more than one group code.
        </p>
        <Problems list={problems} />
        <div className="space-y-3">
          {rows.map((r, i) => (
            <div key={i} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[8rem_minmax(0,1fr)] xl:grid-cols-[8rem_minmax(18rem,2fr)_8rem_minmax(0,1fr)_auto]">
              <Field label="Group code" htmlFor={`is-g-${i}`}><Select id={`is-g-${i}`} options={groups} placeholder="Choose" value={r.group_code} onChange={(e) => set(i, { group_code: e.target.value })} /></Field>
              <Field label="Item" htmlFor={`is-i-${i}`}><ItemPicker id={`is-i-${i}`} value={r.item} onChange={(item) => set(i, { item, hsn: '' })} /></Field>
              <Field label={`Quantity${r.item?.base_uom ? ` (${r.item.base_uom})` : ''}`} htmlFor={`is-q-${i}`}>
                <Input id={`is-q-${i}`} inputMode="decimal" value={r.qty} onChange={(e) => set(i, { qty: e.target.value.replace(/[^\d.]/g, '') })} />
              </Field>
              <Field label="Remarks" htmlFor={`is-r-${i}`}><Input id={`is-r-${i}`} value={r.remarks} onChange={(e) => set(i, { remarks: e.target.value })} /></Field>
              <div className="flex items-end justify-between gap-2 sm:col-span-2 xl:col-span-1">
                {r.hsn && <span className="pb-2 text-xs text-muted-foreground">HSN {r.hsn}</span>}
                <Button variant="ghost" size="icon" aria-label={`Remove line ${i + 1}`} onClick={() => setRows((x) => (x.length > 1 ? x.filter((_, n) => n !== i) : [blank(s.groups[0])]))}><Trash2 /></Button>
              </div>
            </div>
          ))}
        </div>
        <Button variant="outline" onClick={() => setRows((x) => [...x, blank(x[x.length - 1]?.group_code ?? s.groups[0])])}><Plus /> Add line</Button>
      </Card>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" onClick={() => { setProblems([]); onDone() }}>Cancel</Button>
        <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
      </div>
    </div>
  )
}
