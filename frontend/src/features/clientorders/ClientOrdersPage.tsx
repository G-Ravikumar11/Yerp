import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, FileUp, Plus, Ruler, ShoppingCart, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, ConfirmDialog, Stat, StatGrid } from '@/components/ui'
import { clientOrderKeys, decideClientOrder, placeClientOrder, useClientOrders, type ClientOrder } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { DeleteOrderDialog } from '@/features/deleteorder/DeleteOrderDialog'
import { BulkBar, BulkDeleteDialog } from '@/components/data/BulkDelete'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'
import { BudgetModal } from './BudgetModal'
import { NewClientOrderModal } from './NewClientOrderModal'
import { OrderSheetModal } from './OrderSheetModal'
import { OrderDetailModal } from './OrderDetailModal'
import { RequisitionModal } from './RequisitionModal'

const TONE = { approved: 'success', rejected: 'danger', pending: 'warning', none: 'neutral' } as const

/** Where the order is on its way to being placed, in the words the office uses. */
function Stage({ o }: { o: ClientOrder }) {
  const line = 'mt-1 text-xs text-muted-foreground'
  if (o.approval_status === 'approved') return <p className="mt-1 text-xs text-success">Approved - placed</p>
  if (o.approval_status === 'pending')
    return (
      <p className={line}>
        With <strong className="font-medium text-foreground">{o.waiting_on || 'the approver'}</strong>
        {o.waiting_step ? ` (step ${o.waiting_step})` : ''}
      </p>
    )
  if (o.approval_status === 'rejected') return o.rejection_reason ? <p className={line}>{o.rejection_reason}</p> : null
  return <p className={line}>{o.budgeted ? 'Not sent for approval' : 'Budget, then approval'}</p>
}

