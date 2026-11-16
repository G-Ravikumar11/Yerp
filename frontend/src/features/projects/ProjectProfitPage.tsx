import { useMemo, useState } from 'react'
import { Download, Printer, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Input, Modal, Stat, StatGrid } from '@/components/ui'
import { usePnl, useWastage, useWastageByJob, type PnlRow, type WastageNorm } from '@/api/costs'
import { JOB_STATUS } from '@/api/projects'
import { ProjectPlantCosts } from '@/features/equipment/PlantChecks'
import { cn, compactINR } from '@/lib/utils'
import { alphabetical, percent, rupees } from './figures'

type Filter = 'all' | 'losing' | 'nobudget' | 'unbilled' | 'ontrack'

const FILTERS: { value: Filter; label: string; test: (r: PnlRow) => boolean }[] = [
  { value: 'all', label: 'All', test: () => true },
  // A loss is only what was spent past the project's allocated budget; spending within it is cost, not loss.
  { value: 'losing', label: 'Over budget (loss)', test: (r) => r.losing },
  { value: 'nobudget', label: 'No budget set', test: (r) => !!r.no_budget && !r.losing },
  { value: 'unbilled', label: 'Not billed yet', test: (r) => !!r.not_billed && !r.losing && !r.no_budget },
  { value: 'ontrack', label: 'Within budget', test: (r) => !r.losing && !r.no_budget && !r.not_billed },
]

