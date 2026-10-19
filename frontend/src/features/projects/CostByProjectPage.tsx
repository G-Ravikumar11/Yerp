import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Printer, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Input, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useCosts, type CostRow } from '@/api/costs'
import { cn, compactINR } from '@/lib/utils'
import { CostMixBar } from './CostMix'
import { alphabetical, rupees } from './figures'

type Filter = 'all' | 'over' | 'negative' | 'unpaid'

const FILTERS: { value: Filter; label: string; test: (r: CostRow) => boolean }[] = [
  { value: 'all', label: 'All', test: () => true },
  { value: 'over', label: 'Over budget', test: (r) => r.over_budget > 0 },
  { value: 'negative', label: 'Negative margin', test: (r) => r.margin < 0 },
  { value: 'unpaid', label: 'Unpaid bills', test: (r) => r.unpaid > 0 },
]

const Progress = ({ percent }: { percent: number }) => {
  const p = Math.max(0, Math.min(100, Math.round(percent || 0)))
  return (
    <div className="ml-auto w-28">
      <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${p}% complete`}>
        <div className="h-full rounded-full bg-primary" style={{ width: `${p}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">{p}% complete</div>
    </div>
  )
}

/** What each job sold for, what it has actually been committed to cost, and what is left - listed A to Z. */
export default function CostByProjectPage() {
  const nav = useNavigate()
  const q = useCosts()
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

  const columns: TableColumn<CostRow>[] = [
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
    { id: 'cv', header: 'Contract', hideBelow: 'md', align: 'right', sort: (r) => r.contract_value, cell: (r) => <span className="font-medium text-foreground">{rupees(r.contract_value)}</span> },
    { id: 'pr', header: 'Progress', hideBelow: 'lg', align: 'right', sort: (r) => r.percent_complete, cell: (r) => <Progress percent={r.percent_complete} /> },
    {
      id: 'inc', header: 'Incurred', align: 'right', sort: (r) => r.incurred,
      cell: (r) => (
        <div>
          <div className="font-medium text-foreground">{rupees(r.incurred)}</div>
          {r.commitment > 0 && <div className="mt-0.5 text-xs text-muted-foreground">+{rupees(r.commitment)} committed</div>}
        </div>
      ),
    },
    {
      id: 'fc', header: 'Forecast cost', hideBelow: 'md', align: 'right', sort: (r) => r.forecast_cost,
      cell: (r) => (
        <div>
          <div className="font-medium text-foreground">{rupees(r.forecast_cost)}</div>
          {r.over_budget > 0 && <div className="mt-0.5 text-xs text-danger">{rupees(r.over_budget)} over estimate</div>}
        </div>
      ),
    },
    {
      id: 'm', header: 'Margin', align: 'right', sort: (r) => r.margin,
      cell: (r) => (
        <div className={r.margin < 0 ? 'text-danger' : r.margin > 0 ? 'text-success' : 'text-muted-foreground'}>
          <div className="font-semibold">{rupees(r.margin)}</div>
          <div className="mt-0.5 text-xs font-medium opacity-90">{r.margin_percent}%</div>
        </div>
      ),
    },
    {
      id: 'i', header: 'Invoiced', hideBelow: 'xl', align: 'right', sort: (r) => r.invoiced,
      cell: (r) => (
        <div>
          <div className="font-medium text-foreground">{rupees(r.invoiced)}</div>
          {Math.abs(r.over_billed) >= 1 && <div className={cn('mt-0.5 text-xs', r.over_billed > 0 ? 'text-warning' : 'text-muted-foreground')}>{r.over_billed > 0 ? 'ahead by ' : 'behind by '}{rupees(Math.abs(r.over_billed))}</div>}
        </div>
      ),
    },
    {
      id: 'u', header: 'Unpaid bills', hideBelow: 'xl', align: 'right', sort: (r) => r.unpaid,
      cell: (r) => (
        <div>
          {r.unpaid ? <span className="font-semibold text-warning">{rupees(r.unpaid)}</span> : <span className="text-muted-foreground">-</span>}
          {r.bills_awaiting_approval > 0 && <div className="mt-0.5 text-xs text-muted-foreground">{r.bills_awaiting_approval} awaiting approval</div>}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Cost by Project"
        description="What each job sold for, what it has actually been committed to cost, and what is left."
        actions={<><Button variant="outline" asChild><a href="/api/costs/by-project.xlsx"><FileSpreadsheet /> Download</a></Button><Button variant="outline" className="print:hidden" onClick={() => window.print()}><Printer /> Print</Button></>}
      />
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Sold" value={compactINR(s?.sold)} loading={q.isPending} />
        <Stat label="Incurred" value={compactINR(s?.incurred)} loading={q.isPending} />
        <Stat label="Committed" value={compactINR(s?.commitment)} loading={q.isPending} />
        <Stat label="Forecast cost" value={compactINR(s?.forecast_cost)} loading={q.isPending} />
        <Stat label="Forecast margin" value={compactINR(s?.margin)} tone={(s?.margin ?? 0) < 0 ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Retention held" value={compactINR(s?.retention_held)} loading={q.isPending} />
        <Stat label="Owed to us" value={compactINR(s?.outstanding)} loading={q.isPending} />
        <Stat label="Over budget" value={`${s?.over_budget ?? 0} project${s?.over_budget === 1 ? '' : 's'}`} tone={s?.over_budget ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <section aria-label="Where the money went" className="mb-6 rounded-xl border border-border bg-card p-4 shadow-card">
        <h2 className="mb-3 text-sm font-semibold">Where the money went</h2>
        {q.isPending ? <Skeleton className="h-10 w-full" /> : <CostMixBar categories={s?.categories ?? []} />}
      </section>

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

      <DataTable label="Cost by project" rows={rows} columns={columns} rowKey={(r) => r.job_id} onRowClick={(r) => nav(`/projects/costs/${r.job_id}`)} loading={q.isPending}
        empty={all.length ? 'No project matches that.' : 'No projects yet. Raise a job, then the orders and bills against it, and the money appears here on its own.'} />
    </>
  )
}
