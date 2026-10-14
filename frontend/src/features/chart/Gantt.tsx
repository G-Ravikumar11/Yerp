import { useMemo, useState } from 'react'
import type { Activity } from '@/api/schedule'
import { today } from '@/lib/format'
import { cn } from '@/lib/utils'

const DAY = 86400000
const ROW = 42
const HEAD = 52
const LEFT = 250
const ZOOM = { Days: 26, Weeks: 10, Months: 3.6 } as const
const C = { done: 'var(--color-success)', late: 'var(--color-danger)', behind: 'var(--color-warning)', going: 'var(--color-info)', idle: 'var(--color-subtle)' }
/**
 * The colour of a bar says where the work stands, and moves as it is reported: grey until it starts, blue while it keeps
 * up with the plan, amber once it is more than 10 points behind where the plan has it, red when it is past its deadline
 * or running late, green when it is complete.
 */
const colourOf = (a: Activity) => {
  if (a.status === 'Completed' || a.actual_percent >= 100) return C.done
  if (a.overdue || a.status === 'Delayed' || a.state === 'late') return C.late
  if (a.planned_percent - a.actual_percent > 10 && (a.actual_percent > 0 || a.planned_percent > 10)) return C.behind
  if (a.actual_percent > 0 || a.status === 'In Progress') return C.going
  return C.idle
}
const at = (iso: string) => Math.round(new Date(iso + 'T00:00:00').getTime() / DAY)
const fmt = (n: number, o: Intl.DateTimeFormatOptions) => new Date(n * DAY).toLocaleDateString('en-GB', { timeZone: 'UTC', ...o })

/**
 * The programme drawn on a timeline: one bar per activity from its start to its deadline, filled as far as it is done,
 * a hatched tail where it is forecast to run late, a diamond for each milestone, an arrow from what must finish to
 * what waits on it, and a red line for today.
 */
