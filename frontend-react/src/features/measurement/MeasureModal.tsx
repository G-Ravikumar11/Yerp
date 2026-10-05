import { useMemo, useState } from 'react'
import { DataGrid } from '@/components/grid'
import { Button, Field, Input, Modal, NumField, Tabs } from '@/components/ui'
import { batchUrl, mbKeys, recordUrl, type MbEntry, type MbLine } from '@/api/mb'
import { useSession } from '@/lib/session'
/** The work order as the window shows it: its number, who it is with, and where. */
export interface MeasureOrder {
  wo_number: string
  contractor: string
  project: string
}
import { blankDim, dimTotal, evalCalc, type DimLine } from '@/lib/measure'
import { formatQty, today } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { sendOrQueue } from '@/stores/offline'
import { toast } from '@/stores/toast'
import { dimColumns } from './dimensions'
import { ItemFacts } from './ItemFacts'
import { SheetFill, toDimLine } from './SheetFill'
import { SheetBlocks, type Loaded } from './SheetBlocks'

type Mode = 'dims' | 'total'

/**
 * Where a measurement goes. The subcontract book is keyed by `item_id` and counts blocks built alike;
 * the client book is keyed by `line_id`, has a witness, and takes the lines as they are.
 */
export interface MeasureTarget {
  url: string
  idKey: 'item_id' | 'line_id'
  client?: boolean
  /** Lists to refresh once it is recorded. */
  invalidate?: readonly (readonly unknown[])[]
}

const subTarget = (orderId: number): MeasureTarget => ({ url: recordUrl(orderId), idKey: 'item_id' })

/**
 * One measurement into the book: the dimension lines as they are written in
 * the field book, worked out as they are typed, or - for a count - just a
 * total. With no signal it is kept on the device and sent when one returns.
 */
export function MeasureModal({ orderId, order, jobCode, line, entry, onClose, target }: { orderId: number; order?: MeasureOrder; jobCode?: string; line: MbLine | null; /** An entry already in the book, to change its calculation. */ entry?: MbEntry | null; onClose: () => void; target?: MeasureTarget }) {
  return (
    <Modal open={!!line} onOpenChange={(o) => !o && onClose()} size="xl" title={line ? `${entry ? 'Change the measurement of' : 'Measure'} ${[line.item_code, line.activity_no].filter(Boolean).join(' ')} ${line.description}` : 'Measure'} description={line ? allowance(line, !!target?.client) : undefined}>
      {line && <MeasureForm key={`${line.item_id}-${entry?.id ?? 0}`} entry={entry ?? undefined} orderId={orderId} order={order} jobCode={jobCode} line={line} onClose={onClose} target={target ?? subTarget(orderId)} />}
    </Modal>
  )
}

const allowance = (l: MbLine, client: boolean) =>
  `${formatQty(l.measured_to_date)} of ${formatQty(l.ordered_qty)} ${l.uom ?? ''} measured` +
  (l.tolerance_percent ? `; up to ${formatQty(l.max_quantity)} allowed with ${l.tolerance_percent}% tolerance` : '') +
  (client ? '. Past that the work is a variation, raised from the book.' : '. Past that the order is amended.')

