import { Printer } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { usePnl, type PnlRow } from '@/api/costs'
import { formatINR } from '@/lib/utils'

/** What each project earned against what it truly cost - material, labour and plant included - worst margin first. */
export default function ProjectProfitPage() {
  const q = usePnl()
  const s = q.data?.summary
  const columns: TableColumn<PnlRow>[] = [
    { id: 'p', header: 'Project', sort: (r) => r.number, cell: (r) => <div><span className="font-semibold">{r.number} {r.name}</span><div className="text-xs text-muted-foreground">{r.customer_name}</div></div> },
    { id: 'ov', header: 'Order value', hideBelow: 'md', align: 'right', sort: (r) => r.order_value, cell: (r) => formatINR(r.order_value) },
    { id: 'rev', header: 'Revenue', hideBelow: 'md', align: 'right', sort: (r) => r.revenue, cell: (r) => formatINR(r.revenue) },
    { id: 'cost', header: 'Cost', align: 'right', sort: (r) => r.incurred, cell: (r) => <div>{formatINR(r.incurred)}{r.committed > 0 && <div className="text-xs text-muted-foreground">+{formatINR(r.committed)} committed</div>}</div> },
    { id: 'm', header: 'Margin', align: 'right', sort: (r) => r.margin, cell: (r) => <div className={`font-bold ${r.losing ? 'text-danger' : 'text-success'}`}>{formatINR(r.margin)}<div className="text-xs font-normal">{r.margin_percent}%</div></div> },
    { id: 'md', header: 'Mandays', hideBelow: 'lg', align: 'right', cell: (r) => r.mandays },
    { id: 'st', header: 'Status', cell: (r) => (r.losing ? <Badge tone="danger" dot>losing money</Badge> : r.over_budget ? <Badge tone="warning" dot>over budget</Badge> : <Badge tone="success" dot>{r.status || 'live'}</Badge>) },
    { id: 'x', header: '', align: 'right', cell: (r) => <Button size="sm" variant="outline" asChild><a href={`/api/jobs/${r.job_id}/pnl.xlsx`} title="As a workbook">Download</a></Button> },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Project Profit" description="What each project earned against what it truly cost - material, labour and plant included." actions={<Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button>} />
      <StatGrid>
        <Stat label="Projects" value={s?.projects ?? 0} loading={q.isPending} />
        <Stat label="Order book" value={formatINR(s?.order_value ?? 0)} loading={q.isPending} />
        <Stat label="Revenue" value={formatINR(s?.revenue ?? 0)} loading={q.isPending} />
        <Stat label="Cost incurred" value={formatINR(s?.incurred ?? 0)} loading={q.isPending} />
        <Stat label="Margin" value={formatINR(s?.margin ?? 0)} tone={(s?.margin ?? 0) < 0 ? 'danger' : 'success'} loading={q.isPending} />
        <Stat label="Owed to us" value={formatINR(s?.owed_to_us ?? 0)} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Project profit" rows={q.data?.projects ?? []} columns={columns} rowKey={(r) => r.job_id} loading={q.isPending} empty="No projects yet." />
    </>
  )
}
