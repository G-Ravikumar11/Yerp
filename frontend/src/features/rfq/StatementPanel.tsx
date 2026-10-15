import { useState } from 'react'
import { ArrowLeft, Check, FileSpreadsheet, Link2, Plus, Scissors, Trophy } from 'lucide-react'
import { Badge, Button, Skeleton, Tabs } from '@/components/ui'
import { useStatement, type Statement } from '@/api/rfq'
import { compare, defaultCompare, fastest, MAX_COMPARE, parseCompare, toggleVendor, topLanded, type Comparison } from '@/lib/rfqCompare'
import { formatDate } from '@/lib/format'
import { toast } from '@/stores/toast'
import { cn, formatINR } from '@/lib/utils'
import { Recommendation } from './AiQuotes'
import type { AwardPreset } from './AwardModal'
import { ComparisonDocModal } from './ComparisonDocModal'
import { ComparisonMatrix, Scorecards } from './ComparisonViews'
import { SupplierLinks } from './VendorLinks'

export type CompareView = 'matrix' | 'cards'

interface Props {
  id: number
  /** The `compare` search param as it stands; null means "the default six". */
  compareParam: string | null
  onCompare: (names: string[] | null) => void
  view: CompareView
  onView: (v: CompareView) => void
  onBack: () => void
  /** Add a quote; with a supplier named when their file came through a link without rates. */
  onQuote: (supplier?: string) => void
  /** Ask suppliers to quote through their own link. */
  onAsk: () => void
  onAward: (preset?: AwardPreset) => void
}

