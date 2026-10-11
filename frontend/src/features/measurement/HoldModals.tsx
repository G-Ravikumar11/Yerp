import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Tabs, Textarea } from '@/components/ui'
import { holdWork, mbKeys, releaseHold, type MbEntry, type MbLine } from '@/api/mb'
import { formatQty } from '@/lib/format'
import { useAction } from '@/lib/mutate'

type By = 'percent' | 'quantity'

/**
 * Hold part of an item's measured work back from billing - the share kept for finishes and handing
 * over, say. It stays in the book as held, with the reason, and the owner releases it later.
 */
export function HoldModal({ orderId, line, onClose }: { orderId: number; line: MbLine | null; onClose: () => void }) {
  return (
    <Modal open={!!line} onOpenChange={(o) => !o && onClose()} title={line ? `Hold work on ${[line.item_code, line.activity_no].filter(Boolean).join(' ')} ${line.description}` : 'Hold'} description="Held work is left off the bill until it is released. Only work not yet billed can be held.">
      {line && <HoldForm key={line.item_id} orderId={orderId} line={line} onClose={onClose} />}
    </Modal>
  )
}

function HoldForm({ orderId, line, onClose }: { orderId: number; line: MbLine; onClose: () => void }) {
  const [by, setBy] = useState<By>('percent')
  const [percent, setPercent] = useState(5)
  const [qty, setQty] = useState(0)
  const [reason, setReason] = useState('')
  const available = Math.max(0, line.unbilled ?? 0)
  const quantity = by === 'percent' ? Math.round(((available * percent) / 100) * 1000) / 1000 : qty
  const bad = quantity <= 0 || quantity > available + 0.0001 || !reason.trim()
  const save = useAction(() => holdWork(orderId, { item_id: line.item_id, reason, ...(by === 'percent' ? { percent } : { quantity: qty }) }), { invalidate: [mbKeys.all, ['subbills']], onSuccess: onClose })
  return (
    <div>
      <p className="mb-4 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[13px]">
        <span className="font-medium">{formatQty(available)}</span> {line.uom} measured and not yet billed
        {!!line.held && <> · {formatQty(line.held)} already held</>}
      </p>
      <Tabs label="Hold by" value={by} onChange={setBy} items={[{ value: 'percent', label: 'A percent' }, { value: 'quantity', label: 'A quantity' }]} />
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {by === 'percent' ? (
          <Field label="Percent to hold" htmlFor="h-percent" hint="Of the work measured and not yet billed.">
            <NumField id="h-percent" value={percent} onValue={setPercent} autoFocus />
          </Field>
        ) : (
          <Field label={`Quantity to hold (${line.uom ?? ''})`} htmlFor="h-qty">
            <NumField id="h-qty" value={qty} onValue={setQty} autoFocus />
          </Field>
        )}
        <div className="self-end pb-2 text-sm">
          Holds <span className="tabular font-semibold">{formatQty(quantity)}</span> {line.uom}
          {quantity > available + 0.0001 && <span className="block text-xs text-danger">That is more than can be held.</span>}
        </div>
        <Field label="Why is it held?" htmlFor="h-reason" className="sm:col-span-2" hint="Read back when it is released.">
          <Textarea id="h-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Held for finishes and handing over" />
        </Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && (
          <p role="alert" className="mr-auto max-w-md text-[13px] text-danger">
            {save.error.message}
          </p>
        )}
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button loading={save.isPending} disabled={bad} onClick={() => save.mutate()}>
          Hold it
        </Button>
      </div>
    </div>
  )
}

/** Put held work back into what can be billed. The owner's alone; all or part of it. */
export function ReleaseModal({ entry, line, onClose }: { entry: MbEntry | null; line?: MbLine; onClose: () => void }) {
  return (
    <Modal open={!!entry} onOpenChange={(o) => !o && onClose()} title="Release held work" description="Released work goes on the next bill.">
      {entry && <ReleaseForm key={entry.id} entry={entry} line={line} onClose={onClose} />}
    </Modal>
  )
}

function ReleaseForm({ entry, line, onClose }: { entry: MbEntry; line?: MbLine; onClose: () => void }) {
  const remaining = entry.held_remaining ?? 0
  const [qty, setQty] = useState(remaining)
  const save = useAction(() => releaseHold(entry.id, qty), { invalidate: [mbKeys.all, ['subbills']], onSuccess: onClose })
  return (
    <div>
      <p className="mb-1 text-sm">
        {line?.description} - held {formatQty(remaining)} {line?.uom}
      </p>
      {entry.remarks && <p className="mb-4 text-[13px] text-muted-foreground">{entry.remarks}</p>}
      <Field label={`Quantity to release (${line?.uom ?? ''})`} htmlFor="r-qty" hint={`Up to ${formatQty(remaining)}.`}>
        <Input id="r-qty" type="number" step="any" value={qty} onChange={(e) => setQty(Number(e.target.value))} autoFocus />
      </Field>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && (
          <p role="alert" className="mr-auto max-w-md text-[13px] text-danger">
            {save.error.message}
          </p>
        )}
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button loading={save.isPending} disabled={qty <= 0 || qty > remaining + 0.0001} onClick={() => save.mutate()}>
          Release
        </Button>
      </div>
    </div>
  )
}
