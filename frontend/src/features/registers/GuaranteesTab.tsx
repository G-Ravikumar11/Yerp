import { Link } from 'react-router-dom'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Stat, StatGrid } from '@/components/ui'
import { useAdvances, useGuarantees, type Advance, type Guarantee } from '@/api/registers'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

const STATE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = { 'in force': 'success', 'lapses within 30 days': 'warning', lapsed: 'danger', 'no expiry recorded': 'neutral' }
const order = (id: number, no: string) => <Link className="font-mono text-[13px] text-primary underline-offset-2 hover:underline" to={`/subcontractors/work-orders/${id}`}>{no}</Link>

/** Bank guarantees held against live orders, and when they lapse. */
export function GuaranteesTab() {
  const q = useGuarantees()
  const s = q.data?.summary
  const columns: TableColumn<Guarantee>[] = [
    { id: 'c', header: 'Contractor', cell: (r) => r.contractor },
    { id: 'o', header: 'Order', cell: (r) => order(r.order_id, r.order) },
    { id: 'a', header: 'Amount', align: 'right', cell: (r) => formatINR(r.amount) },
    { id: 'v', header: 'Valid until', hideBelow: 'md', cell: (r) => formatDate(r.valid_until) || '-' },
    { id: 'd', header: 'Days left', hideBelow: 'md', align: 'right', cell: (r) => (r.days_left === null ? '-' : r.days_left) },
    { id: 'w', header: 'Work ends', hideBelow: 'lg', cell: (r) => `${formatDate(r.completion_date) || '-'}${r.defect_liability_months ? ` + ${r.defect_liability_months} mo DLP` : ''}` },
    { id: 's', header: 'State', cell: (r) => <Badge tone={STATE[r.state] ?? 'neutral'}>{r.state}</Badge> },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Guarantees held" value={compactINR(s?.held)} loading={q.isPending} />
        <Stat label="Lapsing within 30 days" value={s?.lapsing_soon ?? 0} tone={s?.lapsing_soon ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Lapsed" value={s?.lapsed ?? 0} tone={s?.lapsed ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="No expiry recorded" value={s?.no_expiry ?? 0} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Bank guarantees" rows={q.data?.guarantees ?? []} columns={columns} rowKey={(r) => r.order_id} loading={q.isPending} empty="No bank guarantees on any live order." />
    </>
  )
}

/** Advances given to gangs, and how much has come back through their bills. */
export function AdvancesTab() {
  const q = useAdvances()
  const s = q.data?.summary
  const columns: TableColumn<Advance>[] = [
    { id: 'c', header: 'Contractor', cell: (r) => r.contractor },
    { id: 'o', header: 'Order', cell: (r) => order(r.order_id, r.order) },
    { id: 'a', header: 'Advance', align: 'right', cell: (r) => formatINR(r.advance) },
    { id: 'p', header: 'Recovery', hideBelow: 'md', align: 'right', cell: (r) => `${r.recovery_percent}%` },
    { id: 'r', header: 'Recovered', align: 'right', cell: (r) => <div className="flex flex-col items-end">{formatINR(r.recovered)}<div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(r.percent_recovered)} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, r.percent_recovered))}%` }} /></div></div> },
    { id: 'out', header: 'Still out', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.outstanding)}</span> },
    { id: 's', header: 'Security', cell: (r) => <Badge tone={r.secured_by_bg ? 'success' : 'warning'}>{r.secured_by_bg ? 'BG held' : 'unsecured'}</Badge> },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Advances given" value={compactINR(s?.given)} loading={q.isPending} />
        <Stat label="Recovered so far" value={compactINR(s?.recovered)} loading={q.isPending} />
        <Stat label="Still out" value={compactINR(s?.outstanding)} loading={q.isPending} />
        <Stat label="Out with no guarantee" value={compactINR(s?.unsecured)} tone={s?.unsecured ? 'warning' : undefined} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Advances" rows={q.data?.advances ?? []} columns={columns} rowKey={(r) => r.order_id} loading={q.isPending} empty="No advances on any live order." />
    </>
  )
}
