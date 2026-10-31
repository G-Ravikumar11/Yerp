import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Ban, Check, Columns3, Download, Pencil } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { PromptModal } from '@/components/data/PromptModal'
import { Badge, Button, Skeleton, Tabs } from '@/components/ui'
import { cancelRfq, rfqKeys, useStatement, type RfqSupplier, type Statement } from '@/api/rfq'
import { stage, supplierRows } from '@/lib/rfqCompare'
import { formatDate } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { AwardModal, type AwardPreset } from './AwardModal'
import { ComparisonDocModal } from './ComparisonDocModal'
import { ComparisonTab } from './ComparisonTab'
import { EnquiryFormModal } from './EnquiryFormModal'
import { ItemsTab } from './ItemsTab'
import { QuoteModal } from './QuoteModal'
import { SuppliersTab } from './SuppliersTab'
import { AskSuppliersModal } from './VendorLinks'

type View = 'compare' | 'suppliers' | 'items'

/** One enquiry: what is asked for, who has been asked and has answered, their quotes side by side, and the award. */
export default function EnquiryPage() {
  const id = Number(useParams().id)
  const q = useStatement(id)
  const d = q.data
  if (q.isPending) return <Skeleton className="h-72 w-full" />
  if (!d) return <p role="alert" className="py-10 text-center text-sm text-danger">That enquiry could not be opened. It may have been deleted.</p>
  return <Enquiry d={d} />
}

function Enquiry({ d }: { d: Statement }) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const quotes = d.suppliers.length
  const asked = (d.invites ?? []).length
  const open = d.rfq.status === 'OPEN'
  const fallback: View = quotes ? 'compare' : 'suppliers'
  const view = (['compare', 'suppliers', 'items'].includes(params.get('view') ?? '') ? params.get('view') : fallback) as View
  const setView = (v: View) => setParams((p) => { const n = new URLSearchParams(p); if (v === fallback) n.delete('view'); else n.set('view', v); return n }, { replace: true })

  const [quoting, setQuoting] = useState<{ supplier: string; existing: RfqSupplier | null } | null>(null)
  const [asking, setAsking] = useState(false)
  const [award, setAward] = useState<AwardPreset | null>(null)
  const [editing, setEditing] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [doc, setDoc] = useState(false)
  const cancel = useAction((reason: string) => cancelRfq(d.rfq.id, reason), { invalidate: [rfqKeys.all], onSuccess: () => setCancelling(false) })

  const st = stage({ status: d.rfq.status, quotes, asked })
  const waiting = (d.invites ?? []).filter((i) => i.status !== 'quoted').length
  // A supplier named: their quote to edit, or the rates they sent as a file to enter. None: a new quote.
  const quoteFor = (supplier = '') => setQuoting({ supplier, existing: (supplier && d.suppliers.find((s) => s.supplier_name.trim().toLowerCase() === supplier.trim().toLowerCase())) || null })

  return (
    <>
      <Link to="/store/enquiries" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Enquiries</Link>
      <PageHeader
        eyebrow={d.rfq.number}
        title={d.rfq.title}
        description={[d.rfq.project || 'No particular project', d.rfq.needed_by && `needed by ${formatDate(d.rfq.needed_by)}`, d.rfq.quotes_due && `quotes due ${formatDate(d.rfq.quotes_due)}`, d.rfq.created_by_name && `opened by ${d.rfq.created_by_name}`].filter(Boolean).join(' · ')}
        actions={
          <>
            <Badge tone={st.tone} dot>{st.label}</Badge>
            <Button variant={view === 'compare' ? 'secondary' : 'outline'} onClick={() => setView('compare')}><Columns3 /> Comparison</Button>
            {quotes > 0 && <Button variant="outline" onClick={() => setDoc(true)}><Download /> Download</Button>}
            {open && <Button variant="outline" onClick={() => setEditing(true)}><Pencil /> Edit</Button>}
            {open && <Button variant="ghost" onClick={() => setCancelling(true)}><Ban /> Cancel enquiry</Button>}
            <MasterDelete kind="rfq" id={d.rfq.id} label={d.rfq.number} noun="enquiry" onDeleted={() => navigate('/store/enquiries')} />
          </>
        }
      />

      <Progress d={d} waiting={waiting} />

      <div className="mb-5 mt-6 w-fit max-w-full">
        <Tabs label="Enquiry" value={view} onChange={setView} items={[
          { value: 'compare', label: 'Comparison' },
          { value: 'suppliers', label: 'Suppliers', count: supplierRows(d).length },
          { value: 'items', label: 'Items', count: d.lines.length },
        ]} />
      </div>

      {view === 'compare' && <ComparisonTab d={d} onAward={setAward} onAsk={() => setAsking(true)} onQuote={quoteFor} />}
      {view === 'suppliers' && <SuppliersTab d={d} onAsk={() => setAsking(true)} onQuote={quoteFor} />}
      {view === 'items' && <ItemsTab d={d} onEdit={() => setEditing(true)} />}

      <QuoteModal statement={d} open={!!quoting} supplier={quoting?.supplier ?? ''} existing={quoting?.existing ?? null} onClose={() => setQuoting(null)} />
      <AskSuppliersModal statement={d} open={asking} onClose={() => setAsking(false)} />
      <AwardModal statement={d} open={!!award} preset={award} onClose={() => setAward(null)} />
      <EnquiryFormModal open={editing} statement={d} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />
      <ComparisonDocModal statement={d} initial={d.suppliers.map((s) => s.supplier_name)} open={doc} onClose={() => setDoc(false)} />
      <PromptModal open={cancelling} title={`Cancel ${d.rfq.number}?`} description="Suppliers' links stop taking quotes and nothing is ordered. The enquiry stays on file, under Cancelled."
        fields={[{ key: 'reason', label: 'Why (optional)' }]} confirm="Cancel the enquiry" busy={cancel.isPending} error={cancel.error?.message}
        onSubmit={(v) => cancel.mutate(v.reason ?? '')} onClose={() => setCancelling(false)} />
    </>
  )
}

