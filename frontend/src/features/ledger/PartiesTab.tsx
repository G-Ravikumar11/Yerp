import { useState } from 'react'
import { Download, Pencil, Plus, Trash2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, ConfirmDialog, Select, Stat, StatGrid } from '@/components/ui'
import { deleteOpening, ledgerKeys, PARTY_LABEL, useOpenings, useParties, type Opening, type Party } from '@/api/ledger'
import { bookKeys } from '@/api/books'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { useSession } from '@/lib/session'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { OnAccountModal } from './OnAccountModal'
import { OpeningModal } from './OpeningModal'
import { StatementModal } from './StatementModal'

/** Every party we deal with, what has been billed, what has moved, and who owes whom. */
export function PartiesTab({ job = 0 }: { job?: number }) {
  const { can } = useSession()
  const [type, setType] = useState('')
  const q = useParties(type, job)
  const [onAccount, setOnAccount] = useState<'IN' | 'OUT' | null>(null)
  const [statement, setStatement] = useState<Party | null>(null)
  const [opening, setOpening] = useState<Opening | 'new' | null>(null)
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
    { id: 'act', header: '', align: 'right', cell: (p) => <div className="flex justify-end gap-1"><Button size="sm" variant="outline" onClick={() => setStatement(p)}>Statement</Button><Button size="icon-sm" variant="ghost" asChild><a href={`/api/ledger/statement.pdf?party_type=${encodeURIComponent(p.party_type)}&party=${encodeURIComponent(p.party)}`} target="_blank" rel="noreferrer" aria-label={`Download the statement of ${p.party} (PDF)`} title="Download the statement (PDF)"><Download /></a></Button></div> },
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
        {can('accounts.manage') && <Button variant="outline" size="sm" onClick={() => setOpening('new')}><Plus /> Opening balance</Button>}
      </div>
      <DataTable label="Parties" rows={q.data?.parties ?? []} columns={columns} rowKey={(p) => `${p.party_type}-${p.party}`} loading={q.isPending} empty="No bills and no money moved yet." />
      <OpeningBalances onEdit={setOpening} job={job} />
      <OpeningModal target={opening} onClose={() => setOpening(null)} />
      <OnAccountModal direction={onAccount} onClose={() => setOnAccount(null)} />
      <StatementModal target={statement ? { type: statement.party_type, party: statement.party } : null} onClose={() => setStatement(null)} />
    </>
  )
}

/** The opening balances entered, so a wrong one is found and changed, not entered a second time. */
function OpeningBalances({ onEdit, job = 0 }: { onEdit: (o: Opening) => void; job?: number }) {
  const { can } = useSession()
  const q = useOpenings()
  const [removing, setRemoving] = useState<Opening | null>(null)
  const remove = useAction((id: number) => deleteOpening(id), { invalidate: [ledgerKeys.all, bookKeys.all, ['dashboard']], onSuccess: () => setRemoving(null) })
  // One project's: only the balances entered for it.
  const all = q.data?.openings ?? []
  const rows = job ? all.filter((o) => o.job_id === job) : all
  const edit = can('accounts.manage')
  const columns: TableColumn<Opening>[] = [
    { id: 'no', header: 'No.', cell: (o) => <span className="font-mono text-[13px]">{o.number}</span> },
    { id: 'party', header: 'Party', sort: (o) => o.party, cell: (o) => <div className="font-medium">{o.party}<div className="text-xs font-normal text-muted-foreground">{PARTY_LABEL[o.party_type] ?? o.party_type}{o.project ? ` - ${o.project}` : ''}</div></div> },
    { id: 'means', header: 'Balance', cell: (o) => <div>{o.means}<div className="text-xs text-muted-foreground">{o.note}</div></div> },
    { id: 'amount', header: 'Amount', align: 'right', sort: (o) => o.amount, cell: (o) => <span className="tabular font-semibold">{formatINR(o.amount)}</span> },
    { id: 'on', header: 'As on', hideBelow: 'md', sort: (o) => o.as_on, cell: (o) => formatDate(o.as_on) },
    ...(edit ? [{
      id: 'act', header: '', align: 'right' as const, cell: (o: Opening) => (
        <div className="flex justify-end gap-1">
          <Button size="icon-sm" variant="ghost" aria-label={`Edit ${o.number}`} onClick={() => onEdit(o)}><Pencil /></Button>
          <Button size="icon-sm" variant="ghost" aria-label={`Delete ${o.number}`} onClick={() => setRemoving(o)}><Trash2 /></Button>
        </div>
      ),
    }] : []),
  ]
  if (!q.isPending && !rows.length) return null
  return (
    <section aria-label="Opening balances" className="mt-8">
      <h2 className="text-base font-semibold">Opening balances</h2>
      <p className="mb-3 text-[13px] text-muted-foreground">What each party owed, or was owed, on the day the books here begin. Each is the first line of the party's ledger and goes to Tally as an opening journal. Change a wrong one; do not add a second.</p>
      <DataTable label="Opening balances" rows={rows} columns={columns} rowKey={(o) => o.id} loading={q.isPending} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Remove ${removing?.number ?? ''}?`} tone="danger" confirmLabel="Remove" loading={remove.isPending}
        description={removing ? `${removing.party}'s balance will no longer start from ${formatINR(removing.amount)}.` : undefined}
        onConfirm={() => { if (removing) remove.mutate(removing.id) }} />
    </section>
  )
}
