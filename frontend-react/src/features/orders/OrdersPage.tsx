import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Button, Stat, StatGrid, StatusBadge } from '@/components/ui'
import { useOrders, type Order } from '@/api/orders'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'
import { formatDate } from '@/lib/format'
import { DeleteOrderDialog } from '@/features/deleteorder/DeleteOrderDialog'
import { DeleteButton } from '@/features/deleteorder/DeleteButton'
import { NewOrderModal } from './NewOrderModal'

export default function OrdersPage() {
  const nav = useNavigate()
  const { can, isOwner } = useSession()
  const orders = useOrders()
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<Order | null>(null)

  const filters = useListFilters(orders.data?.orders, {
    search: (o) => [o.wo_number, o.contractor, o.vendor_code, o.project, o.subject, o.work_type, o.department, o.status, o.net_order_value].join(' '),
    status: (o) => o.status,
    date: (o) => o.created_at,
  })

  const s = orders.data?.summary
  const columns: TableColumn<Order>[] = [
    {
      id: 'no',
      header: 'Order',
      sort: (o) => o.wo_number,
      cell: (o) => (
        <div>
          <div className="font-mono text-[13px] font-medium">{o.wo_number}</div>
          {o.amendment_no > 0 && <div className="text-xs text-muted-foreground">revision {o.amendment_no}</div>}
        </div>
      ),
    },
    {
      id: 'who',
      header: 'Sub contractor',
      sort: (o) => o.contractor,
      cell: (o) => (
        <div className="max-w-xs">
          <div className="truncate font-medium">
            {o.contractor || <span className="text-subtle">Not chosen</span>}
            {o.vendor_code && <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">{o.vendor_code}</span>}
          </div>
          <div className="truncate text-xs text-muted-foreground">{o.project}</div>
        </div>
      ),
    },
    { id: 'subject', header: 'Work', cell: (o) => <span className="line-clamp-2 max-w-sm text-muted-foreground">{o.subject || '-'}</span>, hideBelow: 'lg' },
    { id: 'dept', header: 'Trade', sort: (o) => o.department, cell: (o) => o.department || '-', hideBelow: 'md' },
    { id: 'items', header: 'Lines', align: 'right', sort: (o) => o.item_count, cell: (o) => o.item_count, hideBelow: 'md' },
    { id: 'value', header: 'Net value', align: 'right', sort: (o) => o.net_order_value, cell: (o) => formatINR(o.net_order_value) },
    { id: 'start', header: 'Starts', sort: (o) => o.commencement_date, cell: (o) => formatDate(o.commencement_date) || '-', hideBelow: 'xl' },
    { id: 'status', header: 'Status', sort: (o) => o.status, cell: (o) => <StatusBadge status={o.status} /> },
    { id: 'del', header: '', align: 'right', width: '3.5rem', cell: (o) => (isOwner ? <DeleteButton label={o.wo_number} onClick={() => setDeleting(o)} /> : null) },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Work Orders"
        description="What each gang has been asked to build, at what rate, and who has signed for it."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href="/api/wo/orders.xlsx">
                <Download /> Excel
              </a>
            </Button>
            {can('workorders.manage') && (
              <Button onClick={() => setCreating(true)}>
                <Plus /> New work order
              </Button>
            )}
          </>
        }
      />

      <StatGrid>
        <Stat label="Orders" value={s?.total ?? 0} loading={orders.isPending} />
        <Stat label="Awaiting approval" value={s?.awaiting ?? 0} tone={s?.awaiting ? 'warning' : undefined} loading={orders.isPending} />
        <Stat label="Approved" value={(s?.approved ?? 0) + (s?.executed ?? 0)} loading={orders.isPending} />
        <Stat label="In draft" value={s?.draft ?? 0} loading={orders.isPending} />
        <Stat label="Committed value" value={compactINR(s?.value)} loading={orders.isPending} />
      </StatGrid>

      <FilterBar filters={filters} placeholder="Search by number, gang, project, work..." />

      <DataTable
        label="Work orders"
        rows={filters.filtered}
        columns={columns}
        rowKey={(o) => o.id}
        loading={orders.isPending}
        onRowClick={(o) => nav(`/subcontractors/work-orders/${o.id}`)}
        empty={filters.active ? 'Nothing matches those filters.' : 'No work orders yet. Start one with New work order.'}
      />

      <NewOrderModal open={creating} onOpenChange={setCreating} />
      <DeleteOrderDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} kind="subcontract" id={deleting?.id ?? 0} number={deleting?.wo_number ?? ''} onDeleted={() => setDeleting(null)} />
    </>
  )
}
