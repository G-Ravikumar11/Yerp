import { useMemo, useState } from 'react'
import { Button, Modal, Skeleton } from '@/components/ui'
import { billKeys, drawBill } from '@/api/subbills'
import { mbKeys, useMeasurementBook } from '@/api/mb'
import { useAction } from '@/lib/mutate'
import { formatDate, formatQty } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Drawing up a bill: everything measured and not yet billed, or only the entries of the measurement book that are
 * ticked here. Entries that share a hold are billed together - the hold is on the group - so ticking one block
 * brings its group with it.
 */
export function DrawBillDialog({ orderId, open, onOpenChange, onDrawn }: { orderId: number; open: boolean; onOpenChange: (o: boolean) => void; onDrawn: (billId: number) => void }) {
  const book = useMeasurementBook(open ? orderId : 0)
  const [mode, setMode] = useState<'all' | 'chosen'>('all')
  const [ticked, setTicked] = useState<Set<number>>(new Set())
  const byItem = useMemo(() => new Map((book.data?.lines ?? []).map((l) => [l.item_id, l])), [book.data])
  const open_ = useMemo(() => (book.data?.entries ?? []).filter((e) => !e.billed).sort((a, b) => a.id - b.id), [book.data])

  const draw = useAction(() => drawBill(orderId, mode === 'chosen' ? [...ticked] : undefined), {
    invalidate: [billKeys.all, mbKeys.all],
    onSuccess: (r) => {
      onOpenChange(false)
      onDrawn(r.bill.id)
    },
  })

  const toggle = (id: number, on: boolean) =>
    setTicked((s) => {
      const next = new Set(s)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  const all = open_.length > 0 && open_.every((e) => ticked.has(e.id))

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Draw up a bill"
      description="Bill everything that is measured and not yet billed, or pick the entries of the measurement book this bill is for."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={draw.isPending} disabled={mode === 'chosen' && ticked.size === 0} onClick={() => draw.mutate()}>
            {mode === 'chosen' ? `Draw up a bill for ${ticked.size} ${ticked.size === 1 ? 'entry' : 'entries'}` : 'Draw up the bill'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div role="radiogroup" aria-label="What goes on the bill" className="grid gap-2 text-sm sm:grid-cols-2">
          {(
            [
              ['all', 'Everything not yet billed', 'All the work measured since the last bill.'],
              ['chosen', 'Only the entries I choose', 'Bill one entry, or a few, and leave the rest for later.'],
            ] as const
          ).map(([value, label, hint]) => (
            <label key={value} className={cn('flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5', mode === value ? 'border-primary bg-primary-soft' : 'border-border')}>
              <input type="radio" name="draw-mode" checked={mode === value} onChange={() => setMode(value)} className="mt-1 size-4 accent-[var(--primary)]" />
              <span>
                <span className="block font-medium">{label}</span>
                <span className="block text-xs text-muted-foreground">{hint}</span>
              </span>
            </label>
          ))}
        </div>

        {mode === 'chosen' &&
          (book.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : open_.length === 0 ? (
            <p className="rounded-lg border border-border px-3 py-6 text-center text-sm text-muted-foreground">Everything measured is on a bill already.</p>
          ) : (
            <div className="max-h-[22rem] overflow-y-auto rounded-lg border border-border">
              <table aria-label="Entries not yet billed" className="w-full text-[13px]">
                <thead className="sticky top-0 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="w-10 px-3 py-2">
                      <input type="checkbox" aria-label="Tick every entry" checked={all} onChange={(e) => setTicked(e.target.checked ? new Set(open_.map((x) => x.id)) : new Set())} />
                    </th>
                    <th className="px-2 py-2">Entry</th>
                    <th className="px-2 py-2">Where</th>
                    <th className="px-2 py-2">Item</th>
                    <th className="px-2 py-2 text-right">Quantity</th>
                  </tr>
                </thead>
                <tbody>
                  {open_.map((e) => {
                    const line = byItem.get(e.item_id)
                    return (
                      <tr key={e.id} className="border-t border-border">
                        <td className="px-3 py-1.5">
                          <input type="checkbox" aria-label={`Bill ${e.code || 'entry ' + e.id}`} checked={ticked.has(e.id)} onChange={(x) => toggle(e.id, x.target.checked)} />
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="font-mono text-xs font-medium">{e.code || `#${e.id}`}</div>
                          <div className="text-xs text-muted-foreground">{formatDate(e.measured_on)}</div>
                        </td>
                        <td className="px-2 py-1.5">{e.kind === 'hold' ? 'Held back' : e.kind === 'release' ? 'Released' : e.location || '-'}</td>
                        <td className="px-2 py-1.5">
                          <span className="font-medium">{e.activity_no}</span> <span className="text-muted-foreground">{(line?.description ?? '').slice(0, 40)}</span>
                        </td>
                        <td className={cn('tabular px-2 py-1.5 text-right font-medium', e.quantity < 0 && 'text-danger')}>
                          {formatQty(e.quantity)} {line?.uom}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ))}
        {draw.error && (
          <p role="alert" className="text-sm text-danger">
            {draw.error.message}
          </p>
        )}
      </div>
    </Modal>
  )
}
