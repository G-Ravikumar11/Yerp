import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Skeleton } from '@/components/ui'
import { useProjectCosts } from '@/api/costs'
import { formatINR } from '@/lib/utils'
import { CostMixBar } from './CostMix'

function Figures({ title, children }: { title: string; children: React.ReactNode }) {
  return <section aria-label={title} className="mt-4 rounded-xl border border-border bg-card p-5 shadow-card"><h2 className="mb-3 text-sm font-semibold">{title}</h2><div className="flex flex-wrap gap-x-8 gap-y-4">{children}</div></section>
}
const Fig = ({ label, value, tone, sub }: { label: string; value: React.ReactNode; tone?: string; sub?: string }) => <div className="min-w-36 flex-1"><p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p><p className={`tabular font-display text-xl font-semibold ${tone ?? ''}`}>{value}{sub && <span className="ml-1.5 text-[13px] font-normal text-muted-foreground">{sub}</span>}</p></div>

function Papers<T>({ title, rows, columns, empty }: { title: string; rows: T[]; columns: TableColumn<T>[]; empty: string }) {
  return <section aria-label={title} className="mt-6"><h2 className="mb-2 text-sm font-semibold">{title}</h2><DataTable label={title} rows={rows} columns={columns} rowKey={(_, i) => i} empty={empty} /></section>
}

/** One project, and the papers behind each figure. */
export default function ProjectCostsPage() {
  const id = Number(useParams().id)
  const q = useProjectCosts(id)
  const r = q.data
  return (
    <>
      <Link to="/projects/costs" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" /> Cost by Project</Link>
      {q.isPending || !r ? <Skeleton className="h-64 w-full" /> : (
        <>
          <PageHeader title={`${r.number} ${r.name}`} description={r.customer_name || 'No customer set'} />
          <Figures title="The contract">
            <Fig label="Contract value" value={formatINR(r.contract_value)} />
            <Fig label="Estimate" value={formatINR(r.estimate)} />
            <Fig label="Forecast cost" value={formatINR(r.forecast_cost)} tone={r.over_budget > 0 ? 'text-danger' : undefined} />
            <Fig label="Forecast margin" value={formatINR(r.margin)} sub={`${r.margin_percent}%`} tone={r.margin < 0 ? 'text-danger' : 'text-success'} />
          </Figures>
          {r.over_budget > 0 && <p role="alert" className="mt-4 rounded-xl border-l-4 border-danger bg-card p-4 text-sm shadow-card"><strong className="text-danger">{formatINR(r.over_budget)} over the estimate.</strong> <span className="text-muted-foreground">What this job has already cost, plus what is still promised to suppliers and subcontractors, is above what it was estimated to take.</span></p>}
          <Figures title="Where the cost has got to">
            <Fig label="Incurred" value={formatINR(r.incurred)} />
            <Fig label="Labour" value={formatINR(r.labour)} sub={`${r.labour_hours} hrs`} />
            <Fig label="Committed" value={formatINR(r.commitment)} />
            <Fig label="Cost to complete" value={formatINR(r.cost_to_complete)} />
            <Fig label="Complete" value={`${r.percent_complete}%`} />
          </Figures>
          {(r.categories ?? []).some((c) => c.amount > 0) && <section aria-label="Where the money went" className="mt-4 rounded-xl border border-border bg-card p-5 shadow-card"><h2 className="mb-3 text-sm font-semibold">Where the money went</h2><CostMixBar categories={r.categories} /></section>}
          <Figures title="The customer side">
            <Fig label="Invoiced" value={formatINR(r.invoiced)} />
            <Fig label="Earned by the work" value={formatINR(r.earned)} />
            <Fig label={r.over_billed >= 0 ? 'Invoiced ahead by' : 'Work not yet billed'} value={formatINR(Math.abs(r.over_billed))} tone={Math.abs(r.over_billed) >= 1 && r.over_billed > 0 ? 'text-warning' : undefined} />
            <Fig label="Owed to us" value={formatINR(r.outstanding)} />
            <Fig label="Retention held" value={formatINR(r.retention_held)} sub={r.retention_percent ? `${r.retention_percent}%` : undefined} />
          </Figures>
          <Figures title="Owed to suppliers">
            <Fig label="Billed to us" value={formatINR(r.billed)} />
            <Fig label="Paid" value={formatINR(r.paid)} />
            <Fig label="Unpaid" value={formatINR(r.unpaid)} tone={r.unpaid ? 'text-warning' : undefined} />
            <Fig label="Awaiting approval" value={r.bills_awaiting_approval} />
          </Figures>
          <Papers title="Work orders - what was sold" rows={r.work_order_list} empty="Nothing sold on this project yet." columns={[{ id: 'n', header: 'Number', cell: (w) => w.number }, { id: 's', header: 'Status', cell: (w) => w.status }, { id: 'a', header: 'Approval', hideBelow: 'md', cell: (w) => w.approval }, { id: 'v', header: 'Value', align: 'right', cell: (w) => formatINR(w.value) }]} />
          <Papers title="Purchase orders - committed to suppliers" rows={r.purchase_order_list} empty="Nothing ordered from a supplier for this project." columns={[{ id: 'n', header: 'Number', cell: (p) => p.number }, { id: 's', header: 'Supplier', cell: (p) => p.supplier }, { id: 't', header: 'Status', hideBelow: 'md', cell: (p) => p.status }, { id: 'v', header: 'Total', align: 'right', cell: (p) => formatINR(p.total) }]} />
          <Papers title="Subcontract orders - work issued out" rows={r.subcontract_list} empty="Nothing issued to a subcontractor." columns={[{ id: 'n', header: 'Number', cell: (s) => s.number }, { id: 's', header: 'Status', cell: (s) => s.status }, { id: 'v', header: 'Net value', align: 'right', cell: (s) => formatINR(s.net) }]} />
          <Papers title="Bills - what is owed and paid" rows={r.bill_list} empty="No bills against this project." columns={[{ id: 'n', header: 'Number', cell: (b) => b.number }, { id: 's', header: 'Supplier', cell: (b) => b.supplier }, { id: 't', header: 'Status', hideBelow: 'md', cell: (b) => b.status }, { id: 'a', header: 'Approval', hideBelow: 'md', cell: (b) => b.approval }, { id: 'v', header: 'Total', align: 'right', cell: (b) => formatINR(b.total) }]} />
        </>
      )}
    </>
  )
}
