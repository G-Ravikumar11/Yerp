import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Download, FileUp, GitBranch, Save, ShoppingCart } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataGrid, type Column } from '@/components/grid'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Stat, StatGrid, Tabs, Textarea } from '@/components/ui'
import {
  boqKeys,
  importBoq,
  makeClientOrder,
  newRevision,
  saveBoqLines,
  useBoq,
  useBoqChanges,
  useTracker,
  type BoqFlag,
  type BoqKind,
  type BoqLine,
  type TrackerRow,
} from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatQty } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

/** A line as the grid holds it: figures may be blank. */
interface Row {
  key: string
  kind: BoqKind
  sno: string
  description: string
  uom: string
  quantity: number | null
  rate: number | null
  code: string
  item_code: string
  remarks: string
}

const blank = (): Row => ({ key: '', kind: 'item', sno: '', description: '', uom: '', quantity: null, rate: null, code: '', item_code: '', remarks: '' })
const fromLines = (lines: BoqLine[]): Row[] => lines.map((l) => ({ key: l.key, kind: l.kind, sno: l.sno, description: l.description, uom: l.uom, quantity: l.kind === 'section' || l.kind === 'note' ? null : l.quantity, rate: l.kind === 'section' || l.kind === 'note' ? null : l.rate, code: l.code, item_code: l.item_code, remarks: l.remarks }))
const priced = (r: Row) => r.kind === 'item' || r.kind === 'sub'
const amountOf = (r: Row) => (priced(r) && r.quantity && r.rate ? Math.round(r.quantity * r.rate * 100) / 100 : null)

/**
 * What the server is sent. A row with words but no quantity and no rate is a heading, not an item at nought -
 * which is what a pasted section title would otherwise become.
 */
const payload = (rows: Row[]) =>
  rows
    .filter((r) => r.description.trim())
    .map((r) => ({ ...r, kind: priced(r) && !r.quantity && !r.rate ? ('section' as BoqKind) : r.kind, quantity: r.quantity ?? 0, rate: r.rate ?? 0 }))

const KINDS = [
  { value: 'section', label: 'Section' },
  { value: 'item', label: 'Item' },
  { value: 'sub', label: 'Sub-item' },
  { value: 'note', label: 'Note' },
]

const FLAG_TEXT: Record<BoqFlag, string> = { no_gang: 'No gang yet', over_allotted: 'Given past the BOQ', loss: 'Gang rate above ours', over_executed: 'Executed past the BOQ' }

type Tab = 'boq' | 'tracker' | 'revisions'