export default function ClientOrdersPage() {
  const { can, user, isOwner } = useSession()
  const [deleting, setDeleting] = useState<ClientOrder | null>(null)
  const [picked, setPicked] = useState<Set<string | number>>(new Set())
  const [clearing, setClearing] = useState(false)
  const orders = useClientOrders()
  const [creating, setCreating] = useState(false)
  const [fromFile, setFromFile] = useState(false)
  const [budgeting, setBudgeting] = useState<ClientOrder | null>(null)
  const [material, setMaterial] = useState<ClientOrder | null>(null)
  const [viewing, setViewing] = useState<ClientOrder | null>(null)
  const [sendingBack, setSendingBack] = useState<ClientOrder | null>(null)
  const manage = can('workorders.manage')

  const all = orders.data?.work_orders ?? []
  const filters = useListFilters(all, {
    search: (o) => [o.number, o.job_name, o.customer_name, o.reference, o.status].join(' '),
    status: (o) => o.status.toUpperCase(),
    date: (o) => o.order_date,
    facets: { job: { label: 'Projects', get: (o) => o.job_name }, customer: { label: 'Customers', get: (o) => o.customer_name } },
  })
  const s = orders.data?.summary

  const invalidate = [clientOrderKeys.all, ['approvals']]
  const place = useAction((o: ClientOrder) => placeClientOrder(o.id), {
    invalidate,
    success: (r) => r.message + (r.work_order?.approval_status === 'approved' ? ' It can now be measured and billed.' : ''),
  })
  const decide = useAction((a: { o: ClientOrder; decision: 'approve' | 'reject'; note: string }) => decideClientOrder(a.o.id, a.decision, a.note), {
    invalidate,
    success: (r, a) => {
      const st = r.work_order?.approval_status ?? r.status
      if (st === 'approved') return `${a.o.number} approved and placed. It can now be measured.`
      if (st === 'rejected') return 'Sent back.'
      return `Signed - it now goes to ${r.work_order?.waiting_on || 'the next approver'}.`
    },
    onSuccess: () => setSendingBack(null),
  })

  /** The one thing this order needs next, and nothing else. */
  const rowActions = (o: ClientOrder) => {
    const budget = (primary: boolean) => (
      <Button size="sm" variant={primary ? 'primary' : 'outline'} onClick={() => setBudgeting(o)}>
        {o.budgeted ? 'Budget' : 'Allocate budget'}
      </Button>
    )
    const ap = o.approval_status
    if (ap === 'approved')
      return (
        <>
          <Button size="sm" asChild>
            <Link to="/clients/measurement" title="Record what has been built against this order">
              <Ruler /> Measure
            </Link>
          </Button>
          {budget(false)}
          {o.budgeted && (
            <Button size="sm" variant="outline" onClick={() => setMaterial(o)} title="What still has to be bought for this order">
              <ShoppingCart /> Material
            </Button>
          )}
        </>
      )
    if (ap === 'pending')
      return (
        <>
          {can('subcontracts.approve') ? (
            <>
              <Button size="sm" loading={decide.isPending} onClick={() => decide.mutate({ o, decision: 'approve', note: 'Approved' })} title="Sign it off - it is placed once the last signature is on">
                Approve
              </Button>
              <Button size="sm" variant="outline" onClick={() => setSendingBack(o)}>
                Send back
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" asChild>
              <Link to="/approvals">Open in Approvals</Link>
            </Button>
          )}
          {budget(false)}
        </>
      )
    if (!o.budgeted) return budget(true)
    return (
      <>
        <Button size="sm" loading={place.isPending && place.variables?.id === o.id} onClick={() => place.mutate(o)} title="Sends it for approval. It is placed once approved.">
          {ap === 'rejected' ? 'Send again' : o.status === 'Placed' ? 'Send for approval' : 'Place order'}
        </Button>
        {budget(false)}
      </>
    )
  }

  const columns: TableColumn<ClientOrder>[] = [
    {
      id: 'no',
      header: 'Work order',
      width: '9rem',
      sort: (o) => o.number,
      cell: (o) => (
        <div>
          <span className="font-mono text-[13px] font-semibold">{o.number}</span>
          <div className="mt-1 whitespace-nowrap text-xs" onClick={(e) => e.stopPropagation()}>
            <a className="text-primary underline-offset-2 hover:underline" href={`/api/erp/work-orders/${o.id}/export.xlsx`}>
              Excel
            </a>
            {' · '}
            <a className="text-primary underline-offset-2 hover:underline" href={`/api/erp/work-orders/${o.id}/export.pdf`} target="_blank" rel="noopener">
              PDF
            </a>
          </div>
        </div>
      ),
    },
    {
      id: 'job',
      header: 'Job',
      sort: (o) => o.job_name,
      cell: (o) => (
        <div className="min-w-44 max-w-xs">
          <div className="truncate">{o.job_name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {o.customer_name}
            {o.reference ? ` · ${o.reference}` : ''}
          </div>
        </div>
      ),
    },
    { id: 'date', header: 'Ordered', hideBelow: 'xl', sort: (o) => o.order_date, cell: (o) => formatDate(o.order_date) },
    { id: 'lines', header: 'Lines', hideBelow: 'lg', align: 'right', cell: (o) => o.line_count },
    { id: 'value', header: 'Value', align: 'right', sort: (o) => o.total_value, cell: (o) => formatINR(o.total_value) },
    { id: 'budget', header: 'Budget', hideBelow: 'lg', align: 'right', cell: (o) => (o.budgeted ? formatINR(o.budget_cost) : <span className="text-subtle">not budgeted</span>) },
    {
      id: 'margin',
      header: 'Margin',
      hideBelow: 'md',
      align: 'right',
      cell: (o) =>
        o.budgeted ? (
          <div className={o.margin < 0 ? 'text-danger' : 'text-success'}>
            <span className="font-medium">{formatINR(o.margin)}</span>
            <div className="text-xs font-normal text-muted-foreground">{o.margin_percent}%</div>
          </div>
        ) : (
          '-'
        ),
    },
    {
      id: 'status',
      header: 'Status',
      cell: (o) => (
        <div className="max-w-56">
          <Badge tone={TONE[o.approval_status] ?? 'neutral'}>{o.status}</Badge>
          <Stage o={o} />
        </div>
      ),
    },
    { id: 'act', header: '', align: 'right', cell: (o) => <div className="ml-auto flex max-w-64 flex-wrap justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>{rowActions(o)}{isOwner && <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" aria-label={`Delete ${o.number}`} onClick={() => setDeleting(o)}><Trash2 /></Button>}{o.budgeted && <Button size="sm" variant="outline" asChild><Link to={`/clients/work-orders/${o.id}/budget-report`} title="The budget read back under the lines it was allocated against">Report</Link></Button>}</div> },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Clients"
        title="Client Work Orders"
        description="Orders received from clients: the work we are paid for. Its budget, measurement and RA bills hang off it. Orders we give to contractors are under Subcontractors."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href="/api/erp/work-orders/template">
                <Download /> Sheet template
              </a>
            </Button>
            {manage && (
              <>
                <Button variant="outline" onClick={() => setFromFile(true)} title="Bring in an order that already exists as a sheet">
                  <FileUp /> From a file
                </Button>
                <Button onClick={() => setCreating(true)}>
                  <Plus /> New client work order
                </Button>
              </>
            )}
          </>
        }
      />

      <StatGrid className="xl:grid-cols-4">
        <Stat label="Work orders" value={s?.count ?? 0} loading={orders.isPending} />
        <Stat label="Awaiting approval" value={s?.awaiting_approval ?? 0} tone={s?.awaiting_approval ? 'warning' : undefined} loading={orders.isPending} />
        <Stat label="Order value" value={compactINR(s?.total_value)} loading={orders.isPending} />
        <Stat label="Expected margin" value={compactINR(s?.total_margin)} loading={orders.isPending} />
      </StatGrid>

      <FilterBar filters={filters} placeholder="Search by number, job, customer or reference..." />

      {isOwner && <BulkBar count={picked.size} noun="work order" shown={filters.filtered.length} onClear={() => setPicked(new Set())} onDelete={() => setClearing(true)} />}
      <DataTable
        label="Client work orders"
        selection={isOwner ? { selected: picked, onChange: setPicked } : undefined}
        rows={filters.filtered}
        columns={columns}
        rowKey={(o) => o.id}
        loading={orders.isPending}
        onRowClick={setViewing}
        empty={filters.active ? 'Nothing matches those filters.' : 'No work orders yet. Start one with New client work order.'}
      />

      <NewClientOrderModal open={creating} onOpenChange={setCreating} staff={user?.type === 'employee'} onCreated={(o) => setBudgeting(o)} />
      <OrderSheetModal open={fromFile} onOpenChange={setFromFile} staff={user?.type === 'employee'} />
      <BudgetModal order={budgeting} onClose={() => setBudgeting(null)} />
      <BulkDeleteDialog open={clearing} onOpenChange={setClearing} kind="client" noun="work order" ids={[...picked].map(Number)} onFinished={() => setPicked(new Set())} detail="Each goes with its measurements, RA bills, variations and budget. This cannot be undone." />
      <DeleteOrderDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} kind="client" id={deleting?.id ?? 0} number={deleting?.number ?? ''} onDeleted={() => setDeleting(null)} />
      <RequisitionModal order={material} onClose={() => setMaterial(null)} />
      <OrderDetailModal order={viewing} onClose={() => setViewing(null)} />
      <ConfirmDialog
        open={!!sendingBack}
        onOpenChange={(o) => !o && setSendingBack(null)}
        title={`Send ${sendingBack?.number ?? ''} back?`}
        description="It goes back to whoever made it, with what you write."
        confirmLabel="Send back"
        reason={{ label: 'What needs putting right before it is placed?', required: true }}
        loading={decide.isPending}
        onConfirm={(note) => {
          if (sendingBack) decide.mutate({ o: sendingBack, decision: 'reject', note })
        }}
      />
    </>
  )
}
