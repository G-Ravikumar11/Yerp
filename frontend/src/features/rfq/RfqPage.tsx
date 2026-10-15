import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { useRfqs, useStatement, type Rfq } from '@/api/rfq'
import { formatDate } from '@/lib/format'
import { AwardModal, type AwardPreset } from './AwardModal'
import { NewRfqModal } from './NewRfqModal'
import { QuoteModal } from './QuoteModal'
import { AskSuppliersModal } from './VendorLinks'
import { StatementPanel } from './StatementPanel'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

const tone = (s: string) => (s === 'AWARDED' ? 'success' : s === 'OPEN' ? 'warning' : 'neutral') as 'success' | 'warning' | 'neutral'

/** What to do next with an enquiry, in words. */
function nextStep(r: Rfq): { text: string; tone: 'neutral' | 'warning' | 'info' | 'success' } {
  if (r.status === 'AWARDED') return { text: 'Done: orders made', tone: 'success' }
  if (r.status !== 'OPEN') return { text: 'Cancelled', tone: 'neutral' }
  if (r.quotes === 0) return { text: 'Ask suppliers for quotes', tone: 'warning' }
  if (r.quotes < 3) return { text: `Waiting for quotes (${r.quotes} of 3)`, tone: 'info' }
  return { text: 'Compare and award', tone: 'success' }
}

/** Three suppliers asked, their answers side by side, the lowest landed at site - and an award that makes the orders. */
export default function RfqPage() {
  const q = useRfqs()
  // The enquiry, the vendors compared and the view live in the link, so a comparison survives a refresh and can be sent on.
  const [params, setParams] = useSearchParams()
  const open = Number(params.get('id')) || null
  const patch = (next: Record<string, string | null>, replace = true) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(next)) if (v) n.set(k, v); else n.delete(k)
    return n
  }, { replace })
  const setOpen = (id: number | null) => patch({ id: id ? String(id) : null, compare: null, view: null }, false)
  const [creating, setCreating] = useState(false)
  const [quoting, setQuoting] = useState<string | null>(null)       // the supplier, '' for anyone
  const [asking, setAsking] = useState(false)
  const [awarding, setAwarding] = useState(false)
  const [preset, setPreset] = useState<AwardPreset | null>(null)
  const statement = useStatement(open)
  const s = q.data?.summary
  const columns: TableColumn<Rfq>[] = [
    { id: 'no', header: 'No.', cell: (r) => <span className="font-mono font-semibold">{r.number}</span> },
    { id: 'for', header: 'For', cell: (r) => <div>{r.title}<div className="text-xs text-muted-foreground">{r.project}</div></div> },
    { id: 'lines', header: 'Lines', hideBelow: 'md', align: 'right', cell: (r) => r.lines },
    { id: 'quotes', header: 'Quotes', align: 'right', cell: (r) => r.quotes },
    { id: 'need', header: 'Needed by', hideBelow: 'md', cell: (r) => (r.needed_by ? formatDate(r.needed_by) : '-') },
    { id: 'next', header: 'Next step', cell: (r) => { const n = nextStep(r); return <Badge tone={n.tone} dot>{n.text}</Badge> } },
    { id: 'st', header: 'Status', hideBelow: 'lg', cell: (r) => <Badge tone={tone(r.status)}>{r.status === 'OPEN' ? 'Open' : r.status === 'AWARDED' ? 'Awarded' : 'Cancelled'}</Badge> },
    { id: 'a', header: '', align: 'right', cell: (r) => <Button size="sm" variant={r.status === 'OPEN' ? 'primary' : 'outline'} onClick={() => setOpen(r.id)}>Open</Button> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="rfq" id={r.id} label={String(r.number)} noun="enquiry" /> },
  ]
  const filters = useListFilters(q.data?.rfqs, {
    search: (r) => [r.number, r.title, r.project, r.status].join(' '),
    status: (r) => r.status,
    date: (r) => r.needed_by,
  })
  return (
    <>
      <PageHeader eyebrow="Store" title="Enquiries & Comparison" description="Ask suppliers for prices, see their quotes side by side, and give the order to the best one. Each supplier can send their quote through a link, in any format."
        actions={<Button onClick={() => setCreating(true)}><Plus /> New enquiry</Button>} />
      {open ? (
        <StatementPanel id={open} onBack={() => setOpen(null)} onQuote={(supplier) => setQuoting(supplier ?? '')} onAsk={() => setAsking(true)} onAward={(p) => { setPreset(p ?? null); setAwarding(true) }} />
      ) : (
        <>
          <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
            <Stat label="Open enquiries" value={s?.open ?? 0} loading={q.isPending} />
            <Stat label="Fewer than three quotes" value={s?.waiting_for_quotes ?? 0} tone={s?.waiting_for_quotes ? 'warning' : undefined} loading={q.isPending} />
            <Stat label="Awarded" value={s?.awarded ?? 0} loading={q.isPending} />
          </StatGrid>
          <FilterBar filters={filters} placeholder="Search by enquiry, title, project..." />
          <DataTable label="Enquiries" rows={filters.filtered} columns={columns} rowKey={(r) => r.id} loading={q.isPending} empty="No enquiries yet. Press New enquiry, list what you need, then ask suppliers for their prices." />
        </>
      )}
      <NewRfqModal open={creating} onClose={() => setCreating(false)} onOpened={(id) => { setCreating(false); setOpen(id) }} />
      <QuoteModal statement={statement.data ?? null} open={quoting !== null} supplier={quoting ?? ''} onClose={() => setQuoting(null)} />
      {statement.data && <AskSuppliersModal statement={statement.data} open={asking} onClose={() => setAsking(false)} />}
      <AwardModal statement={statement.data ?? null} open={awarding} preset={preset} onClose={() => setAwarding(false)} />
    </>
  )
}
