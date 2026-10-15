import { CalendarClock, FileText, Truck, X } from 'lucide-react'
import { Badge, Button } from '@/components/ui'
import type { RfqSupplier, Statement } from '@/api/rfq'
import { cellTone, type Comparison } from '@/lib/rfqCompare'
import { formatDate } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

export interface ViewProps {
  d: Statement
  c: Comparison
  /** The enquiry is still open: quotes can be taken away and awards made. */
  open: boolean
  onRemove: (name: string) => void
  onAwardVendor: (name: string) => void
}

const days = (s: RfqSupplier) => (s.delivery_days ? `${s.delivery_days} days` : 'Not stated')
const missing = (d: Statement, s: RfqSupplier) => d.lines.length - s.lines_quoted
const ref = (s: RfqSupplier) => [s.quote_ref, s.quote_date && formatDate(s.quote_date)].filter(Boolean).join(' · ')

function RankBadge({ rank }: { rank?: string }) {
  if (!rank) return <Badge tone="warning">Part quote</Badge>
  return <span title={rank === 'L1' ? 'L1: the lowest total for all items' : `${rank}: number ${rank.slice(1)} from the lowest total`} className={cn('rounded px-1.5 py-0.5 text-[10px] font-bold', rank === 'L1' ? 'bg-success text-white' : 'bg-muted text-muted-foreground')}>{rank}</span>
}

/** The supplier's own quotation file, and whether the supplier sent it through their link. */
function QuoteFile({ s }: { s: RfqSupplier }) {
  if (!s.document && s.source !== 'vendor') return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] print:hidden">
      {s.document && <a href={`/api/files/${s.document.id}`} target="_blank" rel="noopener" className="inline-flex items-center gap-1 font-medium text-primary underline-offset-2 hover:underline" title={s.document.name}><FileText className="size-3" /> Their quotation</a>}
      {s.source === 'vendor' && <span className="rounded bg-info/10 px-1 text-info">sent by the supplier</span>}
    </div>
  )
}

function Coverage({ d, s }: { d: Statement; s: RfqSupplier }) {
  const gap = missing(d, s)
  return gap ? <Badge tone="warning">{gap} {gap === 1 ? 'item' : 'items'} missing</Badge> : <span className="text-[11px] text-success">All items quoted</span>
}

// Item and quantity stay put while the vendors scroll past; the item's width fixes where the quantity sticks.
// A phone has room to pin only a narrow item column.
const stickItem = 'sticky left-0 z-10 w-36 min-w-36 bg-card shadow-[inset_-1px_0_0_var(--color-border)] sm:w-64 sm:min-w-64 sm:shadow-none'
const stickQty = 'z-10 bg-card sm:sticky sm:left-64 sm:shadow-[inset_-1px_0_0_var(--color-border)]'

