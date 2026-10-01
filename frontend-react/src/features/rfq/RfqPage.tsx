import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { useRfqs, useStatement, type Rfq } from '@/api/rfq'
import { formatDate } from '@/lib/format'
import { AwardModal } from './AwardModal'
import { NewRfqModal } from './NewRfqModal'
import { QuoteModal } from './QuoteModal'
import { StatementPanel } from './StatementPanel'

const tone = (s: string) => (s === 'AWARDED' ? 'success' : s === 'OPEN' ? 'warning' : 'neutral') as 'success' | 'warning' | 'neutral'

/** Three suppliers asked, their answers side by side, the lowest landed at site - and an award that makes the orders. */
export default function RfqPage() {
  const q = useRfqs()
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [quoting, setQuoting] = useState(false)
  const [awarding, setAwarding] = useState(false)
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
  ]
  return (
    <>
      <PageHeader eyebrow="Store" title="Enquiries & Comparison" description="Three suppliers asked, their answers side by side, the lowest landed at site - and an award that makes the orders." actions={<Button onClick={() => setCreating(true)}><Plus /> Enquiry</Button>} />
      <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
        <Stat label="Open enquiries" value={s?.open ?? 0} loading={q.isPending} />
        <Stat label="Fewer than three quotes" value={s?.waiting_for_quotes ?? 0} tone={s?.waiting_for_quotes ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Awarded" value={s?.awarded ?? 0} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Enquiries" rows={q.data?.rfqs ?? []} columns={columns} rowKey={(r) => r.id} loading={q.isPending} empty="No enquiries yet. Ask three suppliers before an order goes out." />
      {open && <StatementPanel id={open} onClose={() => setOpen(null)} onQuote={() => setQuoting(true)} onAward={() => setAwarding(true)} />}
      <NewRfqModal open={creating} onClose={() => setCreating(false)} onOpened={(id) => { setCreating(false); setOpen(id) }} />
      <QuoteModal statement={statement.data ?? null} open={quoting} onClose={() => setQuoting(false)} />
      <AwardModal statement={statement.data ?? null} open={awarding} onClose={() => setAwarding(false)} />
    </>
  )
}
