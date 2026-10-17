import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, FileText, Link2, Pencil, Plus, Trophy } from 'lucide-react'
import { Button, Tabs } from '@/components/ui'
import type { RfqSupplier, Statement } from '@/api/rfq'
import { compare, type Comparison } from '@/lib/rfqCompare'
import { formatDate, formatQty } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'
import type { AwardPreset } from './AwardModal'
import { QuoteCheckModal } from './QuoteCheck'

const days = (n: number) => (n ? `${n} ${n === 1 ? 'day' : 'days'}` : '-')
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()

/** The quotes side by side: what to award said once at the top, then every item against every supplier. */
export function ComparisonTab({ d, onAward, onAsk, onQuote }: { d: Statement; onAward: (p: AwardPreset) => void; onAsk: () => void; onQuote: (supplier?: string) => void }) {
  const open = d.rfq.status === 'OPEN'
  if (!d.suppliers.length) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card px-6 py-14 text-center">
        <p className="font-medium">No quotes yet</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
          {open ? 'Send suppliers a link to quote on their phone, or enter a quote that came by email or WhatsApp. They appear here side by side.' : 'This enquiry closed before any supplier quoted.'}
        </p>
        {open && (
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Button onClick={onAsk}><Link2 /> Ask suppliers</Button>
            <Button variant="outline" onClick={() => onQuote()}><Plus /> Enter a quote</Button>
          </div>
        )}
      </div>
    )
  }
  const c = compare(d, d.suppliers.map((s) => s.supplier_name))
  return (
    <div className="grid gap-4">
      <Verdict d={d} c={c} onAward={onAward} />
      <Sheet d={d} c={c} onQuote={onQuote} />
    </div>
  )
}

