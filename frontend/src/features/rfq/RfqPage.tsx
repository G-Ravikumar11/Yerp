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
import type { ReadQuote } from '@/api/aiPurchasing'
import { ReadQuoteModal } from './AiQuotes'
import { QuoteModal } from './QuoteModal'
import { StatementPanel, type CompareView } from './StatementPanel'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { formatCompare } from '@/lib/rfqCompare'

const tone = (s: string) => (s === 'AWARDED' ? 'success' : s === 'OPEN' ? 'warning' : 'neutral') as 'success' | 'warning' | 'neutral'

/** Three suppliers asked, their answers side by side, the lowest landed at site - and an award that makes the orders. */
export default function RfqPage() {
  const q = useRfqs()
  // The enquiry, the vendors compared and the view live in the link, so a comparison survives a refresh and can be sent on.
  const [params, setParams] = useSearchParams()
  const open = Number(params.get('id')) || null
  // A phone opens on the scorecards unless the link says otherwise; six columns do not fit across one.
  const asked = params.get('view')
  const view: CompareView = asked === 'cards' || asked === 'matrix' ? asked : window.matchMedia('(max-width: 639px)').matches ? 'cards' : 'matrix'
  const patch = (next: Record<string, string | null>, replace = true) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(next)) if (v) n.set(k, v); else n.delete(k)
    return n
  }, { replace })
  const setOpen = (id: number | null) => patch({ id: id ? String(id) : null, compare: null, view: null }, false)
  const [creating, setCreating] = useState(false)
  const [quoting, setQuoting] = useState(false)
  const [reading, setReading] = useState(false)
  const [prefill, setPrefill] = useState<ReadQuote | null>(null)
  const [awarding, setAwarding] = useState(false)
  const [preset, setPreset] = useState<AwardPreset | null>(null)
  const statement = useStatement(open)
  const s = q.data?.summary
  const columns: TableColumn<Rfq>[] = [
    { id: 'no', header: 'No.', cell: (r) => <span className="font-mono font-semibold">{r.number}</span> },
    { id: 'for', header: 'For', cell: (r) => <div>{r.title}<div className="text-xs text-muted-foreground">{r.project}</div></div> },
    { id: 'lines', header: 'Lines', hideBelow: 'md', align: 'right', cell: (r) => r.lines },
    { id: 'quotes', header: 'Quotes', align: 'right', cell: (r) => <span>{r.quotes}{r.status === 'OPEN' && r.quotes < 3 && <span className="ml-1 text-[11px] text-warning">need 3</span>}</span> },
    { id: 'need', header: 'Needed by', hideBelow: 'md', cell: (r) => (r.needed_by ? formatDate(r.needed_by) : '-') },
    { id: 'st', header: 'Status', cell: (r) => <Badge tone={tone(r.status)} dot>{r.status === 'OPEN' ? 'Open' : r.status === 'AWARDED' ? 'Awarded' : 'Cancelled'}</Badge> },
    { id: 'a', header: '', align: 'right', cell: (r) => <Button size="sm" variant={r.status === 'OPEN' ? 'primary' : 'outline'} onClick={() => setOpen(r.id)}>{r.status === 'OPEN' ? 'Quotes & compare' : 'Statement'}</Button> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="rfq" id={r.id} label={String(r.number)} noun="enquiry" /> },
  ]
  const filters = useListFilters(q.data?.rfqs, {
    search: (r) => [r.number, r.title, r.project, r.status].join(' '),
    status: (r) => r.status,
    date: (r) => r.needed_by,
  })
  return (
    <>
      <PageHeader eyebrow="Store" title="Enquiries & Comparison" actions={<Button onClick={() => setCreating(true)}><Plus /> Enquiry</Button>} />
      {open ? (
        <StatementPanel id={open} compareParam={params.get('compare')} onCompare={(names) => patch({ compare: names ? formatCompare(names) : null })} view={view} onView={(v) => patch({ view: v })} onBack={() => setOpen(null)} onQuote={() => { setPrefill(null); setQuoting(true) }} onRead={() => setReading(true)} onAward={(p) => { setPreset(p ?? null); setAwarding(true) }} />
      ) : (
        <>
          <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
            <Stat label="Open enquiries" value={s?.open ?? 0} loading={q.isPending} />
            <Stat label="Fewer than three quotes" value={s?.waiting_for_quotes ?? 0} tone={s?.waiting_for_quotes ? 'warning' : undefined} loading={q.isPending} />
            <Stat label="Awarded" value={s?.awarded ?? 0} loading={q.isPending} />
          </StatGrid>
          <FilterBar filters={filters} placeholder="Search by enquiry, title, project..." />
          <DataTable label="Enquiries" rows={filters.filtered} columns={columns} rowKey={(r) => r.id} loading={q.isPending} empty="No enquiries yet. Ask three suppliers before an order goes out." />
        </>
      )}
      <NewRfqModal open={creating} onClose={() => setCreating(false)} onOpened={(id) => { setCreating(false); setOpen(id) }} />
      <QuoteModal statement={statement.data ?? null} open={quoting} prefill={prefill} onClose={() => setQuoting(false)} />
      {statement.data && <ReadQuoteModal key={statement.data.rfq.id} statement={statement.data} open={reading} onClose={() => setReading(false)} onUse={(q) => { setPrefill(q); setReading(false); setQuoting(true) }} />}
      <AwardModal statement={statement.data ?? null} open={awarding} preset={preset} onClose={() => setAwarding(false)} />
    </>
  )
}
