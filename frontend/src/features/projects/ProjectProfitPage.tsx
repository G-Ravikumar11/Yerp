import { useMemo, useState } from 'react'
import { Download, Printer, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Input, Modal, Stat, StatGrid } from '@/components/ui'
import { usePnl, useWastage, useWastageByJob, type PnlRow } from '@/api/costs'
import { JOB_STATUS } from '@/api/projects'
import { ProjectPlantCosts } from '@/features/equipment/PlantChecks'
import { cn, compactINR } from '@/lib/utils'
import { alphabetical, percent, rupees } from './figures'

type Filter = 'all' | 'losing' | 'over' | 'unbilled' | 'ontrack'

const FILTERS: { value: Filter; label: string; test: (r: PnlRow) => boolean }[] = [
  { value: 'all', label: 'All', test: () => true },
  { value: 'losing', label: 'Losing money', test: (r) => r.losing },
  { value: 'over', label: 'Over budget', test: (r) => r.over_budget && !r.losing },
  { value: 'unbilled', label: 'Not billed yet', test: (r) => !!r.not_billed && !r.losing && !r.over_budget },
  { value: 'ontrack', label: 'On track', test: (r) => !r.losing && !r.over_budget && !r.not_billed },
]

/** What each project earned against what it truly cost - material, labour and plant included - listed A to Z. */
export default function ProjectProfitPage() {
  const q = usePnl()
  const waste = useWastageByJob()
  const [lost, setLost] = useState<PnlRow | null>(null)
  const totalLost = Object.values(waste.data ?? {}).reduce((a, b) => a + b, 0)
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
      // Nothing billed yet is no margin at all, not a loss of what it has cost so far.
      cell: (r) => (r.not_billed && !r.losing ? <span className="text-xs text-muted-foreground">Not billed yet</span> : (
        <div className={r.losing ? 'text-danger' : 'text-success'}>
          <div className="font-semibold">{rupees(r.margin)}</div>
          <div className="mt-0.5 text-xs font-medium opacity-90">{r.margin_percent}%</div>
        </div>
      )),
    },
    {
      id: 'w', header: 'Wastage loss', align: 'right', sort: (r) => waste.data?.[String(r.job_id)] ?? 0,
      // Material within its limit is cost; only what went past BBS + 2% or the store norm is a loss.
      cell: (r) => {
        const v = waste.data?.[String(r.job_id)] ?? 0
        return v > 0
          ? <button type="button" className="font-semibold text-danger underline-offset-4 hover:underline" onClick={() => setLost(r)} title="Material drawn past its limit - see which">{rupees(v)}</button>
          : <span className="text-xs text-muted-foreground">None</span>
      },
    },
    { id: 'md', header: 'Mandays', hideBelow: 'lg', align: 'right', sort: (r) => r.mandays, cell: (r) => <span className="text-muted-foreground">{r.mandays.toLocaleString('en-IN')}</span> },
    { id: 'st', header: 'Status', cell: (r) => (r.losing ? <Badge tone="danger" dot>Losing money</Badge> : r.over_budget ? <Badge tone="warning" dot>Over budget</Badge> : r.not_billed ? <Badge tone="neutral" dot>Not billed yet</Badge> : <Badge tone="success" dot>{JOB_STATUS[r.status] ?? (r.status || 'Live')}</Badge>) },
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
        <Stat label="Wastage loss" value={compactINR(totalLost)} tone={totalLost > 0 ? 'danger' : undefined} sub="Only material past its limit (BBS + 2%, store norms)" loading={waste.isPending} />
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


/** What one project lost: each material drawn past its limit, by how much, and what that was worth. */
function WastageModal({ row, onClose }: { row: PnlRow; onClose: () => void }) {
  const q = useWastage(row.job_id)
  const d = q.data
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Wastage loss - ${row.name}`} size="lg"
      description="Material within its limit is the project's cost, not a loss. This is only what went past it, valued at what it was issued at. It is already inside the project's material cost.">
      {!d ? <p className="text-sm text-muted-foreground">Loading...</p> : d.rows.length === 0 ? <p className="text-sm text-muted-foreground">Nothing past its limit.</p> : (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-2">Material</th><th className="py-2">Limit</th><th className="py-2 text-right">Allowed</th><th className="py-2 text-right">Used</th><th className="py-2 text-right">Over</th><th className="py-2 text-right">Loss</th>
          </tr></thead>
          <tbody>
            {d.rows.map((w) => (
              <tr key={`${w.item}-${w.boq_item ?? ''}`} className="border-b border-border last:border-0 align-top">
                <td className="py-2"><div className="font-medium">{w.item}</div>{w.boq_item && <div className="text-xs text-muted-foreground">{w.boq_item}</div>}</td>
                <td className="py-2 text-xs text-muted-foreground">{w.basis}</td>
                <td className="py-2 text-right tabular-nums">{w.limit.toLocaleString('en-IN', { maximumFractionDigits: 1 })} {w.uom}</td>
                <td className="py-2 text-right tabular-nums">{w.used.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</td>
                <td className="py-2 text-right tabular-nums text-danger">{w.over.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</td>
                <td className="py-2 text-right font-semibold tabular-nums text-danger">{rupees(w.value)}</td>
              </tr>
            ))}
            <tr><td colSpan={5} className="py-2 text-right font-semibold">Total</td><td className="py-2 text-right font-bold text-danger tabular-nums">{rupees(d.total)}</td></tr>
          </tbody>
        </table>
      )}
    </Modal>
  )
}

