import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Download, FileUp, GitBranch, Plus, Save, ShoppingCart } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataGrid, type Column } from '@/components/grid'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Stat, StatGrid, Tabs, Textarea } from '@/components/ui'
import {
  boqKeys,
  importBoq,
  makeClientOrder,
  newRevision,
  useBoqVariations,
  saveBoqLines,
  useBoq,
  useBoqChanges,
  useBoqMaterials,
  useBoqSummary,
  useTracker,
  type BoqFlag,
  type BoqKind,
  type BoqLine,
  type BoqSummary,
  type BoqSummarySection,
  type TrackerRow,
} from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatQty } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'
import { VariationDialog } from './VariationDialog'

/** A line as the grid holds it: figures may be blank. */
interface Row {
  key: string
  kind: BoqKind
  group_code: string
  description: string
  uom: string
  quantity: number | null
  rate: number | null
  item_code: string
  remarks: string
  material: string
  /** Rate agreed, quantity not known yet (R/o): no amount, and in no total. */
  rate_only: boolean
}

const blank = (): Row => ({ key: '', kind: 'item', group_code: '', description: '', uom: '', quantity: null, rate: null, item_code: '', remarks: '', material: '', rate_only: false })
const fromLines = (lines: BoqLine[]): Row[] => lines.map((l) => ({ key: l.key, kind: l.kind, group_code: l.group_code ?? '', description: l.description, uom: l.uom, quantity: l.kind === 'section' || l.kind === 'note' || l.rate_only ? null : l.quantity, rate: l.kind === 'section' || l.kind === 'note' ? null : l.rate, item_code: l.item_code, remarks: l.remarks, material: l.material ?? '', rate_only: !!l.rate_only }))
/**
 * What a row is, from what is in it - there is no Kind column to set. A row with a quantity, a rate or R/o is an item;
 * with only words it is a heading. A note, which can only come from an older BOQ, stays one.
 */
const kindOf = (r: Row): BoqKind => (r.kind === 'note' ? 'note' : r.quantity || r.rate || r.rate_only ? (r.kind === 'sub' ? 'sub' : 'item') : 'section')
const priced = (r: Row) => kindOf(r) === 'item' || kindOf(r) === 'sub'
const locked = (r: Row) => r.kind === 'note'
const amountOf = (r: Row) => (priced(r) && !r.rate_only && r.quantity && r.rate ? Math.round(r.quantity * r.rate * 100) / 100 : null)

/**
 * What the server is sent. A row with words but no quantity and no rate is a heading, not an item at nought -
 * which is what a pasted section title would otherwise become.
 */
const payload = (rows: Row[]) =>
  rows
    .filter((r) => r.description.trim())
    .map((r) => ({ ...r, kind: kindOf(r), quantity: r.rate_only ? 0 : (r.quantity ?? 0), rate: r.rate ?? 0 }))

const FLAG_TEXT: Record<BoqFlag, string> = { no_contractor: 'No contractor yet', over_allotted: 'Given past the BOQ', loss: 'Contractor rate above ours', over_executed: 'Executed past the BOQ' }

type Tab = 'boq' | 'summary' | 'tracker' | 'variations' | 'revisions'

/**
 * The group codes on offer. "Customize" at the end of the list takes any other; the codes already on this BOQ
 * are added to the list so a typed one comes back next time.
 */
const GROUP_CODES = ['SUB STRUCTURE WORKS', 'SUPER STRUCTURE WORKS', 'FINISHING WORKS', 'ELECTRICAL WORKS', 'PLUMBING WORKS', 'FIRE FIGHTING', 'HVAC']

const MATERIALS = ['M10', 'M20', 'M25', 'M30', 'M40', 'M60', 'Fe500', 'Fe550/550D', 'Ply wood', 'Steel', 'Cement']

