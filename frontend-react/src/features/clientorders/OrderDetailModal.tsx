import { Badge, Modal } from '@/components/ui'
import { useClientOrder, type ClientOrder } from '@/api/clientOrders'
import { formatQty } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const cell = 'px-3 py-2'
const head = 'px-3 py-2 text-xs uppercase tracking-wide text-muted-foreground'

/** One order, in full: what was sold, what it is budgeted to cost, and who has signed. */
export function OrderDetailModal({ order, onClose }: { order: ClientOrder | null; onClose: () => void }) {
  return (
    <Modal open={!!order} onOpenChange={(o) => !o && onClose()} size="xl" title={order ? `${order.number} - ${order.job_name}` : 'Work order'} description={order ? [order.customer_name, order.reference].filter(Boolean).join(' · ') : undefined}>
      {order && <Detail id={order.id} />}
    </Modal>
  )
}

function Detail({ id }: { id: number }) {
  const q = useClientOrder(id)
  if (q.isPending) return <p className="py-10 text-center text-sm text-muted-foreground">Opening the order...</p>
  const o = q.data
  if (!o) return <p role="alert" className="py-6 text-sm text-danger">Could not open that order.</p>
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold">What was sold</h3>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-surface text-left">
                <th className={head}>Item</th>
                <th className={`${head} text-right`}>Quantity</th>
                <th className={`${head} text-right`}>Rate</th>
                <th className={`${head} text-right`}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {(o.lines ?? []).map((l) => (
                <tr key={l.id} className="border-b border-border last:border-0">
                  <td className={cell}>
                    <span className="font-mono text-[13px]">{l.fg_code}</span> {l.item_name}
                    {l.description && l.description !== l.item_name && <div className="text-xs text-muted-foreground">{l.description}</div>}
                  </td>
                  <td className={`${cell} tabular text-right`}>{formatQty(l.qty)} {l.uom}</td>
                  <td className={`${cell} tabular text-right`}>{formatINR(l.rate)}</td>
                  <td className={`${cell} tabular text-right`}>{formatINR(l.amount)}</td>
                </tr>
              ))}
              <tr className="bg-surface font-medium">
                <td className={cell} colSpan={3}>Order value</td>
                <td className={`${cell} tabular text-right`}>{formatINR(o.total_value)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Budget</h3>
        {(o.bom ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">No budget yet, so there is no margin to show.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <tbody>
                {(o.bom ?? []).map((b, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    <td className={cell}>
                      <span className="font-mono text-[13px]">{b.rm_code}</span> {b.rm_name}
                      <div className="text-xs text-muted-foreground">for {b.fg_code}</div>
                    </td>
                    <td className={`${cell} tabular text-right`}>{formatQty(b.qty)} {b.uom}</td>
                    <td className={`${cell} tabular text-right`}>{formatINR(b.rate)}</td>
                    <td className={`${cell} tabular text-right`}>{formatINR(b.amount ?? b.qty * b.rate)}</td>
                  </tr>
                ))}
                <tr className="bg-surface font-medium">
                  <td className={cell} colSpan={3}>Budgeted cost · margin {o.margin_percent}%</td>
                  <td className={`${cell} tabular text-right`}>{formatINR(o.budget_cost)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </section>

      {(o.approval_history ?? []).length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Approval</h3>
          <ul className="space-y-1.5 text-sm">
            {(o.approval_history ?? []).map((h, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Badge tone={/reject/.test(h.decision ?? '') ? 'danger' : 'success'}>{h.decision}</Badge>
                <span>{h.by}</span>
                {h.note && <span className="text-muted-foreground">- {h.note}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
