import { cn } from '@/lib/utils'

/** How far along something is, as a ring with its percentage in the middle; a tick marks where the plan has it. */
export function ProgressRing({ percent, planned, size = 44, tone, label }: { percent: number; planned?: number; size?: number; tone?: string; label?: string }) {
  const done = Math.max(0, Math.min(100, percent))
  const stroke = Math.max(4, Math.round(size / 9))
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const tick = planned !== undefined && planned > 0 && planned < 100 ? (planned / 100) * 2 * Math.PI - Math.PI / 2 : null
  return (
    <div role="progressbar" aria-valuenow={Math.round(done)} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? 'Work done'} className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeOpacity=".15" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - done / 100)} className={cn('transition-[stroke-dashoffset] duration-500 ease-out', tone ?? 'stroke-primary')} />
      </svg>
      {tick !== null && <span title={`Plan: ${planned}%`} aria-hidden className="absolute size-1.5 rounded-full bg-foreground/70" style={{ left: size / 2 + r * Math.cos(tick) - 3, top: size / 2 + r * Math.sin(tick) - 3 }} />}
      <span className="absolute text-[11px] font-semibold tabular">{Math.round(done)}%</span>
    </div>
  )
}
