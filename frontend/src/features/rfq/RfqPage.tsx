import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Tabs } from '@/components/ui'
import { useRfqs, type RfqRow } from '@/api/rfq'
import { stage } from '@/lib/rfqCompare'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { EnquiryFormModal } from './EnquiryFormModal'

type Show = 'open' | 'awarded' | 'cancelled' | 'all'
const STATUS: Record<Exclude<Show, 'all'>, string> = { open: 'OPEN', awarded: 'AWARDED', cancelled: 'CANCELLED' }

/** Who has been asked and who has answered, in a few words. */
function suppliersText(r: RfqRow) {
  if (!r.quotes && !r.asked) return <span className="text-muted-foreground">None asked yet</span>
  return (
    <span>
      <span className="font-medium">{r.quotes} {r.quotes === 1 ? 'quote' : 'quotes'}</span>
      {r.waiting > 0 && <span className="text-muted-foreground"> · {r.waiting} waiting</span>}
    </span>
  )
}

/** Every enquiry, by where it has got. Opening one goes to its own page: the items, the suppliers, the comparison. */
export default function RfqPage() {
  const q = useRfqs()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const show = (['open', 'awarded', 'cancelled', 'all'].includes(params.get('show') ?? '') ? params.get('show') : 'open') as Show
  const rows = (q.data?.rfqs ?? []).filter((r) => show === 'all' || r.status === STATUS[show])
  const filters = useListFilters(rows, {
    search: (r) => [r.number, r.title, r.project, ...r.awarded_to, r.best?.supplier_name ?? ''].join(' '),
    facets: { project: { label: 'Project', get: (r) => r.project } },
  })
  // An old link to one enquiry (from a notification, say) opens its page.
  const legacy = Number(params.get('id'))
  if (legacy) return <Navigate to={`/store/enquiries/${legacy}`} replace />

  const s = q.data?.summary
  const columns: TableColumn<RfqRow>[] = [
    {
      id: 'for',
      header: 'Enquiry',
      sort: (r) => r.id,
      cell: (r) => (
        <div className="max-w-[26rem]">
          <div className="flex items-baseline gap-2">
            <span className="shrink-0 font-mono text-xs text-muted-foreground">{r.number}</span>
            <span className="truncate font-medium">{r.title}</span>
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {[r.project, `${r.lines} ${r.lines === 1 ? 'item' : 'items'}`, r.needed_by && `needed by ${formatDate(r.needed_by)}`].filter(Boolean).join(' · ')}
          </div>
        </div>
      ),
    },
    { id: 'sup', header: 'Suppliers', hideBelow: 'sm', sort: (r) => r.quotes, cell: suppliersText },
    {
      id: 'best',
      header: 'Best quote',
      hideBelow: 'md',
      align: 'right',
      sort: (r) => r.best?.landed ?? Number.POSITIVE_INFINITY,
      cell: (r) =>
        r.status === 'AWARDED' && r.awarded_to.length ? (
          <div className="ml-auto max-w-[13rem] text-right">
            <div className="truncate text-[13px]">to {r.awarded_to.join(', ')}</div>
            <div className="text-xs text-muted-foreground">{r.orders} purchase {r.orders === 1 ? 'order' : 'orders'}</div>
          </div>
        ) : r.best ? (
          <div className="ml-auto max-w-[13rem] text-right">
            <div className="font-medium tabular">{formatINR(r.best.landed)}</div>
            <div className="truncate text-xs text-muted-foreground">{r.best.supplier_name}</div>
          </div>
        ) : <span className="text-muted-foreground">-</span>,
    },
    { id: 'stage', header: 'Stage', width: '11rem', cell: (r) => { const st = stage(r); return <Badge tone={st.tone} dot>{st.label}</Badge> } },
    { id: 'master-del', header: '', align: 'right', width: '3rem', cell: (r) => <MasterDelete kind="rfq" id={r.id} label={r.number} noun="enquiry" /> },
  ]
  const setShow = (v: Show) => setParams((p) => { const n = new URLSearchParams(p); if (v === 'open') n.delete('show'); else n.set('show', v); return n }, { replace: true })

  return (
    <>
      <PageHeader eyebrow="Store" title="Enquiries & Comparison" description="Ask suppliers for their rates, compare the quotes side by side, and turn the best one into a purchase order."
        actions={<Button onClick={() => setCreating(true)}><Plus /> New enquiry</Button>} />
      <div className="mb-4 w-fit max-w-full">
        <Tabs label="Show" value={show} onChange={setShow} items={[
          { value: 'open', label: 'Open', count: s?.open ?? 0 },
          { value: 'awarded', label: 'Awarded', count: s?.awarded ?? 0 },
          { value: 'cancelled', label: 'Cancelled', count: s?.cancelled ?? 0 },
          { value: 'all', label: 'All', count: q.data?.rfqs.length ?? 0 },
        ]} />
      </div>
      <FilterBar filters={filters} placeholder="Search by number, title, project or supplier..." />
      <DataTable label="Enquiries" rows={filters.filtered} columns={columns} rowKey={(r) => r.id} loading={q.isPending} onRowClick={(r) => navigate(`/store/enquiries/${r.id}`)}
        empty={show === 'open' && !filters.active
          ? <div className="py-4"><p className="font-medium text-foreground">No open enquiries</p><p className="mt-1">Press New enquiry, list what you need, then ask suppliers for their rates.</p></div>
          : 'Nothing matches.'} />
      <EnquiryFormModal open={creating} onClose={() => setCreating(false)} onSaved={(id) => { setCreating(false); navigate(`/store/enquiries/${id}`) }} />
    </>
  )
}
