import { useMemo, useState } from 'react'
import { DataGrid } from '@/components/grid'
import { Button, Field, Input, Modal, NumField, Tabs } from '@/components/ui'
import { mbKeys, recordUrl, type MbLine, type MeasurementInput } from '@/api/mb'
import type { Order } from '@/api/orders'
import { blankDim, dimTotal, type DimLine } from '@/lib/measure'
import { formatQty, today } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { sendOrQueue } from '@/stores/offline'
import { toast } from '@/stores/toast'
import { dimColumns } from './dimensions'
import { ItemFacts } from './ItemFacts'

type Mode = 'dims' | 'total'

/**
 * One measurement into the book: the dimension lines as they are written in
 * the field book, worked out as they are typed, or - for a count - just a
 * total. With no signal it is kept on the device and sent when one returns.
 */
export function MeasureModal({ orderId, order, jobCode, line, onClose }: { orderId: number; order?: Order; jobCode?: string; line: MbLine | null; onClose: () => void }) {
  return (
    <Modal open={!!line} onOpenChange={(o) => !o && onClose()} size="xl" title={line ? `Measure ${line.activity_no} ${line.description}` : 'Measure'} description={line ? allowance(line) : undefined}>
      {line && <MeasureForm key={line.item_id} orderId={orderId} order={order} jobCode={jobCode} line={line} onClose={onClose} />}
    </Modal>
  )
}

const allowance = (l: MbLine) =>
  `${formatQty(l.measured_to_date)} of ${formatQty(l.ordered_qty)} ${l.uom ?? ''} measured` +
  (l.tolerance_percent ? `; up to ${formatQty(l.max_quantity)} allowed with ${l.tolerance_percent}% tolerance` : '') +
  '. Past that the order is amended.'

function MeasureForm({ orderId, order, jobCode, line, onClose }: { orderId: number; order?: Order; jobCode?: string; line: MbLine; onClose: () => void }) {
  const [mode, setMode] = useState<Mode>('dims')
  const [dims, setDims] = useState<DimLine[]>([])
  const [total, setTotal] = useState(0)
  const [blocks, setBlocks] = useState(1)
  const [on, setOn] = useState(today())
  const [ref, setRef] = useState('')
  const [where, setWhere] = useState('')
  const [remarks, setRemarks] = useState('')

  const one = mode === 'dims' ? dimTotal(dims) : total
  const quantity = Math.round(one * blocks * 1000) / 1000
  const after = (line.measured_to_date ?? 0) + quantity
  const over = quantity > 0 && after > (line.max_quantity ?? Infinity) + 0.0001

  const save = useAction(
    async () => {
      const body: MeasurementInput = {
        item_id: line.item_id,
        measured_on: on,
        mb_ref: ref,
        location: where,
        remarks,
        multiplier: blocks,
        ...(mode === 'dims'
          ? {
              dimensions: dims
                .filter((d) => d.particulars.trim() || [d.nos, d.nom, d.length, d.breadth, d.depth].some((v) => v !== null))
                .map((d) => ({ particulars: d.particulars, nos: d.nos, nom: d.nom, length: d.length, breadth: d.breadth, depth: d.depth, deduct: d.deduct, is_heading: d.heading })),
            }
          : { quantity: total }),
      }
      const sent = await sendOrQueue<{ message: string }>({
        method: 'POST',
        url: recordUrl(orderId),
        body,
        label: `Measured ${formatQty(quantity)} ${line.uom ?? ''} against ${line.activity_no}`.trim(),
      })
      if (sent.queued) {
        toast.info('No connection - kept on this device and sent when it returns.')
        return { message: '' }
      }
      return sent.result
    },
    { invalidate: [mbKeys.all, ['subbills']], onSuccess: onClose },
  )

  const columns = useMemo(() => dimColumns, [])

  return (
    <div>
      <div className="mb-4 rounded-lg border border-border bg-muted/40 p-3" aria-label="The work order being measured">
        {order && (
          <p className="mb-2 flex flex-wrap items-baseline gap-x-2 text-[13px]">
            <span className="font-mono font-semibold">{order.wo_number}</span>
            {jobCode && <span className="rounded bg-primary-soft px-1.5 py-0.5 font-mono text-[11px] text-primary">{jobCode}</span>}
            <span className="text-muted-foreground">
              {order.contractor || 'no gang'} · {order.project}
            </span>
          </p>
        )}
        <ItemFacts line={line} />
      </div>
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
        <DataGrid aria-label="Dimensions" columns={columns} rows={dims} onRowsChange={(r) => setDims(r)} newRow={blankDim} minRows={5} maxHeight={300} rowClassName={(r) => (r.heading ? 'font-semibold' : undefined)} />
      ) : (
        <div className="max-w-xs">
          <Field label={`Quantity (${line.uom ?? ''})`} htmlFor="m-total">
            <NumField id="m-total" value={total} onValue={setTotal} autoFocus />
          </Field>
        </div>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Blocks built alike" htmlFor="m-blocks" hint="The lines above are of one.">
          <NumField id="m-blocks" value={blocks} onValue={(n) => setBlocks(n > 0 ? n : 1)} />
        </Field>
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
        </div>
        <div className="flex items-center gap-2">
          {save.error && <p role="alert" className="max-w-md text-right text-[13px] text-danger">{save.error.message}</p>}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} disabled={quantity === 0} onClick={() => save.mutate()}>
            Record it in the book
          </Button>
        </div>
      </div>
    </div>
  )
}