/** Lines down the side, up to six vendors across, the lowest in each row among them marked, and their totals underneath. */
export function ComparisonMatrix({ d, c, open, onRemove, onAwardVendor }: ViewProps) {
  const sups = c.suppliers
  const head = 'sticky top-0 z-20 bg-surface'
  return (
    <div className="max-h-[75vh] overflow-auto print:max-h-none print:overflow-visible">
      <table aria-label="Comparison" className="w-full text-[13px]">
        <thead>
          <tr>
            <th className={cn(head, stickItem, 'z-30 bg-surface px-3 py-2 text-left align-bottom text-xs font-medium text-muted-foreground')}>Item</th>
            <th className={cn(head, stickQty, 'z-30 bg-surface px-3 py-2 text-right align-bottom text-xs font-medium text-muted-foreground')}>Qty</th>
            {sups.map((s) => {
              const rank = c.rank.get(s.supplier_name)
              return (
                <th key={s.supplier_name} scope="col" className={cn(head, 'min-w-44 px-2 py-2 text-left align-top font-normal')}>
                  <div className={cn('rounded-lg border bg-card p-2.5', rank === 'L1' ? 'border-success/50 ring-1 ring-success/30' : 'border-border')}>
                    <div className="flex items-start gap-1.5">
                      <RankBadge rank={rank} />
                      <span className="min-w-0 flex-1 truncate font-semibold" title={s.supplier_name}>{s.supplier_name}</span>
                      {open && <MasterDelete kind="rfq_quote" id={s.quote_id} label={`${s.supplier_name}'s quote`} noun="supplier quote" />}
                      {sups.length > 1 && <button type="button" aria-label={`Stop comparing ${s.supplier_name}`} title="Take out of the comparison" onClick={() => onRemove(s.supplier_name)} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground print:hidden"><X className="size-3.5" /></button>}
                    </div>
                    {ref(s) && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{ref(s)}</div>}
                    <QuoteFile s={s} />
                    <div className={cn('mt-1.5 text-[15px] font-bold tabular', rank === 'L1' && 'text-success')} title="Total at site: rates + GST + transport">{formatINR(s.landed)}</div>
                    <div className="mt-1 grid gap-0.5 text-[11px] text-muted-foreground">
                      <span className="flex items-center gap-1"><Truck className="size-3" /> {days(s)}</span>
                      <span className="flex items-center gap-1 truncate" title={s.payment_terms}><CalendarClock className="size-3 shrink-0" /> {s.payment_terms || 'Terms not stated'}</span>
                    </div>
                    <div className="mt-1.5"><Coverage d={d} s={s} /></div>
                  </div>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {d.lines.map((l) => {
            const low = c.lowest.get(l.rfq_line_id)
            return (
              <tr key={l.rfq_line_id} className="border-t border-border">
                <td className={cn(stickItem, 'px-3 py-2')}>{l.description}<div className="text-[11px] text-muted-foreground">{l.item_code}{l.spread_percent > 0 && ` - spread ${l.spread_percent}%`}{l.awarded_supplier && <> - <strong>awarded {l.awarded_supplier}</strong></>}</div></td>
                <td className={cn(stickQty, 'whitespace-nowrap px-3 py-2 text-right tabular')}>{l.qty} {l.uom}</td>
                {sups.map((s) => {
                  const o = l.offers.find((x) => x.supplier_name === s.supplier_name)
                  if (!o) return <td key={s.supplier_name} className="px-3 py-2 text-right"><span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">— Not quoted</span></td>
                  const tone = cellTone(o.rate, low)
                  return (
                    <td key={s.supplier_name} className="whitespace-nowrap px-3 py-2 text-right tabular">
                      <span className={cn('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5', tone === 'best' && 'bg-success/10 font-bold text-success', tone === 'high' && 'bg-warning/10 text-warning')} title={tone === 'best' ? 'Lowest among the vendors compared' : tone === 'high' ? `More than 25% over the lowest (${formatINR(low)})` : undefined}>
                        {tone === 'high' && <span aria-hidden className="size-1.5 rounded-full bg-warning" />}
                        {formatINR(o.rate)}
                      </span>
                      <div className="text-[11px] text-muted-foreground">{formatINR(o.amount)} +{o.tax_percent}% GST</div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
        {sups.length > 0 && <tfoot className="sticky bottom-0 z-20 bg-card shadow-[0_-1px_0_var(--color-border)] print:static">
          {([['Basic', 'basic'], ['GST / tax', 'tax'], ['Transport', 'freight'], ['Total at site', 'landed']] as const).map(([label, k]) => (
            <tr key={k} className={k === 'landed' ? 'border-t-2 border-border font-bold' : ''}>
              <td className={cn(stickItem, 'px-3 py-1.5 text-right')}>{label}</td><td className={stickQty} />
              {sups.map((s) => <td key={s.supplier_name} className={cn('whitespace-nowrap px-3 py-1.5 text-right tabular', k === 'landed' && c.rank.get(s.supplier_name) === 'L1' && 'bg-success/10 text-success')}>{formatINR(s[k])}</td>)}
            </tr>
          ))}
          <tr className="text-xs">
            <td className={cn(stickItem, 'px-3 py-1.5 text-right')}>Delivery / payment</td><td className={stickQty} />
            {sups.map((s) => <td key={s.supplier_name} className="px-3 py-1.5 text-right">{days(s)}<br /><span className="text-muted-foreground">{s.payment_terms || '-'}</span>{!s.complete && <><br /><span className="text-warning">incomplete</span></>}</td>)}
          </tr>
          {open && (
            <tr className="print:hidden">
              <td className={stickItem} /><td className={stickQty} />
              {sups.map((s) => <td key={s.supplier_name} className="px-3 pb-2 pt-1 text-right"><Button size="sm" variant={c.rank.get(s.supplier_name) === 'L1' ? 'primary' : 'outline'} disabled={!s.complete} title={s.complete ? undefined : 'Only a supplier who quoted every line can take the whole order'} onClick={() => onAwardVendor(s.supplier_name)}>Award this vendor</Button></td>)}
            </tr>
          )}
        </tfoot>}
      </table>
    </div>
  )
}

/** One card a vendor: where they rank, what makes up their landed total, their terms and how much of the enquiry they covered. */
export function Scorecards({ d, c, open, onRemove, onAwardVendor }: ViewProps) {
  return (
    <ul aria-label="Scorecards" className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
      {c.suppliers.map((s) => {
        const rank = c.rank.get(s.supplier_name)
        const won = [...c.split.winners.values()].filter((n) => n === s.supplier_name).length
        const pct = d.lines.length ? Math.round((s.lines_quoted / d.lines.length) * 100) : 0
        return (
          <li key={s.supplier_name} aria-label={s.supplier_name} className={cn('flex flex-col rounded-xl border bg-card p-4 shadow-card', rank === 'L1' ? 'border-success/50 ring-1 ring-success/30' : 'border-border')}>
            <div className="flex items-start gap-2">
              <RankBadge rank={rank} />
              <div className="min-w-0 flex-1"><div className="truncate font-semibold">{s.supplier_name}</div>{ref(s) && <div className="text-[11px] text-muted-foreground">{ref(s)}</div>}<QuoteFile s={s} /></div>
              {c.suppliers.length > 1 && <button type="button" aria-label={`Stop comparing ${s.supplier_name}`} onClick={() => onRemove(s.supplier_name)} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"><X className="size-4" /></button>}
            </div>
            <div className={cn('mt-3 text-2xl font-bold tabular', rank === 'L1' && 'text-success')}>{formatINR(s.landed)}</div>
            <div className="text-[11px] text-muted-foreground">total at site (rates + GST + transport)</div>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
              <dt className="text-muted-foreground">Basic</dt><dd className="text-right tabular">{formatINR(s.basic)}</dd>
              <dt className="text-muted-foreground">GST / tax</dt><dd className="text-right tabular">{formatINR(s.tax)}</dd>
              <dt className="text-muted-foreground">Transport</dt><dd className="text-right tabular">{formatINR(s.freight)}</dd>
              <dt className="text-muted-foreground">Delivery</dt><dd className="text-right">{days(s)}</dd>
              <dt className="text-muted-foreground">Payment</dt><dd className="truncate text-right" title={s.payment_terms}>{s.payment_terms || 'Not stated'}</dd>
              <dt className="text-muted-foreground">Lowest on</dt><dd className="text-right">{won} of {d.lines.length} lines</dd>
            </dl>
            <div className="mt-3">
              <div className="flex items-center justify-between text-[11px]"><span className="text-muted-foreground">Quoted {s.lines_quoted} of {d.lines.length} lines</span><Coverage d={d} s={s} /></div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className={cn('h-full rounded-full', s.complete ? 'bg-success' : 'bg-warning')} style={{ width: `${pct}%` }} /></div>
            </div>
            {open && <Button className="mt-4" size="sm" variant={rank === 'L1' ? 'primary' : 'outline'} disabled={!s.complete} onClick={() => onAwardVendor(s.supplier_name)}>Award this vendor</Button>}
          </li>
        )
      })}
    </ul>
  )
}
