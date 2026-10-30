import { useQueries } from '@tanstack/react-query'
import { Trophy } from 'lucide-react'
import { Link } from 'react-router-dom'
import { get } from '@/lib/api'
import { Badge, Modal } from '@/components/ui'
import type { RfqRow, Statement } from '@/api/rfq'
import { pooledComparison, type PooledItem } from '@/lib/rfqCompare'
import { formatINR } from '@/lib/utils'
import { cn } from '@/lib/utils'

/**
 * The enquiries ticked on the list, their quotes pooled: for each item, every supplier's rate whichever enquiry it came
 * in on, the cheapest named; and over all of it, the supplier cheapest on the most items.
 */
export function CompareEnquiriesModal({ enquiries, onClose }: { enquiries: RfqRow[]; onClose: () => void }) {
  const qs = useQueries({
    // Same key as an enquiry's own page, so what either fetched is shared.
    queries: enquiries.map((r) => ({ queryKey: ['rfq', 'one', r.id], staleTime: 0, queryFn: () => get<Statement>(`/api/rfqs/${r.id}/statement`) })),
  })
  const loading = qs.some((q) => q.isPending)
  const failed = qs.find((q) => q.error)?.error
  const statements = qs.flatMap((q) => (q.data ? [q.data] : []))
  const p = !loading && !failed ? pooledComparison(statements) : null

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title={`Compare ${enquiries.length} enquiries`}
      description={`${enquiries.map((r) => r.number).join(', ')}: every supplier's rate for each item, whichever enquiry it was quoted on. Rates are per unit before GST; a tie goes to the quicker delivery.`}>
      {loading ? <p className="py-8 text-center text-sm text-muted-foreground">Reading the quotes...</p>
        : failed ? <p role="alert" className="py-8 text-center text-sm text-danger">{failed.message}</p>
        : p && (
          <div className="grid gap-5">
            <Verdict p={p} />
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[40rem] text-[13px]">
                <thead className="bg-surface text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2.5">Item</th>
                    <th className="px-3 py-2.5">Cheapest</th>
                    <th className="px-3 py-2.5">Every quote</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {p.items.map((it) => <ItemRow key={it.key} it={it} />)}
                </tbody>
              </table>
            </div>
          </div>
        )}
    </Modal>
  )
}

function Verdict({ p }: { p: ReturnType<typeof pooledComparison> }) {
  if (!p.best) return <p className="rounded-lg border border-border bg-surface px-4 py-3 text-sm">No supplier has quoted on these enquiries yet, so there is nothing to compare. Ask suppliers from each enquiry's page first.</p>
  const priced = p.items.length - p.unpriced
  const runners = p.suppliers.slice(1).filter((s) => s.cheapest > 0)
  return (
    <div className="rounded-lg border border-success/40 bg-success/[0.07] px-4 py-3">
      <p className="flex items-center gap-2 text-sm">
        <Trophy className="size-4 shrink-0 text-success" />
        <span><strong>{p.best.supplier_name}</strong> is the better buy: cheapest on {p.best.cheapest} of {priced} priced {priced === 1 ? 'item' : 'items'}.</span>
      </p>
      <p className="mt-1 pl-6 text-[13px] text-muted-foreground">
        {runners.length ? `Also cheapest somewhere: ${runners.map((s) => `${s.supplier_name} (${s.cheapest})`).join(', ')}. Buying each item from its cheapest supplier is the lowest cost overall.` : 'Nobody else is cheapest on any item.'}
        {p.unpriced > 0 && ` ${p.unpriced} ${p.unpriced === 1 ? 'item has' : 'items have'} no quote yet.`}
      </p>
    </div>
  )
}

function ItemRow({ it }: { it: PooledItem }) {
  const saving = it.best && it.next ? it.next.rate - it.best.rate : 0
  return (
    <tr className="align-top">
      <td className="px-3 py-2.5">
        <div className="font-medium">{it.description || it.item_code}</div>
        <div className="text-xs text-muted-foreground">{[it.item_code, it.uom, `on ${it.enquiries.join(', ')}`].filter(Boolean).join(' · ')}</div>
      </td>
      <td className="px-3 py-2.5">
        {it.best ? (
          <>
            <div className="font-semibold text-success">{it.best.supplier_name}</div>
            <div className="tabular">{formatINR(it.best.rate)} / {it.uom || 'unit'}</div>
            {saving > 0 && <div className="text-xs text-muted-foreground">{formatINR(saving)} less than {it.next!.supplier_name}</div>}
          </>
        ) : <span className="text-muted-foreground">Not quoted yet</span>}
      </td>
      <td className="px-3 py-2.5">
        <ul className="grid gap-1">
          {it.offers.map((o, i) => (
            <li key={o.supplier_name} className={cn('flex flex-wrap items-baseline gap-x-2', i === 0 ? 'text-foreground' : 'text-muted-foreground')}>
              {i === 0 && <Badge tone="success">L1</Badge>}
              <span>{o.supplier_name}</span>
              <span className="tabular">{formatINR(o.rate)}</span>
              <span className="text-xs">GST {o.tax_percent}%{o.delivery_days ? ` · ${o.delivery_days} days` : ''} · <Link className="underline-offset-2 hover:underline" to={`/store/enquiries/${o.rfq_id}?view=compare`}>{o.rfq_number}</Link></span>
            </li>
          ))}
          {!it.offers.length && <li className="text-muted-foreground">-</li>}
        </ul>
      </td>
    </tr>
  )
}