/** Three steps, each saying how far it has got: the items listed, the quotes in, the order made. */
function Progress({ d, waiting }: { d: Statement; waiting: number }) {
  const quotes = d.suppliers.length
  const awarded = d.rfq.status === 'AWARDED'
  const cancelled = d.rfq.status === 'CANCELLED'
  const orders = d.orders ?? []
  const steps: { title: string; text: React.ReactNode; state: 'done' | 'now' | 'later' | 'stopped' }[] = [
    { title: 'Items', text: `${d.lines.length} ${d.lines.length === 1 ? 'item' : 'items'} listed`, state: 'done' },
    {
      title: 'Quotes',
      text: quotes ? `${quotes} received${waiting ? ` · ${waiting} waiting` : ''}${quotes < 3 && !awarded && !cancelled ? ' · three make a fair comparison' : ''}` : waiting ? `${waiting} asked, none in yet` : 'Nobody asked yet',
      state: awarded || quotes >= 3 ? 'done' : cancelled ? 'stopped' : 'now',
    },
    {
      title: 'Order',
      text: awarded
        ? orders.length ? <>{orders.map((o, i) => <span key={o.id}>{i > 0 && ', '}<Link className="text-primary hover:underline" to={`/store/purchase-orders?q=${encodeURIComponent(o.number)}`}>{o.number}</Link></span>)}</> : 'Awarded'
        : cancelled ? 'Cancelled' : quotes ? 'Compare, then award' : 'After the quotes',
      state: awarded ? 'done' : cancelled ? 'stopped' : quotes ? 'now' : 'later',
    },
  ]
  return (
    <ol aria-label="Progress" className="grid overflow-hidden rounded-xl border border-border bg-card sm:grid-cols-3">
      {steps.map((s, i) => (
        <li key={s.title} className={cn('flex items-start gap-3 px-4 py-3.5', i > 0 && 'border-t border-border sm:border-l sm:border-t-0')}>
          <span className={cn('mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold',
            s.state === 'done' ? 'bg-success text-white' : s.state === 'now' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>
            {s.state === 'done' ? <Check className="size-3.5" /> : i + 1}
          </span>
          <div className="min-w-0">
            <p className={cn('text-sm font-medium', s.state === 'later' || s.state === 'stopped' ? 'text-muted-foreground' : 'text-foreground')}>{s.title}</p>
            <p className="text-[13px] text-muted-foreground">{s.text}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}