/** Pick up to six of the vendors who quoted and set them side by side: the best single supplier, the best split, and an award from either. */
export function StatementPanel({ id, compareParam, onCompare, view, onView, onBack, onQuote, onAsk, onAward }: Props) {
  const q = useStatement(id)
  const d = q.data
  const [doc, setDoc] = useState(false)
  if (q.isPending || !d) return <Skeleton className="mt-6 h-48 w-full" />
  // A link naming vendors who have since gone (or nobody) falls back to the six cheapest landed.
  const fromLink = parseCompare(compareParam, d.suppliers.map((s) => s.supplier_name))
  const selected = fromLink.length ? fromLink : defaultCompare(d.suppliers)
  const c = compare(d, selected)
  const open = d.rfq.status === 'OPEN'
  const sups = d.suppliers
  const toggle = (name: string) => {
    const t = toggleVendor(selected, name, sups.length)
    if (t.ok) onCompare(t.next)
    else toast.info(t.reason === 'max' ? `You can compare up to ${MAX_COMPARE} vendors simultaneously.` : 'Keep at least two vendors to compare.')
  }
  const awardVendor = (name: string) => onAward({ mode: 'one_supplier', supplier: name })
  return (
    <section aria-label={`Comparative statement ${d.rfq.number}`} className="mt-2 rounded-xl border border-border bg-card shadow-card print:border-0 print:shadow-none">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <button type="button" onClick={onBack} className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground print:hidden"><ArrowLeft className="size-3.5" /> Back to Enquiries</button>
          <div className="flex min-w-0 items-center gap-2">
            <h2 className="truncate text-lg font-semibold"><span className="font-mono">{d.rfq.number}</span> <span className="font-normal text-muted-foreground">·</span> {d.rfq.title}</h2>
            {!open && <Badge tone={d.rfq.status === 'AWARDED' ? 'success' : 'neutral'} dot>{d.rfq.status === 'AWARDED' ? 'Awarded' : 'Cancelled'}</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{d.rfq.project || 'No particular project'} · {d.lines.length} {d.lines.length === 1 ? 'line' : 'lines'} · {sups.length} {sups.length === 1 ? 'quote' : 'quotes'}{d.rfq.needed_by && ` · needed by ${formatDate(d.rfq.needed_by)}`}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          {open && <Button size="sm" variant={sups.length < 3 ? 'primary' : 'outline'} onClick={onAsk}><Link2 /> Ask suppliers</Button>}
          {open && <Button size="sm" variant="outline" onClick={() => onQuote()}><Plus /> Add a quote</Button>}
          <Button size="sm" variant="outline" disabled={sups.length === 0} onClick={() => setDoc(true)}><FileSpreadsheet /> Download comparison</Button>
          {open && sups.length > 0 && <Button size="sm" variant={sups.length >= 3 ? 'primary' : 'outline'} onClick={() => onAward()}>Award</Button>}
        </div>
      </div>
      <Steps d={d} />
      <SupplierLinks statement={d} onAddFromFile={(name) => onQuote(name)} />
      {sups.length > 0 && <div className="print:hidden"><Recommendation id={id} /></div>}
      {sups.length > 0 && <BestValue d={d} c={c} open={open} everyone={selected.length === sups.length} onAward={onAward} />}
      {sups.length > 0 && (
        <div className="grid gap-3 border-b border-border px-5 py-4 print:hidden">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="text-sm font-medium" aria-live="polite">Comparing <strong>{c.suppliers.length}</strong> of {sups.length} <span className="font-normal text-muted-foreground">· up to {MAX_COMPARE}</span></span>
            {sups.length > 2 && (
              <div role="group" aria-label="Quick picks" className="inline-flex overflow-hidden rounded-lg border border-border bg-surface text-[13px]">
                {([...(sups.length > MAX_COMPARE ? [['Top 6 (L1 to L6)', () => topLanded(sups, MAX_COMPARE)] as const] : []), ['Top 3', () => topLanded(sups, 3)], ['Fastest delivery', () => fastest(sups, 3)], [sups.length > MAX_COMPARE ? 'Reset' : 'All', () => null]] as const).map(([label, pick]) => (
                  <button key={label} type="button" title={label === 'Fastest delivery' ? 'The three quickest to deliver' : undefined} onClick={() => onCompare(pick())} className="border-r border-border px-3 py-1.5 text-muted-foreground transition-colors last:border-r-0 hover:bg-accent hover:text-foreground">{label}</button>
                ))}
              </div>
            )}
            <div className="ml-auto">
              <Tabs label="View" value={view} onChange={onView} items={[{ value: 'matrix', label: 'Matrix' }, { value: 'cards', label: 'Scorecards' }] as const} />
            </div>
          </div>
          <div role="group" aria-label="Vendors to compare" className="-mx-1 flex gap-1.5 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {sups.map((s) => {
              const on = selected.includes(s.supplier_name)
              return (
                <button key={s.quote_id} type="button" aria-pressed={on} onClick={() => toggle(s.supplier_name)}
                  className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors', on ? 'border-primary/40 bg-primary-soft font-medium text-primary' : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground', !on && selected.length >= MAX_COMPARE && 'opacity-50')}>
                  {on ? <Check className="size-3" /> : <span className="size-3 rounded-full border border-current opacity-40" />}{s.supplier_name}{s.rank && <span className="text-[10px] opacity-70">{s.rank}</span>}
                </button>
              )
            })}
          </div>
        </div>
      )}
      {view === 'cards' && sups.length > 0
        ? <Scorecards d={d} c={c} open={open} onRemove={toggle} onAwardVendor={awardVendor} />
        : <ComparisonMatrix d={d} c={c} open={open} onRemove={toggle} onAwardVendor={awardVendor} />}
      <ComparisonDocModal statement={d} initial={selected} open={doc} onClose={() => setDoc(false)} />
      {sups.length === 0 && <p className="p-5 text-sm text-muted-foreground">No quotes yet. Press <strong>Ask suppliers</strong> to send each supplier a link to quote on their own, or <strong>Add a quote</strong> to enter one you received.</p>}
    </section>
  )
}

