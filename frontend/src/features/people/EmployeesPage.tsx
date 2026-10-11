import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Stat, StatGrid, Tabs } from '@/components/ui'
import { useEmployees, useHrStats, type Employee } from '@/api/people'
import { formatDate } from '@/lib/format'
import { EmployeeFormModal } from './EmployeeFormModal'

type Tab = '' | 'active' | 'onboarding' | 'offboarding' | 'terminated'
export const EMPLOYEE_TONE: Record<string, 'success' | 'warning' | 'neutral' | 'danger'> = { active: 'success', onboarding: 'warning', offboarding: 'warning', terminated: 'neutral' }

export default function EmployeesPage() {
  const nav = useNavigate()
  const [tab, setTab] = useState<Tab>('')
  const q = useEmployees(tab)
  const stats = useHrStats()
  const [creating, setCreating] = useState(false)
  const filters = useListFilters(q.data, { search: (e) => [e.full_name, e.email, e.employee_id, e.job_title, e.department_name].join(' ') })
  const s = stats.data

  const columns: TableColumn<Employee>[] = [
    { id: 'name', header: 'Employee', sort: (e) => e.full_name, cell: (e) => <div><span className="font-medium">{e.full_name}</span>{e.level && <Badge className="ml-2" tone="ember">{e.level}</Badge>}<div className="text-xs text-muted-foreground">{e.email}</div></div> },
    { id: 'id', header: 'ID', hideBelow: 'lg', cell: (e) => <span className="font-mono text-[13px]">{e.employee_id || '-'}</span> },
    { id: 'dept', header: 'Department', hideBelow: 'md', sort: (e) => e.department_name, cell: (e) => e.department_name || <span className="text-subtle">none</span> },
    { id: 'title', header: 'Title', hideBelow: 'lg', cell: (e) => e.job_title || '-' },
    { id: 'start', header: 'Started', hideBelow: 'xl', sort: (e) => e.start_date, cell: (e) => formatDate(e.start_date) },
    { id: 'status', header: 'Status', cell: (e) => <Badge tone={EMPLOYEE_TONE[e.status] ?? 'neutral'}>{e.status}</Badge> },
    { id: 'act', header: '', align: 'right', cell: (e) => <Button size="sm" variant="outline" onClick={() => nav(`/people/employees/${e.id}`)}>View</Button> },
  ]

  return (
    <>
      <PageHeader eyebrow="People" title="Employees" description="Everyone who works for the business, the department each belongs to, and what each may do. What you set here is what they see when they sign in." actions={<Button onClick={() => setCreating(true)}><Plus /> Add an employee</Button>} />
      <StatGrid>
        <Stat label="Employees" value={s?.total_employees ?? 0} loading={stats.isPending} />
        <Stat label="Active" value={s?.active ?? 0} loading={stats.isPending} />
        <Stat label="Onboarding" value={s?.onboarding ?? 0} loading={stats.isPending} />
        <Stat label="Offboarding" value={s?.offboarding ?? 0} loading={stats.isPending} />
        <Stat label="Departments" value={s?.departments ?? 0} loading={stats.isPending} />
      </StatGrid>
      <div className="mb-4"><Tabs label="Status" value={tab} onChange={setTab} items={[{ value: '', label: 'All' }, { value: 'active', label: 'Active' }, { value: 'onboarding', label: 'Onboarding' }, { value: 'offboarding', label: 'Offboarding' }, { value: 'terminated', label: 'Terminated' }]} /></div>
      <FilterBar filters={filters} placeholder="Search by name, email, ID, title or department..." />
      <DataTable label="Employees" rows={filters.filtered} columns={columns} rowKey={(e) => e.id} loading={q.isPending} onRowClick={(e) => nav(`/people/employees/${e.id}`)} empty={filters.active ? 'Nothing matches those filters.' : 'No employees found.'} />
      <EmployeeFormModal open={creating} onClose={() => setCreating(false)} />
    </>
  )
}