/** What each project earned against what it truly cost - material, labour and plant included - listed A to Z. */
export default function ProjectProfitPage() {
  const q = usePnl()
  const waste = useWastageByJob()
  const [lost, setLost] = useState<PnlRow | null>(null)
  const totalLost = Object.values(waste.data ?? {}).reduce((a, b) => a + b.loss, 0)
  const totalUnchecked = Object.values(waste.data ?? {}).reduce((a, b) => a + b.unchecked, 0)
  const s = q.data?.summary
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const all = useMemo(() => (q.data?.projects ?? []).slice().sort(alphabetical), [q.data])
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.value, all.filter(f.test).length])) as Record<Filter, number>, [all])
  const rows = useMemo(() => {
    const test = FILTERS.find((f) => f.value === filter)!.test
    const term = search.trim().toLowerCase()
    return all.filter((r) => test(r) && (!term || `${r.name} ${r.number} ${r.customer_name}`.toLowerCase().includes(term)))
  }, [all, filter, search])

  const columns: TableColumn<PnlRow>[] = [
    {
      id: 'p', header: 'Project', sort: (r) => r.name.toLowerCase(),
      cell: (r) => (
        <div className="min-w-48">
          <div className="font-medium leading-snug text-foreground">{r.name}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            {r.number && <span className="font-mono">{r.number}</span>}
            {r.number && r.customer_name && <span aria-hidden>·</span>}
            <span className="truncate">{r.customer_name}</span>
          </div>
        </div>
      ),
    },
    { id: 'ov', header: 'Order value', hideBelow: 'md', align: 'right', sort: (r) => r.order_value, cell: (r) => <span className="font-medium text-foreground">{rupees(r.order_value)}</span> },
    {
      id: 'rev', header: 'Billed', hideBelow: 'md', align: 'right', sort: (r) => r.revenue,
      cell: (r) => {
        const pct = percent(r.revenue, r.order_value)
        return (
          <div className="ml-auto w-36">
            <div className="font-medium text-foreground">{rupees(r.revenue)}</div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${pct}% of the order value billed`}>
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, pct)}%` }} />
            </div>
            <div className="mt-1 text-[11px] text-muted-foreground">{pct}% of order</div>
          </div>
        )
      },
    },
    {
      id: 'cost', header: 'Cost', align: 'right', sort: (r) => r.incurred,
      cell: (r) => (
        <div>
          <div className="font-medium text-foreground">{rupees(r.incurred)}</div>
          {r.committed > 0 && <div className="mt-0.5 text-xs text-muted-foreground">+{rupees(r.committed)} committed</div>}
        </div>
      ),
    },
    {
      id: 'm', header: 'Margin', align: 'right', sort: (r) => r.margin,
      // Billed less cost so far. Below zero while within budget is cost ahead of billing, not a loss: only spend past the budget is.
      cell: (r) => (r.not_billed && !r.losing ? <span className="text-xs text-muted-foreground">Not billed yet</span> : (
        <div className={r.margin >= 0 ? 'text-success' : r.losing ? 'text-danger' : 'text-muted-foreground'} title={r.margin < 0 && !r.losing ? 'Cost ahead of billing, still within budget' : undefined}>
          <div className="font-semibold">{rupees(r.margin)}</div>
          <div className="mt-0.5 text-xs font-medium opacity-90">{r.margin_percent}%</div>
        </div>
      )),
    },
    {
      id: 'loss', header: 'Loss (over budget)', align: 'right', sort: (r) => r.loss ?? 0,
      // Only what was spent past the allocated budget. Spending up to the budget is the project's cost.
      cell: (r) => ((r.loss ?? 0) > 0
        ? <div className="text-danger"><div className="font-semibold">{rupees(r.loss ?? 0)}</div><div className="mt-0.5 text-xs">over {rupees(r.budgeted_cost ?? 0)} budget</div></div>
        : r.no_budget ? <span className="text-xs text-muted-foreground">No budget set</span>
          : <div><div className="text-xs text-success">None</div><div className="mt-0.5 text-xs text-muted-foreground">{rupees(Math.max(0, (r.budgeted_cost ?? 0) - r.incurred))} left</div></div>),
    },
    {
      id: 'w', header: 'Wastage loss', align: 'right', sort: (r) => { const d = waste.data?.[String(r.job_id)]; return (d?.loss ?? 0) * 1e6 + (d?.wasted ?? 0) },
      // Material within its limit is cost; only what went past BBS + 2% or the store norm is a loss. Wastage the store recorded
      // where no norm is set is shown as well - never hidden as "None" - but is not called a loss past a limit.
      cell: (r) => {
        const d = waste.data?.[String(r.job_id)]
        if (d && d.loss > 0) return (
          <button type="button" className="text-right text-danger underline-offset-4 hover:underline" onClick={() => setLost(r)} title="Material drawn past its limit - see which">
            <div className="font-semibold">{rupees(d.loss)}</div>
            {d.unchecked > 0 && <div className="text-xs text-warning">+{rupees(d.unchecked)} wasted, no norm</div>}
          </button>
        )
        if (d && d.wasted > 0) return (
          <button type="button" className="text-right underline-offset-4 hover:underline" onClick={() => setLost(r)} title="Wastage recorded - see which materials and whether a norm is set">
            <div className="font-semibold text-warning">{rupees(d.wasted)} wasted</div>
            <div className="text-xs text-muted-foreground">{d.unchecked > 0 ? 'Norm not configured' : 'Within norm'}</div>
          </button>
        )
        return <span className="text-xs text-muted-foreground">None</span>
      },
    },
    { id: 'md', header: 'Mandays', hideBelow: 'lg', align: 'right', sort: (r) => r.mandays, cell: (r) => <span className="text-muted-foreground">{r.mandays.toLocaleString('en-IN')}</span> },
    { id: 'st', header: 'Status', cell: (r) => (r.losing ? <Badge tone="danger" dot>Loss: over budget</Badge> : r.no_budget ? <Badge tone="warning" dot>No budget set</Badge> : r.not_billed ? <Badge tone="neutral" dot>Not billed yet</Badge> : <Badge tone="success" dot>{JOB_STATUS[r.status] ?? (r.status || 'Live')}</Badge>) },
    {
      id: 'x', header: '', align: 'right', width: '3rem',
      cell: (r) => <Button size="icon-sm" variant="ghost" asChild><a href={`/api/jobs/${r.job_id}/pnl.xlsx`} aria-label={`Download the workbook for ${r.name}`} title="Download as a workbook"><Download /></a></Button>,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Project Profit"
        description="What each project earned against what it truly cost - material, labour and plant included."
        actions={<Button variant="outline" className="print:hidden" onClick={() => window.print()}><Printer /> Print</Button>}
      />

      <StatGrid>
        <Stat label="Order book" value={compactINR(s?.order_value)} loading={q.isPending} />
        <Stat label="Revenue" value={compactINR(s?.revenue)} loading={q.isPending} />
        <Stat label="Cost incurred" value={compactINR(s?.incurred)} loading={q.isPending} />
        <Stat label="Margin" value={compactINR(s?.margin)} tone={(s?.margin ?? 0) < 0 ? 'danger' : 'success'} sub={s?.cost_not_billed ? `${compactINR(s.cost_not_billed)} spent on work not billed yet` : 'On what has been billed'} loading={q.isPending} />
        <Stat label="Owed to us" value={compactINR(s?.owed_to_us)} loading={q.isPending} />
        <Stat label="Loss (over budget)" value={compactINR(s?.loss ?? 0)} tone={(s?.loss ?? 0) > 0 ? 'danger' : undefined} sub={`Only spend past the allocated budget${s?.no_budget ? ` · ${s.no_budget} without a budget` : ''}`} loading={q.isPending} />
        <Stat label="Wastage loss" value={compactINR(totalLost)} tone={totalLost > 0 ? 'danger' : undefined} sub={totalUnchecked > 0 ? `Past its limit (BBS + 2%, store norms) · ${compactINR(totalUnchecked)} more wasted with no norm set` : 'Only material past its limit (BBS + 2%, store norms)'} loading={waste.isPending} />
      </StatGrid>
      {lost && <WastageModal row={lost} onClose={() => setLost(null)} />}

      <div className="mb-3 flex flex-wrap items-center gap-3 print:hidden">
        <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[13px] font-medium transition-colors',
                filter === f.value ? 'border-primary bg-primary-soft text-primary' : 'border-border bg-card text-muted-foreground hover:text-foreground',
              )}
            >
              {f.label}
              <span className={cn('tabular text-xs', filter === f.value ? 'text-primary' : 'text-subtle')}>{counts[f.value]}</span>
            </button>
          ))}
        </div>
        <div className="ml-auto w-full sm:w-72">
          <Input aria-label="Search projects" placeholder="Search by project, number or client" leading={<Search />} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      <DataTable label="Project profit" rows={rows} columns={columns} rowKey={(r) => r.job_id} loading={q.isPending} empty={all.length ? 'No project matches that.' : 'No projects yet.'} />
      <ProjectPlantCosts />
    </>
  )
}


