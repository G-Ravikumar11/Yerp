import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, ConfirmDialog, Field, Input, Modal } from '@/components/ui'
import { del, get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'

/** `custom` ones are the days this business has marked off itself; the rest are India's public holidays. */
interface Holiday { date: string; name: string; custom: boolean; id?: number }

const useHolidays = (year: number) => useQuery({ queryKey: ['calendar', 'holidays', year], queryFn: () => get<Holiday[]>(`/api/calendar/holidays?year=${year}`), staleTime: 60_000 })

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const iso = (y: number, m: number, d: number) => `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`

export default function CalendarPage() {
  const { isOwner } = useSession()
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth())
  const q = useHolidays(year)
  const byDate = new Map<string, Holiday[]>()
  for (const h of q.data ?? []) byDate.set(h.date, [...(byDate.get(h.date) ?? []), h])
  const today = iso(now.getFullYear(), now.getMonth(), now.getDate())
  // The day being marked, when the dialog is open ('' is a dialog with no day chosen yet).
  const [marking, setMarking] = useState<string | null>(null)
  const [removing, setRemoving] = useState<Holiday | null>(null)
  const remove = useAction((h: Holiday) => del<{ message: string }>(`/api/calendar/holidays/${h.id}`), { invalidate: [['calendar']], success: 'Holiday removed' })

  const go = (by: number) => {
    const d = new Date(year, month + by, 1)
    setYear(d.getFullYear())
    setMonth(d.getMonth())
  }
  const lead = (new Date(year, month, 1).getDay() + 6) % 7 // Monday first
  const length = new Date(year, month + 1, 0).getDate()
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length }, (_, i) => i + 1)]
  while (cells.length % 7) cells.push(null)
  const inMonth = (q.data ?? []).filter((h) => h.date.startsWith(`${year}-${String(month + 1).padStart(2, '0')}`))

  return (
    <>
      <PageHeader eyebrow="Command Center" title="Calendar" description="Public holidays in India, and the days off this business has added. Every employee has the days you add off."
        actions={isOwner && <Button onClick={() => setMarking(iso(year, month, now.getMonth() === month && now.getFullYear() === year ? now.getDate() : 1))}><Plus /> Add holiday</Button>} />
      <div className="mb-4 flex items-center gap-2">
        <Button variant="outline" size="sm" aria-label="Previous month" onClick={() => go(-1)}><ChevronLeft /></Button>
        <h2 className="min-w-44 text-center text-lg font-semibold">{new Date(year, month, 1).toLocaleString('en-IN', { month: 'long', year: 'numeric' })}</h2>
        <Button variant="outline" size="sm" aria-label="Next month" onClick={() => go(1)}><ChevronRight /></Button>
        <Button variant="outline" size="sm" onClick={() => { setYear(now.getFullYear()); setMonth(now.getMonth()) }}>Today</Button>
      </div>
      <div className="grid gap-5 lg:grid-cols-[1fr_18rem]">
        <div>
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="grid grid-cols-7 border-b border-border bg-muted/40 text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {DAYS.map((d) => <div key={d} className="py-2">{d}</div>)}
            </div>
            <div className="grid grid-cols-7">
              {cells.map((day, i) => {
                const key = day ? iso(year, month, day) : ''
                const here = key ? byDate.get(key) ?? [] : []
                const own = here.filter((h) => h.custom)
                const sunday = i % 7 === 6
                const body = day && (
                  <>
                    <span className={'grid size-6 place-items-center rounded-full text-[13px] ' + (key === today ? 'bg-[var(--primary)] font-semibold text-white' : sunday ? 'text-danger' : '')}>{day}</span>
                    {here.map((h) => <p key={h.id ?? h.name} className={'mt-1 line-clamp-2 text-[11px] font-medium leading-tight ' + (h.custom ? 'text-amber-700 dark:text-amber-400' : '')}>{h.name}</p>)}
                  </>
                )
                const tint = (day ? '' : 'bg-muted/20 ') + (own.length ? 'bg-amber-500/15 ' : here.length ? 'bg-[var(--primary)]/10 ' : '')
                const cell = 'min-h-20 border-b border-r border-border p-1.5 text-left align-top text-sm '
                // The Master can mark a day by choosing it.
                return isOwner && day
                  ? <button type="button" key={i} aria-label={`Mark ${key} as a holiday`} onClick={() => setMarking(key)} className={cell + tint + 'hover:bg-muted/60'}>{body}</button>
                  : <div key={i} className={cell + tint}>{body}</div>
              })}
            </div>
          </div>
          <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-[var(--primary)]/25" /> Public holiday</span>
            <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-amber-500/40" /> Added by this business</span>
            {isOwner && <span>Choose a day to add a holiday.</span>}
          </p>
        </div>
        <aside aria-label="Holidays this month" className="rounded-xl border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-semibold">Holidays in {new Date(year, month, 1).toLocaleString('en-IN', { month: 'long' })}</h3>
          {q.isError ? <p role="alert" className="text-[13px] text-danger">Could not load the holidays.</p> : inMonth.length === 0 ? <p className="text-[13px] text-muted-foreground">{q.isPending ? 'Loading…' : 'No holidays this month.'}</p> : (
            <ul className="space-y-2">
              {inMonth.map((h) => (
                <li key={`${h.date}-${h.id ?? h.name}`} className="flex items-start justify-between gap-2 text-[13px]">
                  <div>
                    <span className="font-medium">{new Date(h.date + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', weekday: 'short' })}</span><br />
                    <span className="text-muted-foreground">{h.name}</span>
                    {h.custom && <span className="ml-1.5 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400">Added</span>}
                  </div>
                  {h.custom && isOwner && <Button size="sm" variant="ghost" aria-label={`Remove ${h.name}`} onClick={() => setRemoving(h)}><Trash2 /></Button>}
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
      <MarkHoliday key={marking ?? 'closed'} date={marking} onClose={() => setMarking(null)} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Remove ${removing?.name ?? 'this holiday'}?`} description="The day goes back to being an ordinary day for everybody: it counts as a working day again." confirmLabel="Remove it" tone="danger"
        onConfirm={() => { if (removing) remove.mutate(removing); setRemoving(null) }} />
    </>
  )
}

/** Marks a day, or a run of days, as holidays for the whole business. */
function MarkHoliday({ date, onClose }: { date: string | null; onClose: () => void }) {
  const [day, setDay] = useState(date ?? '')
  const [last, setLast] = useState('')     // empty: just the one day
  const [name, setName] = useState('')
  const end = last || day
  const backwards = !!day && !!end && end < day
  const days = day && end && !backwards ? Math.round((new Date(end + 'T00:00').getTime() - new Date(day + 'T00:00').getTime()) / 86_400_000) + 1 : 0
  const save = useAction(() => post<{ added: number; skipped: number }>('/api/calendar/holidays', { date: day, end_date: last && last !== day ? last : undefined, name: name.trim() }), {
    invalidate: [['calendar']],
    success: (r) => (r.added === 1 ? 'Holiday added' : `${r.added} holidays added`) + (r.skipped ? ` (${r.skipped} already marked)` : ''),
    onSuccess: onClose,
  })
  return (
    <Modal open={date !== null} onOpenChange={(o) => !o && onClose()} title="Add holidays" description="Everybody in the business has these days off. They are not counted as working days, and nobody is marked absent on them.">
      <form onSubmit={(e) => { e.preventDefault(); if (days > 0 && name.trim()) save.mutate() }}>
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="From" htmlFor="hd-date"><Input id="hd-date" type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
            <Field label="To" htmlFor="hd-last" hint="Leave empty for one day."><Input id="hd-last" type="date" min={day || undefined} value={last} onChange={(e) => setLast(e.target.value)} /></Field>
          </div>
          <Field label="Name" htmlFor="hd-name"><Input id="hd-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Site shutdown, Founders' Day..." autoFocus /></Field>
          {days > 0 && <p className="text-[13px] text-muted-foreground">{days === 1 ? 'One day will be marked.' : `${days} days will be marked, ${new Date(day + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} to ${new Date(end + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}.`}</p>}
        </div>
        <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
          {(backwards || save.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{backwards ? 'The last day cannot be before the first.' : save.error?.message}</p>}
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={days <= 0 || !name.trim()}>{days > 1 ? `Add ${days} holidays` : 'Add holiday'}</Button>
        </div>
      </form>
    </Modal>
  )
}