export default function BoqPage() {
  const id = Number(useParams().id)
  const { can } = useSession()
  const [params] = useSearchParams()
  const [tab, setTab] = useState<Tab>(params.get('tab') === 'variations' ? 'variations' : 'boq')
  const [varying, setVarying] = useState<{ id: number | null } | null>(null)
  const [viewing, setViewing] = useState<number | undefined>(undefined)
  const [gst, setGst] = useState(18)
  const book = useBoq(id, viewing)
  const tracker = useTracker(id, tab === 'tracker')
  const summary = useBoqSummary(id, gst, tab === 'summary', viewing)
  const variations = useBoqVariations(id)
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

  // The listed codes, then any others this BOQ already uses, so a code typed once is on the list from then on.
  const groupOptions = useMemo(() => {
    const used = rows.map((r) => r.group_code.trim()).filter(Boolean)
    return Array.from(new Set([...GROUP_CODES, ...used]))
  }, [rows])

  // The standard list, then every material added on any BOQ before, then this sheet's own - so one added once is there next time.
  const known = useBoqMaterials()
  const materialOptions = useMemo(() => {
    const used = rows.map((r) => r.material.trim()).filter(Boolean)
    return Array.from(new Set([...MATERIALS, ...(known.data?.materials ?? []), ...used]))
  }, [rows, known.data])

  const columns = useMemo<Column<Row>[]>(
    () => [
      { id: 'group_code', header: 'Group code', hint: 'Pick one, or type your own', type: 'select', freeText: true, customLabel: 'Customize...', width: 190, pin: true, options: groupOptions },
      { id: 'item_code', header: 'Item code', hint: 'Type this work\u2019s item code (any pattern, e.g. CIV-RCC-25). It is kept everywhere. Blank: one is given on save.', width: 150, mono: true, placeholder: 'Type the code' },
      { id: 'description', header: 'Description', hint: 'Paste the client’s lines here', width: 420, required: true, placeholder: 'What is the work?' },
      { id: 'material', header: 'Material', hint: 'Grade or material: M40, Fe550/550D', type: 'select', freeText: true, customLabel: 'Add an item...', width: 130, options: materialOptions, readOnly: locked },
      { id: 'uom', header: 'Unit', type: 'select', freeText: true, width: 84, options: ['cum', 'sqm', 'rmt', 'nos', 'kg', 'MT', 'ltr', 'LS'], readOnly: locked },
      { id: 'quantity', header: 'Quantity', type: 'number', decimals: 3, width: 112, readOnly: (r) => locked(r) || r.rate_only, validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null) },
      { id: 'rate', header: 'Rate', hint: '₹ per unit', type: 'number', decimals: 2, width: 112, readOnly: locked, validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null) },
      { id: 'rate_only', header: 'R/o', hint: 'Rate only: rate agreed, quantity not yet known. Comes to nothing and is in no total.', type: 'checkbox', width: 64, readOnly: locked, countsAsData: false },
      { id: 'amount', header: 'Amount', type: 'number', width: 140, readOnly: true, get: (r) => amountOf(r), format: (v) => (typeof v === 'number' ? formatINR(v) : ''), summary: 'sum' },
      { id: 'remarks', header: 'Remarks', hint: 'Any note about the line', width: 260, placeholder: 'Remarks' },
    ],
    [groupOptions, materialOptions],
  )

  const head = book.data?.boq
  // The files are made from the saved BOQ: a download with changes still on screen would leave them out.
  const savedFirst = (e: React.MouseEvent) => {
    if (!dirty) return
    e.preventDefault()
    toast.error('Save the BOQ first, so the download has your changes in it.')
  }
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
                <a href={`/api/boqs/${id}/export.xlsx${viewing === undefined ? '' : `?rev=${viewing}`}`} onClick={savedFirst}>
                  <Download /> Excel
                </a>
              </Button>
              <Button variant="outline" asChild>
                <a href={`/api/boqs/${id}/export.pdf${viewing === undefined ? '' : `?rev=${viewing}`}`} target="_blank" rel="noopener" onClick={savedFirst}>
                  PDF
                </a>
              </Button>
              {can('workorders.manage') && viewing === undefined && (
                <Button variant="outline" onClick={() => setRevising(true)}>
                  <GitBranch /> New revision
                </Button>
              )}
              {can('workorders.create') && viewing === undefined && (
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
            { value: 'summary', label: 'Summary' },
            { value: 'tracker', label: 'Tracker' },
            { value: 'variations', label: 'Variations', count: variations.data?.summary.raised },
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
              <Button variant="ghost" size="sm" asChild>
                <a href="/api/boqs/sample.xlsx">
                  <Download /> Sample sheet
                </a>
              </Button>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={issue} onChange={(e) => setIssue(e.target.checked)} className="size-4 accent-[var(--primary)]" />
                Give new lines item codes
              </label>
              <Button size="sm" loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
                <Save /> Save the BOQ
              </Button>
              {dirty && <Badge tone="warning">Unsaved changes</Badge>}
              <span className="text-xs text-muted-foreground">Paste lines straight from Excel (Group code, Description, Unit, Qty, Rate). A line with no quantity or rate is saved as a heading.</span>
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
            rowClassName={(r) => (kindOf(r) === 'section' ? 'font-semibold bg-surface/60' : r.kind === 'note' ? 'italic text-muted-foreground' : undefined)}
            emptyText="Nothing in the BOQ yet."
          />
        </div>
      )}

      {tab === 'summary' && <SummaryView summary={summary.data} loading={summary.isPending} gst={gst} onGst={setGst} />}

      {tab === 'tracker' && <TrackerView rows={tracker.data?.rows ?? []} flags={tracker.data?.flags} totals={tracker.data?.totals} loading={tracker.isPending} denied={tracker.isError} />}

      {tab === 'variations' && (
        <div className="grid gap-4">
          <StatGrid>
            <Stat label="Awaiting approval" value={variations.data?.summary.awaiting_approval ?? 0} tone={variations.data?.summary.awaiting_approval ? 'warning' : undefined} loading={variations.isPending} />
            <Stat label="Approved, added to the BOQ" value={compactINR(variations.data?.summary.approved_value)} loading={variations.isPending} />
            <Stat label="Raised, not yet approved" value={compactINR(variations.data?.summary.pending_value)} loading={variations.isPending} />
          </StatGrid>
          <div>
            {can('workorders.manage') && viewing === undefined && (
              <Button onClick={() => setVarying({ id: null })}>
                <Plus /> New variation
              </Button>
            )}
          </div>
          <DataTable
            label="Variations"
            rows={variations.data?.variations ?? []}
            rowKey={(x) => x.id}
            loading={variations.isPending}
            onRowClick={(x) => setVarying({ id: x.id })}
            empty="No variations. Raise one when work runs past the BOQ or an item the BOQ never had is asked for."
            columns={[
              { id: 'no', header: 'Variation', width: '9rem', cell: (x) => <span className="font-mono text-[13px] font-semibold">{x.number.slice(x.number.lastIndexOf('/') + 1)}</span> },
              { id: 'why', header: 'Why', cell: (x) => <div className="max-w-sm truncate" title={x.reason}>{x.reason || '-'}</div> },
              { id: 'basis', header: 'Against', hideBelow: 'md', cell: (x) => x.basis_rev },
              { id: 'val', header: 'Adds', align: 'right', cell: (x) => <span className={cn('font-semibold', x.value < 0 && 'text-danger')}>{formatINR(x.value)}</span> },
              { id: 'st', header: 'Status', cell: (x) => <div><Badge tone={x.status === 'APPROVED' ? 'success' : x.status === 'SUBMITTED' ? 'warning' : x.status === 'CANCELLED' ? 'danger' : 'neutral'}>{x.status.toLowerCase()}</Badge>{x.status === 'SUBMITTED' && x.waiting_on && <div className="mt-1 text-xs text-muted-foreground">with {x.waiting_on}</div>}{x.applied_rev && <div className="mt-1 text-xs text-muted-foreground">made {x.applied_rev}</div>}</div> },
            ]}
          />
          <VariationDialog boqId={id} id={varying?.id ?? null} lines={book.data?.lines ?? []} open={!!varying} onOpenChange={(o) => !o && setVarying(null)} />
        </div>
      )}

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

