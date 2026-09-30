import { useRef, useState } from 'react'
import { Download, FileUp, Plus, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Input, Tabs } from '@/components/ui'
import { decideVendor, importVendors, useVendors, vendorKeys, type Registration, type Vendor } from '@/api/vendors'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { VendorFormModal } from './VendorFormModal'

type Tab = '' | Registration

const REG: Record<Registration, { word: string; tone: 'success' | 'warning' | 'danger' }> = {
  APPROVED: { word: 'Registered', tone: 'success' },
  PENDING: { word: 'Awaiting approval', tone: 'warning' },
  REJECTED: { word: 'Sent back', tone: 'danger' },
}

export default function VendorsPage() {
  const { can } = useSession()
  const [tab, setTab] = useState<Tab>('')
  const [q, setQ] = useState('')
  const search = useDebounced(q)
  const vendors = useVendors(tab, search)
  const [editing, setEditing] = useState<Vendor | null>(null)
  const [creating, setCreating] = useState(false)
  const [sendBack, setSendBack] = useState<Vendor | null>(null)
  const file = useRef<HTMLInputElement>(null)

  const decide = useAction((a: { v: Vendor; decision: 'approve' | 'reject'; comments?: string }) => decideVendor(a.v.id, a.decision, a.comments), {
    invalidate: [vendorKeys.all, ['approvals'], ['orders']],
    onSuccess: () => setSendBack(null),
  })
  const bring = useAction((f: File) => importVendors(f), {
    invalidate: [vendorKeys.all],
    onSuccess: (r) => {
      const notes = [...(r.skipped ?? []), ...(r.warnings ?? [])]
      if (notes.length) toast.info(notes.slice(0, 3).join(' '))
    },
  })

  const s = vendors.data?.summary
  const total = s ? s.registered + s.pending + s.sent_back : undefined

  const columns: TableColumn<Vendor>[] = [
    { id: 'code', header: 'Vendor code', width: '7rem', sort: (v) => v.vendor_code, cell: (v) => <span className="font-mono text-[13px] font-semibold">{v.vendor_code || '-'}</span> },
    {
      id: 'name',
      header: 'Sub contractor',
      sort: (v) => v.company_name,
      cell: (v) => (
        <div className="max-w-xs">
          <div className="truncate font-medium">{v.company_name}</div>
          <div className="truncate text-xs text-muted-foreground">{[v.nature_of_work, [v.city, v.state].filter(Boolean).join(', ')].filter(Boolean).join(' · ')}</div>
        </div>
      ),
    },
    { id: 'project', header: 'Project', hideBelow: 'lg', cell: (v) => <span className="text-[13px]">{v.registered_project}</span> },
    {
      id: 'tax',
      header: 'PAN / GST',
      hideBelow: 'md',
      cell: (v) => (
        <div className="font-mono text-xs">
          <div>{v.pan || <span className="text-subtle">no PAN</span>}</div>
          {v.gst_number && <div className="text-muted-foreground">{v.gst_number}</div>}
        </div>
      ),
    },
    {
      id: 'bank',
      header: 'Bank',
      hideBelow: 'xl',
      cell: (v) => (
        <div className="text-[13px]">
          {v.bank_name}
          {v.bank_account && (
            <div className="font-mono text-xs text-muted-foreground">
              {v.bank_account} · {v.bank_ifsc}
            </div>
          )}
        </div>
      ),
    },
    {
      id: 'status',
      header: 'Registration',
      sort: (v) => v.registration_status,
      cell: (v) => (
        <div>
          <Badge tone={REG[v.registration_status]?.tone ?? 'neutral'} dot>
            {REG[v.registration_status]?.word ?? v.registration_status}
          </Badge>
          {(!v.pan || !v.bank_account || !v.bank_ifsc) && <div className="mt-1 text-xs text-warning">No {[!v.pan && 'PAN', (!v.bank_account || !v.bank_ifsc) && 'bank'].filter(Boolean).join(' or ')} on file</div>}
          {v.registration_status === 'REJECTED' && v.rejection_reason && <div className="mt-1 max-w-48 text-xs text-muted-foreground">{v.rejection_reason}</div>}
          {v.registration_status === 'PENDING' && v.registered_by_name && <div className="mt-1 text-xs text-muted-foreground">by {v.registered_by_name}</div>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (v) => (
        <div className="flex flex-wrap justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
          {v.registration_status === 'PENDING' && can('subcontracts.approve') && (
            <>
              <Button size="sm" loading={decide.isPending && decide.variables?.v.id === v.id} onClick={() => decide.mutate({ v, decision: 'approve' })}>
                Approve
              </Button>
              <Button size="sm" variant="outline" onClick={() => setSendBack(v)}>
                Send back
              </Button>
            </>
          )}
          <Button size="sm" variant="outline" onClick={() => setEditing(v)}>
            Form
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`/api/wo/contractors/${v.id}/registration.pdf`} target="_blank" rel="noopener">
              PDF
            </a>
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`/api/wo/contractors/${v.id}/registration.xlsx`}>Excel</a>
          </Button>
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Vendor Register"
        description="Every gang with its vendor code and its Sub Contractor Registration Form. No order is issued to a gang whose form is not signed off."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href="/api/wo/contractors.xlsx">
                <Download /> Excel
              </a>
            </Button>
            {can('workorders.manage|billing.manage') && (
              <>
                <input ref={file} type="file" hidden accept=".xlsx" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) bring.mutate(f) }} />
                <Button variant="outline" loading={bring.isPending} onClick={() => file.current?.click()}>
                  <FileUp /> Import forms
                </Button>
                <Button onClick={() => setCreating(true)}>
                  <Plus /> Register a sub contractor
                </Button>
              </>
            )}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          label="Registration"
          value={tab}
          onChange={setTab}
          items={[
            { value: '', label: 'All vendors', count: total },
            { value: 'APPROVED', label: 'Registered', count: s?.registered },
            { value: 'PENDING', label: 'Awaiting approval', count: s?.pending },
            { value: 'REJECTED', label: 'Sent back', count: s?.sent_back },
          ]}
        />
        <div className="min-w-[14rem] flex-1 sm:max-w-sm">
          <Input type="search" aria-label="Search vendors" placeholder="Search by name, vendor code, work, GSTIN" value={q} onChange={(e) => setQ(e.target.value)} leading={<Search />} />
        </div>
      </div>

      <DataTable
        label="Vendors"
        rows={vendors.data?.contractors ?? []}
        columns={columns}
        rowKey={(v) => v.id}
        loading={vendors.isPending}
        empty={search || tab ? 'Nobody matches that.' : 'No sub contractors yet. Register one, or import the registration forms workbook.'}
      />

      <VendorFormModal vendor={null} open={creating} onOpenChange={setCreating} />
      <VendorFormModal vendor={editing} open={!!editing} onOpenChange={(o) => !o && setEditing(null)} />
      <ConfirmDialog
        open={!!sendBack}
        onOpenChange={(o) => !o && setSendBack(null)}
        title={`Send ${sendBack?.company_name ?? 'it'} back?`}
        description="The form returns to whoever registered it."
        confirmLabel="Send back"
        reason={{ label: 'What is wrong with the form?', required: true }}
        loading={decide.isPending}
        onConfirm={(comments) => {
          if (sendBack) decide.mutate({ v: sendBack, decision: 'reject', comments })
        }}
      />
    </>
  )
}