export function Gantt({ rows, onOpen }: { rows: Activity[]; onOpen: (a: Activity) => void }) {
  const [zoom, setZoom] = useState<keyof typeof ZOOM>('Weeks')
  const px = ZOOM[zoom]
  const t = at(today())
  const span = useMemo(() => {
    const ds = rows.flatMap((a) => [a.planned_start, a.planned_finish, a.forecast_finish]).filter(Boolean).map(at)
    if (!ds.length) return null
    return { from: Math.min(...ds) - 3, to: Math.max(...ds, t) + 10 }
  }, [rows, t])
  if (!span) return null
  const days = span.to - span.from + 1
  const x = (n: number) => (n - span.from) * px
  const index = new Map(rows.map((a, i) => [a.id, i]))
  const width = days * px
  // Header: a label for each month, and a tick for each week (or each day when zoomed right in).
  const months: { at: number; label: string }[] = []
  for (let n = span.from; n <= span.to; n++) if (new Date(n * DAY).getUTCDate() === 1 || n === span.from) months.push({ at: n, label: fmt(n, { month: 'short', year: '2-digit' }) })
  const ticks: number[] = []
  const step = zoom === 'Days' ? 1 : zoom === 'Weeks' ? 7 : 28
  for (let n = span.from; n <= span.to; n += step) ticks.push(n)
  return (
    <section aria-label="Gantt chart" className="overflow-hidden rounded-xl border border-border bg-card shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold">Gantt chart</h2>
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <Key color={C.idle} label="not started" /><Key color={C.going} label="on plan" /><Key color={C.behind} label="behind plan" /><Key color={C.late} label="late / delayed" /><Key color={C.done} label="complete" />
          <div role="group" aria-label="Zoom" className="ml-2 flex overflow-hidden rounded-md border border-border">
            {(Object.keys(ZOOM) as (keyof typeof ZOOM)[]).map((z) => <button key={z} type="button" aria-pressed={z === zoom} onClick={() => setZoom(z)} className={cn('px-2.5 py-1 text-xs', z === zoom ? 'bg-primary text-primary-foreground' : 'hover:bg-accent')}>{z}</button>)}
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <div className="flex" style={{ width: LEFT + width }}>
          <div className="sticky left-0 z-20 shrink-0 border-r border-border bg-card" style={{ width: LEFT }}>
            <div className="flex items-end border-b border-border px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground" style={{ height: HEAD }}>Activity</div>
            {rows.map((a) => (
              <button key={a.id} type="button" onClick={() => onOpen(a)} title={`${a.name}\n${a.planned_start} to ${a.planned_finish}`} className="block w-full truncate border-b border-border px-3 text-left hover:bg-accent" style={{ height: ROW }}>
                <span className="block truncate text-[13px] font-medium"><span className="mr-1.5 font-mono text-[11px] text-muted-foreground">{a.code}</span>{a.name}</span>
                <span className={cn('block truncate text-[11px]', a.overdue ? 'text-danger' : 'text-muted-foreground')}>{a.overdue ? `${a.status} - ${a.days_late} day${a.days_late === 1 ? '' : 's'} overdue` : a.status}{a.assigned_to && ` - ${a.assigned_to}`}</span>
              </button>
            ))}
          </div>
          <div className="relative" style={{ width }}>
            <div className="relative border-b border-border" style={{ height: HEAD }}>
              {months.map((m) => <span key={m.at} className="absolute top-1.5 border-l border-border pl-1.5 text-[11px] font-semibold" style={{ left: x(m.at) }}>{m.label}</span>)}
              {ticks.map((n) => <span key={n} className="absolute bottom-1 -translate-x-1/2 text-[10px] text-muted-foreground" style={{ left: x(n) + (zoom === 'Days' ? px / 2 : 0) }}>{zoom === 'Months' ? '' : fmt(n, { day: 'numeric' })}</span>)}
            </div>
            <div className="relative" style={{ height: rows.length * ROW }}>
              {ticks.map((n) => <div key={n} className="absolute inset-y-0 w-px bg-border/50" style={{ left: x(n) }} aria-hidden />)}
              {rows.map((a, i) => <div key={a.id} className="absolute inset-x-0 border-b border-border/70" style={{ top: i * ROW, height: ROW }} aria-hidden />)}
              <div className="absolute inset-y-0 z-10 w-0.5 bg-danger" style={{ left: x(t) + px / 2 }} aria-hidden title="Today" />
              <svg className="pointer-events-none absolute inset-0 z-[5]" width={width} height={rows.length * ROW} aria-hidden>
                <defs><marker id="gantt-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" className="text-muted-foreground" /></marker></defs>
                {rows.map((a, i) => {
                  const p = a.depends_on_id != null ? index.get(a.depends_on_id) : undefined
                  if (p === undefined || !a.planned_start) return null
                  const pre = rows[p]
                  const x1 = x(at(pre.planned_finish) + 1), y1 = p * ROW + ROW / 2
                  const x2 = x(at(a.planned_start)), y2 = i * ROW + ROW / 2
                  const mid = Math.max(x1 + 6, Math.min(x2 - 6, x1 + 10))
                  const late = !!pre.overdue
                  return <path key={a.id} d={`M${x1},${y1} H${mid} V${y2} H${x2 - 1}`} fill="none" strokeWidth="1.4" className={late ? 'stroke-danger text-danger' : 'stroke-muted-foreground text-muted-foreground'} markerEnd="url(#gantt-arrow)"><title>{`${a.code} cannot start until ${pre.code} finishes`}</title></path>
                })}
              </svg>
              {rows.map((a, i) => {
                const s = at(a.planned_start), f = at(a.planned_finish)
                const left = x(s), w = Math.max(px, (f - s + 1) * px)
                const color = colourOf(a)
                return a.is_milestone ? (
                  <button key={a.id} type="button" onClick={() => onOpen(a)} aria-label={`Milestone ${a.name}, ${a.planned_finish}, ${a.state}`} title={`${a.name} - ${a.planned_finish}`}
                    className="absolute z-[8] size-4 rotate-45 border border-card" style={{ left: x(f) + px / 2 - 8, top: i * ROW + ROW / 2 - 8, background: color }} />
                ) : (
                  <button key={a.id} type="button" onClick={() => onOpen(a)} aria-label={`${a.name}, ${a.planned_start} to ${a.planned_finish}, ${a.actual_percent}% done, planned ${a.planned_percent}%, ${a.state}`}
                    title={`${a.name}\n${a.planned_start} to ${a.planned_finish}\nDone ${a.actual_percent}% - planned ${a.planned_percent}%`} className="absolute z-[8] h-[18px] overflow-hidden rounded text-left ring-1 ring-inset ring-foreground/20" style={{ left, width: w, top: i * ROW + 12, background: `color-mix(in srgb, ${color} 26%, transparent)` }}>
                    <span className="block h-full transition-[width,background-color] duration-300" style={{ width: `${Math.min(100, a.actual_percent)}%`, background: color }} />
                    {w > 46 && <span aria-hidden className="absolute inset-y-0 left-1.5 flex items-center text-[10px] font-semibold leading-none text-foreground [text-shadow:0_0_3px_var(--color-card)]">{Math.round(a.actual_percent)}%</span>}
                    <span aria-hidden className="absolute inset-y-0 w-px bg-foreground/60" style={{ left: `${Math.min(100, a.planned_percent)}%` }} />
                  </button>
                )
              })}
              {rows.map((a, i) => {
                if (a.is_milestone || a.status === 'Completed' || a.actual_percent >= 100 || !(a.forecast_finish && a.forecast_finish > a.planned_finish)) return null
                const left = x(at(a.planned_finish) + 1), w = x(at(a.forecast_finish) + 1) - left
                return <div key={a.id} aria-hidden title={`Forecast to finish ${a.forecast_finish}`} className="absolute z-[7] h-1.5 opacity-80" style={{ left, width: Math.max(4, w), top: i * ROW + 18, background: 'repeating-linear-gradient(90deg,var(--color-danger) 0 4px,transparent 4px 7px)' }} />
              })}
            </div>
          </div>
        </div>
      </div>
      <p className="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">The thin line across a bar is where the plan has it today. Arrows run from the activity that must finish to the one that waits on it. The red line is today.</p>
    </section>
  )
}

const Key = ({ color, label }: { color: string; label: string }) => <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm" style={{ background: color }} />{label}</span>
