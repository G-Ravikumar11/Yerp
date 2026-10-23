import { useState } from 'react'
import { FileText } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Input, Stat, StatGrid, Tabs } from '@/components/ui'
import { ledgerKeys, voidEntry, voucherUrl } from '@/api/ledger'
import { clearEntry, recoKeys, useCheques, type Cheque, type ChequeStatus } from '@/api/bankreco'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

const TONE: Record<ChequeStatus, 'warning' | 'success' | 'danger' | 'neutral' | 'ember'> = {
  PENDING: 'warning', CLEARED: 'success', STALE: 'ember', BOUNCED: 'danger', CANCELLED: 'neutral',
}
const LABEL: Record<ChequeStatus, string> = { PENDING: 'Not presented yet', CLEARED: 'Cleared', STALE: 'Stale (over 3 months)', BOUNCED: 'Bounced', CANCELLED: 'Cancelled' }
const FILTERS = [{ value: '', label: 'All' }, { value: 'PENDING', label: 'Pending' }, { value: 'STALE', label: 'Stale' }, { value: 'BOUNCED', label: 'Bounced' }]

/**
 * Every cheque written or received, and where it stands. A cheque written more than three months ago and never
 * presented is stale: the bank will not honour it, so it is cancelled and written again. A cheque received and
 * returned unpaid is marked bounced: the receipt is voided and the bill owes again.
 */
export function ChequesTab() {
  const { can } = useSession()
  const [filter, setFilter] = useState('')
  const q = useCheques(filter)
  const [on, setOn] = useState<Record<number, string>>({})
  const [bouncing, setBouncing] = useState<Cheque | null>(null)
  const done = { invalidate: [recoKeys.all, ledgerKeys.all, ['owed']] }
  const clear = useAction((a: { id: number; on: string }) => clearEntry(a.id, a.on), done)
  const bounce = useAction((a: { c: Cheque; why: string }) => voidEntry(a.c.id, `Cheque bounced: ${a.why}`), { ...done, onSuccess: () => setBouncing(null) })
  const s = q.data?.summary

  const columns: TableColumn<Cheque>[] = [
    { id: 'no', header: 'Cheque', cell: (c) => <div><span className="font-mono">{c.reference || '-'}</span><div className="text-xs text-muted-foreground">{formatDate(c.paid_on)} · {c.number}</div></div> },
    { id: 'way', header: '', cell: (c) => <Badge tone={c.direction === 'IN' ? 'info' : 'neutral'}>{c.direction === 'IN' ? 'Received' : 'Issued'}</Badge> },
    { id: 'party', header: 'Party', cell: (c) => <div>{c.party_name}<div className="text-xs text-muted-foreground">{c.doc_number || c.head || (c.doc_type === 'contra' ? 'Transfer' : 'on account')}</div></div> },
    { id: 'acct', header: 'Account', hideBelow: 'lg', cell: (c) => c.account },
    { id: 'amount', header: 'Amount', align: 'right', cell: (c) => <span className="tabular-nums">{formatINR(c.amount)}</span> },
    { id: 'status', header: 'Where it is', cell: (c) => <div><Badge tone={TONE[c.status]} dot>{LABEL[c.status]}</Badge>{c.cleared_on && <div className="text-xs text-muted-foreground">on {formatDate(c.cleared_on)}</div>}{c.void_reason && c.status !== 'CLEARED' && <div className="max-w-56 truncate text-xs text-muted-foreground" title={c.void_reason}>{c.void_reason}</div>}</div> },
    {
      id: 'act', header: '', align: 'right', cell: (c) => (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {can('bills.pay') && (c.status === 'PENDING' || c.status === 'STALE') && <>
            <Input type="date" aria-label={`Cleared on, cheque ${c.reference}`} className="h-8 w-36" min={c.paid_on} max={today()} value={on[c.id] ?? ''} onChange={(e) => setOn((x) => ({ ...x, [c.id]: e.target.value }))} />
            <Button size="sm" variant="outline" disabled={!on[c.id]} onClick={() => clear.mutate({ id: c.id, on: on[c.id] })}>Cleared</Button>
            {c.direction === 'IN' && <Button size="sm" variant="ghost" className="text-danger" onClick={() => setBouncing(c)}>Bounced</Button>}
          </>}
          <Button size="icon-sm" variant="ghost" asChild><a href={voucherUrl(c.id)} target="_blank" rel="noreferrer" aria-label={`Voucher ${c.number}`} title="The voucher"><FileText /></a></Button>
        </div>
      ),
    },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Issued, not presented" value={compactINR(s?.issued_pending)} loading={q.isPending} />
        <Stat label="Received, not credited" value={compactINR(s?.received_pending)} loading={q.isPending} />
        <Stat label="Stale" value={s?.stale ?? 0} tone={s?.stale ? 'warning' : undefined} sub="over 3 months: cancel and write again" loading={q.isPending} />
        <Stat label="Bounced" value={s?.bounced ?? 0} tone={s?.bounced ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <div className="mb-3 max-w-md"><Tabs label="Cheques" value={filter} onChange={setFilter} items={FILTERS} /></div>
      <DataTable label="Cheque register" rows={q.data?.cheques ?? []} columns={columns} rowKey={(c) => c.id} loading={q.isPending}
        empty="No cheques yet. A payment or receipt made by cheque shows here." />
      <ConfirmDialog open={!!bouncing} onOpenChange={(o) => !o && setBouncing(null)} title={`Cheque ${bouncing?.reference ?? ''} bounced?`}
        description={bouncing ? `${formatINR(bouncing.amount)} from ${bouncing.party_name}. The receipt is voided and what it settled is owed again.` : undefined}
        confirmLabel="It bounced" tone="danger" reason={{ label: 'Why was it returned? (insufficient funds, signature...)', required: true }} loading={bounce.isPending}
        onConfirm={(why) => { if (bouncing) bounce.mutate({ c: bouncing, why }) }} />
    </>
  )
}
