import { Download } from 'lucide-react'
import { Button, Modal, Skeleton } from '@/components/ui'
import { PARTY_LABEL, useStatementOfAccount, type PartyType } from '@/api/ledger'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const th = 'px-3 py-2'

/** A statement of account: the bills and the money, in date order, with the running balance. */
export function StatementModal({ target, onClose }: { target: { type: PartyType; party: string } | null; onClose: () => void }) {
  const q = useStatementOfAccount(target?.type ?? '', target?.party ?? '', !!target)
  const d = q.data
  const weOwe = target?.type !== 'client'
  return (
    <Modal open={!!target} onOpenChange={(o) => !o && onClose()} size="xl" title={target ? `Statement - ${target.party}` : 'Statement'} description={target ? PARTY_LABEL[target.type] : undefined}>
      {!d ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <div>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="text-muted-foreground">{[d.master.gstin && `GSTIN ${d.master.gstin}`, d.master.pan && `PAN ${d.master.pan}`, d.master.phone].filter(Boolean).join(' · ') || ' '}</div>
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/ledger/statement.pdf?party_type=${encodeURIComponent(d.party_type)}&party=${encodeURIComponent(d.party)}`} target="_blank" rel="noopener"><Download /> PDF</a>
            </Button>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border bg-surface text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className={th}>Date</th><th className={th}>Particulars</th><th className={th}>No.</th>
                  <th className={`${th} text-right`}>{weOwe ? 'Their bills' : 'Our bills'}</th><th className={`${th} text-right`}>{weOwe ? 'Paid by us' : 'Received'}</th><th className={`${th} text-right`}>Balance</th>
                </tr>
              </thead>
              <tbody>
                {d.opening !== 0 && <tr className="border-b border-border"><td /><td className={`${th} italic`}>Opening balance</td><td /><td /><td /><td className={`${th} tabular text-right`}>{formatINR(d.opening)}</td></tr>}
                {d.rows.map((r, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    <td className={`${th} whitespace-nowrap`}>{formatDate(r.date)}</td>
                    <td className={th}>{r.kind}{r.against && r.against !== r.number && <span className="text-muted-foreground"> against {r.against}</span>}{r.reference && <span className="text-muted-foreground"> {r.reference}</span>}</td>
                    <td className={`${th} font-mono text-xs`}>{r.number}</td>
                    <td className={`${th} tabular text-right`}>{r.billed ? formatINR(r.billed) : ''}</td>
                    <td className={`${th} tabular text-right`}>{r.moved ? formatINR(r.moved) : ''}</td>
                    <td className={`${th} tabular text-right`}>{formatINR(r.balance)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-surface font-bold"><td colSpan={3} className={`${th} text-right`}>Totals</td><td className={`${th} tabular text-right`}>{formatINR(d.billed)}</td><td className={`${th} tabular text-right`}>{formatINR(d.moved)}</td><td className={`${th} tabular text-right`}>{formatINR(d.closing)}</td></tr>
              </tfoot>
            </table>
          </div>
          <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-sm">
            <strong>{d.closing > 0 ? (weOwe ? 'Balance payable by us: ' : 'Balance due from you: ') : d.closing < 0 ? (weOwe ? 'Advance with you: ' : 'Paid in advance: ') : 'Settled: '}</strong>
            {formatINR(Math.abs(d.closing))}{d.closing_words ? ` - ${d.closing_words}` : ''}
          </p>
        </div>
      )}
    </Modal>
  )
}