/** The two ways to award, priced against each other for the vendors on screen. */
function BestValue({ d, c, open, everyone, onAward }: { d: Statement; c: Comparison; open: boolean; everyone: boolean; onAward: (p: AwardPreset) => void }) {
  const { l1, split } = c
  const awards = [...split.winners].map(([rfq_line_id, supplier_name]) => ({ rfq_line_id, supplier_name }))
  const of = everyone ? 'all quotes' : 'the vendors compared'
  return (
    <div className="grid gap-3 border-b border-border px-5 py-4 md:grid-cols-2">
      <div className="rounded-lg border border-success/30 bg-success/5 p-4">
        <div className="flex items-center gap-1.5 text-xs font-medium text-success"><Trophy className="size-3.5" /> Cheapest one supplier for everything (L1 of {of})</div>
        {l1 ? (
          <>
            <div className="mt-1.5 text-lg font-bold">{l1.supplier_name}</div>
            <div className="text-[13px]"><strong className="tabular">{formatINR(l1.landed)}</strong> total at site · {l1.delivery_days ? `delivery in ${l1.delivery_days} days` : 'delivery not stated'}</div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">{c.savingVsL2 > 0 ? `${formatINR(c.savingVsL2)} cheaper than the next (L2)` : c.rank.size > 1 ? 'Same as the next (L2)' : 'Nobody else compared quoted every item'}</div>
            {open && <Button size="sm" className="mt-3" onClick={() => onAward({ mode: 'one_supplier', supplier: l1.supplier_name })}>Give the whole order to {l1.supplier_name}</Button>}
          </>
        ) : <p className="mt-1.5 text-[13px] text-muted-foreground">Nobody compared has quoted every line, so there is no L1 to award the whole order to.</p>}
      </div>
      <div className="rounded-lg border border-info/30 bg-info/5 p-4">
        <div className="flex items-center gap-1.5 text-xs font-medium text-info"><Scissors className="size-3.5" /> Cheapest if the order is split by item</div>
        {split.uncovered.length ? (
          <p className="mt-1.5 text-[13px] text-muted-foreground">Nobody compared quoted {split.uncovered.map((l) => l.description).slice(0, 3).join(', ')}{split.uncovered.length > 3 && ` and ${split.uncovered.length - 3} more`}. Add a vendor who did.</p>
        ) : (
          <>
            <div className="mt-1.5 text-lg font-bold tabular">{formatINR(split.basic)} <span className="text-[13px] font-normal text-muted-foreground">basic, across {split.vendors} {split.vendors === 1 ? 'vendor' : 'vendors'}</span></div>
            <div className="text-[13px]">
              {!l1 ? 'Each line from whoever quoted it lowest.' : c.splitSaving > 0
                ? <>Splitting orders saves <strong className="text-success">{formatINR(c.splitSaving)}</strong> in basic cost across {split.vendors} vendors vs awarding L1 alone.</>
                : <>Awarding L1 alone is as cheap in basic cost: no split needed.</>}
            </div>
            {!everyone && d.lowest_per_line_basic < split.basic - 0.5 && <div className="mt-0.5 text-[13px] text-muted-foreground">Across all quotes it would be {formatINR(d.lowest_per_line_basic)}.</div>}
            {open && <Button size="sm" variant="outline" className="mt-3" disabled={split.vendors < 1} onClick={() => onAward({ mode: 'per_line', awards })}>Split the order this way</Button>}
          </>
        )}
      </div>
      {d.rfq.award_reason && <p className="text-[13px] md:col-span-2"><strong>Why not the lowest:</strong> {d.rfq.award_reason}</p>}
    </div>
  )
}

/**
 * Where the enquiry stands, in three steps: what is needed, the quotes in hand (three are asked for), and the
 * comparison and award. The next thing to do is the one highlighted.
 */
function Steps({ d }: { d: Statement }) {
  const quotes = d.suppliers.length
  const asked = (d.invites ?? []).length
  const waiting = (d.invites ?? []).filter((i) => i.status === 'sent' || i.status === 'opened').length
  const files = (d.invites ?? []).filter((i) => i.status === 'document').length
  const done = d.rfq.status !== 'OPEN'
  const now = done ? 3 : quotes >= 3 ? 3 : 2
  const steps = [
    { n: 1, title: 'What is needed', text: `${d.lines.length} ${d.lines.length === 1 ? 'item' : 'items'}${d.rfq.needed_by ? `, by ${formatDate(d.rfq.needed_by)}` : ''}` },
    {
      n: 2, title: 'Collect quotes',
      text: `${quotes} of 3 received${asked ? ` · ${asked} asked by link${waiting ? `, ${waiting} not answered yet` : ''}` : ''}${files ? ` · ${files} sent a file to add` : ''}`,
    },
    { n: 3, title: 'Compare and award', text: done ? (d.rfq.status === 'AWARDED' ? 'Awarded: purchase orders made' : 'Cancelled') : quotes >= 2 ? 'Pick the cheapest one supplier, or split by item' : 'Needs at least two quotes' },
  ]
  return (
    <ol aria-label="Steps" className="grid gap-2 border-b border-border px-5 py-3 sm:grid-cols-3 print:hidden">
      {steps.map((st) => {
        const past = st.n < now || done
        const current = st.n === now && !done
        return (
          <li key={st.n} aria-current={current ? 'step' : undefined} className={cn('flex items-start gap-2.5 rounded-lg border px-3 py-2', current ? 'border-primary/50 bg-primary-soft' : 'border-border')}>
            <span className={cn('grid size-6 shrink-0 place-items-center rounded-full text-xs font-bold', past ? 'bg-success text-white' : current ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>{past ? <Check className="size-3.5" /> : st.n}</span>
            <span className="min-w-0"><span className="block text-sm font-semibold">{st.title}</span><span className="block text-xs text-muted-foreground">{st.text}</span></span>
          </li>
        )
      })}
    </ol>
  )
}