/** The answer: the cheapest total at site and by how much, with the award one press away. Once awarded, who got it. */
function Verdict({ d, c, onAward }: { d: Statement; c: Comparison; onAward: (p: AwardPreset) => void }) {
  const awarded = d.rfq.status === 'AWARDED'
  if (awarded) {
    const orders = d.orders ?? []
    return (
      <div className="rounded-xl border border-success/30 bg-success-soft px-5 py-4">
        <p className="flex items-center gap-2 text-sm font-semibold text-success"><Check className="size-4" /> Awarded{d.rfq.awarded_at ? ` on ${formatDate(d.rfq.awarded_at.slice(0, 10))}` : ''}</p>
        {orders.length > 0 && (
          <ul className="mt-2 grid gap-1 text-sm">
            {orders.map((o) => <li key={o.id}><Link to={`/store/purchase-orders?q=${encodeURIComponent(o.number)}`} className="font-mono text-[13px] text-primary hover:underline">{o.number}</Link> to <strong>{o.supplier_name}</strong> · <span className="tabular">{formatINR(o.total)}</span> <span className="text-muted-foreground">({o.status.toLowerCase()})</span></li>)}
          </ul>
        )}
        {d.rfq.award_reason && <p className="mt-2 text-[13px]"><span className="text-muted-foreground">Why not the lowest: </span>{d.rfq.award_reason}</p>}
      </div>
    )
  }
  if (d.rfq.status !== 'OPEN') return null
  const { l1, split } = c
  const l2 = c.suppliers.find((s) => c.rank.get(s.supplier_name) === 'L2')
  const canSplit = !split.uncovered.length && split.vendors > 1
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-4 rounded-xl border border-border bg-card px-5 py-4 shadow-xs">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg bg-success-soft text-success"><Trophy className="size-[18px]" /></span>
        {l1 ? (
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Lowest total at site</p>
            <p className="mt-0.5 text-base"><strong>{l1.supplier_name}</strong> <span className="ml-1 font-semibold tabular text-success">{formatINR(l1.landed)}</span></p>
            <p className="mt-0.5 text-[13px] text-muted-foreground">
              {l2 ? `${formatINR(l2.landed - l1.landed)} less than ${l2.supplier_name}` : 'The only supplier who quoted every item so far'}
              {c.splitSaving > 0.5 && ` · buying each item from its cheapest supplier saves ${formatINR(c.splitSaving)} more`}
            </p>
          </div>
        ) : (
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">No full quote yet</p>
            <p className="mt-0.5 text-[13px] text-muted-foreground">Nobody has priced every item, so there is no single cheapest supplier.{canSplit ? ' The order can still be split, each item to its cheapest.' : ''}</p>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {canSplit && <Button variant="outline" onClick={() => onAward({ mode: 'lowest_per_line' })}>Split by item</Button>}
        {c.suppliers.some((s) => s.complete) && <Button variant={l1 ? 'outline' : 'primary'} onClick={() => onAward({ mode: 'one_supplier', supplier: '' })}>Choose another</Button>}
        {l1 && <Button onClick={() => onAward({ mode: 'one_supplier', supplier: l1.supplier_name })}>Award to {l1.supplier_name}</Button>}
      </div>
    </div>
  )
}

function Rank({ rank }: { rank?: string }) {
  if (!rank) return null
  return <span className={cn('rounded px-1.5 py-px text-[10px] font-bold tracking-wide', rank === 'L1' ? 'bg-success text-white' : 'bg-muted text-muted-foreground')}>{rank}</span>
}

/** Items down the side, suppliers across, the lowest in each row in green; totals and terms underneath. */
function Sheet({ d, c, onQuote }: { d: Statement; c: Comparison; onQuote: (supplier?: string) => void }) {
  const [show, setShow] = useState<'rate' | 'amount'>('rate')
  const [checking, setChecking] = useState<RfqSupplier | null>(null)
  const open = d.rfq.status === 'OPEN'
  const sups = c.suppliers
  const col = 'min-w-40 border-l border-border px-4 text-right'
  const label = 'sticky left-0 z-10 bg-card px-4 text-left'
  const isL1 = (s: RfqSupplier) => c.rank.get(s.supplier_name) === 'L1'
  const anyValid = sups.some((s) => s.valid_until)
  const anyRef = sups.some((s) => s.quote_ref || s.quote_date)
  const terms: [string, (s: RfqSupplier) => React.ReactNode][] = [
    ['Delivery', (s) => days(s.delivery_days)],
    ['Payment', (s) => <span className="line-clamp-2" title={s.payment_terms}>{s.payment_terms || '-'}</span>],
    ...(anyValid ? [['Valid till', (s: RfqSupplier) => (s.valid_until ? formatDate(s.valid_until) : '-')] as [string, (s: RfqSupplier) => React.ReactNode]] : []),
    ...(anyRef ? [['Their quote', (s: RfqSupplier) => (s.quote_ref || s.quote_date ? <><div>{s.quote_ref ? `No. ${s.quote_ref}` : '-'}</div>{s.quote_date && <div className="text-xs text-muted-foreground">{formatDate(s.quote_date)}</div>}</> : '-')] as [string, (s: RfqSupplier) => React.ReactNode]] : []),
  ]
  return (
    <section aria-label="Comparative statement" className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-3">
          <Tabs label="Show" value={show} onChange={setShow} items={[{ value: 'rate', label: 'Rate per unit' }, { value: 'amount', label: 'Amount' }]} />
          <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:inline-flex"><span className="size-2.5 rounded-sm bg-success/25 ring-1 ring-success/40" /> lowest for the item</span>
        </div>
        {open && <Button size="sm" variant="ghost" onClick={() => onQuote()}><Plus /> Enter a quote</Button>}
      </div>
      <div className="overflow-x-auto">
        <table aria-label="Comparison" className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface/60 align-top">
              <th scope="col" className={cn(label, 'min-w-56 bg-surface py-3 text-xs font-medium text-muted-foreground')}>Item</th>
              {sups.map((s) => (
                <th key={s.quote_id} scope="col" className={cn(col, 'py-3 font-normal')} style={{ width: `${70 / sups.length}%` }}>
                  <div className="flex items-start justify-end gap-2">
                    <div className="min-w-0 text-right">
                      <div className="truncate font-semibold" title={s.supplier_name}>{s.supplier_name}</div>
                      <div className="mt-1 flex flex-wrap items-center justify-end gap-1">
                        <Rank rank={c.rank.get(s.supplier_name)} />
                        {!s.complete && <span className="rounded bg-warning-soft px-1.5 py-px text-[10px] font-medium text-warning" title={`Quoted ${s.lines_quoted} of ${d.lines.length} items`}>{s.lines_quoted} of {d.lines.length} items</span>}
                      </div>
                    </div>
                    <div className="-mr-1.5 flex shrink-0 flex-col print:hidden">
                      {s.document && <Button size="icon-sm" variant="ghost" aria-label={`${s.supplier_name}'s quotation file`} title="Check against their quotation" onClick={() => setChecking(s)}><FileText /></Button>}
                      {open && <Button size="icon-sm" variant="ghost" aria-label={`Edit ${s.supplier_name}'s quote`} title="Edit this quote" onClick={() => onQuote(s.supplier_name)}><Pencil /></Button>}
                    </div>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.lines.map((l) => {
              const low = c.lowest.get(l.rfq_line_id)
              return (
                <tr key={l.rfq_line_id} className="border-b border-border/70">
                  <th scope="row" className={cn(label, 'py-2.5 font-normal')}>
                    <div className="font-medium">{l.description}</div>
                    <div className="text-xs text-muted-foreground">{formatQty(l.qty)} {l.uom}{l.item_code && <span className="font-mono"> · {l.item_code}</span>}</div>
                  </th>
                  {sups.map((s) => {
                    const o = l.offers.find((x) => same(x.supplier_name, s.supplier_name))
                    if (!o) return <td key={s.quote_id} className={cn(col, 'py-2.5 text-muted-foreground')}>-</td>
                    const best = low !== undefined && o.rate <= low + 0.0001 && sups.length > 1
                    const won = !!l.awarded_supplier && same(l.awarded_supplier, s.supplier_name)
                    return (
                      <td key={s.quote_id} className={cn(col, 'py-2.5 tabular', best && 'bg-success/[0.07]')} title={`GST ${o.tax_percent}%${o.remarks ? ` · ${o.remarks}` : ''}`}>
                        <div className={cn('inline-flex items-center gap-1', best ? 'font-semibold text-success' : 'text-foreground')}>
                          {won && <Check className="size-3.5 text-primary" aria-label="Awarded" />}
                          {formatINR(show === 'rate' ? o.rate : o.amount)}
                        </div>
                        {o.remarks && <div className="truncate text-[11px] text-muted-foreground">{o.remarks}</div>}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
          <tfoot className="text-[13px]">
            {([['Items total', (s: RfqSupplier) => formatINR(s.basic)], ['GST', (s: RfqSupplier) => formatINR(s.tax)], ['Transport', (s: RfqSupplier) => (s.freight ? formatINR(s.freight) : '-')]] as const).map(([name, get], i) => (
              <tr key={name} className={cn('text-muted-foreground', i === 0 && 'border-t border-border')}>
                <th scope="row" className={cn(label, 'py-1.5 font-normal')}>{name}</th>
                {sups.map((s) => <td key={s.quote_id} className={cn(col, 'py-1.5 tabular')}>{get(s)}</td>)}
              </tr>
            ))}
            <tr className="border-y border-border text-sm">
              <th scope="row" className={cn(label, 'py-3 font-semibold')}>Total at site</th>
              {sups.map((s) => (
                <td key={s.quote_id} className={cn(col, 'py-3 font-semibold tabular', isL1(s) && 'bg-success/[0.07] text-success')}>
                  {s.complete ? formatINR(s.landed) : <span className="font-normal text-muted-foreground" title="Not every item is priced, so this total is not comparable">{formatINR(s.landed)}*</span>}
                </td>
              ))}
            </tr>
            {terms.map(([name, get]) => (
              <tr key={name} className="align-top">
                <th scope="row" className={cn(label, 'py-1.5 font-normal text-muted-foreground')}>{name}</th>
                {sups.map((s) => <td key={s.quote_id} className={cn(col, 'py-1.5')}>{get(s)}</td>)}
              </tr>
            ))}
          </tfoot>
        </table>
      </div>
      {sups.some((s) => !s.complete) && <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">* A part quote: some items are not priced, so its total cannot be compared with a full one.</p>}
      {checking && <QuoteCheckModal statement={d} supplier={checking} onClose={() => setChecking(null)} />}
    </section>
  )
}
