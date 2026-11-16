import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Banknote } from 'lucide-react'
import { Badge, Button, Input, Modal, Skeleton } from '@/components/ui'
import { ledgerKeys } from '@/api/ledger'
import { owedKeys, useOwedPayables, useOwedReceivables } from '@/api/owed'
import { useJournals } from '@/api/journals'
import { bookKeys } from '@/api/books'
import { ExpenseModal, TransferModal } from '@/features/ledger/VoucherModals'
import { OnAccountModal } from '@/features/ledger/OnAccountModal'
import { PayModal } from '@/features/money/PayModal'
import { JournalModal } from '@/features/money/JournalModal'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { SHORTCUT, voucherTypesFor, type VoucherKind } from '@/lib/voucher'
import { formatINR } from '@/lib/utils'
import { useVoucher } from '@/stores/voucher'

/** A bill (or invoice, or release) that a payment or a receipt can be set against. */
interface Open {
  id: number
  doc_type: string
  number: string
  party: string
  project: string
  due_date: string
  outstanding: number
  bucket: string
  days_overdue: number
}

const REFRESH = [owedKeys.all, ['dashboard'], ledgerKeys.all, bookKeys.all]

/**
 * One screen for every voucher accounts passes. Pick the kind - Payment, Receipt, Contra, Expense, Other receipt,
 * Journal - and the form that kind already has opens: nothing here is a new form, so a voucher passed from here and one
 * passed from its own page are the same voucher. A payment or a receipt asks first which bill it is for, or whether it is
 * on account.
 */