/** The BOQ's front page: each section with what it comes to, then the total, the GST on it, and the total with GST. */
function SummaryView({ summary, loading, gst, onGst }: { summary?: BoqSummary; loading: boolean; gst: number; onGst: (v: number) => void }) {
  const sections: TableColumn<BoqSummarySection>[] = [
    { id: 'group', header: 'Group', width: '7rem', cell: (s) => <span className="font-mono text-xs font-semibold">{s.group_code}</span> },
    { id: 'title', header: 'Description', cell: (s) => <span className="font-medium">{s.title}</span> },
    { id: 'items', header: 'Items', align: 'right', hideBelow: 'md', cell: (s) => s.items },
    { id: 'ro', header: 'Rate only', align: 'right', hideBelow: 'md', cell: (s) => (s.rate_only ? <Badge tone="neutral">{s.rate_only} R/o</Badge> : '') },
    { id: 'amount', header: 'Amount', align: 'right', cell: (s) => <span className="font-semibold tabular">{formatINR(s.amount)}</span> },
  ]
  const money = (v?: number) => formatINR(v ?? 0)
  const left = summary?.rate_only_items ?? 0
  return (
    <div className="grid gap-5">
      <StatGrid>
        <Stat label="Total" value={compactINR(summary?.total)} loading={loading} />
        <Stat label={`GST @${summary?.gst_percent ?? gst}%`} value={compactINR(summary?.gst)} loading={loading} />
        <Stat label="Total incl. GST" value={compactINR(summary?.total_with_gst)} tone="success" loading={loading} />
        <Stat label="Rate-only items" value={left} tone={left ? 'warning' : undefined} loading={loading} />
      </StatGrid>
      <div className="flex items-center gap-2 text-[13px]">
        <label htmlFor="boq-gst" className="text-muted-foreground">GST rate</label>
        <Input id="boq-gst" type="number" min={0} max={100} step="0.5" value={gst} onChange={(e) => onGst(Math.min(100, Math.max(0, Number(e.target.value) || 0)))} className="w-24" />
        <span className="text-muted-foreground">%</span>
      </div>
      <div>
        <DataTable label="BOQ summary by section" rows={summary?.sections ?? []} columns={sections} rowKey={(s) => s.key + s.title} loading={loading} empty="Nothing in the BOQ yet. Add sections and items on the BOQ tab." />
        <dl className="mt-2 overflow-hidden rounded-lg border border-border text-sm">
          <div className="flex justify-between bg-success-soft px-4 py-2.5 font-semibold"><dt>TOTAL</dt><dd className="tabular">{money(summary?.total)}</dd></div>
          <div className="flex justify-between px-4 py-2.5"><dt>GST @{summary?.gst_percent ?? gst}%</dt><dd className="tabular">{money(summary?.gst)}</dd></div>
          <div className="flex justify-between bg-warning-soft px-4 py-2.5 font-bold"><dt>TOTAL incl. GST</dt><dd className="tabular">{money(summary?.total_with_gst)}</dd></div>
        </dl>
        {left > 0 && <p className="mt-2 text-xs text-muted-foreground">{left} rate-only item{left === 1 ? '' : 's'} (R/o) {left === 1 ? 'is' : 'are'} priced but not yet quantified, so {left === 1 ? 'it is' : 'they are'} in none of these figures.</p>}
      </div>
      {!!summary?.by_material.length && (
        <div>
          <h2 className="mb-2 text-sm font-semibold">By material or grade</h2>
          <DataTable
            label="BOQ by material"
            rows={summary.by_material}
            rowKey={(m) => m.material}
            columns={[
              { id: 'm', header: 'Material', cell: (m) => <span className="font-medium">{m.material}</span> },
              { id: 'n', header: 'Items', align: 'right', cell: (m) => m.items },
              { id: 'a', header: 'Amount', align: 'right', cell: (m) => <span className="tabular">{formatINR(m.amount)}</span> },
            ]}
          />
        </div>
      )}
    </div>
  )
}

