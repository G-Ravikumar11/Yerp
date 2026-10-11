import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Button, ConfirmDialog, Stat, StatGrid } from '@/components/ui'
import { ledgerKeys, PARTY_LABEL, useEntries, voidEntry, type Entry } from '@/api/ledger'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

/** Every receipt and payment, newest first. A wrong one is voided - kept, struck through, and the bill goes back to owing. */
export function EntriesTab() {
  const { can } = useSession()
  const q = useEntries()
  const [voiding, setVoiding] = useState<Entry | null>(null)
  const act = useAction((a: { e: Entry; reason: string }) => voidEntry(a.e.id, a.reason), { invalidate: [ledgerKeys.all, ['owed']], onSuccess: () => setVoiding(null) })
  const rows = q.data?.entries ?? []
  const filters = useListFilters(rows, { search: (e) => [e.number, e.party_name, e.doc_number, e.mode, e.reference, e.account].join(' '), date: (e) => e.paid_on })
  const s = q.data?.summary
  const strike = (e: Entry) => cn(e.voided && 'line-through opacity-55')

  const columns: TableColumn<Entry>[] = [
    { id: 'date', header: 'Date', sort: (e) => e.paid_on, cell: (e) => <span className={strike(e)}>{formatDate(e.paid_on)}</span> },
    { id: 'no', header: 'No.', cell: (e) => <span className={cn('font-mono text-[13px]', strike(e))}>{e.number}</span> },
    { id: 'party', header: 'Party', cell: (e) => <div className={strike(e)}>{e.party_name}<div className="text-xs text-muted-foreground">{PARTY_LABEL[e.party_type] ?? ''}</div></div> },
    { id: 'against', header: 'Against', hideBelow: 'md', cell: (e) => e.doc_number || 'on account' },
    { id: 'mode', header: 'Mode', hideBelow: 'lg', cell: (e) => <div className="text-[13px]">{e.mode}{e.reference && <div className="text-xs text-muted-foreground">{e.reference}</div>}{e.account && <div className="text-xs text-muted-foreground">{e.account}</div>}</div> },
    { id: 'in', header: 'In', align: 'right', cell: (e) => (e.direction === 'IN' ? <span className={strike(e)}>{formatINR(e.amount)}</span> : '') },
    { id: 'out', header: 'Out', align: 'right', cell: (e) => (e.direction === 'OUT' ? <span className={strike(e)}>{formatINR(e.amount)}</span> : '') },
    { id: 'act', header: '', align: 'right', cell: (e) => (e.voided ? <span className="text-xs text-muted-foreground" title={e.void_reason}>void</span> : can('bills.pay') ? <Button size="sm" variant="outline" onClick={() => setVoiding(e)}>Void</Button> : null) },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="payment" id={r.id} label={String(r.number)} noun="payment" /> },
  ]

  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Received" value={compactINR(s?.received)} loading={q.isPending} />
        <Stat label="Paid out" value={compactINR(s?.paid)} loading={q.isPending} />
        <Stat label="Net" value={compactINR((s?.received ?? 0) - (s?.paid ?? 0))} loading={q.isPending} />
        <Stat label="Entries" value={s?.entries ?? 0} loading={q.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by number, party, bill or reference..." />
      <DataTable label="Receipts and payments" rows={filters.filtered} columns={columns} rowKey={(e) => e.id} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'Nothing received or paid yet. Record it from a bill, or on account from the Parties tab.'} />
      <ConfirmDialog open={!!voiding} onOpenChange={(o) => !o && setVoiding(null)} title={`Void ${voiding?.number ?? ''}?`} description="It is kept, struck through, and the bill goes back to owing." confirmLabel="Void it" tone="danger" reason={{ label: 'Why is this being voided?', required: true }} loading={act.isPending} onConfirm={(reason) => { if (voiding) act.mutate({ e: voiding, reason }) }} />
    </>
  )
}
