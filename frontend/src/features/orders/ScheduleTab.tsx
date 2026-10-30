import { useMemo, useRef, useState } from 'react'
import { FileUp, Landmark, Layers, ListOrdered, ListTree, Merge, Sigma, Split } from 'lucide-react'
import { DataGrid, type Column } from '@/components/grid'
import { Badge, Button, ConfirmDialog, Field, Modal, Select } from '@/components/ui'
import { chargeBudget, importSchedule, orderKeys, type Order, type OrderItem, type Vocabulary } from '@/api/orders'
import { arrangeSchedule, cumulativeSchedule, type ScheduleRow } from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { cn, formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'
import { ApiError } from '@/lib/api'
import { BoqPicker } from './BoqPicker'

/** One line of the schedule as it is edited: numbers may be blank, the cost centre is a choice by id. */
export interface LineRow {
  activity_no: string
  item_code: string
  item_description: string
  technical_spec: string
  uom: string
  quantity: number | null
  unit_rate: number | null
  tolerance_percent: number | null
  budget_id: string
  is_header: boolean
  /** The line of the project BOQ it came from. */
  boq_key: string
  /** A line for a whole heading: the BOQ lines it adds up. */
  boq_parts: { key: string; qty: number }[]
  /** The grade or material the BOQ gives it (M60, Fe550). */
  material: string
  /** A heading: 1 a main heading, 2 the sub-heading under it. */
  heading_level: number
}

const blankLine = (): LineRow => ({
  activity_no: '',
  item_code: '',
  item_description: '',
  technical_spec: '',
  uom: '',
  quantity: null,
  unit_rate: null,
  tolerance_percent: null,
  budget_id: '',
  is_header: false,
  boq_key: '',
  boq_parts: [],
  material: '',
  heading_level: 0,
})

/** A line the server laid out, as the sheet holds it. With one cost centre on the order, a line without one is charged to it. */
const fromServer = (r: ScheduleRow, onlyBudget: string): LineRow => ({
  ...blankLine(),
  activity_no: r.activity_no ?? '',
  item_code: r.item_code ?? '',
  item_description: r.item_description ?? '',
  technical_spec: r.technical_spec ?? '',
  uom: r.uom ?? '',
  quantity: r.is_header ? null : (r.quantity ?? null),
  unit_rate: r.is_header ? null : (r.unit_rate ?? null),
  tolerance_percent: r.tolerance_percent || null,
  budget_id: r.budget_id ? String(r.budget_id) : r.is_header ? '' : onlyBudget,
  is_header: !!r.is_header,
  boq_key: r.boq_key ?? '',
  boq_parts: r.boq_parts ?? [],
  material: r.material ?? '',
  heading_level: r.heading_level ?? 0,
})

export const linesFrom = (o: Order): LineRow[] =>
  (o.items ?? []).map((i) => ({
    activity_no: i.activity_no,
    item_code: i.item_code,
    item_description: i.item_description,
    technical_spec: i.technical_spec,
    uom: i.uom,
    quantity: i.is_header ? null : i.quantity,
    unit_rate: i.is_header ? null : i.unit_rate,
    tolerance_percent: i.tolerance_percent || null,
    budget_id: i.budget_id ? String(i.budget_id) : '',
    is_header: i.is_header,
    boq_key: i.boq_key ?? '',
    boq_parts: i.boq_parts ?? [],
    material: i.material ?? '',
    heading_level: i.heading_level ?? 0,
  }))

/** What the server takes: every line with a description, numbers filled in, the cost centre as an id. */
export const toPayload = (rows: LineRow[]): Partial<OrderItem>[] =>
  rows
    .filter((r) => r.item_description.trim())
    .map((r) => ({
      activity_no: r.activity_no,
      item_code: r.item_code,
      item_description: r.item_description.trim(),
      technical_spec: r.technical_spec,
      uom: r.uom,
      quantity: r.is_header ? 0 : (r.quantity ?? 0),
      unit_rate: r.is_header ? 0 : (r.unit_rate ?? 0),
      tolerance_percent: r.is_header ? 0 : (r.tolerance_percent ?? 0),
      budget_id: r.is_header || !r.budget_id ? null : Number(r.budget_id),
      is_header: r.is_header,
      boq_key: r.boq_key || '',
      boq_parts: r.boq_parts ?? [],
      material: r.is_header ? '' : r.material || '',
      heading_level: r.is_header ? r.heading_level || 1 : 0,
    }))

const amount = (r: LineRow) => (r.is_header || !r.quantity || !r.unit_rate ? null : Math.round(r.quantity * r.unit_rate * 100) / 100)

/** What each heading adds up to, as the sheet would show it: the lines under it, down to the next heading as high as it. */
export function headingTotals(rows: LineRow[]): (number | null)[] {
  return rows.map((r, i) => {
    if (!r.is_header) return null
    const level = r.heading_level || 1
    let sum = 0
    for (let j = i + 1; j < rows.length; j++) {
      const o = rows[j]
      if (o.is_header && (o.heading_level || 1) <= level) break
      sum += amount(o) ?? 0
    }
    return Math.round(sum * 100) / 100
  })
}

/**
 * The schedule of quantities: what the contractor is to build, in what quantity, at
 * what rate, and which cost centre pays for it. Edited as a sheet; saved as a
 * whole. A line can be a heading, which prices and measures nothing.
 */
export function ScheduleTab({
  order,
  rows,
  onRows,
  disabled,
  vocab,
  onCostCentre,
  dirty,
  onCharged,
  startPicking = false,
  onPicked,
}: {
  order: Order
  rows: LineRow[]
  onRows: (rows: LineRow[]) => void
  disabled: boolean
  vocab: Vocabulary | undefined
  onCostCentre: () => void
  dirty: boolean
  /** The server changed the lines (their cost centres): start the form again from what it now holds. */
  onCharged: () => void
  /** Open the BOQ picker straight away: the order was just opened on a project with a BOQ. */
  startPicking?: boolean
  onPicked?: () => void
}) {
  const budgets = order.budgets ?? []
  const file = useRef<HTMLInputElement>(null)
  const [chargeTo, setChargeTo] = useState('')
  const [pending, setPending] = useState<File | null>(null)
  const [picking, setPicking] = useState(startPicking)
  const [byHeading, setByHeading] = useState(false)
  const [combining, setCombining] = useState(false)
  const [level, setLevel] = useState('0')
  const [keepGrades, setKeepGrades] = useState(true)
  const offBoq = rows.filter((r) => !r.is_header && r.item_description.trim() && !r.boq_key && !r.boq_parts?.length).length
  const onlyBudget = budgets.length === 1 ? String(budgets[0].id) : ''
  const subtotals = useMemo(() => headingTotals(rows), [rows])

  const columns = useMemo<Column<LineRow>[]>(
    () => [
      { id: 'activity_no', header: 'Activity', hint: 'No.', width: 88, mono: true, pin: true, placeholder: '1.0' },
      { id: 'item_code', header: 'Item code', hint: 'Shown in the Measurement Book', width: 120, mono: true, placeholder: 'STR001' },
      { id: 'item_description', header: 'Description of work', hint: 'What the contractor is to do', width: 400, required: true, placeholder: 'What is the work?' },
      { id: 'material', header: 'Material', hint: 'Grade or material', width: 110, readOnly: (r) => r.is_header, placeholder: 'M25' },
      { id: 'technical_spec', header: 'Specification', hint: "The BOQ heading's text, or the line's own", width: 240 },
      { id: 'uom', header: 'Unit', type: 'select', freeText: true, width: 96, options: vocab?.uoms ?? [], readOnly: (r) => r.is_header },
      {
        id: 'quantity',
        header: 'Quantity',
        type: 'number',
        decimals: 3,
        width: 116,
        readOnly: (r) => r.is_header,
        validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null),
      },
      {
        id: 'unit_rate',
        header: 'Rate',
        hint: '₹ per unit',
        type: 'number',
        decimals: 2,
        width: 116,
        readOnly: (r) => r.is_header,
        validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null),
      },
      {
        id: 'amount',
        header: 'Amount',
        type: 'number',
        width: 150,
        readOnly: true,
        // A heading shows what the lines under it add up to; the total counts the lines only, once.
        get: (r, i) => (r.is_header ? (subtotals[i] ?? null) : amount(r)),
        format: (v) => (typeof v === 'number' ? formatINR(v) : ''),
        summary: (all) => formatINR(all.reduce((n, r) => n + (amount(r) ?? 0), 0)),
      },
      {
        id: 'tolerance_percent',
        header: 'Tolerance',
        hint: '% over allowed',
        type: 'number',
        decimals: 1,
        width: 108,
        readOnly: (r) => r.is_header,
        validate: (v) => ((v as number) < 0 || (v as number) > 100 ? '0 to 100' : null),
      },
      {
        id: 'budget_id',
        header: 'Cost centre',
        type: 'select',
        width: 190,
        readOnly: (r) => r.is_header,
        options: budgets.map((b) => ({ value: String(b.id), label: b.name || b.code })),
      },
      { id: 'is_header', header: 'Heading', type: 'checkbox', width: 84 },
      {
        id: 'against_boq',
        header: 'BOQ',
        hint: 'Against the project BOQ?',
        width: 110,
        readOnly: true,
        get: (r) => (r.is_header || !r.item_description.trim() ? '' : r.boq_parts?.length ? `${r.boq_parts.length} BOQ ${r.boq_parts.length === 1 ? 'line' : 'lines'}` : r.boq_key ? 'In BOQ' : 'Not in BOQ'),
      },
    ],
    [vocab, budgets, subtotals],
  )

  const read = useAction(
    async (f: File) => {
      const out = await importSchedule(order.id, f)
      return out
    },
    {
      success: (r) => r.message,
      onSuccess: (r) => {
        onRows(
          r.lines.map((l) => ({
            ...blankLine(),
            activity_no: l.activity_no ?? '',
            item_code: l.item_code ?? '',
            item_description: l.item_description ?? '',
            technical_spec: l.technical_spec ?? '',
            material: l.material ?? '',
            uom: l.uom ?? '',
            quantity: l.quantity ?? null,
            unit_rate: l.unit_rate ?? null,
          })),
        )
      },
    },
  )

  const charge = useAction(() => chargeBudget(order.id, Number(chargeTo), false), { invalidate: [orderKeys.all], success: (r) => r.message, onSuccess: onCharged })
  // The lines already on the schedule added up per heading, as one line each - or put back as their BOQ lines.
  const levels = Math.max(1, ...rows.filter((r) => r.is_header).map((r) => r.heading_level || 1))
  const fromBoq = rows.filter((r) => !r.is_header && (r.boq_key || r.boq_parts?.length)).length
  const totals = rows.filter((r) => !r.is_header && r.boq_parts?.length).length
  const combine = useAction(() => cumulativeSchedule(order.id, toPayload(rows), { level: Number(level), keep_grades: keepGrades }), {
    success: 'Added up per heading. The order value is unchanged.',
    onSuccess: (r) => {
      onRows(r.rows.map((x) => fromServer(x, onlyBudget)))
      setCombining(false)
    },
  })
  const split = useAction(() => cumulativeSchedule(order.id, toPayload(rows), { split: true }), {
    success: 'Put back as the BOQ lines',
    onSuccess: (r) => onRows(r.rows.map((x) => fromServer(x, onlyBudget))),
  })
  // In the BOQ's order under its headings, every line numbered again - as the sheet would be.
  const arrange = useAction(() => arrangeSchedule(order.id, toPayload(rows), true), {
    success: 'Laid out like the BOQ and numbered',
    onSuccess: (r) => onRows(r.rows.map((x) => fromServer(x, onlyBudget))),
  })

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {!disabled && (
          <>
            <input
              ref={file}
              type="file"
              hidden
              accept=".xlsx,.csv"
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (!f) return
                if (rows.some((r) => r.item_description.trim())) setPending(f)
                else read.mutate(f)
              }}
            />
            {order.job_id ? (
              <>
                <Button size="sm" onClick={() => { setByHeading(false); setPicking(true) }}>
                  <ListTree /> Add from the project BOQ
                </Button>
                <Button size="sm" variant="outline" title="Each heading of the BOQ as one line: its quantities added up, at one rate" onClick={() => { setByHeading(true); setPicking(true) }}>
                  <Sigma /> Add BOQ headings (cumulative)
                </Button>
              </>
            ) : (
              <span className="text-[13px] text-muted-foreground">Choose and save the project, then build this order from its BOQ.</span>
            )}
            <Button
              variant="outline"
              size="sm"
              loading={arrange.isPending}
              disabled={!rows.some((r) => r.item_description.trim())}
              title="Put the lines in the BOQ's order under their headings, add any heading that is missing, and number them all"
              onClick={() => arrange.mutate()}
            >
              <ListOrdered /> Arrange &amp; number
            </Button>
            {order.job_id ? (
              <Button
                variant="outline"
                size="sm"
                disabled={fromBoq < 2}
                title="Add up the BOQ lines already on the schedule into one line per heading - the order value stays the same"
                onClick={() => setCombining(true)}
              >
                <Merge /> Make cumulative
              </Button>
            ) : null}
            {totals > 0 && (
              <Button variant="ghost" size="sm" loading={split.isPending} title="Put each added-up line back as the BOQ lines it stands for" onClick={() => split.mutate()}>
                <Split /> Split into lines
              </Button>
            )}
            <Button variant="outline" size="sm" loading={read.isPending} onClick={() => file.current?.click()}>
              <FileUp /> Import from Excel
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <a href="/api/wo/boq/template">Template</a>
            </Button>
            <span className="mx-1 hidden h-5 w-px bg-border sm:block" aria-hidden />
            {order.job_id ? (
              <>
                <div className="w-44">
                  <Select aria-label="Cost centre for every line" value={chargeTo} onChange={(e) => setChargeTo(e.target.value)} placeholder="Charge every line to..." options={budgets.map((b) => ({ value: b.id, label: b.name || b.code }))} />
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  loading={charge.isPending}
                  disabled={!chargeTo}
                  onClick={() => {
                    if (dirty) return toast.error('Save the schedule first, then charge it to a cost centre.')
                    charge.mutate()
                  }}
                >
                  <Layers /> Charge
                </Button>
                <Button variant="ghost" size="sm" onClick={onCostCentre}>
                  <Landmark /> Set the budget
                </Button>
              </>
            ) : (
              <span className="text-[13px] text-muted-foreground">Choose and save the project to charge lines to its budget.</span>
            )}
          </>
        )}
        {order.job_id && offBoq > 0 && (
          <Badge tone="warning" title="These lines are not tied to a line of the project BOQ, so they are not counted against what the client's BOQ allows.">
            {offBoq} {offBoq === 1 ? 'line' : 'lines'} not against the BOQ
          </Badge>
        )}
        {dirty && !disabled && <Badge tone="warning">Unsaved changes</Badge>}
      </div>

      {budgets.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {budgets.map((b) => (
            <Badge key={b.id} tone={b.over ? 'danger' : 'neutral'} title={`Allocated ${formatINR(b.allocated)}; this order ${formatINR(b.this_order)}; committed elsewhere ${formatINR(b.committed)}`}>
              {b.name || b.code}: {formatINR(b.available)} left{b.over ? ' - overrun' : ''}
            </Badge>
          ))}
        </div>
      )}

      <DataGrid
        aria-label="Schedule of quantities"
        columns={columns}
        rows={rows}
        onRowsChange={(next) => onRows(next)}
        newRow={blankLine}
        readOnly={disabled}
        autoGrow={!disabled}
        minRows={disabled ? 0 : 8}
        maxHeight={520}
        rowClassName={(r) => (r.is_header ? cn('font-semibold', (r.heading_level || 1) > 1 ? 'bg-surface/30' : 'bg-surface/60') : undefined)}
        emptyText="There are no lines on this order."
      />
      <BoqPicker
        orderId={order.id}
        jobId={order.job_id ?? 0}
        open={picking}
        startMode={byHeading ? 'headings' : 'lines'}
        current={toPayload(rows) as Partial<ScheduleRow>[]}
        onOpenChange={(o) => { setPicking(o); if (!o) onPicked?.() }}
        onAdd={(laid) => onRows(laid.map((r) => fromServer(r, onlyBudget)))}
      />
      <Modal
        open={combining}
        onOpenChange={setCombining}
        title="Make the schedule cumulative"
        description="The BOQ lines on this schedule are added up into one line per heading, as in an Excel abstract. Each line keeps the BOQ lines it stands for, and its rate is set so the order's value stays the same. Different units are never added together. Nothing is saved until you save the schedule."
        footer={
          <>
            <Button variant="ghost" onClick={() => setCombining(false)}>
              Cancel
            </Button>
            <Button loading={combine.isPending} onClick={() => combine.mutate()}>
              <Merge /> Add up
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Field label="Add up under" htmlFor="cum-level">
            <Select
              id="cum-level"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              options={['Main headings (e.g. PLAIN CEMENT CONCRETE)', 'Sub-headings (e.g. Basement-02)', 'Third-level headings', 'Fourth-level headings']
                .slice(0, Math.max(2, levels))
                .map((label, i) => ({ value: String(i), label }))}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={keepGrades} onChange={(e) => setKeepGrades(e.target.checked)} />
            Keep each grade separate (M60 and M40 as their own lines)
          </label>
        </div>
      </Modal>
      <ConfirmDialog
        open={!!pending}
        onOpenChange={(o) => !o && setPending(null)}
        title="Replace the schedule on screen?"
        description="The workbook's lines take the place of what is here. Nothing is saved until you save the schedule."
        confirmLabel="Replace"
        onConfirm={() => {
          if (pending) read.mutate(pending)
          setPending(null)
        }}
      />
      {read.error instanceof ApiError && <p className="mt-2 text-sm text-danger">{read.error.message}</p>}
    </div>
  )
}