export default function NewVoucher() {
  const hide = useVoucher((s) => s.hide)
  const { can } = useSession()
  const types = voucherTypesFor(can)
  const [kind, setKind] = useState<VoucherKind | null>(null)
  // A payment or receipt: against a bill (the one picked), or on account.
  const [against, setAgainst] = useState<Open | 'account' | null>(null)

  // While the list is showing, the key beside each kind picks it.
  useEffect(() => {
    if (kind) return
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return
      const t = types.find((x) => x.key === e.key.toLowerCase())
      if (t) { e.preventDefault(); setKind(t.kind) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [kind, types])

  const back = () => { setKind(null); setAgainst(null) }

  if (!kind) {
    return (
      <Modal open onOpenChange={(o) => !o && hide()} title="New voucher" size="lg" description={`What are you passing? Press the key shown, or click. (${SHORTCUT} opens this from any screen.)`}>
        <div className="grid gap-2.5 sm:grid-cols-2">
          {types.map((t) => (
            <button key={t.kind} type="button" onClick={() => setKind(t.kind)}
              className="group flex items-start gap-3 rounded-xl border border-border bg-card p-3.5 text-left transition-colors hover:border-primary/40 hover:bg-accent focus-visible:border-primary focus-visible:outline-none">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary"><t.icon className="size-[18px]" /></span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-semibold">{t.label}<kbd className="rounded border border-border bg-muted px-1.5 py-px text-[11px] font-medium uppercase text-muted-foreground">{t.key}</kbd></span>
                <span className="mt-0.5 block text-[13px] text-muted-foreground">{t.hint}</span>
              </span>
            </button>
          ))}
        </div>
      </Modal>
    )
  }

  if (kind === 'contra') return <TransferModal open onClose={hide} invalidate={REFRESH} />
  if (kind === 'expense' || kind === 'income') return <ExpenseModal kind={kind} onClose={hide} />
  if (kind === 'journal') return <JournalFlow onClose={hide} />

  // Payment or receipt.
  const paying = kind === 'payment'
  if (against === 'account') return <OnAccountModal direction={paying ? 'OUT' : 'IN'} onClose={hide} />
  if (against) return <PayModal docType={against.doc_type} docId={against.id} title={against.number} verb={paying ? 'Pay' : 'Receive'} open onOpenChange={(o) => !o && hide()} invalidate={REFRESH} />
  return (
    <Modal open onOpenChange={(o) => !o && hide()} size="lg" title={paying ? 'Payment voucher' : 'Receipt voucher'}
      description={paying ? 'Pick the bill this payment is for. With no bill behind it - an advance - record it on account.' : 'Pick the bill this money is against. With no bill behind it - money paid ahead - record it on account.'}>
      {paying ? <PayableList onPick={setAgainst} /> : <ReceivableList onPick={setAgainst} />}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={back}><ArrowLeft /> Another kind of voucher</Button>
        <Button variant="outline" onClick={() => setAgainst('account')}><Banknote /> On account, with no bill</Button>
      </div>
    </Modal>
  )
}

/** The journal form wants the books' own ledgers, which come with the journals list. */
function JournalFlow({ onClose }: { onClose: () => void }) {
  const q = useJournals(0)
  if (q.data) return <JournalModal ledgers={q.data.ledgers} defaultJob={0} onClose={onClose} />
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New journal voucher" size="lg">
      {q.isError ? <p role="alert" className="text-sm text-danger">Could not open the journal form. Try again.</p> : <Skeleton className="h-40 w-full" />}
    </Modal>
  )
}

function PayableList({ onPick }: { onPick: (o: Open) => void }) {
  const q = useOwedPayables()
  const all = q.data?.rows ?? []
  // A bill nobody has approved yet cannot be paid; it is counted, not hidden.
  const rows = all.filter((r) => r.doc_type && r.approved !== false).map((r): Open => ({ ...r, doc_type: r.doc_type!, party: r.party }))
  const waiting = all.length - rows.length
  const skipped = waiting > 0 ? `${waiting} bill${waiting === 1 ? '' : 's'} waiting for approval ${waiting === 1 ? 'is' : 'are'} not listed: they cannot be paid until approved.` : ''
  return <OpenBills rows={rows} loading={q.isPending} error={q.isError} skipped={skipped} who="supplier or contractor" empty="No bill is waiting to be paid." onPick={onPick} />
}

function ReceivableList({ onPick }: { onPick: (o: Open) => void }) {
  const q = useOwedReceivables()
  const all = q.data?.rows ?? []
  const rows = all.filter((r) => r.doc_type).map((r): Open => ({ ...r, doc_type: r.doc_type!, party: r.customer }))
  // A tax invoice has no receipt voucher: it is not a bill the money book settles.
  const other = all.length - rows.length
  const skipped = other > 0 ? `${other} invoice${other === 1 ? '' : 's'} on Pay & Receive ${other === 1 ? 'is' : 'are'} not listed: an invoice cannot be received by a voucher.` : ''
  return <OpenBills rows={rows} loading={q.isPending} error={q.isError} skipped={skipped} who="client" empty="No bill is waiting to be received." onPick={onPick} />
}

function OpenBills({ rows, loading, error, skipped, who, empty, onPick }: { rows: Open[]; loading: boolean; error: boolean; skipped: string; who: string; empty: string; onPick: (o: Open) => void }) {
  const [q, setQ] = useState('')
  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    return rows.filter((r) => words.every((w) => `${r.party} ${r.number} ${r.project}`.toLowerCase().includes(w)))
  }, [rows, q])
  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <p role="alert" className="text-sm text-danger">Could not read the open bills. Try again.</p>
  return (
    <div>
      <Input aria-label="Find a bill" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search by ${who}, bill number or project...`} className="mb-3" />
      {!rows.length ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">{empty}</p> : !shown.length ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">No bill matches that.</p>
      ) : (
        <ul className="max-h-72 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {shown.map((r) => (
            <li key={`${r.doc_type}-${r.id}`}>
              <button type="button" onClick={() => onPick(r)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{r.party || '-'}</span>
                  <span className="block truncate text-xs text-muted-foreground">{r.number}{r.project ? ` - ${r.project}` : ''}{r.due_date ? ` - due ${formatDate(r.due_date)}` : ''}</span>
                </span>
                <span className="text-right">
                  <span className="tabular block text-sm font-semibold">{formatINR(r.outstanding)}</span>
                  <Badge tone={r.bucket === 'Not due' ? 'neutral' : r.days_overdue > 60 ? 'danger' : 'warning'} className="mt-0.5">{r.bucket === 'Not due' ? 'not due' : `${r.days_overdue} days late`}</Badge>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {skipped && <p className="mt-2 text-xs text-muted-foreground">{skipped}</p>}
    </div>
  )
}
