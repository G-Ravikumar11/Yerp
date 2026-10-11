import { Skeleton } from '@/components/ui'
import { useTeam, useWeek, type Attendance } from '@/api/staff'
import { formatDate } from '@/lib/format'
import { Link } from 'react-router-dom'

/** This week's hours, day by day. */
export function WeekCard() {
  const q = useWeek()
  const days = q.data ?? []
  const max = Math.max(8, ...days.map((d) => d.hours || 0))
  return (
    <section aria-label="This week" className="rounded-xl border border-border bg-card p-5 shadow-card">
      <h2 className="mb-3 text-sm font-semibold">This week</h2>
      {q.isPending ? <Skeleton className="h-40 w-full" /> : (
        <div className="flex h-40 items-end gap-2" role="img" aria-label="Hours worked each day this week">
          {days.map((d) => (
            <div key={d.date} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
              <span className="tabular text-[11px] text-muted-foreground">{d.hours > 0 ? d.hours.toFixed(1) : ''}</span>
              <div className={`w-full rounded-t-md ${d.is_today ? 'bg-primary' : 'bg-muted-foreground/25'}`} style={{ height: `${Math.max(((d.hours || 0) / max) * 100, 2)}%` }} />
              <span className={`text-[11px] ${d.is_today ? 'font-semibold text-primary' : 'text-muted-foreground'}`}>{d.day}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/** The last few days of the person's own clock. */
export function RecentCard({ rows }: { rows: Attendance[] }) {
  return (
    <section aria-label="Recent attendance" className="rounded-xl border border-border bg-card p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Recent attendance</h2><Link to="/me/timesheet" className="text-xs text-primary hover:underline">All of it</Link></div>
      {rows.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">No recent activity</p> : (
        <ul className="grid gap-1.5">
          {rows.slice(0, 5).map((r) => (
            <li key={r.date} className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-accent"><span>{formatDate(r.date)}</span><span className="tabular text-muted-foreground">{r.clock_in?.slice(0, 5) || '-'} to {r.clock_out?.slice(0, 5) || '-'}</span><span className="tabular font-medium">{r.total_hours > 0 ? `${r.total_hours.toFixed(1)}h` : '-'}</span></li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** The department, at a glance. */
export function PresenceCard() {
  const q = useTeam()
  const team = q.data ?? []
  return (
    <section aria-label="Team presence" className="rounded-xl border border-border bg-card p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Team presence</h2><Link to="/me/team" className="text-xs text-primary hover:underline">My team</Link></div>
      {team.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">No team members found</p> : (
        <ul className="grid gap-1.5">
          {team.slice(0, 5).map((t) => (
            <li key={t.id} className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-accent"><span className="flex items-center gap-2"><span className={`size-2.5 rounded-full ${t.is_online ? (t.is_on_break ? 'bg-warning' : 'bg-success') : 'bg-subtle'}`} aria-hidden />{t.name}</span><span className="text-xs text-muted-foreground">{t.is_online ? (t.is_on_break ? 'On a break' : 'Working') : 'Away'}</span></li>
          ))}
        </ul>
      )}
    </section>
  )
}
