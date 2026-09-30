import { useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Input } from '@/components/ui'
import { useCustomers, type Customer } from '@/api/customers'
import { useDebounced } from '@/lib/hooks'
import { useSession } from '@/lib/session'
import { CustomerFormModal } from './CustomerFormModal'

export default function CustomersPage() {
  const { can } = useSession()
  const [q, setQ] = useState('')
  const search = useDebounced(q)
  const customers = useCustomers(search)
  const [editing, setEditing] = useState<Customer | null>(null)
  const [creating, setCreating] = useState(false)
  const manage = can('customers.manage')

  const columns: TableColumn<Customer>[] = [
    { id: 'code', header: 'Code', width: '6rem', sort: (c) => c.code, cell: (c) => <span className="font-mono text-[13px] font-semibold">{c.code}</span> },
    {
      id: 'name',
      header: 'Customer',
      sort: (c) => c.name,
      cell: (c) => (
        <div className="max-w-xs">
          <div className="truncate font-medium">{c.name}</div>
          {c.contact_person && <div className="truncate text-xs text-muted-foreground">{c.contact_person}</div>}
        </div>
      ),
    },
    {
      id: 'contact',
      header: 'Contact',
      hideBelow: 'md',
      cell: (c) => (
        <div className="text-[13px]">
          {c.email || <span className="text-subtle">-</span>}
          {c.phone_number && <div className="text-xs text-muted-foreground">{c.phone_number}</div>}
        </div>
      ),
    },
    {
      id: 'tax',
      header: 'GSTIN',
      hideBelow: 'lg',
      cell: (c) => (
        <div className="font-mono text-xs">
          {c.gstin || <span className="text-subtle">-</span>}
          {c.pan && <div className="text-muted-foreground">PAN {c.pan}</div>}
          {(c.city || c.state) && <div className="font-sans text-muted-foreground">{[c.city, c.state].filter(Boolean).join(', ')}</div>}
        </div>
      ),
    },
    { id: 'projects', header: 'Projects', align: 'right', sort: (c) => c.projects ?? 0, cell: (c) => c.projects ?? 0 },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (c) =>
        manage ? (
          <Button size="sm" variant="outline" onClick={() => setEditing(c)}>
            Edit
          </Button>
        ) : null,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Clients"
        title="Customers"
        description="The party a project belongs to, and the detail its paperwork needs."
        actions={
          manage && (
            <Button onClick={() => setCreating(true)}>
              <Plus /> Add new customer
            </Button>
          )
        }
      />
      <div className="mb-4 max-w-sm">
        <Input type="search" aria-label="Search customers" placeholder="Search by name, code or GSTIN" value={q} onChange={(e) => setQ(e.target.value)} leading={<Search />} />
      </div>
      <DataTable label="Customers" rows={customers.data ?? []} columns={columns} rowKey={(c) => c.id} loading={customers.isPending} empty={search ? 'Nothing matches that.' : 'No customers yet. Add the first one to start a project against it.'} />
      <CustomerFormModal open={creating || !!editing} customer={editing} onClose={() => { setCreating(false); setEditing(null) }} />
    </>
  )
}
