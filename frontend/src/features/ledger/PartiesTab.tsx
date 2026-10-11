import { useState } from 'react'
import { Plus } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Select, Stat, StatGrid } from '@/components/ui'
import { PARTY_LABEL, useParties, type Party } from '@/api/ledger'
import { useSession } from '@/lib/session'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { OnAccountModal } from './OnAccountModal'
import { StatementModal } from './StatementModal'

/** Every party we deal with, what has been billed, what has moved, and who owes whom. */
export function PartiesTab() {
  const { can } = useSession()
  const [type, setType] = useState('')
  const q = useParties(type)
  const [onAccount, setOnAccount] = useState<'IN' | 'OUT' | null>(null)
  const [statement, setStatement] = useState<Party | null>(null)
  const s = q.data?.summary

  const columns: TableColumn<Party>[] = [
    { id: 'party', header: 'Party', sort: (p) => p.party, cell: (p) => <span className="font-semibold">{p.party}</span> },
    { id: 'type', header: 'Type', hideBelow: 'md', cell: (p) => PARTY_LABEL[p.party_type] ?? p.party_type },
    { id: 'billed', header: 'Billed', hideBelow: 'lg', align: 'right', cell: (p) => formatINR(p.billed) },
    { id: 'moved', header: 'Received / paid', hideBelow: 'lg', align: 'right', cell: (p) => formatINR(p.moved) },
    {
      id: 'bal',
      header: 'Balance',
      align: 'right',
      sort: (p) => Math.abs(p.balance),
      cell: (p) => {
        const owing = p.balance > 0
        const advance = p.balance < 0
        const note = p.party_type === 'client' ? (owing ? 'they owe us' : advance ? 'paid ahead' : 'square') : owing ? 'we owe them' : advance ? 'advance with them' : 'square'
        return (
          <div className={cn('font-bold', owing && 'text-warning')}>
            {formatINR(Math.abs(p.balance))}
            <div className="text-[11px] font-normal text-muted-foreground">{note}</div>
          </div>
        )
      },
    },
    { id: 'last', header: 'Last', hideBelow: 'xl', cell: (p) => p.last },
    { id: 'act', header: '', align: 'right', cell: (p) => <Button size="sm" variant="outline" onClick={() => setStatement(p)}>Statement</Button> },
  ]

  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Owed to us" value={compactINR(s?.owed_to_us)} loading={q.isPending} />
        <Stat label="We owe" value={compactINR(s?.we_owe)} loading={q.isPending} />
        <Stat label="Advances out" value={compactINR(s?.advances_out)} loading={q.isPending} />
        <Stat label="Parties" value={s?.parties ?? 0} loading={q.isPending} />
      </StatGrid>
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <div className="w-48"><Select aria-label="Party type" value={type} onChange={(e) => setType(e.target.value)} placeholder="Every party" options={Object.entries(PARTY_LABEL).map(([v, l]) => ({ value: v, label: `${l}s` }))} /></div>
        {can('bills.pay') && (
          <>
            <Button variant="outline" size="sm" onClick={() => setOnAccount('IN')}><Plus /> Money in on account</Button>
            <Button variant="outline" size="sm" onClick={() => setOnAccount('OUT')}><Plus /> Advance / payment on account</Button>
          </>
        )}
      </div>
      <DataTable label="Parties" rows={q.data?.parties ?? []} columns={columns} rowKey={(p) => `${p.party_type}-${p.party}`} loading={q.isPending} empty="No bills and no money moved yet." />
      <OnAccountModal direction={onAccount} onClose={() => setOnAccount(null)} />
      <StatementModal target={statement ? { type: statement.party_type, party: statement.party } : null} onClose={() => setStatement(null)} />
    </>
  )
}
