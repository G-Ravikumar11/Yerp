import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { JOB_STATUS, useProject, type ProjectDoc } from '@/api/projects'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { ProjectFormModal } from './ProjectFormModal'
import { marginClass } from './ProjectsPage'

function Docs({ title, rows, party }: { title: string; rows: ProjectDoc[]; party: (d: ProjectDoc) => string }) {
  if (!rows.length) return null
  const columns: TableColumn<ProjectDoc>[] = [
    { id: 'no', header: title.replace(/s$/, ''), cell: (d) => <span className="font-mono text-[13px] font-semibold">{d.number}</span> },
    { id: 'who', header: 'With', hideBelow: 'md', cell: (d) => party(d) },
    { id: 'date', header: 'Date', hideBelow: 'md', cell: (d) => formatDate(d.issue_date) },
    { id: 'total', header: 'Total', align: 'right', cell: (d) => formatINR(d.total) },
    { id: 'status', header: 'Status', cell: (d) => <span>{d.status}{d.over_order && <span className="ml-1.5 text-xs text-danger">over order</span>}</span> },
  ]
  return <section aria-label={title} className="mb-6"><h2 className="mb-2 text-sm font-semibold">{title}</h2><DataTable label={title} rows={rows} columns={columns} rowKey={(d) => d.id} /></section>
}

/** One project: where the money stands, and every paper filed against it. */
export default function ProjectPage() {
  const id = Number(useParams().id)
  const q = useProject(id)
  const [editing, setEditing] = useState(false)
  const p = q.data
  const c = p?.costing
  const cls = c ? marginClass(c.margin_percent, c.invoiced > 0) : ''
  const none = p && !p.invoices.length && !p.bills.length && !p.purchase_orders.length && !p.quotes.length
  return (
    <>
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" /> All projects</Link>
      {q.isPending || !p || !c ? <Skeleton className="h-64 w-full" /> : (
        <>
          <PageHeader title={`${p.number} - ${p.name}`} description={[p.customer_name, p.site_address, JOB_STATUS[p.status] ?? p.status].filter(Boolean).join(' - ')} actions={<Button variant="outline" onClick={() => setEditing(true)}>Edit</Button>} />
          {c.over_budget && <p role="alert" className="mb-4 rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm font-semibold text-danger">Costs and open orders have passed the {formatINR(c.budget)} budget.</p>}
          <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
            <Stat label="Quoted" value={formatINR(c.quoted)} />
            <Stat label="Invoiced" value={formatINR(c.invoiced)} />
            <Stat label="Received" value={formatINR(c.received)} />
            <Stat label="Cost so far" value={formatINR(c.total_cost)} />
            <Stat label="Committed" value={formatINR(c.committed)} />
            <Stat label="Labour" value={formatINR(c.labour_cost)} sub={`${c.labour_hours}h`} />
            <Stat label="Profit" value={<span className={cls}>{formatINR(c.profit)}</span>} />
            <Stat label="Margin" value={<span className={cls}>{c.invoiced ? `${c.margin_percent}%` : '-'}</span>} />
          </StatGrid>
          {none && <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">Nothing filed against this project yet.</p>}
          <Docs title="Invoices" rows={p.invoices} party={(d) => d.to_contact ?? ''} />
          <Docs title="Purchase orders" rows={p.purchase_orders} party={(d) => d.supplier_name ?? ''} />
          <Docs title="Bills" rows={p.bills} party={(d) => d.vendor_name ?? ''} />
          <Docs title="Quotes" rows={p.quotes} party={() => ''} />
          <ProjectFormModal project={p} open={editing} onClose={() => setEditing(false)} />
        </>
      )}
    </>
  )
}