export default function BoqPage() {
  const id = Number(useParams().id)
  const { can } = useSession()
  const [tab, setTab] = useState<Tab>('boq')
  const [viewing, setViewing] = useState<number | undefined>(undefined)
  const book = useBoq(id, viewing)
  const tracker = useTracker(id, tab === 'tracker')
  const [rows, setRows] = useState<Row[]>([])
  const [dirty, setDirty] = useState(false)
  const [issue, setIssue] = useState(true)
  const [revising, setRevising] = useState(false)
  const [ordering, setOrdering] = useState(false)
  const [label, setLabel] = useState('')
  const [note, setNote] = useState('')
  const [reference, setReference] = useState('')
  const [compare, setCompare] = useState(0)
  const file = useRef<HTMLInputElement>(null)
  const changes = useBoqChanges(id, compare, tab === 'revisions')

  // What is on screen follows the server until the person starts changing it.
  useEffect(() => {
    if (book.data && !dirty) setRows(fromLines(book.data.lines))
  }, [book.data, dirty])

  const editable = !!book.data?.editable && can('workorders.manage')
  const edit = (next: Row[]) => {
    setRows(next)
    setDirty(true)
  }

  const save = useAction(() => saveBoqLines(id, payload(rows), issue), {
    invalidate: [boqKeys.all],
    success: (r) => r.message,
    onSuccess: (r) => {
      setDirty(false)
      setRows(fromLines(r.lines))
    },
  })
  const read = useAction((f: File) => importBoq(id, f), {
    onSuccess: (r) => {
      edit(fromLines(r.lines))
      toast.success(r.message)
      r.warnings.forEach((w) => toast.info(w))
    },
  })
  const revise = useAction(() => newRevision(id, label.trim(), note.trim()), {
    invalidate: [boqKeys.all],
    success: (r) => r.message,
    onSuccess: () => {
      setRevising(false)
      setViewing(undefined)
      setDirty(false)
    },
  })
  const order = useAction(() => makeClientOrder(id, reference.trim()), { invalidate: [boqKeys.all, ['clientorders']], success: (r) => r.message, onSuccess: () => setOrdering(false) })

  const columns = useMemo<Column<Row>[]>(
    () => [
      { id: 'sno', header: 'S.No', width: 84, mono: true, pin: true, placeholder: '1.1' },
      { id: 'description', header: 'Description', hint: 'Paste the client’s lines here', width: 420, required: true, placeholder: 'What is the work?' },
      { id: 'uom', header: 'Unit', type: 'select', freeText: true, width: 84, options: ['cum', 'sqm', 'rmt', 'nos', 'kg', 'MT', 'ltr', 'LS'], readOnly: (r) => !priced(r) },
      { id: 'quantity', header: 'Quantity', type: 'number', decimals: 3, width: 112, readOnly: (r) => !priced(r), validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null) },
      { id: 'rate', header: 'Rate', hint: '₹ per unit', type: 'number', decimals: 2, width: 112, readOnly: (r) => !priced(r), validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null) },
      { id: 'amount', header: 'Amount', type: 'number', width: 140, readOnly: true, get: (r) => amountOf(r), format: (v) => (typeof v === 'number' ? formatINR(v) : ''), summary: 'sum' },
      { id: 'kind', header: 'Kind', type: 'select', width: 110, options: KINDS, countsAsData: false },
      { id: 'item_code', header: 'Item code', hint: 'Given on save', width: 120, mono: true, readOnly: true },
      { id: 'code', header: 'Client code', width: 110, mono: true },
    ],
    [],
  )

  const head = book.data?.boq
  const noCode = rows.filter((r) => priced(r) && r.description.trim() && !r.item_code).length

  return (
    <>
      <PageHeader
        eyebrow="BOQ"
        title={head ? `${head.number} - ${head.project}` : 'BOQ'}
        description={head ? `${head.revision}${head.status === 'ISSUED' ? ' (issued, read only)' : ''} · ${head.customer || head.title}` : undefined}
        actions={
          head && (
            <>
              <Button variant="outline" asChild>
                <a href={`/api/boqs/${id}/export.xlsx${viewing === undefined ? '' : `?rev=${viewing}`}`}>
                  <Download /> Excel
                </a>
              </Button>
              <Button variant="outline" asChild>
                <a href={`/api/boqs/${id}/export.pdf${viewing === undefined ? '' : `?rev=${viewing}`}`} target="_blank" rel="noopener">
                  PDF
                </a>
              </Button>
              {can('workorders.manage') && viewing === undefined && (
                <Button variant="outline" onClick={() => setRevising(true)}>
                  <GitBranch /> New revision
                </Button>
              )}
              {can('workorders.manage') && viewing === undefined && (
                <Button variant="outline" onClick={() => setOrdering(true)}>
                  <ShoppingCart /> Client work order
                </Button>
              )}
            </>
          )
        }
      />

      <StatGrid className="mb-5">
        <Stat label="BOQ value" value={compactINR(book.data?.total)} loading={book.isPending} />
        <Stat label="Priced lines" value={head?.items ?? 0} loading={book.isPending} />
        <Stat label="Revision" value={head?.revision ?? '-'} loading={book.isPending} />
        <Stat label="Without an item code" value={noCode} tone={noCode ? 'warning' : undefined} loading={book.isPending} />
      </StatGrid>

      <div className="mb-4 max-w-md">
        <Tabs
          label="BOQ views"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'boq', label: 'BOQ' },
            { value: 'tracker', label: 'Tracker' },
            { value: 'revisions', label: 'Revisions', count: book.data?.revisions.length },
          ]}
        />
      </div>

      {tab === 'boq' && (
        <div>
          {editable && viewing === undefined && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <input
                ref={file}
                type="file"
                hidden
                accept=".xlsx,.csv"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ''
                  if (f) read.mutate(f)
                }}
              />
              <Button variant="outline" size="sm" loading={read.isPending} onClick={() => file.current?.click()}>
                <FileUp /> Import the client&apos;s sheet
              </Button>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={issue} onChange={(e) => setIssue(e.target.checked)} className="size-4 accent-[var(--primary)]" />
                Give new lines item codes
              </label>
              <Button size="sm" loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
                <Save /> Save the BOQ
              </Button>
              {dirty && <Badge tone="warning">Unsaved changes</Badge>}
              <span className="text-xs text-muted-foreground">Paste lines straight from Excel (S.No, Description, Unit, Qty, Rate). A line with no quantity or rate is saved as a heading.</span>
            </div>
          )}
          {!editable && viewing !== undefined && (
            <p className="mb-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[13px]">
              You are looking at {head?.revision}, as it was issued. <button type="button" className="font-medium text-primary underline underline-offset-4" onClick={() => setViewing(undefined)}>Back to the current revision</button>
            </p>
          )}
          <DataGrid
            aria-label="Bill of quantities"
            columns={columns}
            rows={rows}
            onRowsChange={edit}
            newRow={blank}
            readOnly={!editable}
            autoGrow={editable}
            minRows={editable ? 12 : 0}
            maxHeight={620}
            rowClassName={(r) => (r.kind === 'section' ? 'font-semibold bg-surface/60' : r.kind === 'note' ? 'italic text-muted-foreground' : undefined)}
            emptyText="Nothing in the BOQ yet."
          />
        </div>
      )}

      {tab === 'tracker' && <TrackerView rows={tracker.data?.rows ?? []} flags={tracker.data?.flags} totals={tracker.data?.totals} loading={tracker.isPending} denied={tracker.isError} />}

      {tab === 'revisions' && (
        <div className="grid gap-5">
          <DataTable
            label="Revisions"
            rows={book.data?.revisions ?? []}
            rowKey={(r) => r.rev_no}
            columns={[
              { id: 'rev', header: 'Revision', cell: (r) => <span className="font-semibold">{r.label}</span> },
              { id: 'status', header: 'Status', cell: (r) => <Badge tone={r.status === 'OPEN' ? 'warning' : 'success'}>{r.status === 'OPEN' ? 'Being edited' : 'Issued'}</Badge> },
              { id: 'note', header: 'Note', hideBelow: 'md', cell: (r) => r.note || '-' },
              { id: 'by', header: 'By', hideBelow: 'lg', cell: (r) => r.created_by_name },
              {
                id: 'act',
                header: '',
                align: 'right',
                cell: (r) => (
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => { setViewing(r.rev_no === book.data?.boq.current_rev ? undefined : r.rev_no); setTab('boq'); setDirty(false) }}>
                      View
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setCompare(r.rev_no)}>
                      Changes since
                    </Button>
                  </div>
                ),
              },
            ]}
          />
          <div>
            <h2 className="mb-2 text-lg font-semibold">
              What changed since {changes.data?.from ?? 'that revision'}
              {changes.data && <span className="ml-2 text-sm font-normal text-muted-foreground">to {changes.data.to}: {formatINR(changes.data.difference)}</span>}
            </h2>
            <DataTable
              label="Changes between revisions"
              rows={changes.data?.changes ?? []}
              rowKey={(c) => c.change + c.line}
              loading={changes.isPending}
              empty="Nothing has changed."
              columns={[
                { id: 'what', header: 'Change', width: '7rem', cell: (c) => <Badge tone={c.change === 'added' ? 'success' : c.change === 'removed' ? 'danger' : 'warning'}>{c.change}</Badge> },
                { id: 'line', header: 'Line', cell: (c) => c.line },
                { id: 'detail', header: 'Detail', hideBelow: 'md', cell: (c) => c.detail ?? '' },
                { id: 'amt', header: 'Value', align: 'right', cell: (c) => formatINR(c.amount) },
              ]}
            />
          </div>
        </div>
      )}

      <Modal
        open={revising}
        onOpenChange={setRevising}
        title="Start a new revision"
        description={`${head?.revision ?? 'This revision'} is issued and locked as it stands; the next one opens as a copy to change.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevising(false)}>Cancel</Button>
            <Button loading={revise.isPending} onClick={() => dirty ? toast.error('Save the BOQ first.') : revise.mutate()}>Issue and start the next</Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Field label="Name of the next revision" htmlFor="rev-label"><Input id="rev-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={`R${(head?.current_rev ?? 0) + 1} - After variations`} /></Field>
          <Field label="Why" htmlFor="rev-note"><Textarea id="rev-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} /></Field>
        </div>
      </Modal>

      <Modal
        open={ordering}
        onOpenChange={setOrdering}
        title="Make the client's work order"
        description="One order for the project, drawn from this BOQ: its priced lines in their item codes, at the client's rates. Lines need item codes first."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOrdering(false)}>Cancel</Button>
            <Button loading={order.isPending} onClick={() => (dirty ? toast.error('Save the BOQ first.') : order.mutate())}>Create the order</Button>
          </>
        }
      >
        <Field label="The client's order number" htmlFor="co-ref" hint="Optional. Printed on every bill raised against the order."><Input id="co-ref" value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
      </Modal>
    </>
  )
}

function TrackerView({ rows, flags, totals, loading, denied }: { rows: TrackerRow[]; flags?: Record<BoqFlag, number>; totals?: { value: number; given_cost: number; client_billed: number; gang_billed: number }; loading: boolean; denied: boolean }) {
  if (denied) return <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">The tracker shows the gang rates against ours, so it is for those who see the reports.</p>
  const columns: TableColumn<TrackerRow>[] = [
    { id: 'sno', header: 'S.No', width: '5rem', cell: (r) => <span className={cn('font-mono text-xs', r.kind === 'section' && 'font-semibold')}>{r.sno}</span> },
    { id: 'd', header: 'Description', cell: (r) => (r.kind === 'section' ? <span className="font-semibold">{r.description}</span> : <div className="max-w-sm truncate" title={r.description}>{r.description}</div>) },
    { id: 'qty', header: 'BOQ qty', align: 'right', cell: (r) => (r.kind === 'section' ? '' : `${formatQty(r.quantity ?? 0)} ${r.uom ?? ''}`) },
    { id: 'rate', header: 'Our rate', align: 'right', hideBelow: 'md', cell: (r) => (r.kind === 'section' ? '' : formatINR(r.rate ?? 0)) },
    { id: 'given', header: 'Given to gangs', align: 'right', cell: (r) => (r.kind === 'section' ? '' : <span title={(r.orders ?? []).join(', ')}>{formatQty(r.given ?? 0)}</span>) },
    { id: 'grate', header: 'Gang rate', align: 'right', hideBelow: 'lg', cell: (r) => (r.kind === 'section' || !r.given ? '' : formatINR(r.gang_rate ?? 0)) },
    { id: 'margin', header: 'Margin', align: 'right', hideBelow: 'lg', cell: (r) => (r.margin_percent == null ? '' : <span className={r.margin_percent < 0 ? 'font-medium text-danger' : ''}>{r.margin_percent}%</span>) },
    { id: 'done', header: 'Executed', align: 'right', hideBelow: 'md', cell: (r) => (r.kind === 'section' ? '' : `${formatQty(Math.max(r.executed ?? 0, r.client_executed ?? 0))} (${r.percent_done ?? 0}%)`) },
    { id: 'gb', header: 'Gangs billed', align: 'right', hideBelow: 'xl', cell: (r) => (r.kind === 'section' ? '' : formatQty(r.gang_billed ?? 0)) },
    { id: 'cb', header: 'Client billed', align: 'right', hideBelow: 'xl', cell: (r) => (r.kind === 'section' ? '' : formatQty(r.client_billed ?? 0)) },
    { id: 'flags', header: 'Look at', cell: (r) => <div className="flex flex-wrap gap-1">{(r.flags ?? []).map((f) => <Badge key={f} tone={f === 'no_gang' ? 'neutral' : 'danger'}>{FLAG_TEXT[f]}</Badge>)}</div> },
  ]
  return (
    <div className="grid gap-4">
      <StatGrid>
        <Stat label="No gang yet" value={flags?.no_gang ?? 0} tone={flags?.no_gang ? 'warning' : undefined} loading={loading} />
        <Stat label="Given past the BOQ" value={flags?.over_allotted ?? 0} tone={flags?.over_allotted ? 'danger' : undefined} loading={loading} />
        <Stat label="Gang rate above ours" value={flags?.loss ?? 0} tone={flags?.loss ? 'danger' : undefined} loading={loading} />
        <Stat label="Executed past the BOQ" value={flags?.over_executed ?? 0} tone={flags?.over_executed ? 'danger' : undefined} loading={loading} />
        <Stat label="Cost of what gangs have" value={compactINR(totals?.given_cost)} loading={loading} />
      </StatGrid>
      <DataTable label="BOQ tracker" rows={rows} columns={columns} rowKey={(r) => (r.key ?? r.kind) + r.sno + r.description} loading={loading} empty="Nothing to track yet. Save the BOQ, then give its lines to gangs." rowClassName={(r) => (r.kind === 'section' ? 'bg-surface/60' : undefined)} />
    </div>
  )
}
