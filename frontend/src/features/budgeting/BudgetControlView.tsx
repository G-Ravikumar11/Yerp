import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Card, Stat, StatGrid, Tabs } from '@/components/ui'
import { LoadError } from '@/features/equipment/plantParts'
import { STATUS_TONE, useProjectBudgetControl, type BudgetControlLine } from '@/api/budgetControl'
import { compactINR, formatINR } from '@/lib/utils'

const qty = (n: number, unit: string) => `${n.toLocaleString('en-IN', { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}`

/**
 * HO QS budget control for one project: every applicable BOQ line, how much of it is budgeted, given to contractors and
 * left. The figures are the server's - the same ones a work order is checked against when it is sent.
 */
export function BudgetControlView({ job, onEdit }: { job: number; onEdit?: (key: string) => void }) {
  const q = useProjectBudgetControl(job)
  const [show, setShow] = useState<'todo' | 'all'>('todo')
  const d = q.data
  const s = d?.summary
  const rows = (d?.lines ?? []).filter((l) => show === 'all' || l.status !== 'Budgeted')
  const cols: TableColumn<BudgetControlLine>[] = [
    { id: 'no', header: 'Item', width: '4.5rem', sort: (l) => l.item_no, cell: (l) => <div>{l.item_no || '-'}{l.item_code && <div className="font-mono text-[11px] text-muted-foreground">{l.item_code}</div>}</div> },
    { id: 'd', header: 'Description', sort: (l) => l.description, cell: (l) => <div className="min-w-[10rem] max-w-[22rem]">{l.description.split('\n')[0]}</div> },
    { id: 'u', header: 'Unit', hideBelow: 'md', cell: (l) => l.unit || '-' },
    { id: 'aq', header: 'Approved qty', align: 'right', sort: (l) => l.approved_qty, cell: (l) => qty(l.approved_qty, '') },
    { id: 'bq', header: 'Budgeted qty', align: 'right', hideBelow: 'lg', cell: (l) => qty(l.budgeted_qty, '') },
    { id: 'rq', header: 'Remaining qty', align: 'right', hideBelow: 'md', cell: (l) => <span className={l.remaining_qty > 0 ? 'font-semibold text-danger' : ''}>{qty(l.remaining_qty, '')}</span> },
    { id: 'av', header: 'Approved value', align: 'right', sort: (l) => l.approved_value, cell: (l) => formatINR(l.approved_value) },
    { id: 'bv', header: 'Budgeted value', align: 'right', hideBelow: 'lg', cell: (l) => formatINR(l.budgeted_value) },
    { id: 'rv', header: 'Remaining value', align: 'right', sort: (l) => l.remaining_value, cell: (l) => <span className={l.remaining_value > 0 ? 'font-semibold text-danger' : ''}>{formatINR(l.remaining_value)}</span> },
    {
      id: 'wo', header: 'Left for contractors', align: 'right', hideBelow: 'md',
      cell: (l) => l.status !== 'Budgeted' ? <span className="text-muted-foreground">-</span> : (
        <div title={`Budget for contractors ${formatINR(l.contractor_budget)}; committed on work orders ${formatINR(l.committed_value)} (${qty(l.committed_qty, l.unit)})`}>
          <span className={l.available_value < 0 ? 'font-semibold text-danger' : ''}>{formatINR(l.available_value)}</span>
          <div className={`text-xs ${l.available_qty < 0 ? 'text-danger' : 'text-muted-foreground'}`}>{qty(l.available_qty, l.unit)} left</div>
        </div>
      ),
    },
    { id: 's', header: 'Status', sort: (l) => l.status, cell: (l) => <Badge tone={STATUS_TONE[l.status] ?? 'neutral'} dot>{l.status}</Badge> },
  ]
  if (q.isError) return <LoadError message={q.error.message} retry={() => q.refetch()} />
  return (
    <div>
      <StatGrid>
        <Stat label="Budget complete" value={s ? `${s.completion_percent}%` : '-'} sub={s ? `${s.budgeted} of ${s.lines} lines` : undefined} tone={s ? (s.status === 'Complete' ? 'success' : 'warning') : undefined} loading={q.isPending} />
        <Stat label="Partly budgeted" value={s?.partial ?? 0} sub="Material only - no labour or plant & other" tone={s?.partial ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Not budgeted" value={s?.unbudgeted ?? 0} tone={s?.unbudgeted ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Approved value" value={compactINR(s?.approved_value)} loading={q.isPending} />
        <Stat label="Budgeted value" value={compactINR(s?.budgeted_value)} sub={s ? `${s.value_percent}% of the BOQ` : undefined} loading={q.isPending} />
        <Stat label="Value to budget" value={compactINR(s?.remaining_value)} tone={s?.remaining_value ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      {d && !d.live && <Card className="mt-4 p-3 text-[13px] text-muted-foreground">This project is not live, so its work orders are not held to the budget.</Card>}
      {s && s.status !== 'Complete' && s.lines > 0 && d?.live && (
        <p role="status" className="mt-4 rounded-md border border-warning/40 bg-warning-soft p-3 text-[13px]">No work order on this project is sent or approved until every line below is budgeted (labour or plant & other set).</p>
      )}
      <div className="my-4"><Tabs label="Lines" value={show} onChange={setShow} items={[{ value: 'todo', label: `To budget (${(s?.partial ?? 0) + (s?.unbudgeted ?? 0)})` }, { value: 'all', label: `All lines (${s?.lines ?? 0})` }]} /></div>
      <DataTable label="HO QS budget by BOQ line" rows={rows} columns={cols} rowKey={(l) => l.key} loading={q.isPending}
        empty={show === 'todo' ? 'Every line is budgeted.' : 'The BOQ has no lines with a quantity.'} onRowClick={onEdit ? (l) => onEdit(l.key) : undefined} />
      <p className="mt-2 text-[11px] text-muted-foreground">Quantities are in each line&apos;s own unit, so they are shown per line, never added together. A rate-only line counts once it has a quantity.</p>
    </div>
  )
}
