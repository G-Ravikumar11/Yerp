import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { Archive, FileSpreadsheet, FileText } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { VERDICT, useMatch, useReceipts, type GrnRow, type MatchRow } from '@/api/grn'
import { useVouchers, voucherPdf, voucherRegister, type Voucher } from '@/api/materialVouchers'
import { useIssues, useStock, type Issue, type StockRow } from '@/api/stock'
import { apiUrl } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'
import { LedgerModal } from './LedgerModal'
import { ReceiptModal } from './ReceiptModal'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')
const tone = (s: string) => (s === 'POSTED' ? 'success' : s === 'CANCELLED' ? 'danger' : 'neutral') as 'success' | 'danger' | 'neutral'

/** Store > Reports > Old store records. What the old store (Stock & Issues, Goods Receipt & Match, Material Issue Vouchers) holds, kept to read:
 * its stock and ledger, its issue notes, its goods receipts and the three-way match, its vouchers. The old store takes nothing new - the work is done in the
 * Store Hub - but these records still count in project costs, purchase orders and the invoice tracker, and are kept in full. */
export default function OldStoreRecords() {
  return (
    <div>
      <p role="status" className="mb-4 flex flex-wrap items-center gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[13px]">
        <Archive className="size-4 shrink-0 text-warning" /> These are the old store's records, kept to read. New receipts, issues and transfers are made in the Store Hub; these figures still count in project costs.
      </p>
      <nav aria-label="Old store records" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
        <NavLink end to="/store/hub/reports/old-store" className={tab}>Stock & issue notes</NavLink>
        <NavLink to="/store/hub/reports/old-store/receipts" className={tab}>Goods receipts & match</NavLink>
        <NavLink to="/store/hub/reports/old-store/vouchers" className={tab}>Material issue vouchers</NavLink>
      </nav>
      <Routes>
        <Route index element={<StockRecords />} />
        <Route path="receipts" element={<ReceiptRecords />} />
        <Route path="vouchers" element={<VoucherRecords />} />
      </Routes>
    </div>
  )
}

