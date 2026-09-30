import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button } from '@/components/ui'
import { staffKeys, sendCost, useMyCosts, type MyCost } from '@/api/staff'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { CostFormModal } from './CostFormModal'

const label = (c: MyCost) => (c.approval_status === 'pending' ? 'With approver' : c.approval_status === 'approved' ? 'Approved' : c.approval_status === 'rejected' ? 'Sent back' : 'Not sent')
const tone = (c: MyCost) => (c.approval_status === 'pending' ? 'warning' : c.approval_status === 'approved' ? 'success' : c.approval_status === 'rejected' ? 'danger' : 'neutral') as 'warning' | 'success' | 'danger' | 'neutral'

/** The bills and receipts this person has raised, and where each one is on its way to being paid. */
export default function CostsPage() {
  const q = useMyCosts()
  const [editing, setEditing] = useState<MyCost | null>(null)
  const [creating, setCreating] = useState(false)
  const resend = useAction((c: MyCost) => sendCost(c.id, { vendor_name: c.vendor_name, amount: c.amount, tax_amount: c.tax_amount, issue_date: c.issue_date, reference: c.reference, category: c.category, notes: c.notes, job_id: c.job_id, purchase_order_id: c.purchase_order_id }), { invalidate: [staffKeys.all, ['approvals']], success: (r) => r.message || 'Sent for approval' })
  const rows = q.data ?? []
  const filters = useListFilters(rows, { search: (c) => [c.number, c.vendor_name, c.job_name, c.reference].join(' '), status: label, date: (c) => c.issue_date })
  const columns: TableColumn<MyCost>[] = [
    { id: 'no', header: 'Bill', sort: (c) => c.number, cell: (c) => <span className="font-mono text-[13px] font-semibold">{c.number}</span> },
    { id: 'to', header: 'Owed to', sort: (c) => c.vendor_name, cell: (c) => c.vendor_name },
    { id: 'job', header: 'Job', hideBelow: 'lg', cell: (c) => c.job_name || '-' },
    { id: 'date', header: 'Date', hideBelow: 'xl', sort: (c) => c.issue_date, cell: (c) => formatDate(c.issue_date) },
    { id: 'total', header: 'Total', align: 'right', sort: (c) => c.total, cell: (c) => <>{formatINR(c.total)}{c.over_order && <span className="ml-1.5 text-xs text-danger" title={`More than ${c.purchase_order_number}`}>over order</span>}</> },
    { id: 'status', header: 'Status', cell: (c) => <div><Badge tone={tone(c)} dot>{label(c)}</Badge>{c.rejection_reason && <div className="mt-1 max-w-56 text-xs text-muted-foreground">{c.rejection_reason}</div>}</div> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (c) => (
        <div className="flex justify-end gap-1.5">
          {(c.approval_status === 'rejected' || c.approval_status === 'none') && <Button size="sm" variant="outline" onClick={() => setEditing(c)}>Fix</Button>}
          {c.approval_status === 'none' && <Button size="sm" loading={resend.isPending && resend.variables?.id === c.id} onClick={() => resend.mutate(c)}>Send</Button>}
        </div>
      ),
    },
  ]
  return (
    <>
      <PageHeader eyebrow="My work" title="My Costs" description="Bills and receipts you have raised, and where each is on its way to being paid." actions={<Button onClick={() => setCreating(true)}><Plus /> Raise a cost</Button>} />
      <FilterBar filters={filters} placeholder="Search by bill, who it is owed to, job or reference..." />
      <DataTable label="My costs" rows={filters.filtered} columns={columns} rowKey={(c) => c.id} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'Nothing raised yet. Raise a cost and it goes up the line for approval.'} />
      <CostFormModal open={creating || !!editing} cost={editing} onClose={() => { setCreating(false); setEditing(null) }} />
    </>
  )
}
