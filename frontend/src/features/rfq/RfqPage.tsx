import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { GitCompareArrows, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Tabs } from '@/components/ui'
import { useQuoteFiles, useRfqs, type RfqRow } from '@/api/rfq'
import { stage } from '@/lib/rfqCompare'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { EnquiryFormModal } from './EnquiryFormModal'
import { CompareEnquiriesModal } from './CompareEnquiriesModal'
import { QuoteFilesPanel } from './QuoteFilesPanel'

type Show = 'open' | 'awarded' | 'cancelled' | 'files' | 'all'
const STATUS: Record<Exclude<Show, 'all' | 'files'>, string> = { open: 'OPEN', awarded: 'AWARDED', cancelled: 'CANCELLED' }

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
  // Enquiries ticked to compare together.
  const [picked, setPicked] = useState<Set<string | number>>(new Set())
  const [comparing, setComparing] = useState(false)
  // Pressing Compare enquiries puts the list into choosing: boxes appear, and a row click ticks it instead of opening it.
  const [picking, setPicking] = useState(false)
  const stopPicking = () => { setPicking(false); setPicked(new Set()) }
  const toggle = (r: RfqRow) => setPicked((cur) => { const n = new Set(cur); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n })
  const show = (['open', 'awarded', 'cancelled', 'files', 'all'].includes(params.get('show') ?? '') ? params.get('show') : 'open') as Show
  const files = useQuoteFiles()
  const rows = (q.data?.rfqs ?? []).filter((r) => show === 'all' || (show !== 'files' && r.status === STATUS[show]))
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
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => { if (picking) return stopPicking(); if (show === 'files') setShow('open'); setPicking(true) }}><GitCompareArrows /> Compare enquiries</Button>
            <Button onClick={() => setCreating(true)}><Plus /> New enquiry</Button>
          </div>
        } />
      {picking && show !== 'files' && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary-soft/40 px-4 py-2.5">
          <p className="text-sm">
            {picked.size === 0 ? 'Tick the enquiries to compare - at least two.'
              : picked.size === 1 ? 'Tick one more enquiry to compare.'
              : `${picked.size} enquiries ticked: their quotes pooled, item by item, and the better supplier named.`}
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={stopPicking}>Cancel</Button>
            <Button size="sm" disabled={picked.size < 2} onClick={() => setComparing(true)}><GitCompareArrows /> Compare {picked.size >= 2 ? picked.size : ''}</Button>
          </div>
        </div>
      )}
      <div className="mb-4 w-fit max-w-full">
        <Tabs label="Show" value={show} onChange={setShow} items={[
          { value: 'open', label: 'Open', count: s?.open ?? 0 },
          { value: 'awarded', label: 'Awarded', count: s?.awarded ?? 0 },
          { value: 'cancelled', label: 'Cancelled', count: s?.cancelled ?? 0 },
          { value: 'files', label: 'Add files & compare', count: files.data?.files.length ?? 0 },
          { value: 'all', label: 'All', count: q.data?.rfqs.length ?? 0 },
        ]} />
      </div>
      {show === 'files' ? <QuoteFilesPanel /> : (
        <>
        <FilterBar filters={filters} placeholder="Search by number, title, project or supplier..." />
        <DataTable label="Enquiries" rows={filters.filtered} columns={columns} rowKey={(r) => r.id} loading={q.isPending}
          selection={picking ? { selected: picked, onChange: setPicked } : undefined}
          onRowClick={(r) => (picking ? toggle(r) : navigate(`/store/enquiries/${r.id}`))}
          empty={show === 'open' && !filters.active
            ? <div className="py-4"><p className="font-medium text-foreground">No open enquiries</p><p className="mt-1">Press New enquiry, list what you need, then ask suppliers for their rates.</p></div>
            : 'Nothing matches.'} />
        </>
      )}
      {comparing && <CompareEnquiriesModal enquiries={(q.data?.rfqs ?? []).filter((r) => picked.has(r.id))} onClose={() => setComparing(false)} />}
      <EnquiryFormModal open={creating} onClose={() => setCreating(false)} onSaved={(id) => { setCreating(false); navigate(`/store/enquiries/${id}`) }} />
    </>
  )
}
