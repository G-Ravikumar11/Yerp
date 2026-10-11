import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { JOB_STATUS, useBoard, type BoardProject } from '@/api/projects'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { ProjectFormModal } from './ProjectFormModal'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

export const marginClass = (percent: number, hasRevenue: boolean) => (!hasRevenue ? 'text-muted-foreground' : percent < 0 ? 'text-danger' : percent < 10 ? 'text-warning' : 'text-success')
const tone = (s: string) => (s === 'complete' ? 'success' : s === 'cancelled' ? 'danger' : s === 'on_hold' ? 'warning' : 'neutral') as 'success' | 'danger' | 'warning' | 'neutral'

/** What each site is making: invoiced, spent, committed, and the margin. */
export default function ProjectsPage() {
  const nav = useNavigate()
  const { can } = useSession()
  const q = useBoard()
  const [editing, setEditing] = useState<BoardProject | 'new' | null>(null)
  const rows = q.data?.jobs ?? []
  const filters = useListFilters(rows, { search: (j) => [j.number, j.name, j.customer_name].join(' '), status: (j) => JOB_STATUS[j.status] ?? j.status })
  const t = q.data?.totals
  const columns: TableColumn<BoardProject>[] = [
    { id: 'no', header: 'Project', sort: (j) => j.number, cell: (j) => <div><span className="font-semibold">{j.number}</span><div className="text-xs text-muted-foreground">{j.name}</div></div> },
    { id: 'cust', header: 'Customer', hideBelow: 'md', cell: (j) => j.customer_name || '-' },
    { id: 'status', header: 'Status', cell: (j) => <div className="flex items-center gap-1.5"><Badge tone={tone(j.status)} dot>{JOB_STATUS[j.status] ?? j.status}</Badge>{j.costing.over_budget && <span className="text-xs font-bold text-danger">over budget</span>}</div> },
    { id: 'inv', header: 'Invoiced', hideBelow: 'md', align: 'right', sort: (j) => j.costing.invoiced, cell: (j) => formatINR(j.costing.invoiced) },
    { id: 'cost', header: 'Cost', hideBelow: 'lg', align: 'right', sort: (j) => j.costing.total_cost, cell: (j) => formatINR(j.costing.total_cost) },
    { id: 'com', header: 'Committed', hideBelow: 'xl', align: 'right', cell: (j) => (j.costing.committed ? formatINR(j.costing.committed) : '-') },
    { id: 'profit', header: 'Profit', align: 'right', sort: (j) => j.costing.profit, cell: (j) => <span className={`font-semibold ${marginClass(j.costing.margin_percent, j.costing.invoiced > 0)}`}>{formatINR(j.costing.profit)}</span> },
    { id: 'margin', header: 'Margin', hideBelow: 'md', align: 'right', cell: (j) => <span className={`font-semibold ${marginClass(j.costing.margin_percent, j.costing.invoiced > 0)}`}>{j.costing.invoiced ? `${j.costing.margin_percent}%` : '-'}</span> },
    { id: 'act', header: '', align: 'right', cell: (j) => can('workorders.manage|reports.view') && <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setEditing(j) }}>Edit</Button> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (j) => <MasterDelete kind="project" id={j.id} label={`${j.number} ${j.name}`} noun="project" /> },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Projects" description="What each site is making." actions={<Button onClick={() => setEditing('new')}><Plus /> New project</Button>} />
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Invoiced" value={formatINR(t?.invoiced ?? 0)} loading={q.isPending} />
        <Stat label="Cost" value={formatINR(t?.cost ?? 0)} loading={q.isPending} />
        <Stat label="Committed" value={formatINR(t?.committed ?? 0)} loading={q.isPending} />
        <Stat label="Profit" value={formatINR(t?.profit ?? 0)} tone={(t?.profit ?? 0) >= 0 ? 'success' : 'danger'} loading={q.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by number, name or customer..." />
      <DataTable label="Projects" rows={filters.filtered} columns={columns} rowKey={(j) => j.id} onRowClick={(j) => nav(`/projects/${j.id}`)} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'No live jobs. Add one and every quote, bill and order can be filed against it.'} />
      <ProjectFormModal project={editing && editing !== 'new' ? editing : null} open={!!editing} onClose={() => setEditing(null)} />
    </>
  )
}