function TrackerView({ rows, flags, totals, loading, denied }: { rows: TrackerRow[]; flags?: Record<BoqFlag, number>; totals?: { value: number; given_cost: number; client_billed: number; contractor_billed: number }; loading: boolean; denied: boolean }) {
  if (denied) return <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">The tracker shows the contractor rates against ours, so it is for those who see the reports.</p>
  const columns: TableColumn<TrackerRow>[] = [
    { id: 'group', header: 'Group', width: '6rem', cell: (r) => <span className={cn('font-mono text-xs', r.kind === 'section' && 'font-semibold')}>{r.group_code}</span> },
    { id: 'code', header: 'Item code', width: '7rem', cell: (r) => <span className="whitespace-nowrap font-mono text-xs">{r.item_code ?? ''}</span> },
    { id: 'd', header: 'Description', cell: (r) => (r.kind === 'section' ? <span className="font-semibold">{r.description}</span> : <div className="max-w-sm truncate" title={r.description}>{r.description}</div>) },
    { id: 'qty', header: 'BOQ qty', align: 'right', cell: (r) => (r.kind === 'section' ? '' : `${formatQty(r.quantity ?? 0)} ${r.uom ?? ''}`) },
    { id: 'rate', header: 'Our rate', align: 'right', hideBelow: 'md', cell: (r) => (r.kind === 'section' ? '' : formatINR(r.rate ?? 0)) },
    { id: 'given', header: 'Given to contractors', align: 'right', cell: (r) => (r.kind === 'section' ? '' : <span title={(r.orders ?? []).join(', ')}>{formatQty(r.given ?? 0)}</span>) },
    { id: 'grate', header: 'Contractor rate', align: 'right', hideBelow: 'lg', cell: (r) => (r.kind === 'section' || !r.given ? '' : formatINR(r.contractor_rate ?? 0)) },
    { id: 'margin', header: 'Margin', align: 'right', hideBelow: 'lg', cell: (r) => (r.margin_percent == null ? '' : <span className={r.margin_percent < 0 ? 'font-medium text-danger' : ''}>{r.margin_percent}%</span>) },
    { id: 'done', header: 'Executed', align: 'right', hideBelow: 'md', cell: (r) => (r.kind === 'section' ? '' : `${formatQty(Math.max(r.executed ?? 0, r.client_executed ?? 0))} (${r.percent_done ?? 0}%)`) },
    { id: 'gb', header: 'Contractors billed', align: 'right', hideBelow: 'xl', cell: (r) => (r.kind === 'section' ? '' : formatQty(r.contractor_billed ?? 0)) },
    { id: 'cb', header: 'Client billed', align: 'right', hideBelow: 'xl', cell: (r) => (r.kind === 'section' ? '' : formatQty(r.client_billed ?? 0)) },
    { id: 'flags', header: 'Look at', cell: (r) => <div className="flex flex-wrap gap-1">{(r.flags ?? []).map((f) => <Badge key={f} tone={f === 'no_contractor' ? 'neutral' : 'danger'}>{FLAG_TEXT[f]}</Badge>)}</div> },
  ]
  return (
    <div className="grid gap-4">
      <StatGrid>
        <Stat label="No contractor yet" value={flags?.no_contractor ?? 0} tone={flags?.no_contractor ? 'warning' : undefined} loading={loading} />
        <Stat label="Given past the BOQ" value={flags?.over_allotted ?? 0} tone={flags?.over_allotted ? 'danger' : undefined} loading={loading} />
        <Stat label="Contractor rate above ours" value={flags?.loss ?? 0} tone={flags?.loss ? 'danger' : undefined} loading={loading} />
        <Stat label="Executed past the BOQ" value={flags?.over_executed ?? 0} tone={flags?.over_executed ? 'danger' : undefined} loading={loading} />
        <Stat label="Cost of what contractors have" value={compactINR(totals?.given_cost)} loading={loading} />
      </StatGrid>
      <DataTable label="BOQ tracker" rows={rows} columns={columns} rowKey={(r) => (r.key ?? r.kind) + r.group_code + r.description} loading={loading} empty="Nothing to track yet. Save the BOQ, then give its lines to contractors." rowClassName={(r) => (r.kind === 'section' ? 'bg-surface/60' : undefined)} />
    </div>
  )
}
