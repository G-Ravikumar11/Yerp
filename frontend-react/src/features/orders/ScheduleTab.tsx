import { useMemo, useRef, useState } from 'react'
import { FileUp, Landmark, Layers, ListTree } from 'lucide-react'
import { DataGrid, type Column } from '@/components/grid'
import { Badge, Button, ConfirmDialog, Select } from '@/components/ui'
import { chargeBudget, importSchedule, orderKeys, type Order, type OrderItem, type Vocabulary } from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'
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
}

export const blankLine = (): LineRow => ({ activity_no: '', item_code: '', item_description: '', technical_spec: '', uom: '', quantity: null, unit_rate: null, tolerance_percent: null, budget_id: '', is_header: false, boq_key: '' })

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
    }))

const amount = (r: LineRow) => (r.is_header || !r.quantity || !r.unit_rate ? null : Math.round(r.quantity * r.unit_rate * 100) / 100)

/**
 * The schedule of quantities: what the gang is to build, in what quantity, at
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
}) {
  const budgets = order.budgets ?? []
  const file = useRef<HTMLInputElement>(null)
  const [chargeTo, setChargeTo] = useState('')
  const [pending, setPending] = useState<File | null>(null)
  const [picking, setPicking] = useState(false)

  const columns = useMemo<Column<LineRow>[]>(
    () => [
      { id: 'activity_no', header: 'Activity', hint: 'No.', width: 88, mono: true, pin: true, placeholder: '1.0' },
      { id: 'item_code', header: 'Item code', hint: 'Shown in the Measurement Book', width: 120, mono: true, placeholder: 'STR001' },
      { id: 'item_description', header: 'Description of work', hint: 'What the contractor is to do', width: 400, required: true, placeholder: 'What is the work?' },
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
        get: (r) => amount(r),
        format: (v) => (typeof v === 'number' ? formatINR(v) : ''),
        summary: 'sum',
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
    ],
    [vocab, budgets],
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
            uom: l.uom ?? '',
            quantity: l.quantity ?? null,
            unit_rate: l.unit_rate ?? null,
          })),
        )
      },
    },
  )

  const charge = useAction(() => chargeBudget(order.id, Number(chargeTo), false), { invalidate: [orderKeys.all], success: (r) => r.message, onSuccess: onCharged })

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
            <Button variant="outline" size="sm" loading={read.isPending} onClick={() => file.current?.click()}>
              <FileUp /> Import from Excel
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <a href="/api/wo/boq/template">Template</a>
            </Button>
            {order.job_id ? (
              <Button variant="outline" size="sm" onClick={() => setPicking(true)}>
                <ListTree /> From the project BOQ
              </Button>
            ) : null}
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
        rowClassName={(r) => (r.is_header ? 'font-semibold bg-surface/50' : undefined)}
        emptyText="There are no lines on this order."
      />
      <BoqPicker
        orderId={order.id}
        jobId={order.job_id ?? 0}
        open={picking}
        onOpenChange={setPicking}
        onAdd={(added) => onRows([...rows.filter((r) => r.item_description.trim()), ...added.map((l) => ({ ...blankLine(), ...l }) as LineRow)])}
      />
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
