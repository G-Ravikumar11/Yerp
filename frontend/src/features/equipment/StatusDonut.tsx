import { Tooltip } from '@/components/ui'
import { STATUS_LABEL } from '@/api/plant'
import { cn } from '@/lib/utils'

/**
 * The machines by status, as a ring with the total in its middle and a legend beside it. The statuses are the register's
 * own (Available, Deployed, Under repair, Breakdown, Returned); "Available" is what the dashboard counts as idle.
 * Colours were checked for both themes, including colour-blind readers; every slice is also named in the legend.
 */
const KNOWN: { status: string; label: string; stroke: string; swatch: string; always: boolean }[] = [
  { status: 'Available', label: 'Available / idle', stroke: 'stroke-[#2563eb] dark:stroke-[#3b82f6]', swatch: 'bg-[#2563eb] dark:bg-[#3b82f6]', always: true },
  { status: 'Deployed', label: 'Working', stroke: 'stroke-[#15803d] dark:stroke-[#3d9468]', swatch: 'bg-[#15803d] dark:bg-[#3d9468]', always: true },
  { status: 'Under repair', label: 'Under maintenance', stroke: 'stroke-[#a21caf] dark:stroke-[#b04ac0]', swatch: 'bg-[#a21caf] dark:bg-[#b04ac0]', always: true },
  { status: 'Breakdown', label: 'Breakdown', stroke: 'stroke-[#dc2626] dark:stroke-[#dc5252]', swatch: 'bg-[#dc2626] dark:bg-[#dc5252]', always: true },
  { status: 'Returned', label: 'Returned', stroke: 'stroke-subtle', swatch: 'bg-subtle', always: false },
]
const OTHER = { stroke: 'stroke-subtle', swatch: 'bg-subtle' }

const SIZE = 148
const R = 58
const WIDTH = 18
const GAP = 2 // the card shows through between slices
const C = 2 * Math.PI * R

const pct = (n: number, total: number) => {
  if (!total || !n) return '0%'
  const p = (n / total) * 100
  return p < 1 ? '<1%' : `${Math.round(p)}%`
}
const plural = (n: number) => `${n} machine${n === 1 ? '' : 's'}`

export function StatusDonut({ distribution, onPick }: { distribution: { status: string; count: number }[]; onPick: (status: string) => void }) {
  const counts = new Map<string, number>()
  for (const d of distribution ?? []) counts.set(d.status || 'Available', (counts.get(d.status || 'Available') ?? 0) + (Number(d.count) || 0))
  // The four working statuses always, even at zero; Returned and anything else only when there are some.
  const rows = [
    ...KNOWN.filter((k) => k.always || (counts.get(k.status) ?? 0) > 0).map((k) => ({ ...k, count: counts.get(k.status) ?? 0 })),
    ...[...counts.entries()].filter(([s, n]) => n > 0 && !KNOWN.some((k) => k.status === s)).map(([s, n]) => ({ status: s, label: STATUS_LABEL[s] ?? s, ...OTHER, always: false, count: n })),
  ]
  const total = rows.reduce((n, r) => n + r.count, 0)
  const shown = rows.filter((r) => r.count > 0)
  const gap = shown.length > 1 ? GAP : 0
  let start = 0
  const slices = shown.map((r) => {
    const len = (r.count / total) * C
    const s = { ...r, dash: Math.max(len - gap, 0.5), offset: -start }
    start += len
    return s
  })
  const tip = (r: { label: string; count: number }) => `${r.label}: ${plural(r.count)} (${pct(r.count, total)})`

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center">
      <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} className="-rotate-90" aria-hidden>
          <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" className="stroke-muted" strokeWidth={WIDTH} />
          {slices.map((s) => (
            <Tooltip key={s.status} content={tip(s)} side="top">
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={R}
                fill="none"
                strokeWidth={WIDTH}
                strokeDasharray={`${s.dash} ${C - s.dash}`}
                strokeDashoffset={s.offset}
                className={cn(s.stroke, 'cursor-pointer transition-[stroke-width] duration-150 hover:[stroke-width:22px]')}
                onClick={() => onPick(s.status)}
              />
            </Tooltip>
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
          <span className="text-2xl font-semibold leading-none tabular">{total}</span>
          <span className="mt-1 text-[11px] text-muted-foreground">machines</span>
        </div>
      </div>
      <ul className="grid w-full min-w-0 gap-0.5" aria-label="Equipment by status">
        {rows.map((r) => (
          <li key={r.status}>
            <Tooltip content={tip(r)} side="top">
              <button
                type="button"
                onClick={() => onPick(r.status)}
                aria-label={`${tip(r)}. Open these in the register.`}
                className="grid w-full grid-cols-[0.625rem_1fr_auto_2.75rem] items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-primary"
              >
                <span className={cn('size-2.5 rounded-sm', r.swatch)} aria-hidden />
                <span className="truncate">{r.label}</span>
                <span className="text-right font-medium tabular">{r.count}</span>
                <span className="text-right text-muted-foreground tabular">{pct(r.count, total)}</span>
              </button>
            </Tooltip>
          </li>
        ))}
      </ul>
    </div>
  )
}
