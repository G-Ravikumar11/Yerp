import { Skeleton, Stat, StatGrid, Badge, Button } from '@/components/ui'
import { attKeys, clockFor, useAttStats, useBySite, useLive, type LivePerson } from '@/api/attendance'
import { useAction } from '@/lib/mutate'
import { plural } from '@/lib/format'

const state = (p: LivePerson) => (p.clock_in && !p.clock_out ? 'working' : p.clock_out ? 'done' : 'absent')

/** Who is in today: the figures, where they are, and a board of everybody. */
export function TodayTab() {
  const stats = useAttStats()
  const live = useLive()
  const site = useBySite()
  const clock = useAction((v: { id: number; which: 'in' | 'out' }) => clockFor(v.id, v.which), { invalidate: [attKeys.all], success: (r) => r.message })
  const rows = live.data ?? []
  const working = rows.filter((p) => state(p) === 'working').length
  const s = stats.data
  const s2 = site.data

  return (
    <>
      <StatGrid>
        <Stat label="Employees" value={s?.total_employees ?? 0} loading={stats.isPending} />
        <Stat label="Present today" value={s?.present ?? 0} tone="success" loading={stats.isPending} />
        <Stat label="Absent today" value={s?.absent ?? 0} tone={s?.absent ? 'danger' : undefined} loading={stats.isPending} />
        <Stat label="Average hours" value={`${s?.avg_hours ?? 0}h`} loading={stats.isPending} />
        <Stat label="Working now" value={working} loading={live.isPending} />
      </StatGrid>

      <section aria-label="Today by site" className="mb-6 rounded-xl border border-border bg-card p-4 shadow-card">
        <h2 className="text-sm font-semibold">Today by site</h2>
        <p className="mb-2 text-xs text-muted-foreground">Clock-ins inside each project's site location.</p>
        {site.isPending ? <Skeleton className="h-10 w-full" /> : !s2?.fenced_sites ? (
          <p className="text-[13px] text-muted-foreground">No project has a site location yet. Add one on the project and clock-ins there are counted on it.</p>
        ) : (
          <div className="grid gap-2">
            {s2.sites.map((x) => (
              <div key={x.project} className="border-b border-border pb-2 last:border-0">
                <p className="text-sm"><strong>{x.project}</strong> <span className="text-xs text-muted-foreground">{plural(x.people.length, 'person', 'people')} on site</span></p>
                <div className="mt-1 flex flex-wrap gap-1.5">{x.people.length ? x.people.map((p, i) => <Badge key={i}>{p.employee} - {p.clock_in.slice(0, 5)}</Badge>) : <span className="text-xs text-muted-foreground">nobody clocked in here</span>}</div>
              </div>
            ))}
            {s2.elsewhere.length > 0 && <div><p className="text-sm font-semibold text-warning">Not at any site</p><div className="mt-1 flex flex-wrap gap-1.5">{s2.elsewhere.map((p, i) => <Badge key={i} tone="warning">{p.employee} - {p.clock_in.slice(0, 5)}</Badge>)}</div></div>}
          </div>
        )}
      </section>

      <h2 className="mb-3 text-sm font-semibold">Everybody</h2>
      {live.isPending ? <Skeleton className="h-32 w-full" /> : rows.length === 0 ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No employees yet. Add some under People, Employees.</p> : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((p) => {
            const st = state(p)
            return (
              <section key={p.id} aria-label={p.full_name} className={`rounded-xl border bg-card p-4 shadow-card ${st === 'working' ? 'border-success/60' : st === 'done' ? 'border-info/50' : 'border-border'}`}>
                <div className="flex items-start gap-3">
                  <span className={`grid size-10 shrink-0 place-items-center rounded-full text-sm font-semibold ${st === 'working' ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground'}`}>{p.full_name.charAt(0)}</span>
                  <div className="min-w-0 flex-1"><p className="truncate font-medium">{p.full_name}</p><p className="truncate text-xs text-muted-foreground">{p.job_title || p.department || 'Employee'}</p></div>
                  <Badge tone={st === 'working' ? 'success' : st === 'done' ? 'info' : 'neutral'} dot>{st === 'working' ? 'Working' : st === 'done' ? 'Done' : 'Not in'}</Badge>
                </div>
                <p className="tabular mt-3 flex justify-between text-[13px] text-muted-foreground"><span>In {p.clock_in ? p.clock_in.slice(0, 5) : '--:--'}</span><span>Out {p.clock_out ? p.clock_out.slice(0, 5) : '--:--'}</span><span>{p.total_hours || 0}h</span></p>
                {p.check_type && <p className="mt-1 text-xs capitalize text-muted-foreground">{p.check_type}{p.location_label && ` - ${p.location_label.slice(0, 40)}`}</p>}
                {st !== 'done' && <Button size="sm" variant="outline" className="mt-3" loading={clock.isPending && clock.variables?.id === p.id} onClick={() => clock.mutate({ id: p.id, which: st === 'working' ? 'out' : 'in' })}>{st === 'working' ? 'Clock out' : 'Clock in'}</Button>}
              </section>
            )
          })}
        </div>
      )}
    </>
  )
}
