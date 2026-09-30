import { useState } from 'react'
import { Button, Field, Input, Modal } from '@/components/ui'
import { raisePurchaseOrder, useRequisition, type ClientOrder } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { formatQty } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'

/** What the budget says still has to be bought: the shortfall after the store and what is already on order. */
export function RequisitionModal({ order, onClose }: { order: ClientOrder | null; onClose: () => void }) {
  return (
    <Modal open={!!order} onOpenChange={(o) => !o && onClose()} size="xl" title={order ? `Material for ${order.number}` : 'Material'}>
      {order && <Shortfall key={order.id} id={order.id} onClose={onClose} />}
    </Modal>
  )
}

function Shortfall({ id, onClose }: { id: number; onClose: () => void }) {
  const req = useRequisition(id)
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const [supplier, setSupplier] = useState('')
  const [by, setBy] = useState('')
  const raise = useAction((codes: string[]) => raisePurchaseOrder(id, { supplier_name: supplier.trim(), needed_by: by, item_codes: codes }), { invalidate: [['purchase-orders']], onSuccess: onClose })

  if (req.isPending) return <p className="py-10 text-center text-sm text-muted-foreground">Reading the budget...</p>
  if (req.error || !req.data) return <p role="alert" className="py-6 text-sm text-danger">Could not read the budget.</p>

  const { lines, summary } = req.data
  const short = lines.filter((l) => !l.covered)
  const picked = short.filter((l) => !skipped.has(l.item_code))
  const toggle = (code: string) =>
    setSkipped((s) => {
      const next = new Set(s)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })

  return (
    <div>
      <p className="mb-4 text-sm text-muted-foreground">
        {short.length
          ? `${short.length} item${short.length === 1 ? '' : 's'} still to buy, ${formatINR(summary.value)}. Priced at what the store last paid.`
          : 'Nothing left to buy. The budget is covered by what is in the store and what is already on order.'}
      </p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-surface text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="w-10 px-3 py-2" />
              <th className="px-3 py-2">Item</th>
              <th className="px-3 py-2 text-right">Needed</th>
              <th className="px-3 py-2 text-right">In store</th>
              <th className="px-3 py-2 text-right">On order</th>
              <th className="px-3 py-2 text-right">To buy</th>
              <th className="px-3 py-2 text-right">Rate</th>
              <th className="px-3 py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">
                  This order has no budget behind it, so nothing is known about what it needs.
                </td>
              </tr>
            )}
            {lines.map((l) => (
              <tr key={l.item_code} className={cn('border-b border-border last:border-0', l.covered && 'opacity-55')}>
                <td className="px-3 py-2">{!l.covered && <input type="checkbox" aria-label={`Buy ${l.item_code}`} checked={!skipped.has(l.item_code)} onChange={() => toggle(l.item_code)} className="size-4 accent-[var(--primary)]" />}</td>
                <td className="px-3 py-2">
                  <span className="font-mono text-[13px]">{l.item_code}</span>
                  <div className="text-xs text-muted-foreground">{l.item_name}</div>
                </td>
                <td className="tabular px-3 py-2 text-right">{formatQty(l.needed)} {l.uom}</td>
                <td className="tabular px-3 py-2 text-right">{formatQty(l.in_store)}</td>
                <td className="tabular px-3 py-2 text-right">{formatQty(l.on_order)}</td>
                <td className="tabular px-3 py-2 text-right font-medium">{l.covered ? <span className="text-success">covered</span> : formatQty(l.to_buy)}</td>
                <td className="tabular px-3 py-2 text-right">
                  {formatINR(l.rate)}
                  {l.budget_rate != null && l.rate !== l.budget_rate && <div className="text-xs text-muted-foreground">budget {formatINR(l.budget_rate)}</div>}
                </td>
                <td className="tabular px-3 py-2 text-right">{formatINR(l.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {short.length > 0 && (
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="Order with" htmlFor="rq-supplier" hint="Who the purchase order is for. It arrives as a draft to check and approve.">
            <Input id="rq-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Supplier's name" />
          </Field>
          <Field label="Needed by" htmlFor="rq-by">
            <Input id="rq-by" type="date" value={by} onChange={(e) => setBy(e.target.value)} />
          </Field>
        </div>
      )}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {raise.error && (
          <p role="alert" className="mr-auto text-[13px] text-danger">
            {raise.error.message}
          </p>
        )}
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
        {short.length > 0 && (
          <Button loading={raise.isPending} disabled={!supplier.trim() || picked.length === 0} onClick={() => raise.mutate(picked.map((l) => l.item_code))}>
            Raise the purchase order
          </Button>
        )}
      </div>
    </div>
  )
}