function MeasureForm({ orderId, order, jobCode, line, entry, onClose, target }: { orderId: number; order?: MeasureOrder; jobCode?: string; line: MbLine; entry?: MbEntry; onClose: () => void; target: MeasureTarget }) {
  const lined = entry?.dimensions.some((d) => !d.is_heading) ?? true
  const [mode, setMode] = useState<Mode>(lined ? 'dims' : 'total')
  const [dims, setDims] = useState<DimLine[]>(() => (entry && lined ? entry.dimensions.map((d) => toDimLine({ ...d, is_heading: !!d.is_heading })) : []))
  const [total, setTotal] = useState(entry && !lined ? Math.round((entry.quantity / (entry.multiplier || 1)) * 1000) / 1000 : 0)
  const [blocks, setBlocks] = useState(entry?.multiplier || 1)
  const [on, setOn] = useState(entry?.measured_on || today())
  const [ref, setRef] = useState(entry?.mb_ref ?? '')
  const [where, setWhere] = useState(entry?.location ?? '')
  const [remarks, setRemarks] = useState(entry?.remarks ?? '')
  const [calcLabel, setCalcLabel] = useState('')
  const [calcText, setCalcText] = useState('')
  const [witness, setWitness] = useState('')
  // Blocks loaded from a sheet, checked in the grid before anything is recorded.
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  // Part of what is measured held back from billing - for finishes and handing over, say - recorded with it.
  const { can } = useSession()
  const canHold = !target.client && !entry && can('billing.manage')
  const [holding, setHolding] = useState(false)
  const [holdBy, setHoldBy] = useState<'percent' | 'quantity'>('percent')
  const [holdPct, setHoldPct] = useState(5)
  const [holdQty, setHoldQty] = useState(0)
  const [holdWhy, setHoldWhy] = useState('Held back for finishes and handing over')

  const one = mode === 'dims' ? dimTotal(dims) : total
  const quantity = Math.round(one * blocks * 1000) / 1000
  const after = (line.measured_to_date ?? 0) - (entry?.quantity ?? 0) + quantity
  const over = quantity > 0 && after > (line.max_quantity ?? Infinity) + 0.0001
  const held = canHold && holding ? Math.round((holdBy === 'percent' ? (quantity * holdPct) / 100 : holdQty) * 1000) / 1000 : 0
  const holdBad = held < 0 || (held > 0 && held > quantity + 0.0001) || (held > 0 && !holdWhy.trim())

  const save = useAction(
    async () => {
      const body: Record<string, unknown> = {
        [target.idKey]: line.item_id,
        measured_on: on,
        mb_ref: ref,
        location: where,
        remarks,
        ...(target.client ? { witnessed_by: witness } : { multiplier: blocks }),
        ...(mode === 'dims'
          ? {
              dimensions: dims
                .filter((d) => d.particulars.trim() || [d.nos, d.nom, d.length, d.breadth, d.depth].some((v) => v !== null))
                .map((d) => ({ particulars: d.particulars, nos: d.nos, nom: d.nom, length: d.length, breadth: d.breadth, depth: d.depth, deduct: d.deduct, is_heading: d.heading })),
            }
          : { quantity: total }),
      }
      // With a hold, the measurement and its hold go in together, the hold tied to this entry so it prints under it.
      const withHold = held > 0
      const one = { location: where, multiplier: blocks, ...(mode === 'dims' ? { dimensions: body.dimensions } : { quantity: total }) }
      const sent = await sendOrQueue<{ message: string }>({
        method: entry ? 'PUT' : 'POST',
        url: entry ? `/api/sub-mb/entries/${entry.id}` : withHold ? batchUrl(orderId) : target.url,
        body: withHold
          ? { item_id: line.item_id, measured_on: on, mb_ref: ref, remarks, entries: [{ ...one, group: 'h' }], holds: [{ group: 'h', quantity: held, reason: holdWhy.trim() }] }
          : body,
        label: `${entry ? 'Changed' : 'Measured'} ${formatQty(quantity)} ${line.uom ?? ''} against ${line.activity_no}`.trim(),
      })
      if (sent.queued) {
        toast.info('No connection - kept on this device and sent when it returns.')
        return { message: '' }
      }
      return sent.result
    },
    { invalidate: [...(target.invalidate ?? [mbKeys.all, ['subbills']])], onSuccess: onClose },
  )

  const columns = useMemo(() => dimColumns, [])

  /** A custom calculation: worked out from what the lines come to, and kept as a line of its own. */
  const lineTotal = dimTotal(dims)
  const calc = calcText.trim() ? evalCalc(calcText, lineTotal) : null
  const addCalc = () => {
    if (calc === null || calc === 0) return
    const label = calcLabel.trim() || calcText.trim()
    setDims((rows) => [...rows.filter((r) => r.particulars.trim() || [r.nos, r.nom, r.length, r.breadth, r.depth].some((v) => v !== null)), { ...blankDim(), particulars: label, nos: Math.abs(calc), deduct: calc < 0 }])
    setCalcLabel('')
    setCalcText('')
  }

  const facts = (
    <div className="mb-4 rounded-lg border border-border bg-muted/40 p-3" aria-label="The work order being measured">
      {order && (
        <p className="mb-2 flex flex-wrap items-baseline gap-x-2 text-[13px]">
          <span className="font-mono font-semibold">{order.wo_number}</span>
          {jobCode && <span className="rounded bg-primary-soft px-1.5 py-0.5 font-mono text-[11px] text-primary">{jobCode}</span>}
          <span className="text-muted-foreground">
            {order.contractor || 'no contractor'} · {order.project}
          </span>
        </p>
      )}
      <ItemFacts line={line} />
    </div>
  )

  if (loaded) {
    return (
      <div>
        {facts}
        <SheetBlocks orderId={orderId} line={line} loaded={loaded} onDone={onClose} onDiscard={() => setLoaded(null)} />
      </div>
    )
  }

  return (
    <div>
      {facts}
      {!target.client && !entry && <SheetFill orderId={orderId} itemId={line.item_id} itemName={[line.item_code, line.activity_no].filter(Boolean).join(' ') || line.description} onLoad={setLoaded} />}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <Tabs
          label="How it is measured"
          value={mode}
          onChange={setMode}
          items={[
            { value: 'dims', label: 'Dimensions' },
            { value: 'total', label: 'Just a total' },
          ]}
        />
        <p className="text-[13px] text-muted-foreground">
          {mode === 'dims' ? "No's × NoM × L × B × D, deductions taken away. A blank is not a nought." : 'For a count, or a quantity that has no dimensions.'}
        </p>
      </div>

      {mode === 'dims' ? (
        <>
          <DataGrid aria-label="Dimensions" columns={columns} rows={dims} onRowsChange={(r) => setDims(r)} newRow={blankDim} minRows={5} maxHeight={300} rowClassName={(r) => (r.heading ? 'font-semibold' : undefined)} />
          <div className="mt-3 rounded-lg border border-dashed border-border p-3" aria-label="Custom calculation">
            <p className="mb-2 text-[13px] font-medium">Custom calculation</p>
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] sm:items-end">
              <Field label="Name" htmlFor="m-calc-label">
                <Input id="m-calc-label" value={calcLabel} onChange={(e) => setCalcLabel(e.target.value)} placeholder="Hold 5% for finishes" />
              </Field>
              <Field label="Calculation" htmlFor="m-calc" hint={calcText.trim() ? (calc === null ? 'Not understood. Try total * 5%' : `= ${formatQty(calc)}${calc < 0 ? ' (taken away)' : ''}`) : `"total" is what the lines above come to (${formatQty(lineTotal)}). Try -total * 5%, (total - 12.5) / 2 or 3 x 4.5`}>
                <Input id="m-calc" value={calcText} onChange={(e) => setCalcText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCalc() } }} placeholder="-total * 5%" />
              </Field>
              <Button variant="outline" disabled={calc === null || calc === 0} onClick={addCalc}>
                Add as a line
              </Button>
            </div>
          </div>
        </>
      ) : (
        <div className="max-w-xs">
          <Field label={`Quantity (${line.uom ?? ''})`} htmlFor="m-total">
            <NumField id="m-total" value={total} onValue={setTotal} autoFocus />
          </Field>
        </div>
      )}

      {canHold && (
        <div aria-label="Hold back" className={`mt-4 rounded-lg border p-3 ${holding ? 'border-warning/50 bg-warning-soft' : 'border-dashed border-border'}`}>
          <label className="flex items-center gap-2 text-[13px] font-medium">
            <input type="checkbox" aria-label="Hold part of this back" checked={holding} onChange={(e) => setHolding(e.target.checked)} />
            Hold part of this back from billing
            <span className="font-normal text-muted-foreground">- kept in the book, left off the bill until it is released</span>
          </label>
          {holding && (
            <div className="mt-3 grid gap-3 sm:grid-cols-[auto_8rem_minmax(0,1fr)] sm:items-end">
              <Tabs label="Hold by" value={holdBy} onChange={setHoldBy} items={[{ value: 'percent', label: 'A percent' }, { value: 'quantity', label: 'A quantity' }]} />
              {holdBy === 'percent' ? (
                <Field label="Percent" htmlFor="m-hold-pct">
                  <NumField id="m-hold-pct" value={holdPct} onValue={(n) => setHoldPct(Math.max(0, Math.min(100, n)))} />
                </Field>
              ) : (
                <Field label={`Quantity (${line.uom ?? ''})`} htmlFor="m-hold-qty">
                  <NumField id="m-hold-qty" value={holdQty} onValue={(n) => setHoldQty(Math.max(0, n))} />
                </Field>
              )}
              <Field label="Why it is held" htmlFor="m-hold-why">
                <Input id="m-hold-why" value={holdWhy} onChange={(e) => setHoldWhy(e.target.value)} />
              </Field>
            </div>
          )}
        </div>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {target.client ? (
          <Field label="Witnessed by" htmlFor="m-witness" hint="Who saw it measured.">
            <Input id="m-witness" value={witness} onChange={(e) => setWitness(e.target.value)} />
          </Field>
        ) : (
          <Field label="Blocks built alike" htmlFor="m-blocks" hint="The lines above are of one.">
            <NumField id="m-blocks" value={blocks} onValue={(n) => setBlocks(n > 0 ? n : 1)} />
          </Field>
        )}
        <Field label="Measured on" htmlFor="m-on">
          <Input id="m-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        </Field>
        <Field label="MB reference" htmlFor="m-ref">
          <Input id="m-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="MB-12 / p.51" />
        </Field>
        <Field label="Where" htmlFor="m-where">
          <Input id="m-where" value={where} onChange={(e) => setWhere(e.target.value)} placeholder="Block C-3, first floor" />
        </Field>
        <Field label="Remarks" htmlFor="m-remarks" className="sm:col-span-2 lg:col-span-4">
          <Input id="m-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        </Field>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <div>
          <p className="text-[13px] text-muted-foreground">
            This entry {blocks !== 1 && `(${formatQty(one)} × ${blocks} blocks)`}
          </p>
          <p className={`tabular font-display text-2xl font-semibold ${over ? 'text-danger' : ''}`}>
            {formatQty(quantity)} <span className="text-base font-normal text-muted-foreground">{line.uom}</span>
          </p>
          {over && <p className="mt-0.5 text-xs text-danger">That takes the item to {formatQty(after)}, past the {formatQty(line.max_quantity)} the order allows.</p>}
          {held > 0 && (
            <p aria-label="Held from this entry" className="mt-0.5 text-[13px] tabular">
              Held <strong>{formatQty(held)}</strong> · to be paid <strong>{formatQty(Math.round((quantity - held) * 1000) / 1000)}</strong>
            </p>
          )}
          {holdBad && <p className="mt-0.5 text-xs text-danger">{held > quantity ? 'More is held than is measured.' : 'Say why it is held.'}</p>}
        </div>
        <div className="flex items-center gap-2">
          {save.error && <p role="alert" className="max-w-md text-right text-[13px] text-danger">{save.error.message}</p>}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} disabled={quantity === 0 || holdBad} onClick={() => save.mutate()}>
            {entry ? 'Save the change' : 'Record it in the book'}
          </Button>
        </div>
      </div>
    </div>
  )
}
