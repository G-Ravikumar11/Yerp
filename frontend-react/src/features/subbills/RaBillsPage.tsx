import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Download, FilePlus2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Button, Select, Stat, StatGrid, StatusBadge } from '@/components/ui'
import { billKeys, drawBill, useSubBills, withRunningTotals, type SubBill } from '@/api/subbills'
import { useOrders } from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { DeleteOrderDialog } from '@/features/deleteorder/DeleteOrderDialog'
import { BulkBar, BulkDeleteDialog } from '@/components/data/BulkDelete'
import { DeleteButton } from '@/features/deleteorder/DeleteButton'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

export default function RaBillsPage() {
  const nav = useNavigate()
  const { can, isOwner } = useSession()
  const [deleting, setDeleting] = useState<SubBill | null>(null)
  const [picked, setPicked] = useState<Set<string | number>>(new Set())
  const [clearing, setClearing] = useState(false)
  const [params, setParams] = useSearchParams()
  const orderId = Number(params.get('order')) || 0
  const orders = useOrders()
  const bills = useSubBills(orderId)
  const usable = (orders.data?.orders ?? []).filter((o) => o.status !== 'DRAFT' && o.status !== 'PROVISIONAL')
  const chosen = usable.find((o) => o.id === orderId)

  const rows = bills.data?.bills ?? []
  const running = useMemo(() => withRunningTotals(rows), [rows])
  const filters = useListFilters(rows, {
    search: (b) => [b.number, b.contractor, b.vendor_code, b.project, b.status, b.net_payable, b.work_name].join(' '),
    status: (b) => b.status,
    date: (b) => b.bill_date,
    facets: { project: { label: 'Projects', get: (b) => b.project }, gang: { label: 'Gangs', get: (b) => b.contractor }, order: { label: 'Work orders', get: (b) => b.order } },
  })

  const s = bills.data?.summary
  const upToDate = rows.filter((b) => b.status !== 'CANCELLED').reduce((m, b) => Math.max(m, b.gross_to_date), 0)

  const draw = useAction(() => drawBill(orderId), {
    invalidate: [billKeys.all],
    onSuccess: (r) => nav(`/subcontractors/ra-bills/${r.bill.id}`),
  })

  const columns: TableColumn<SubBill>[] = [
    { id: 'no', header: 'Bill', sort: (b) => b.number, cell: (b) => <span className="font-mono text-[13px] font-medium">{b.number}</span> },
    {
      id: 'who',
      header: 'Gang',
      cell: (b) => (
        <div className="max-w-xs">
          <div className="truncate font-medium">
            {b.contractor}
            {b.vendor_code && <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">{b.vendor_code}</span>}
          </div>
          <div className="truncate text-xs text-muted-foreground">{b.project}</div>
        </div>
      ),
    },
    { id: 'date', header: 'Dated', sort: (b) => b.bill_date, cell: (b) => formatDate(b.bill_date), hideBelow: 'xl' },
    { id: 'prev', header: 'Previous', align: 'right', cell: (b) => <span className="text-muted-foreground">{formatINR(b.previously_billed)}</span>, hideBelow: 'md' },
    { id: 'this', header: 'This bill', align: 'right', sort: (b) => b.this_bill, cell: (b) => formatINR(b.this_bill) },
    { id: 'upto', header: 'Up to date', align: 'right', sort: (b) => b.gross_to_date, cell: (b) => <span className="font-semibold">{formatINR(b.gross_to_date)}</span>, hideBelow: 'md' },
    { id: 'ret', header: 'Retention held', align: 'right', cell: (b) => formatINR(b.retention_amount), hideBelow: 'xl' },
    { id: 'tds', header: 'TDS', align: 'right', cell: (b) => formatINR(b.tds_amount), hideBelow: 'xl' },
    { id: 'net', header: 'Net payable', align: 'right', sort: (b) => b.net_payable, cell: (b) => <span className="font-semibold">{formatINR(b.net_payable)}</span> },
    { id: 'cum', header: 'Cumulative net', align: 'right', cell: (b) => <span className="font-semibold">{formatINR(running.get(b.id) ?? 0)}</span>, hideBelow: 'lg' },
    {
      id: 'status',
      header: 'Status',
      sort: (b) => b.status,
      cell: (b) => (
        <div>
          <StatusBadge status={b.status} />
          {b.status === 'SUBMITTED' && b.waiting_on && <div className="mt-1 text-xs text-muted-foreground">with {b.waiting_on}</div>}
        </div>
      ),
    },
    { id: 'del', header: '', align: 'right', width: '3.5rem', cell: (b) => (isOwner ? <DeleteButton label={b.number} onClick={() => setDeleting(b)} /> : null) },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="RA Bills"
        description="Certificate of payment, abstract and MB for each bill - prepared, certified, approved, paid."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href={`/api/sub-bills.xlsx${orderId ? `?order_id=${orderId}` : ''}`}>
                <Download /> Register
              </a>
            </Button>
            {can('billing.manage') && orderId > 0 && chosen && (chosen.status === 'APPROVED' || chosen.status === 'EXECUTED') && (
              <Button loading={draw.isPending} onClick={() => draw.mutate()}>
                <FilePlus2 /> Draw up a bill
              </Button>
            )}
          </>
        }
      />

      <div className="mb-6 max-w-2xl">
        <Select
          aria-label="Work order"
          value={orderId || ''}
          onChange={(e) => setParams(e.target.value ? { order: e.target.value } : {})}
          placeholder="All work orders"
          options={usable.map((o) => ({ value: o.id, label: `${o.wo_number} - ${o.contractor || 'no gang'} · ${o.project}` }))}
        />
      </div>

      <StatGrid className="xl:grid-cols-6">
        {orderId > 0 && <Stat label="Billed up to date" value={compactINR(upToDate)} loading={bills.isPending} />}
        <Stat label="Claimed by the gang" value={compactINR(s?.claimed)} loading={bills.isPending} />
        <Stat label="Awaiting certification" value={s?.awaiting_certification ?? 0} tone={s?.awaiting_certification ? 'warning' : undefined} loading={bills.isPending} />
        <Stat label="Certified, unpaid" value={compactINR(s?.certified_unpaid)} loading={bills.isPending} />
        <Stat label="Retention we hold" value={compactINR(s?.retention_held)} loading={bills.isPending} />
        <Stat label="Paid out" value={compactINR(s?.paid)} loading={bills.isPending} />
      </StatGrid>

      <FilterBar filters={filters} placeholder="Search by bill, gang, project..." />
      {isOwner && <BulkBar count={picked.size} noun="bill" shown={filters.filtered.length} onClear={() => setPicked(new Set())} onDelete={() => setClearing(true)} />}
      <DataTable
        label="RA bills"
        selection={isOwner ? { selected: picked, onChange: setPicked } : undefined}
        rows={filters.filtered}
        columns={columns}
        rowKey={(b) => b.id}
        loading={bills.isPending}
        onRowClick={(b) => nav(`/subcontractors/ra-bills/${b.id}`)}
        empty={filters.active ? 'Nothing matches those filters.' : "No bills yet. Measure the gang's work, then draw one up."}
      />
      <BulkDeleteDialog open={clearing} onOpenChange={setClearing} kind="bill" noun="bill" ids={[...picked].map(Number)} onFinished={() => setPicked(new Set())} detail="Each goes with its approvals and payments. What each measured becomes free to bill again. This cannot be undone." />
      <DeleteOrderDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} kind="bill" id={deleting?.id ?? 0} number={deleting?.number ?? ''} onDeleted={() => setDeleting(null)} />
    </>
  )
}
