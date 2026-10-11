import { useState } from 'react'
import { FileSpreadsheet, PackagePlus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { VERDICT, useMatch, useReceipts, type GrnRow, type MatchRow } from '@/api/grn'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { ReceiptModal } from './ReceiptModal'
import { ReceiveModal } from './ReceiveModal'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

const tone = (s: string) => (s === 'POSTED' ? 'success' : s === 'CANCELLED' ? 'danger' : 'neutral') as 'success' | 'danger' | 'neutral'

/** What arrived at the gate, and whether the order, the delivery and the bill agree. */
export default function GrnPage() {
  const q = useReceipts()
  const [exceptions, setExceptions] = useState(false)
  const match = useMatch(exceptions)
  const [receiving, setReceiving] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const s = q.data?.summary
  const m = match.data?.summary
  const receipts: TableColumn<GrnRow>[] = [
    { id: 'no', header: 'Receipt', cell: (g) => <div><button type="button" className="font-mono font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(g.id)}>{g.number}</button>{g.challan_number && <div className="text-xs text-muted-foreground">challan {g.challan_number}</div>}</div> },
    { id: 'sup', header: 'Supplier', cell: (g) => <div>{g.supplier_name}<div className="text-xs text-muted-foreground">{g.purchase_order}{g.project && ` - ${g.project}`}</div></div> },
    { id: 'on', header: 'Received', hideBelow: 'md', sort: (g) => g.received_on, cell: (g) => formatDate(g.received_on) },
    { id: 'acc', header: 'Accepted', align: 'right', cell: (g) => formatINR(g.accepted_value) },
    { id: 'rej', header: 'Rejected', hideBelow: 'md', align: 'right', cell: (g) => (g.rejected_value ? <span className="text-warning">{formatINR(g.rejected_value)}</span> : '-') },
    { id: 'st', header: 'Status', cell: (g) => <Badge tone={tone(g.status)} dot>{g.status === 'POSTED' ? 'Posted' : g.status === 'CANCELLED' ? 'Cancelled' : 'Draft'}</Badge> },
    { id: 'act', header: '', align: 'right', cell: (g) => <div className="flex justify-end gap-1.5">{g.actions.includes('POST') && <Button size="sm" onClick={() => setOpen(g.id)}>Post</Button>}<Button size="sm" variant="outline" onClick={() => setOpen(g.id)}>Open</Button><Button size="sm" variant="ghost" asChild><a href={`/api/grn/${g.id}/export.xlsx`} title="As a workbook"><FileSpreadsheet /></a></Button></div> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="grn" id={r.id} label={String(r.number)} noun="goods receipt" /> },
  ]
  const matches: TableColumn<MatchRow>[] = [
    { id: 'po', header: 'Order', cell: (r) => <div><span className="font-mono font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.supplier_name}</div></div> },
    { id: 'proj', header: 'Project', hideBelow: 'lg', cell: (r) => r.project || '-' },
    { id: 'ord', header: 'Ordered', hideBelow: 'md', align: 'right', cell: (r) => formatINR(r.ordered_value) },
    { id: 'rec', header: 'Received', align: 'right', cell: (r) => <div>{formatINR(r.received_value)}<div className="text-xs text-muted-foreground">{r.receipt_count} receipt{r.receipt_count === 1 ? '' : 's'}</div></div> },
    { id: 'bil', header: 'Billed', align: 'right', cell: (r) => <div>{formatINR(r.billed_value)}<div className="text-xs text-muted-foreground">{r.bill_count} bill{r.bill_count === 1 ? '' : 's'}</div></div> },
    { id: 'v', header: 'Verdict', cell: (r) => <div><Badge tone={VERDICT[r.verdict]?.tone ?? 'neutral'} dot>{VERDICT[r.verdict]?.label ?? r.verdict}</Badge><div className="mt-0.5 max-w-72 text-xs text-muted-foreground">{r.note}</div></div> },
  ]
  const filters = useListFilters(q.data?.goods_receipts, {
    search: (g) => [g.number, g.challan_number, g.supplier_name, g.purchase_order, g.project, g.status].join(' '),
    status: (g) => g.status,
    date: (g) => g.received_on,
  })
  return (
    <>
      <PageHeader eyebrow="Store" title="Goods Receipt & Match" description="What actually arrived at the gate, and whether the order, the delivery and the bill agree." actions={<Button onClick={() => setReceiving(true)}><PackagePlus /> Receive a delivery</Button>} />
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Receipts" value={s?.count ?? 0} loading={q.isPending} />
        <Stat label="Not yet posted" value={s?.awaiting_posting ?? 0} loading={q.isPending} />
        <Stat label="Accepted" value={formatINR(s?.accepted_value ?? 0)} loading={q.isPending} />
        <Stat label="Rejected" value={formatINR(s?.rejected_value ?? 0)} loading={q.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by receipt, challan, supplier, order..." />
      <DataTable label="Goods receipts" rows={filters.filtered} columns={receipts} rowKey={(g) => g.id} loading={q.isPending} empty="Nothing received yet. Take a delivery against an approved order." />
      <div className="mb-3 mt-10 flex flex-wrap items-center justify-between gap-3"><h2 className="text-sm font-semibold">The three-way match</h2><label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={exceptions} onChange={(e) => setExceptions(e.target.checked)} /> Only what needs a look</label></div>
      <StatGrid>
        <Stat label="Orders" value={m?.orders ?? 0} loading={match.isPending} />
        <Stat label="Agreeing" value={m?.matched ?? 0} loading={match.isPending} />
        <Stat label="Need a look" value={m?.exceptions ?? 0} tone={m?.exceptions ? 'warning' : undefined} loading={match.isPending} />
        <Stat label="Billed over receipt" value={formatINR(m?.over_billed ?? 0)} tone={m?.over_billed ? 'danger' : undefined} loading={match.isPending} />
        <Stat label="Received, not billed" value={formatINR(m?.accrual_owed ?? 0)} loading={match.isPending} />
      </StatGrid>
      <DataTable label="Three-way match" rows={match.data?.orders ?? []} columns={matches} rowKey={(r) => r.purchase_order_id} loading={match.isPending} empty="Nothing to compare yet." />
      <ReceiveModal open={receiving} onClose={() => setReceiving(false)} onStarted={(g) => { setReceiving(false); setOpen(g.id) }} />
      <ReceiptModal id={open} onClose={() => setOpen(null)} />
    </>
  )
}
