import { useState } from 'react'
import { AlertTriangle, CalendarClock, Clock3, History } from 'lucide-react'
import { Card, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useDashboard } from '@/api/plant'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { LoadError, RangeBar, ServiceBadge, StatusBadge } from './plantParts'
import type { ServiceStatus } from '@/api/equipment'

const SERVICE_STATUSES = ['Overdue', 'Service due', 'Due soon', 'Upcoming']

const COST_LABEL: Record<string, string> = { fuel: 'Fuel and diesel', maintenance: 'Maintenance and repairs', rental: 'Rental charges', rental_outstanding: 'Rental dues outstanding', labour_estimate: 'Operator labour (from hours)', total: 'Total operating cost' }

const Panel = ({ title, icon: Icon, children }: { title: string; icon: typeof Clock3; children: React.ReactNode }) => (
  <Card className="p-4">
    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Icon className="size-4 text-primary" aria-hidden />{title}</h3>
    {children}
  </Card>
)
const Empty = ({ text }: { text: string }) => <p className="text-[13px] text-muted-foreground">{text}</p>

/** Where the machines stand and what they cost, for the period chosen - every figure counted from the records. */
export function PlantDashboard({ onGo }: { onGo: (tab: string) => void }) {
  const [range, setRange] = useState({ from: '', to: '' })
  const q = useDashboard({ date_from: range.from, date_to: range.to })
  const d = q.data
  const c = d?.cards
  const busy = q.isPending
  if (q.isError) return <LoadError message={q.error.message} retry={() => q.refetch()} />
  const total = d ? d.status_distribution.reduce((n, s) => n + s.count, 0) : 0
  return (
    <div>
      <RangeBar from={range.from} to={range.to} onChange={(from, to) => setRange({ from, to })}>
        {d && <span className="text-xs text-muted-foreground">Showing {formatDate(d.date_from)} to {formatDate(d.date_to)}</span>}
      </RangeBar>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-5">
        <Stat label="Total equipment" value={c?.total ?? 0} sub={c ? `${c.owned} owned - ${c.rented} rented - ${c.leased} leased` : undefined} loading={busy} onClick={() => onGo('register')} />
        <Stat label="Owned" value={c?.owned ?? 0} loading={busy} />
        <Stat label="Rented" value={c?.rented ?? 0} loading={busy} onClick={() => onGo('rentals')} />
        <Stat label="Working now" value={c?.working ?? 0} tone="success" loading={busy} />
        <Stat label="Idle" value={c?.idle ?? 0} loading={busy} />
        <Stat label="Under maintenance" value={c?.maintenance ?? 0} tone={c?.maintenance ? 'warning' : undefined} loading={busy} onClick={() => onGo('maintenance')} />
        <Stat label="Breakdowns" value={c?.breakdown ?? 0} tone={c?.breakdown ? 'danger' : undefined} loading={busy} onClick={() => onGo('maintenance')} />
        <Stat label="Active operators" value={c?.operators ?? 0} loading={busy} onClick={() => onGo('allocation')} />
        <Stat label="Working hours" value={`${c?.working_hours ?? 0} h`} loading={busy} onClick={() => onGo('logbook')} />
        <Stat label="Fuel expenditure" value={formatINR(c?.fuel ?? 0)} loading={busy} onClick={() => onGo('fuel')} />
        <Stat label="Maintenance expenditure" value={formatINR(c?.maintenance_cost ?? 0)} loading={busy} />
        <Stat label="Operating cost" value={formatINR(c?.operating_cost ?? 0)} loading={busy} onClick={() => onGo('expenses')} />
        <Stat label="Due soon" value={c?.upcoming ?? 0} sub="maintenance and rental returns" tone={c?.upcoming ? 'warning' : undefined} loading={busy} />
        <Stat label="Services overdue or due" value={(c?.service?.Overdue ?? 0) + (c?.service?.['Service due'] ?? 0)} sub={c?.service ? `${c.service.Overdue} overdue - ${c.service['Service due']} due - ${c.service['Due soon']} due soon` : undefined} tone={c?.service?.Overdue ? 'danger' : c?.service?.['Service due'] ? 'warning' : undefined} loading={busy} onClick={() => onGo('register')} />
      </StatGrid>
      {busy ? <Skeleton className="h-64 w-full" /> : d && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Equipment status" icon={Clock3}>
            {total === 0 ? <Empty text="No machines on the register yet." /> : (
              <ul className="grid gap-2">
                {d.status_distribution.map((s) => (
                  <li key={s.status} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-3 text-[13px]">
                    <StatusBadge status={s.status} />
                    <span className="h-2.5 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-primary" style={{ width: `${(s.count / total) * 100}%` }} /></span>
                    <span className="text-right tabular">{s.count}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel title="Cost summary" icon={History}>
            <dl className="grid gap-1.5 text-[13px]">
              {Object.entries(d.cost_summary).map(([k, v]) => (
                <div key={k} className={`flex justify-between gap-3 ${k === 'total' ? 'border-t border-border pt-1.5 font-semibold' : ''}`}><dt className={k === 'labour_estimate' || k === 'rental_outstanding' ? 'text-muted-foreground' : ''}>{COST_LABEL[k] ?? k}</dt><dd className="tabular">{formatINR(v)}</dd></div>
              ))}
            </dl>
            <p className="mt-2 text-[11px] text-muted-foreground">Labour from hours is shown for reference; wages enter the total only when they are entered as an expense, so they are never counted twice.</p>
          </Panel>
          <Panel title="Maintenance reminders" icon={AlertTriangle}>
            {d.maintenance_reminders.length === 0 ? <Empty text="Nothing due." /> : (
              <ul className="grid gap-1.5 text-[13px]">{d.maintenance_reminders.map((r, i) => <li key={i} className={`flex flex-wrap items-center gap-x-2 gap-y-0.5 ${r.due ? 'text-danger' : ''}`}>{SERVICE_STATUSES.includes(r.status ?? '') && <ServiceBadge status={r.status as ServiceStatus} />}<span><strong>{r.code} {r.name}</strong> - {r.what}{r.on && ` (${formatDate(r.on)})`}</span></li>)}</ul>
            )}
          </Panel>
          <Panel title="Rental returns" icon={CalendarClock}>
            {d.rental_returns.length === 0 ? <Empty text="No hire due back in the next week." /> : (
              <ul className="grid gap-1.5 text-[13px]">{d.rental_returns.map((r) => <li key={r.rental_id} className={r.overdue ? 'text-danger' : ''}><strong>{r.code} {r.name}</strong> - {r.agreement_no}, {r.overdue ? 'overdue since' : 'due back'} {formatDate(r.expected_return)}</li>)}</ul>
            )}
          </Panel>
          <Panel title="Too much idle time" icon={Clock3}>
            {d.excess_idle.length === 0 ? <Empty text="No machine stood idle for more than 40% of its hours on duty." /> : (
              <ul className="grid gap-1.5 text-[13px]">{d.excess_idle.map((m) => <li key={m.asset_id}><strong>{m.code} {m.name}</strong> - idle {m.idle_hours} h against {m.operating_hours} h running ({Math.round(m.idle_share * 100)}%)</li>)}</ul>
            )}
          </Panel>
          <Panel title="Recent activity" icon={History}>
            {d.recent.length === 0 ? <Empty text="Nothing recorded yet." /> : (
              <ul className="grid gap-1.5 text-[13px]">{d.recent.map((r, i) => <li key={i}><span className="text-muted-foreground">{r.at.slice(5, 16)}</span> <strong>{r.what}</strong> {r.details}<span className="text-muted-foreground"> - {r.who}</span></li>)}</ul>
            )}
          </Panel>
        </div>
      )}
    </div>
  )
}
