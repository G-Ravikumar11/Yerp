import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Input, Select } from '@/components/ui'
import { LoadError } from '@/features/equipment/plantParts'
import { STATUS_TONE, useHoBudgetControl, type LiveProjectBudget } from '@/api/budgetControl'
import { formatINR } from '@/lib/utils'

const STATUSES = ['Incomplete', 'Not started', 'Complete', 'No BOQ lines']

/** HO QS's list: every live project with a BOQ, how much of it is budgeted, and what is left. A row opens its Budgeting page. */
export function HoBudgetControl() {
  const nav = useNavigate()
  const q = useHoBudgetControl(true)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase()
    return (q.data?.projects ?? []).filter((p) => (!status || p.summary.status === status) && (!s || `${p.code} ${p.name}`.toLowerCase().includes(s)))
  }, [q.data, search, status])
  const columns: TableColumn<LiveProjectBudget>[] = [
    { id: 'p', header: 'Project', sort: (p) => p.code, cell: (p) => <div><div className="font-mono text-[13px] font-semibold">{p.code || '-'}</div><div className="max-w-xs truncate text-xs text-muted-foreground">{p.name}</div></div> },
    { id: 'l', header: 'BOQ lines', align: 'right', sort: (p) => p.summary.lines, cell: (p) => p.summary.lines },
    { id: 'b', header: 'Budgeted', align: 'right', sort: (p) => p.summary.budgeted, cell: (p) => p.summary.budgeted },
    { id: 'pt', header: 'Partly', align: 'right', hideBelow: 'md', sort: (p) => p.summary.partial, cell: (p) => <span className={p.summary.partial ? 'text-warning' : ''}>{p.summary.partial}</span> },
    { id: 'u', header: 'Not budgeted', align: 'right', hideBelow: 'md', sort: (p) => p.summary.unbudgeted, cell: (p) => <span className={p.summary.unbudgeted ? 'font-semibold text-danger' : ''}>{p.summary.unbudgeted}</span> },
    { id: 'c', header: 'Complete', align: 'right', sort: (p) => p.summary.completion_percent, cell: (p) => `${p.summary.completion_percent}%` },
    { id: 'r', header: 'Value to budget', align: 'right', hideBelow: 'sm', sort: (p) => p.summary.remaining_value, cell: (p) => formatINR(p.summary.remaining_value) },
    { id: 's', header: 'Status', sort: (p) => p.summary.status, cell: (p) => <Badge tone={STATUS_TONE[p.summary.status] ?? 'neutral'} dot>{p.summary.status}</Badge> },
  ]
  const left = (q.data?.projects ?? []).filter((p) => p.summary.status !== 'Complete' && p.summary.status !== 'No BOQ lines').length
  return (
    <section aria-label="Budget control" className="mb-8">
      <h2 className="mb-1 text-sm font-semibold">Budget control</h2>
      <p className="mb-3 text-[13px] text-muted-foreground">
        Every BOQ line of a live project is budgeted before any work order on it is sent.{q.data && (left ? ` ${left} project${left === 1 ? '' : 's'} still to finish.` : ' Every live project is budgeted.')}
      </p>
      <div className="mb-3 flex flex-wrap gap-2">
        <div className="w-56"><Input aria-label="Search projects" placeholder="Project code or name" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="w-44"><Select aria-label="Budget status" value={status} placeholder="Any status" onChange={(e) => setStatus(e.target.value)} options={STATUSES.map((s) => ({ value: s, label: s }))} /></div>
      </div>
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : (
        <DataTable label="Budget control" rows={rows} columns={columns} rowKey={(p) => p.job_id} loading={q.isPending} onRowClick={(p) => nav(`/projects/budgeting?job=${p.job_id}`)}
          empty={search || status ? 'No project matches.' : 'No live project has a BOQ yet.'} />
      )}
    </section>
  )
}
