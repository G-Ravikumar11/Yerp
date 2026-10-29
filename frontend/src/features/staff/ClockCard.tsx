import { useEffect, useState } from 'react'
import { Coffee, LogIn, LogOut, MapPin } from 'lucide-react'
import { Button, Select, Skeleton } from '@/components/ui'
import { bookToJob, breakFor, clock, staffKeys, useClock, useMyJobs, useToday } from '@/api/staff'
import { useAction } from '@/lib/mutate'

/** 3725 seconds -> "1h 02m". */
const hm = (seconds: number) => {
  const m = Math.floor(Math.max(0, seconds) / 60)
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}
const pad = (n: number) => String(n).padStart(2, '0')
const clockTime = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

/** Re-draws every second, so the wall clock and the counters move. */
function useSecondTicks(running: boolean) {
  const [, tick] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [running])
}

// The dial: a 240 degree arc, open at the bottom, filling clockwise from the lower left to the lower right.
const CX = 120
const CY = 120
const R = 92
const START = 150
const SWEEP = 240
const point = (deg: number, r = R) => ({ x: CX + r * Math.cos((deg * Math.PI) / 180), y: CY + r * Math.sin((deg * Math.PI) / 180) })
const arc = (from: number, to: number) => {
  const a = point(from)
  const b = point(to)
  return `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} A ${R} ${R} 0 ${to - from > 180 ? 1 : 0} 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`
}

/** Hours worked against the day's target, drawn like a speedometer. */
function Gauge({ worked, target, tone, label, note }: { worked: number /* seconds */; target: number /* hours */; tone: 'idle' | 'working' | 'break' | 'done'; label: string; note: string }) {
  const fraction = target > 0 ? Math.min(1, worked / (target * 3600)) : 0
  const end = START + SWEEP * fraction
  const tip = point(end)
  const stroke = { idle: 'stroke-muted-foreground/40', working: 'stroke-primary', break: 'stroke-warning', done: 'stroke-success' }[tone]
  const fill = { idle: 'fill-muted-foreground/60', working: 'fill-primary', break: 'fill-warning', done: 'fill-success' }[tone]
  const needleFrom = point(end, R - 46)
  const needleTo = point(end, R - 20)
  const ticks = Array.from({ length: 13 }, (_, i) => START + (SWEEP * i) / 12)
  const seconds = Math.floor(worked) % 60
  return (
    <div className="relative mx-auto w-full max-w-64" role="img" aria-label={label}>
      <svg viewBox="0 0 240 200" className="w-full" aria-hidden="true">
        <path d={arc(START, START + SWEEP)} fill="none" strokeWidth={12} strokeLinecap="round" className="stroke-border" />
        {fraction > 0.002 && <path d={arc(START, end)} fill="none" strokeWidth={12} strokeLinecap="round" className={`${stroke} transition-[stroke] duration-300`} />}
        {ticks.map((deg, i) => {
          const a = point(deg, R - 17)
          const b = point(deg, R - (i % 3 === 0 ? 25 : 21))
          return <line key={deg} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeWidth={i % 3 === 0 ? 2 : 1.25} strokeLinecap="round" className="stroke-muted-foreground/35" />
        })}
        <line x1={needleFrom.x} y1={needleFrom.y} x2={needleTo.x} y2={needleTo.y} strokeWidth={3} strokeLinecap="round" className="stroke-foreground/80" />
        <circle cx={tip.x} cy={tip.y} r={8.5} className="fill-card" />
        <circle cx={tip.x} cy={tip.y} r={5.5} className={fill} />
      </svg>
      <div className="pointer-events-none absolute inset-x-0 top-[34%] text-center">
        <p className="tabular font-display text-3xl font-semibold leading-none" role="timer" aria-label="Time worked">
          {hm(worked)}
          {tone === 'working' && <span className="ml-1 text-sm font-normal text-muted-foreground">{pad(seconds)}s</span>}
        </p>
        <p className="mt-1.5 text-xs text-muted-foreground">of {hm(target * 3600)}</p>
      </div>
      <p className="pointer-events-none absolute inset-x-0 bottom-[8%] text-center text-sm font-medium">{note}</p>
    </div>
  )
}

