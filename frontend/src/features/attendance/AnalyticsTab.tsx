import { Skeleton, Stat, StatGrid } from '@/components/ui'
import { useAnalytics } from '@/api/attendance'

/** Thirty days of the clock: how many come in, how often late, how much overtime. */
export function AnalyticsTab() {
  const q = useAnalytics(30)
  const d = q.data
  const days = Object.entries(d?.daily ?? {}).slice(-14)
  const max = Math.max(...days.map(([, v]) => v.present), 1)
  return (
    <>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Average day" value={`${d?.avg_daily_hours ?? 0}h`} loading={q.isPending} />
        <Stat label="Late arrivals" value={d?.late_arrivals ?? 0} tone={d?.late_arrivals ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Overtime sessions" value={d?.overtime_sessions ?? 0} loading={q.isPending} />
        <Stat label="Attendance rate" value={`${d?.avg_attendance_rate ?? 0}%`} loading={q.isPending} />
      </StatGrid>
      <section aria-label="Present each day" className="rounded-xl border border-border bg-card p-4 shadow-card">
        <h2 className="mb-3 text-sm font-semibold">Present each day (last 14 days with records)</h2>
        {q.isPending ? <Skeleton className="h-44 w-full" /> : days.length === 0 ? <p className="text-sm text-muted-foreground">No days recorded yet.</p> : (
          <div className="flex h-48 items-end gap-1.5" role="img" aria-label="Bar chart of people present each day">
            {days.map(([day, v]) => (
              <div key={day} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
                <span className="tabular text-[11px] font-semibold">{v.present}</span>
                <div className="w-full rounded-t bg-primary" style={{ height: `${Math.max((v.present / max) * 100, 3)}%` }} />
                <span className="text-[10px] text-muted-foreground">{day.slice(5)}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
