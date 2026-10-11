import { useState } from 'react'
import { FileText, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, ConfirmDialog } from '@/components/ui'
import { poKeys, resendPo, savePo, usePurchaseOrders, type PurchaseOrder } from '@/api/purchaseOrders'
import { useSuppliers } from '@/api/ledger'
import { SupplierModal } from '@/features/ledger/SupplierModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { OrderFormModal } from './OrderFormModal'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

const tone = (o: PurchaseOrder) => (o.approval_status === 'pending' ? 'warning' : o.status === 'Approved' || o.status === 'Received' ? 'success' : o.status === 'Rejected' ? 'danger' : 'neutral') as 'warning' | 'success' | 'danger' | 'neutral'

/** Purchase orders: spend agreed before it is committed. Staff raise them for approval; the owner's are agreed by approving here. */
export default function PurchaseOrdersPage() {
  const { can, user } = useSession()
  const staff = user?.type === 'employee'
  const q = usePurchaseOrders(staff)
  const [editing, setEditing] = useState<PurchaseOrder | null>(null)
  const [creating, setCreating] = useState(false)
  const [approving, setApproving] = useState<PurchaseOrder | null>(null)
  const [supplierOf, setSupplierOf] = useState<string | null>(null)
  const suppliers = useSuppliers()
  const approve = useAction((o: PurchaseOrder) => savePo(o.id, { supplier_name: o.supplier_name, amount: o.amount, tax_amount: o.tax_amount, total: o.total, issue_date: o.issue_date, needed_by: o.needed_by, notes: o.notes, job_id: o.job_id, status: 'Approved', line_items: o.line_items.map(({ id: _id, received_qty: _r, ...l }) => l) }, false), { invalidate: [poKeys.all, ['approvals'], ['stock']], success: (_r, o) => `${o.number} approved. Receive the goods under Store, Goods Receipt.`, onSuccess: () => setApproving(null) })
  const resend = useAction((o: PurchaseOrder) => resendPo(o.id), { invalidate: [poKeys.all], success: 'Sent for approval' })

  const rows = q.data ?? []
  const filters = useListFilters(rows, { search: (o) => [o.number, o.supplier_name, o.job_name, o.status, o.reference].join(' '), status: (o) => o.status, date: (o) => o.issue_date })
  const master = suppliers.data?.suppliers.find((s) => s.name === supplierOf) ?? null

  const columns: TableColumn<PurchaseOrder>[] = [
    { id: 'no', header: 'Order', sort: (o) => o.number, cell: (o) => <span className="font-mono text-[13px] font-semibold">{o.number}</span> },
    { id: 'sup', header: 'Supplier', sort: (o) => o.supplier_name, cell: (o) => o.supplier_name },
    { id: 'job', header: 'Job', hideBelow: 'lg', cell: (o) => o.job_name || '-' },
    { id: 'date', header: 'Date', hideBelow: 'xl', sort: (o) => o.issue_date, cell: (o) => formatDate(o.issue_date) },
    { id: 'total', header: 'Total', align: 'right', sort: (o) => o.total, cell: (o) => formatINR(o.total) },
    { id: 'billed', header: 'Billed', hideBelow: 'md', align: 'right', cell: (o) => (o.billed_count ? <>{formatINR(o.billed_total)} <span className="text-xs text-muted-foreground">({o.billed_count})</span></> : '-') },
    { id: 'status', header: 'Status', cell: (o) => <div><Badge tone={tone(o)}>{o.status}</Badge>{o.rejection_reason && <div className="mt-1 max-w-56 text-xs text-muted-foreground">{o.rejection_reason}</div>}</div> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (o) => (
        <div className="flex flex-wrap justify-end gap-1.5">
          {!staff && (o.status === 'Draft' || o.status === 'Rejected') && o.approval_status !== 'pending' && can('purchase.manage|bills.view_all') && <Button size="sm" onClick={() => setApproving(o)}>Approve</Button>}
          {!staff && o.approval_status !== 'pending' && <Button size="sm" variant="outline" onClick={() => setEditing(o)}>Edit</Button>}
          {staff && (o.approval_status === 'rejected' || o.approval_status === 'none') && <Button size="sm" loading={resend.isPending && resend.variables?.id === o.id} onClick={() => resend.mutate(o)}>Send again</Button>}
          {!staff && <Button size="sm" variant="outline" asChild><a href={`/api/purchase-orders/${o.id}/document.pdf`} target="_blank" rel="noopener" title="The order in the ruled form it is signed on"><FileText /> PDF</a></Button>}
          {!staff && <a className="text-xs text-primary underline-offset-2 hover:underline" href={`/api/purchase-orders/${o.id}/export.xlsx`}>Excel</a>}
          {!staff && can('purchase.manage') && <button type="button" className="text-xs text-primary underline-offset-2 hover:underline" onClick={() => setSupplierOf(o.supplier_name)} title="The supplier's PAN, GSTIN, address and contact, as they print on the order">Supplier</button>}
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="purchase_order" id={r.id} label={String(r.number)} noun="purchase order" /> },
  ]

  return (
    <>
      <PageHeader
        eyebrow={staff ? 'Me' : 'Store'}
        title={staff ? 'My Orders' : 'Purchase Orders'}
        description={staff ? 'Get the spend agreed before you commit it.' : 'Spend agreed before it is committed. Goods can be received against an order once it is approved.'}
        actions={<Button onClick={() => setCreating(true)}><Plus /> {staff ? 'Raise an order' : 'New order'}</Button>}
      />
      <FilterBar filters={filters} placeholder="Search by order, supplier, job or reference..." />
      <DataTable label="Purchase orders" rows={filters.filtered} columns={columns} rowKey={(o) => o.id} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'No orders yet. Raising one gets the spend agreed before it is committed.'} />

      <OrderFormModal open={creating || !!editing} order={editing} staff={staff} onClose={() => { setCreating(false); setEditing(null) }} />
      <SupplierModal open={supplierOf !== null} supplier={master} presetName={supplierOf ?? undefined} onClose={() => setSupplierOf(null)} />
      <ConfirmDialog open={!!approving} onOpenChange={(o) => !o && setApproving(null)} title={`Approve ${approving?.number ?? 'this order'}?`} description={approving ? `${approving.number} for ${formatINR(approving.total)} with ${approving.supplier_name}. Goods can then be received against it.` : undefined} confirmLabel="Approve" loading={approve.isPending} onConfirm={() => { if (approving) approve.mutate(approving) }} />
    </>
  )
}