/** What the old store held, item by item with its ledger, and the issue notes made to site. */
function StockRecords() {
  const [low, setLow] = useState(false)
  const stock = useStock(low)
  const issues = useIssues()
  const [ledger, setLedger] = useState<string | null>(null)
  const s = stock.data?.summary
  const n = issues.data?.summary
  const held: TableColumn<StockRow>[] = [
    { id: 'item', header: 'Item', sort: (r) => r.item_code, cell: (r) => <div><span className="font-mono font-semibold">{r.item_code}</span><div className="text-xs text-muted-foreground">{r.item_name}</div></div> },
    { id: 'rec', header: 'Received', hideBelow: 'md', align: 'right', cell: (r) => r.received },
    { id: 'iss', header: 'Issued', hideBelow: 'md', align: 'right', cell: (r) => r.issued },
    { id: 'hand', header: 'On hand', align: 'right', sort: (r) => r.on_hand, cell: (r) => <div className={`font-bold ${r.negative ? 'text-danger' : r.below_level ? 'text-warning' : ''}`}>{r.on_hand} {r.uom}{r.negative && <div className="text-[11px] font-normal">more issued than received</div>}</div> },
    { id: 'rate', header: 'Rate', hideBelow: 'lg', align: 'right', cell: (r) => formatINR(r.rate) },
    { id: 'val', header: 'Value', align: 'right', sort: (r) => r.value, cell: (r) => <strong>{formatINR(r.value)}</strong> },
    { id: 'act', header: '', align: 'right', cell: (r) => <Button size="sm" variant="outline" onClick={() => setLedger(r.item_code)}>Ledger</Button> },
  ]
  const notes: TableColumn<Issue>[] = [
    { id: 'no', header: 'Note', cell: (i) => <span className="font-mono font-semibold">{i.number}</span> },
    { id: 'for', header: 'Against', cell: (i) => <div>{i.work_order || '-'}{i.purpose && <div className="text-xs text-muted-foreground">{i.purpose}</div>}</div> },
    { id: 'by', header: 'Taken by', hideBelow: 'md', cell: (i) => i.issued_to || '-' },
    { id: 'on', header: 'Date', hideBelow: 'md', sort: (i) => i.issued_on, cell: (i) => formatDate(i.issued_on) },
    { id: 'val', header: 'Value', align: 'right', cell: (i) => <strong>{formatINR(i.total_value)}</strong> },
    { id: 'st', header: 'Status', cell: (i) => <Badge tone={tone(i.status)} dot>{i.status === 'POSTED' ? 'Posted' : i.status === 'CANCELLED' ? 'Cancelled' : 'Draft'}</Badge> },
    { id: 'act', header: '', align: 'right', cell: (i) => <Button size="sm" variant="outline" asChild><a href={`/api/stock-issues/${i.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> Slip</a></Button> },
  ]
  return (
    <div>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Items held" value={s?.items_held ?? 0} loading={stock.isPending} />
        <Stat label="Value in the old store" value={formatINR(s?.value_on_hand ?? 0)} loading={stock.isPending} />
        <Stat label="Below reorder level" value={s?.below_reorder ?? 0} tone={s?.below_reorder ? 'warning' : undefined} loading={stock.isPending} />
        <Stat label="Going negative" value={s?.negative_lines ?? 0} tone={s?.negative_lines ? 'danger' : undefined} loading={stock.isPending} />
      </StatGrid>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Held in the old store</h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Only what is running low</label>
          <Button size="sm" variant="outline" asChild><a href="/api/stock.xlsx"><FileSpreadsheet /> Download</a></Button>
        </div>
      </div>
      {stock.isError ? <p role="alert" className="text-sm text-danger">The old store's stock could not be loaded.</p> : <DataTable label="Old store stock" rows={stock.data?.stock ?? []} columns={held} rowKey={(r) => r.item_code} loading={stock.isPending} empty="The old store holds nothing." />}
      <StatGrid className="mt-8 lg:grid-cols-3 xl:grid-cols-3">
        <Stat label="Issue notes" value={n?.notes ?? 0} loading={issues.isPending} />
        <Stat label="Not yet posted" value={n?.not_yet_posted ?? 0} loading={issues.isPending} />
        <Stat label="Issued to site" value={formatINR(n?.issued_value ?? 0)} loading={issues.isPending} />
      </StatGrid>
      <h2 className="mb-2 text-sm font-semibold">Issue notes</h2>
      {issues.isError ? <p role="alert" className="text-sm text-danger">The issue notes could not be loaded.</p> : <DataTable label="Old store issue notes" rows={issues.data?.issues ?? []} columns={notes} rowKey={(i) => i.id} loading={issues.isPending} empty="Nothing was issued from the old store." />}
      <LedgerModal code={ledger} onClose={() => setLedger(null)} />
    </div>
  )
}

/** What arrived at the old store's gate, and whether the order, the delivery and the bill agree. */
function ReceiptRecords() {
  const q = useReceipts()
  const [exceptions, setExceptions] = useState(false)
  const match = useMatch(exceptions)
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
    { id: 'act', header: '', align: 'right', cell: (g) => <div className="flex justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => setOpen(g.id)}>Open</Button><Button size="sm" variant="ghost" asChild><a href={`/api/grn/${g.id}/export.xlsx`} title="As a workbook"><FileSpreadsheet /></a></Button></div> },
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
    <div>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Receipts" value={s?.count ?? 0} loading={q.isPending} />
        <Stat label="Not yet posted" value={s?.awaiting_posting ?? 0} loading={q.isPending} />
        <Stat label="Accepted" value={formatINR(s?.accepted_value ?? 0)} loading={q.isPending} />
        <Stat label="Rejected" value={formatINR(s?.rejected_value ?? 0)} loading={q.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by receipt, challan, supplier, order..." />
      {q.isError ? <p role="alert" className="text-sm text-danger">The goods receipts could not be loaded.</p> : <DataTable label="Old store goods receipts" rows={filters.filtered} columns={receipts} rowKey={(g) => g.id} loading={q.isPending} empty="No goods receipt on record." />}
      <div className="mb-3 mt-10 flex flex-wrap items-center justify-between gap-3"><h2 className="text-sm font-semibold">The three-way match</h2><label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={exceptions} onChange={(e) => setExceptions(e.target.checked)} /> Only what needs a look</label></div>
      <StatGrid>
        <Stat label="Orders" value={m?.orders ?? 0} loading={match.isPending} />
        <Stat label="Agreeing" value={m?.matched ?? 0} loading={match.isPending} />
        <Stat label="Need a look" value={m?.exceptions ?? 0} tone={m?.exceptions ? 'warning' : undefined} loading={match.isPending} />
        <Stat label="Billed over receipt" value={formatINR(m?.over_billed ?? 0)} tone={m?.over_billed ? 'danger' : undefined} loading={match.isPending} />
        <Stat label="Received, not billed" value={formatINR(m?.accrual_owed ?? 0)} loading={match.isPending} />
      </StatGrid>
      <DataTable label="Three-way match" rows={match.data?.orders ?? []} columns={matches} rowKey={(r) => r.purchase_order_id} loading={match.isPending} empty="Nothing to compare yet." />
      <ReceiptModal id={open} onClose={() => setOpen(null)} />
    </div>
  )
}

/** The Material Issue Vouchers kept in Sl. No. order, each as the printed form, and the register as Excel. */
function VoucherRecords() {
  const [job, setJob] = useState(0)
  const q = useVouchers(job)
  const d = q.data
  const columns: TableColumn<Voucher>[] = [
    { id: 'no', header: 'Sl. No.', width: '5rem', sort: (v) => v.number, cell: (v) => <span className="font-mono font-semibold">{v.number}</span> },
    { id: 'on', header: 'Date', sort: (v) => v.voucher_on, cell: (v) => formatDate(v.voucher_on) },
    { id: 'project', header: 'Project Name', cell: (v) => v.project },
    { id: 'ind', header: 'Indented By', hideBelow: 'md', cell: (v) => v.indented_by || '-' },
    { id: 'by', header: 'Issued By', hideBelow: 'lg', cell: (v) => v.issued_by || '-' },
    { id: 'for', header: 'Issued For', hideBelow: 'lg', cell: (v) => v.issued_for || '-' },
    {
      id: 'items', header: 'Items',
      cell: (v) => (
        <div className="max-w-72 text-[13px]">
          {v.lines.slice(0, 3).map((l, i) => <div key={i} className="truncate">{l.description} - {l.issued_qty} {l.uom}{l.returned_qty ? `, ${l.returned_qty} back` : ''}</div>)}
          {v.lines.length > 3 && <div className="text-xs text-muted-foreground">and {v.lines.length - 3} more</div>}
        </div>
      ),
    },
    { id: 'act', header: '', align: 'right', cell: (v) => <Button size="sm" variant="outline" asChild><a href={apiUrl(voucherPdf(v.id))} target="_blank" rel="noopener"><FileText /> PDF</a></Button> },
  ]
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="min-w-64 flex-1 sm:max-w-md"><ProjectPicker value={job} onChange={setJob} id="miv-reg-job" allowAll /></div>
        <Button variant="outline" className="ml-auto" asChild><a href={apiUrl(voucherRegister(job))}><FileSpreadsheet /> Download register (Excel)</a></Button>
      </div>
      <StatGrid className="lg:grid-cols-2 xl:grid-cols-2">
        <Stat label="Vouchers" value={d?.summary.vouchers ?? 0} loading={q.isPending} />
        <Stat label="Items issued" value={d?.summary.lines ?? 0} loading={q.isPending} />
      </StatGrid>
      {q.isError ? <p role="alert" className="text-sm text-danger">The vouchers could not be loaded.</p> : <DataTable label="Voucher register" rows={d?.vouchers ?? []} columns={columns} rowKey={(v) => v.id} loading={q.isPending} empty="No vouchers on record." />}
    </div>
  )
}
