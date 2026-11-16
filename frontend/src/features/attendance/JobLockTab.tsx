import { Link } from 'react-router-dom'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { UserCheck } from 'lucide-react'
import { Badge, Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { attKeys, setJobLockExempt, useJobLock, useJobLockWeek, type JobLock, type JobLockWeek } from '@/api/attendance'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'

const mapUrl = (lat: number, lng: number) => `https://www.google.com/maps?q=${lat},${lng}`
const away = (m: number | null) => (m == null ? '' : m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`)

/** Who may clock in where, the sites that cannot be checked yet, who was turned away, and punches worth a second look. */
export function JobLockTab() {
  const q = useJobLock()
  const week = useJobLockWeek()
  const { can } = useSession()
  const exempt = useAction((a: { id: number; exempt: boolean }) => setJobLockExempt(a.id, a.exempt), { invalidate: [attKeys.all], success: (r) => r.message })
  const d = q.data
  if (q.isPending || !d) return <Skeleton className="h-64 w-full" />
  const manage = can('people.manage')
  // One click lets the person clock in anywhere (Field staff, below); the same switch, put where the refusal is read.
  const allow = (id: number, name: string) => manage ? <Button size="sm" variant="outline" loading={exempt.isPending && exempt.variables?.id === id} onClick={() => exempt.mutate({ id, exempt: true })} aria-label={`Allow ${name}`}><UserCheck /> Allow person</Button> : null
  const refused: TableColumn<JobLock['refused'][number]>[] = [
    { id: 'at', header: 'When', cell: (r) => <span className="whitespace-nowrap">{formatDate(r.at)} {r.at.slice(11, 16)}</span> },
    { id: 'who', header: 'Who', cell: (r) => <span className="font-medium">{r.employee}</span> },
    { id: 'why', header: 'Why it was refused', cell: (r) => r.reason },
    { id: 'away', header: 'Away', align: 'right', hideBelow: 'md', cell: (r) => away(r.distance_m) },
    { id: 'map', header: '', cell: (r) => (r.lat ? <a href={mapUrl(r.lat, r.lng)} target="_blank" rel="noreferrer" className="text-[13px] text-primary underline underline-offset-4">Map</a> : '') },
    { id: 'allow', header: '', align: 'right', cell: (r) => (r.exempt ? <Badge tone="warning">Allowed anywhere</Badge> : allow(r.employee_id, r.employee)) },
  ]
  const weekly: TableColumn<JobLockWeek['by_person'][number]>[] = [
    { id: 'who', header: 'Who', cell: (r) => <div><div className="font-medium">{r.name || 'Unknown'}</div><div className="text-xs text-muted-foreground">{r.job_title}</div></div> },
    { id: 'n', header: 'Refused', align: 'right', cell: (r) => <span className="tabular-nums">{r.refused} {r.repeat && <Badge tone="warning">Again and again</Badge>}</span> },
    { id: 'd', header: 'On days', align: 'right', hideBelow: 'md', cell: (r) => r.days },
    { id: 'why', header: 'Usually because', hideBelow: 'md', cell: (r) => <span className="text-[13px]">{r.reason}</span> },
    { id: 'last', header: 'Last', hideBelow: 'lg', cell: (r) => <span className="whitespace-nowrap">{formatDate(r.last_at)} {r.last_at.slice(11, 16)}</span> },
    { id: 'allow', header: '', align: 'right', cell: (r) => (r.exempt ? <Badge tone="warning">Allowed anywhere</Badge> : allow(r.employee_id, r.name)) },
  ]
  const flagged: TableColumn<JobLock['flagged'][number]>[] = [
    { id: 'on', header: 'Day', cell: (r) => <span className="whitespace-nowrap">{formatDate(r.date)} {r.clock_in.slice(0, 5)}</span> },
    { id: 'who', header: 'Who', cell: (r) => <span className="font-medium">{r.employee}</span> },
    { id: 'flag', header: 'Worth a look', cell: (r) => r.flag },
    { id: 'map', header: '', cell: (r) => (r.lat ? <a href={mapUrl(r.lat, r.lng)} target="_blank" rel="noreferrer" className="text-[13px] text-primary underline underline-offset-4">Map</a> : '') },
  ]
  const staff: TableColumn<JobLock['staff'][number]>[] = [
    { id: 'who', header: 'Who', cell: (r) => <div><div className="font-medium">{r.name}</div><div className="text-xs text-muted-foreground">{r.job_title}</div></div> },
    { id: 'sites', header: 'May clock in at', cell: (r) => (r.exempt ? <Badge tone="warning">Anywhere</Badge> : `${d.office_set ? 'Office, ' : ''}${r.sites.length ? r.sites.join(', ') : 'any site'}`) },
    {
      id: 'x', header: 'Field staff', cell: (r) => (
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={r.exempt} disabled={!manage || exempt.isPending} aria-label={`${r.name} may clock in anywhere`} onChange={(e) => exempt.mutate({ id: r.id, exempt: e.target.checked })} /> Anywhere
        </label>
      ),
    },
  ]
  return (
    <div className="grid gap-6">
      {!d.on && <p role="alert" className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-sm">Site Lock is off, so staff can clock in from anywhere. Switch it on in Settings.</p>}
      <StatGrid className="xl:grid-cols-3">
        <Stat label="Site Lock" value={d.on ? 'On' : 'Off'} tone={d.on ? 'success' : 'warning'} />
        <Stat label="Sites with no location" value={d.sites_without_location.length} tone={d.sites_without_location.length ? 'warning' : undefined} sub="Staff on these cannot be checked yet" />
        <Stat label="Refused clock-ins" value={d.refused.length} sub="The latest 100" />
      </StatGrid>
      {d.sites_without_location.length > 0 && (
        <section className="rounded-xl border border-warning/40 bg-card p-4">
          <h2 className="text-sm font-semibold">Set these sites&rsquo; locations first</h2>
          <p className="mb-2 text-[13px] text-muted-foreground">Someone assigned to one of these can still clock in from anywhere; the punch is flagged below. Open the project, press Edit and set its site location.</p>
          <ul className="flex flex-wrap gap-2 text-sm">
            {d.sites_without_location.map((s) => <li key={s.id}><Link to={`/projects/${s.id}`} className="text-primary underline underline-offset-4">{s.name}</Link></li>)}
          </ul>
        </section>
      )}
      {week.data && (
        <section aria-label="Weekly summary">
          <h2 className="mb-1 text-base font-semibold">This week</h2>
          <p className="mb-2 text-[13px] text-muted-foreground">{formatDate(week.data.from)} to {formatDate(week.data.to)}, against the week before. HR is sent this every Monday morning.</p>
          <StatGrid className="xl:grid-cols-4">
            <Stat label="Refused this week" value={week.data.refused} sub={week.data.change === 0 ? 'Same as the week before' : `${week.data.change > 0 ? 'Up' : 'Down'} ${Math.abs(week.data.change)} on the week before`} tone={week.data.change > 0 ? 'warning' : undefined} />
            <Stat label="People refused" value={week.data.people} />
            <Stat label="Again and again" value={week.data.repeat_people} sub="Refused three times or more" tone={week.data.repeat_people ? 'warning' : undefined} />
            <Stat label="Let through, worth a look" value={week.data.flagged_punches} />
          </StatGrid>
          <div className="my-3 flex flex-wrap gap-2 text-[12px] text-muted-foreground" aria-label="Refusals by day">
            {week.data.by_day.map((x) => <span key={x.date} className="rounded-md border border-border px-2 py-1">{formatDate(x.date).slice(0, 6)}: <strong className="text-foreground">{x.count}</strong></span>)}
          </div>
          <DataTable label="Refused this week, by person" rows={week.data.by_person} columns={weekly} rowKey={(r) => r.employee_id} empty="Nobody was turned away this week." />
        </section>
      )}
      <section>
        <h2 className="mb-2 text-base font-semibold">Refused clock-ins</h2>
        <DataTable label="Refused clock-ins" rows={d.refused} columns={refused} rowKey={(r) => r.id} empty="Nobody has been turned away." />
      </section>
      <section>
        <h2 className="mb-2 text-base font-semibold">Let through, worth a look</h2>
        <DataTable label="Flagged punches" rows={d.flagged} columns={flagged} rowKey={(r) => r.id} empty="Nothing flagged." />
      </section>
      <section>
        <h2 className="mb-2 text-base font-semibold">Who may clock in where</h2>
        <p className="mb-2 text-[13px] text-muted-foreground">Sites come from each person&rsquo;s assignment (Employees, Access). Tick Anywhere only for field staff with no fixed site.</p>
        <DataTable label="Staff under Site Lock" rows={d.staff} columns={staff} rowKey={(r) => r.id} empty="No staff yet." />
      </section>
    </div>
  )
}
