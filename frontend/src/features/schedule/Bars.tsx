import type { CurvePoint } from '@/api/schedule'

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
