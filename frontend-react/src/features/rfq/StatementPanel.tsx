import { FileSpreadsheet, Plus, Printer, ScanText } from 'lucide-react'
import { Button, Skeleton } from '@/components/ui'
import { useStatement } from '@/api/rfq'
import { Recommendation } from './AiQuotes'
import { formatINR } from '@/lib/utils'

/** Lines down the side, suppliers across the top, the lowest in each row marked, and each supplier's total landed at site underneath. */
export function StatementPanel({ id, onClose, onQuote, onRead, onAward }: { id: number; onClose: () => void; onQuote: () => void; onRead: () => void; onAward: () => void }) {
  const q = useStatement(id)
  const d = q.data
  if (q.isPending || !d) return <Skeleton className="mt-6 h-48 w-full" />
  const open = d.rfq.status === 'OPEN'
  const sups = d.suppliers
  const th = 'px-3 py-2 text-right text-xs font-medium text-muted-foreground'
  return (
    <section aria-label={`Comparative statement ${d.rfq.number}`} className="mt-6 rounded-xl border border-border bg-card shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
        <h2 className="font-semibold">Comparative statement - {d.rfq.number} {d.rfq.title}</h2>
        <div className="flex flex-wrap gap-2">
          {open && <Button size="sm" variant="outline" onClick={onRead}><ScanText /> Read a quote</Button>}
          {open && <Button size="sm" variant="outline" onClick={onQuote}><Plus /> Quote</Button>}
          {open && sups.length > 0 && <Button size="sm" onClick={onAward}>Award</Button>}
          <Button size="sm" variant="outline" asChild><a href={`/api/rfqs/${id}/comparison.xlsx`}><FileSpreadsheet /> Comparison</a></Button>
          <Button size="sm" variant="outline" onClick={() => window.print()}><Printer /> Print</Button>
          <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
      {sups.length > 0 && <Recommendation id={id} />}
      {sups.length > 0 && <p className="px-5 py-3 text-[13px]">{d.l1 && <>L1 landed: <strong>{d.l1}</strong> at {formatINR(d.l1_landed)}{d.saving_vs_l2 > 0 && ` - ${formatINR(d.saving_vs_l2)} under L2`}. </>}Lowest in every line, from whoever quoted it: {formatINR(d.lowest_per_line_basic)} basic.{d.rfq.award_reason && <span className="mt-1 block"><strong>Why not the lowest:</strong> {d.rfq.award_reason}</span>}</p>}
      <div className="overflow-x-auto">
        <table aria-label="Comparison" className="w-full text-[13px]">
          <thead className="bg-surface"><tr><th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Item</th><th className={th}>Qty</th>{sups.map((s) => <th key={s.supplier_name} className={`${th} min-w-32`}>{s.supplier_name}{s.rank && <span className={`ml-1 rounded px-1.5 py-0.5 text-[10px] ${s.is_l1 ? 'bg-success text-white' : 'bg-muted'}`}>{s.rank}</span>}</th>)}</tr></thead>
          <tbody>
            {d.lines.map((l) => (
              <tr key={l.rfq_line_id} className="border-t border-border">
                <td className="px-3 py-2">{l.description}<div className="text-[11px] text-muted-foreground">{l.item_code}{l.spread_percent > 0 && ` - spread ${l.spread_percent}%`}{l.awarded_supplier && <> - <strong>awarded {l.awarded_supplier}</strong></>}</div></td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular">{l.qty} {l.uom}</td>
                {sups.map((s) => {
                  const o = l.offers.find((x) => x.supplier_name === s.supplier_name)
                  if (!o) return <td key={s.supplier_name} className="px-3 py-2 text-right text-muted-foreground">not quoted</td>
                  return <td key={s.supplier_name} className={`whitespace-nowrap px-3 py-2 text-right tabular ${o.supplier_name === l.lowest ? 'bg-success/10 font-bold' : ''}`}>{formatINR(o.rate)}<div className="text-[11px] font-normal text-muted-foreground">{formatINR(o.amount)} +{o.tax_percent}%</div></td>
                })}
              </tr>
            ))}
          </tbody>
          {sups.length > 0 && (
            <tfoot>
              {([['Basic', 'basic'], ['Tax', 'tax'], ['Freight', 'freight'], ['Landed at site', 'landed']] as const).map(([label, key]) => (
                <tr key={key} className={key === 'landed' ? 'border-t-2 border-border font-bold' : ''}><td colSpan={2} className="px-3 py-1.5 text-right">{label}</td>{sups.map((s) => <td key={s.supplier_name} className={`whitespace-nowrap px-3 py-1.5 text-right tabular ${s.is_l1 && key === 'landed' ? 'text-success' : ''}`}>{formatINR(s[key])}</td>)}</tr>
              ))}
              <tr><td colSpan={2} className="px-3 py-1.5 text-right text-xs">Delivery / payment</td>{sups.map((s) => <td key={s.supplier_name} className="px-3 py-1.5 text-right text-xs">{s.delivery_days ? `${s.delivery_days} days` : '-'}<br />{s.payment_terms || '-'}{!s.complete && <><br /><span className="text-warning">incomplete</span></>}</td>)}</tr>
            </tfoot>
          )}
        </table>
      </div>
      {sups.length === 0 && <p className="p-5 text-sm text-muted-foreground">No quotes yet. Record each supplier's answer with Quote.</p>}
    </section>
  )
}
