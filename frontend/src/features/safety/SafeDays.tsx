import { useMemo } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Stat, StatGrid } from '@/components/ui'
import { formatDate } from '@/lib/format'
import { useManHours, type Incident, type ManHours } from '@/api/safety'

const DAY = 86_400_000
const SERIOUS = ['Lost time injury', 'Fatality']

const asDay = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`)
const localToday = () => {
  const n = new Date()
  return Date.UTC(n.getFullYear(), n.getMonth(), n.getDate())
}
const n = (v: number) => v.toLocaleString('en-IN')
const monthName = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })

interface Run { incident: Incident; before: number | null }

/** Safe man-hours: hours worked since the last lost-time injury, the injury rates per million man-hours, and what ended each safe run. */
export function SafeDays({ job, incidents, loading }: { job: number; incidents: Incident[]; loading: boolean }) {
  const h = useManHours(job)
  const m = h.data
  const { sinceAny, sinceInjury, best, last, runs } = useMemo(() => {
    const today = localToday()
    const dated = incidents.filter((i) => i.happened_on).sort((a, b) => asDay(a.happened_on) - asDay(b.happened_on))
    const serious = dated.filter((i) => SERIOUS.includes(i.kind) || (i.lost_days ?? 0) >= 1)
    const gap = (from: string) => Math.max(0, Math.round((today - asDay(from)) / DAY))
    const runs: Run[] = serious.map((incident, k) => ({ incident, before: k ? Math.round((asDay(incident.happened_on) - asDay(serious[k - 1].happened_on)) / DAY) : null }))
    const lastAny = dated[dated.length - 1]
    const lastSerious = serious[serious.length - 1]
    const sinceInjury = lastSerious ? gap(lastSerious.happened_on) : null
    const gaps = runs.map((r) => r.before).filter((b): b is number => b !== null)
    const best = lastSerious ? Math.max(sinceInjury ?? 0, ...gaps) : null
    return { sinceAny: lastAny ? gap(lastAny.happened_on) : null, sinceInjury, best, last: lastAny, runs: runs.reverse() }
  }, [incidents])

  const shown = (v: number | null) => (v === null ? 'none yet' : v)
  const rate = (v: number | null | undefined) => (v === null || v === undefined ? '-' : v)
  const columns: TableColumn<Run>[] = [
    { id: 'no', header: 'No.', cell: (r) => <span className="font-mono text-[13px]">{r.incident.number}</span> },
    { id: 'on', header: 'Date', cell: (r) => formatDate(r.incident.happened_on) },
    { id: 'kind', header: 'Kind', cell: (r) => <span className="font-semibold text-danger">{r.incident.kind}</span> },
    { id: 'what', header: 'What happened', hideBelow: 'md', cell: (r) => <span className="line-clamp-2 max-w-80">{r.incident.description}</span> },
    { id: 'before', header: 'Safe days before it', align: 'right', cell: (r) => (r.before === null ? '-' : r.before) },
  ]
  const months: TableColumn<ManHours['by_month'][number]>[] = [
    { id: 'm', header: 'Month', cell: (r) => monthName(r.month) },
    { id: 'c', header: 'Contractors', align: 'right', hideBelow: 'md', cell: (r) => n(r.contractor_hours) },
    { id: 's', header: 'Staff', align: 'right', hideBelow: 'md', cell: (r) => n(r.staff_hours) },
    { id: 'h', header: 'Man-hours', align: 'right', cell: (r) => <span className="font-medium">{n(r.hours)}</span> },
    { id: 'i', header: 'Incidents', align: 'right', cell: (r) => r.incidents || '-' },
    { id: 'l', header: 'Lost-time injuries', align: 'right', cell: (r) => (r.ltis ? <span className="font-semibold text-danger">{r.ltis}</span> : '-') },
  ]

  return (
    <div className="grid gap-6">
      <section aria-label="Safe man-hours" className="rounded-xl border border-success/30 bg-success-soft p-5">
        <p className="text-sm text-muted-foreground">Safe man-hours {m?.since ? `since the last lost-time injury on ${formatDate(m.since)}` : 'without a lost-time injury'}</p>
        <p className="tabular mt-1 font-display text-5xl font-semibold tracking-tight">{h.isPending ? '...' : n(m?.safe_hours ?? 0)}</p>
        <p className="mt-2 text-[13px] text-muted-foreground">{m ? `${n(m.total_hours)} man-hours worked in all: ${n(m.contractor_hours)} by contractors' labour (site diaries) and ${n(m.staff_hours)} by staff (attendance), over ${m.days_recorded} recorded days.` : ''}</p>
      </section>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="LTIFR" value={rate(m?.ltifr)} sub="Lost-time injuries per million man-hours" loading={h.isPending} />
        <Stat label="Severity rate" value={rate(m?.severity_rate)} sub={m ? `${m.days_lost} days lost, per million man-hours` : undefined} loading={h.isPending} />
        <Stat label="Recordable injury rate" value={rate(m?.recordable_rate)} sub={m ? `${m.recordable} recordable, per million man-hours` : undefined} loading={h.isPending} />
        <Stat label="Man-hours this month" value={n(m?.this_month_hours ?? 0)} loading={h.isPending} />
      </StatGrid>
      <StatGrid>
        <Stat label="Days without a lost-time injury" value={shown(sinceInjury)} tone={sinceInjury === 0 ? 'danger' : undefined} loading={loading} />
        <Stat label="Days since the last incident" value={shown(sinceAny)} sub={last ? `${last.kind}, ${formatDate(last.happened_on)}` : undefined} tone={sinceAny === 0 ? 'danger' : undefined} loading={loading} />
        <Stat label="Longest safe run" value={m ? `${n(m.best_run_hours)} hrs` : shown(best)} sub={best === null ? 'man-hours in a row' : `${best} days in a row at best`} loading={loading} />
      </StatGrid>
      <section>
        <h2 className="mb-2 text-base font-semibold">Month by month</h2>
        <DataTable label="Man-hours by month" rows={m?.by_month ?? []} columns={months} rowKey={(r) => r.month} loading={h.isPending}
          empty="No hours recorded yet. Man-hours come from the labour on each site diary and the hours staff clock on site." />
        <p className="mt-2 text-xs text-muted-foreground">A day with no site diary counts no contractor hours, so the figure is only as full as the diaries. Rates per 1,000,000 man-hours; a lost-time injury is one recorded as such, a fatality, or any injury that cost a day or more off work.</p>
      </section>
      <section>
        <h2 className="mb-2 text-base font-semibold">What ended each safe run</h2>
        <DataTable label="What ended each safe run" rows={runs} columns={columns} rowKey={(r) => r.incident.id} loading={loading} empty="No lost-time injury has been recorded. Every day so far has been a safe one." />
      </section>
    </div>
  )
}
