import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui'
import { get } from '@/lib/api'

interface Holiday { date: string; name: string }

const useHolidays = (year: number) => useQuery({ queryKey: ['calendar', 'holidays', year], queryFn: () => get<Holiday[]>(`/api/calendar/holidays?year=${year}`), staleTime: 24 * 60 * 60_000 })

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const iso = (y: number, m: number, d: number) => `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`

export default function CalendarPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth())
  const q = useHolidays(year)
  const byDate = new Map((q.data ?? []).map((h) => [h.date, h.name]))
  const today = iso(now.getFullYear(), now.getMonth(), now.getDate())

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
      <PageHeader eyebrow="Command Center" title="Calendar" description="Public holidays in India, month by month." />
      <div className="mb-4 flex items-center gap-2">
        <Button variant="outline" size="sm" aria-label="Previous month" onClick={() => go(-1)}><ChevronLeft /></Button>
        <h2 className="min-w-44 text-center text-lg font-semibold">{new Date(year, month, 1).toLocaleString('en-IN', { month: 'long', year: 'numeric' })}</h2>
        <Button variant="outline" size="sm" aria-label="Next month" onClick={() => go(1)}><ChevronRight /></Button>
        <Button variant="outline" size="sm" onClick={() => { setYear(now.getFullYear()); setMonth(now.getMonth()) }}>Today</Button>
      </div>
      <div className="grid gap-5 lg:grid-cols-[1fr_18rem]">
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="grid grid-cols-7 border-b border-border bg-muted/40 text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {DAYS.map((d) => <div key={d} className="py-2">{d}</div>)}
          </div>
          <div className="grid grid-cols-7">
            {cells.map((day, i) => {
              const key = day ? iso(year, month, day) : ''
              const holiday = key ? byDate.get(key) : undefined
              const sunday = i % 7 === 6
              return (
                <div key={i} className={'min-h-20 border-b border-r border-border p-1.5 text-sm ' + (day ? '' : 'bg-muted/20 ') + (holiday ? 'bg-[var(--primary)]/10 ' : '')}>
                  {day && (
                    <>
                      <span className={'grid size-6 place-items-center rounded-full text-[13px] ' + (key === today ? 'bg-[var(--primary)] font-semibold text-white' : sunday ? 'text-danger' : '')}>{day}</span>
                      {holiday && <p className="mt-1 line-clamp-2 text-[11px] font-medium leading-tight">{holiday}</p>}
                    </>
                  )}
                </div>
              )
            })}
          </div>
        </div>
        <aside aria-label="Holidays this month" className="rounded-xl border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-semibold">Holidays in {new Date(year, month, 1).toLocaleString('en-IN', { month: 'long' })}</h3>
          {q.isError ? <p role="alert" className="text-[13px] text-danger">Could not load the holidays.</p> : inMonth.length === 0 ? <p className="text-[13px] text-muted-foreground">{q.isPending ? 'Loading…' : 'No public holidays this month.'}</p> : (
            <ul className="space-y-2">
              {inMonth.map((h) => (
                <li key={h.date} className="text-[13px]"><span className="font-medium">{new Date(h.date + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', weekday: 'short' })}</span><br /><span className="text-muted-foreground">{h.name}</span></li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </>
  )
}
