import type { Activity, CurvePoint } from '@/api/schedule'
import { today } from '@/lib/format'

const STATE: Record<string, string> = { done: 'bg-success', late: 'bg-danger', behind: 'bg-warning', 'on track': 'bg-primary', 'not started': 'bg-subtle' }
const STATE_TEXT: Record<string, string> = { done: 'text-success', late: 'text-danger', behind: 'text-warning', 'on track': 'text-primary', 'not started': 'text-muted-foreground' }
const day = 86400000
const at = (iso: string) => new Date(iso).getTime()

/** Every activity as a bar across its planned dates, filled as far as it is done, its forecast finish drawn past it when it is slipping. */
export function Bars({ activities, onEdit, onProgress }: { activities: Activity[]; onEdit: (a: Activity) => void; onProgress: (a: Activity) => void }) {
  const dates = activities.flatMap((a) => [a.planned_start, a.planned_finish, a.forecast_finish]).filter(Boolean).sort()
  const t0 = at(dates[0])
  const t = at(today())
  const t1 = Math.max(at(dates[dates.length - 1]), t)
  const span = Math.max(1, (t1 - t0) / day + 1)
  const pos = (iso: string) => ((at(iso) - t0) / day / span) * 100
  const todayAt = pos(today())
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-card">
      <table aria-label="Programme" className="w-full border-collapse text-[13.5px]">
        <thead className="bg-surface text-left text-xs text-muted-foreground">
          <tr><th className="px-3 py-2">Code</th><th className="px-3 py-2">Activity</th><th className="px-3 py-2 text-right">Done</th><th className="min-w-[360px] px-3 py-2">{dates[0]} <span className="float-right">{new Date(t1).toISOString().slice(0, 10)}</span></th><th className="px-3 py-2">State</th><th /></tr>
        </thead>
        <tbody>
          {activities.map((a) => {
            const left = pos(a.planned_start)
            const width = Math.max(0.8, pos(a.planned_finish) - left + 100 / span)
            const slips = a.forecast_finish && a.forecast_finish > a.planned_finish
            return (
              <tr key={a.id} className="border-t border-border">
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{a.code}</td>
                <td className="min-w-52 px-3 py-2"><button type="button" className="text-left font-semibold text-primary underline-offset-2 hover:underline" onClick={() => onEdit(a)}>{a.name}</button><div className="text-[11px] text-muted-foreground">{a.planned_start} to {a.planned_finish}{a.depends_on && ` - after ${a.depends_on}`} - {a.progress_from}</div></td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular">{a.actual_percent}%<div className="text-[11px] text-muted-foreground">plan {a.planned_percent}%</div></td>
                <td className="relative px-3 py-2">
                  <div className="relative h-6">
                    <div className="absolute inset-y-0 w-px bg-danger/50" style={{ left: `${todayAt}%` }} aria-hidden />
                    <div className="absolute top-[5px] h-3.5 overflow-hidden rounded bg-border" style={{ left: `${left}%`, width: `${width}%` }}><div className={`h-full ${STATE[a.state] ?? 'bg-primary'}`} style={{ width: `${Math.min(100, a.actual_percent)}%` }} /></div>
                    {slips && <div title={`Forecast finish ${a.forecast_finish}`} className="absolute top-[9px] h-1.5 opacity-80" style={{ left: `${left + width}%`, width: `${Math.max(0.5, pos(a.forecast_finish) - left - width + 100 / span)}%`, background: 'repeating-linear-gradient(90deg,var(--color-danger) 0 4px,transparent 4px 7px)' }} />}
                  </div>
                </td>
                <td className={`whitespace-nowrap px-3 py-2 text-xs ${STATE_TEXT[a.state] ?? ''}`}>{a.state}{a.slip_days > 0 && <div className="text-[11px]">+{a.slip_days} days</div>}</td>
                <td className="px-3 py-2 text-right">{!a.work_order_line_id && <button type="button" className="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => onProgress(a)}>Progress</button>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Planned against actual, week by week. */
export function Curve({ curve }: { curve: CurvePoint[] }) {
  if (curve.length < 2) return null
  const W = 760, H = 180, pad = 28
  const x = (i: number) => pad + (i * (W - pad * 2)) / (curve.length - 1)
  const y = (p: number) => H - pad - (p * (H - pad * 2)) / 100
  const line = (key: 'planned' | 'actual') => curve.flatMap((c, i) => (c[key] === null || c[key] === undefined ? [] : [[x(i), y(c[key] as number)]])).map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  return (
    <section aria-label="Planned against actual" className="mt-5 rounded-xl border border-border bg-card p-4 shadow-card">
      <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">Planned against actual</h2><span className="text-xs text-muted-foreground">dashed planned - solid actual</span></div>
      <div className="overflow-x-auto"><svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[480px]" role="img" aria-label="S-curve of planned and actual progress">
        {[0, 25, 50, 75, 100].map((p) => <g key={p}><line x1={pad} x2={W - pad} y1={y(p)} y2={y(p)} stroke="currentColor" strokeOpacity=".08" /><text x="2" y={y(p) + 3} fontSize="9" fill="currentColor" fillOpacity=".5">{p}%</text></g>)}
        <path d={line('planned')} fill="none" stroke="currentColor" strokeOpacity=".45" strokeWidth="2" strokeDasharray="5 3" />
        <path d={line('actual')} fill="none" stroke="var(--color-primary)" strokeWidth="2.5" />
        <text x={pad} y={H - 6} fontSize="9" fill="currentColor" fillOpacity=".5">{curve[0].week}</text>
        <text x={W - pad} y={H - 6} fontSize="9" textAnchor="end" fill="currentColor" fillOpacity=".5">{curve[curve.length - 1].week}</text>
      </svg></div>
    </section>
  )
}
