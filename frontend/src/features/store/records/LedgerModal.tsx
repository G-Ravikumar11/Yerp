import { Modal, Skeleton } from '@/components/ui'
import { useLedger } from '@/api/stock'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** Every movement of one item, with the balance after each. The balance is the sum of the movements; corrections are posted, never edited. */
export function LedgerModal({ code, onClose }: { code: string | null; onClose: () => void }) {
  const q = useLedger(code)
  const d = q.data
  return (
    <Modal open={!!code} onOpenChange={(o) => !o && onClose()} title={d ? `${code} - ${d.item_name}` : (code ?? '')} description={d ? `${d.on_hand} ${d.uom} on hand - ${formatINR(d.rate)} each - ${formatINR(d.value)} in the store` : undefined} size="xl">
      {!d ? <Skeleton className="h-40 w-full" /> : (
        <div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
          <table aria-label="Movements" className="w-full text-[13px]">
            <thead className="sticky top-0 bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Kind</th><th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Rate</th><th className="px-3 py-2 text-right">Balance</th><th className="px-3 py-2">Reference</th><th className="px-3 py-2">Remarks</th></tr></thead>
            <tbody>
              {d.movements.length === 0 && <tr><td colSpan={7} className="px-3 py-5 text-center text-muted-foreground">No movements.</td></tr>}
              {d.movements.map((m, i) => <tr key={i} className="border-t border-border"><td className="px-3 py-2">{formatDate(m.moved_on)}</td><td className="px-3 py-2 capitalize">{m.kind.toLowerCase()}</td><td className={`px-3 py-2 text-right tabular ${m.quantity < 0 ? 'text-warning' : ''}`}>{m.quantity}</td><td className="px-3 py-2 text-right tabular">{formatINR(m.rate)}</td><td className="px-3 py-2 text-right font-semibold tabular">{m.balance}</td><td className="px-3 py-2 font-mono text-xs">{m.source_ref || '-'}</td><td className="px-3 py-2">{m.remarks}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
