import { useEffect, useState } from 'react'
import { Coffee, LogIn, LogOut, MapPin } from 'lucide-react'
import { breakFor, clock, staffKeys, useClock, useToday } from '@/api/staff'
import { Skeleton } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { Sheet } from './ui'

const pad = (n: number) => String(n).padStart(2, '0')
/** Seconds as 7h 05m. */
const hm = (seconds: number) => `${Math.floor(Math.max(0, seconds) / 3600)}h ${pad(Math.floor((Math.max(0, seconds) % 3600) / 60))}m`

const ghost = 'h-12 flex-1 rounded-full border px-4 text-[15px] font-semibold active:opacity-80 disabled:opacity-50'

/**
 * Clock in and out from the phone, for staff. The same clock as the website's (api/staff.ts): the phone's position goes
 * with the clock-in, and the server matches it to a site or the office, so the day is saved as site, office or field and
 * not as typed in by hand. Without the location permission the server decides (Attendance settings, "Require location",
 * on unless the company switched it off): it turns the clock-in away saying so, which the person sees as the message of
 * the failed press, or accepts it as manual.
 */
export function ClockPanel() {
  const q = useClock()
  const today = useToday()
  const refresh = { invalidate: [staffKeys.clock, staffKeys.today, staffKeys.dashboard] }
  const go = useAction((which: 'in' | 'out') => clock(which), { ...refresh, success: (r, w) => r.message || (w === 'in' ? 'Clocked in' : 'Clocked out') })
  const rest = useAction((which: 'start' | 'stop') => breakFor(which), { invalidate: [staffKeys.clock], success: (r, w) => r.message || (w === 'start' ? 'Break started' : 'Break over') })

  // The count moves a little at a time while somebody is working.
  const [, tick] = useState(0)
  const live = !!q.data?.clocked_in && !q.data?.clock_out
  useEffect(() => {
    if (!live) return
    const id = window.setInterval(() => tick((n) => n + 1), 30_000)
    return () => window.clearInterval(id)
  }, [live])

  if (q.isPending) return <Skeleton className="mt-3.5 h-[116px] w-full rounded-2xl" />
  if (q.isError) return null

  const c = q.data
  const done = !!c?.clock_out
  const working = !!c?.clocked_in && !done
  const onBreak = !!c?.is_on_break
  const sinceRead = working && !onBreak ? Math.max(0, (Date.now() - q.dataUpdatedAt) / 1000) : 0
  const worked = done ? (c?.total_hours ?? 0) * 3600 : (c?.elapsed_seconds ?? 0) + sinceRead
  const site = today.data?.clock.site
  const note = done
    ? `${c?.clock_in?.slice(0, 5)} to ${c?.clock_out?.slice(0, 5)} · ${hm(worked)} worked`
    : onBreak ? 'On a break'
    : working ? `Working since ${c?.clock_in?.slice(0, 5)} · ${hm(worked)}`
    : c?.holiday ? `Holiday · ${c.holiday}` : c?.is_working_day === false ? 'Not a working day' : 'Not clocked in yet'

  return (
    <Sheet className="mt-3.5">
      <div className="flex items-center gap-3">
        <span className={cn('grid size-11 shrink-0 place-items-center rounded-[14px]', working ? 'bg-success/15 text-success' : done ? 'bg-muted text-muted-foreground' : 'bg-primary/15 text-primary')}>
          {done ? <LogOut className="size-5" /> : <LogIn className="size-5" />}
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <b className="block text-[15px] font-semibold">{done ? 'Done for the day' : working ? (onBreak ? 'On a break' : 'Clocked in') : 'Clock in'}</b>
          <span className="block truncate text-[12.5px] text-muted-foreground">{note}</span>
        </div>
      </div>
      {(site || !done) && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground"><MapPin className="size-3.5 shrink-0" /><span className="truncate">{site || 'Your position is saved with the clock-in'}</span></p>
      )}
      {!done && (
        <div className="mt-3 flex gap-2">
          {!c?.clocked_in && (
            <button type="button" disabled={go.isPending} onClick={() => go.mutate('in')} className="h-12 flex-1 rounded-full bg-[image:var(--app-grad)] text-[15px] font-semibold text-white active:opacity-90 disabled:opacity-60">
              {go.isPending ? 'Clocking in…' : 'Clock in'}
            </button>
          )}
          {working && (
            <>
              <button type="button" disabled={rest.isPending} onClick={() => rest.mutate(onBreak ? 'stop' : 'start')} className={cn(ghost, 'border-warning/60 text-warning')}><Coffee className="mr-1.5 inline size-4" />{onBreak ? 'End break' : 'Break'}</button>
              <button type="button" disabled={go.isPending} onClick={() => go.mutate('out')} className={cn(ghost, 'border-danger/60 text-danger')}><LogOut className="mr-1.5 inline size-4" />Clock out</button>
            </>
          )}
        </div>
      )}
    </Sheet>
  )
}
