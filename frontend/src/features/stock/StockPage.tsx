import { useState } from 'react'
import { FileText, FileSpreadsheet, Send } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { PromptModal } from '@/components/data/PromptModal'
import { Badge, Button, ConfirmDialog, Stat, StatGrid } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { cancelIssue, countStock, postIssue, stockKeys, useIssues, useStock, type Issue, type StockRow } from '@/api/stock'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { IssueModal } from './IssueModal'
import { LedgerModal } from './LedgerModal'
import { TransferModal } from './TransferModal'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

/** What is in the store, what went to site, and what it cost. The store's balance is the sum of its movements. */
export default function StockPage() {
  const { can } = useSession()
  const [low, setLow] = useState(false)
  const stock = useStock(low)
  const issues = useIssues()
  const [issuing, setIssuing] = useState(false)
  const [sending, setSending] = useState(false)
  const [ledger, setLedger] = useState<string | null>(null)
  const [counting, setCounting] = useState<StockRow | null>(null)
  const [forcing, setForcing] = useState<{ id: number; why: string } | null>(null)
  const [cancelling, setCancelling] = useState<Issue | null>(null)
  const refresh = { invalidate: [stockKeys.all] }
  const count = useAction((v: { row: StockRow; n: number }) => countStock(v.row.item_code, v.n), { ...refresh, success: (r) => r.message, onSuccess: () => setCounting(null) })
  const post = useAction((v: { id: number; force: boolean }) => postIssue(v.id, v.force ? { allow_negative: true } : {}), { ...refresh, success: (r) => r.message, onSuccess: () => setForcing(null), onError: (e, v) => { if (e instanceof ApiError && e.status === 409 && !v.force) setForcing({ id: v.id, why: e.message }) } })
  const cancel = useAction((i: Issue) => cancelIssue(i.id), { ...refresh, success: (r) => r.message, onSuccess: () => setCancelling(null) })
  const s = stock.data?.summary
  const n = issues.data?.summary
  const manage = can('stores.manage')

  const held: TableColumn<StockRow>[] = [
    { id: 'item', header: 'Item', sort: (r) => r.item_code, cell: (r) => <div><span className="font-mono font-semibold">{r.item_code}</span><div className="text-xs text-muted-foreground">{r.item_name}</div></div> },
    { id: 'rec', header: 'Received', hideBelow: 'md', align: 'right', cell: (r) => r.received },
    { id: 'iss', header: 'Issued', hideBelow: 'md', align: 'right', cell: (r) => r.issued },
    { id: 'hand', header: 'On hand', align: 'right', sort: (r) => r.on_hand, cell: (r) => <div className={`font-bold ${r.negative ? 'text-danger' : r.below_level ? 'text-warning' : ''}`}>{r.on_hand} {r.uom}{r.below_level && <div className="text-[11px] font-normal">below {r.reorder_level}</div>}{r.negative && <div className="text-[11px] font-normal">more issued than received</div>}</div> },
    { id: 'rate', header: 'Rate', hideBelow: 'lg', align: 'right', cell: (r) => formatINR(r.rate) },
    { id: 'val', header: 'Value', align: 'right', sort: (r) => r.value, cell: (r) => <strong>{formatINR(r.value)}</strong> },
    { id: 'act', header: '', align: 'right', cell: (r) => <div className="flex justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => setLedger(r.item_code)}>Ledger</Button>{manage && <Button size="sm" variant="outline" onClick={() => setCounting(r)}>Count</Button>}</div> },
  ]
  const notes: TableColumn<Issue>[] = [
    { id: 'no', header: 'Note', cell: (i) => <span className="font-mono font-semibold">{i.number}</span> },
    { id: 'for', header: 'Against', cell: (i) => <div>{i.work_order || '-'}{i.purpose && <div className="text-xs text-muted-foreground">{i.purpose}</div>}</div> },
    { id: 'by', header: 'Taken by', hideBelow: 'md', cell: (i) => i.issued_to || '-' },
    { id: 'on', header: 'Date', hideBelow: 'md', sort: (i) => i.issued_on, cell: (i) => formatDate(i.issued_on) },
    { id: 'val', header: 'Value', align: 'right', cell: (i) => <strong>{formatINR(i.total_value)}</strong> },
    { id: 'st', header: 'Status', cell: (i) => <Badge tone={i.status === 'POSTED' ? 'success' : i.status === 'CANCELLED' ? 'danger' : 'neutral'} dot>{i.status === 'POSTED' ? 'Posted' : i.status === 'CANCELLED' ? 'Cancelled' : 'Draft'}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (i) => (
        <div className="flex flex-wrap justify-end gap-1.5">
          <Button size="sm" variant="outline" asChild><a href={`/api/stock-issues/${i.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> Slip</a></Button>
          {i.status === 'DRAFT' && <Button size="sm" loading={post.isPending && post.variables?.id === i.id} onClick={() => post.mutate({ id: i.id, force: false })}>Post it</Button>}
          {i.status !== 'CANCELLED' && manage && <Button size="sm" variant="outline" onClick={() => setCancelling(i)}>Cancel</Button>}
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="stock_issue" id={r.id} label={String(r.number)} noun="stock issue" /> },
  ]
  return (
    <>
      <PageHeader eyebrow="Store" title="Stock & Issues" description="What is in the store, what went to site, and what it cost." actions={<><Button onClick={() => setIssuing(true)}><Send /> Issue to site</Button><Button variant="outline" onClick={() => setSending(true)}>Send to another site</Button><Button variant="outline" asChild><a href="/api/stock.xlsx"><FileSpreadsheet /> Download</a></Button></>} />
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Items held" value={s?.items_held ?? 0} loading={stock.isPending} />
        <Stat label="Value in the store" value={formatINR(s?.value_on_hand ?? 0)} loading={stock.isPending} />
        <Stat label="Below reorder level" value={s?.below_reorder ?? 0} tone={s?.below_reorder ? 'warning' : undefined} loading={stock.isPending} />
        <Stat label="Going negative" value={s?.negative_lines ?? 0} tone={s?.negative_lines ? 'danger' : undefined} loading={stock.isPending} />
      </StatGrid>
      <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">In the store</h2><label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Only what is running low</label></div>
      <DataTable label="Stock" rows={stock.data?.stock ?? []} columns={held} rowKey={(r) => r.item_code} loading={stock.isPending} empty="Nothing in the store yet. Material arrives by posting a goods receipt." />
      <StatGrid className="mt-8 lg:grid-cols-3 xl:grid-cols-3">
        <Stat label="Issue notes" value={n?.notes ?? 0} loading={issues.isPending} />
        <Stat label="Not yet posted" value={n?.not_yet_posted ?? 0} loading={issues.isPending} />
        <Stat label="Issued to site" value={formatINR(n?.issued_value ?? 0)} loading={issues.isPending} />
      </StatGrid>
      <h2 className="mb-2 text-sm font-semibold">Issue notes</h2>
      <DataTable label="Issue notes" rows={issues.data?.issues ?? []} columns={notes} rowKey={(i) => i.id} loading={issues.isPending} empty="Nothing issued yet." />
      <IssueModal open={issuing} onClose={() => setIssuing(false)} />
      <TransferModal open={sending} onClose={() => setSending(false)} />
      <LedgerModal code={ledger} onClose={() => setLedger(null)} />
      <PromptModal open={!!counting} title={counting ? `Physical count - ${counting.item_code}` : ''} description={counting ? `The book says ${counting.on_hand}. What did you count?` : undefined} fields={[{ key: 'n', label: 'Counted', initial: counting ? String(counting.on_hand) : '', required: true }]} confirm="Post the count" busy={count.isPending} error={count.error?.message} onSubmit={(v) => { if (counting) count.mutate({ row: counting, n: parseFloat(v.n) }) }} onClose={() => setCounting(null)} />
      <ConfirmDialog open={!!forcing} onOpenChange={(o) => !o && setForcing(null)} title="Post it anyway?" description={forcing?.why} confirmLabel="Post it anyway" tone="danger" loading={post.isPending} onConfirm={() => { if (forcing) post.mutate({ id: forcing.id, force: true }) }} />
      <ConfirmDialog open={!!cancelling} onOpenChange={(o) => !o && setCancelling(null)} title={`Cancel ${cancelling?.number ?? 'this note'}?`} description="Anything already posted goes back into the store." confirmLabel="Cancel the note" tone="danger" loading={cancel.isPending} onConfirm={() => { if (cancelling) cancel.mutate(cancelling) }} />
    </>
  )
}