/** The wall clock, a dial of hours worked today, and the buttons: clock in and out, take a break, say which site the hours belong to. */
export function ClockCard() {
  const q = useClock()
  const today = useToday()
  const jobs = useMyJobs()
  const c = q.data
  const refresh = { invalidate: [staffKeys.clock, staffKeys.today, staffKeys.dashboard] }
  const go = useAction((which: 'in' | 'out') => clock(which), { ...refresh, success: (r, w) => r.message || (w === 'in' ? 'Clocked in' : 'Clocked out') })
  const rest = useAction((which: 'start' | 'stop') => breakFor(which), { invalidate: [staffKeys.clock], success: (r, w) => r.message || (w === 'start' ? 'Break started' : 'Break over') })
  const book = useAction((id: number | null) => bookToJob(id), { invalidate: [staffKeys.today], success: 'Hours booked to that site' })

  // Called before the early return below: hooks must run in the same order on every render. The wall clock always
  // moves; nothing else does until somebody is working.
  useSecondTicks(true)
  if (q.isPending) return <Skeleton className="h-64 w-full rounded-xl" />

  const now = new Date()
  const done = !!c?.clock_out
  const working = !!c?.clocked_in && !done
  const onBreak = !!c?.is_on_break
  // The server's figure when it was read, plus the seconds since. It stands still on a break, which has its own count.
  const sinceRead = working ? Math.max(0, (Date.now() - q.dataUpdatedAt) / 1000) : 0
  const worked = done ? (c?.total_hours ?? 0) * 3600 : (c?.elapsed_seconds ?? 0) + (onBreak ? 0 : sinceRead)
  const breakNow = (c?.break_elapsed_seconds ?? 0) + (onBreak ? sinceRead : 0)
  const breakToday = (c?.break_minutes ?? 0) * 60 + (onBreak ? breakNow : 0)
  const target = c?.target_hours ?? 8
  const tone = done ? 'done' : onBreak ? 'break' : working ? 'working' : 'idle'
  const note = done ? 'Done for the day' : onBreak ? `On a break · ${hm(breakNow)}` : working ? `Working · in since ${c?.clock_in?.slice(0, 5)}` : c?.holiday ? `Holiday · ${c.holiday}` : c?.is_working_day === false ? 'Not a working day' : 'Not started'
  const site = today.data?.clock.site
  const current = jobs.data?.find((j) => j.name === site)

  return (
    <section aria-label="Clock" className="rounded-xl border border-border bg-card p-5 shadow-card sm:p-6">
      <div className="grid items-center gap-6 lg:grid-cols-[1fr_auto_1fr]">
        <div className="text-center lg:text-left">
          <p className="tabular font-display text-5xl font-semibold leading-none tracking-tight sm:text-6xl" aria-label="The time now">{clockTime(now)}</p>
          <p className="mt-2 text-sm text-muted-foreground">{now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
          <p className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground"><MapPin className="size-3.5" /> {site || 'No site chosen yet'}</p>
        </div>

        <Gauge worked={worked} target={target} tone={tone} label={`${hm(worked)} worked of ${hm(target * 3600)}`} note={note} />

        <div className="flex flex-wrap justify-center gap-2 lg:justify-end">
          {!c?.clocked_in && <Button size="lg" loading={go.isPending} onClick={() => go.mutate('in')}><LogIn /> Clock in</Button>}
          {working && (
            <>
              <Button size="lg" variant="outline" className="border-warning/60 text-warning hover:bg-warning/10" loading={rest.isPending} onClick={() => rest.mutate(onBreak ? 'stop' : 'start')}><Coffee /> {onBreak ? 'End break' : 'Take a break'}</Button>
              <Button size="lg" variant="outline" className="border-danger/60 text-danger hover:bg-danger/10" loading={go.isPending} onClick={() => go.mutate('out')}><LogOut /> Clock out</Button>
            </>
          )}
          {done && <p className="text-sm text-muted-foreground">{c?.clock_in?.slice(0, 5)} to {c?.clock_out?.slice(0, 5)} · {hm((c?.total_hours ?? 0) * 3600)} worked</p>}
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-3 border-t border-border pt-4 text-center sm:max-w-sm">
        <div><dt className="text-xs text-muted-foreground">Worked today</dt><dd className="tabular text-lg font-semibold">{hm(worked)}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Break time</dt><dd className="tabular text-lg font-semibold">{hm(breakToday)}</dd></div>
      </dl>

      {c?.clocked_in && (jobs.data?.length ?? 0) > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
          <label htmlFor="book-job" className="text-sm font-medium">Today's hours are on</label>
          <div className="min-w-56">
            <Select id="book-job" value={current?.id ?? ''} placeholder="Choose a site" disabled={book.isPending} options={(jobs.data ?? []).map((j) => ({ value: j.id, label: `${j.number ? j.number + ' - ' : ''}${j.name}` }))} onChange={(e) => e.target.value && book.mutate(Number(e.target.value))} />
          </div>
        </div>
      )}
    </section>
  )
}
