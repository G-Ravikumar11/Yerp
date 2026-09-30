import { useState } from 'react'
import { FileUp, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, ConfirmDialog, Tabs } from '@/components/ui'
import { billKeys, deleteBill, updateBill, useSupplierBills, type SupplierBill } from '@/api/bills'
import { PayModal } from '@/features/money/PayModal'
import { SheetImportModal } from '@/features/sheetimport/SheetImportModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { BillFormModal } from './BillFormModal'

type Tab = '' | 'Draft' | 'Unpaid' | 'Paid' | 'Overdue'
const TONE: Record<string, 'neutral' | 'warning' | 'success' | 'danger' | 'info'> = { draft: 'neutral', 'awaiting payment': 'warning', unpaid: 'warning', paid: 'success', overdue: 'danger', cancelled: 'neutral', rejected: 'danger', 'partially paid': 'info' }

export default function BillsPage() {
  const { can } = useSession()
  const q = useSupplierBills()
  const [tab, setTab] = useState<Tab>('')
  const [editing, setEditing] = useState<SupplierBill | null>(null)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [accepting, setAccepting] = useState<SupplierBill | null>(null)
  const [paying, setPaying] = useState<SupplierBill | null>(null)
  const [removing, setRemoving] = useState<SupplierBill | null>(null)
  const manage = can('accounts.manage|bills.pay')

  const accept = useAction((b: SupplierBill) => updateBill(b.id, { status: 'Awaiting Payment' }), { invalidate: [billKeys.all, ['owed']], success: (_r, b) => `${b.number} accepted. Pay it when it falls due.`, onSuccess: () => setAccepting(null) })
  const remove = useAction((b: SupplierBill) => deleteBill(b.id), { invalidate: [billKeys.all, ['owed']], success: 'Bill deleted', onSuccess: () => setRemoving(null) })

  const all = q.data ?? []
  const byTab = all.filter((b) => (tab === '' ? true : tab === 'Unpaid' ? b.status !== 'Paid' && b.status !== 'Draft' : b.status.toLowerCase() === tab.toLowerCase()))
  const filters = useListFilters(byTab, { search: (b) => [b.number, b.vendor_name, b.reference].join(' '), date: (b) => b.issue_date })

  const columns: TableColumn<SupplierBill>[] = [
    { id: 'no', header: 'Bill', sort: (b) => b.number, cell: (b) => <span className="font-semibold">{b.number || '-'}</span> },
    { id: 'vendor', header: 'Vendor', sort: (b) => b.vendor_name, cell: (b) => b.vendor_name || '-' },
    { id: 'issue', header: 'Issued', hideBelow: 'lg', sort: (b) => b.issue_date, cell: (b) => formatDate(b.issue_date) || '-' },
    { id: 'due', header: 'Due', hideBelow: 'md', sort: (b) => b.due_date, cell: (b) => formatDate(b.due_date) || '-' },
    { id: 'amount', header: 'Amount', align: 'right', sort: (b) => b.total, cell: (b) => formatINR(b.total) },
    { id: 'paid', header: 'Paid', hideBelow: 'md', align: 'right', cell: (b) => formatINR(b.amount_paid) },
    {
      id: 'status',
      header: 'Status',
      cell: (b) => (
        <div>
          <Badge tone={TONE[(b.status || 'Draft').toLowerCase()] ?? 'neutral'}>{b.status || 'Draft'}</Badge>
          {b.approval_status && b.approval_status !== 'none' && <div className="mt-1 text-xs text-muted-foreground">approval: {b.approval_status}</div>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (b) =>
        manage ? (
          <div className="flex flex-wrap justify-end gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setEditing(b)}>Edit</Button>
            {(b.status || 'Draft') === 'Draft' ? (
              <Button size="sm" onClick={() => setAccepting(b)} title="Checked and owed - it can then be paid">Accept</Button>
            ) : !['Paid', 'Cancelled', 'Rejected'].includes(b.status) ? (
              <Button size="sm" variant="outline" className="border-success text-success" onClick={() => setPaying(b)}>Pay</Button>
            ) : null}
            <Button size="sm" variant="outline" className="border-danger text-danger" onClick={() => setRemoving(b)}>Delete</Button>
          </div>
        ) : null,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Money"
        title="Supplier Bills"
        description="Bills from vendors and suppliers. A new one is a draft: accept it once it has been checked, and it then shows as owed and can be paid."
        actions={
          manage && (
            <>
              <Button variant="outline" onClick={() => setImporting(true)} title="Any workbook with a vendor, an amount and a date"><FileUp /> From Excel</Button>
              <Button onClick={() => setCreating(true)}><Plus /> New bill</Button>
            </>
          )
        }
      />
      <div className="mb-4">
        <Tabs label="Status" value={tab} onChange={setTab} items={[{ value: '', label: 'All' }, { value: 'Draft', label: 'Draft' }, { value: 'Unpaid', label: 'Unpaid' }, { value: 'Paid', label: 'Paid' }, { value: 'Overdue', label: 'Overdue' }]} />
      </div>
      <FilterBar filters={filters} placeholder="Search bills..." />
      <DataTable label="Supplier bills" rows={filters.filtered} columns={columns} rowKey={(b) => b.id} loading={q.isPending} empty={filters.active || tab ? 'No bills found.' : 'No bills yet.'} />

      <BillFormModal open={creating || !!editing} bill={editing} onClose={() => { setCreating(false); setEditing(null) }} />
      <SheetImportModal open={importing} onOpenChange={setImporting} kind="bills" title="Bills from Excel" intro="Any workbook works: a vendor, an amount, a tax figure and a date, in whatever columns and order they come. Each row is brought in as a draft bill to check before sending up." confirmLabel="Bring these in as drafts" invalidate={[billKeys.all]} />
      {paying && <PayModal docType="supplier_bill" docId={paying.id} title={paying.number} open onOpenChange={(o) => !o && setPaying(null)} invalidate={[billKeys.all, ['owed']]} />}
      <ConfirmDialog open={!!accepting} onOpenChange={(o) => !o && setAccepting(null)} title={`Accept ${accepting?.number ?? 'this bill'}?`} description={accepting ? `${accepting.number} from ${accepting.vendor_name} for ${formatINR(accepting.total || accepting.amount)}. It then shows as owed and can be paid.` : undefined} confirmLabel="Accept" loading={accept.isPending} onConfirm={() => { if (accepting) accept.mutate(accepting) }} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${removing?.number ?? 'this bill'}?`} confirmLabel="Delete it" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </>
  )
}
