import type { Activity, CurvePoint } from '@/api/schedule'
import { ProgressRing } from './ProgressRing'
import { ProgressControl } from './ProgressControl'

const RING: Record<string, string> = { done: 'stroke-success', late: 'stroke-danger', behind: 'stroke-warning', 'on track': 'stroke-primary', 'not started': 'stroke-subtle' }
const STATE_TEXT: Record<string, string> = { done: 'text-success', late: 'text-danger', behind: 'text-warning', 'on track': 'text-primary', 'not started': 'text-muted-foreground' }

/** Every activity with a ring showing how far along it is (a dot where the plan has it), its dates, state and what it slips by. */
export function Bars({ activities, onEdit }: { activities: Activity[]; onEdit: (a: Activity) => void }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-card">
      <table aria-label="Programme" className="w-full border-collapse text-[13.5px]">
        <thead className="bg-surface text-left text-xs text-muted-foreground">
          <tr><th className="px-3 py-2">Code</th><th className="px-3 py-2">Activity</th><th className="px-3 py-2">Done</th><th className="px-3 py-2">Plan</th><th className="px-3 py-2">Forecast finish</th><th className="px-3 py-2">State</th><th /></tr>
        </thead>
        <tbody>
          {activities.map((a) => (
            <tr key={a.id} className="border-t border-border">
              <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{a.code}</td>
              <td className="min-w-52 px-3 py-2"><button type="button" className="text-left font-semibold text-primary underline-offset-2 hover:underline" onClick={() => onEdit(a)}>{a.name}</button><div className="text-[11px] text-muted-foreground">{a.planned_start} to {a.planned_finish}{a.depends_on && ` - after ${a.depends_on}`} - {a.progress_from}</div></td>
              <td className="px-3 py-1.5"><ProgressRing percent={a.actual_percent} planned={a.planned_percent} tone={RING[a.state]} label={`${a.name} done`} /></td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground tabular">{a.planned_percent}%</td>
              <td className="whitespace-nowrap px-3 py-2 text-xs tabular">{a.forecast_finish || '-'}</td>
              <td className={`whitespace-nowrap px-3 py-2 text-xs ${STATE_TEXT[a.state] ?? ''}`}>{a.state}{a.slip_days > 0 && <div className="text-[11px]">+{a.slip_days} days</div>}</td>
              <td className="px-3 py-2 text-right">{!a.work_order_line_id && <ProgressControl id={a.id} percent={a.actual_percent} compact />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Planned against actual, week by week. */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** "Oct 2026" under the curve, where each month begins (the year in full, so it is never read as a day). */
const monthLabel = (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`

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
        {curve.map((c, i) => (i === 0 || c.week.slice(0, 7) !== curve[i - 1].week.slice(0, 7)) && (
          <g key={c.week}>
            <line x1={x(i)} x2={x(i)} y1={pad} y2={H - pad} stroke="currentColor" strokeOpacity=".06" />
            <text x={x(i)} y={H - 8} fontSize="10" fill="currentColor" fillOpacity=".7" textAnchor={i === 0 ? 'start' : 'middle'}>{monthLabel(c.week)}</text>
          </g>
        ))}
      </svg></div>
    </section>
  )
}
