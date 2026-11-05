import { Link } from 'react-router-dom'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Skeleton, Stat, StatGrid } from '@/components/ui'
import { attKeys, setJobLockExempt, useJobLock, type JobLock } from '@/api/attendance'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'

const mapUrl = (lat: number, lng: number) => `https://www.google.com/maps?q=${lat},${lng}`
const away = (m: number | null) => (m == null ? '' : m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`)

/** Who may clock in where, the sites that cannot be checked yet, who was turned away, and punches worth a second look. */
export function JobLockTab() {
  const q = useJobLock()
  const { can } = useSession()
  const exempt = useAction((a: { id: number; exempt: boolean }) => setJobLockExempt(a.id, a.exempt), { invalidate: [attKeys.all], success: (r) => r.message })
  const d = q.data
  if (q.isPending || !d) return <Skeleton className="h-64 w-full" />
  const manage = can('people.manage')
  const refused: TableColumn<JobLock['refused'][number]>[] = [
    { id: 'at', header: 'When', cell: (r) => <span className="whitespace-nowrap">{formatDate(r.at)} {r.at.slice(11, 16)}</span> },
    { id: 'who', header: 'Who', cell: (r) => <span className="font-medium">{r.employee}</span> },
    { id: 'why', header: 'Why it was refused', cell: (r) => r.reason },
    { id: 'away', header: 'Away', align: 'right', hideBelow: 'md', cell: (r) => away(r.distance_m) },
    { id: 'map', header: '', cell: (r) => (r.lat ? <a href={mapUrl(r.lat, r.lng)} target="_blank" rel="noreferrer" className="text-[13px] text-primary underline underline-offset-4">Map</a> : '') },
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
      {!d.on && <p role="alert" className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-sm">Job Lock is off, so staff can clock in from anywhere. Switch it on in Settings.</p>}
      <StatGrid className="xl:grid-cols-3">
        <Stat label="Job Lock" value={d.on ? 'On' : 'Off'} tone={d.on ? 'success' : 'warning'} />
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
        <DataTable label="Staff under Job Lock" rows={d.staff} columns={staff} rowKey={(r) => r.id} empty="No staff yet." />
      </section>
    </div>
  )
}
