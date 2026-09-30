import { Clock, Coffee, LogIn, LogOut } from 'lucide-react'
import { Button, Select, Skeleton } from '@/components/ui'
import { bookToJob, breakFor, clock, staffKeys, useClock, useMyJobs, useToday } from '@/api/staff'
import { useAction } from '@/lib/mutate'

const hm = (h: number | undefined) => {
  const m = Math.round((h ?? 0) * 60)
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

/** Clock in and out, take a break, say which site the hours belong to. */
export function ClockCard() {
  const q = useClock()
  const today = useToday()
  const jobs = useMyJobs()
  const c = q.data
  const refresh = { invalidate: [staffKeys.clock, staffKeys.today, staffKeys.dashboard] }
  const go = useAction((which: 'in' | 'out') => clock(which), { ...refresh, success: (r, w) => r.message || (w === 'in' ? 'Clocked in' : 'Clocked out') })
  const rest = useAction((which: 'start' | 'stop') => breakFor(which), { invalidate: [staffKeys.clock], success: (r, w) => r.message || (w === 'start' ? 'Break started' : 'Break over') })
  const book = useAction((id: number | null) => bookToJob(id), { invalidate: [staffKeys.today], success: 'Hours booked to that site' })

  if (q.isPending) return <Skeleton className="h-44 w-full rounded-xl" />
  const done = !!c?.clock_out
  const working = !!c?.clocked_in && !done
  const site = today.data?.clock.site
  const current = jobs.data?.find((j) => j.name === site)

  return (
    <section aria-label="Clock" className="rounded-xl border border-border bg-card p-5 shadow-card">
      <div className="flex flex-wrap items-center gap-4">
        <span className={`grid size-12 shrink-0 place-items-center rounded-full ${working ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground'}`}><Clock className="size-6" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-muted-foreground">{done ? 'Done for the day' : working ? (c?.is_on_break ? 'On a break' : 'Working') : c?.is_working_day === false ? 'Not a working day' : 'Not clocked in yet'}</p>
          <p className="tabular font-display text-2xl font-semibold">
            {working ? <>In since {c?.clock_in?.slice(0, 5)} <span className="text-base font-normal text-muted-foreground">({hm(c?.elapsed_hours)} worked)</span></> : done ? <>{c?.clock_in?.slice(0, 5)} to {c?.clock_out?.slice(0, 5)} <span className="text-base font-normal text-muted-foreground">({hm(c?.total_hours)})</span></> : '-'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!c?.clocked_in && <Button size="lg" loading={go.isPending} disabled={c?.is_working_day === false} onClick={() => go.mutate('in')}><LogIn /> Clock in</Button>}
          {working && (
            <>
              <Button variant="outline" loading={rest.isPending} onClick={() => rest.mutate(c?.is_on_break ? 'stop' : 'start')}><Coffee /> {c?.is_on_break ? 'End break' : 'Take a break'}</Button>
              <Button size="lg" variant="outline" loading={go.isPending} onClick={() => go.mutate('out')}><LogOut /> Clock out</Button>
            </>
          )}
        </div>
      </div>
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
