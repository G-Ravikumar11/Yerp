import { useState } from 'react'
import { ArrowLeft, Columns2, Download, Link2, Plus, Trophy } from 'lucide-react'
import { Badge, Button, Skeleton } from '@/components/ui'
import { useStatement, type RfqSupplier, type Statement } from '@/api/rfq'
import { compare, type Comparison } from '@/lib/rfqCompare'
import { formatDate } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import type { AwardPreset } from './AwardModal'
import { ComparisonDocModal } from './ComparisonDocModal'
import { AttachQuotation, QuoteCheckModal } from './QuoteCheck'
import { SupplierLinks } from './VendorLinks'

interface Props {
  id: number
  onBack: () => void
  /** Add a quote; with a supplier named when their file came through a link without rates. */
  onQuote: (supplier?: string) => void
  /** Ask suppliers to quote through their own link. */
  onAsk: () => void
  onAward: (preset?: AwardPreset) => void
}

const days = (n: number) => (n ? `${n} ${n === 1 ? 'day' : 'days'}` : '-')

/**
 * One enquiry as a comparative statement: who quoted what, item by item, the lowest in each row marked, the totals
 * underneath, and the one answer that matters said once at the top - who is cheapest overall, by how much, and a
 * button to give them the order.
 */
export function StatementPanel({ id, onBack, onQuote, onAsk, onAward }: Props) {
  const q = useStatement(id)
  const d = q.data
  const [doc, setDoc] = useState(false)
  if (q.isPending || !d) return <Skeleton className="mt-6 h-64 w-full" />
  const c = compare(d, d.suppliers.map((s) => s.supplier_name))
  const open = d.rfq.status === 'OPEN'
  const quotes = d.suppliers.length
  const waiting = (d.invites ?? []).filter((i) => i.status === 'sent' || i.status === 'opened').length

  return (
    <section aria-label={`Comparison ${d.rfq.number}`} className="mt-2 overflow-hidden rounded-xl border border-border bg-card shadow-card print:border-0 print:shadow-none">
      {/* the enquiry and what can be done with it */}
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 pb-4 pt-4">
        <div className="min-w-0">
          <button type="button" onClick={onBack} className="mb-1.5 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground print:hidden"><ArrowLeft className="size-3.5" /> All enquiries</button>
          <h2 className="flex min-w-0 flex-wrap items-center gap-x-2 text-lg font-semibold">
            <span className="font-mono text-muted-foreground">{d.rfq.number}</span>
            <span className="truncate">{d.rfq.title}</span>
            {!open && <Badge tone={d.rfq.status === 'AWARDED' ? 'success' : 'neutral'}>{d.rfq.status === 'AWARDED' ? 'Awarded' : 'Cancelled'}</Badge>}
          </h2>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            {[d.rfq.project || 'No particular project', `${d.lines.length} ${d.lines.length === 1 ? 'item' : 'items'}`, d.rfq.needed_by && `needed by ${formatDate(d.rfq.needed_by)}`].filter(Boolean).join(' · ')}
          </p>
          {open && (
            <p className="mt-2 text-[13px]">
              <span className={cn('font-medium', quotes >= 3 ? 'text-success' : 'text-foreground')}>{quotes >= 3 ? `${quotes} quotes` : `${quotes} of 3 quotes`}</span>
              <span className="text-muted-foreground">{waiting ? ` · ${waiting} supplier${waiting === 1 ? '' : 's'} asked, not answered yet` : ''}{quotes < 3 ? ' · ask more suppliers for a fair comparison' : ''}</span>
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          {open && <Button size="sm" variant="outline" onClick={onAsk}><Link2 /> Ask suppliers</Button>}
          {open && <Button size="sm" variant="outline" onClick={() => onQuote()}><Plus /> Add a quote</Button>}
          {quotes > 0 && <Button size="sm" variant="ghost" onClick={() => setDoc(true)}><Download /> Download</Button>}
        </div>
      </header>

      <SupplierLinks statement={d} onAddFromFile={(name) => onQuote(name)} />

      {quotes === 0 ? (
        <div className="border-t border-border px-5 py-10 text-center">
          <p className="font-medium">No quotes yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">Send each supplier a link to quote on their own, or add a quote you received by email or WhatsApp.</p>
          {open && <div className="mt-4 flex justify-center gap-2"><Button onClick={onAsk}><Link2 /> Ask suppliers</Button><Button variant="outline" onClick={() => onQuote()}><Plus /> Add a quote</Button></div>}
        </div>
      ) : (
        <>
          <Verdict d={d} c={c} open={open} onAward={onAward} />
          <Sheet d={d} c={c} open={open} onAward={(name) => onAward({ mode: 'one_supplier', supplier: name })} />
        </>
      )}
      <ComparisonDocModal statement={d} initial={d.suppliers.map((s) => s.supplier_name)} open={doc} onClose={() => setDoc(false)} />
    </section>
  )
}

/** The answer, said once: the cheapest total, by how much, and the button to give them the order. */
function Verdict({ d, c, open, onAward }: { d: Statement; c: Comparison; open: boolean; onAward: (p?: AwardPreset) => void }) {
  const { l1, split } = c
  const next = c.suppliers.find((s) => c.rank.get(s.supplier_name) === 'L2')
  const awards = [...split.winners].map(([rfq_line_id, supplier_name]) => ({ rfq_line_id, supplier_name }))
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-border bg-success/[0.06] px-5 py-3.5">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Trophy className="mt-0.5 size-5 shrink-0 text-success" />
        {l1 ? (
          <p className="text-sm">
            <span className="text-muted-foreground">Lowest total: </span><strong>{l1.supplier_name}</strong> <strong className="tabular text-success">{formatINR(l1.landed)}</strong>
            {next ? <span className="text-muted-foreground"> · {formatINR(next.landed - l1.landed)} less than {next.supplier_name}</span> : <span className="text-muted-foreground"> · the only full quote so far</span>}
            {c.splitSaving > 0.5 && <span className="block text-[13px] text-muted-foreground">Buying each item from whoever is cheapest for it would save {formatINR(c.splitSaving)} more, across {split.vendors} suppliers.</span>}
          </p>
        ) : <p className="text-sm text-muted-foreground">Nobody has quoted every item yet, so there is no single cheapest supplier. You can still split the order by item.</p>}
      </div>
      {open && (
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          {c.splitSaving > 0.5 || (!l1 && !split.uncovered.length) ? <Button size="sm" variant="outline" onClick={() => onAward({ mode: 'per_line', awards })}>Split by item</Button> : null}
          {l1 && <Button size="sm" onClick={() => onAward({ mode: 'one_supplier', supplier: l1.supplier_name })}>Award to {l1.supplier_name}</Button>}
        </div>
      )}
      {d.rfq.award_reason && <p className="basis-full text-[13px]"><strong>Why not the lowest:</strong> {d.rfq.award_reason}</p>}
    </div>
  )
}

/** Items down the side, suppliers across, the cheapest in each row in green, totals and terms underneath. */
function Sheet({ d, c, open, onAward }: { d: Statement; c: Comparison; open: boolean; onAward: (name: string) => void }) {
  const sups = c.suppliers
  const [checking, setChecking] = useState<RfqSupplier | null>(null)
  const col = 'min-w-40 border-l border-border px-4'
  const label = 'sticky left-0 z-10 bg-card px-5 text-left'
  const total = (s: RfqSupplier) => c.rank.get(s.supplier_name) === 'L1'
  return (
    <div className="overflow-x-auto border-t border-border">
      <table aria-label="Quotes compared" className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border bg-surface/60 align-top">
            <th scope="col" className={cn(label, 'min-w-48 bg-surface py-3 text-xs font-medium text-muted-foreground')}>Item</th>
            {sups.map((s) => (
              <th key={s.quote_id} scope="col" className={cn(col, 'py-3 text-left font-normal')}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-semibold" title={s.supplier_name}>{s.supplier_name}</span>
                      {total(s) && <span className="rounded bg-success px-1.5 py-px text-[10px] font-bold text-white" title="Lowest total for all items">Lowest</span>}
                      {!s.complete && <span className="rounded bg-warning/15 px-1.5 py-px text-[10px] font-medium text-warning" title={`Quoted ${s.lines_quoted} of ${d.lines.length} items`}>Part quote</span>}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
                      {s.quote_ref && <span>No. {s.quote_ref}</span>}
                      {s.quote_date && <span>{formatDate(s.quote_date)}</span>}
                      {s.document
                        ? <button type="button" onClick={() => setChecking(s)} className="inline-flex items-center gap-0.5 text-primary hover:underline" title={`Compare with ${s.document.name}`}><Columns2 className="size-3" />Compare with their quote</button>
                        : open && <span className="print:hidden"><AttachQuotation statement={d} supplier={s} /></span>}
                      {s.source === 'vendor' && <span title="Sent by the supplier through their link">via link</span>}
                    </div>
                  </div>
                  {open && <span className="print:hidden"><MasterDelete kind="rfq_quote" id={s.quote_id} label={`${s.supplier_name}'s quote`} noun="supplier quote" /></span>}
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
                  <div className="text-xs text-muted-foreground">{l.qty} {l.uom}{l.item_code && ` · ${l.item_code}`}</div>
                </th>
                {sups.map((s) => {
                  const o = l.offers.find((x) => x.supplier_name === s.supplier_name)
                  if (!o) return <td key={s.quote_id} className={cn(col, 'py-2.5 text-xs text-muted-foreground')}>Not quoted</td>
                  const best = low !== undefined && o.rate <= low + 0.0001 && sups.length > 1
                  return (
                    <td key={s.quote_id} className={cn(col, 'py-2.5 tabular', best && 'bg-success/[0.07]')}>
                      <div className={cn('font-medium', best && 'text-success')}>{formatINR(o.rate)} <span className="text-xs font-normal text-muted-foreground">/ {l.uom || 'unit'}</span></div>
                      <div className="text-xs text-muted-foreground">Amount {formatINR(o.amount)} · GST {o.tax_percent}%{o.remarks && ` · ${o.remarks}`}</div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
        <tfoot className="text-[13px]">
          {([['Items total', (s: RfqSupplier) => formatINR(s.basic)], ['GST', (s: RfqSupplier) => formatINR(s.tax)], ['Transport', (s: RfqSupplier) => (s.freight ? formatINR(s.freight) : '-')]] as const).map(([name, get]) => (
            <tr key={name} className="text-muted-foreground">
              <th scope="row" className={cn(label, 'py-1.5 font-normal')}>{name}</th>
              {sups.map((s) => <td key={s.quote_id} className={cn(col, 'py-1.5 tabular')}>{get(s)}</td>)}
            </tr>
          ))}
          <tr className="border-y border-border text-sm">
            <th scope="row" className={cn(label, 'py-2.5 font-semibold')}>Total at site</th>
            {sups.map((s) => <td key={s.quote_id} className={cn(col, 'py-2.5 font-semibold tabular', total(s) && 'bg-success/[0.07] text-success')}>{formatINR(s.landed)}</td>)}
          </tr>
          <tr>
            <th scope="row" className={cn(label, 'py-1.5 font-normal text-muted-foreground')}>Delivery</th>
            {sups.map((s) => <td key={s.quote_id} className={cn(col, 'py-1.5')}>{days(s.delivery_days)}</td>)}
          </tr>
          <tr>
            <th scope="row" className={cn(label, 'py-1.5 font-normal text-muted-foreground')}>Payment</th>
            {sups.map((s) => <td key={s.quote_id} className={cn(col, 'py-1.5')} title={s.payment_terms}><span className="line-clamp-2">{s.payment_terms || '-'}</span></td>)}
          </tr>
          {open && (
            <tr className="print:hidden">
              <th scope="row" className={label} />
              {sups.map((s) => (
                <td key={s.quote_id} className={cn(col, 'pb-4 pt-2')}>
                  <Button size="sm" variant={total(s) ? 'primary' : 'outline'} disabled={!s.complete} title={s.complete ? undefined : 'Only a supplier who quoted every item can take the whole order'} onClick={() => onAward(s.supplier_name)}>Award</Button>
                </td>
              ))}
            </tr>
          )}
        </tfoot>
      </table>
      {checking && <QuoteCheckModal statement={d} supplier={checking} onClose={() => setChecking(null)} />}
    </div>
  )
}
