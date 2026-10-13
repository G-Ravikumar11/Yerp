import { cn } from '@/lib/utils'

/**
 * How far along something is, as a bar with its percentage; a tick shows where the plan says it should be.
 * `thin` is the very small one, for lists of many activities.
 */
export function ProgressBar({ percent, planned, tone, label, className, thin }: { percent: number; planned?: number; tone?: string; label?: string; className?: string; thin?: boolean }) {
  const done = Math.max(0, Math.min(100, percent))
  return (
    <div className={cn('flex items-center gap-1.5', className)}>
      <div
        role="progressbar"
        aria-valuenow={Math.round(done)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? 'Work done'}
        className={cn('relative min-w-12 flex-1 overflow-hidden rounded-full bg-border', thin ? 'h-1' : 'h-1.5')}
      >
        <div className={cn('h-full rounded-full transition-[width] duration-500 ease-out', tone ?? 'bg-primary')} style={{ width: `${done}%` }} />
        {planned !== undefined && planned > 0 && planned < 100 && <div title={`Plan: ${planned}%`} className="absolute inset-y-0 w-px bg-foreground/60" style={{ left: `${planned}%` }} aria-hidden />}
      </div>
      <span className={cn('shrink-0 text-right font-semibold tabular', thin ? 'w-8 text-[10px]' : 'w-10 text-[11px]')}>{Math.round(done * 10) / 10}%</span>
    </div>
  )
}
