import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { ArrowLeftRight, FileText, MinusCircle, PlusCircle } from 'lucide-react'
import { Button, ConfirmDialog, Stat, StatGrid } from '@/components/ui'
import { entryAgainst, ledgerKeys, PARTY_LABEL, useEntries, voidEntry, voucherUrl, type Entry } from '@/api/ledger'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { ExpenseModal, TransferModal } from './VoucherModals'

/** Every receipt, payment, expense and transfer, newest first, each with its voucher. A wrong one is voided - kept, struck
    through, and the bill goes back to owing. */
export function EntriesTab() {
  const { can } = useSession()
  const q = useEntries()
  const [voiding, setVoiding] = useState<Entry | null>(null)
  const [voucher, setVoucher] = useState<'expense' | 'income' | null>(null)
  const [transferring, setTransferring] = useState(false)
  const act = useAction((a: { e: Entry; reason: string }) => voidEntry(a.e.id, a.reason), { invalidate: [ledgerKeys.all, ['owed']], onSuccess: () => setVoiding(null) })
  const rows = q.data?.entries ?? []
  const filters = useListFilters(rows, { search: (e) => [e.number, e.party_name, e.doc_number, e.head, e.mode, e.reference, e.account, e.note].join(' '), date: (e) => e.paid_on })
  const s = q.data?.summary
  const strike = (e: Entry) => cn(e.voided && 'line-through opacity-55')

  const columns: TableColumn<Entry>[] = [
    { id: 'date', header: 'Date', sort: (e) => e.paid_on, cell: (e) => <span className={strike(e)}>{formatDate(e.paid_on)}</span> },
    { id: 'no', header: 'No.', cell: (e) => <span className={cn('font-mono text-[13px]', strike(e))}>{e.number}</span> },
    { id: 'party', header: 'Party', cell: (e) => <div className={strike(e)}>{e.party_name}<div className="text-xs text-muted-foreground">{e.doc_type === 'contra' ? (e.direction === 'IN' ? 'From our account' : 'To our account') : e.doc_type === 'expense' ? 'Expense' : e.doc_type === 'income' ? 'Other receipt' : PARTY_LABEL[e.party_type] ?? ''}</div></div> },
    { id: 'against', header: 'Against', hideBelow: 'md', cell: (e) => <div>{entryAgainst(e)}{e.note && (e.head || e.doc_type === 'contra') && <div className="max-w-56 truncate text-xs text-muted-foreground" title={e.note}>{e.note}</div>}</div> },
    { id: 'mode', header: 'Mode', hideBelow: 'lg', cell: (e) => <div className="text-[13px]">{e.mode}{e.reference && <div className="text-xs text-muted-foreground">{e.reference}</div>}{e.account && <div className="text-xs text-muted-foreground">{e.account}</div>}</div> },
    { id: 'in', header: 'In', align: 'right', cell: (e) => (e.direction === 'IN' ? <span className={strike(e)}>{formatINR(e.amount)}</span> : '') },
    { id: 'out', header: 'Out', align: 'right', cell: (e) => (e.direction === 'OUT' ? <span className={strike(e)}>{formatINR(e.amount)}</span> : '') },
    { id: 'voucher', header: '', align: 'right', width: '3rem', cell: (e) => <Button size="icon-sm" variant="ghost" asChild><a href={voucherUrl(e.id)} target="_blank" rel="noreferrer" aria-label={`Voucher ${e.number}`} title="Print the voucher"><FileText /></a></Button> },
    { id: 'act', header: '', align: 'right', cell: (e) => (e.voided ? <span className="text-xs text-muted-foreground" title={e.void_reason}>void</span> : can('bills.pay') ? <Button size="sm" variant="outline" onClick={() => setVoiding(e)}>Void</Button> : null) },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="payment" id={r.id} label={String(r.number)} noun="payment" /> },
  ]

  return (
    <>
      {can('bills.pay') && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setVoucher('expense')}><MinusCircle /> Expense voucher</Button>
          <Button size="sm" variant="outline" onClick={() => setVoucher('income')}><PlusCircle /> Other receipt</Button>
          <Button size="sm" variant="outline" onClick={() => setTransferring(true)}><ArrowLeftRight /> Bank / cash transfer</Button>
        </div>
      )}
      <StatGrid className="xl:grid-cols-5">
        <Stat label="Received" value={compactINR(s?.received)} loading={q.isPending} />
        <Stat label="Paid out" value={compactINR(s?.paid)} sub={s?.expenses ? `${compactINR(s.expenses)} of it expenses` : undefined} loading={q.isPending} />
        <Stat label="Net" value={compactINR((s?.received ?? 0) - (s?.paid ?? 0))} loading={q.isPending} />
        <Stat label="Moved between accounts" value={compactINR(s?.transferred)} loading={q.isPending} />
        <Stat label="Entries" value={s?.entries ?? 0} loading={q.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by number, party, bill or reference..." />
      <DataTable label="Receipts and payments" rows={filters.filtered} columns={columns} rowKey={(e) => e.id} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'Nothing received or paid yet. Record it from a bill, or on account from the Parties tab.'} />
      <ExpenseModal kind={voucher} onClose={() => setVoucher(null)} />
      <TransferModal open={transferring} onClose={() => setTransferring(false)} />
      <ConfirmDialog open={!!voiding} onOpenChange={(o) => !o && setVoiding(null)} title={`Void ${voiding?.number ?? ''}?`} description={voiding?.doc_type === 'contra' ? 'It is kept, struck through, and taken out of both accounts.' : 'It is kept, struck through, and the bill goes back to owing.'} confirmLabel="Void it" tone="danger" reason={{ label: 'Why is this being voided?', required: true }} loading={act.isPending} onConfirm={(reason) => { if (voiding) act.mutate({ e: voiding, reason }) }} />
    </>
  )
}
