import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Printer } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useCosts, type CostRow } from '@/api/costs'
import { formatINR } from '@/lib/utils'
import { CostMixBar } from './CostMix'

const Progress = ({ percent }: { percent: number }) => {
  const p = Math.max(0, Math.min(100, percent || 0))
  return <div className="ml-auto min-w-[70px] max-w-24"><div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${p}%` }} /></div><div className="mt-0.5 text-right text-[11px] text-muted-foreground">{p}%</div></div>
}

/** What each job sold for, what it has actually been committed to cost, and what is left. */
export default function CostByProjectPage() {
  const nav = useNavigate()
  const q = useCosts()
  const s = q.data?.summary
  const columns: TableColumn<CostRow>[] = [
    { id: 'p', header: 'Project', sort: (r) => r.number, cell: (r) => <div><span className="font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.name}</div></div> },
    { id: 'c', header: 'Customer', hideBelow: 'lg', cell: (r) => r.customer_name || '-' },
    { id: 'cv', header: 'Contract', hideBelow: 'md', align: 'right', sort: (r) => r.contract_value, cell: (r) => formatINR(r.contract_value) },
    { id: 'pr', header: 'Progress', hideBelow: 'lg', align: 'right', cell: (r) => <Progress percent={r.percent_complete} /> },
    { id: 'inc', header: 'Incurred', align: 'right', sort: (r) => r.incurred, cell: (r) => <div>{formatINR(r.incurred)}{r.commitment > 0 && <div className="text-xs text-muted-foreground">+ {formatINR(r.commitment)} committed</div>}</div> },
    { id: 'fc', header: 'Forecast cost', hideBelow: 'md', align: 'right', cell: (r) => <div>{formatINR(r.forecast_cost)}{r.over_budget > 0 && <div className="text-xs text-danger">{formatINR(r.over_budget)} over estimate</div>}</div> },
    { id: 'm', header: 'Margin', align: 'right', sort: (r) => r.margin, cell: (r) => <div className={`font-semibold ${r.margin < 0 ? 'text-danger' : r.margin > 0 ? 'text-success' : 'text-muted-foreground'}`}>{formatINR(r.margin)}<div className="text-xs font-normal text-muted-foreground">{r.margin_percent}%</div></div> },
    { id: 'i', header: 'Invoiced', hideBelow: 'xl', align: 'right', cell: (r) => <div>{formatINR(r.invoiced)}{Math.abs(r.over_billed) >= 1 && <div className={`text-xs ${r.over_billed > 0 ? 'text-warning' : 'text-muted-foreground'}`}>{r.over_billed > 0 ? 'ahead by ' : 'behind by '}{formatINR(Math.abs(r.over_billed))}</div>}</div> },
    { id: 'u', header: 'Unpaid bills', hideBelow: 'xl', align: 'right', cell: (r) => <div>{r.unpaid ? <span className="font-semibold text-warning">{formatINR(r.unpaid)}</span> : '-'}{r.bills_awaiting_approval > 0 && <div className="text-xs text-muted-foreground">{r.bills_awaiting_approval} awaiting approval</div>}</div> },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Cost by Project" description="What each job sold for, what it has actually been committed to cost, and what is left." actions={<><Button variant="outline" asChild><a href="/api/costs/by-project.xlsx"><FileSpreadsheet /> Download</a></Button><Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button></>} />
      <StatGrid>
        <Stat label="Sold" value={formatINR(s?.sold ?? 0)} loading={q.isPending} />
        <Stat label="Incurred" value={formatINR(s?.incurred ?? 0)} loading={q.isPending} />
        <Stat label="Committed" value={formatINR(s?.commitment ?? 0)} loading={q.isPending} />
        <Stat label="Forecast cost" value={formatINR(s?.forecast_cost ?? 0)} loading={q.isPending} />
        <Stat label="Forecast margin" value={formatINR(s?.margin ?? 0)} tone={(s?.margin ?? 0) < 0 ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Retention held" value={formatINR(s?.retention_held ?? 0)} loading={q.isPending} />
        <Stat label="Owed to us" value={formatINR(s?.outstanding ?? 0)} loading={q.isPending} />
        <Stat label="Over budget" value={`${s?.over_budget ?? 0} project(s)`} tone={s?.over_budget ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <section aria-label="Where the money went" className="mb-6 rounded-xl border border-border bg-card p-4 shadow-card"><h2 className="mb-3 text-sm font-semibold">Where the money went</h2>{q.isPending ? <Skeleton className="h-10 w-full" /> : <CostMixBar categories={s?.categories ?? []} />}</section>
      <DataTable label="Cost by project" rows={q.data?.projects ?? []} columns={columns} rowKey={(r) => r.job_id} onRowClick={(r) => nav(`/projects/costs/${r.job_id}`)} loading={q.isPending} empty="No projects yet. Raise a job, then the orders and bills against it, and the money appears here on its own." />
    </>
  )
}
