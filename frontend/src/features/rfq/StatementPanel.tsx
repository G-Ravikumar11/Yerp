import { useState } from 'react'
import { ArrowLeft, Check, FileSpreadsheet, Plus, ScanText, Scissors, Trophy } from 'lucide-react'
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

export type CompareView = 'matrix' | 'cards'

interface Props {
  id: number
  /** The `compare` search param as it stands; null means "the default six". */
  compareParam: string | null
  onCompare: (names: string[] | null) => void
  view: CompareView
  onView: (v: CompareView) => void
  onBack: () => void
  onQuote: () => void
  onRead: () => void
  onAward: (preset?: AwardPreset) => void
}

/** Pick up to six of the vendors who quoted and set them side by side: the best single supplier, the best split, and an award from either. */
export function StatementPanel({ id, compareParam, onCompare, view, onView, onBack, onQuote, onRead, onAward }: Props) {
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
          {open && <Button size="sm" variant="ghost" onClick={onRead}><ScanText /> Read a quote</Button>}
          {open && <Button size="sm" variant="outline" onClick={onQuote}><Plus /> Quote</Button>}
          <Button size="sm" variant="outline" disabled={sups.length === 0} onClick={() => setDoc(true)}><FileSpreadsheet /> Comparison</Button>
          {open && sups.length > 0 && <Button size="sm" onClick={() => onAward()}>Award</Button>}
        </div>
      </div>
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
      {sups.length === 0 && <p className="p-5 text-sm text-muted-foreground">No quotes yet. Record each supplier's answer with Quote.</p>}
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
        <div className="flex items-center gap-1.5 text-xs font-medium text-success"><Trophy className="size-3.5" /> Single-vendor best (L1 of {of})</div>
        {l1 ? (
          <>
            <div className="mt-1.5 text-lg font-bold">{l1.supplier_name}</div>
            <div className="text-[13px]"><strong className="tabular">{formatINR(l1.landed)}</strong> landed · {l1.delivery_days ? `${l1.delivery_days} days` : 'delivery not stated'}</div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">{c.savingVsL2 > 0 ? `${formatINR(c.savingVsL2)} under L2` : c.rank.size > 1 ? 'Level with L2' : 'Nobody else compared quoted every line'}</div>
            {open && <Button size="sm" className="mt-3" onClick={() => onAward({ mode: 'one_supplier', supplier: l1.supplier_name })}>Award L1 ({l1.supplier_name})</Button>}
          </>
        ) : <p className="mt-1.5 text-[13px] text-muted-foreground">Nobody compared has quoted every line, so there is no L1 to award the whole order to.</p>}
      </div>
      <div className="rounded-lg border border-info/30 bg-info/5 p-4">
        <div className="flex items-center gap-1.5 text-xs font-medium text-info"><Scissors className="size-3.5" /> Line-by-line best split</div>
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
            {open && <Button size="sm" variant="outline" className="mt-3" disabled={split.vendors < 1} onClick={() => onAward({ mode: 'per_line', awards })}>Award best split</Button>}
          </>
        )}
      </div>
      {d.rfq.award_reason && <p className="text-[13px] md:col-span-2"><strong>Why not the lowest:</strong> {d.rfq.award_reason}</p>}
    </div>
  )
}
