import { useMemo } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Stat, StatGrid } from '@/components/ui'
import { formatDate } from '@/lib/format'
import type { Incident } from '@/api/safety'

const DAY = 86_400_000
const SERIOUS = ['Lost time injury', 'Fatality']

const asDay = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`)
const localToday = () => {
  const n = new Date()
  return Date.UTC(n.getFullYear(), n.getMonth(), n.getDate())
}

interface Run { incident: Incident; before: number | null }

/** How long the site has gone without an injury or an incident, and what ended each run. */
export function SafeDays({ incidents, loading }: { incidents: Incident[]; loading: boolean }) {
  const { sinceAny, sinceInjury, best, last, runs } = useMemo(() => {
    const today = localToday()
    const dated = incidents.filter((i) => i.happened_on).sort((a, b) => asDay(a.happened_on) - asDay(b.happened_on))
    const serious = dated.filter((i) => SERIOUS.includes(i.kind))
    const gap = (from: string) => Math.max(0, Math.round((today - asDay(from)) / DAY))
    const runs: Run[] = serious.map((incident, n) => ({ incident, before: n ? Math.round((asDay(incident.happened_on) - asDay(serious[n - 1].happened_on)) / DAY) : null }))
    const lastAny = dated[dated.length - 1]
    const lastSerious = serious[serious.length - 1]
    const sinceInjury = lastSerious ? gap(lastSerious.happened_on) : null
    const gaps = runs.map((r) => r.before).filter((b): b is number => b !== null)
    const best = lastSerious ? Math.max(sinceInjury ?? 0, ...gaps) : null
    return { sinceAny: lastAny ? gap(lastAny.happened_on) : null, sinceInjury, best, last: lastAny, runs: runs.reverse() }
  }, [incidents])

  const shown = (n: number | null) => (n === null ? 'none yet' : n)
  const columns: TableColumn<Run>[] = [
    { id: 'no', header: 'No.', cell: (r) => <span className="font-mono text-[13px]">{r.incident.number}</span> },
    { id: 'on', header: 'Date', cell: (r) => formatDate(r.incident.happened_on) },
    { id: 'kind', header: 'Kind', cell: (r) => <span className="font-semibold text-danger">{r.incident.kind}</span> },
    { id: 'what', header: 'What happened', hideBelow: 'md', cell: (r) => <span className="line-clamp-2 max-w-80">{r.incident.description}</span> },
    { id: 'before', header: 'Safe days before it', align: 'right', cell: (r) => (r.before === null ? '-' : r.before) },
  ]

  return (
    <>
      <div className="mb-4">
        <StatGrid>
          <Stat label="Days without a lost-time injury" value={shown(sinceInjury)} tone={sinceInjury === 0 ? 'danger' : undefined} loading={loading} />
          <Stat label="Days since the last incident" value={shown(sinceAny)} sub={last ? `${last.kind}, ${formatDate(last.happened_on)}` : undefined} tone={sinceAny === 0 ? 'danger' : undefined} loading={loading} />
          <Stat label="Longest safe run" value={shown(best)} sub={best === null ? undefined : 'days in a row'} loading={loading} />
        </StatGrid>
      </div>
      <DataTable label="What ended each safe run" rows={runs} columns={columns} rowKey={(r) => r.incident.id} loading={loading} empty="No lost-time injury has been recorded. Every day so far has been a safe one." />
    </>
  )
}