const NORM_BADGE: Record<WastageNorm, { label: string; tone: 'danger' | 'success' | 'warning' | 'neutral' }> = {
  OVER: { label: 'Over norm', tone: 'danger' },
  WITHIN: { label: 'Within norm', tone: 'success' },
  BBS: { label: 'Over BBS', tone: 'danger' },
  NO_NORM: { label: 'Norm Not Configured', tone: 'warning' },
  NOT_LINKED: { label: 'No BOQ item named', tone: 'neutral' },
}
const qty = (v: number | null, uom = '') => (v == null ? <span className="text-muted-foreground" title="No norm: nothing to compare with">n/a</span> : `${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}${uom ? ` ${uom}` : ''}`)

/** One project's wastage, material by material: what the work should have used, what was used, what was wasted, what the norm allows
 * and what went past it. Where no norm is set the recorded wastage is still shown, with the comparison marked as not available. */
function WastageModal({ row, onClose }: { row: PnlRow; onClose: () => void }) {
  const q = useWastage(row.job_id)
  const d = q.data
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Wastage loss - ${row.name}`} size="xl"
      description="Material within its limit is the project's cost, not a loss: only what went past the norm (or BBS + allowance) is counted as a loss. Wastage the store recorded where no norm is set is shown as it was recorded. All of it is already inside the project's material cost.">
      {q.isError ? <p className="text-sm text-danger" role="alert">{(q.error as Error).message}</p> : !d ? <p className="text-sm text-muted-foreground">Loading...</p> : d.rows.length === 0 ? <p className="text-sm text-muted-foreground">No wastage recorded and nothing past its limit.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-max text-sm">
            <thead><tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="py-2 pr-3">Material</th><th className="py-2 pr-3">Norm status</th>
              <th className="py-2 pr-3 text-right">Expected consumption</th><th className="py-2 pr-3 text-right">Actual consumption</th>
              <th className="py-2 pr-3 text-right">Actual wastage</th><th className="py-2 pr-3 text-right">Allowed wastage</th>
              <th className="py-2 pr-3 text-right">Excess wastage</th><th className="py-2 text-right">Loss</th>
            </tr></thead>
            <tbody>
              {d.rows.map((w) => (
                <tr key={`${w.item}-${w.boq_item ?? ''}-${w.norm}`} className="border-b border-border last:border-0 align-top">
                  <td className="py-2 pr-3"><div className="font-medium">{w.item}</div>{w.boq_item && <div className="text-xs text-muted-foreground">{w.boq_item}</div>}</td>
                  <td className="py-2 pr-3"><Badge tone={NORM_BADGE[w.norm].tone}>{NORM_BADGE[w.norm].label}</Badge><div className="mt-0.5 text-xs text-muted-foreground">{w.basis}</div></td>
                  <td className="py-2 pr-3 text-right tabular-nums">{qty(w.expected, w.uom)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{qty(w.used, w.uom)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-medium">{qty(w.wasted, w.uom)}<div className="text-xs font-normal text-muted-foreground">{rupees(w.wasted_value)}</div></td>
                  <td className="py-2 pr-3 text-right tabular-nums">{qty(w.allowed, w.uom)}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${w.over ? 'text-danger' : ''}`}>{qty(w.over, w.uom)}</td>
                  <td className="py-2 text-right font-semibold tabular-nums">{w.over == null ? <span className="text-xs font-normal text-muted-foreground">No norm to compare</span> : <span className={w.value > 0 ? 'text-danger' : ''}>{rupees(w.value)}</span>}</td>
                </tr>
              ))}
              <tr>
                <td colSpan={4} className="py-2 text-right font-semibold">Total</td>
                <td className="py-2 pr-3 text-right font-semibold tabular-nums">{rupees(d.wasted_value)}</td>
                <td colSpan={2} className="py-2 pr-3 text-right text-xs text-muted-foreground">{d.unchecked_value > 0 ? `${rupees(d.unchecked_value)} of it with no norm set` : ''}</td>
                <td className="py-2 text-right font-bold text-danger tabular-nums">{rupees(d.total)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}

